from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.helpers import Call, ToolError


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
    mm.update_transaction.return_value = {}
    await call("update_transaction", transaction_id="t1", amount=2, description="New",
               category_id="c2", date="2026-03-04", notes="", hide_from_reports=True,
               needs_review=False)
    mm.update_transaction.assert_awaited_once_with(
        transaction_id="t1", amount=2, merchant_name="New", category_id="c2", date="2026-03-04",
        notes="", hide_from_reports=True, needs_review=False)


async def test_update_transaction_only_id(call: Call, mm: AsyncMock) -> None:
    mm.update_transaction.return_value = {}
    await call("update_transaction", transaction_id="t1")
    mm.update_transaction.assert_awaited_once_with(transaction_id="t1")


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
    mm.delete_transaction_categories.return_value = [True, RuntimeError("in use")]
    assert await call("delete_transaction_categories", category_ids=["c1", "c2"]) == [
        {"category_id": "c1", "deleted": True},
        {"category_id": "c2", "deleted": False, "error": "in use"},
    ]
    mm.delete_transaction_categories.assert_awaited_once_with(["c1", "c2"])
