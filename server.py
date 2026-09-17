#!/usr/bin/env python3
"""MonarchMoney MCP Server - Provides access to Monarch Money financial data via MCP protocol."""

import os
import asyncio
import json
from typing import Any, Dict, Optional, List
from datetime import datetime, date
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.models import InitializationOptions
from mcp.types import ServerCapabilities
from mcp.types import Tool, TextContent
from monarchmoney import MonarchMoney
from gql import gql  # installed with monarchmoney


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


def require_date_pair(start: Optional[str], end: Optional[str]) -> None:
    """The Monarch API rejects a start_date without an end_date (and vice versa)."""
    if bool(start) != bool(end):
        raise ValueError("Provide both start_date and end_date, or neither.")


# ---------------------------------------------------------------------------
# Transaction rules. The monarchmoney library doesn't wrap these, so we call
# Monarch's GraphQL operations directly (same operations the web app uses).
# Unofficial: Monarch can change these without notice.
# ---------------------------------------------------------------------------
PAYLOAD_ERRORS = """
    fragment PayloadErrorFields on PayloadError {
        fieldErrors { field messages __typename }
        message
        code
        __typename
    }
"""

GET_RULES = gql("""
    query GetTransactionRules {
        transactionRules {
            id
            order
            merchantCriteriaUseOriginalStatement
            merchantCriteria { operator value __typename }
            amountCriteria {
                operator isExpense value
                valueRange { lower upper __typename }
                __typename
            }
            categoryIds
            accountIds
            categories { id name __typename }
            accounts { id displayName __typename }
            setMerchantAction { id name __typename }
            setCategoryAction { id name __typename }
            addTagsAction { id name __typename }
            setHideFromReportsAction
            reviewStatusAction
            recentApplicationCount
            lastAppliedAt
            __typename
        }
    }
""")

CREATE_RULE = gql("""
    mutation Common_CreateTransactionRuleMutationV2($input: CreateTransactionRuleInput!) {
        createTransactionRuleV2(input: $input) {
            errors { ...PayloadErrorFields __typename }
            transactionRule { id __typename }
            __typename
        }
    }
""" + PAYLOAD_ERRORS)

DELETE_RULE = gql("""
    mutation Common_DeleteTransactionRule($id: ID!) {
        deleteTransactionRule(id: $id) {
            deleted
            errors { ...PayloadErrorFields __typename }
            __typename
        }
    }
""" + PAYLOAD_ERRORS)

AMOUNT_OPERATORS = {"eq", "gt", "lt", "between"}
TEXT_OPERATORS = {"eq", "contains"}


def raise_payload_errors(errors: Optional[Dict[str, Any]], action: str) -> None:
    """Monarch returns an `errors` object on success too, with empty fields."""
    if not errors:
        return
    if errors.get("message"):
        raise RuntimeError(f"{action} failed: {errors['message']}")
    field_errors = errors.get("fieldErrors") or []
    if field_errors:
        detail = "; ".join(f"{fe['field']}: {', '.join(fe['messages'])}" for fe in field_errors)
        raise RuntimeError(f"{action} failed: {detail}")


def build_rule_input(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Translate tool arguments into Monarch's CreateTransactionRuleInput."""
    criteria = []
    if arguments.get("merchant_contains"):
        criteria.append({"operator": "contains", "value": arguments["merchant_contains"]})
    if arguments.get("merchant_equals"):
        criteria.append({"operator": "eq", "value": arguments["merchant_equals"]})

    amount = arguments.get("amount")
    amount_criteria = None
    if amount:
        op = amount.get("operator")
        if op not in AMOUNT_OPERATORS:
            raise ValueError(f"amount.operator must be one of {sorted(AMOUNT_OPERATORS)}")
        amount_criteria = {
            "operator": op,
            "isExpense": amount.get("is_expense", True),
            "value": None,
            "valueRange": None,
        }
        if op == "between":
            if amount.get("lower") is None or amount.get("upper") is None:
                raise ValueError("amount.lower and amount.upper are required for 'between'")
            amount_criteria["valueRange"] = {"lower": amount["lower"], "upper": amount["upper"]}
        else:
            if amount.get("value") is None:
                raise ValueError("amount.value is required unless operator is 'between'")
            amount_criteria["value"] = amount["value"]

    if not criteria and not amount_criteria and not arguments.get("account_ids") \
            and not arguments.get("match_category_ids"):
        raise ValueError("A rule needs at least one condition (merchant, amount, account, or category)")
    if not arguments.get("set_category_id") and not arguments.get("set_merchant_name"):
        raise ValueError("A rule needs an action: set_category_id and/or set_merchant_name")

    return {
        "merchantCriteria": criteria or None,
        "merchantCriteriaUseOriginalStatement": bool(arguments.get("use_original_statement", False)),
        "amountCriteria": amount_criteria,
        "accountIds": arguments.get("account_ids") or None,
        "categoryIds": arguments.get("match_category_ids") or None,
        "setCategoryAction": arguments.get("set_category_id") or None,
        "setMerchantAction": arguments.get("set_merchant_name") or None,
        "addTagsAction": None,
        "splitTransactionsAction": None,
        "applyToExistingTransactions": bool(arguments.get("apply_to_existing", False)),
    }


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
            print("Loaded existing session successfully")
            return
        except Exception:
            print("Existing session invalid, logging in fresh")
    
    # Login with credentials
    if mfa_secret:
        await mm_client.login(email, password, mfa_secret_key=mfa_secret)
    else:
        await mm_client.login(email, password)
    
    # Save session for future use
    mm_client.save_session(str(session_file))
    print("Logged in and saved session")


# Tool definitions
@server.list_tools()
async def list_tools() -> List[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="get_accounts",
            description="Retrieve all linked financial accounts",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_transactions",
            description="Fetch transactions with optional filtering",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of transactions to return",
                        "default": 100
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Number of transactions to skip",
                        "default": 0
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format"
                    },
                    "account_id": {
                        "type": "string",
                        "description": "Filter by specific account ID"
                    },
                    "category_id": {
                        "type": "string",
                        "description": "Filter by specific category ID"
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_budgets",
            description="Retrieve budget information",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format"
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_cashflow",
            description="Analyze cashflow data",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in YYYY-MM-DD format"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in YYYY-MM-DD format"
                    }
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="get_transaction_categories",
            description="List all transaction categories",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        ),
        Tool(
            name="create_transaction",
            description="Create a new transaction",
            inputSchema={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "number",
                        "description": "Transaction amount (negative for expenses)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Merchant name / description shown for the transaction"
                    },
                    "category_id": {
                        "type": "string",
                        "description": "Category ID for the transaction"
                    },
                    "account_id": {
                        "type": "string",
                        "description": "Account ID for the transaction"
                    },
                    "date": {
                        "type": "string",
                        "description": "Transaction date in YYYY-MM-DD format"
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes for the transaction"
                    }
                },
                "required": ["amount", "description", "account_id", "date", "category_id"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="update_transaction",
            description="Update an existing transaction",
            inputSchema={
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "ID of the transaction to update"
                    },
                    "amount": {
                        "type": "number",
                        "description": "New transaction amount"
                    },
                    "description": {
                        "type": "string",
                        "description": "New merchant name / description"
                    },
                    "category_id": {
                        "type": "string",
                        "description": "New category ID"
                    },
                    "date": {
                        "type": "string",
                        "description": "New transaction date in YYYY-MM-DD format"
                    },
                    "notes": {
                        "type": "string",
                        "description": "New notes for the transaction"
                    }
                },
                "required": ["transaction_id"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="set_budget_amounts",
            description=(
                "Set monthly budget amounts for one or more categories or category groups. "
                "Each item needs an amount and exactly one of category_id or category_group_id. "
                "An amount of 0 clears that budget. Items are applied in order; results are "
                "reported per item."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 100,
                        "items": {
                            "type": "object",
                            "properties": {
                                "category_id": {"type": "string"},
                                "category_group_id": {"type": "string"},
                                "amount": {"type": "number"}
                            },
                            "required": ["amount"],
                            "additionalProperties": False
                        }
                    },
                    "start_date": {
                        "type": "string",
                        "description": "First day of the month to set, YYYY-MM-DD (default: current month)"
                    },
                    "apply_to_future": {
                        "type": "boolean",
                        "description": "Also apply the amounts to all later months",
                        "default": False
                    }
                },
                "required": ["items"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="list_transaction_rules",
            description="List the household's transaction rules (conditions and actions) in priority order",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False}
        ),
        Tool(
            name="create_transaction_rule",
            description=(
                "Create a transaction rule. Conditions (combine as needed): merchant_contains / "
                "merchant_equals, amount, account_ids, match_category_ids. Actions: set_category_id "
                "and/or set_merchant_name. apply_to_existing defaults to false; setting it true "
                "rewrites matching past transactions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "merchant_contains": {"type": "string", "description": "Merchant name contains this text"},
                    "merchant_equals": {"type": "string", "description": "Merchant name equals this text"},
                    "use_original_statement": {
                        "type": "boolean",
                        "description": "Match the raw bank statement text instead of the merchant name",
                        "default": False
                    },
                    "amount": {
                        "type": "object",
                        "description": "Amount condition, e.g. {operator: 'gt', value: 80}",
                        "properties": {
                            "operator": {"type": "string", "enum": ["eq", "gt", "lt", "between"]},
                            "value": {"type": "number"},
                            "lower": {"type": "number"},
                            "upper": {"type": "number"},
                            "is_expense": {"type": "boolean", "default": True}
                        },
                        "required": ["operator"],
                        "additionalProperties": False
                    },
                    "account_ids": {"type": "array", "items": {"type": "string"}},
                    "match_category_ids": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Only match transactions currently in these categories"
                    },
                    "set_category_id": {"type": "string", "description": "Category to assign"},
                    "set_merchant_name": {"type": "string", "description": "Merchant name to assign"},
                    "apply_to_existing": {"type": "boolean", "default": False}
                },
                "additionalProperties": False
            }
        ),
        Tool(
            name="delete_transaction_rule",
            description="Delete a transaction rule by id (use list_transaction_rules to find it)",
            inputSchema={
                "type": "object",
                "properties": {"rule_id": {"type": "string"}},
                "required": ["rule_id"],
                "additionalProperties": False
            }
        ),
        Tool(
            name="refresh_accounts",
            description="Request a refresh of all account data from financial institutions",
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Execute a tool and return the results."""
    if not mm_client:
        return [TextContent(type="text", text="Error: MonarchMoney client not initialized")]
    
    try:
        if name == "get_accounts":
            accounts = await mm_client.get_accounts()
            # Convert date objects to strings before serialization
            accounts = convert_dates_to_strings(accounts)
            return [TextContent(type="text", text=json.dumps(accounts, indent=2))]
        
        elif name == "get_transactions":
            # Build filter parameters
            filters = {}
            start = parse_date_arg(arguments, "start_date")
            end = parse_date_arg(arguments, "end_date")
            require_date_pair(start, end)
            if start:
                filters["start_date"] = start
                filters["end_date"] = end
            # The library takes lists of IDs (account_ids / category_ids)
            if arguments.get("account_id"):
                filters["account_ids"] = [arguments["account_id"]]
            if arguments.get("category_id"):
                filters["category_ids"] = [arguments["category_id"]]
            
            transactions = await mm_client.get_transactions(
                limit=arguments.get("limit", 100),
                offset=arguments.get("offset", 0),
                **filters
            )
            # Convert date objects to strings before serialization
            transactions = convert_dates_to_strings(transactions)
            return [TextContent(type="text", text=json.dumps(transactions, indent=2))]
        
        elif name == "get_budgets":
            kwargs = {}
            start = parse_date_arg(arguments, "start_date")
            end = parse_date_arg(arguments, "end_date")
            require_date_pair(start, end)
            if start:
                kwargs["start_date"] = start
                kwargs["end_date"] = end
            
            try:
                budgets = await mm_client.get_budgets(**kwargs)
                # Convert date objects to strings before serialization
                budgets = convert_dates_to_strings(budgets)
                return [TextContent(type="text", text=json.dumps(budgets, indent=2))]
            except Exception as e:
                # Handle the case where no budgets exist
                if "Something went wrong while processing: None" in str(e):
                    return [TextContent(type="text", text=json.dumps({
                        "budgets": [],
                        "message": "No budgets configured in your Monarch Money account"
                    }, indent=2))]
                else:
                    # Re-raise other errors
                    raise
        
        elif name == "get_cashflow":
            kwargs = {}
            start = parse_date_arg(arguments, "start_date")
            end = parse_date_arg(arguments, "end_date")
            require_date_pair(start, end)
            if start:
                kwargs["start_date"] = start
                kwargs["end_date"] = end
            
            cashflow = await mm_client.get_cashflow(**kwargs)
            # Convert date objects to strings before serialization
            cashflow = convert_dates_to_strings(cashflow)
            return [TextContent(type="text", text=json.dumps(cashflow, indent=2))]
        
        elif name == "get_transaction_categories":
            categories = await mm_client.get_transaction_categories()
            # Convert date objects to strings before serialization
            categories = convert_dates_to_strings(categories)
            return [TextContent(type="text", text=json.dumps(categories, indent=2))]
        
        elif name == "create_transaction":
            # Convert date string to date object
            result = await mm_client.create_transaction(
                date=parse_date_arg(arguments, "date"),
                account_id=arguments["account_id"],
                amount=arguments["amount"],
                merchant_name=arguments["description"],
                category_id=arguments["category_id"],
                notes=arguments.get("notes") or "",
            )
            # Convert date objects to strings before serialization
            result = convert_dates_to_strings(result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "update_transaction":
            # Build update parameters
            updates = {"transaction_id": arguments["transaction_id"]}
            if "amount" in arguments:
                updates["amount"] = arguments["amount"]
            if "description" in arguments:
                updates["merchant_name"] = arguments["description"]
            if "category_id" in arguments:
                updates["category_id"] = arguments["category_id"]
            if "date" in arguments:
                updates["date"] = parse_date_arg(arguments, "date")
            if "notes" in arguments:
                updates["notes"] = arguments["notes"]
            
            result = await mm_client.update_transaction(**updates)
            # Convert date objects to strings before serialization
            result = convert_dates_to_strings(result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        elif name == "set_budget_amounts":
            start = parse_date_arg(arguments, "start_date")
            if start:
                start = start[:8] + "01"  # budgets are keyed by the first of the month
            apply_to_future = bool(arguments.get("apply_to_future", False))

            results = []
            for item in arguments["items"]:
                category_id = item.get("category_id") or None
                group_id = item.get("category_group_id") or None
                entry = {"category_id": category_id, "category_group_id": group_id,
                         "amount": item["amount"]}
                if (category_id is None) == (group_id is None):
                    entry.update(ok=False, error="Provide exactly one of category_id or category_group_id")
                    results.append(entry)
                    continue
                try:
                    resp = await mm_client.set_budget_amount(
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

            summary = {
                "start_date": start or "current month",
                "apply_to_future": apply_to_future,
                "succeeded": sum(1 for r in results if r["ok"]),
                "failed": sum(1 for r in results if not r["ok"]),
                "results": results,
            }
            return [TextContent(type="text", text=json.dumps(convert_dates_to_strings(summary), indent=2))]

        elif name == "list_transaction_rules":
            result = await mm_client.gql_call(
                operation="GetTransactionRules", graphql_query=GET_RULES, variables={}
            )
            return [TextContent(type="text", text=json.dumps(convert_dates_to_strings(result), indent=2))]

        elif name == "create_transaction_rule":
            rule_input = build_rule_input(arguments)
            result = await mm_client.gql_call(
                operation="Common_CreateTransactionRuleMutationV2",
                graphql_query=CREATE_RULE,
                variables={"input": rule_input},
            )
            payload = (result or {}).get("createTransactionRuleV2") or {}
            raise_payload_errors(payload.get("errors"), "Rule creation")
            return [TextContent(type="text", text=json.dumps({
                "created": payload.get("transactionRule"),
                "input": rule_input,
            }, indent=2))]

        elif name == "delete_transaction_rule":
            result = await mm_client.gql_call(
                operation="Common_DeleteTransactionRule",
                graphql_query=DELETE_RULE,
                variables={"id": arguments["rule_id"]},
            )
            payload = (result or {}).get("deleteTransactionRule") or {}
            raise_payload_errors(payload.get("errors"), "Rule deletion")
            # Monarch's `deleted` flag isn't reliable (it can come back false on
            # success), so confirm by checking whether the rule still exists.
            rules = await mm_client.gql_call(
                operation="GetTransactionRules", graphql_query=GET_RULES, variables={}
            )
            still_there = any(
                r.get("id") == arguments["rule_id"]
                for r in (rules or {}).get("transactionRules") or []
            )
            return [TextContent(type="text", text=json.dumps({
                "rule_id": arguments["rule_id"],
                "deleted": not still_there,
                "api_deleted_flag": payload.get("deleted"),
            }, indent=2))]

        elif name == "refresh_accounts":
            result = await mm_client.request_accounts_refresh()
            # Convert date objects to strings before serialization
            result = convert_dates_to_strings(result)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        else:
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]
    
    except Exception as e:
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]


async def main():
    """Main entry point for the server."""
    # Initialize the MonarchMoney client
    try:
        await initialize_client()
    except Exception as e:
        print(f"Failed to initialize MonarchMoney client: {e}")
        return
    
    # Run the MCP server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream,
            InitializationOptions(
                server_name="monarch-money",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools={}
                )
            )
        )


if __name__ == "__main__":
    asyncio.run(main())