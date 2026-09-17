"""The MCP layer: tool listing, dispatch, error handling, startup."""

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import TextContent
from monarchmoney import MonarchMoney

import server
from tests.helpers import Call, ToolError


async def test_list_tools_matches_registry() -> None:
    tools = await server.list_tools()
    assert [t.name for t in tools] == list(server.TOOLS)
    assert len(tools) == 53


@pytest.mark.parametrize("name", sorted(server.TOOLS))
def test_tool_schema_is_well_formed(name: str) -> None:
    tool, _ = server.TOOLS[name]
    schema: dict[str, Any] = tool.inputSchema
    assert tool.description
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema.get("required", [])) <= set(schema["properties"])
    for prop in schema["properties"].values():
        assert "type" in prop


@pytest.mark.parametrize("name", sorted(server.TOOLS))
def test_tool_annotations_match_name(name: str) -> None:
    annotations = server.TOOLS[name][0].annotations
    assert annotations is not None
    reads = name.startswith(("get_", "list_"))
    assert annotations.readOnlyHint is reads
    if name.startswith("delete_"):
        assert annotations.destructiveHint is True


async def test_call_tool_without_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "mm_client", None)
    [content] = await server.call_tool("get_accounts", {})
    assert isinstance(content, TextContent)
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
    [content] = await server.call_tool("get_accounts", None)  # type: ignore[arg-type]
    assert isinstance(content, TextContent)
    assert content.text == "[]"


# --- initialize_client --------------------------------------------------------

@pytest.fixture
def client_cls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> MagicMock:
    monkeypatch.setenv("MONARCH_EMAIL", "e@x")
    monkeypatch.setenv("MONARCH_PASSWORD", "pw")
    monkeypatch.delenv("MONARCH_MFA_SECRET", raising=False)
    monkeypatch.delenv("MONARCH_FORCE_LOGIN", raising=False)
    monkeypatch.setattr(server, "session_file", tmp_path / "session")
    monkeypatch.setattr(server, "mm_client", None)
    cls = MagicMock()
    cls.return_value = AsyncMock(spec=MonarchMoney)
    monkeypatch.setattr(server, "MonarchMoney", cls)
    return cls


async def test_initialize_requires_credentials(client_cls: MagicMock,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONARCH_PASSWORD")
    with pytest.raises(ValueError, match="MONARCH_EMAIL and MONARCH_PASSWORD"):
        await server.initialize_client()


async def test_initialize_logs_in_without_session(client_cls: MagicMock) -> None:
    await server.initialize_client()
    client = client_cls.return_value
    client.login.assert_awaited_once_with("e@x", "pw")
    client.save_session.assert_called_once_with(str(server.session_file))
    assert server.mm_client is client


async def test_initialize_passes_mfa_secret(client_cls: MagicMock,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONARCH_MFA_SECRET", "SECRET")
    await server.initialize_client()
    client_cls.return_value.login.assert_awaited_once_with("e@x", "pw", mfa_secret_key="SECRET")


async def test_initialize_reuses_valid_session(client_cls: MagicMock) -> None:
    server.session_file.write_text("x")
    await server.initialize_client()
    client = client_cls.return_value
    client.load_session.assert_called_once_with(str(server.session_file))
    client.login.assert_not_awaited()


async def test_initialize_logs_in_when_session_invalid(client_cls: MagicMock) -> None:
    server.session_file.write_text("x")
    client = client_cls.return_value
    client.get_accounts.side_effect = RuntimeError("expired")
    await server.initialize_client()
    client.login.assert_awaited_once()
    client.save_session.assert_called_once()


async def test_initialize_force_login_skips_session(client_cls: MagicMock,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    server.session_file.write_text("x")
    monkeypatch.setenv("MONARCH_FORCE_LOGIN", "1")
    await server.initialize_client()
    client = client_cls.return_value
    client.load_session.assert_not_called()
    client.login.assert_awaited_once()


async def test_serve_stops_when_login_fails(client_cls: MagicMock,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    client_cls.return_value.login.side_effect = RuntimeError("bad password")
    await server.serve()
    out, err = capsys.readouterr()
    assert out == ""
    assert "Failed to initialize MonarchMoney client: bad password" in err
