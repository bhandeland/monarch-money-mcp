#!/usr/bin/env python3
"""MonarchMoney MCP Server - Provides access to Monarch Money financial data via MCP protocol."""

import os
import sys
import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, Optional, List
from datetime import datetime, date
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.types import ServerCapabilities, Tool, TextContent, ToolAnnotations
from monarchmoney import MonarchMoney
from monarchmoney.monarchmoney import BalanceHistoryRow

import monarch_gql as q


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


def parse_date_arg(arguments: Dict[str, Any], key: str) -> Optional[str]:
    """Validate a YYYY-MM-DD argument and return it as a string.

    The monarchmoney library puts dates straight into GraphQL variables, so it
    needs strings. Passing date objects causes "Object of type date is not JSON
    serializable".
    """
    value = arguments.get(key)
    if value in (None, ""):
        return None
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def date_range_args(arguments: Dict[str, Any]) -> Dict[str, str]:
    """start_date/end_date kwargs. The Monarch API rejects one without the other."""
    start = parse_date_arg(arguments, "start_date")
    end = parse_date_arg(arguments, "end_date")
    if bool(start) != bool(end):
        raise ValueError("Provide both start_date and end_date, or neither.")
    return {"start_date": start, "end_date": end} if start else {}


def first_of_month(arguments: Dict[str, Any], key: str) -> Optional[str]:
    """Budgets are keyed by the first of the month."""
    value = parse_date_arg(arguments, key)
    return value[:8] + "01" if value else None


def pick(arguments: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """Copy the arguments that were provided, renaming tool keys to API keys."""
    return {api: arguments[arg] for arg, api in mapping.items() if arg in arguments}


def result(data: Any) -> List[TextContent]:
    return [TextContent(type="text", text=json.dumps(convert_dates_to_strings(data), indent=2))]


# Initialize the MCP server
server = Server("monarch-money")

# Global variable to store the MonarchMoney client
mm_client: Optional[MonarchMoney] = None
session_file = Path.home() / ".monarchmoney_session"


async def initialize_client():
    """Initialize the MonarchMoney client with authentication."""
    global mm_client

    email = os.getenv("MONARCH_EMAIL")
    password = os.getenv("MONARCH_PASSWORD")
    mfa_secret = os.getenv("MONARCH_MFA_SECRET")

    if not email or not password:
        raise ValueError("MONARCH_EMAIL and MONARCH_PASSWORD environment variables are required")

    mm_client = MonarchMoney()

    # Try to load existing session first
    if session_file.exists() and not os.getenv("MONARCH_FORCE_LOGIN"):
        try:
            mm_client.load_session(str(session_file))
            # Test if session is still valid
            await mm_client.get_accounts()
            print("Loaded existing session successfully", file=sys.stderr)
            return
        except Exception:
            print("Existing session invalid, logging in fresh", file=sys.stderr)

    # Login with credentials
    if mfa_secret:
        await mm_client.login(email, password, mfa_secret_key=mfa_secret)
    else:
        await mm_client.login(email, password)

    # Save session for future use
    mm_client.save_session(str(session_file))
    print("Logged in and saved session", file=sys.stderr)


# ---------------------------------------------------------------------------
# Tool registry. Each handler takes the client and the tool arguments and
# returns JSON-serializable data.
# ---------------------------------------------------------------------------
Handler = Callable[[MonarchMoney, Dict[str, Any]], Awaitable[Any]]
TOOLS: Dict[str, tuple] = {}

READ = ToolAnnotations(readOnlyHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


def tool(name: str, description: str, properties: Optional[Dict[str, Any]] = None,
         required: Optional[List[str]] = None, annotations: ToolAnnotations = READ):
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required

    def register(fn: Handler) -> Handler:
        TOOLS[name] = (Tool(name=name, description=description, inputSchema=schema,
                            annotations=annotations), fn)
        return fn
    return register


def string(description: str, **extra) -> Dict[str, Any]:
    return {"type": "string", "description": description, **extra}


def number(description: str) -> Dict[str, Any]:
    return {"type": "number", "description": description}


def boolean(description: str, default: Optional[bool] = None) -> Dict[str, Any]:
    prop: Dict[str, Any] = {"type": "boolean", "description": description}
    if default is not None:
        prop["default"] = default
    return prop


def id_list(description: str) -> Dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


DATE_RANGE = {
    "start_date": string("Start date in YYYY-MM-DD format (requires end_date)"),
    "end_date": string("End date in YYYY-MM-DD format (requires start_date)"),
}


# --- Accounts ---------------------------------------------------------------

@tool("get_accounts", "Retrieve all linked financial accounts")
async def get_accounts(mm, args):
    return await mm.get_accounts()


@tool("get_account_type_options",
      "List valid account types and subtypes (needed for create_manual_account / update_account)")
async def get_account_type_options(mm, args):
    return await mm.get_account_type_options()


@tool("get_institutions", "List connected financial institutions and their connection status")
async def get_institutions(mm, args):
    return await mm.get_institutions()


@tool("get_account_holdings", "Get investment holdings for a brokerage or similar account",
      {"account_id": string("Account ID")}, ["account_id"])
async def get_account_holdings(mm, args):
    return await mm.get_account_holdings(int(args["account_id"]))


@tool("get_account_history", "Get the full daily balance history for one account",
      {"account_id": string("Account ID")}, ["account_id"])
async def get_account_history(mm, args):
    return await mm.get_account_history(int(args["account_id"]))


@tool("get_recent_account_balances",
      "Get daily balances for all accounts from start_date (default: last 31 days)",
      {"start_date": string("Start date in YYYY-MM-DD format")})
async def get_recent_account_balances(mm, args):
    return await mm.get_recent_account_balances(parse_date_arg(args, "start_date"))


@tool("get_net_worth_history",
      "Get the daily net worth (sum of all accounts), optionally limited to one account type",
      {**DATE_RANGE,
       "account_type": string("Only include accounts of this type, e.g. 'brokerage' "
                              "(see get_account_type_options)")})
async def get_net_worth_history(mm, args):
    return await mm.get_aggregate_snapshots(
        **date_range_args(args), account_type=args.get("account_type"))


@tool("get_account_snapshots_by_type",
      "Get net balances grouped by account type, by month or by year",
      {"start_date": string("Start date in YYYY-MM-DD format"),
       "timeframe": string("Granularity", enum=["month", "year"])},
      ["start_date", "timeframe"])
async def get_account_snapshots_by_type(mm, args):
    return await mm.get_account_snapshots_by_type(
        parse_date_arg(args, "start_date"), args["timeframe"])


@tool("create_manual_account", "Create a manual (non-synced) account",
      {"account_name": string("Account name"),
       "account_type": string("Account type, e.g. 'other_asset', 'loan' (see get_account_type_options)"),
       "account_sub_type": string("Account subtype, e.g. 'auto', 'mortgage' (see get_account_type_options)"),
       "include_in_net_worth": boolean("Count this account toward net worth", True),
       "balance": number("Starting balance (default 0)")},
      ["account_name", "account_type", "account_sub_type"], WRITE)
async def create_manual_account(mm, args):
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
async def update_account(mm, args):
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
async def delete_account(mm, args):
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
async def upload_account_balance_history(mm, args):
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
async def refresh_accounts(mm, args):
    account_ids = args.get("account_ids") or [a["id"] for a in (await mm.get_accounts())["accounts"]]
    if args.get("wait"):
        done = await mm.request_accounts_refresh_and_wait(account_ids=account_ids)
        return {"account_ids": account_ids, "completed": done}
    started = await mm.request_accounts_refresh(account_ids)
    return {"account_ids": account_ids, "started": started}


@tool("get_refresh_status", "Check whether a previously requested account refresh has finished",
      {"account_ids": id_list("Accounts to check (default: all)")})
async def get_refresh_status(mm, args):
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
async def get_transactions(mm, args):
    filters = date_range_args(args)
    filters.update(pick(args, {
        "search": "search",
        "tag_ids": "tag_ids",
        "has_attachments": "has_attachments",
        "has_notes": "has_notes",
        "hidden_from_reports": "hidden_from_reports",
        "is_split": "is_split",
        "is_recurring": "is_recurring",
    }))
    # The library takes lists of IDs; the single-ID arguments are kept for compatibility
    account_ids = list(args.get("account_ids") or [])
    if args.get("account_id"):
        account_ids.append(args["account_id"])
    category_ids = list(args.get("category_ids") or [])
    if args.get("category_id"):
        category_ids.append(args["category_id"])
    return await mm.get_transactions(
        limit=args.get("limit", 100),
        offset=args.get("offset", 0),
        account_ids=account_ids,
        category_ids=category_ids,
        **filters,
    )


@tool("get_transaction_details",
      "Get full details for one transaction (original statement text, attachments, splits, goal, etc.)",
      {"transaction_id": string("Transaction ID")}, ["transaction_id"])
async def get_transaction_details(mm, args):
    return await mm.get_transaction_details(args["transaction_id"])


@tool("get_transactions_summary",
      "Get aggregate transaction stats (count, sums, averages, date range) for the whole household")
async def get_transactions_summary(mm, args):
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
async def create_transaction(mm, args):
    return await mm.create_transaction(
        date=parse_date_arg(args, "date"),
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
       "needs_review": boolean("Mark the transaction as needing review")},
      ["transaction_id"], WRITE)
async def update_transaction(mm, args):
    updates = pick(args, {
        "transaction_id": "transaction_id",
        "amount": "amount",
        "description": "merchant_name",
        "category_id": "category_id",
        "notes": "notes",
        "hide_from_reports": "hide_from_reports",
        "needs_review": "needs_review",
    })
    if "date" in args:
        updates["date"] = parse_date_arg(args, "date")
    return await mm.update_transaction(**updates)


@tool("delete_transaction", "Permanently delete a transaction",
      {"transaction_id": string("Transaction ID")}, ["transaction_id"], DESTRUCTIVE)
async def delete_transaction(mm, args):
    return {"transaction_id": args["transaction_id"],
            "deleted": await mm.delete_transaction(args["transaction_id"])}


@tool("get_transaction_splits", "Get the split lines for a transaction",
      {"transaction_id": string("Transaction ID")}, ["transaction_id"])
async def get_transaction_splits(mm, args):
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
async def update_transaction_splits(mm, args):
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
async def upload_transaction_attachment(mm, args):
    path = Path(args["file_path"]).expanduser()
    return await mm.upload_attachment(args["transaction_id"], path.read_bytes(), path.name)


# --- Tags -------------------------------------------------------------------

@tool("get_transaction_tags", "List all transaction tags")
async def get_transaction_tags(mm, args):
    return await mm.get_transaction_tags()


@tool("create_transaction_tag", "Create a transaction tag",
      {"name": string("Tag name"),
       "color": string("Hex color including '#', e.g. '#19D2A5'", default="#19D2A5")},
      ["name"], WRITE)
async def create_transaction_tag(mm, args):
    return await mm.create_transaction_tag(args["name"], args.get("color", "#19D2A5"))


@tool("set_transaction_tags",
      "Set the tags on a transaction. Replaces existing tags; an empty list removes them all.",
      {"transaction_id": string("Transaction ID"),
       "tag_ids": id_list("Tag IDs (see get_transaction_tags)")},
      ["transaction_id", "tag_ids"], WRITE)
async def set_transaction_tags(mm, args):
    return await mm.set_transaction_tags(args["transaction_id"], args["tag_ids"])


# --- Categories -------------------------------------------------------------

@tool("get_transaction_categories", "List all transaction categories")
async def get_transaction_categories(mm, args):
    return await mm.get_transaction_categories()


@tool("get_transaction_category_groups", "List category groups (needed for create_transaction_category)")
async def get_transaction_category_groups(mm, args):
    return await mm.get_transaction_category_groups()


@tool("create_transaction_category", "Create a transaction category in a category group",
      {"group_id": string("Category group ID (see get_transaction_category_groups)"),
       "name": string("Category name"),
       "icon": string("Emoji icon", default="❓"),
       "rollover_enabled": boolean("Roll unspent budget over to the next month", False)},
      ["group_id", "name"], WRITE)
async def create_transaction_category(mm, args):
    return await mm.create_transaction_category(
        group_id=args["group_id"],
        transaction_category_name=args["name"],
        icon=args.get("icon", "❓"),
        rollover_enabled=args.get("rollover_enabled", False),
    )


@tool("delete_transaction_categories",
      "Delete one or more categories. Their transactions become uncategorized.",
      {"category_ids": id_list("Category IDs to delete")}, ["category_ids"], DESTRUCTIVE)
async def delete_transaction_categories(mm, args):
    outcomes = await mm.delete_transaction_categories(args["category_ids"])
    return [{"category_id": cid, "deleted": ok is True, **({} if ok is True else {"error": str(ok)})}
            for cid, ok in zip(args["category_ids"], outcomes)]


# --- Budgets and cash flow --------------------------------------------------

@tool("get_budgets", "Retrieve budget information", dict(DATE_RANGE))
async def get_budgets(mm, args):
    try:
        return await mm.get_budgets(**date_range_args(args))
    except Exception as e:
        # Monarch returns this opaque error when no budgets exist
        if "Something went wrong while processing: None" in str(e):
            return {"budgets": [], "message": "No budgets configured in your Monarch Money account"}
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
async def set_budget_amounts(mm, args):
    start = first_of_month(args, "start_date")
    apply_to_future = bool(args.get("apply_to_future", False))

    results = []
    for item in args["items"]:
        category_id = item.get("category_id") or None
        group_id = item.get("category_group_id") or None
        entry = {"category_id": category_id, "category_group_id": group_id, "amount": item["amount"]}
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
async def get_cashflow(mm, args):
    return await mm.get_cashflow(**date_range_args(args))


@tool("get_cashflow_summary", "Total income, expenses, savings, and savings rate for a period",
      dict(DATE_RANGE))
async def get_cashflow_summary(mm, args):
    return await mm.get_cashflow_summary(**date_range_args(args))


@tool("get_recurring_transactions",
      "List upcoming recurring transactions (bills, subscriptions, income) with merchant, "
      "amount, and account. Defaults to the current month.",
      dict(DATE_RANGE))
async def get_recurring_transactions(mm, args):
    return await mm.get_recurring_transactions(**date_range_args(args))


# --- Transaction rules ------------------------------------------------------

@tool("list_transaction_rules",
      "List the household's transaction rules (conditions and actions) in priority order")
async def list_transaction_rules(mm, args):
    return await mm.gql_call(operation="GetTransactionRules", graphql_query=q.GET_RULES, variables={})


@tool("create_transaction_rule",
      "Create a transaction rule. Conditions (combine as needed): merchant_contains / "
      "merchant_equals, amount, account_ids, match_category_ids. Actions: set_category_id, "
      "set_merchant_name, and/or add_tag_ids. apply_to_existing defaults to false; setting it "
      "true rewrites matching past transactions.",
      {"merchant_contains": string("Merchant name contains this text"),
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
       "apply_to_existing": boolean("Also apply to matching past transactions", False)},
      annotations=WRITE)
async def create_transaction_rule(mm, args):
    rule_input = q.build_rule_input(args)
    resp = await mm.gql_call(
        operation="Common_CreateTransactionRuleMutationV2",
        graphql_query=q.CREATE_RULE,
        variables={"input": rule_input},
    )
    payload = (resp or {}).get("createTransactionRuleV2") or {}
    q.raise_payload_errors(payload.get("errors"), "Rule creation")
    return {"created": payload.get("transactionRule"), "input": rule_input}


@tool("delete_transaction_rule", "Delete a transaction rule by id (use list_transaction_rules to find it)",
      {"rule_id": {"type": "string"}}, ["rule_id"], DESTRUCTIVE)
async def delete_transaction_rule(mm, args):
    resp = await mm.gql_call(
        operation="Common_DeleteTransactionRule",
        graphql_query=q.DELETE_RULE,
        variables={"id": args["rule_id"]},
    )
    payload = (resp or {}).get("deleteTransactionRule") or {}
    q.raise_payload_errors(payload.get("errors"), "Rule deletion")
    # Monarch's `deleted` flag isn't reliable (it can come back false on
    # success), so confirm by checking whether the rule still exists.
    rules = await list_transaction_rules(mm, {})
    still_there = any(r.get("id") == args["rule_id"] for r in (rules or {}).get("transactionRules") or [])
    return {"rule_id": args["rule_id"], "deleted": not still_there,
            "api_deleted_flag": payload.get("deleted")}


# --- Goals ------------------------------------------------------------------

GOAL_FIELDS = {
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
    "target_date": "targetDate",
    "planned_monthly_contribution": "plannedMonthlyContribution",
    "priority": "priority",
    "is_sinking_fund": "isSinkingFund",
}


@tool("get_goals", "List savings goals with balances, progress, and per-account allocations")
async def get_goals(mm, args):
    return await mm.gql_call(operation="Common_SavingsGoals",
                             graphql_query=q.GET_SAVINGS_GOALS, variables={})


@tool("create_goal", "Create a savings goal", GOAL_FIELDS, ["name", "type"], WRITE)
async def create_goal(mm, args):
    goal = pick(args, GOAL_FIELD_NAMES)
    if "target_date" in args:
        goal["targetDate"] = parse_date_arg(args, "target_date")
    return await mm.gql_call(operation="Common_CreateSavingsGoals",
                             graphql_query=q.CREATE_SAVINGS_GOALS,
                             variables={"input": {"goals": [goal]}})


@tool("update_goal", "Update a savings goal's settings",
      {"goal_id": string("Goal ID (see get_goals)"), **GOAL_FIELDS}, ["goal_id"], WRITE)
async def update_goal(mm, args):
    goal = {"id": args["goal_id"], **pick(args, GOAL_FIELD_NAMES)}
    if "target_date" in args:
        goal["targetDate"] = parse_date_arg(args, "target_date")
    resp = await mm.gql_call(operation="Common_UpdateSavingsGoal",
                             graphql_query=q.UPDATE_SAVINGS_GOAL, variables={"input": goal})
    payload = resp.get("updateSavingsGoal") or {}
    q.raise_payload_errors(payload.get("errors"), "Goal update")
    return payload.get("savingsGoal")


async def goal_id_mutation(mm, operation, document, field, goal_id, action):
    resp = await mm.gql_call(operation=operation, graphql_query=document,
                             variables={"input": {"id": goal_id}})
    payload = resp.get(field) or {}
    q.raise_payload_errors(payload.get("errors"), action)
    return payload


@tool("archive_goal", "Archive a savings goal (can be restored with unarchive_goal)",
      {"goal_id": string("Goal ID")}, ["goal_id"], WRITE)
async def archive_goal(mm, args):
    return await goal_id_mutation(mm, "Common_ArchiveSavingsGoal", q.ARCHIVE_SAVINGS_GOAL,
                                  "archiveSavingsGoal", args["goal_id"], "Goal archive")


@tool("unarchive_goal", "Restore an archived savings goal",
      {"goal_id": string("Goal ID")}, ["goal_id"], WRITE)
async def unarchive_goal(mm, args):
    return await goal_id_mutation(mm, "Common_UnarchiveSavingsGoal", q.UNARCHIVE_SAVINGS_GOAL,
                                  "unarchiveSavingsGoal", args["goal_id"], "Goal unarchive")


@tool("delete_goal", "Permanently delete a savings goal and its contribution history",
      {"goal_id": string("Goal ID")}, ["goal_id"], DESTRUCTIVE)
async def delete_goal(mm, args):
    return await goal_id_mutation(mm, "Common_DeleteSavingsGoal", q.DELETE_SAVINGS_GOAL,
                                  "deleteSavingsGoal", args["goal_id"], "Goal deletion")


GOAL_MONEY_FIELDS = {
    "goal_id": string("Goal ID (see get_goals)"),
    "account_id": string("Account the money is held in"),
    "amount": number("Amount (positive)"),
    "date": string("Date in YYYY-MM-DD format (default: today)"),
    "notes": string("Optional note"),
}


def goal_money_input(args: Dict[str, Any]) -> Dict[str, Any]:
    money = {"id": args["goal_id"], "accountId": args["account_id"], "amount": args["amount"]}
    if args.get("date"):
        money["date"] = parse_date_arg(args, "date")
    if args.get("notes"):
        money["notes"] = args["notes"]
    return money


@tool("contribute_to_goal", "Record a contribution from an account to a savings goal",
      GOAL_MONEY_FIELDS, ["goal_id", "account_id", "amount"], WRITE)
async def contribute_to_goal(mm, args):
    return await mm.gql_call(operation="Common_ContributeToSavingsGoal",
                             graphql_query=q.CONTRIBUTE_TO_SAVINGS_GOAL,
                             variables={"input": goal_money_input(args)})


@tool("withdraw_from_goal", "Record a withdrawal from a savings goal back to an account",
      GOAL_MONEY_FIELDS, ["goal_id", "account_id", "amount"], WRITE)
async def withdraw_from_goal(mm, args):
    return await mm.gql_call(operation="Common_WithdrawFromSavingsGoal",
                             graphql_query=q.WITHDRAW_FROM_SAVINGS_GOAL,
                             variables={"input": goal_money_input(args)})


@tool("set_goal_budget_amount", "Set the monthly budgeted contribution for a savings goal",
      {"goal_id": string("Goal ID"),
       "amount": number("Monthly amount"),
       "month": string("Any date in the month, YYYY-MM-DD (default: current month)"),
       "apply_to_future": boolean("Also apply to all later months", False),
       "account_id": string("Account the contribution comes from (optional)")},
      ["goal_id", "amount"], WRITE)
async def set_goal_budget_amount(mm, args):
    resp = await mm.gql_call(
        operation="Common_SetSavingsGoalBudgetAmount",
        graphql_query=q.SET_SAVINGS_GOAL_BUDGET_AMOUNT,
        variables={"input": {
            "savingsGoalId": args["goal_id"],
            "amount": args["amount"],
            "month": first_of_month(args, "month") or date.today().replace(day=1).isoformat(),
            "applyToFuture": args.get("apply_to_future", False),
            "accountId": args.get("account_id"),
        }},
    )
    payload = resp.get("setSavingsGoalBudgetAmount") or {}
    q.raise_payload_errors(payload.get("errors"), "Goal budget update")
    return payload


# --- Merchants --------------------------------------------------------------

@tool("get_merchants", "List or search merchants with transaction counts and default categories",
      {"search": string("Filter by name"),
       "limit": {"type": "integer", "description": "Maximum results", "default": 100},
       "offset": {"type": "integer", "description": "Results to skip", "default": 0},
       "order_by": string("Sort order", enum=q.MERCHANT_ORDERINGS, default="TRANSACTION_COUNT")})
async def get_merchants(mm, args):
    return await mm.gql_call(
        operation="Web_GetMerchantSettingsPage",
        graphql_query=q.GET_MERCHANTS,
        variables={
            "search": args.get("search") or None,
            "limit": args.get("limit", 100),
            "offset": args.get("offset", 0),
            "orderBy": args.get("order_by", "TRANSACTION_COUNT"),
        },
    )


@tool("get_merchant", "Get one merchant's details, including rule count and recurring settings",
      {"merchant_id": string("Merchant ID")}, ["merchant_id"])
async def get_merchant(mm, args):
    return await mm.gql_call(operation="Common_GetEditMerchant", graphql_query=q.GET_MERCHANT,
                             variables={"merchantId": args["merchant_id"]})


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
async def update_merchant(mm, args):
    merchant = {"merchantId": args["merchant_id"], **pick(args, {
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
    resp = await mm.gql_call(operation="Common_UpdateMerchant", graphql_query=q.UPDATE_MERCHANT,
                             variables={"input": merchant})
    payload = resp.get("updateMerchant") or {}
    q.raise_payload_errors(payload.get("errors"), "Merchant update")
    return payload.get("merchant")


@tool("delete_merchant",
      "Delete a merchant. With move_to_merchant_id, its transactions, rules, and recurring "
      "settings move to that merchant first (this is how merchants are merged).",
      {"merchant_id": string("Merchant to delete"),
       "move_to_merchant_id": string("Merchant to merge into")},
      ["merchant_id"], DESTRUCTIVE)
async def delete_merchant(mm, args):
    resp = await mm.gql_call(
        operation="Common_DeleteMerchant",
        graphql_query=q.DELETE_MERCHANT,
        variables={"merchantId": args["merchant_id"],
                   "moveToId": args.get("move_to_merchant_id")},
    )
    return {"merchant_id": args["merchant_id"],
            "merged_into": args.get("move_to_merchant_id"),
            "success": (resp.get("deleteMerchant") or {}).get("success")}


# --- Other ------------------------------------------------------------------

@tool("get_credit_history", "Get credit score history")
async def get_credit_history(mm, args):
    return await mm.get_credit_history()


@tool("get_subscription_details", "Get the Monarch Money subscription plan and status")
async def get_subscription_details(mm, args):
    return await mm.get_subscription_details()


# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> List[Tool]:
    """List all available tools."""
    return [t for t, _ in TOOLS.values()]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Execute a tool and return the results."""
    if not mm_client:
        return [TextContent(type="text", text="Error: MonarchMoney client not initialized")]
    if name not in TOOLS:
        return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    try:
        return result(await TOOLS[name][1](mm_client, arguments or {}))
    except Exception as e:
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]


async def serve():
    """Authenticate, then run the MCP server over stdio."""
    try:
        await initialize_client()
    except Exception as e:
        print(f"Failed to initialize MonarchMoney client: {e}", file=sys.stderr)
        return

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="monarch-money",
                server_version="1.0.0",
                capabilities=ServerCapabilities(tools={}),
            ),
        )


def main():
    """Console-script entry point."""
    asyncio.run(serve())


if __name__ == "__main__":
    main()
