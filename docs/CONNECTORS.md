# CONNECTORS.md

> Specifications for connecting brokerage accounts. Honest read on what works
> and what doesn't. Read this before writing connector code.

---

## Schwab Trader API (PRIMARY — trading account)

**Status:** Schwab has a real, publicly available API after the TD Ameritrade acquisition. This is the only major retail broker with a full developer API.

### Capabilities

| Feature | Available | Notes |
|---|---|---|
| Account balances | ✅ | |
| Positions | ✅ | including cost basis |
| Transactions | ✅ | full history |
| Real-time quotes | ✅ | requires market data subscription |
| Historical quotes | ✅ | |
| Order placement | ✅ | **NOT USED until Phase 6** |
| Options chains | ✅ | |
| Account statements | ✅ | |

### Onboarding sequence

1. **Register at developer.schwab.com.** Personal Schwab account holders are eligible.
2. **Create an app.** Specify it's a personal-use app (not commercial). Callback URL: start with `https://localhost:8080/callback` for local dev, swap to production URL when deployed.
3. **Wait for approval.** This takes **1–4 weeks.** Apply early. There is no expedited path.
4. **Receive App Key and App Secret.** Store in environment variables — never in repo.

### OAuth flow

Schwab uses OAuth 2.0 with **30-minute access tokens** and **7-day refresh tokens**. Refresh tokens MUST be rotated every 7 days or the user re-authenticates manually. This is the most fragile part of the integration.

```
Step 1: User clicks "Connect Schwab" in dashboard.
Step 2: Redirect to Schwab authorize URL with app_key, redirect_uri, response_type=code, scope=readonly.
Step 3: User logs in on Schwab.com, approves access.
Step 4: Schwab redirects back to redirect_uri with ?code=AUTH_CODE.
Step 5: Backend POSTs to /oauth/token with code + app_key + app_secret.
Step 6: Receive access_token (30min) + refresh_token (7d).
Step 7: Encrypt and store in accounts table.
Step 8: Set up cron to refresh access_token every 25 minutes.
Step 9: Set up reminder/alert to refresh the refresh_token weekly (manual flow).
```

### Endpoints used

| Endpoint | Purpose | Frequency |
|---|---|---|
| `GET /accounts` | Account list | Once on connect |
| `GET /accounts/{id}` | Balances, positions | Every 15 min during market hours |
| `GET /accounts/{id}/transactions` | Trade history | Daily EOD |
| `GET /marketdata/{ticker}/quotes` | Real-time quotes | On demand |
| `GET /marketdata/{ticker}/pricehistory` | Backtest data backup | Not Phase 1 (using yfinance) |

### Rate limits

- 120 requests per minute per account
- 50,000 requests per day
- Practical implication: sync every 15 min is fine. Don't poll every second.

### File: `connectors/schwab.py` (Phase 5)

```python
class SchwabClient:
    def __init__(self, account_id: int): ...
    def authorize_url(self) -> str: ...
    def handle_callback(self, code: str) -> dict: ...
    def refresh_access_token(self) -> dict: ...
    def get_positions(self) -> list[dict]: ...
    def get_transactions(self, since: date) -> list[dict]: ...
    def get_quote(self, ticker: str) -> dict: ...
    # NO order placement methods until Phase 6
```

---

## Plaid (SECONDARY — Roth + Fidelity balance tracking)

**Status:** Read-only balance/holdings/transactions for accounts where Schwab API isn't appropriate (Roth, or Fidelity).

### Capabilities

| Feature | Available | Notes |
|---|---|---|
| Account balances | ✅ | |
| Holdings | ✅ | with delayed pricing |
| Transactions | ✅ | |
| Order placement | ❌ | not Plaid's product |
| Real-time quotes | ❌ | |

### Reuse from existing stack

Brian already has Plaid integration via Poof E Gone for Command Center. **Reuse those credentials and access tokens.** Do not create a separate Plaid app for The Board Market — same client_id, same secret, new Link flow per account.

### File: `connectors/plaid.py` (Phase 5)

```python
class PlaidClient:
    def __init__(self): ...
    def create_link_token(self, user_id: int) -> str: ...
    def exchange_public_token(self, public_token: str) -> str: ...
    def get_holdings(self, access_token: str) -> dict: ...
    def get_investment_transactions(self, access_token: str, since: date) -> list: ...
```

---

## Fidelity (TERTIARY — manual CSV import)

**Status:** Fidelity has no retail public API. Plaid covers it for balance/holdings sync. For trade history, manual CSV export is the fallback.

### Workflow

1. User logs into Fidelity.com → Activity & Orders → Download
2. Exports CSV
3. Uploads to dashboard via `/api/connectors/fidelity/upload`
4. `connectors/manual_csv.py` parses, dedupes against existing transactions, inserts new ones

### Expected CSV columns (as of Fidelity's current export format)

`Run Date, Action, Symbol, Description, Type, Quantity, Price, Commission, Fees, Accrued Interest, Amount, Cash Balance, Settlement Date`

Column names occasionally change. Validate columns on import, fail gracefully with clear error.

### File: `connectors/manual_csv.py` (Phase 5)

```python
def parse_fidelity_csv(file_path: str) -> list[dict]: ...
def import_to_ledger(account_id: int, transactions: list[dict]) -> dict: ...
```

---

## Hierarchy of preferred connection methods

For any given account, use in this order:

1. **Schwab Trader API** if it's a Schwab account and Brian has API approval
2. **Plaid** if API isn't available or for Roth (read-only is fine for retirement)
3. **Manual CSV import** as last resort

---

## Security requirements (non-negotiable)

- All tokens encrypted at rest using `cryptography.fernet`
- Master key in environment variable, never in repo
- No tokens in logs, ever (use logging filters)
- HTTPS only for callback URLs in production
- OAuth state parameter required (CSRF protection)
- Token refresh failures alert Brian via configured notification channel
- Sync errors logged but never expose token values

---

## Failure modes and recovery

| Failure | Recovery |
|---|---|
| Schwab access_token expired | Auto-refresh from refresh_token |
| Schwab refresh_token expired (7d) | Show "Reconnect Schwab" banner in UI |
| Plaid item login_required | Show "Reauthenticate {bank}" banner |
| Manual CSV format changed | Fail import, alert Brian with parser error |
| Network failure during sync | Retry 3x with backoff, then alert |
| Position sync conflict (manual vs API) | API wins, log discrepancy |
