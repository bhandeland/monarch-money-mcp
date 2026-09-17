from datetime import date, datetime
from unittest.mock import AsyncMock

import pytest

from monarchmoney.monarchmoney import BalanceHistoryRow
from tests.helpers import Call, ToolError


@pytest.mark.parametrize("tool, method", [
    ("get_accounts", "get_accounts"),
    ("get_account_type_options", "get_account_type_options"),
    ("get_institutions", "get_institutions"),
    ("get_credit_history", "get_credit_history"),
    ("get_subscription_details", "get_subscription_details"),
    ("get_transactions_summary", "get_transactions_summary"),
    ("get_transaction_tags", "get_transaction_tags"),
    ("get_transaction_categories", "get_transaction_categories"),
    ("get_transaction_category_groups", "get_transaction_category_groups"),
])
async def test_passthrough_reads(call: Call, mm: AsyncMock, tool: str, method: str) -> None:
    getattr(mm, method).return_value = {"from": method}
    assert await call(tool) == {"from": method}
    getattr(mm, method).assert_awaited_once_with()


async def test_get_account_holdings_converts_id(call: Call, mm: AsyncMock) -> None:
    mm.get_account_holdings.return_value = {"portfolio": {}}
    assert await call("get_account_holdings", account_id="123") == {"portfolio": {}}
    mm.get_account_holdings.assert_awaited_once_with(123)


async def test_get_account_history_converts_id(call: Call, mm: AsyncMock) -> None:
    mm.get_account_history.return_value = []
    await call("get_account_history", account_id="456")
    mm.get_account_history.assert_awaited_once_with(456)


async def test_get_account_holdings_rejects_bad_id(call: Call) -> None:
    with pytest.raises(ToolError, match="invalid literal"):
        await call("get_account_holdings", account_id="abc")


async def test_get_recent_account_balances(call: Call, mm: AsyncMock) -> None:
    mm.get_recent_account_balances.return_value = {}
    await call("get_recent_account_balances", start_date="2026-01-01")
    await call("get_recent_account_balances")
    assert [c.args for c in mm.get_recent_account_balances.await_args_list] == [("2026-01-01",), (None,)]


async def test_get_net_worth_history_passes_dates(call: Call, mm: AsyncMock) -> None:
    mm.get_aggregate_snapshots.return_value = {}
    await call("get_net_worth_history", start_date="2026-01-01", end_date="2026-02-01",
               account_type="brokerage")
    mm.get_aggregate_snapshots.assert_awaited_once_with(
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1), account_type="brokerage")


async def test_get_net_worth_history_defaults(call: Call, mm: AsyncMock) -> None:
    mm.get_aggregate_snapshots.return_value = {}
    await call("get_net_worth_history")
    mm.get_aggregate_snapshots.assert_awaited_once_with(start_date=None, end_date=None, account_type=None)


async def test_get_account_snapshots_by_type(call: Call, mm: AsyncMock) -> None:
    mm.get_account_snapshots_by_type.return_value = {}
    await call("get_account_snapshots_by_type", start_date="2026-01-01", timeframe="year")
    mm.get_account_snapshots_by_type.assert_awaited_once_with("2026-01-01", "year")


async def test_create_manual_account(call: Call, mm: AsyncMock) -> None:
    mm.create_manual_account.return_value = {"id": "a1"}
    await call("create_manual_account", account_name="Car", account_type="other_asset",
               account_sub_type="car")
    mm.create_manual_account.assert_awaited_once_with(
        account_type="other_asset", account_sub_type="car", is_in_net_worth=True,
        account_name="Car", account_balance=0)


async def test_create_manual_account_options(call: Call, mm: AsyncMock) -> None:
    mm.create_manual_account.return_value = {}
    await call("create_manual_account", account_name="Loan", account_type="loan",
               account_sub_type="auto", include_in_net_worth=False, balance=-500)
    kwargs = mm.create_manual_account.await_args.kwargs
    assert (kwargs["is_in_net_worth"], kwargs["account_balance"]) == (False, -500)


async def test_update_account_maps_only_given_fields(call: Call, mm: AsyncMock) -> None:
    mm.update_account.return_value = {}
    await call("update_account", account_id="a1", balance=10.5, hide_from_summary_list=True)
    mm.update_account.assert_awaited_once_with(
        account_id="a1", account_balance=10.5, hide_from_summary_list=True)


async def test_delete_account(call: Call, mm: AsyncMock) -> None:
    mm.delete_account.return_value = True
    assert await call("delete_account", account_id="a1") is True
    mm.delete_account.assert_awaited_once_with("a1")


async def test_upload_account_balance_history(call: Call, mm: AsyncMock) -> None:
    mm.upload_account_balance_history.return_value = True
    out = await call("upload_account_balance_history", account_id="a1",
                     rows=[{"date": "2026-01-01", "amount": 5}, {"date": "2026-01-02", "amount": 6.5}])
    assert out == {"account_id": "a1", "rows": 2, "completed": True}
    mm.upload_account_balance_history.assert_awaited_once_with("a1", [
        BalanceHistoryRow(datetime(2026, 1, 1), 5), BalanceHistoryRow(datetime(2026, 1, 2), 6.5)])


async def test_refresh_accounts_defaults_to_all(call: Call, mm: AsyncMock) -> None:
    mm.get_accounts.return_value = {"accounts": [{"id": "a1"}, {"id": "a2"}]}
    mm.request_accounts_refresh.return_value = True
    assert await call("refresh_accounts") == {"account_ids": ["a1", "a2"], "started": True}
    mm.request_accounts_refresh.assert_awaited_once_with(["a1", "a2"])


async def test_refresh_accounts_given_ids_and_wait(call: Call, mm: AsyncMock) -> None:
    mm.request_accounts_refresh_and_wait.return_value = False
    out = await call("refresh_accounts", account_ids=["a3"], wait=True)
    assert out == {"account_ids": ["a3"], "completed": False}
    mm.get_accounts.assert_not_awaited()
    mm.request_accounts_refresh_and_wait.assert_awaited_once_with(account_ids=["a3"])


async def test_get_refresh_status(call: Call, mm: AsyncMock) -> None:
    mm.is_accounts_refresh_complete.return_value = True
    assert await call("get_refresh_status") == {"completed": True}
    assert await call("get_refresh_status", account_ids=["a1"]) == {"completed": True}
    assert [c.args for c in mm.is_accounts_refresh_complete.await_args_list] == [(None,), (["a1"],)]
