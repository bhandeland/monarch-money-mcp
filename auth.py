"""Authentication: where the Monarch token comes from, where it's kept, and renewing it.

A credential is either a token or a pair of browser cookies (session_id and
csrftoken), for when Monarch blocks password login with a CAPTCHA.

Credential sources, in order:
  1. MONARCH_TOKEN environment variable
  2. MONARCH_COOKIES environment variable (a browser Cookie header)
  3. The session file written by `monarch-money-mcp login` (JSON, mode 0600)
  4. MONARCH_EMAIL / MONARCH_PASSWORD (+ MONARCH_MFA_SECRET), which logs in and
     saves the token to the session file

Only (4) can renew a credential that stops working while the server is running.
"""

import asyncio
import json
import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from gql.transport.exceptions import TransportServerError
from monarchmoney import MonarchMoney
from monarchmoney.monarchmoney import (REQUIRED_COOKIES, CaptchaRequiredException,
                                       RequireMFAException)

import monarch_gql as q

DEFAULT_SESSION_FILE = Path.home() / ".config" / "monarch-money-mcp" / "session.json"
# Pickle files written by earlier versions of this server and by the library.
# Never loaded (unpickling can run code); `login` removes them.
LEGACY_SESSION_FILES = [Path.home() / ".monarchmoney_session", Path(".mm") / "mm_session.pickle"]

NOT_LOGGED_IN = (
    "Not logged in to Monarch Money. Run `uv run monarch-money-mcp login`, "
    "or set MONARCH_TOKEN, MONARCH_COOKIES, or MONARCH_EMAIL and MONARCH_PASSWORD."
)
SESSION_EXPIRED = (
    "Monarch Money session expired. Run `uv run monarch-money-mcp login`, then restart the server."
)
CAPTCHA_BLOCKED = (
    "Monarch Money asked for a CAPTCHA, so logging in with a password didn't work. "
    "Run `uv run monarch-money-mcp login --cookies` to log in with cookies from your browser, "
    "then restart the server."
)
COOKIE_PROMPT = "Paste the Cookie header from a signed-in app.monarch.com tab: "

Cookies = dict[str, str]
Credential = str | Cookies


class AuthError(Exception):
    pass


# Claude Desktop passes an optional extension setting the user left blank either
# as "" or as the unreplaced "${user_config.<key>}" placeholder.
_UNSET_PLACEHOLDER = re.compile(r"\$\{user_config\.[^}]*\}")


def configured_env(env: Mapping[str, str]) -> dict[str, str]:
    """The MONARCH_* variables that actually have a value."""
    return {k: v for k, v in env.items()
            if k.startswith("MONARCH_") and v and not _UNSET_PLACEHOLDER.fullmatch(v)}


def session_file(env: Mapping[str, str]) -> Path:
    override = env.get("MONARCH_SESSION_FILE")
    return Path(override).expanduser() if override else DEFAULT_SESSION_FILE


def parse_cookies(header: str, source: str = "The Cookie header") -> Cookies:
    """Keep only the cookies Monarch needs from a browser Cookie header."""
    header = re.sub(r"^\s*cookie:", "", header, flags=re.IGNORECASE)
    pairs = (part.partition("=") for part in header.split(";"))
    found = {k.strip(): v.strip() for k, sep, v in pairs if sep}
    missing = [name for name in REQUIRED_COOKIES if not found.get(name)]
    if missing:
        raise AuthError(f"{source} is missing {', '.join(missing)}.")
    return {name: found[name] for name in REQUIRED_COOKIES}


def load_credential(path: Path) -> Credential | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    token = data.get("token")
    if isinstance(token, str) and token:
        return token
    cookies = data.get("cookies")
    if isinstance(cookies, dict) and all(isinstance(cookies.get(k), str) and cookies.get(k)
                                         for k in REQUIRED_COOKIES):
        return {k: str(cookies[k]) for k in REQUIRED_COOKIES}
    return None


def save_token(path: Path, token: str) -> None:
    _save(path, {"token": token})


def save_cookies(path: Path, cookies: Cookies) -> None:
    _save(path, {"cookies": {k: cookies[k] for k in REQUIRED_COOKIES}})


def _save(path: Path, data: dict[str, object]) -> None:
    """Write the session file readable only by the current user."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
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


def client_for(credential: Credential) -> MonarchMoney:
    if isinstance(credential, str):
        return MonarchMoney(token=credential)
    mm = MonarchMoney()
    mm.set_cookies(credential)
    return mm


def credential_of(mm: MonarchMoney) -> Credential | None:
    # The library keeps cookies in a private attribute and has no getter.
    cookies: Cookies | None = getattr(mm, "_cookies", None)
    return cookies or mm.token


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
    """Log in with a password. Without an MFA secret, ask_mfa_code supplies the code.

    Raises CaptchaRequiredException when Monarch wants a CAPTCHA.
    """
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
        env_cookies = self.env.get("MONARCH_COOKIES")
        for name, credential in (
            ("MONARCH_TOKEN", env_token),
            ("MONARCH_COOKIES", env_cookies and parse_cookies(env_cookies, "MONARCH_COOKIES")),
        ):
            if not credential:
                continue
            mm = client_for(credential)
            if await token_works(mm):
                return mm
            if not self.can_renew:
                raise AuthError(f"{name} was rejected by Monarch Money.")

        saved = None if self.env.get("MONARCH_FORCE_LOGIN") else load_credential(self.session_file)
        if saved:
            mm = client_for(saved)
            if await token_works(mm):
                return mm

        if not self.can_renew:
            raise AuthError(SESSION_EXPIRED if saved else NOT_LOGGED_IN)
        return await self._login()

    async def renew(self, stale: MonarchMoney) -> MonarchMoney:
        """Replace a client whose credential stopped working.

        Concurrent callers share one login: whoever gets the lock second sees the
        session file already holds a different credential and reuses it.
        """
        if not self.can_renew:
            raise AuthError(SESSION_EXPIRED)
        async with self._lock:
            saved = load_credential(self.session_file)
            if saved and saved != credential_of(stale):
                return client_for(saved)
            return await self._login()

    async def _login(self) -> MonarchMoney:
        try:
            mm = await password_login(self.env["MONARCH_EMAIL"], self.env["MONARCH_PASSWORD"],
                                      self.env.get("MONARCH_MFA_SECRET") or None)
        except CaptchaRequiredException as e:
            raise AuthError(CAPTCHA_BLOCKED) from e
        if mm.token:
            save_token(self.session_file, mm.token)
        return mm


async def interactive_login(env: Mapping[str, str], prompt: Callable[[str], str],
                            secret_prompt: Callable[[str], str],
                            notify: Callable[[str], object]) -> Path:
    """Log in once (asking for an MFA code if needed) and save only the token.

    If Monarch wants a CAPTCHA, explain and fall back to browser cookies.
    """
    email = env.get("MONARCH_EMAIL") or prompt("Monarch email: ")
    password = secret_prompt("Monarch password: ")
    try:
        mm = await password_login(email, password, env.get("MONARCH_MFA_SECRET") or None,
                                  lambda: prompt("MFA code: "))
    except CaptchaRequiredException:
        notify("Monarch asked for a CAPTCHA, so password login won't work from here. "
               "Log in to app.monarch.com in your browser, open the developer tools, "
               "and copy the Cookie request header from any request to api.monarch.com.")
        return await cookie_login(env, secret_prompt)
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


async def cookie_login(env: Mapping[str, str], secret_prompt: Callable[[str], str]) -> Path:
    """Save the session cookies from a browser Cookie header, once they're shown to work."""
    cookies = parse_cookies(secret_prompt(COOKIE_PROMPT))
    if not await token_works(client_for(cookies)):
        raise AuthError("Monarch Money rejected those cookies. Log in again in your browser "
                        "and copy a fresh Cookie header.")
    path = session_file(env)
    save_cookies(path, cookies)
    return path
