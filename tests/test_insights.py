from datetime import date
from typing import Any
from unittest.mock import AsyncMock

import pytest

import server
from tests.helpers import Call, ToolError, gql_input, gql_ops


# --- Insights -------------------------------------------------------------------

async def test_get_insights_defaults(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"insights": [{"id": "i1"}]}
    assert await call("get_insights") == [{"id": "i1"}]
    assert gql_ops(mm) == [("Common_GetInsights", {"limit": 50})]


async def test_get_insights_filters(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"insights": []}
    await call("get_insights", status=["new", "in_progress"], bookmarked=True, dismissed=False,
               unhelpful=False, limit=5, offset=10)
    assert gql_ops(mm) == [("Common_GetInsights", {
        "statuses": ["new", "in_progress"], "bookmarked": True, "dismissed": False,
        "unhelpful": False, "limit": 5, "offset": 10})]


async def test_get_insight(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"insight": {"id": "i1", "status": "new"}}
    assert await call("get_insight", insight_id="i1") == {"id": "i1", "status": "new"}
    assert gql_ops(mm) == [("Common_GetInsight", {"id": "i1"})]


async def test_get_insight_counts(call: Call, mm: AsyncMock) -> None:
    data = {"insightCounts": {"completed": 1, "bookmarked": 2, "dismissed": 3, "unhelpful": 0},
            "insightSurfacedValueTotal": 120.5}
    mm.gql_call.return_value = data
    assert await call("get_insight_counts") == data
    assert gql_ops(mm) == [("Common_GetInsightCounts", {})]


@pytest.mark.parametrize("tool, args, operation, field, expected_input, result_key", [
    ("update_insight_status",
     {"insight_id": "i1", "status": "denied", "denial_reason": "not relevant",
      "allow_resurface": False, "mute_subject": True},
     "Common_UpdateInsightStatus", "updateInsightStatus",
     {"id": "i1", "status": "denied", "denialReason": "not relevant", "allowResurface": False,
      "muteSubject": True},
     "insight"),
    ("set_insight_bookmarked", {"insight_id": "i1", "bookmarked": True},
     "Common_SetInsightBookmarked", "setInsightBookmarked",
     {"id": "i1", "bookmarked": True}, "insight"),
    ("set_insight_feedback", {"insight_id": "i1", "feedback": "dislike", "reason": "wrong"},
     "Common_SetInsightFeedback", "setInsightFeedback",
     {"id": "i1", "feedback": "dislike", "reason": "wrong"}, "insight"),
    ("set_insight_feedback", {"insight_id": "i1"},
     "Common_SetInsightFeedback", "setInsightFeedback",
     {"id": "i1", "feedback": None}, "insight"),
    ("dismiss_insight", {"insight_id": "i1"},
     "Common_SoftDeleteInsight", "softDeleteInsight", {"id": "i1"}, "deleted"),
    ("undo_insight_denial", {"insight_id": "i1"},
     "Common_UndoInsightDenial", "undoInsightDenial", {"id": "i1"}, "insight"),
    ("update_financial_insight_status",
     {"financial_insight_id": "f1", "status": "in_progress", "execution_method": "self_guided",
      "denial_reason": "later", "allow_resurface": True},
     "Common_UpdateFinancialInsightStatus", "updateFinancialInsightStatus",
     {"id": "f1", "status": "in_progress", "executionMethod": "self_guided",
      "denialReason": "later", "allowResurface": True},
     "financialInsight"),
])
async def test_insight_mutations(call: Call, mm: AsyncMock, tool: str, args: dict[str, Any],
                                 operation: str, field: str, expected_input: dict[str, Any],
                                 result_key: str) -> None:
    mm.gql_call.return_value = {field: {result_key: {"id": "x"}, "errors": None}}
    assert await call(tool, **args) == {"id": "x"}
    assert gql_ops(mm)[0][0] == operation
    assert gql_input(mm) == expected_input


async def test_insight_mutation_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"setInsightBookmarked": {"insight": None,
                                                         "errors": {"message": "not found"}}}
    with pytest.raises(ToolError, match="Insight bookmark failed: not found"):
        await call("set_insight_bookmarked", insight_id="i1", bookmarked=False)


async def test_update_insight_status_requires_status(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="^Invalid arguments for update_insight_status: "
                                        "'status' is a required property$"):
        await call("update_insight_status", insight_id="i1")
    mm.gql_call.assert_not_awaited()


# --- Financial insights (savings opportunities) -----------------------------------

async def test_get_financial_insights_defaults(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"financialInsights": [{"id": "f1"}]}
    assert await call("get_financial_insights") == [{"id": "f1"}]
    assert gql_ops(mm) == [("Common_GetFinancialInsightsList", {"limit": 50})]


async def test_get_financial_insights_filters(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"financialInsights": []}
    await call("get_financial_insights", status=["new"], opportunity_type=["duplicate"],
               limit=3, offset=6)
    assert gql_ops(mm) == [("Common_GetFinancialInsightsList", {
        "statuses": ["new"], "opportunityTypes": ["duplicate"], "limit": 3, "offset": 6})]


async def test_get_financial_insight(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"financialInsight": {"id": "f1", "actions": []}}
    assert await call("get_financial_insight", financial_insight_id="f1") == {"id": "f1", "actions": []}
    assert gql_ops(mm) == [("Common_GetFinancialInsight", {"id": "f1"})]


async def test_get_financial_insight_summary(call: Call, mm: AsyncMock) -> None:
    data = {"financialInsightSummary": {"newCount": 2}, "latestFinancialInsightRun": {"id": "r1"}}
    mm.gql_call.return_value = data
    assert await call("get_financial_insight_summary", start_date="2026-01-01",
                      end_date="2026-06-30") == data
    assert gql_ops(mm) == [("Common_GetFinancialInsightSummary",
                            {"startDate": "2026-01-01", "endDate": "2026-06-30"})]


async def test_get_financial_insight_summary_all_time(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {}
    await call("get_financial_insight_summary")
    assert gql_ops(mm) == [("Common_GetFinancialInsightSummary",
                            {"startDate": None, "endDate": None})]


async def test_get_financial_insight_summary_needs_both_dates(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Provide both start_date and end_date"):
        await call("get_financial_insight_summary", start_date="2026-01-01")


# --- Weekly recap -----------------------------------------------------------------

@pytest.mark.parametrize("today, start, end", [
    (date(2026, 9, 16), "2026-09-06", "2026-09-12"),  # Wednesday
    (date(2026, 9, 13), "2026-09-06", "2026-09-12"),  # Sunday
    (date(2026, 9, 12), "2026-08-30", "2026-09-05"),  # Saturday: that week isn't over
    (date(2026, 9, 14), "2026-09-06", "2026-09-12"),  # Monday
])
def test_last_recap_week(today: date, start: str, end: str) -> None:
    assert server.last_recap_week(today) == (start, end)


@pytest.fixture
def no_poll_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "RECAP_POLL_INTERVAL", 0)


async def test_get_weekly_recap_dates(call: Call, mm: AsyncMock, no_poll_wait: None) -> None:
    mm.gql_call.return_value = {"recap": {"id": "r1", "summary": "Good week"}}
    assert await call("get_weekly_recap", start_date="2026-09-06", end_date="2026-09-12") == {
        "id": "r1", "summary": "Good week"}
    assert gql_ops(mm) == [("Common_GetWeeklyRecap",
                            {"startDate": "2026-09-06", "endDate": "2026-09-12"})]


async def test_get_weekly_recap_defaults_to_last_week(call: Call, mm: AsyncMock,
                                                      monkeypatch: pytest.MonkeyPatch,
                                                      no_poll_wait: None) -> None:
    monkeypatch.setattr(server, "last_recap_week", lambda today: ("2026-09-06", "2026-09-12"))
    mm.gql_call.return_value = {"recap": {"id": "r1"}}
    await call("get_weekly_recap")
    assert gql_ops(mm)[0][1] == {"startDate": "2026-09-06", "endDate": "2026-09-12"}


async def test_get_weekly_recap_waits_for_generation(call: Call, mm: AsyncMock,
                                                     no_poll_wait: None) -> None:
    mm.gql_call.side_effect = [{"recap": None}, {"recap": None}, {"recap": {"id": "r1"}}]
    assert await call("get_weekly_recap") == {"id": "r1"}
    assert len(gql_ops(mm)) == 3


async def test_get_weekly_recap_gives_up(call: Call, mm: AsyncMock, no_poll_wait: None,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "RECAP_POLL_ATTEMPTS", 3)
    mm.gql_call.return_value = {"recap": None}
    with pytest.raises(ToolError, match="isn't ready yet"):
        await call("get_weekly_recap")
    assert len(gql_ops(mm)) == 3


async def test_get_weekly_recap_needs_both_dates(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Provide both start_date and end_date"):
        await call("get_weekly_recap", end_date="2026-09-12")
