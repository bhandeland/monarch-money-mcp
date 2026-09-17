"""The MCP layer: tool listing, dispatch, error handling, startup."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from gql.transport.exceptions import TransportServerError
from mcp import Client
from mcp.types import TextContent
from monarchmoney import MonarchMoney

import auth
import server
from tests.helpers import Call, ToolError


async def test_list_tools_matches_registry() -> None:
    async with Client(server.server) as client:
        tools = (await client.list_tools()).tools
    assert [t.name for t in tools] == list(server.TOOLS)
    assert len(tools) == 70


@pytest.mark.parametrize("name", sorted(server.TOOLS))
def test_tool_schema_is_well_formed(name: str) -> None:
    tool, _ = server.TOOLS[name]
    schema: dict[str, Any] = tool.input_schema
    assert tool.description
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema.get("required", [])) <= set(schema["properties"])
    for prop in schema["properties"].values():
        assert "type" in prop


@pytest.mark.parametrize("name", sorted(server.TOOLS))
def test_tool_annotations_match_name(name: str) -> None:
    annotations = server.TOOLS[name][0].annotations
    assert annotations is not None
    reads = name.startswith(("get_", "list_", "preview_", "search_"))
    assert annotations.read_only_hint is reads
    if name.startswith("delete_"):
        assert annotations.destructive_hint is True


async def test_call_tool_without_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "mm_client", None)
    result = await server.call_tool("get_accounts", {})
    [content] = result.content
    assert isinstance(content, TextContent) and result.is_error
    assert content.text == "Error: MonarchMoney client not initialized"


async def test_call_tool_unknown(call: Call) -> None:
    with pytest.raises(ToolError, match="^Error: Unknown tool 'nope'$"):
        await call("nope")


async def test_call_tool_wraps_exceptions(call: Call, mm: AsyncMock) -> None:
    mm.get_accounts.side_effect = RuntimeError("boom")
    with pytest.raises(ToolError, match="^Error executing get_accounts: boom$"):
        await call("get_accounts")


async def test_call_tool_serializes_dates(call: Call, mm: AsyncMock) -> None:
    from datetime import date
    mm.get_accounts.return_value = {"accounts": [{"updated": date(2026, 1, 2)}]}
    assert await call("get_accounts") == {"accounts": [{"updated": "2026-01-02"}]}


async def test_call_tool_accepts_none_arguments(mm: AsyncMock) -> None:
    mm.get_accounts.return_value = []
    result = await server.call_tool("get_accounts", None)
    [content] = result.content
    assert isinstance(content, TextContent) and not result.is_error
    assert content.text == "[]"


# --- token renewal ----------------------------------------------------------------

UNAUTHORIZED = TransportServerError("401, message='Unauthorized'", 401)


@pytest.fixture
def renewer(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replaces the server's authenticator; renew() returns a fresh client."""
    authenticator = AsyncMock(spec=auth.Authenticator)
    authenticator.renew.return_value = AsyncMock(spec=MonarchMoney)
    monkeypatch.setattr(server, "authenticator", authenticator)
    return authenticator


async def test_expired_token_is_renewed_and_retried(call: Call, mm: AsyncMock, renewer: AsyncMock) -> None:
    mm.get_accounts.side_effect = UNAUTHORIZED
    fresh = renewer.renew.return_value
    fresh.get_accounts.return_value = {"accounts": []}
    assert await call("get_accounts") == {"accounts": []}
    renewer.renew.assert_awaited_once_with(mm)
    assert server.mm_client is fresh


async def test_renewal_failure_is_reported(call: Call, mm: AsyncMock, renewer: AsyncMock) -> None:
    mm.get_accounts.side_effect = UNAUTHORIZED
    renewer.renew.side_effect = auth.AuthError(auth.SESSION_EXPIRED)
    with pytest.raises(ToolError, match="^Error executing get_accounts: Monarch Money session expired"):
        await call("get_accounts")
    assert server.mm_client is mm


async def test_retry_happens_only_once(call: Call, mm: AsyncMock, renewer: AsyncMock) -> None:
    mm.get_accounts.side_effect = UNAUTHORIZED
    renewer.renew.return_value.get_accounts.side_effect = UNAUTHORIZED
    with pytest.raises(ToolError, match="401"):
        await call("get_accounts")
    renewer.renew.assert_awaited_once()


async def test_other_errors_are_not_retried(call: Call, mm: AsyncMock, renewer: AsyncMock) -> None:
    mm.get_accounts.side_effect = TransportServerError("502", 502)
    with pytest.raises(ToolError, match="502"):
        await call("get_accounts")
    renewer.renew.assert_not_awaited()


# --- startup and CLI --------------------------------------------------------------

async def test_serve_stops_when_auth_fails(renewer: AsyncMock, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(server, "mm_client", None)
    renewer.client.side_effect = auth.AuthError(auth.NOT_LOGGED_IN)
    await server.serve()
    out, err = capsys.readouterr()
    assert out == ""
    assert "Failed to initialize MonarchMoney client: Not logged in" in err
    assert server.mm_client is None


@pytest.mark.parametrize("argv, expected", [
    ([], "serve"), (["serve"], "serve"), (["login"], "login"), (["logout"], "logout"),
])
def test_main_dispatch(monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: str) -> None:
    ran: list[str] = []

    async def fake_serve() -> None:
        ran.append("serve")

    async def fake_login() -> None:
        ran.append("login")

    monkeypatch.setattr(server, "serve", fake_serve)
    monkeypatch.setattr(server, "login", fake_login)
    monkeypatch.setattr(server, "logout", lambda: ran.append("logout"))
    server.main(argv)
    assert ran == [expected]


@pytest.mark.parametrize("argv, expected", [
    (["install", "--client", "claude-desktop"], "claude-desktop"),
    (["install", "--client", "claude-code"], "claude-code"),
    (["install", "--print"], None),
])
def test_main_install(monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: str | None) -> None:
    clients: list[str | None] = []
    monkeypatch.setattr(server.install, "install", clients.append)
    server.main(argv)
    assert clients == [expected]


def test_main_install_needs_a_target() -> None:
    with pytest.raises(SystemExit):
        server.main(["install"])


def test_main_login_failure_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_login() -> None:
        raise auth.AuthError("bad password")

    monkeypatch.setattr(server, "login", failing_login)
    with pytest.raises(SystemExit, match="^Login failed: bad password$"):
        server.main(["login"])


async def test_login_saves_and_cleans_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    async def fake_interactive_login(env: object, prompt: object, secret: object) -> Path:
        return tmp_path / "session.json"

    monkeypatch.setattr(auth, "interactive_login", fake_interactive_login)
    monkeypatch.setattr(auth, "remove_legacy_sessions", lambda: [tmp_path / "old.pickle"])
    await server.login()
    assert capsys.readouterr().out.splitlines() == [
        f"Saved session to {tmp_path / 'session.json'}",
        f"Removed old session file {tmp_path / 'old.pickle'}",
    ]


def test_logout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                capsys: pytest.CaptureFixture[str]) -> None:
    session = tmp_path / "session.json"
    monkeypatch.setenv("MONARCH_SESSION_FILE", str(session))
    auth.save_token(session, "abc")
    server.logout()
    server.logout()
    assert capsys.readouterr().out.splitlines() == [f"Removed {session}", f"No session at {session}"]
