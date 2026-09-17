from datetime import date
from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops

THIS_MONTH = date.today().replace(day=1).isoformat()


async def test_get_budget_settings(call: Call, mm: AsyncMock) -> None:
    settings = {"budgetSystem": "fixed_and_flex", "budgetApplyToFutureMonthsDefault": None,
                "flexExpenseRolloverPeriod": None,
                "budgetStatus": {"hasBudget": True, "hasTransactions": True,
                                 "willCreateBudgetFromEmptyDefaultCategories": False}}
    mm.gql_call.return_value = settings
    assert await call("get_budget_settings") == settings
    assert gql_ops(mm) == [("Common_GetBudgetSettings", {})]


# --- move_budget_money --------------------------------------------------------------

MOVED = {"moveMoneyBetweenCategories": {
    "fromBudgetItem": {"id": "b1", "budgetAmount": 90},
    "toBudgetItem": {"id": "b2", "budgetAmount": 60},
    "errors": None,
}}


async def test_move_budget_money_between_categories(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = MOVED
    out = await call("move_budget_money", amount=10, start_date="2027-03-15",
                     from_category_id="c1", to_category_group_id="g2")
    assert out == {"start_date": "2027-03-01",
                   "from": {"id": "b1", "budgetAmount": 90},
                   "to": {"id": "b2", "budgetAmount": 60}}
    assert gql_ops(mm)[0][0] == "Web_MoveMoneyMutation"
    assert gql_input(mm) == {"amount": 10, "startDate": "2027-03-01", "timeframe": "month",
                             "fromCategoryId": "c1", "toCategoryGroupId": "g2"}


async def test_move_budget_money_flex_defaults_to_this_month(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = MOVED
    out = await call("move_budget_money", amount=5.5, from_flex=True, to_category_id="c9")
    assert out["start_date"] == THIS_MONTH
    assert gql_input(mm) == {"amount": 5.5, "startDate": THIS_MONTH, "timeframe": "month",
                             "fromBudgetTarget": "flex_expense", "toCategoryId": "c9"}


@pytest.mark.parametrize("args, message", [
    ({"to_category_id": "c2"}, "exactly one of from_category_id"),
    ({"from_category_id": "c1", "from_flex": True, "to_category_id": "c2"}, "exactly one of from_"),
    ({"from_category_id": "c1", "from_category_group_id": "g1", "to_category_id": "c2"},
     "exactly one of from_"),
    ({"from_category_id": "c1"}, "exactly one of to_category_id"),
    ({"from_category_id": "c1", "to_flex": False}, "exactly one of to_"),
    ({"from_category_id": "c1", "to_category_id": "c1"}, "different"),
    ({"from_flex": True, "to_flex": True}, "different"),
])
async def test_move_budget_money_needs_one_source_and_destination(
        call: Call, mm: AsyncMock, args: dict[str, object], message: str) -> None:
    with pytest.raises(ToolError, match=message):
        await call("move_budget_money", amount=1, **args)
    mm.gql_call.assert_not_awaited()


@pytest.mark.parametrize("amount", [0, -3])
async def test_move_budget_money_needs_positive_amount(call: Call, mm: AsyncMock, amount: float) -> None:
    with pytest.raises(ToolError, match="amount must be greater than 0"):
        await call("move_budget_money", amount=amount, from_category_id="c1", to_category_id="c2")
    mm.gql_call.assert_not_awaited()


async def test_move_budget_money_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"moveMoneyBetweenCategories": {
        "fromBudgetItem": None, "toBudgetItem": None, "errors": {"message": "Not enough money"}}}
    with pytest.raises(ToolError, match="Moving budget money failed: Not enough money"):
        await call("move_budget_money", amount=1, from_category_id="c1", to_category_id="c2")


# --- set_flex_budget_amount ---------------------------------------------------------

async def test_set_flex_budget_amount(call: Call, mm: AsyncMock) -> None:
    mm.update_flexible_budget.return_value = {
        "updateOrCreateFlexBudgetItem": {"budgetItem": {"id": "f1", "budgetAmount": 1200}}}
    out = await call("set_flex_budget_amount", amount=1200, start_date="2027-02-10",
                     apply_to_future=True)
    assert out == {"start_date": "2027-02-01", "apply_to_future": True,
                   "budget_item": {"id": "f1", "budgetAmount": 1200}}
    mm.update_flexible_budget.assert_awaited_once_with(
        amount=1200, start_date="2027-02-01", apply_to_future=True)


async def test_set_flex_budget_amount_defaults(call: Call, mm: AsyncMock) -> None:
    mm.update_flexible_budget.return_value = {"updateOrCreateFlexBudgetItem": None}
    out = await call("set_flex_budget_amount", amount=0)
    assert out == {"start_date": "current month", "apply_to_future": False, "budget_item": None}
    mm.update_flexible_budget.assert_awaited_once_with(
        amount=0, start_date=None, apply_to_future=False)


# --- update_budget_settings ---------------------------------------------------------

SETTINGS_UPDATED = {"updateBudgetSettings": {
    "budgetSystem": "fixed_and_flex", "budgetApplyToFutureMonthsDefault": True,
    "budgetRolloverPeriod": None}}


async def test_update_budget_settings_apply_to_future_only(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = SETTINGS_UPDATED
    assert await call("update_budget_settings", apply_to_future_default=True) == \
        SETTINGS_UPDATED["updateBudgetSettings"]
    assert [name for name, _ in gql_ops(mm)] == ["Common_UpdateBudgetSettings"]
    assert gql_input(mm) == {"budgetApplyToFutureMonthsDefault": True}


async def test_update_budget_settings_rollover_keeps_current_period(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [
        {"budgetSystem": "fixed_and_flex",
         "flexExpenseRolloverPeriod": {"id": "p1", "startMonth": "2026-01-01", "startingBalance": 75}},
        SETTINGS_UPDATED,
    ]
    await call("update_budget_settings", flex_rollover_starting_balance=0)
    [(first, _), (second, variables)] = gql_ops(mm)
    assert (first, second) == ("Common_GetBudgetSettings", "Common_UpdateBudgetSettings")
    assert variables["input"] == {"rolloverEnabled": True, "rolloverStartMonth": "2026-01-01",
                                  "rolloverStartingBalance": 0}


async def test_update_budget_settings_enable_rollover_defaults(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [{"budgetSystem": "fixed_and_flex", "flexExpenseRolloverPeriod": None},
                               SETTINGS_UPDATED]
    await call("update_budget_settings", flex_rollover_enabled=True, apply_to_future_default=False)
    assert gql_ops(mm)[1][1]["input"] == {
        "budgetApplyToFutureMonthsDefault": False, "rolloverEnabled": True,
        "rolloverStartMonth": THIS_MONTH, "rolloverStartingBalance": 0}


async def test_update_budget_settings_explicit_rollover(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [{"flexExpenseRolloverPeriod": None}, SETTINGS_UPDATED]
    await call("update_budget_settings", flex_rollover_enabled=False,
               flex_rollover_start_month="2026-04-09", flex_rollover_starting_balance=12.5)
    assert gql_ops(mm)[1][1]["input"] == {"rolloverEnabled": False,
                                          "rolloverStartMonth": "2026-04-01",
                                          "rolloverStartingBalance": 12.5}


async def test_update_budget_settings_needs_a_change(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("update_budget_settings")
    mm.gql_call.assert_not_awaited()


# --- reset_budget_rollover ----------------------------------------------------------

async def test_reset_budget_rollover(call: Call, mm: AsyncMock) -> None:
    period = {"id": "p9", "startMonth": "2027-01-01", "startingBalance": 40}
    mm.gql_call.return_value = {"resetBudgetRollover": {"budgetRolloverPeriod": period, "errors": None}}
    assert await call("reset_budget_rollover", category_id="c1", start_month="2027-01-20",
                      starting_balance=40) == period
    assert gql_ops(mm)[0][0] == "Web_ResetRolloverMutation"
    assert gql_input(mm) == {"categoryId": "c1", "startMonth": "2027-01-01", "startingBalance": 40}


async def test_reset_budget_rollover_group_without_balance(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"resetBudgetRollover": {"budgetRolloverPeriod": {}, "errors": None}}
    await call("reset_budget_rollover", category_group_id="g1", start_month="2027-01-01")
    assert gql_input(mm) == {"categoryGroupId": "g1", "startMonth": "2027-01-01"}


@pytest.mark.parametrize("ids", [{}, {"category_id": "c1", "category_group_id": "g1"}])
async def test_reset_budget_rollover_needs_one_target(call: Call, mm: AsyncMock,
                                                      ids: dict[str, str]) -> None:
    with pytest.raises(ToolError, match="exactly one of category_id or category_group_id"):
        await call("reset_budget_rollover", start_month="2027-01-01", **ids)
    mm.gql_call.assert_not_awaited()


async def test_reset_budget_rollover_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"resetBudgetRollover": {"errors": {"message": "no rollover"}}}
    with pytest.raises(ToolError, match="Rollover reset failed: no rollover"):
        await call("reset_budget_rollover", category_id="c1", start_month="2027-01-01")
