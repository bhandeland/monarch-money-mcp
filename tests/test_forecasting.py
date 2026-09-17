from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops


# --- cash flow projection -----------------------------------------------------------

async def test_get_cash_flow_projection(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"cashFlowProjection": {"safeToSpend": 120.5}}
    out = await call("get_cash_flow_projection", account_id="a1",
                     start_date="2026-09-01", end_date="2026-09-30")
    assert out == {"safeToSpend": 120.5}
    assert gql_ops(mm) == [("Common_GetCashFlowProjection", {
        "accountId": "a1", "startDate": "2026-09-01", "endDate": "2026-09-30"})]


async def test_get_cash_flow_projection_days(call: Call, mm: AsyncMock) -> None:
    await call("get_cash_flow_projection", account_id="a1", days=14)
    assert gql_ops(mm) == [("Common_GetCashFlowProjection", {"accountId": "a1", "days": 14})]


async def test_get_cash_flow_projection_needs_both_dates(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="both start_date and end_date"):
        await call("get_cash_flow_projection", account_id="a1", start_date="2026-09-01")
    mm.gql_call.assert_not_awaited()


# --- forecast scenarios ---------------------------------------------------------------

async def test_get_forecast_scenarios(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"forecastScenarios": [{"externalId": "s1"}]}
    assert await call("get_forecast_scenarios") == [{"externalId": "s1"}]
    assert gql_ops(mm) == [("Web_ForecastScenarios", {})]


async def test_get_forecast_scenario(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"forecastScenario": {"externalId": "s1"}, "me": {"id": "u"}}
    assert await call("get_forecast_scenario", scenario_id="s1") == {"externalId": "s1"}
    assert gql_ops(mm) == [("Web_ForecastScenario", {"externalId": "s1"})]


async def test_get_forecast_scenario_default(call: Call, mm: AsyncMock) -> None:
    await call("get_forecast_scenario")
    assert gql_ops(mm) == [("Web_ForecastScenario", {})]


async def test_create_forecast_scenario(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createForecastScenario": {
        "scenario": {"externalId": "s2"}, "errors": None}}
    assert await call("create_forecast_scenario", name="Early retirement", color="blue") == {
        "externalId": "s2"}
    assert gql_ops(mm)[0][0] == "Web_CreateForecastScenario"
    assert gql_input(mm) == {"name": "Early retirement", "color": "blue"}


async def test_create_forecast_scenario_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createForecastScenario": {"errors": {"message": "limit"}}}
    with pytest.raises(ToolError, match="Forecast scenario creation failed: limit"):
        await call("create_forecast_scenario", name="x")


async def test_update_forecast_scenario_uses_current_version(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [
        {"forecastScenario": {"externalId": "s1", "categoryVersions": {"settingsVersion": 7}}},
        {"updateForecastScenario": {"newVersion": 8, "scenario": {"externalId": "s1"},
                                    "errors": None}},
    ]
    out = await call("update_forecast_scenario", scenario_id="s1", name="Plan B",
                     inflation_rate=2.5, projection_years=40, use_actuals_as_baseline=True,
                     split_uncategorized_savings=False, dollar_mode="todaysDollars",
                     icon="🏖️", color="green")
    assert out == {"newVersion": 8, "scenario": {"externalId": "s1"}, "errors": None}
    ops = gql_ops(mm)
    assert ops[0] == ("Common_ForecastScenarioSettingsVersion", {"externalId": "s1"})
    assert ops[1] == ("Web_UpdateForecastScenario", {"input": {
        "scenarioExternalId": "s1", "expectedVersion": 7, "name": "Plan B",
        "inflationRate": 2.5, "projectionYears": 40, "useActualsAsBaseline": True,
        "splitUncategorizedSavings": False, "dollarMode": "todaysDollars",
        "icon": "🏖️", "color": "green"}})


async def test_update_forecast_scenario_unknown(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"forecastScenario": None}
    with pytest.raises(ToolError, match="No forecast scenario s9"):
        await call("update_forecast_scenario", scenario_id="s9", name="x")
    assert len(gql_ops(mm)) == 1


async def test_update_forecast_scenario_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [
        {"forecastScenario": {"externalId": "s1", "categoryVersions": {"settingsVersion": 1}}},
        {"updateForecastScenario": {"errors": {"message": "version conflict"}}},
    ]
    with pytest.raises(ToolError, match="Forecast scenario update failed: version conflict"):
        await call("update_forecast_scenario", scenario_id="s1", name="x")


async def test_duplicate_forecast_scenario(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"duplicateForecastScenario": {
        "scenario": {"externalId": "s3"}, "errors": None}}
    assert await call("duplicate_forecast_scenario", scenario_id="s1") == {"externalId": "s3"}
    assert gql_ops(mm)[0][0] == "Web_DuplicateForecastScenario"
    assert gql_input(mm) == {"sourceScenarioExternalId": "s1"}


async def test_delete_forecast_scenario(call: Call, mm: AsyncMock) -> None:
    payload = {"deleted": True, "deletedScenarioExternalId": "s3", "errors": None, "scenarios": []}
    mm.gql_call.return_value = {"deleteForecastScenario": payload}
    assert await call("delete_forecast_scenario", scenario_id="s3") == payload
    assert gql_ops(mm)[0][0] == "Web_DeleteForecastScenario"
    assert gql_input(mm) == {"scenarioExternalId": "s3"}


async def test_delete_forecast_scenario_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteForecastScenario": {"errors": {"message": "last one"}}}
    with pytest.raises(ToolError, match="Forecast scenario deletion failed: last one"):
        await call("delete_forecast_scenario", scenario_id="s1")


# --- debt paydown ---------------------------------------------------------------------

async def test_get_debt_accounts(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"debtAccounts": [{"id": "d1"}]}
    assert await call("get_debt_accounts") == [{"id": "d1"}]
    assert gql_ops(mm) == [("Common_DebtPaydownAccounts", {})]


async def test_get_debt_paydown_plan(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"debtAccounts": [], "debtProjectionForecastLimit": 30,
                                "debtPaydownPlan": {"debtFreeDate": "2030-01-01"}}
    out = await call("get_debt_paydown_plan", method="snowball",
                     additional_monthly_payment=200, additional_one_time_payment=1000)
    assert out["debtPaydownPlan"] == {"debtFreeDate": "2030-01-01"}
    assert gql_ops(mm) == [("Common_DebtPaydown", {"input": {
        "debtPaydownMethod": "snowball", "additionalMonthlyPayment": 200,
        "additionalOneTimePayment": 1000}})]


async def test_get_debt_paydown_plan_defaults_to_avalanche(call: Call, mm: AsyncMock) -> None:
    await call("get_debt_paydown_plan")
    assert gql_ops(mm) == [("Common_DebtPaydown", {"input": {"debtPaydownMethod": "avalanche"}})]


async def test_get_debt_paydown_budget_amounts(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"debtPaydownMonthlyBudgetAmounts": [{"id": "x"}]}
    out = await call("get_debt_paydown_budget_amounts",
                     start_month="2026-09-15", end_month="2026-12-31")
    assert out == [{"id": "x"}]
    assert gql_ops(mm) == [("Common_DebtPaydownMonthlyBudgetAmounts", {
        "startMonth": "2026-09-01", "endMonth": "2026-12-01"})]


async def test_set_debt_paydown_budget_amount(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setDebtPaydownBudgetAmount": {"success": True, "errors": None}}
    out = await call("set_debt_paydown_budget_amount", account_id="d1", month="2026-10-20",
                     amount=450, apply_to_future=True)
    assert out == {"success": True, "errors": None}
    assert gql_ops(mm)[0][0] == "Common_SetDebtPaydownBudgetAmount"
    assert gql_input(mm) == {"accountId": "d1", "month": "2026-10-01", "amount": 450,
                             "applyToFuture": True}


async def test_set_debt_paydown_budget_amount_clears(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setDebtPaydownBudgetAmount": {"success": True, "errors": None}}
    await call("set_debt_paydown_budget_amount", account_id="d1", month="2026-10-01")
    assert gql_input(mm) == {"accountId": "d1", "month": "2026-10-01", "amount": None}


async def test_set_debt_paydown_budget_amount_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setDebtPaydownBudgetAmount": {
        "success": False, "errors": {"fieldErrors": [{"field": "month", "messages": ["bad"]}]}}}
    with pytest.raises(ToolError, match="Debt payment budget update failed: month: bad"):
        await call("set_debt_paydown_budget_amount", account_id="d1", month="2026-10-01",
                   amount=1)


# --- paychecks ------------------------------------------------------------------------

async def test_get_paychecks(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"paychecks": [{"id": "p1"}]}
    out = await call("get_paychecks", start_date="2026-01-01", end_date="2026-06-30",
                     owner_id="u1", employer_id="e1")
    assert out == [{"id": "p1"}]
    assert gql_ops(mm) == [("Common_GetPaychecks", {
        "startDate": "2026-01-01", "endDate": "2026-06-30", "ownerId": "u1", "employerId": "e1"})]


async def test_get_paychecks_all(call: Call, mm: AsyncMock) -> None:
    await call("get_paychecks")
    assert gql_ops(mm) == [("Common_GetPaychecks", {})]


async def test_get_paycheck(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"paycheck": {"id": "p1"}}
    assert await call("get_paycheck", paycheck_id="p1") == {"id": "p1"}
    assert gql_ops(mm) == [("Common_GetPaycheck", {"id": "p1"})]


async def test_get_paychecks_summary(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"paychecksSummary": {"count": 2}}
    out = await call("get_paychecks_summary", start_date="2026-01-01", end_date="2026-12-31",
                     owner_ids=["u1"], employer_id="e1")
    assert out == {"count": 2}
    assert gql_ops(mm) == [("Common_GetPaychecksSummary", {
        "startDate": "2026-01-01", "endDate": "2026-12-31", "ownerIds": ["u1"],
        "employerId": "e1"})]


async def test_get_paycheck_employers(call: Call, mm: AsyncMock) -> None:
    resp = {"paycheckEmployers": [{"id": "e1"}], "paycheckEmployerCount": 1}
    mm.gql_call.return_value = resp
    assert await call("get_paycheck_employers", search="Acme", limit=10, offset=5) == resp
    assert gql_ops(mm) == [("Common_GetPaycheckEmployers",
                            {"search": "Acme", "limit": 10, "offset": 5})]


async def test_create_paycheck(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createPaycheck": {"paycheck": {"id": "p1"}, "errors": None}}
    out = await call(
        "create_paycheck", employer_id="e1", gross_amount=5000, pay_date="2026-09-15",
        pay_period_start="2026-09-01", pay_period_end="2026-09-14", owner_id="u1",
        payroll_provider="gusto",
        deductions=[{"deduction_type": "federal_income_tax", "amount": 700},
                    {"deduction_type": "custom", "amount": 20, "custom_name": "Gym"}],
        deposit_transaction_ids=["t1"])
    assert out == {"id": "p1"}
    assert gql_ops(mm)[0][0] == "Common_CreatePaycheck"
    assert gql_input(mm) == {
        "employerId": "e1", "grossAmount": 5000, "payDate": "2026-09-15",
        "payPeriodStart": "2026-09-01", "payPeriodEnd": "2026-09-14", "ownerId": "u1",
        "payrollProvider": "gusto",
        "deductions": [{"deductionType": "federal_income_tax", "amount": 700},
                       {"deductionType": "custom", "amount": 20, "customDeductionName": "Gym"}],
        "deposits": [{"transactionId": "t1"}]}


async def test_create_paycheck_rejects_bad_date(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="does not match format"):
        await call("create_paycheck", employer_id="e1", gross_amount=1, pay_date="Friday")
    mm.gql_call.assert_not_awaited()


async def test_create_paycheck_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createPaycheck": {"errors": {
        "message": None, "fieldErrors": [{"field": "grossAmount", "messages": ["too big"]}]}}}
    with pytest.raises(ToolError, match="Paycheck creation failed: grossAmount: too big"):
        await call("create_paycheck", employer_id="e1", gross_amount=1, pay_date="2026-09-15")


async def test_update_paycheck(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updatePaycheck": {"paycheck": {"id": "p1"}, "errors": None}}
    out = await call("update_paycheck", paycheck_id="p1", gross_amount=5100,
                     pay_date="2026-09-16", deductions=[])
    assert out == {"id": "p1"}
    assert gql_ops(mm)[0][0] == "Common_UpdatePaycheck"
    assert gql_input(mm) == {"id": "p1", "grossAmount": 5100, "payDate": "2026-09-16",
                             "deductions": []}


async def test_delete_paycheck(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deletePaycheck": {"success": True, "errors": None}}
    assert await call("delete_paycheck", paycheck_id="p1") == {"success": True, "errors": None}
    assert gql_ops(mm)[0][0] == "Common_DeletePaycheck"
    assert gql_input(mm) == {"id": "p1"}


async def test_create_paycheck_employer(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createPaycheckEmployer": {"employer": {"id": "e1"},
                                                           "errors": None}}
    assert await call("create_paycheck_employer", name="Acme") == {"id": "e1"}
    assert gql_ops(mm)[0][0] == "Common_CreatePaycheckEmployer"
    assert gql_input(mm) == {"name": "Acme"}


async def test_update_paycheck_employer(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updatePaycheckEmployer": {"employer": {"id": "e1"},
                                                           "errors": None}}
    assert await call("update_paycheck_employer", employer_id="e1", name="Acme Inc") == {
        "id": "e1"}
    assert gql_input(mm) == {"id": "e1", "name": "Acme Inc"}


async def test_update_paycheck_employer_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updatePaycheckEmployer": {"errors": {"message": "taken"}}}
    with pytest.raises(ToolError, match="Paycheck employer update failed: taken"):
        await call("update_paycheck_employer", employer_id="e1", name="x")


async def test_delete_paycheck_employer(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deletePaycheckEmployer": {"success": True, "errors": None}}
    out = await call("delete_paycheck_employer", employer_id="e1")
    assert out == {"success": True, "errors": None}
    assert gql_ops(mm) == [("Common_DeletePaycheckEmployer", {"id": "e1"})]
