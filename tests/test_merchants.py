from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops


async def test_get_merchants_defaults(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"merchants": [{"id": "m1"}], "merchantCount": 1}
    assert await call("get_merchants") == {"merchants": [{"id": "m1"}], "merchantCount": 1}
    assert gql_ops(mm) == [("Web_GetMerchantSettingsPage", {
        "search": None, "limit": 100, "offset": 0, "orderBy": "TRANSACTION_COUNT"})]


async def test_get_merchants_options(call: Call, mm: AsyncMock) -> None:
    await call("get_merchants", search="wal", limit=5, offset=10, order_by="NAME")
    assert gql_ops(mm) == [("Web_GetMerchantSettingsPage", {
        "search": "wal", "limit": 5, "offset": 10, "orderBy": "NAME"})]


async def test_get_merchant(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"merchant": {"id": "m1", "ruleCount": 2}}
    assert await call("get_merchant", merchant_id="m1") == {"merchant": {"id": "m1", "ruleCount": 2}}
    assert gql_ops(mm) == [("Common_GetEditMerchant", {"merchantId": "m1"})]


async def test_update_merchant_maps_fields(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateMerchant": {"merchant": {"id": "m1"}, "errors": None}}
    out = await call("update_merchant", merchant_id="m1", name="Costco",
                     default_category_id="c1", default_category_mode="new_and_edits",
                     recurrence={"is_recurring": True, "frequency": "monthly",
                                 "base_date": "2026-01-15", "amount": -65, "is_active": True})
    assert out == {"id": "m1"}
    assert gql_ops(mm)[0][0] == "Common_UpdateMerchant"
    assert gql_input(mm) == {
        "merchantId": "m1", "name": "Costco", "defaultCategoryId": "c1",
        "defaultCategoryApplicationMode": "new_and_edits",
        "recurrence": {"isRecurring": True, "frequency": "monthly", "baseDate": "2026-01-15",
                       "amount": -65, "isActive": True},
    }


async def test_update_merchant_stop_recurring(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateMerchant": {"merchant": {"id": "m1"}}}
    await call("update_merchant", merchant_id="m1", recurrence={"is_recurring": False})
    assert gql_input(mm) == {"merchantId": "m1", "recurrence": {"isRecurring": False}}


async def test_update_merchant_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateMerchant": {"errors": {"message": "name taken"}}}
    with pytest.raises(ToolError, match="Merchant update failed: name taken"):
        await call("update_merchant", merchant_id="m1", name="Dup")


async def test_delete_merchant(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [{"merchant": {"id": "m1", "canBeDeleted": True}},
                               {"deleteMerchant": {"success": True}}]
    assert await call("delete_merchant", merchant_id="m1") == {
        "merchant_id": "m1", "merged_into": None, "success": True}
    assert gql_ops(mm) == [("Common_GetEditMerchant", {"merchantId": "m1"}),
                           ("Common_DeleteMerchant", {"merchantId": "m1", "moveToId": None})]


async def test_delete_merchant_refuses_undeletable(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"merchant": {"id": "m1", "canBeDeleted": False}}
    with pytest.raises(ToolError, match="can't delete this merchant.*move_to_merchant_id"):
        await call("delete_merchant", merchant_id="m1")
    assert [op for op, _ in gql_ops(mm)] == ["Common_GetEditMerchant"]


async def test_delete_merchant_unknown(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"merchant": None}
    with pytest.raises(ToolError, match="No merchant m1"):
        await call("delete_merchant", merchant_id="m1")


async def test_delete_merchant_merge(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteMerchant": {"success": False}}
    assert await call("delete_merchant", merchant_id="m1", move_to_merchant_id="m2") == {
        "merchant_id": "m1", "merged_into": "m2", "success": False}
    assert gql_ops(mm) == [("Common_DeleteMerchant", {"merchantId": "m1", "moveToId": "m2"})]
