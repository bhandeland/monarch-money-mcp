#!/usr/bin/env python3
"""MonarchMoney MCP Server - Provides access to Monarch Money financial data via MCP protocol."""

import argparse
import getpass
import os
import sys
import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, cast

from gql import GraphQLRequest
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (CallToolRequestParams, CallToolResult, ListToolsResult,
                       PaginatedRequestParams, TextContent, Tool, ToolAnnotations)
from monarchmoney import MonarchMoney
from monarchmoney.monarchmoney import BalanceHistoryRow

import auth
import monarch_gql as q

# Tool arguments and API responses are untyped JSON.
Args = dict[str, Any]


def convert_dates_to_strings(obj: Any) -> Any:
    """
    Recursively convert all date/datetime objects to ISO format strings.

    This ensures that the data can be serialized by any JSON encoder,
    not just our custom one. This is necessary because the MCP framework
    may attempt to serialize the response before we can use our custom encoder.
    """
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {key: convert_dates_to_strings(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_dates_to_strings(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(convert_dates_to_strings(item) for item in obj)
    else:
        return obj


def parse_date_arg(arguments: Args, key: str) -> str | None:
    """Validate a YYYY-MM-DD argument and return it as a string.

    The monarchmoney library puts dates straight into GraphQL variables, so it
    needs strings. Passing date objects causes "Object of type date is not JSON
    serializable".
    """
    value = arguments.get(key)
    if value in (None, ""):
        return None
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def require_date_arg(arguments: Args, key: str) -> str:
    value = parse_date_arg(arguments, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def date_range(arguments: Args) -> tuple[str | None, str | None]:
    """start_date/end_date. The Monarch API rejects one without the other."""
    start = parse_date_arg(arguments, "start_date")
    end = parse_date_arg(arguments, "end_date")
    if bool(start) != bool(end):
        raise ValueError("Provide both start_date and end_date, or neither.")
    return start, end


def first_of_month(arguments: Args, key: str) -> str | None:
    """Budgets are keyed by the first of the month."""
    value = parse_date_arg(arguments, key)
    return value[:8] + "01" if value else None


def month_bounds(day: date) -> tuple[str, str]:
    """First and last day of the month containing `day`."""
    next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return day.replace(day=1).isoformat(), (next_month - timedelta(days=1)).isoformat()


def pick(arguments: Args, mapping: dict[str, str]) -> Args:
    """Copy the arguments that were provided, renaming tool keys to API keys."""
    return {api: arguments[arg] for arg, api in mapping.items() if arg in arguments}


def result(data: Any) -> CallToolResult:
    text = json.dumps(convert_dates_to_strings(data), indent=2)
    return CallToolResult(content=[TextContent(type="text", text=text)])


def error(message: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=message)], is_error=True)

# Set by serve() once authenticated; replaced when the token has to be renewed.
mm_client: MonarchMoney | None = None
authenticator = auth.Authenticator(os.environ)


# ---------------------------------------------------------------------------
# Tool registry. Each handler takes the client and the tool arguments and
# returns JSON-serializable data.
# ---------------------------------------------------------------------------
Handler = Callable[[MonarchMoney, Args], Awaitable[Any]]
TOOLS: dict[str, tuple[Tool, Handler]] = {}

READ = ToolAnnotations(read_only_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)


def tool(name: str, description: str, properties: Args | None = None,
         required: list[str] | None = None,
         annotations: ToolAnnotations = READ) -> Callable[[Handler], Handler]:
    schema: Args = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required

    def register(fn: Handler) -> Handler:
        TOOLS[name] = (Tool(name=name, description=description, input_schema=schema,
                            annotations=annotations), fn)
        return fn
    return register


def string(description: str, **extra: Any) -> Args:
    return {"type": "string", "description": description, **extra}


def number(description: str) -> Args:
    return {"type": "number", "description": description}


def boolean(description: str, default: bool | None = None) -> Args:
    prop: Args = {"type": "boolean", "description": description}
    if default is not None:
        prop["default"] = default
    return prop


def id_list(description: str) -> Args:
    return {"type": "array", "items": {"type": "string"}, "description": description}


DATE_RANGE: Args = {
    "start_date": string("Start date in YYYY-MM-DD format (requires end_date)"),
    "end_date": string("End date in YYYY-MM-DD format (requires start_date)"),
}


# --- Accounts ---------------------------------------------------------------

@tool("get_accounts", "Retrieve all linked financial accounts")
async def get_accounts(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_accounts()


@tool("get_account_type_options",
      "List valid account types and subtypes (needed for create_manual_account / update_account)")
async def get_account_type_options(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_account_type_options()


@tool("get_institutions", "List connected financial institutions and their connection status")
async def get_institutions(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_institutions()


@tool("get_account_holdings", "Get investment holdings for a brokerage or similar account",
      {"account_id": string("Account ID")}, ["account_id"])
async def get_account_holdings(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_account_holdings(int(args["account_id"]))


@tool("get_account_history", "Get the full daily balance history for one account",
      {"account_id": string("Account ID")}, ["account_id"])
async def get_account_history(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_account_history(int(args["account_id"]))


@tool("get_recent_account_balances",
      "Get daily balances for all accounts from start_date (default: last 31 days)",
      {"start_date": string("Start date in YYYY-MM-DD format")})
async def get_recent_account_balances(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_recent_account_balances(parse_date_arg(args, "start_date"))


@tool("get_net_worth_history",
      "Get the daily net worth (sum of all accounts), optionally limited to one account type",
      {**DATE_RANGE,
       "account_type": string("Only include accounts of this type, e.g. 'brokerage' "
                              "(see get_account_type_options)")})
async def get_net_worth_history(mm: MonarchMoney, args: Args) -> Any:
    start, end = date_range(args)
    # Annotated as dates, but the library sends them as GraphQL variables, which
    # need strings (its own default start_date is an ISO string).
    return await mm.get_aggregate_snapshots(
        start_date=cast(Any, start),
        end_date=cast(Any, end),
        account_type=args.get("account_type"),
    )


@tool("get_account_snapshots_by_type",
      "Get net balances grouped by account type, by month or by year",
      {"start_date": string("Start date in YYYY-MM-DD format"),
       "timeframe": string("Granularity", enum=["month", "year"])},
      ["start_date", "timeframe"])
async def get_account_snapshots_by_type(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_account_snapshots_by_type(
        require_date_arg(args, "start_date"), args["timeframe"])


@tool("create_manual_account", "Create a manual (non-synced) account",
      {"account_name": string("Account name"),
       "account_type": string("Account type, e.g. 'other_asset', 'loan' (see get_account_type_options)"),
       "account_sub_type": string("Account subtype, e.g. 'auto', 'mortgage' (see get_account_type_options)"),
       "include_in_net_worth": boolean("Count this account toward net worth", True),
       "balance": number("Starting balance (default 0)")},
      ["account_name", "account_type", "account_sub_type"], WRITE)
async def create_manual_account(mm: MonarchMoney, args: Args) -> Any:
    return await mm.create_manual_account(
        account_type=args["account_type"],
        account_sub_type=args["account_sub_type"],
        is_in_net_worth=args.get("include_in_net_worth", True),
        account_name=args["account_name"],
        account_balance=args.get("balance", 0),
    )


@tool("update_account",
      "Update an account's settings. balance only applies to manual accounts.",
      {"account_id": string("Account ID"),
       "account_name": string("New name"),
       "balance": number("New balance (manual accounts only)"),
       "account_type": string("New account type"),
       "account_sub_type": string("New account subtype"),
       "include_in_net_worth": boolean("Count this account toward net worth"),
       "hide_from_summary_list": boolean("Hide from the accounts summary list"),
       "hide_transactions_from_reports": boolean("Exclude this account's transactions from reports")},
      ["account_id"], WRITE)
async def update_account(mm: MonarchMoney, args: Args) -> Any:
    return await mm.update_account(**pick(args, {
        "account_id": "account_id",
        "account_name": "account_name",
        "balance": "account_balance",
        "account_type": "account_type",
        "account_sub_type": "account_sub_type",
        "include_in_net_worth": "include_in_net_worth",
        "hide_from_summary_list": "hide_from_summary_list",
        "hide_transactions_from_reports": "hide_transactions_from_reports",
    }))


@tool("delete_account", "Permanently delete an account and its transactions",
      {"account_id": string("Account ID")}, ["account_id"], DESTRUCTIVE)
async def delete_account(mm: MonarchMoney, args: Args) -> Any:
    return await mm.delete_account(args["account_id"])


@tool("upload_account_balance_history",
      "Upload daily balance history for a manual account. Replaces existing history on those dates.",
      {"account_id": string("Account ID"),
       "rows": {
           "type": "array", "minItems": 1,
           "items": {
               "type": "object",
               "properties": {"date": string("YYYY-MM-DD"), "amount": number("Balance on that date")},
               "required": ["date", "amount"],
               "additionalProperties": False,
           },
       }},
      ["account_id", "rows"], DESTRUCTIVE)
async def upload_account_balance_history(mm: MonarchMoney, args: Args) -> Any:
    rows = [BalanceHistoryRow(datetime.strptime(r["date"], "%Y-%m-%d"), r["amount"])
            for r in args["rows"]]
    completed = await mm.upload_account_balance_history(args["account_id"], rows)
    return {"account_id": args["account_id"], "rows": len(rows), "completed": completed}


@tool("refresh_accounts",
      "Request a refresh of account data from financial institutions. With wait=true, "
      "blocks until the refresh finishes (up to about 5 minutes).",
      {"account_ids": id_list("Accounts to refresh (default: all)"),
       "wait": boolean("Wait for the refresh to finish", False)},
      annotations=WRITE)
async def refresh_accounts(mm: MonarchMoney, args: Args) -> Any:
    account_ids: list[str] = args.get("account_ids") or [
        a["id"] for a in (await mm.get_accounts())["accounts"]]
    if args.get("wait"):
        done = await mm.request_accounts_refresh_and_wait(account_ids=account_ids)
        return {"account_ids": account_ids, "completed": done}
    started = await mm.request_accounts_refresh(account_ids)
    return {"account_ids": account_ids, "started": started}


@tool("get_refresh_status", "Check whether a previously requested account refresh has finished",
      {"account_ids": id_list("Accounts to check (default: all)")})
async def get_refresh_status(mm: MonarchMoney, args: Args) -> Any:
    return {"completed": await mm.is_accounts_refresh_complete(args.get("account_ids") or None)}


# --- Transactions -----------------------------------------------------------

@tool("get_transactions", "Fetch transactions with optional filtering",
      {"limit": {"type": "integer", "description": "Maximum number of transactions to return",
                 "default": 100},
       "offset": {"type": "integer", "description": "Number of transactions to skip", "default": 0},
       **DATE_RANGE,
       "search": string("Free-text search (merchant, notes, etc.)"),
       "account_id": string("Filter by a single account ID"),
       "category_id": string("Filter by a single category ID"),
       "account_ids": id_list("Filter by account IDs"),
       "category_ids": id_list("Filter by category IDs"),
       "tag_ids": id_list("Filter by tag IDs"),
       "has_attachments": boolean("Only transactions with (true) or without (false) attachments"),
       "has_notes": boolean("Only transactions with (true) or without (false) notes"),
       "hidden_from_reports": boolean("Only hidden (true) or visible (false) transactions"),
       "is_split": boolean("Only split (true) or unsplit (false) transactions"),
       "is_recurring": boolean("Only recurring (true) or non-recurring (false) transactions")})
async def get_transactions(mm: MonarchMoney, args: Args) -> Any:
    start, end = date_range(args)
    filters = pick(args, {
        "search": "search",
        "tag_ids": "tag_ids",
        "has_attachments": "has_attachments",
        "has_notes": "has_notes",
        "hidden_from_reports": "hidden_from_reports",
        "is_split": "is_split",
        "is_recurring": "is_recurring",
    })
    # The library takes lists of IDs; the single-ID arguments are kept for compatibility
    account_ids: list[str] = list(args.get("account_ids") or [])
    if args.get("account_id"):
        account_ids.append(args["account_id"])
    category_ids: list[str] = list(args.get("category_ids") or [])
    if args.get("category_id"):
        category_ids.append(args["category_id"])
    return await mm.get_transactions(
        limit=args.get("limit", 100),
        offset=args.get("offset", 0),
        start_date=start,
        end_date=end,
        account_ids=account_ids,
        category_ids=category_ids,
        **filters,
    )


@tool("get_transaction_details",
      "Get full details for one transaction (original statement text, attachments, splits, goal, etc.)",
      {"transaction_id": string("Transaction ID")}, ["transaction_id"])
async def get_transaction_details(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_transaction_details(args["transaction_id"])


@tool("get_transactions_summary",
      "Get aggregate transaction stats (count, sums, averages, date range) for the whole household")
async def get_transactions_summary(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_transactions_summary()


@tool("create_transaction", "Create a new transaction",
      {"amount": number("Transaction amount (negative for expenses)"),
       "description": string("Merchant name / description shown for the transaction"),
       "category_id": string("Category ID for the transaction"),
       "account_id": string("Account ID for the transaction"),
       "date": string("Transaction date in YYYY-MM-DD format"),
       "notes": string("Optional notes for the transaction"),
       "update_balance": boolean("Also adjust the account balance (manual accounts)", False)},
      ["amount", "description", "account_id", "date", "category_id"], WRITE)
async def create_transaction(mm: MonarchMoney, args: Args) -> Any:
    return await mm.create_transaction(
        date=require_date_arg(args, "date"),
        account_id=args["account_id"],
        amount=args["amount"],
        merchant_name=args["description"],
        category_id=args["category_id"],
        notes=args.get("notes") or "",
        update_balance=args.get("update_balance", False),
    )


@tool("update_transaction", "Update an existing transaction",
      {"transaction_id": string("ID of the transaction to update"),
       "amount": number("New transaction amount"),
       "description": string("New merchant name / description"),
       "category_id": string("New category ID"),
       "date": string("New transaction date in YYYY-MM-DD format"),
       "notes": string("New notes for the transaction"),
       "hide_from_reports": boolean("Hide this transaction from reports and budgets"),
       "needs_review": boolean("Mark the transaction as needing review"),
       "review_status": string("Review status", enum=q.REVIEW_STATUSES),
       "is_recurring": boolean("Mark as recurring or not"),
       "owner_user_id": string("Household member who owns it (see get_household_members)"),
       "business_entity_id": string("Business the transaction belongs to"),
       "goal_id": string("Legacy (pre-savings-goals) goal to link")},
      ["transaction_id"], WRITE)
async def update_transaction(mm: MonarchMoney, args: Args) -> Any:
    updates = {"id": args["transaction_id"], **pick(args, {
        "amount": "amount",
        "description": "name",
        "category_id": "category",
        "notes": "notes",
        "hide_from_reports": "hideFromReports",
        "needs_review": "needsReview",
        "review_status": "reviewStatus",
        "is_recurring": "isRecurring",
        "owner_user_id": "ownerUserId",
        "business_entity_id": "businessEntityId",
        "goal_id": "goalId",
    })}
    if "date" in args:
        updates["date"] = parse_date_arg(args, "date")
    resp = await q.execute(mm, q.UPDATE_TRANSACTION, {"input": updates})
    payload = resp.get("updateTransaction") or {}
    q.raise_payload_errors(payload.get("errors"), "Transaction update")
    return payload.get("transaction")


@tool("delete_transaction", "Permanently delete a transaction",
      {"transaction_id": string("Transaction ID")}, ["transaction_id"], DESTRUCTIVE)
async def delete_transaction(mm: MonarchMoney, args: Args) -> Any:
    return {"transaction_id": args["transaction_id"],
            "deleted": await mm.delete_transaction(args["transaction_id"])}


def bulk_selection(args: Args) -> Args:
    ids: list[str] = args["transaction_ids"]
    # expectedAffectedTransactionCount makes Monarch refuse if the selection
    # doesn't match what we think we're changing.
    return {"selectedTransactionIds": ids, "excludedTransactionIds": [], "allSelected": False,
            "expectedAffectedTransactionCount": len(ids), "filters": None}


def bulk_result(payload: Args, requested: int, action: str) -> Args:
    errors = payload.get("errors")
    if errors:
        raise RuntimeError(f"{action} failed: {errors.get('message') or errors}")
    return {"success": payload.get("success"), "requested": requested,
            "affected": payload.get("affectedCount")}


TRANSACTION_IDS: Args = {"type": "array", "minItems": 1, "maxItems": 500,
                         "items": {"type": "string"}, "description": "Transaction IDs"}
BULK_UPDATE_FIELDS = {
    "category_id": "categoryId",
    "merchant_name": "merchantName",
    "notes": "notes",
    "hide_from_reports": "hide",
    "tag_ids": "tags",
    "review_status": "reviewStatus",
    "is_recurring": "isRecurring",
    "owner_user_id": "ownerUserId",
    "business_entity_id": "businessEntityId",
}


@tool("bulk_update_transactions",
      "Apply the same change to many transactions at once. tag_ids replaces their tags.",
      {"transaction_ids": TRANSACTION_IDS,
       "category_id": string("Category to assign"),
       "merchant_name": string("Merchant name to assign"),
       "date": string("Date to set, YYYY-MM-DD"),
       "notes": string("Notes to set"),
       "hide_from_reports": boolean("Hide (true) or unhide (false)"),
       "tag_ids": id_list("Tags to set (replaces existing tags)"),
       "review_status": string("Review status", enum=q.REVIEW_STATUSES),
       "is_recurring": boolean("Mark as recurring or not"),
       "owner_user_id": string("Household member who owns them"),
       "business_entity_id": string("Business they belong to")},
      ["transaction_ids"], WRITE)
async def bulk_update_transactions(mm: MonarchMoney, args: Args) -> Any:
    updates = pick(args, BULK_UPDATE_FIELDS)
    if "date" in args:
        updates["date"] = parse_date_arg(args, "date")
    if not updates:
        raise ValueError("Nothing to update: give at least one field to change")
    resp = await q.execute(mm, q.BULK_UPDATE_TRANSACTIONS, {**bulk_selection(args), "updates": updates})
    return bulk_result(resp.get("bulkUpdateTransactions") or {}, len(args["transaction_ids"]), "Bulk update")


@tool("bulk_delete_transactions", "Permanently delete many transactions at once",
      {"transaction_ids": TRANSACTION_IDS}, ["transaction_ids"], DESTRUCTIVE)
async def bulk_delete_transactions(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.BULK_DELETE_TRANSACTIONS, bulk_selection(args))
    return bulk_result(resp.get("bulkDeleteTransactions") or {}, len(args["transaction_ids"]), "Bulk delete")


@tool("move_transactions", "Move transactions from one account to another",
      {"from_account_id": string("Account the transactions are in"),
       "to_account_id": string("Account to move them to"),
       "transaction_ids": TRANSACTION_IDS},
      ["from_account_id", "to_account_id", "transaction_ids"], WRITE)
async def move_transactions(mm: MonarchMoney, args: Args) -> Any:
    ids: list[str] = args["transaction_ids"]
    resp = await q.execute(mm, q.MOVE_TRANSACTIONS, {"input": {
        "fromAccountId": args["from_account_id"],
        "toAccountId": args["to_account_id"],
        "selectedTransactionIds": ids,
        "isAllSelected": False,
        "expectedAffectedTransactionCount": len(ids),
    }})
    payload = resp.get("moveTransactions") or {}
    q.raise_payload_errors(payload.get("errors"), "Move")
    return {"requested": len(ids), "moved": payload.get("numTransactionsMoved")}


@tool("get_transaction_splits", "Get the split lines for a transaction",
      {"transaction_id": string("Transaction ID")}, ["transaction_id"])
async def get_transaction_splits(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_transaction_splits(args["transaction_id"])


@tool("update_transaction_splits",
      "Replace a transaction's splits. Split amounts must sum to the transaction amount "
      "(same sign). An empty list removes all splits.",
      {"transaction_id": string("Transaction ID"),
       "splits": {
           "type": "array",
           "items": {
               "type": "object",
               "properties": {
                   "amount": number("Split amount (negative for expenses)"),
                   "category_id": string("Category ID"),
                   "merchant_name": string("Merchant name (default: the original's)"),
                   "notes": string("Notes for this split"),
               },
               "required": ["amount", "category_id"],
               "additionalProperties": False,
           },
       }},
      ["transaction_id", "splits"], DESTRUCTIVE)
async def update_transaction_splits(mm: MonarchMoney, args: Args) -> Any:
    splits = [pick(s, {"amount": "amount", "category_id": "categoryId",
                       "merchant_name": "merchantName", "notes": "notes"})
              for s in args["splits"]]
    resp = await mm.update_transaction_splits(args["transaction_id"], splits)
    q.raise_payload_errors((resp.get("updateTransactionSplit") or {}).get("errors"), "Split update")
    return resp


@tool("upload_transaction_attachment",
      "Attach a local file (receipt, invoice, etc.) to a transaction",
      {"transaction_id": string("Transaction ID"),
       "file_path": string("Absolute path to the file on this machine")},
      ["transaction_id", "file_path"], WRITE)
async def upload_transaction_attachment(mm: MonarchMoney, args: Args) -> Any:
    path = Path(args["file_path"]).expanduser()
    return await mm.upload_attachment(args["transaction_id"], path.read_bytes(), path.name)


# --- Tags -------------------------------------------------------------------

@tool("get_transaction_tags", "List all transaction tags")
async def get_transaction_tags(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_transaction_tags()


@tool("create_transaction_tag", "Create a transaction tag",
      {"name": string("Tag name"),
       "color": string("Hex color including '#', e.g. '#19D2A5'", default="#19D2A5")},
      ["name"], WRITE)
async def create_transaction_tag(mm: MonarchMoney, args: Args) -> Any:
    return await mm.create_transaction_tag(args["name"], args.get("color", "#19D2A5"))


@tool("set_transaction_tags",
      "Set the tags on a transaction. Replaces existing tags; an empty list removes them all.",
      {"transaction_id": string("Transaction ID"),
       "tag_ids": id_list("Tag IDs (see get_transaction_tags)")},
      ["transaction_id", "tag_ids"], WRITE)
async def set_transaction_tags(mm: MonarchMoney, args: Args) -> Any:
    return await mm.set_transaction_tags(args["transaction_id"], args["tag_ids"])


@tool("update_transaction_tag", "Rename a tag or change its color",
      {"tag_id": string("Tag ID (see get_transaction_tags)"),
       "name": string("New name"),
       "color": string("New hex color including '#'")},
      ["tag_id"], WRITE)
async def update_transaction_tag(mm: MonarchMoney, args: Args) -> Any:
    if "name" not in args and "color" not in args:
        raise ValueError("Give a new name and/or color")
    # Monarch requires both name and color, so fill in whichever wasn't given
    tags = (await mm.get_transaction_tags())["householdTransactionTags"]
    current = next((t for t in tags if t["id"] == args["tag_id"]), None)
    if current is None:
        raise ValueError(f"No tag {args['tag_id']}")
    resp = await q.execute(mm, q.UPDATE_TRANSACTION_TAG, {"input": {
        "id": args["tag_id"],
        "name": args.get("name", current["name"]),
        "color": args.get("color", current["color"]),
    }})
    payload = resp.get("updateTransactionTag") or {}
    q.raise_payload_errors(payload.get("errors"), "Tag update")
    return payload.get("tag")


@tool("delete_transaction_tag", "Delete a tag. It's removed from all transactions.",
      {"tag_id": string("Tag ID")}, ["tag_id"], DESTRUCTIVE)
async def delete_transaction_tag(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.DELETE_TRANSACTION_TAG, {"tagId": args["tag_id"]})
    q.raise_payload_errors((resp.get("deleteTransactionTag") or {}).get("errors"), "Tag deletion")
    return {"tag_id": args["tag_id"], "deleted": True}


# --- Categories -------------------------------------------------------------

@tool("get_transaction_categories", "List all transaction categories")
async def get_transaction_categories(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_transaction_categories()


@tool("get_transaction_category_groups", "List category groups (needed for create_transaction_category)")
async def get_transaction_category_groups(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_transaction_category_groups()


@tool("create_transaction_category", "Create a transaction category in a category group",
      {"group_id": string("Category group ID (see get_transaction_category_groups)"),
       "name": string("Category name"),
       "icon": string("Emoji icon", default="❓"),
       "rollover_enabled": boolean("Roll unspent budget over to the next month", False)},
      ["group_id", "name"], WRITE)
async def create_transaction_category(mm: MonarchMoney, args: Args) -> Any:
    return await mm.create_transaction_category(
        group_id=args["group_id"],
        transaction_category_name=args["name"],
        icon=args.get("icon", "❓"),
        rollover_enabled=args.get("rollover_enabled", False),
    )


@tool("update_transaction_category", "Change a category's name, icon, group, or budget settings",
      {"category_id": string("Category ID"),
       "name": string("New name"),
       "icon": string("New emoji icon"),
       "group_id": string("Move to this category group"),
       "exclude_from_budget": boolean("Leave this category out of the budget"),
       "budget_variability": string("Budget type", enum=q.BUDGET_VARIABILITIES),
       "rollover_enabled": boolean("Roll unspent budget over to the next month")},
      ["category_id"], WRITE)
async def update_transaction_category(mm: MonarchMoney, args: Args) -> Any:
    changes = pick(args, {
        "name": "name",
        "icon": "icon",
        "group_id": "group",
        "exclude_from_budget": "excludeFromBudget",
        "budget_variability": "budgetVariability",
        "rollover_enabled": "rolloverEnabled",
    })
    if not changes:
        raise ValueError("Nothing to update: give at least one field to change")
    resp = await q.execute(mm, q.UPDATE_CATEGORY, {"input": {"id": args["category_id"], **changes}})
    payload = resp.get("updateCategory") or {}
    q.raise_payload_errors(payload.get("errors"), "Category update")
    return payload.get("category")


@tool("delete_transaction_categories",
      "Delete one or more categories. Their transactions move to move_to_category_id, "
      "or become uncategorized if it isn't given.",
      {"category_ids": id_list("Category IDs to delete"),
       "move_to_category_id": string("Category to move their transactions to")},
      ["category_ids"], DESTRUCTIVE)
async def delete_transaction_categories(mm: MonarchMoney, args: Args) -> Any:
    results: list[Args] = []
    for cid in args["category_ids"]:
        try:
            resp = await q.execute(mm, q.DELETE_CATEGORY, {
                "id": cid, "moveToCategoryId": args.get("move_to_category_id")})
            payload = resp.get("deleteCategory") or {}
            q.raise_payload_errors(payload.get("errors"), "Category deletion")
            if not payload.get("deleted"):
                raise RuntimeError("Category deletion failed")
            results.append({"category_id": cid, "deleted": True})
        except Exception as e:
            results.append({"category_id": cid, "deleted": False, "error": str(e)})
    return results


CATEGORY_GROUP_FIELDS: Args = {
    "name": string("Group name"),
    "icon": string("Emoji icon"),
    "color": string("Hex color including '#'"),
    "budget_variability": string("Budget type", enum=q.BUDGET_VARIABILITIES),
}
CATEGORY_GROUP_FIELD_NAMES = {"name": "name", "icon": "icon", "color": "color",
                              "budget_variability": "budgetVariability"}


@tool("create_category_group", "Create a category group",
      {**CATEGORY_GROUP_FIELDS, "type": string("Group type", enum=q.CATEGORY_TYPES)},
      ["name", "type"], WRITE)
async def create_category_group(mm: MonarchMoney, args: Args) -> Any:
    group = {"type": args["type"], **pick(args, CATEGORY_GROUP_FIELD_NAMES)}
    resp = await q.execute(mm, q.CREATE_CATEGORY_GROUP, {"input": group})
    return (resp.get("createCategoryGroup") or {}).get("categoryGroup")


@tool("update_category_group", "Change a category group's name, icon, color, or budget type",
      {"group_id": string("Category group ID"), **CATEGORY_GROUP_FIELDS}, ["group_id"], WRITE)
async def update_category_group(mm: MonarchMoney, args: Args) -> Any:
    changes = pick(args, CATEGORY_GROUP_FIELD_NAMES)
    if not changes:
        raise ValueError("Nothing to update: give at least one field to change")
    resp = await q.execute(mm, q.UPDATE_CATEGORY_GROUP, {"input": {"id": args["group_id"], **changes}})
    return (resp.get("updateCategoryGroup") or {}).get("categoryGroup")


@tool("delete_category_group",
      "Delete a category group. Its categories move to move_to_group_id.",
      {"group_id": string("Category group ID"),
       "move_to_group_id": string("Group to move its categories to")},
      ["group_id"], DESTRUCTIVE)
async def delete_category_group(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.DELETE_CATEGORY_GROUP, {
        "id": args["group_id"], "moveToGroupId": args.get("move_to_group_id")})
    payload = resp.get("deleteCategoryGroup") or {}
    q.raise_payload_errors(payload.get("errors"), "Category group deletion")
    return {"group_id": args["group_id"], "deleted": payload.get("deleted")}


# --- Budgets and cash flow --------------------------------------------------

@tool("get_budgets", "Retrieve budget information", dict(DATE_RANGE))
async def get_budgets(mm: MonarchMoney, args: Args) -> Any:
    start, end = date_range(args)
    try:
        return await mm.get_budgets(start_date=start, end_date=end)
    except Exception as e:
        # Monarch returns this opaque error when no budgets exist
        if "Something went wrong while processing: None" in str(e):
            no_budgets: list[Args] = []
            return {"budgets": no_budgets,
                    "message": "No budgets configured in your Monarch Money account"}
        raise


@tool("set_budget_amounts",
      "Set monthly budget amounts for one or more categories or category groups. "
      "Each item needs an amount and exactly one of category_id or category_group_id. "
      "An amount of 0 clears that budget. Items are applied in order; results are "
      "reported per item.",
      {"items": {
          "type": "array", "minItems": 1, "maxItems": 100,
          "items": {
              "type": "object",
              "properties": {
                  "category_id": {"type": "string"},
                  "category_group_id": {"type": "string"},
                  "amount": {"type": "number"},
              },
              "required": ["amount"],
              "additionalProperties": False,
          },
      },
       "start_date": string("First day of the month to set, YYYY-MM-DD (default: current month)"),
       "apply_to_future": boolean("Also apply the amounts to all later months", False)},
      ["items"], WRITE)
async def set_budget_amounts(mm: MonarchMoney, args: Args) -> Any:
    start = first_of_month(args, "start_date")
    apply_to_future = bool(args.get("apply_to_future", False))

    results: list[Args] = []
    for item in args["items"]:
        category_id = item.get("category_id") or None
        group_id = item.get("category_group_id") or None
        entry: Args = {"category_id": category_id, "category_group_id": group_id,
                       "amount": item["amount"]}
        if (category_id is None) == (group_id is None):
            entry.update(ok=False, error="Provide exactly one of category_id or category_group_id")
            results.append(entry)
            continue
        try:
            resp = await mm.set_budget_amount(
                amount=item["amount"],
                category_id=category_id,
                category_group_id=group_id,
                start_date=start,
                apply_to_future=apply_to_future,
            )
            entry.update(ok=True, response=resp)
        except Exception as e:
            entry.update(ok=False, error=str(e))
        results.append(entry)

    return {
        "start_date": start or "current month",
        "apply_to_future": apply_to_future,
        "succeeded": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }


@tool("get_cashflow", "Cash flow broken down by category, category group, and merchant",
      dict(DATE_RANGE))
async def get_cashflow(mm: MonarchMoney, args: Args) -> Any:
    start, end = date_range(args)
    return await mm.get_cashflow(start_date=start, end_date=end)


@tool("get_cashflow_summary", "Total income, expenses, savings, and savings rate for a period",
      dict(DATE_RANGE))
async def get_cashflow_summary(mm: MonarchMoney, args: Args) -> Any:
    start, end = date_range(args)
    return await mm.get_cashflow_summary(start_date=start, end_date=end)


@tool("get_recurring_transactions",
      "List upcoming recurring transactions (bills, subscriptions, income) with merchant, "
      "amount, and account. Defaults to the current month.",
      dict(DATE_RANGE))
async def get_recurring_transactions(mm: MonarchMoney, args: Args) -> Any:
    start, end = date_range(args)
    return await mm.get_recurring_transactions(start_date=start, end_date=end)


@tool("get_recurring_streams",
      "List every recurring series (subscriptions, bills, income) with frequency and amount",
      {"include_liabilities": boolean("Include credit card and loan payments", True)})
async def get_recurring_streams(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.GET_RECURRING_STREAMS,
                           {"includeLiabilities": args.get("include_liabilities", True)})
    return [item["stream"] for item in resp.get("recurringTransactionStreams") or []]


@tool("get_recurring_remaining_due",
      "Total recurring amount still due in a period (default: the current month)",
      {**DATE_RANGE,
       "include_liabilities": boolean("Include credit card and loan payments", True)})
async def get_recurring_remaining_due(mm: MonarchMoney, args: Args) -> Any:
    start, end = date_range(args)
    if not start:
        start, end = month_bounds(date.today())
    resp = await q.execute(mm, q.GET_RECURRING_REMAINING_DUE, {
        "startDate": start, "endDate": end,
        "includeLiabilities": args.get("include_liabilities", True)})
    return {"start_date": start, "end_date": end,
            "amount": (resp.get("recurringRemainingDue") or {}).get("amount")}


@tool("mark_stream_not_recurring",
      "Stop treating a recurring series as recurring (see get_recurring_streams for IDs)",
      {"stream_id": string("Recurring stream ID")}, ["stream_id"], WRITE)
async def mark_stream_not_recurring(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.MARK_STREAM_NOT_RECURRING, {"streamId": args["stream_id"]})
    payload = resp.get("markStreamAsNotRecurring") or {}
    q.raise_payload_errors(payload.get("errors"), "Marking not recurring")
    return {"stream_id": args["stream_id"], "success": payload.get("success")}


# --- Transaction rules ------------------------------------------------------

@tool("list_transaction_rules",
      "List the household's transaction rules (conditions and actions) in priority order")
async def list_transaction_rules(mm: MonarchMoney, args: Args) -> Any:
    return await q.execute(mm, q.GET_RULES)


RULE_FIELDS: Args = {
       "merchant_contains": string("Merchant name contains this text"),
       "merchant_equals": string("Merchant name equals this text"),
       "use_original_statement": boolean(
           "Match the raw bank statement text instead of the merchant name", False),
       "amount": {
           "type": "object",
           "description": "Amount condition, e.g. {operator: 'gt', value: 80}",
           "properties": {
               "operator": {"type": "string", "enum": ["eq", "gt", "lt", "between"]},
               "value": {"type": "number"},
               "lower": {"type": "number"},
               "upper": {"type": "number"},
               "is_expense": {"type": "boolean", "default": True},
           },
           "required": ["operator"],
           "additionalProperties": False,
       },
       "account_ids": id_list("Only match transactions in these accounts"),
       "match_category_ids": id_list("Only match transactions currently in these categories"),
       "set_category_id": string("Category to assign"),
       "set_merchant_name": string("Merchant name to assign"),
       "add_tag_ids": id_list("Tags to add"),
       "apply_to_existing": boolean("Also apply to matching past transactions", False)}
RULE_HELP = ("Conditions (combine as needed): merchant_contains / merchant_equals, amount, "
             "account_ids, match_category_ids. Actions: set_category_id, set_merchant_name, "
             "and/or add_tag_ids.")


@tool("create_transaction_rule",
      f"Create a transaction rule. {RULE_HELP} apply_to_existing defaults to false; setting it "
      "true rewrites matching past transactions (check first with preview_transaction_rule).",
      RULE_FIELDS, annotations=WRITE)
async def create_transaction_rule(mm: MonarchMoney, args: Args) -> Any:
    rule_input = q.build_rule_input(args)
    resp = await q.execute(mm, q.CREATE_RULE, {"input": rule_input})
    payload = resp.get("createTransactionRuleV2") or {}
    q.raise_payload_errors(payload.get("errors"), "Rule creation")
    return {"created": payload.get("transactionRule"), "input": rule_input}


@tool("delete_transaction_rule", "Delete a transaction rule by id (use list_transaction_rules to find it)",
      {"rule_id": {"type": "string"}}, ["rule_id"], DESTRUCTIVE)
async def delete_transaction_rule(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.DELETE_RULE, {"id": args["rule_id"]})
    payload = resp.get("deleteTransactionRule") or {}
    q.raise_payload_errors(payload.get("errors"), "Rule deletion")
    # Monarch's `deleted` flag isn't reliable (it can come back false on
    # success), so confirm by checking whether the rule still exists.
    rules = await q.execute(mm, q.GET_RULES)
    still_there = any(r.get("id") == args["rule_id"] for r in rules.get("transactionRules") or [])
    return {"rule_id": args["rule_id"], "deleted": not still_there,
            "api_deleted_flag": payload.get("deleted")}


@tool("update_transaction_rule",
      f"Replace a rule's conditions and actions (anything not given is cleared). {RULE_HELP}",
      {"rule_id": string("Rule ID (see list_transaction_rules)"), **RULE_FIELDS},
      ["rule_id"], DESTRUCTIVE)
async def update_transaction_rule(mm: MonarchMoney, args: Args) -> Any:
    rule_input = {"id": args["rule_id"], **q.build_rule_input(args)}
    resp = await q.execute(mm, q.UPDATE_RULE, {"input": rule_input})
    q.raise_payload_errors((resp.get("updateTransactionRuleV2") or {}).get("errors"), "Rule update")
    return {"updated": args["rule_id"], "input": rule_input}


@tool("set_transaction_rule_order",
      "Move a rule to a new priority position (0 = first). Returns the new order of all rules.",
      {"rule_id": string("Rule ID"),
       "order": {"type": "integer", "minimum": 0, "description": "New position, 0-based"}},
      ["rule_id", "order"], WRITE)
async def set_transaction_rule_order(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.UPDATE_RULE_ORDER, {"id": args["rule_id"], "order": args["order"]})
    return (resp.get("updateTransactionRuleOrderV2") or {}).get("transactionRules")


@tool("preview_transaction_rule",
      f"Show which existing transactions a rule would change, without saving it. {RULE_HELP} "
      "Returns the total count and up to 30 matches per call.",
      {**{k: v for k, v in RULE_FIELDS.items() if k != "apply_to_existing"},
       "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "Matches to skip"}})
async def preview_transaction_rule(mm: MonarchMoney, args: Args) -> Any:
    rule_input = q.build_rule_input(args)
    resp = await q.execute(mm, q.PREVIEW_RULE, {"rule": rule_input, "offset": args.get("offset", 0)})
    return resp.get("transactionRulePreview")


# --- Goals ------------------------------------------------------------------

GOAL_FIELDS: Args = {
    "name": string("Goal name"),
    "type": string("Goal type", enum=q.GOAL_TYPES),
    "target_amount": number("Target amount"),
    "target_date": string("Target date in YYYY-MM-DD format"),
    "planned_monthly_contribution": number("Planned monthly contribution"),
    "priority": {"type": "integer", "description": "Priority rank (1 = highest)"},
    "is_sinking_fund": boolean("Treat as a sinking fund (money is spent from the goal)"),
}
GOAL_FIELD_NAMES = {
    "name": "name",
    "type": "type",
    "target_amount": "targetAmount",
    "planned_monthly_contribution": "plannedMonthlyContribution",
    "priority": "priority",
    "is_sinking_fund": "isSinkingFund",
}


def goal_input(args: Args) -> Args:
    goal = pick(args, GOAL_FIELD_NAMES)
    if "target_date" in args:
        goal["targetDate"] = parse_date_arg(args, "target_date")
    return goal


@tool("get_goals", "List savings goals with balances, progress, and per-account allocations")
async def get_goals(mm: MonarchMoney, args: Args) -> Any:
    return await q.execute(mm, q.GET_SAVINGS_GOALS)


@tool("create_goal", "Create a savings goal", GOAL_FIELDS, ["name", "type"], WRITE)
async def create_goal(mm: MonarchMoney, args: Args) -> Any:
    return await q.execute(mm, q.CREATE_SAVINGS_GOALS, {"input": {"goals": [goal_input(args)]}})


@tool("update_goal", "Update a savings goal's settings",
      {"goal_id": string("Goal ID (see get_goals)"), **GOAL_FIELDS}, ["goal_id"], WRITE)
async def update_goal(mm: MonarchMoney, args: Args) -> Any:
    goal = {"id": args["goal_id"], **goal_input(args)}
    resp = await q.execute(mm, q.UPDATE_SAVINGS_GOAL, {"input": goal})
    payload = resp.get("updateSavingsGoal") or {}
    q.raise_payload_errors(payload.get("errors"), "Goal update")
    return payload.get("savingsGoal")


async def goal_id_mutation(mm: MonarchMoney, request: GraphQLRequest, field: str,
                           goal_id: str, action: str) -> Args:
    resp = await q.execute(mm, request, {"input": {"id": goal_id}})
    payload: Args = resp.get(field) or {}
    q.raise_payload_errors(payload.get("errors"), action)
    return payload


@tool("archive_goal", "Archive a savings goal (can be restored with unarchive_goal)",
      {"goal_id": string("Goal ID")}, ["goal_id"], WRITE)
async def archive_goal(mm: MonarchMoney, args: Args) -> Any:
    return await goal_id_mutation(mm, q.ARCHIVE_SAVINGS_GOAL, "archiveSavingsGoal",
                                  args["goal_id"], "Goal archive")


@tool("unarchive_goal", "Restore an archived savings goal",
      {"goal_id": string("Goal ID")}, ["goal_id"], WRITE)
async def unarchive_goal(mm: MonarchMoney, args: Args) -> Any:
    return await goal_id_mutation(mm, q.UNARCHIVE_SAVINGS_GOAL, "unarchiveSavingsGoal",
                                  args["goal_id"], "Goal unarchive")


@tool("delete_goal", "Permanently delete a savings goal and its contribution history",
      {"goal_id": string("Goal ID")}, ["goal_id"], DESTRUCTIVE)
async def delete_goal(mm: MonarchMoney, args: Args) -> Any:
    return await goal_id_mutation(mm, q.DELETE_SAVINGS_GOAL, "deleteSavingsGoal",
                                  args["goal_id"], "Goal deletion")


GOAL_MONEY_FIELDS: Args = {
    "goal_id": string("Goal ID (see get_goals)"),
    "account_id": string("Account the money is held in"),
    "amount": number("Amount (positive)"),
    "date": string("Date in YYYY-MM-DD format (default: today)"),
    "notes": string("Optional note"),
}


def goal_money_input(args: Args) -> Args:
    money: Args = {"id": args["goal_id"], "accountId": args["account_id"], "amount": args["amount"]}
    if args.get("date"):
        money["date"] = parse_date_arg(args, "date")
    if args.get("notes"):
        money["notes"] = args["notes"]
    return money


@tool("contribute_to_goal", "Record a contribution from an account to a savings goal",
      GOAL_MONEY_FIELDS, ["goal_id", "account_id", "amount"], WRITE)
async def contribute_to_goal(mm: MonarchMoney, args: Args) -> Any:
    return await q.execute(mm, q.CONTRIBUTE_TO_SAVINGS_GOAL, {"input": goal_money_input(args)})


@tool("withdraw_from_goal", "Record a withdrawal from a savings goal back to an account",
      GOAL_MONEY_FIELDS, ["goal_id", "account_id", "amount"], WRITE)
async def withdraw_from_goal(mm: MonarchMoney, args: Args) -> Any:
    return await q.execute(mm, q.WITHDRAW_FROM_SAVINGS_GOAL, {"input": goal_money_input(args)})


@tool("set_goal_budget_amount", "Set the monthly budgeted contribution for a savings goal",
      {"goal_id": string("Goal ID"),
       "amount": number("Monthly amount"),
       "month": string("Any date in the month, YYYY-MM-DD (default: current month)"),
       "apply_to_future": boolean("Also apply to all later months", False),
       "account_id": string("Account the contribution comes from (optional)")},
      ["goal_id", "amount"], WRITE)
async def set_goal_budget_amount(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.SET_SAVINGS_GOAL_BUDGET_AMOUNT, {"input": {
        "savingsGoalId": args["goal_id"],
        "amount": args["amount"],
        "month": first_of_month(args, "month") or date.today().replace(day=1).isoformat(),
        "applyToFuture": args.get("apply_to_future", False),
        "accountId": args.get("account_id"),
    }})
    payload = resp.get("setSavingsGoalBudgetAmount") or {}
    q.raise_payload_errors(payload.get("errors"), "Goal budget update")
    return payload


# --- Merchants --------------------------------------------------------------

@tool("get_merchants", "List or search merchants with transaction counts and default categories",
      {"search": string("Filter by name"),
       "limit": {"type": "integer", "description": "Maximum results", "default": 100},
       "offset": {"type": "integer", "description": "Results to skip", "default": 0},
       "order_by": string("Sort order", enum=q.MERCHANT_ORDERINGS, default="TRANSACTION_COUNT")})
async def get_merchants(mm: MonarchMoney, args: Args) -> Any:
    return await q.execute(mm, q.GET_MERCHANTS, {
        "search": args.get("search") or None,
        "limit": args.get("limit", 100),
        "offset": args.get("offset", 0),
        "orderBy": args.get("order_by", "TRANSACTION_COUNT"),
    })


@tool("get_merchant", "Get one merchant's details, including rule count and recurring settings",
      {"merchant_id": string("Merchant ID")}, ["merchant_id"])
async def get_merchant(mm: MonarchMoney, args: Args) -> Any:
    return await q.execute(mm, q.GET_MERCHANT, {"merchantId": args["merchant_id"]})


@tool("update_merchant",
      "Rename a merchant, set its default category, or change its recurring settings. "
      "Renaming applies to all of the merchant's transactions.",
      {"merchant_id": string("Merchant ID"),
       "name": string("New name"),
       "default_category_id": string("Category new transactions from this merchant get"),
       "default_category_mode": string(
           "new_only: only new transactions; new_and_edits: also when a transaction's "
           "merchant is changed to this one", enum=["new_only", "new_and_edits"]),
       "recurrence": {
           "type": "object",
           "description": "Recurring settings. is_recurring=false stops treating it as recurring.",
           "properties": {
               "is_recurring": {"type": "boolean"},
               "frequency": {"type": "string", "enum": q.RECURRENCE_FREQUENCIES},
               "base_date": string("A date the charge occurs on, YYYY-MM-DD"),
               "amount": number("Expected amount (negative for expenses)"),
               "is_active": {"type": "boolean"},
           },
           "required": ["is_recurring"],
           "additionalProperties": False,
       }},
      ["merchant_id"], WRITE)
async def update_merchant(mm: MonarchMoney, args: Args) -> Any:
    merchant: Args = {"merchantId": args["merchant_id"], **pick(args, {
        "name": "name",
        "default_category_id": "defaultCategoryId",
        "default_category_mode": "defaultCategoryApplicationMode",
    })}
    if "recurrence" in args:
        merchant["recurrence"] = pick(args["recurrence"], {
            "is_recurring": "isRecurring",
            "frequency": "frequency",
            "base_date": "baseDate",
            "amount": "amount",
            "is_active": "isActive",
        })
    resp = await q.execute(mm, q.UPDATE_MERCHANT, {"input": merchant})
    payload = resp.get("updateMerchant") or {}
    q.raise_payload_errors(payload.get("errors"), "Merchant update")
    return payload.get("merchant")


@tool("delete_merchant",
      "Merge a merchant into move_to_merchant_id: its transactions, rules, and recurring "
      "settings move there and the merchant is removed. Without move_to_merchant_id, Monarch "
      "usually refuses (even for merchants with no transactions).",
      {"merchant_id": string("Merchant to delete"),
       "move_to_merchant_id": string("Merchant to merge into")},
      ["merchant_id"], DESTRUCTIVE)
async def delete_merchant(mm: MonarchMoney, args: Args) -> Any:
    if not args.get("move_to_merchant_id"):
        # Monarch answers an undeletable merchant with an opaque server error
        merchant = (await q.execute(mm, q.GET_MERCHANT, {"merchantId": args["merchant_id"]})).get("merchant")
        if not merchant:
            raise ValueError(f"No merchant {args['merchant_id']}")
        if not merchant.get("canBeDeleted"):
            raise ValueError("Monarch can't delete this merchant directly; "
                             "pass move_to_merchant_id to merge it into another merchant")
    resp = await q.execute(mm, q.DELETE_MERCHANT, {
        "merchantId": args["merchant_id"],
        "moveToId": args.get("move_to_merchant_id"),
    })
    return {"merchant_id": args["merchant_id"],
            "merged_into": args.get("move_to_merchant_id"),
            "success": (resp.get("deleteMerchant") or {}).get("success")}


# --- Other ------------------------------------------------------------------

@tool("get_household_members", "List household members (IDs for owner_user_id)")
async def get_household_members(mm: MonarchMoney, args: Args) -> Any:
    return (await q.execute(mm, q.GET_HOUSEHOLD_MEMBERS)).get("myHousehold")


@tool("search_entities",
      "Find accounts, categories, merchants, tags, and other items by name, like the "
      "web app's command palette",
      {"query": string("What to search for")}, ["query"])
async def search_entities(mm: MonarchMoney, args: Args) -> Any:
    resp = await q.execute(mm, q.SEMANTIC_SEARCH, {"query": args["query"]})
    return (resp.get("semanticSearch") or {}).get("results")


@tool("get_credit_history", "Get credit score history")
async def get_credit_history(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_credit_history()


@tool("get_subscription_details", "Get the Monarch Money subscription plan and status")
async def get_subscription_details(mm: MonarchMoney, args: Args) -> Any:
    return await mm.get_subscription_details()


# ---------------------------------------------------------------------------

def list_tools() -> list[Tool]:
    """List all available tools."""
    return [t for t, _ in TOOLS.values()]


async def call_tool(name: str, arguments: Args | None) -> CallToolResult:
    """Execute a tool and return the results."""
    if not mm_client:
        return error("Error: MonarchMoney client not initialized")
    if name not in TOOLS:
        return error(f"Error: Unknown tool '{name}'")

    handler = TOOLS[name][1]
    try:
        try:
            return result(await handler(mm_client, arguments or {}))
        except Exception as e:
            if not auth.is_auth_error(e):
                raise
            # The token stopped working; log in again and retry once.
            return result(await handler(await renew_client(mm_client), arguments or {}))
    except Exception as e:
        return error(f"Error executing {name}: {str(e)}")


async def on_list_tools(ctx: ServerRequestContext[Any],
                        params: PaginatedRequestParams | None) -> ListToolsResult:
    return ListToolsResult(tools=list_tools())


async def on_call_tool(ctx: ServerRequestContext[Any],
                       params: CallToolRequestParams) -> CallToolResult:
    return await call_tool(params.name, params.arguments)


server: Server[Any] = Server("monarch-money", version="1.0.0",
                             on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def renew_client(stale: MonarchMoney) -> MonarchMoney:
    global mm_client
    mm_client = await authenticator.renew(stale)
    return mm_client


async def serve() -> None:
    """Authenticate, then run the MCP server over stdio."""
    global mm_client
    try:
        mm_client = await authenticator.client()
    except Exception as e:
        print(f"Failed to initialize MonarchMoney client: {e}", file=sys.stderr)
        return

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def login() -> None:
    path = await auth.interactive_login(os.environ, input, getpass.getpass)
    print(f"Saved session to {path}")
    for legacy in auth.remove_legacy_sessions():
        print(f"Removed old session file {legacy}")


def logout() -> None:
    path = auth.session_file(os.environ)
    if auth.delete_token(path):
        print(f"Removed {path}")
    else:
        print(f"No session at {path}")


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point."""
    parser = argparse.ArgumentParser(prog="monarch-money-mcp")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("serve", help="Run the MCP server over stdio (default)")
    commands.add_parser("login", help="Log in once and save only the session token")
    commands.add_parser("logout", help="Delete the saved session token")
    command = parser.parse_args(argv).command

    if command == "login":
        try:
            asyncio.run(login())
        except Exception as e:
            sys.exit(f"Login failed: {e}")
    elif command == "logout":
        logout()
    else:
        asyncio.run(serve())


if __name__ == "__main__":
    main()
