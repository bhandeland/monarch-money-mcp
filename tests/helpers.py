"""Test helpers shared across test modules."""

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

from graphql import OperationDefinitionNode

# The `call` fixture: call("tool_name", **arguments) -> decoded JSON result
Call = Callable[..., Awaitable[Any]]


class ToolError(Exception):
    pass


def gql_ops(mm: AsyncMock) -> list[tuple[str, dict[str, Any]]]:
    """(operation name, variables) for each raw GraphQL call, checking the name matches the document."""
    ops: list[tuple[str, dict[str, Any]]] = []
    for c in mm.gql_call.await_args_list:
        definition = c.kwargs["graphql_query"].document.definitions[0]
        assert isinstance(definition, OperationDefinitionNode) and definition.name
        assert c.kwargs["operation"] == definition.name.value
        ops.append((c.kwargs["operation"], c.kwargs["variables"]))
    return ops


def gql_input(mm: AsyncMock) -> dict[str, Any]:
    """The `input` variable of the single raw GraphQL call made."""
    [(_, variables)] = gql_ops(mm)
    value: dict[str, Any] = variables["input"]
    return value
