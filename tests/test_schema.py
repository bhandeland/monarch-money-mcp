"""Validate every GraphQL operation the server sends against Monarch's schema.

The schema comes from Monarch's web app (scripts/fetch_schema.py); check.sh and CI
fetch it. This catches misspelled fields and wrong argument types without calling
the API.
"""

import inspect
import json
import re
from pathlib import Path

import pytest
from gql import GraphQLRequest
from graphql import DocumentNode, GraphQLSchema, build_client_schema, parse, validate
from monarchmoney import MonarchMoney

import monarch_gql as q
import server

SCHEMA_FILE = Path(__file__).resolve().parent.parent / ".schema" / "monarch_schema.json"


@pytest.fixture(scope="module")
def schema() -> GraphQLSchema:
    if not SCHEMA_FILE.exists():
        pytest.skip("No schema; run `uv run python scripts/fetch_schema.py`")
    return build_client_schema({"__schema": json.loads(SCHEMA_FILE.read_text())})


OUR_OPERATIONS = {name: v for name, v in vars(q).items() if isinstance(v, GraphQLRequest)}


def library_operations() -> dict[str, DocumentNode]:
    """Operations inside the library methods that tools call."""
    called = set(re.findall(r"mm\.(\w+)\(", inspect.getsource(server)))
    docs: dict[str, DocumentNode] = {}
    for method in sorted(called):
        fn = getattr(MonarchMoney, method, None)
        if fn is None:
            continue
        for i, body in enumerate(re.findall(r'"""(.*?)"""', inspect.getsource(fn), re.S)):
            if re.match(r"\s*(query|mutation)\b", body):
                docs[f"{method}#{i}"] = parse(body)
    return docs


LIBRARY_OPERATIONS = library_operations()


def test_found_operations() -> None:
    assert len(OUR_OPERATIONS) > 30
    assert len(LIBRARY_OPERATIONS) > 20


@pytest.mark.parametrize("name", sorted(OUR_OPERATIONS))
def test_our_operation_is_valid(schema: GraphQLSchema, name: str) -> None:
    assert [e.message for e in validate(schema, OUR_OPERATIONS[name].document)] == []


@pytest.mark.parametrize("name", sorted(LIBRARY_OPERATIONS))
def test_library_operation_is_valid(schema: GraphQLSchema, name: str) -> None:
    assert [e.message for e in validate(schema, LIBRARY_OPERATIONS[name])] == []
