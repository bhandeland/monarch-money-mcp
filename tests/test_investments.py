from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops


# --- reads ------------------------------------------------------------------------

async def test_get_portfolio_defaults(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"portfolio": {"performance": {"totalValue": 10}}}
    assert await call("get_portfolio") == {"performance": {"totalValue": 10}}
    assert gql_ops(mm) == [("Web_GetPortfolio", {"portfolioInput": {}})]


async def test_get_portfolio_filters(call: Call, mm: AsyncMock) -> None:
    await call("get_portfolio", account_ids=["a1", "a2"], start_date="2026-01-01",
               end_date="2026-06-30", include_hidden_holdings=True)
    assert gql_ops(mm) == [("Web_GetPortfolio", {"portfolioInput": {
        "accountIds": ["a1", "a2"], "startDate": "2026-01-01", "endDate": "2026-06-30",
        "includeHiddenHoldings": True}})]


async def test_get_portfolio_needs_both_dates(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="both start_date and end_date"):
        await call("get_portfolio", start_date="2026-01-01")
    mm.gql_call.assert_not_awaited()


async def test_search_securities(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"securities": [{"id": "s1", "ticker": "VTI"}]}
    assert await call("search_securities", query="vti") == [{"id": "s1", "ticker": "VTI"}]
    assert gql_ops(mm) == [("SecuritySearch",
                            {"search": "vti", "limit": 20, "orderByPopularity": True})]


async def test_search_securities_limit(call: Call, mm: AsyncMock) -> None:
    await call("search_securities", query="apple", limit=5)
    assert gql_ops(mm)[0][1]["limit"] == 5


async def test_get_security(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"security": {"id": "s1", "name": "Vanguard"}}
    assert await call("get_security", security_id="s1") == {"id": "s1", "name": "Vanguard"}
    assert gql_ops(mm) == [("Common_GetSecurityDetails", {"id": "s1"})]


async def test_get_security_performance(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"securityHistoricalPerformance": [{"security": {"id": "s1"}}]}
    out = await call("get_security_performance", security_ids=["s1", "s2"],
                     start_date="2026-01-01", end_date="2026-02-01")
    assert out == [{"security": {"id": "s1"}}]
    assert gql_ops(mm) == [("Web_GetSecuritiesHistoricalPerformance", {"input": {
        "securityIds": ["s1", "s2"], "startDate": "2026-01-01", "endDate": "2026-02-01"}})]


async def test_get_security_performance_without_dates(call: Call, mm: AsyncMock) -> None:
    await call("get_security_performance", security_ids=["s1"])
    assert gql_input(mm) == {"securityIds": ["s1"]}


async def test_get_security_types(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"securityTypes": [{"type": "etf", "typeDisplay": "ETF"}]}
    assert await call("get_security_types") == [{"type": "etf", "typeDisplay": "ETF"}]
    assert gql_ops(mm) == [("Common_GetSecurityTypes", {})]


async def test_get_allocation_categories(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"myHousehold": {"id": "h", "allocationCategories": [{"slug": "us_stocks"}]}}
    assert await call("get_allocation_categories") == [{"slug": "us_stocks"}]
    assert gql_ops(mm) == [("Web_GetAllocationCategoriesForClassification", {})]


# --- holdings -----------------------------------------------------------------------

async def test_create_manual_holding(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createManualHolding": {"holding": {"id": "h1"}, "errors": None}}
    out = await call("create_manual_holding", account_id="a1", security_id="s1", quantity=2.5)
    assert out == {"id": "h1"}
    assert gql_ops(mm)[0][0] == "Common_CreateManualHolding"
    assert gql_input(mm) == {"accountId": "a1", "securityId": "s1", "quantity": 2.5}


async def test_create_manual_holding_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createManualHolding": {"errors": {
        "message": None, "fieldErrors": [{"field": "quantity", "messages": ["too big"]}]}}}
    with pytest.raises(ToolError, match="Holding creation failed: quantity: too big"):
        await call("create_manual_holding", account_id="a1", security_id="s1", quantity=1e12)


async def test_update_holding(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateHolding": {"holding": {"id": "h1"}, "errors": None}}
    out = await call("update_holding", holding_id="h1", quantity=3, cost_basis=150.5,
                     security_type="etf")
    assert out == {"id": "h1"}
    assert gql_ops(mm)[0][0] == "Common_UpdateHolding"
    assert gql_input(mm) == {"id": "h1", "quantity": 3, "userCostBasis": 150.5,
                             "securityType": "etf"}


async def test_update_holding_only_sends_given_fields(call: Call, mm: AsyncMock) -> None:
    await call("update_holding", holding_id="h1", quantity=0)
    assert gql_input(mm) == {"id": "h1", "quantity": 0}


async def test_update_holding_needs_a_change(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("update_holding", holding_id="h1")
    mm.gql_call.assert_not_awaited()


async def test_delete_holding(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteHolding": {"deleted": True, "errors": None}}
    assert await call("delete_holding", holding_id="h1") == {"deleted": True}
    assert gql_ops(mm) == [("Common_DeleteHolding", {"id": "h1"})]


async def test_delete_holding_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteHolding": {"deleted": False,
                                                  "errors": {"message": "synced holding"}}}
    with pytest.raises(ToolError, match="Holding deletion failed: synced holding"):
        await call("delete_holding", holding_id="h1")


# --- manual investment accounts --------------------------------------------------------

async def test_create_manual_investments_account_with_holdings(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createManualInvestmentsAccount": {"account": {"id": "a9"},
                                                                   "errors": None}}
    out = await call("create_manual_investments_account", name="ZZ Brokerage",
                     subtype="brokerage", tracking_method="holdings",
                     initial_holdings=[{"security_id": "s1", "quantity": 10}])
    assert out == {"id": "a9"}
    assert gql_ops(mm)[0][0] == "Common_CreateManualInvestmentsAccount"
    assert gql_input(mm) == {"name": "ZZ Brokerage", "subtype": "brokerage",
                             "manualInvestmentsTrackingMethod": "holdings",
                             "initialHoldings": [{"securityId": "s1", "quantity": 10}]}


async def test_create_manual_investments_account_with_balance(call: Call, mm: AsyncMock) -> None:
    await call("create_manual_investments_account", name="ZZ 401k", subtype="st_401k",
               tracking_method="balances", initial_balance=1234.5)
    assert gql_input(mm) == {"name": "ZZ 401k", "subtype": "st_401k",
                             "manualInvestmentsTrackingMethod": "balances",
                             "initialBalance": 1234.5}


async def test_create_manual_investments_account_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createManualInvestmentsAccount": {"errors": {"message": "bad subtype"}}}
    with pytest.raises(ToolError, match="Investment account creation failed: bad subtype"):
        await call("create_manual_investments_account", name="x", subtype="nope",
                   tracking_method="balances")


async def test_create_manual_investments_account_rejects_bad_method(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError):
        await call("create_manual_investments_account", name="x", subtype="brokerage",
                   tracking_method="vibes")
    mm.gql_call.assert_not_awaited()


# --- classification -------------------------------------------------------------------

async def test_set_holding_classification(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setHoldingClassification": {
        "holdingClassification": {"id": "c1"}, "errors": None}}
    out = await call("set_holding_classification", holding_id="h1", category_slug="us_stocks")
    assert out == {"id": "c1"}
    assert gql_ops(mm)[0][0] == "Web_SetHoldingClassification"
    assert gql_input(mm) == {"holdingId": "h1", "categorySlug": "us_stocks"}


async def test_set_security_classification(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setSecurityClassification": {
        "securityClassification": {"id": "c2"}, "errors": None}}
    out = await call("set_security_classification", security_id="s1", category_slug="bonds")
    assert out == {"id": "c2"}
    assert gql_ops(mm)[0][0] == "Web_SetSecurityClassification"
    assert gql_input(mm) == {"securityId": "s1", "categorySlug": "bonds"}


async def test_set_classification_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setSecurityClassification": {"errors": {"message": "unknown slug"}}}
    with pytest.raises(ToolError, match="Security classification failed: unknown slug"):
        await call("set_security_classification", security_id="s1", category_slug="nope")


async def test_clear_holding_classification(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"clearHoldingClassification": {"deleted": True, "errors": None}}
    assert await call("clear_holding_classification", holding_id="h1") == {"deleted": True}
    assert gql_ops(mm) == [("Web_ClearHoldingClassification", {"holdingId": "h1"})]


async def test_clear_security_classification(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"clearSecurityClassification": {"deleted": True, "errors": None}}
    assert await call("clear_security_classification", security_id="s1") == {"deleted": True}
    assert gql_ops(mm) == [("Web_ClearSecurityClassification", {"securityId": "s1"})]


async def test_clear_classification_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"clearHoldingClassification": {"deleted": False,
                                                               "errors": {"message": "nope"}}}
    with pytest.raises(ToolError, match="Holding classification reset failed: nope"):
        await call("clear_holding_classification", holding_id="h1")
