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

## Claude Desktop extension

The quickest way to use this with Claude Desktop on macOS, Windows, or Linux:

1. Download `monarch-money-mcp-<version>.mcpb` from the [latest release](https://github.com/bhandeland/monarch-money-mcp/releases/latest).
2. Double-click it (or drag it onto Claude Desktop's Settings > Extensions page) and choose Install. Claude Desktop sets up Python and the dependencies itself.
3. The extension's settings are all optional:
   - **Leave them blank** to use a saved login token. Run `login` once in a terminal first (see [Log in once](#1-log-in-once); with [uv](https://docs.astral.sh/uv/) installed you can skip cloning and run `uvx --from git+https://github.com/bhandeland/monarch-money-mcp monarch-money-mcp login`).
   - **Fill in your email and password** (plus your MFA secret if you use 2FA) to have the extension log in by itself and log in again when the token expires. Claude Desktop keeps these in your system keychain.
   - **Browser cookies** is for when Monarch blocks password login with a CAPTCHA. Paste the Cookie header described in [If Monarch asks for a CAPTCHA](#if-monarch-asks-for-a-captcha).
   - **Session file** only matters if you saved the token somewhere other than the default.

To build the extension yourself: `npx @anthropic-ai/mcpb pack`.

## Installation

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It runs the server and installs its dependencies, including Python if you don't have it.

- **macOS / Linux**: `curl -LsSf https://astral.sh/uv/install.sh | sh` (or `brew install uv`)
- **Windows** (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"` (or `winget install --id=astral-sh.uv -e`)

Open a new terminal afterwards so `uv` is on your PATH. There's nothing to clone - the commands below fetch the server from GitHub.

### 1. Log in once

```bash
uvx --from git+https://github.com/bhandeland/monarch-money-mcp monarch-money-mcp login
```

This asks for your email, password, and MFA code, then saves only the session token to `~/.config/monarch-money-mcp/session.json` (`%USERPROFILE%\.config\monarch-money-mcp\session.json` on Windows), readable only by you. Your password and MFA secret aren't stored anywhere.

If the token stops working, the server's tools return an error asking you to run `login` again.

#### If Monarch asks for a CAPTCHA

Monarch sometimes blocks password logins from scripts with a CAPTCHA. When that happens, `login` says so and asks for your browser's cookies instead. You can also go straight there with `login --cookies`:

1. Log in at [app.monarch.com](https://app.monarch.com) in your browser.
2. Open the developer tools (F12, or Cmd+Option+I on a Mac) and go to the Network tab.
3. Reload the page, click any request to `api.monarch.com` (for example `graphql`), and find `Cookie` under Request Headers.
4. Copy the whole value and paste it at the prompt. It's hidden as you paste.

Only the `session_id` and `csrftoken` cookies are saved, to the same session file. A cookie session can't renew itself, so when it expires (for example after you log out in the browser), run `login --cookies` again with a fresh header.

### 2. Add the server to your client

**Claude Desktop:**

```bash
uvx --from git+https://github.com/bhandeland/monarch-money-mcp monarch-money-mcp install --client claude-desktop
```

This adds a `monarch-money` entry to Claude Desktop's config and leaves everything else in it alone. Restart Claude Desktop afterwards. The config file is at:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

**Claude Code:**

```bash
uvx --from git+https://github.com/bhandeland/monarch-money-mcp monarch-money-mcp install --client claude-code
```

This runs `claude mcp add --scope user`, so the server is available in every project. If `claude` isn't on your PATH, it prints the command to run instead.

**Anything else** (Cursor, a project's `.mcp.json`, and so on):

```bash
uvx --from git+https://github.com/bhandeland/monarch-money-mcp monarch-money-mcp install --print
```

This prints the `mcpServers` JSON to paste into the client's config. It looks like this:

```json
{
  "mcpServers": {
    "monarch-money": {
      "command": "/full/path/to/uvx",
      "args": ["--from", "git+https://github.com/bhandeland/monarch-money-mcp", "monarch-money-mcp"]
    }
  }
}
```

The config uses the full path to `uvx` because desktop apps don't see your shell's PATH. To write it by hand, find that path with `which uvx` (macOS / Linux) or `where.exe uvx` (Windows).

`install` never writes your email, password, or MFA secret into a config file.

### Running from a clone

If you cloned this repository (to develop on it, or to pin a version), run the same commands with `uv run` from the clone:

```bash
cd /path/to/monarch-money-mcp
uv sync
uv run monarch-money-mcp login
uv run monarch-money-mcp install --client claude-desktop
```

Run from a clone, `install` points the client at that clone (`uv --directory /path/to/monarch-money-mcp run monarch-money-mcp`) instead of GitHub.

### Environment variables (all optional)

| Variable | Purpose |
|---|---|
| `MONARCH_TOKEN` | Use this token instead of the saved session |
| `MONARCH_COOKIES` | Use this browser Cookie header (see [If Monarch asks for a CAPTCHA](#if-monarch-asks-for-a-captcha)) instead of the saved session |
| `MONARCH_SESSION_FILE` | Where `login` saves the token and the server reads it |
| `MONARCH_EMAIL`, `MONARCH_PASSWORD`, `MONARCH_MFA_SECRET` | Log in automatically, and log in again when the token expires. This keeps your password and MFA secret in the MCP config, so only use it if unattended re-login matters to you. |
| `MONARCH_FORCE_LOGIN` | With the credentials above, ignore the saved session and log in fresh |

The server tries `MONARCH_TOKEN`, then `MONARCH_COOKIES`, then the saved session, then the credentials.

To get an MFA secret for `MONARCH_MFA_SECRET`, turn on 2FA in Monarch's settings and choose "Can't scan?" / "Enter manually" when the QR code is shown. The secret looks like `T5SPVJIBRNPNNINFSH5W7RFVF2XYADYX`.

## Available Tools

Read-only tools are marked as such to MCP clients; tools that delete or overwrite data are marked destructive.

| Area | Tools |
|---|---|
| Accounts | `get_accounts`, `get_account_type_options`, `get_institutions`, `get_account_holdings`, `get_account_history`, `get_recent_account_balances`, `get_net_worth_history`, `get_account_snapshots_by_type`, `create_manual_account`, `update_account`, `delete_account`, `upload_account_balance_history`, `refresh_accounts`, `get_refresh_status` |
| Transactions | `get_transactions`, `get_transaction_details`, `get_transactions_summary`, `create_transaction`, `update_transaction`, `delete_transaction`, `bulk_update_transactions`, `bulk_delete_transactions`, `move_transactions`, `get_transaction_splits`, `update_transaction_splits`, `upload_transaction_attachment` |
| Tags | `get_transaction_tags`, `create_transaction_tag`, `update_transaction_tag`, `delete_transaction_tag`, `set_transaction_tags` |
| Categories | `get_transaction_categories`, `get_transaction_category_groups`, `create_transaction_category`, `update_transaction_category`, `delete_transaction_categories`, `create_category_group`, `update_category_group`, `delete_category_group` |
| Budgets and cash flow | `get_budgets`, `set_budget_amounts`, `get_cashflow`, `get_cashflow_summary` |
| Recurring | `get_recurring_transactions`, `get_recurring_streams`, `get_recurring_remaining_due`, `mark_stream_not_recurring` |
| Rules | `list_transaction_rules`, `preview_transaction_rule`, `create_transaction_rule`, `update_transaction_rule`, `set_transaction_rule_order`, `delete_transaction_rule` |
| Goals | `get_goals`, `create_goal`, `update_goal`, `archive_goal`, `unarchive_goal`, `delete_goal`, `contribute_to_goal`, `withdraw_from_goal`, `set_goal_budget_amount` |
| Merchants | `get_merchants`, `get_merchant`, `update_merchant`, `delete_merchant` (merges into `move_to_merchant_id`; Monarch rarely allows a plain delete) |
| Forecasting and paychecks | `get_cash_flow_projection`, `get_forecast_scenarios`, `get_forecast_scenario`, `create_forecast_scenario`, `update_forecast_scenario`, `duplicate_forecast_scenario`, `delete_forecast_scenario`, `get_debt_accounts`, `get_debt_paydown_plan`, `get_debt_paydown_budget_amounts`, `set_debt_paydown_budget_amount`, `get_paychecks`, `get_paycheck`, `get_paychecks_summary`, `get_paycheck_employers`, `create_paycheck`, `update_paycheck`, `delete_paycheck`, `create_paycheck_employer`, `update_paycheck_employer`, `delete_paycheck_employer` |
| Other | `get_household_members`, `search_entities`, `get_credit_history`, `get_subscription_details` |

Each tool's parameters are described in its input schema, which your MCP client shows.

Dates are `YYYY-MM-DD`. Where a tool takes `start_date` and `end_date`, give both or neither.

### Unofficial operations

Some tools go through the [monarchmoneycommunity](https://github.com/bradleyseanf/monarchmoneycommunity) library. The rest (rules, goals, merchants, bulk edits, category groups, and more) call the same GraphQL operations Monarch's web app uses, from `monarch_gql.py`. Monarch can change these without notice.

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

## Troubleshooting

The commands below use the short form `monarch-money-mcp <command>`. Put `uvx --from git+https://github.com/bhandeland/monarch-money-mcp` in front of it, or `uv run` from a clone.

- **"Not logged in" or "session expired"**: run `monarch-money-mcp login`, then restart your client.
- **"Monarch Money asked for a CAPTCHA"**: automatic login with `MONARCH_EMAIL`/`MONARCH_PASSWORD` was blocked. Run `monarch-money-mcp login --cookies` (see [If Monarch asks for a CAPTCHA](#if-monarch-asks-for-a-captcha)), then restart your client.
- **Clear the saved session**: `monarch-money-mcp logout`.
- **MFA problems with `MONARCH_MFA_SECRET`**: check the secret, and that your system clock is accurate (TOTP codes depend on it).
- **See startup errors**: run `monarch-money-mcp` on its own. Errors go to stderr. Claude Desktop also logs them, in `~/Library/Logs/Claude/` on macOS and `%APPDATA%\Claude\logs\` on Windows.
- **Client can't find `uv` or `uvx`**: run `install` again after installing uv, or put the full path in the config yourself.

Earlier versions saved the token as a pickle file in `~/.monarchmoney_session` (and the library in `.mm/`). Those are no longer read; `login` deletes them.

## Development

```bash
uv sync
./check.sh          # pyrefly (strict) + pytest, prints only problems and a summary
./check.sh -k goals # extra arguments go to pytest
```

The tests mock the Monarch client, so they never touch a real account. Every tool gets called through the MCP dispatcher, and a full test run fails if any registered tool has no test.

Monarch's web app ships a copy of its GraphQL schema. `scripts/fetch_schema.py` extracts it to `.schema/`, and the tests validate every operation the server sends against it, which catches wrong field names and argument types without calling the API. `check.sh` fetches the schema if it's missing. CI runs `./check.sh` on every push and pull request.

`manifest.json` describes the Claude Desktop extension. After adding or changing a tool, or bumping the version, run `uv run python scripts/update_manifest.py`; a test fails until the manifest matches. Pushing a `v*` tag that matches the version in `pyproject.toml` builds the `.mcpb` and attaches it to a GitHub release.

## License

The changes made in this fork are released under the [MIT License](LICENSE). The original upstream repository, [colvint/monarch-money-mcp](https://github.com/colvint/monarch-money-mcp), has no license, so the MIT License can't cover the code that came from it.

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

- Prefer `login` over putting your password in `.mcp.json`
- Browser cookies give the same access as being logged in to Monarch - treat them like a password
- The MFA secret provides full access to your account - treat it like a password
- The saved session file contains an authentication token or session cookies - it's created readable only by you; `logout` deletes it
- If you do put credentials in `.mcp.json`, restrict access to that file
