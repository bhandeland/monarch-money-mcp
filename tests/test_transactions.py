from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError, gql_input, gql_ops


async def test_get_transactions_defaults(call: Call, mm: AsyncMock) -> None:
    mm.get_transactions.return_value = {"allTransactions": {"results": []}}
    assert await call("get_transactions") == {"allTransactions": {"results": []}}
    mm.get_transactions.assert_awaited_once_with(
        limit=100, offset=0, start_date=None, end_date=None, account_ids=[], category_ids=[])


async def test_get_transactions_all_filters(call: Call, mm: AsyncMock) -> None:
    mm.get_transactions.return_value = {}
    await call("get_transactions", limit=5, offset=10, start_date="2026-01-01", end_date="2026-01-31",
               search="coffee", account_id="a1", account_ids=["a0"], category_id="c1",
               category_ids=["c0"], tag_ids=["t1"], has_attachments=True, has_notes=False,
               hidden_from_reports=False, is_split=True, is_recurring=False)
    mm.get_transactions.assert_awaited_once_with(
        limit=5, offset=10, start_date="2026-01-01", end_date="2026-01-31",
        account_ids=["a0", "a1"], category_ids=["c0", "c1"], search="coffee", tag_ids=["t1"],
        has_attachments=True, has_notes=False, hidden_from_reports=False, is_split=True,
        is_recurring=False)


async def test_get_transactions_requires_both_dates(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="both start_date and end_date"):
        await call("get_transactions", start_date="2026-01-01")
    mm.get_transactions.assert_not_awaited()


async def test_get_transaction_details(call: Call, mm: AsyncMock) -> None:
    mm.get_transaction_details.return_value = {"getTransaction": {"id": "t1"}}
    assert await call("get_transaction_details", transaction_id="t1") == {"getTransaction": {"id": "t1"}}
    mm.get_transaction_details.assert_awaited_once_with("t1")


async def test_create_transaction(call: Call, mm: AsyncMock) -> None:
    mm.create_transaction.return_value = {"createTransaction": {}}
    await call("create_transaction", amount=-4.5, description="Cafe", category_id="c1",
               account_id="a1", date="2026-02-03")
    mm.create_transaction.assert_awaited_once_with(
        date="2026-02-03", account_id="a1", amount=-4.5, merchant_name="Cafe",
        category_id="c1", notes="", update_balance=False)


async def test_create_transaction_options(call: Call, mm: AsyncMock) -> None:
    mm.create_transaction.return_value = {}
    await call("create_transaction", amount=1, description="x", category_id="c", account_id="a",
               date="2026-02-03", notes="hi", update_balance=True)
    kwargs = mm.create_transaction.await_args.kwargs
    assert (kwargs["notes"], kwargs["update_balance"]) == ("hi", True)


async def test_create_transaction_rejects_bad_date(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="does not match format"):
        await call("create_transaction", amount=1, description="x", category_id="c",
                   account_id="a", date="Feb 3")
    mm.create_transaction.assert_not_awaited()


async def test_update_transaction_maps_fields(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateTransaction": {"transaction": {"id": "t1"}, "errors": None}}
    assert await call("update_transaction", transaction_id="t1", amount=2, description="New",
                      category_id="c2", date="2026-03-04", notes="", hide_from_reports=True,
                      needs_review=False, review_status="reviewed", is_recurring=True,
                      owner_user_id="u1", business_entity_id="b1", goal_id="g1") == {"id": "t1"}
    assert gql_ops(mm)[0][0] == "Web_TransactionDrawerUpdateTransaction"
    assert gql_input(mm) == {
        "id": "t1", "amount": 2, "name": "New", "category": "c2", "date": "2026-03-04", "notes": "",
        "hideFromReports": True, "needsReview": False, "reviewStatus": "reviewed", "isRecurring": True,
        "ownerUserId": "u1", "businessEntityId": "b1", "goalId": "g1"}


async def test_update_transaction_only_id(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateTransaction": {"transaction": {"id": "t1"}}}
    await call("update_transaction", transaction_id="t1")
    assert gql_input(mm) == {"id": "t1"}


async def test_update_transaction_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateTransaction": {"errors": {"message": "bad category"}}}
    with pytest.raises(ToolError, match="Transaction update failed: bad category"):
        await call("update_transaction", transaction_id="t1", category_id="x")


async def test_delete_transaction(call: Call, mm: AsyncMock) -> None:
    mm.delete_transaction.return_value = True
    assert await call("delete_transaction", transaction_id="t1") == {"transaction_id": "t1", "deleted": True}
    mm.delete_transaction.assert_awaited_once_with("t1")


async def test_get_transaction_splits(call: Call, mm: AsyncMock) -> None:
    mm.get_transaction_splits.return_value = {"getTransaction": {"splitTransactions": []}}
    await call("get_transaction_splits", transaction_id="t1")
    mm.get_transaction_splits.assert_awaited_once_with("t1")


async def test_update_transaction_splits_maps_fields(call: Call, mm: AsyncMock) -> None:
    mm.update_transaction_splits.return_value = {"updateTransactionSplit": {"errors": None}}
    await call("update_transaction_splits", transaction_id="t1", splits=[
        {"amount": -3, "category_id": "c1"},
        {"amount": -7, "category_id": "c2", "merchant_name": "M", "notes": "n"},
    ])
    mm.update_transaction_splits.assert_awaited_once_with("t1", [
        {"amount": -3, "categoryId": "c1"},
        {"amount": -7, "categoryId": "c2", "merchantName": "M", "notes": "n"},
    ])


async def test_update_transaction_splits_clear(call: Call, mm: AsyncMock) -> None:
    mm.update_transaction_splits.return_value = {"updateTransactionSplit": {}}
    await call("update_transaction_splits", transaction_id="t1", splits=[])
    mm.update_transaction_splits.assert_awaited_once_with("t1", [])


async def test_update_transaction_splits_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.update_transaction_splits.return_value = {
        "updateTransactionSplit": {"errors": {"message": "amounts must sum to -10"}}}
    with pytest.raises(ToolError, match="Split update failed: amounts must sum to -10"):
        await call("update_transaction_splits", transaction_id="t1", splits=[{"amount": -1, "category_id": "c"}])


async def test_upload_transaction_attachment(call: Call, mm: AsyncMock, tmp_path: Path) -> None:
    receipt = tmp_path / "receipt.pdf"
    receipt.write_bytes(b"%PDF")
    mm.upload_attachment.return_value = {"id": "att1"}
    assert await call("upload_transaction_attachment", transaction_id="t1",
                      file_path=str(receipt)) == {"id": "att1"}
    mm.upload_attachment.assert_awaited_once_with("t1", b"%PDF", "receipt.pdf")


async def test_upload_transaction_attachment_missing_file(call: Call, mm: AsyncMock, tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="No such file"):
        await call("upload_transaction_attachment", transaction_id="t1",
                   file_path=str(tmp_path / "nope.pdf"))
    mm.upload_attachment.assert_not_awaited()


# --- Tags ---------------------------------------------------------------------

async def test_create_transaction_tag(call: Call, mm: AsyncMock) -> None:
    mm.create_transaction_tag.return_value = {"tag": {"id": "g1"}}
    await call("create_transaction_tag", name="Trip")
    await call("create_transaction_tag", name="Work", color="#FF0000")
    assert [c.args for c in mm.create_transaction_tag.await_args_list] == [
        ("Trip", "#19D2A5"), ("Work", "#FF0000")]


async def test_set_transaction_tags(call: Call, mm: AsyncMock) -> None:
    mm.set_transaction_tags.return_value = {}
    await call("set_transaction_tags", transaction_id="t1", tag_ids=[])
    mm.set_transaction_tags.assert_awaited_once_with("t1", [])


# --- Categories ---------------------------------------------------------------

async def test_create_transaction_category(call: Call, mm: AsyncMock) -> None:
    mm.create_transaction_category.return_value = {}
    await call("create_transaction_category", group_id="g1", name="Pets")
    mm.create_transaction_category.assert_awaited_once_with(
        group_id="g1", transaction_category_name="Pets", icon="❓", rollover_enabled=False)


async def test_create_transaction_category_options(call: Call, mm: AsyncMock) -> None:
    mm.create_transaction_category.return_value = {}
    await call("create_transaction_category", group_id="g1", name="Pets", icon="🐶",
               rollover_enabled=True)
    kwargs = mm.create_transaction_category.await_args.kwargs
    assert (kwargs["icon"], kwargs["rollover_enabled"]) == ("🐶", True)


async def test_delete_transaction_categories_reports_each(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.side_effect = [
        {"deleteCategory": {"deleted": True, "errors": None}},
        {"deleteCategory": {"deleted": False, "errors": {"message": "in use"}}},
        {"deleteCategory": {"deleted": False, "errors": None}},
    ]
    assert await call("delete_transaction_categories", category_ids=["c1", "c2", "c3"]) == [
        {"category_id": "c1", "deleted": True},
        {"category_id": "c2", "deleted": False, "error": "Category deletion failed: in use"},
        {"category_id": "c3", "deleted": False, "error": "Category deletion failed"},
    ]
    assert gql_ops(mm) == [("Web_DeleteCategory", {"id": c, "moveToCategoryId": None})
                           for c in ("c1", "c2", "c3")]


async def test_delete_transaction_categories_moves_transactions(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteCategory": {"deleted": True}}
    await call("delete_transaction_categories", category_ids=["c1"], move_to_category_id="c9")
    assert gql_ops(mm) == [("Web_DeleteCategory", {"id": "c1", "moveToCategoryId": "c9"})]


async def test_update_transaction_category(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateCategory": {"category": {"id": "c1"}, "errors": None}}
    assert await call("update_transaction_category", category_id="c1", name="Pets", icon="🐶",
                      group_id="g2", exclude_from_budget=True, budget_variability="fixed",
                      rollover_enabled=False) == {"id": "c1"}
    assert gql_ops(mm)[0][0] == "Web_UpdateCategory"
    assert gql_input(mm) == {"id": "c1", "name": "Pets", "icon": "🐶", "group": "g2",
                             "excludeFromBudget": True, "budgetVariability": "fixed",
                             "rolloverEnabled": False}


async def test_update_transaction_category_needs_a_change(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("update_transaction_category", category_id="c1")
    mm.gql_call.assert_not_awaited()


async def test_update_transaction_category_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateCategory": {"errors": {"message": "name taken"}}}
    with pytest.raises(ToolError, match="Category update failed: name taken"):
        await call("update_transaction_category", category_id="c1", name="Dup")


# --- Category groups ------------------------------------------------------------

async def test_create_category_group(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"createCategoryGroup": {"categoryGroup": {"id": "g1"}}}
    assert await call("create_category_group", name="Hobbies", type="expense", icon="🎨",
                      color="#112233", budget_variability="flexible") == {"id": "g1"}
    assert gql_ops(mm)[0][0] == "Common_CreateCategoryGroup"
    assert gql_input(mm) == {"type": "expense", "name": "Hobbies", "icon": "🎨", "color": "#112233",
                             "budgetVariability": "flexible"}


async def test_update_category_group(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"updateCategoryGroup": {"categoryGroup": {"id": "g1", "name": "Fun"}}}
    assert await call("update_category_group", group_id="g1", name="Fun") == {"id": "g1", "name": "Fun"}
    assert gql_ops(mm) == [("Common_UpdateCategoryGroup", {"input": {"id": "g1", "name": "Fun"}})]


async def test_update_category_group_needs_a_change(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("update_category_group", group_id="g1")


async def test_delete_category_group(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteCategoryGroup": {"deleted": True, "errors": None}}
    assert await call("delete_category_group", group_id="g1", move_to_group_id="g2") == {
        "group_id": "g1", "deleted": True}
    await call("delete_category_group", group_id="g3")
    assert gql_ops(mm) == [("Common_DeleteCategoryGroup", {"id": "g1", "moveToGroupId": "g2"}),
                           ("Common_DeleteCategoryGroup", {"id": "g3", "moveToGroupId": None})]


async def test_delete_category_group_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteCategoryGroup": {"errors": {"message": "has categories"}}}
    with pytest.raises(ToolError, match="Category group deletion failed: has categories"):
        await call("delete_category_group", group_id="g1")


# --- Bulk and move --------------------------------------------------------------

SELECTION = {"selectedTransactionIds": ["t1", "t2"], "excludedTransactionIds": [],
             "allSelected": False, "expectedAffectedTransactionCount": 2, "filters": None}


async def test_bulk_update_transactions(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"bulkUpdateTransactions": {"success": True, "affectedCount": 2, "errors": None}}
    out = await call("bulk_update_transactions", transaction_ids=["t1", "t2"], category_id="c1",
                     merchant_name="M", date="2026-01-02", notes="n", hide_from_reports=True,
                     tag_ids=[], review_status="needs_review", is_recurring=False,
                     owner_user_id="u1", business_entity_id="b1")
    assert out == {"success": True, "requested": 2, "affected": 2}
    assert gql_ops(mm) == [("Common_BulkUpdateTransactionsMutation", {**SELECTION, "updates": {
        "categoryId": "c1", "merchantName": "M", "date": "2026-01-02", "notes": "n", "hide": True,
        "tags": [], "reviewStatus": "needs_review", "isRecurring": False, "ownerUserId": "u1",
        "businessEntityId": "b1"}})]


async def test_bulk_update_transactions_needs_a_change(call: Call, mm: AsyncMock) -> None:
    with pytest.raises(ToolError, match="Nothing to update"):
        await call("bulk_update_transactions", transaction_ids=["t1"])
    mm.gql_call.assert_not_awaited()


async def test_bulk_update_transactions_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"bulkUpdateTransactions": {
        "success": False, "affectedCount": 0, "errors": {"message": "count mismatch"}}}
    with pytest.raises(ToolError, match="Bulk update failed: count mismatch"):
        await call("bulk_update_transactions", transaction_ids=["t1"], notes="x")


async def test_bulk_delete_transactions(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"bulkDeleteTransactions": {"success": True, "affectedCount": 2}}
    assert await call("bulk_delete_transactions", transaction_ids=["t1", "t2"]) == {
        "success": True, "requested": 2, "affected": 2}
    assert gql_ops(mm) == [("Common_BulkDeleteTransactionsMutation", SELECTION)]


async def test_bulk_delete_transactions_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"bulkDeleteTransactions": {"errors": {"message": "nope"}}}
    with pytest.raises(ToolError, match="Bulk delete failed: nope"):
        await call("bulk_delete_transactions", transaction_ids=["t1"])


async def test_move_transactions(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"moveTransactions": {"numTransactionsMoved": 2, "errors": None}}
    assert await call("move_transactions", from_account_id="a1", to_account_id="a2",
                      transaction_ids=["t1", "t2"]) == {"requested": 2, "moved": 2}
    assert gql_input(mm) == {"fromAccountId": "a1", "toAccountId": "a2",
                             "selectedTransactionIds": ["t1", "t2"], "isAllSelected": False,
                             "expectedAffectedTransactionCount": 2}


async def test_move_transactions_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"moveTransactions": {"errors": {"message": "same account"}}}
    with pytest.raises(ToolError, match="Move failed: same account"):
        await call("move_transactions", from_account_id="a1", to_account_id="a1", transaction_ids=["t1"])


# --- Tag update/delete ------------------------------------------------------------

TAGS = {"householdTransactionTags": [{"id": "g1", "name": "Trip", "color": "#111111"}]}


async def test_update_transaction_tag_fills_missing_fields(call: Call, mm: AsyncMock) -> None:
    mm.get_transaction_tags.return_value = TAGS
    mm.gql_call.return_value = {"updateTransactionTag": {"tag": {"id": "g1"}, "errors": None}}
    await call("update_transaction_tag", tag_id="g1", name="Vacation")
    await call("update_transaction_tag", tag_id="g1", color="#222222")
    assert gql_ops(mm) == [
        ("Common_UpdateTransactionTag", {"input": {"id": "g1", "name": "Vacation", "color": "#111111"}}),
        ("Common_UpdateTransactionTag", {"input": {"id": "g1", "name": "Trip", "color": "#222222"}}),
    ]


async def test_update_transaction_tag_validation(call: Call, mm: AsyncMock) -> None:
    mm.get_transaction_tags.return_value = TAGS
    with pytest.raises(ToolError, match="name and/or color"):
        await call("update_transaction_tag", tag_id="g1")
    with pytest.raises(ToolError, match="No tag g9"):
        await call("update_transaction_tag", tag_id="g9", name="x")
    mm.gql_call.assert_not_awaited()


async def test_update_transaction_tag_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.get_transaction_tags.return_value = TAGS
    mm.gql_call.return_value = {"updateTransactionTag": {"errors": {"message": "bad color"}}}
    with pytest.raises(ToolError, match="Tag update failed: bad color"):
        await call("update_transaction_tag", tag_id="g1", color="red")


async def test_delete_transaction_tag(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteTransactionTag": {"errors": None}}
    assert await call("delete_transaction_tag", tag_id="g1") == {"tag_id": "g1", "deleted": True}
    assert gql_ops(mm) == [("Common_DeleteHouseholdTransactionTag", {"tagId": "g1"})]


async def test_delete_transaction_tag_surfaces_errors(call: Call, mm: AsyncMock) -> None:
    mm.gql_call.return_value = {"deleteTransactionTag": {"errors": {"message": "not found"}}}
    with pytest.raises(ToolError, match="Tag deletion failed: not found"):
        await call("delete_transaction_tag", tag_id="g1")
