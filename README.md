# Monarch Money MCP Server

An MCP (Model Context Protocol) server for Monarch Money: accounts, transactions, budgets, goals, merchants, rules, and more.

Forked from [colvint/monarch-money-mcp](https://github.com/colvint/monarch-money-mcp), which was archived when Monarch launched its official connector. This fork is maintained and covers the rest of the API.

## Features

- **Accounts**: balances, balance history, net worth over time, investment holdings, manual accounts, refreshes
- **Transactions**: search and filter, create, update, delete, splits, tags, attachments
- **Categories and budgets**: manage categories, set budget amounts, cash flow and summaries
- **Recurring**: upcoming bills, subscriptions, and income
- **Goals**: create and manage savings goals, contributions, and withdrawals
- **Merchants**: list, rename, set default categories, merge
- **Rules**: list, create, and delete transaction rules
- **Credit score** history

## Installation

1. Clone or download this MCP server
2. Install dependencies:
   ```bash
   cd /path/to/monarch-money-mcp
   uv sync
   ```

## Configuration

Add the server to your `.mcp.json` configuration file:

```json
{
  "mcpServers": {
    "monarch-money": {
      "command": "/path/to/uv",
      "args": [
        "--directory", 
        "/path/to/monarch-money-mcp",
        "run",
        "python",
        "server.py"
      ],
      "env": {
        "MONARCH_EMAIL": "your-email@example.com",
        "MONARCH_PASSWORD": "your-password",
        "MONARCH_MFA_SECRET": "your-mfa-secret-key"
      }
    }
  }
}
```

**Important Notes:**
- Replace `/path/to/uv` with the full path to your `uv` executable (find it with `which uv`)
- Replace `/path/to/monarch-money-mcp` with the absolute path to this server directory
- Use absolute paths, not relative paths

### Getting Your MFA Secret

1. Go to Monarch Money settings and enable 2FA
2. When shown the QR code, look for the "Can't scan?" or "Enter manually" option
3. Copy the secret key (it will be a string like `T5SPVJIBRNPNNINFSH5W7RFVF2XYADYX`)
4. Use this as your `MONARCH_MFA_SECRET`

## Available Tools

Read-only tools are marked as such to MCP clients; tools that delete or overwrite data are marked destructive.

| Area | Tools |
|---|---|
| Accounts | `get_accounts`, `get_account_type_options`, `get_institutions`, `get_account_holdings`, `get_account_history`, `get_recent_account_balances`, `get_net_worth_history`, `get_account_snapshots_by_type`, `create_manual_account`, `update_account`, `delete_account`, `upload_account_balance_history`, `refresh_accounts`, `get_refresh_status` |
| Transactions | `get_transactions`, `get_transaction_details`, `get_transactions_summary`, `create_transaction`, `update_transaction`, `delete_transaction`, `get_transaction_splits`, `update_transaction_splits`, `upload_transaction_attachment` |
| Tags | `get_transaction_tags`, `create_transaction_tag`, `set_transaction_tags` |
| Categories | `get_transaction_categories`, `get_transaction_category_groups`, `create_transaction_category`, `delete_transaction_categories` |
| Budgets and cash flow | `get_budgets`, `set_budget_amounts`, `get_cashflow`, `get_cashflow_summary`, `get_recurring_transactions` |
| Rules | `list_transaction_rules`, `create_transaction_rule`, `delete_transaction_rule` |
| Goals | `get_goals`, `create_goal`, `update_goal`, `archive_goal`, `unarchive_goal`, `delete_goal`, `contribute_to_goal`, `withdraw_from_goal`, `set_goal_budget_amount` |
| Merchants | `get_merchants`, `get_merchant`, `update_merchant`, `delete_merchant` (pass `move_to_merchant_id` to merge) |
| Other | `get_credit_history`, `get_subscription_details` |

Each tool's parameters are described in its input schema, which your MCP client shows.

Dates are `YYYY-MM-DD`. Where a tool takes `start_date` and `end_date`, give both or neither.

### Unofficial operations

Most tools go through the [monarchmoneycommunity](https://github.com/bradleyseanf/monarchmoneycommunity) library. Rules, goals, and merchants aren't covered by it, so `monarch_gql.py` calls the same GraphQL operations Monarch's web app uses. Monarch can change these without notice.

Goals use Monarch's current savings goals system. Households still on the legacy goals system aren't supported.

## Usage Examples

### Basic Account Information
```
Use the get_accounts tool to see all my accounts and their current balances.
```

### Transaction Analysis
```
Get all transactions from January 2024 using get_transactions with start_date "2024-01-01" and end_date "2024-01-31".
```

### Budget Tracking
```
Show me my current budget status using the get_budgets tool.
```

## Session Management

The server automatically manages authentication sessions:
- The session token is cached in `~/.monarchmoney_session` for faster subsequent logins
- Use `MONARCH_FORCE_LOGIN=true` in the env section to force a fresh login if needed

## Troubleshooting

### MFA Issues
- Ensure your MFA secret is correct and properly formatted
- Try setting `MONARCH_FORCE_LOGIN=true` in your `.mcp.json` env section
- Check that your system time is accurate (required for TOTP)

### Connection Issues
- Verify your email and password are correct in `.mcp.json`
- Check your internet connection
- Try running the server directly to see detailed error messages:
  ```bash
  uv run server.py
  ```

### Session Problems
- Run `./clear-sessions.sh` to clear cached sessions
- Set `MONARCH_FORCE_LOGIN=true` in your `.mcp.json` env section temporarily

## Credits

### MCP Server
- **Author**: Taurus Colvin ([@colvint](https://github.com/colvint))
- **Description**: MCP (Model Context Protocol) server wrapper for Monarch Money
- **Fork maintained by**: [@bhandeland](https://github.com/bhandeland)

### MonarchMoney Python Library
- **Original author**: hammem ([@hammem](https://github.com/hammem)) - [hammem/monarchmoney](https://github.com/hammem/monarchmoney)
- **Community fork used here**: bradleyseanf ([@bradleyseanf](https://github.com/bradleyseanf)) - [bradleyseanf/monarchmoneycommunity](https://github.com/bradleyseanf/monarchmoneycommunity)
- **License**: MIT License

This MCP server wraps the monarchmoney Python library to provide seamless integration with AI assistants through the Model Context Protocol.

## Security Notes

- Keep your credentials secure in your `.mcp.json` file
- The MFA secret provides full access to your account - treat it like a password
- `~/.monarchmoney_session` contains an authentication token - keep it secure
- Consider restricting access to your `.mcp.json` file since it contains sensitive credentials
