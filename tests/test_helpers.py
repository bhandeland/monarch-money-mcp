from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

import monarch_gql as q
import server
from tests.helpers import gql_ops


def test_parse_date_arg() -> None:
    assert server.parse_date_arg({"d": "2026-01-05"}, "d") == "2026-01-05"
    assert server.parse_date_arg({"d": ""}, "d") is None
    assert server.parse_date_arg({}, "d") is None
    with pytest.raises(ValueError):
        server.parse_date_arg({"d": "01/05/2026"}, "d")


def test_require_date_arg() -> None:
    assert server.require_date_arg({"d": "2026-01-05"}, "d") == "2026-01-05"
    with pytest.raises(ValueError, match="d is required"):
        server.require_date_arg({}, "d")


def test_date_range() -> None:
    assert server.date_range({}) == (None, None)
    assert server.date_range({"start_date": "2026-01-01", "end_date": "2026-01-31"}) == (
        "2026-01-01", "2026-01-31")
    with pytest.raises(ValueError, match="both"):
        server.date_range({"start_date": "2026-01-01"})
    with pytest.raises(ValueError, match="both"):
        server.date_range({"end_date": "2026-01-01"})


def test_first_of_month() -> None:
    assert server.first_of_month({"m": "2026-03-17"}, "m") == "2026-03-01"
    assert server.first_of_month({}, "m") is None


@pytest.mark.parametrize("day, bounds", [
    (date(2026, 2, 14), ("2026-02-01", "2026-02-28")),
    (date(2028, 2, 29), ("2028-02-01", "2028-02-29")),
    (date(2026, 12, 31), ("2026-12-01", "2026-12-31")),
    (date(2026, 9, 1), ("2026-09-01", "2026-09-30")),
    (date(2026, 1, 31), ("2026-01-01", "2026-01-31")),
])
def test_month_bounds(day: date, bounds: tuple[str, str]) -> None:
    assert server.month_bounds(day) == bounds


def test_pick_renames_and_skips_missing() -> None:
    assert server.pick({"a": 1, "c": None}, {"a": "A", "b": "B", "c": "C"}) == {"A": 1, "C": None}


def test_convert_dates_to_strings() -> None:
    data = {"d": date(2026, 1, 2), "l": [datetime(2026, 1, 2, 3, 4)], "t": (date(2026, 1, 3),), "n": 1}
    assert server.convert_dates_to_strings(data) == {
        "d": "2026-01-02", "l": ["2026-01-02T03:04:00"], "t": ("2026-01-03",), "n": 1}


# --- monarch_gql -------------------------------------------------------------

def test_raise_payload_errors_ignores_empty() -> None:
    q.raise_payload_errors(None, "x")
    q.raise_payload_errors({"message": None, "fieldErrors": []}, "x")


def test_raise_payload_errors_message() -> None:
    with pytest.raises(RuntimeError, match="^Thing failed: nope$"):
        q.raise_payload_errors({"message": "nope"}, "Thing")


def test_raise_payload_errors_field_errors() -> None:
    errors = {"fieldErrors": [{"field": "name", "messages": ["too long", "bad"]},
                              {"field": "id", "messages": ["missing"]}]}
    with pytest.raises(RuntimeError, match="^Thing failed: name: too long, bad; id: missing$"):
        q.raise_payload_errors(errors, "Thing")


async def test_execute_names_operation_from_document() -> None:
    mm = AsyncMock()
    mm.gql_call.return_value = {"ok": True}
    assert await q.execute(mm, q.GET_MERCHANT, {"merchantId": "1"}) == {"ok": True}
    assert gql_ops(mm) == [("Common_GetEditMerchant", {"merchantId": "1"})]


async def test_execute_defaults_variables() -> None:
    mm = AsyncMock()
    await q.execute(mm, q.GET_RULES)
    assert gql_ops(mm) == [("GetTransactionRules", {})]


def test_operation_names_are_unique() -> None:
    names = [r.document.definitions[0].name.value  # type: ignore[union-attr]
             for r in vars(q).values() if hasattr(r, "document")]
    assert len(names) == len(set(names)) > 10


RULE_BASE: dict[str, Any] = {"merchant_contains": "coffee", "set_category_id": "c1"}


def test_build_rule_input_minimal() -> None:
    assert q.build_rule_input(RULE_BASE) == {
        "merchantCriteria": [{"operator": "contains", "value": "coffee"}],
        "merchantCriteriaUseOriginalStatement": False,
        "amountCriteria": None,
        "accountIds": None,
        "categoryIds": None,
        "setCategoryAction": "c1",
        "setMerchantAction": None,
        "addTagsAction": None,
        "splitTransactionsAction": None,
        "applyToExistingTransactions": False,
    }


def test_build_rule_input_full() -> None:
    rule = q.build_rule_input({
        "merchant_contains": "a", "merchant_equals": "b", "use_original_statement": True,
        "amount": {"operator": "gt", "value": 80, "is_expense": False},
        "account_ids": ["a1"], "match_category_ids": ["c0"],
        "set_merchant_name": "B", "add_tag_ids": ["t1"], "apply_to_existing": True,
    })
    assert rule["merchantCriteria"] == [{"operator": "contains", "value": "a"},
                                        {"operator": "eq", "value": "b"}]
    assert rule["merchantCriteriaUseOriginalStatement"] is True
    assert rule["amountCriteria"] == {"operator": "gt", "isExpense": False, "value": 80, "valueRange": None}
    assert (rule["accountIds"], rule["categoryIds"]) == (["a1"], ["c0"])
    assert (rule["setMerchantAction"], rule["addTagsAction"]) == ("B", ["t1"])
    assert rule["applyToExistingTransactions"] is True


def test_build_rule_input_between() -> None:
    rule = q.build_rule_input({**RULE_BASE, "amount": {"operator": "between", "lower": 1, "upper": 5}})
    assert rule["amountCriteria"] == {"operator": "between", "isExpense": True, "value": None,
                                      "valueRange": {"lower": 1, "upper": 5}}


@pytest.mark.parametrize("args, message", [
    ({**RULE_BASE, "amount": {"operator": "gte", "value": 1}}, "operator must be one of"),
    ({**RULE_BASE, "amount": {"operator": "between", "lower": 1}}, "lower and amount.upper"),
    ({**RULE_BASE, "amount": {"operator": "eq"}}, "value is required"),
    ({"set_category_id": "c1"}, "at least one condition"),
    ({"merchant_contains": "x"}, "needs an action"),
])
def test_build_rule_input_rejects(args: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        q.build_rule_input(args)


@pytest.mark.parametrize("condition", [
    {"amount": {"operator": "lt", "value": 1}}, {"account_ids": ["a"]}, {"match_category_ids": ["c"]},
])
def test_build_rule_input_accepts_any_single_condition(condition: dict[str, Any]) -> None:
    q.build_rule_input({"set_category_id": "c1", **condition})
