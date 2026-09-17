"""Shared fixtures. The Monarch client is always mocked; tests never hit the network."""

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from mcp.types import TextContent
from monarchmoney import MonarchMoney

import server
from tests.helpers import Call, ToolError

CALLED_TOOLS: set[str] = set()


@pytest.fixture
def mm(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """A MonarchMoney mock installed as the server's client.

    spec= makes calls to methods the library doesn't have fail.
    """
    client = AsyncMock(spec=MonarchMoney)
    client.gql_call.return_value = {"data": None}
    monkeypatch.setattr(server, "mm_client", client)
    return client


@pytest.fixture
def call(mm: AsyncMock) -> Call:
    """Run a tool through the MCP dispatcher and return its decoded JSON result.

    Tool errors come back as text; they're raised so the failure shows the message.
    """
    async def run(tool: str, /, **arguments: Any) -> Any:
        CALLED_TOOLS.add(tool)
        [content] = await server.call_tool(tool, arguments)
        assert isinstance(content, TextContent)
        if content.text.startswith("Error"):
            raise ToolError(content.text)
        return json.loads(content.text)
    return run


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """On a full, passing run, fail if any registered tool was never called by a test."""
    config = session.config
    full_run = (config.args_source == pytest.Config.ArgsSource.TESTPATHS
                and not config.option.keyword and not config.option.markexpr)
    untested = sorted(set(server.TOOLS) - CALLED_TOOLS)
    if full_run and exitstatus == 0 and untested:
        reporter = config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.ensure_newline()
            reporter.write_line(f"FAILED untested tools: {', '.join(untested)}", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
