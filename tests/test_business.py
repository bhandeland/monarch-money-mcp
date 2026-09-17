from datetime import date
from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops


async def test_get_business_entities(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"businessEntities": [{"id": "b1", "name": "Shop"}]}
    assert await call("get_business_entities") == [{"id": "b1", "name": "Shop"}]
    assert gql_ops(mm) == [("Common_GetBusinessEntities", {})]


async def test_get_business_entity(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"businessEntity": {"id": "b1", "name": "Shop"}}
    assert await call("get_business_entity", business_entity_id="b1") == {"id": "b1", "name": "Shop"}
    assert gql_ops(mm) == [("Common_GetBusinessEntity", {"id": "b1"})]


async def test_get_business_entity_missing(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"businessEntity": None}
    with pytest.raises(ToolError, match="No business entity with ID b9"):
        await call("get_business_entity", business_entity_id="b9")


FINANCIALS = [{"entityId": "b1", "sumIncome": 10.0, "sumExpense": -4.0, "netAssets": 6.0,
               "monthlyBreakdown": [], "monthlyNetAssets": []}]


async def test_get_business_entity_financials(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"businessEntityFinancials": FINANCIALS}
    out = await call("get_business_entity_financials", business_entity_ids=["b1"],
                     start_date="2026-01-01", end_date="2026-06-30")
    assert out == FINANCIALS
    assert gql_ops(mm) == [("Common_GetBusinessEntityFinancials",
                            {"entityIds": ["b1"], "startDate": "2026-01-01", "endDate": "2026-06-30"})]


async def test_get_business_entity_financials_defaults_to_all(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [{"businessEntities": [{"id": "b1"}, {"id": "b2"}]},
                               {"businessEntityFinancials": FINANCIALS}]
    await call("get_business_entity_financials", start_date="2026-01-01", end_date="2026-01-31")
    assert gql_ops(mm) == [
        ("Common_GetBusinessEntitiesSummary", {}),
        ("Common_GetBusinessEntityFinancials",
         {"entityIds": ["b1", "b2"], "startDate": "2026-01-01", "endDate": "2026-01-31"}),
    ]


async def test_get_business_entity_financials_without_businesses(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"businessEntities": []}
    assert await call("get_business_entity_financials",
                      start_date="2026-01-01", end_date="2026-01-31") == []
    assert [op for op, _ in gql_ops(mm)] == ["Common_GetBusinessEntitiesSummary"]


@pytest.mark.parametrize("arguments", [
    {"start_date": "2026-01-01"},
    {"end_date": "2026-01-01"},
    {},
])
async def test_business_date_range_is_required(call: Call, mm: AsyncMock,
                                               arguments: dict[str, str]) -> None:
    for tool in ("get_business_entity_financials", "get_business_entity_summaries"):
        with pytest.raises(ToolError, match="start_date and end_date"):
            await call(tool, business_entity_ids=["b1"], **arguments)
    mm.gql_call.assert_not_awaited()


async def test_get_business_entity_summaries(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"businessEntitySummaries": [{"businessEntity": {"id": "b1"}}]}
    out = await call("get_business_entity_summaries", start_date="2026-01-01", end_date="2026-12-31")
    assert out == {"businessEntitySummaries": [{"businessEntity": {"id": "b1"}}]}
    assert gql_ops(mm) == [("Common_GetBusinessEntitySummaries",
                            {"filters": {"startDate": "2026-01-01", "endDate": "2026-12-31"}})]


async def test_get_business_entity_summaries_by_category(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"reports": [], "businessEntitySummaries": [], "aggregates": []}
    await call("get_business_entity_summaries", start_date="2026-01-01", end_date="2026-12-31",
               business_entity_ids=["b1"], include_unassigned=True, by_category=True)
    assert gql_ops(mm) == [("Common_GetBusinessEntityReportsDataByCategory", {"filters": {
        "startDate": "2026-01-01", "endDate": "2026-12-31",
        "businessEntitySet": {"businessEntityIds": ["b1"], "includeUnassigned": True}}})]


async def test_create_business_entity(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"upsertBusinessEntity": {"businessEntity": {"id": "b1"}, "errors": None}}
    out = await call("create_business_entity", name="Shop", description="Etsy store",
                     notes="EIN on file", color="#ff0000", structure="llc")
    assert out == {"id": "b1"}
    assert gql_ops(mm)[0][0] == "Common_UpsertBusinessEntity"
    assert gql_input(mm) == {"name": "Shop", "description": "Etsy store", "notes": "EIN on file",
                             "color": "#ff0000", "structure": "llc"}


async def test_update_business_entity(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"upsertBusinessEntity": {"businessEntity": {"id": "b1"}, "errors": None}}
    assert await call("update_business_entity", business_entity_id="b1", name="New") == {"id": "b1"}
    assert gql_input(mm) == {"id": "b1", "name": "New"}


async def test_update_business_entity_needs_a_change(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("update_business_entity", business_entity_id="b1")
    mm.gql_call.assert_not_awaited()


async def test_upsert_business_entity_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"upsertBusinessEntity": {"errors": {"message": "name taken"}}}
    with pytest.raises(ToolError, match="Business entity save failed: name taken"):
        await call("create_business_entity", name="Shop")


async def test_delete_business_entity(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteBusinessEntity": {"deleted": True, "errors": None}}
    out = await call("delete_business_entity", business_entity_id="b1")
    assert out == {"business_entity_id": "b1", "deleted": True}
    assert gql_ops(mm) == [("Common_DeleteBusinessEntity", {"id": "b1"})]


async def test_delete_business_entity_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteBusinessEntity": {"deleted": False,
                                                         "errors": {"message": "in use"}}}
    with pytest.raises(ToolError, match="Business entity deletion failed: in use"):
        await call("delete_business_entity", business_entity_id="b1")


async def test_set_account_business_entity(call: Call, mm: AsyncMock) -> None:
    accounts = [{"id": "a1", "businessEntity": {"id": "b1"}}]
    mm.gql_call.return_value = {"updateAccounts": {"accounts": accounts, "errors": None}}
    out = await call("set_account_business_entity", account_ids=["a1", "a2"], business_entity_id="b1")
    assert out == accounts
    assert gql_ops(mm) == [("Common_UpdateAccountsForEditingEntities", {"input": [
        {"id": "a1", "businessEntityId": "b1"}, {"id": "a2", "businessEntityId": "b1"}]})]


async def test_set_account_business_entity_clears(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateAccounts": {"accounts": [], "errors": None}}
    await call("set_account_business_entity", account_ids=["a1"])
    assert gql_ops(mm)[0][1] == {"input": [{"id": "a1", "businessEntityId": None}]}


async def test_set_account_business_entity_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateAccounts": {"errors": {"message": "bad account"}}}
    with pytest.raises(ToolError, match="Account business assignment failed: bad account"):
        await call("set_account_business_entity", account_ids=["a1"], business_entity_id="b1")


async def test_get_schedule_c_line_items(call: Call, mm: AsyncMock) -> None:
    items = [{"key": "line_8_advertising", "lineNumber": "8"}]
    mm.gql_call.return_value = {"scheduleCLineItems": items}
    assert await call("get_schedule_c_line_items", tax_year=2025) == items
    assert gql_ops(mm) == [("Web_GetScheduleCLineItems", {"taxYear": 2025})]


async def test_schedule_c_tax_year_defaults_to_this_year(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"scheduleCLineItems": [], "taxScheduleCategoryMappings": []}
    await call("get_schedule_c_line_items")
    await call("get_schedule_c_category_mappings")
    year = date.today().year
    assert gql_ops(mm) == [
        ("Web_GetScheduleCLineItems", {"taxYear": year}),
        ("Web_GetTaxScheduleCategoryMappings", {"schedule": "schedule_c", "taxYear": year}),
    ]


async def test_get_schedule_c_category_mappings(call: Call, mm: AsyncMock) -> None:
    mappings = [{"id": "m1", "lineItem": "line_22_supplies", "category": {"id": "c1"}}]
    mm.gql_call.return_value = {"taxScheduleCategoryMappings": mappings}
    assert await call("get_schedule_c_category_mappings", tax_year=2025) == mappings
    assert gql_ops(mm) == [("Web_GetTaxScheduleCategoryMappings",
                            {"schedule": "schedule_c", "taxYear": 2025})]


async def test_set_schedule_c_category_mapping(call: Call, mm: AsyncMock) -> None:
    mapping = {"id": "m1", "lineItem": "line_22_supplies"}
    mm.gql_call.return_value = {"assignTaxScheduleCategoryMapping": {
        "taxScheduleCategoryMapping": mapping, "errors": None}}
    out = await call("set_schedule_c_category_mapping", category_id="c1",
                     line_item="line_22_supplies", tax_year=2025)
    assert out == mapping
    assert gql_ops(mm)[0][0] == "Web_AssignTaxScheduleCategoryMapping"
    assert gql_input(mm) == {"categoryId": "c1", "lineItem": "line_22_supplies",
                             "schedule": "schedule_c", "taxYear": 2025}


async def test_set_schedule_c_category_mapping_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"assignTaxScheduleCategoryMapping": {"errors": {"message": "nope"}}}
    with pytest.raises(ToolError, match="Schedule C mapping failed: nope"):
        await call("set_schedule_c_category_mapping", category_id="c1",
                   line_item="line_22_supplies", tax_year=2025)


async def test_delete_schedule_c_category_mapping(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteTaxScheduleCategoryMapping": {"deleted": True, "errors": None}}
    out = await call("delete_schedule_c_category_mapping", category_id="c1", tax_year=2025)
    assert out == {"category_id": "c1", "tax_year": 2025, "deleted": True}
    assert gql_ops(mm)[0][0] == "Web_DeleteTaxScheduleCategoryMapping"
    assert gql_input(mm) == {"categoryId": "c1", "schedule": "schedule_c", "taxYear": 2025}


async def test_delete_schedule_c_category_mapping_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteTaxScheduleCategoryMapping": {
        "deleted": False, "errors": {"message": "no mapping"}}}
    with pytest.raises(ToolError, match="Schedule C mapping deletion failed: no mapping"):
        await call("delete_schedule_c_category_mapping", category_id="c1", tax_year=2025)
