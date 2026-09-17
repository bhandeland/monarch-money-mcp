"""Reports: aggregated report data and saved report configurations."""

from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops

SUMMARY = {"sum": -120.0, "count": 3}


async def test_get_report_grouped(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {
        "reports": [{"groupBy": {"date": "2025-01-01", "category": {"id": "c1", "name": "Food"},
                                 "merchant": None},
                     "summary": SUMMARY}],
        "aggregates": [{"summary": {"sum": -500.0, "count": 9}}],
    }
    result = await call("get_report", start_date="2025-01-01", end_date="2025-12-31",
                        category_type="expense", group_by=["category"], timeframe="month",
                        sort_by="sum", exclude_category_ids=["c9"], tag_ids=["t1"])
    assert result == {
        "groups": [{"group": {"date": "2025-01-01", "category": {"id": "c1", "name": "Food"}},
                    "summary": SUMMARY}],
        "total": {"sum": -500.0, "count": 9},
    }
    [(op, variables)] = gql_ops(mm)
    assert op == "Common_GetReportsData"
    assert variables == {
        "filters": {"startDate": "2025-01-01", "endDate": "2025-12-31", "categoryType": "expense",
                    "excludeCategories": ["c9"], "tags": ["t1"]},
        "groupBy": ["category"],
        "groupByTimeframe": "month",
        "sortBy": "sum",
        "fillEmptyValues": False,
        "includeCategory": True,
        "includeCategoryGroup": False,
        "includeMerchant": False,
        "includeBusinessEntity": False,
        "includeBudgetVariability": False,
        "includeOwner": False,
    }


async def test_get_report_totals_only(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"reports": [], "aggregates": []}
    assert await call("get_report") == {"groups": [], "total": None}
    [(_, variables)] = gql_ops(mm)
    assert variables["filters"] == {}
    assert "groupBy" not in variables and "groupByTimeframe" not in variables


async def test_report_filters_nested_sets(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"reports": [], "aggregates": []}
    await call("get_report", owner_user_ids=["u1"], include_jointly_owned=False,
               business_entity_ids=["b1"], relative_period={"unit": "month", "value": 3},
               min_amount=10, max_amount=100, hidden_from_reports=False, fill_empty_values=True)
    [(_, variables)] = gql_ops(mm)
    assert variables["fillEmptyValues"] is True
    assert variables["filters"] == {
        "ownershipSet": {"userIds": ["u1"], "includeJointlyOwned": False},
        "businessEntitySet": {"businessEntityIds": ["b1"], "includeUnassigned": False},
        "timeframePeriod": {"unit": "month", "value": 3, "includeCurrent": True},
        "absAmountGte": 10, "absAmountLte": 100, "hideFromReports": False,
    }


async def test_report_filters_reject_dates_with_relative_period(call: Call) -> None:
    with pytest.raises(ToolError, match="either start_date/end_date or relative_period"):
        await call("get_report", start_date="2025-01-01", end_date="2025-01-31",
                   relative_period={"unit": "year", "value": 1})


async def test_report_filters_need_both_dates(call: Call) -> None:
    with pytest.raises(ToolError, match="both start_date and end_date"):
        await call("get_report", start_date="2025-01-01")


async def test_get_report_configurations(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"reportConfigurations": [{"id": "r1", "displayName": "Food"}]}
    assert await call("get_report_configurations") == [{"id": "r1", "displayName": "Food"}]
    assert gql_ops(mm) == [("Common_GetReportConfigurations", {})]


async def test_create_report_configuration(call: Call, mm: AsyncMock) -> None:
    config = {"id": "r1", "displayName": "Trips"}
    mm.gql_call.return_value = {"createReportConfiguration": {"reportConfiguration": config,
                                                              "errors": None}}
    result = await call("create_report_configuration", display_name="Trips", tag_ids=["t1"],
                        report_type="cashFlow", chart_type="sankeyCashFlowChart")
    assert result == config
    assert gql_input(mm) == {
        "displayName": "Trips",
        "transactionFilters": {"tags": ["t1"]},
        "reportView": {"analysisScope": "cashFlow", "chartType": "sankeyCashFlowChart",
                       "chartCalculation": "totalAmounts"},
    }


async def test_create_report_configuration_without_view(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createReportConfiguration": {"reportConfiguration": {},
                                                              "errors": None}}
    await call("create_report_configuration", display_name="All")
    assert gql_input(mm) == {"displayName": "All", "transactionFilters": {}}


async def test_create_report_configuration_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createReportConfiguration": {
        "reportConfiguration": None, "errors": {"message": "Name taken", "fieldErrors": []}}}
    with pytest.raises(ToolError, match="Name taken"):
        await call("create_report_configuration", display_name="Dup")


async def test_update_report_configuration(call: Call, mm: AsyncMock) -> None:
    config = {"id": "r1", "displayName": "Renamed"}
    mm.gql_call.return_value = {"updateReportConfiguration": {"reportConfiguration": config,
                                                              "errors": None}}
    result = await call("update_report_configuration", report_configuration_id="r1",
                        display_name="Renamed")
    assert result == config
    assert gql_input(mm) == {"id": "r1", "displayName": "Renamed"}


async def test_delete_report_configuration(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteReportConfiguration": {"deleted": True, "errors": None}}
    result = await call("delete_report_configuration", report_configuration_id="r1")
    assert result == {"report_configuration_id": "r1", "deleted": True}
    assert gql_ops(mm) == [("Common_DeleteReportConfiguration", {"id": "r1"})]


async def test_delete_report_configuration_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteReportConfiguration": {
        "deleted": False, "errors": {"message": "Not found", "fieldErrors": []}}}
    with pytest.raises(ToolError, match="Not found"):
        await call("delete_report_configuration", report_configuration_id="nope")
