"""Authentication: where the Monarch token comes from, where it's kept, and renewing it.

Token sources, in order:
  1. MONARCH_TOKEN environment variable
  2. The session file written by `monarch-money-mcp login` (JSON, mode 0600)
  3. MONARCH_EMAIL / MONARCH_PASSWORD (+ MONARCH_MFA_SECRET), which logs in and
     saves the token to the session file

Only (3) can renew a token that stops working while the server is running.
"""

import asyncio
import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from gql.transport.exceptions import TransportServerError
from monarchmoney import MonarchMoney
from monarchmoney.monarchmoney import RequireMFAException

import monarch_gql as q

DEFAULT_SESSION_FILE = Path.home() / ".config" / "monarch-money-mcp" / "session.json"
# Pickle files written by earlier versions of this server and by the library.
# Never loaded (unpickling can run code); `login` removes them.
LEGACY_SESSION_FILES = [Path.home() / ".monarchmoney_session", Path(".mm") / "mm_session.pickle"]

NOT_LOGGED_IN = (
    "Not logged in to Monarch Money. Run `uv run monarch-money-mcp login`, "
    "or set MONARCH_TOKEN, or set MONARCH_EMAIL and MONARCH_PASSWORD."
)
SESSION_EXPIRED = (
    "Monarch Money session expired. Run `uv run monarch-money-mcp login`, then restart the server."
)


class AuthError(Exception):
    pass


def session_file(env: Mapping[str, str]) -> Path:
    override = env.get("MONARCH_SESSION_FILE")
    return Path(override).expanduser() if override else DEFAULT_SESSION_FILE


def load_token(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    token = data.get("token") if isinstance(data, dict) else None
    return token if isinstance(token, str) and token else None


def save_token(path: Path, token: str) -> None:
    """Write the token readable only by the current user."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"token": token}, f)
    os.chmod(tmp, 0o600)  # in case the file already existed with wider permissions
    os.replace(tmp, path)


def delete_token(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def is_auth_error(error: BaseException) -> bool:
    return isinstance(error, TransportServerError) and error.code in (401, 403)


def client_for(token: str) -> MonarchMoney:
    return MonarchMoney(token=token)


async def token_works(mm: MonarchMoney) -> bool:
    try:
        await q.execute(mm, q.GET_ME)
    except TransportServerError as e:
        if is_auth_error(e):
            return False
        raise
    return True


async def password_login(email: str, password: str, mfa_secret: str | None,
                         ask_mfa_code: Callable[[], str] | None = None) -> MonarchMoney:
    """Log in with a password. Without an MFA secret, ask_mfa_code supplies the code."""
    mm = MonarchMoney()
    try:
        # use_saved_session=False: otherwise the library silently loads its own pickle file
        await mm.login(email, password, use_saved_session=False, save_session=False,
                       mfa_secret_key=mfa_secret)
    except RequireMFAException:
        if ask_mfa_code is None:
            raise
        await mm.multi_factor_authenticate(email, password, ask_mfa_code().strip())
    return mm


class Authenticator:
    def __init__(self, env: Mapping[str, str]) -> None:
        self.env = env
        self.session_file = session_file(env)
        self._lock = asyncio.Lock()

    @property
    def can_renew(self) -> bool:
        return bool(self.env.get("MONARCH_EMAIL") and self.env.get("MONARCH_PASSWORD"))

    async def client(self) -> MonarchMoney:
        """A client with a working token, from the first source that has one."""
        env_token = self.env.get("MONARCH_TOKEN")
        if env_token:
            mm = client_for(env_token)
            if await token_works(mm):
                return mm
            if not self.can_renew:
                raise AuthError("MONARCH_TOKEN was rejected by Monarch Money.")

        saved = None if self.env.get("MONARCH_FORCE_LOGIN") else load_token(self.session_file)
        if saved:
            mm = client_for(saved)
            if await token_works(mm):
                return mm

        if not self.can_renew:
            raise AuthError(SESSION_EXPIRED if saved else NOT_LOGGED_IN)
        return await self._login()

    async def renew(self, stale: MonarchMoney) -> MonarchMoney:
        """Replace a client whose token stopped working.

        Concurrent callers share one login: whoever gets the lock second sees the
        session file already holds a different token and reuses it.
        """
        if not self.can_renew:
            raise AuthError(SESSION_EXPIRED)
        async with self._lock:
            saved = load_token(self.session_file)
            if saved and saved != stale.token:
                return client_for(saved)
            return await self._login()

    async def _login(self) -> MonarchMoney:
        mm = await password_login(self.env["MONARCH_EMAIL"], self.env["MONARCH_PASSWORD"],
                                  self.env.get("MONARCH_MFA_SECRET") or None)
        if mm.token:
            save_token(self.session_file, mm.token)
        return mm


async def interactive_login(env: Mapping[str, str], prompt: Callable[[str], str],
                            secret_prompt: Callable[[str], str]) -> Path:
    """Log in once (asking for an MFA code if needed) and save only the token."""
    email = env.get("MONARCH_EMAIL") or prompt("Monarch email: ")
    password = secret_prompt("Monarch password: ")
    mm = await password_login(email, password, env.get("MONARCH_MFA_SECRET") or None,
                              lambda: prompt("MFA code: "))
    if not mm.token or not await token_works(mm):
        raise AuthError("Login did not produce a working token.")
    path = session_file(env)
    save_token(path, mm.token)
    return path


def remove_legacy_sessions() -> list[Path]:
    removed = [p for p in LEGACY_SESSION_FILES if p.exists()]
    for p in removed:
        p.unlink()
    return removed
