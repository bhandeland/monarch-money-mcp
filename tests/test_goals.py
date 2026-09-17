from datetime import date
from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops


async def test_get_goals(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"migratedToSavingsGoals": True, "savingsGoals": []}
    assert await call("get_goals") == {"migratedToSavingsGoals": True, "savingsGoals": []}
    assert gql_ops(mm) == [("Common_SavingsGoals", {})]


async def test_create_goal_maps_fields(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createSavingsGoals": {"savingsGoals": [{"id": "g1"}]}}
    out = await call("create_goal", name="Trip", type="vacation", target_amount=3000,
                     target_date="2027-06-01", planned_monthly_contribution=250, priority=2,
                     is_sinking_fund=True)
    assert out == {"createSavingsGoals": {"savingsGoals": [{"id": "g1"}]}}
    assert gql_ops(mm)[0][0] == "Common_CreateSavingsGoals"
    assert gql_input(mm) == {"goals": [{
        "name": "Trip", "type": "vacation", "targetAmount": 3000, "targetDate": "2027-06-01",
        "plannedMonthlyContribution": 250, "priority": 2, "isSinkingFund": True}]}


async def test_create_goal_minimal(call: Call, mm: AsyncMock) -> None:
    await call("create_goal", name="Rainy day", type="emergency_fund")
    assert gql_input(mm) == {"goals": [{"name": "Rainy day", "type": "emergency_fund"}]}


async def test_create_goal_rejects_bad_date(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="does not match format"):
        await call("create_goal", name="x", type="car", target_date="soon")
    mm.gql_call.assert_not_awaited()


async def test_update_goal(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateSavingsGoal": {"savingsGoal": {"id": "g1"}, "errors": None}}
    assert await call("update_goal", goal_id="g1", target_amount=10, target_date="2027-01-01") == {"id": "g1"}
    assert gql_ops(mm)[0][0] == "Common_UpdateSavingsGoal"
    assert gql_input(mm) == {"id": "g1", "targetAmount": 10, "targetDate": "2027-01-01"}


async def test_update_goal_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateSavingsGoal": {"errors": {"message": "no such goal"}}}
    with pytest.raises(ToolError, match="Goal update failed: no such goal"):
        await call("update_goal", goal_id="g1", name="x")


@pytest.mark.parametrize("tool, operation, field, payload", [
    ("archive_goal", "Common_ArchiveSavingsGoal", "archiveSavingsGoal",
     {"savingsGoal": {"id": "g1", "status": "archived"}, "errors": None}),
    ("unarchive_goal", "Common_UnarchiveSavingsGoal", "unarchiveSavingsGoal",
     {"savingsGoal": {"id": "g1", "status": "active"}, "errors": None}),
    ("delete_goal", "Common_DeleteSavingsGoal", "deleteSavingsGoal",
     {"success": True, "errors": None}),
])
async def test_goal_id_mutations(call: Call, mm: AsyncMock, tool: str, operation: str,
                                 field: str, payload: dict[str, object]) -> None:
    mm.gql_call.return_value = {field: payload}
    assert await call(tool, goal_id="g1") == payload
    assert gql_ops(mm) == [(operation, {"input": {"id": "g1"}})]


@pytest.mark.parametrize("tool, field", [
    ("archive_goal", "archiveSavingsGoal"),
    ("unarchive_goal", "unarchiveSavingsGoal"),
    ("delete_goal", "deleteSavingsGoal"),
])
async def test_goal_id_mutations_surface_errors(call: Call, mm: AsyncMock, tool: str, field: str) -> None:
    mm.gql_call.return_value = {field: {"errors": {"message": "nope"}}}
    with pytest.raises(ToolError, match="failed: nope"):
        await call(tool, goal_id="g1")


@pytest.mark.parametrize("tool, operation", [
    ("contribute_to_goal", "Common_ContributeToSavingsGoal"),
    ("withdraw_from_goal", "Common_WithdrawFromSavingsGoal"),
])
async def test_goal_money_movements(call: Call, mm: AsyncMock, tool: str, operation: str) -> None:
    mm.gql_call.return_value = {"goalEvent": {"id": "e1"}}
    assert await call(tool, goal_id="g1", account_id="a1", amount=50) == {"goalEvent": {"id": "e1"}}
    await call(tool, goal_id="g1", account_id="a1", amount=5, date="2026-04-02", notes="bonus")
    assert gql_ops(mm) == [
        (operation, {"input": {"id": "g1", "accountId": "a1", "amount": 50}}),
        (operation, {"input": {"id": "g1", "accountId": "a1", "amount": 5,
                               "date": "2026-04-02", "notes": "bonus"}}),
    ]


async def test_set_goal_budget_amount(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setSavingsGoalBudgetAmount": {"success": True, "errors": None}}
    out = await call("set_goal_budget_amount", goal_id="g1", amount=200, month="2026-07-19",
                     apply_to_future=True, account_id="a1")
    assert out == {"success": True, "errors": None}
    assert gql_ops(mm)[0][0] == "Common_SetSavingsGoalBudgetAmount"
    assert gql_input(mm) == {"savingsGoalId": "g1", "amount": 200, "month": "2026-07-01",
                             "applyToFuture": True, "accountId": "a1"}


async def test_set_goal_budget_amount_defaults(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setSavingsGoalBudgetAmount": {"success": True}}
    await call("set_goal_budget_amount", goal_id="g1", amount=0)
    assert gql_input(mm) == {"savingsGoalId": "g1", "amount": 0,
                             "month": date.today().replace(day=1).isoformat(),
                             "applyToFuture": False, "accountId": None}


async def test_set_goal_budget_amount_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setSavingsGoalBudgetAmount": {
        "errors": {"fieldErrors": [{"field": "amount", "messages": ["must be positive"]}]}}}
    with pytest.raises(ToolError, match="Goal budget update failed: amount: must be positive"):
        await call("set_goal_budget_amount", goal_id="g1", amount=-1)
