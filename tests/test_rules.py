from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops


async def test_list_transaction_rules(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"transactionRules": [{"id": "r1"}]}
    assert await call("list_transaction_rules") == {"transactionRules": [{"id": "r1"}]}
    assert gql_ops(mm) == [("GetTransactionRules", {})]


async def test_create_transaction_rule(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createTransactionRuleV2": {
        "errors": None, "transactionRule": {"id": "r9"}}}
    out = await call("create_transaction_rule", merchant_equals="Shell", set_category_id="gas")
    assert out["created"] == {"id": "r9"}
    assert out["input"] == gql_input(mm)
    assert gql_ops(mm)[0][0] == "Common_CreateTransactionRuleMutationV2"
    assert gql_input(mm)["merchantCriteria"] == [{"operator": "eq", "value": "Shell"}]


async def test_create_transaction_rule_validation_skips_api(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="at least one condition"):
        await call("create_transaction_rule", set_category_id="gas")
    mm.gql_call.assert_not_awaited()


async def test_create_transaction_rule_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createTransactionRuleV2": {
        "errors": {"fieldErrors": [{"field": "setCategoryAction", "messages": ["unknown"]}]}}}
    with pytest.raises(ToolError, match="Rule creation failed: setCategoryAction: unknown"):
        await call("create_transaction_rule", merchant_equals="Shell", set_category_id="nope")


async def test_delete_transaction_rule_confirms_by_relisting(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [
        {"deleteTransactionRule": {"deleted": False, "errors": None}},
        {"transactionRules": [{"id": "r2"}]},
    ]
    assert await call("delete_transaction_rule", rule_id="r1") == {
        "rule_id": "r1", "deleted": True, "api_deleted_flag": False}
    assert gql_ops(mm) == [("Common_DeleteTransactionRule", {"id": "r1"}), ("GetTransactionRules", {})]


async def test_delete_transaction_rule_still_present(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [
        {"deleteTransactionRule": {"deleted": True}},
        {"transactionRules": [{"id": "r1"}]},
    ]
    out = await call("delete_transaction_rule", rule_id="r1")
    assert out["deleted"] is False


async def test_delete_transaction_rule_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteTransactionRule": {"errors": {"message": "not found"}}}
    with pytest.raises(ToolError, match="Rule deletion failed: not found"):
        await call("delete_transaction_rule", rule_id="r1")
    assert len(gql_ops(mm)) == 1
