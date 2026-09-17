from unittest.mock import AsyncMock

from tests.helpers import Call, gql_ops


async def test_get_household_members(call: Call, mm: AsyncMock) -> None:
    household = {"id": "h1", "name": "Home", "users": [{"id": "u1", "displayName": "A", "email": "a@x"}]}
    mm.gql_call.return_value = {"myHousehold": household}
    assert await call("get_household_members") == household
    assert gql_ops(mm) == [("Common_GetHouseholdMembers", {})]


async def test_search_entities(call: Call, mm: AsyncMock) -> None:
    results = [{"id": "m1", "type": "merchant", "name": "Costco"}]
    mm.gql_call.return_value = {"semanticSearch": {"results": results}}
    assert await call("search_entities", query="costco") == results
    assert gql_ops(mm) == [("Web_GetCommandPaletteEntities", {"query": "costco"})]


async def test_search_entities_no_results(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"semanticSearch": None}
    assert await call("search_entities", query="zzz") is None
