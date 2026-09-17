import asyncio
import json
import stat
from pathlib import Path
from typing import Any, cast

import pytest
from gql.transport.exceptions import TransportQueryError, TransportServerError
from monarchmoney import MonarchMoney
from monarchmoney.monarchmoney import RequireMFAException

import auth


class FakeMonarch:
    """Stands in for MonarchMoney. Tokens in `valid` pass the `me` check."""

    valid: set[str] = set()
    requires_mfa = False
    logins: list[dict[str, Any]] = []
    mfa_codes: list[str] = []

    def __init__(self, token: str | None = None) -> None:
        self.token = token

    async def gql_call(self, operation: str, graphql_query: object, variables: dict[str, Any]) -> Any:
        assert operation == "Common_GetMe"
        if self.token == "server-error":
            raise TransportServerError("500", 500)
        if self.token not in self.valid:
            raise TransportServerError("401, message='Unauthorized'", 401)
        return {"me": {"id": "u1"}}

    async def login(self, email: str, password: str, **kwargs: Any) -> None:
        await asyncio.sleep(0)  # let concurrent renewals interleave
        self.logins.append({"email": email, "password": password, **kwargs})
        if self.requires_mfa and not kwargs["mfa_secret_key"]:
            raise RequireMFAException("Multi-Factor Auth Required")
        self.token = f"fresh-{len(self.logins)}"
        self.valid.add(self.token)

    async def multi_factor_authenticate(self, email: str, password: str, code: str) -> None:
        self.mfa_codes.append(code)
        self.token = "fresh-mfa"
        self.valid.add(self.token)


@pytest.fixture(autouse=True)
def fake_monarch(monkeypatch: pytest.MonkeyPatch) -> type[FakeMonarch]:
    monkeypatch.setattr(FakeMonarch, "valid", {"good"})
    monkeypatch.setattr(FakeMonarch, "requires_mfa", False)
    monkeypatch.setattr(FakeMonarch, "logins", [])
    monkeypatch.setattr(FakeMonarch, "mfa_codes", [])
    monkeypatch.setattr(auth, "MonarchMoney", FakeMonarch)
    return FakeMonarch


@pytest.fixture
def session(tmp_path: Path) -> Path:
    return tmp_path / "cfg" / "session.json"


def env(session: Path, **values: str) -> dict[str, str]:
    return {"MONARCH_SESSION_FILE": str(session), **values}


CREDS = {"MONARCH_EMAIL": "e@x", "MONARCH_PASSWORD": "pw"}


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# --- session file ---------------------------------------------------------------

def test_session_file_default_and_override(tmp_path: Path) -> None:
    assert auth.session_file({}) == auth.DEFAULT_SESSION_FILE
    assert auth.session_file({"MONARCH_SESSION_FILE": str(tmp_path / "s.json")}) == tmp_path / "s.json"


def test_save_token_is_private(session: Path) -> None:
    auth.save_token(session, "abc")
    assert json.loads(session.read_text()) == {"token": "abc"}
    assert mode(session) == 0o600
    assert mode(session.parent) == 0o700
    assert list(session.parent.iterdir()) == [session]


def test_save_token_tightens_existing_file(session: Path) -> None:
    session.parent.mkdir(parents=True)
    session.write_text("{}")
    session.chmod(0o644)
    session.with_suffix(".tmp").write_text("")
    session.with_suffix(".tmp").chmod(0o644)
    auth.save_token(session, "abc")
    assert mode(session) == 0o600
    assert auth.load_token(session) == "abc"


@pytest.mark.parametrize("content", ["not json", "[]", '{"token": ""}', '{"token": 5}', "{}"])
def test_load_token_rejects_bad_content(session: Path, content: str) -> None:
    session.parent.mkdir(parents=True)
    session.write_text(content)
    assert auth.load_token(session) is None


def test_load_token_missing(session: Path) -> None:
    assert auth.load_token(session) is None


def test_delete_token(session: Path) -> None:
    auth.save_token(session, "abc")
    assert auth.delete_token(session) is True
    assert auth.delete_token(session) is False


def test_remove_legacy_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old, absent = tmp_path / "old.pickle", tmp_path / "absent.pickle"
    old.write_bytes(b"x")
    monkeypatch.setattr(auth, "LEGACY_SESSION_FILES", [old, absent])
    assert auth.remove_legacy_sessions() == [old]
    assert not old.exists()


# --- token checks -----------------------------------------------------------------

@pytest.mark.parametrize("error, expected", [
    (TransportServerError("x", 401), True),
    (TransportServerError("x", 403), True),
    (TransportServerError("x", 500), False),
    (TransportQueryError("x"), False),
    (RuntimeError("401"), False),
])
def test_is_auth_error(error: Exception, expected: bool) -> None:
    assert auth.is_auth_error(error) is expected


async def test_token_works() -> None:
    assert await auth.token_works(auth.client_for("good")) is True
    assert await auth.token_works(auth.client_for("bad")) is False
    with pytest.raises(TransportServerError):
        await auth.token_works(auth.client_for("server-error"))


# --- password login ---------------------------------------------------------------

async def test_password_login_never_uses_library_session() -> None:
    mm = await auth.password_login("e@x", "pw", "SECRET")
    assert mm.token == "fresh-1"
    assert FakeMonarch.logins == [{"email": "e@x", "password": "pw", "use_saved_session": False,
                                   "save_session": False, "mfa_secret_key": "SECRET"}]


async def test_password_login_asks_for_mfa_code(fake_monarch: type[FakeMonarch]) -> None:
    fake_monarch.requires_mfa = True
    mm = await auth.password_login("e@x", "pw", None, lambda: " 123456 ")
    assert (mm.token, FakeMonarch.mfa_codes) == ("fresh-mfa", ["123456"])


async def test_password_login_mfa_without_prompt_fails(fake_monarch: type[FakeMonarch]) -> None:
    fake_monarch.requires_mfa = True
    with pytest.raises(RequireMFAException):
        await auth.password_login("e@x", "pw", None)


# --- Authenticator.client -----------------------------------------------------------

async def test_client_prefers_env_token(session: Path) -> None:
    auth.save_token(session, "saved")
    mm = await auth.Authenticator(env(session, MONARCH_TOKEN="good", **CREDS)).client()
    assert mm.token == "good"
    assert FakeMonarch.logins == []
    assert auth.load_token(session) == "saved"


async def test_client_rejected_env_token_without_creds(session: Path) -> None:
    with pytest.raises(auth.AuthError, match="MONARCH_TOKEN was rejected"):
        await auth.Authenticator(env(session, MONARCH_TOKEN="bad")).client()


async def test_client_rejected_env_token_falls_back_to_saved(session: Path) -> None:
    auth.save_token(session, "good")
    mm = await auth.Authenticator(env(session, MONARCH_TOKEN="bad", **CREDS)).client()
    assert mm.token == "good"


async def test_client_uses_saved_token(session: Path) -> None:
    auth.save_token(session, "good")
    mm = await auth.Authenticator(env(session)).client()
    assert mm.token == "good"
    assert FakeMonarch.logins == []


async def test_client_expired_saved_token_without_creds(session: Path) -> None:
    auth.save_token(session, "stale")
    with pytest.raises(auth.AuthError, match="session expired"):
        await auth.Authenticator(env(session)).client()


async def test_client_not_logged_in(session: Path) -> None:
    with pytest.raises(auth.AuthError, match="Not logged in"):
        await auth.Authenticator(env(session)).client()


async def test_client_logs_in_and_saves(session: Path) -> None:
    auth.save_token(session, "stale")
    mm = await auth.Authenticator(env(session, MONARCH_MFA_SECRET="S", **CREDS)).client()
    assert mm.token == "fresh-1"
    assert auth.load_token(session) == "fresh-1"
    assert FakeMonarch.logins[0]["mfa_secret_key"] == "S"


async def test_client_force_login_ignores_saved(session: Path) -> None:
    auth.save_token(session, "good")
    mm = await auth.Authenticator(env(session, MONARCH_FORCE_LOGIN="1", **CREDS)).client()
    assert mm.token == "fresh-1"


async def test_client_empty_mfa_secret_is_none(session: Path) -> None:
    await auth.Authenticator(env(session, MONARCH_MFA_SECRET="", **CREDS)).client()
    assert FakeMonarch.logins[0]["mfa_secret_key"] is None


# --- Authenticator.renew ------------------------------------------------------------

def stale_client(token: str = "stale") -> MonarchMoney:
    return cast(MonarchMoney, FakeMonarch(token))


async def test_renew_without_creds(session: Path) -> None:
    with pytest.raises(auth.AuthError, match="session expired"):
        await auth.Authenticator(env(session)).renew(stale_client())


async def test_renew_logs_in(session: Path) -> None:
    auth.save_token(session, "stale")
    mm = await auth.Authenticator(env(session, **CREDS)).renew(stale_client())
    assert mm.token == "fresh-1"
    assert auth.load_token(session) == "fresh-1"


async def test_renew_reuses_newer_saved_token(session: Path) -> None:
    auth.save_token(session, "newer")
    mm = await auth.Authenticator(env(session, **CREDS)).renew(stale_client())
    assert mm.token == "newer"
    assert FakeMonarch.logins == []


async def test_concurrent_renewals_log_in_once(session: Path) -> None:
    authenticator = auth.Authenticator(env(session, **CREDS))
    clients = await asyncio.gather(*(authenticator.renew(stale_client()) for _ in range(5)))
    assert {c.token for c in clients} == {"fresh-1"}
    assert len(FakeMonarch.logins) == 1


# --- interactive login --------------------------------------------------------------

class Prompts:
    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, question: str) -> str:
        self.asked.append(question)
        return self.answers.pop(0)


async def test_interactive_login_saves_token(session: Path) -> None:
    prompt, secret = Prompts("me@x"), Prompts("pw")
    assert await auth.interactive_login(env(session), prompt, secret) == session
    assert auth.load_token(session) == "fresh-1"
    assert mode(session) == 0o600
    assert (prompt.asked, secret.asked) == (["Monarch email: "], ["Monarch password: "])
    assert FakeMonarch.logins[0]["email"] == "me@x"


async def test_interactive_login_email_from_env_and_mfa(session: Path,
                                                         fake_monarch: type[FakeMonarch]) -> None:
    fake_monarch.requires_mfa = True
    prompt = Prompts("654321")
    await auth.interactive_login(env(session, MONARCH_EMAIL="env@x"), prompt, Prompts("pw"))
    assert prompt.asked == ["MFA code: "]
    assert FakeMonarch.mfa_codes == ["654321"]
    assert auth.load_token(session) == "fresh-mfa"


async def test_interactive_login_rejects_unusable_token(session: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    async def never_works(mm: MonarchMoney) -> bool:
        return False
    monkeypatch.setattr(auth, "token_works", never_works)
    with pytest.raises(auth.AuthError, match="did not produce a working token"):
        await auth.interactive_login(env(session), Prompts("me@x"), Prompts("pw"))
    assert not session.exists()
