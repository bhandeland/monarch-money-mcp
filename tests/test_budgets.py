from datetime import date
from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError


async def test_get_budgets(call: Call, mm: AsyncMock) -> None:
    mm.get_budgets.return_value = {"budgetData": {}}
    assert await call("get_budgets", start_date="2026-01-01", end_date="2026-02-28") == {"budgetData": {}}
    mm.get_budgets.assert_awaited_once_with(start_date="2026-01-01", end_date="2026-02-28")


async def test_get_budgets_none_configured(call: Call, mm: AsyncMock) -> None:
    mm.get_budgets.side_effect = RuntimeError("Something went wrong while processing: None")
    out = await call("get_budgets")
    assert out["budgets"] == [] and "No budgets" in out["message"]
    mm.get_budgets.assert_awaited_once_with(start_date=None, end_date=None)


async def test_get_budgets_other_errors_propagate(call: Call, mm: AsyncMock) -> None:
    mm.get_budgets.side_effect = RuntimeError("timeout")
    with pytest.raises(ToolError, match="timeout"):
        await call("get_budgets")


async def test_set_budget_amounts_per_item_results(call: Call, mm: AsyncMock) -> None:
    mm.set_budget_amount.side_effect = [{"ok": 1}, RuntimeError("bad category")]
    out = await call("set_budget_amounts", start_date="2026-05-20", apply_to_future=True, items=[
        {"category_id": "c1", "amount": 100},
        {"category_group_id": "g1", "amount": 0},
        {"category_id": "c2", "category_group_id": "g2", "amount": 5},
        {"amount": 5},
    ])
    assert (out["start_date"], out["apply_to_future"]) == ("2026-05-01", True)
    assert (out["succeeded"], out["failed"]) == (1, 3)
    assert [r["ok"] for r in out["results"]] == [True, False, False, False]
    assert out["results"][0]["response"] == {"ok": 1}
    assert out["results"][1]["error"] == "bad category"
    assert "exactly one" in out["results"][2]["error"] and "exactly one" in out["results"][3]["error"]
    assert [c.kwargs for c in mm.set_budget_amount.await_args_list] == [
        dict(amount=100, category_id="c1", category_group_id=None, start_date="2026-05-01", apply_to_future=True),
        dict(amount=0, category_id=None, category_group_id="g1", start_date="2026-05-01", apply_to_future=True),
    ]


async def test_set_budget_amounts_defaults(call: Call, mm: AsyncMock) -> None:
    mm.set_budget_amount.return_value = {}
    out = await call("set_budget_amounts", items=[{"category_id": "c1", "amount": 1}])
    assert (out["start_date"], out["apply_to_future"]) == ("current month", False)
    kwargs = mm.set_budget_amount.await_args.kwargs
    assert (kwargs["start_date"], kwargs["apply_to_future"]) == (None, False)


@pytest.mark.parametrize("tool, method", [
    ("get_cashflow", "get_cashflow"),
    ("get_cashflow_summary", "get_cashflow_summary"),
    ("get_recurring_transactions", "get_recurring_transactions"),
])
async def test_date_range_reads(call: Call, mm: AsyncMock, tool: str, method: str) -> None:
    getattr(mm, method).return_value = {"when": date(2026, 1, 1)}
    assert await call(tool, start_date="2026-01-01", end_date="2026-01-31") == {"when": "2026-01-01"}
    assert await call(tool) == {"when": "2026-01-01"}
    assert [c.kwargs for c in getattr(mm, method).await_args_list] == [
        {"start_date": "2026-01-01", "end_date": "2026-01-31"},
        {"start_date": None, "end_date": None},
    ]
    with pytest.raises(ToolError, match="both"):
        await call(tool, end_date="2026-01-31")
