# SCHEMA.md

> SQLite for Phase 3. Postgres migration is Phase 7+ if multi-user ever happens.
> All tables include `created_at` and `updated_at` timestamps (omitted below for brevity).

---

## Tables

### `users`
Single-user for now, designed for multi-user later.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| email | TEXT UNIQUE NOT NULL | |
| password_hash | TEXT NOT NULL | bcrypt |
| display_name | TEXT | "Brian" |
| created_at | TIMESTAMP | |
| last_login | TIMESTAMP | |

### `accounts`
Connected broker/financial accounts.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER FK users.id | |
| provider | TEXT NOT NULL | 'schwab_api' / 'plaid' / 'manual_csv' |
| account_type | TEXT NOT NULL | 'trading' / 'roth' / 'other' |
| nickname | TEXT | "Schwab Roth", "Trading Account" |
| oauth_access_token | TEXT | encrypted at rest (Phase 5+) |
| oauth_refresh_token | TEXT | encrypted at rest |
| oauth_expires_at | TIMESTAMP | |
| plaid_access_token | TEXT | encrypted, for Plaid accounts |
| last_synced_at | TIMESTAMP | |
| is_active | BOOLEAN | |

### `positions`
Real positions synced from broker. Distinct from `plays` (which are signal-driven trades).

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| account_id | INTEGER FK accounts.id | |
| ticker | TEXT NOT NULL | |
| quantity | REAL NOT NULL | |
| avg_cost | REAL NOT NULL | |
| market_value | REAL | last sync |
| unrealized_pnl | REAL | |
| as_of | TIMESTAMP NOT NULL | |

### `plays`
Trades the system generates (paper or live). The core ledger.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER FK users.id | |
| ticker | TEXT NOT NULL | |
| tier | TEXT NOT NULL | 'LOCK' / 'LIVE' / 'STACK' |
| mode | TEXT NOT NULL | 'paper' / 'live' |
| setup_score | REAL NOT NULL | |
| factors_json | TEXT | full factor breakdown stored as JSON |
| flags_json | TEXT | downgrades / notes JSON array |
| catalyst | TEXT | description if known |
| entry_date | DATE NOT NULL | |
| entry_price | REAL NOT NULL | |
| stop_price | REAL NOT NULL | |
| target_price | REAL NOT NULL | |
| size_dollars | REAL NOT NULL | |
| size_shares | REAL | computed |
| horizon | TEXT | 'day_swing' / 'swing' / 'position' |
| exit_date | DATE | NULL if open |
| exit_price | REAL | NULL if open |
| exit_reason | TEXT | 'STOP' / 'TARGET' / 'TIME' / 'GAP_STOP' / 'MANUAL' / NULL if open |
| held_days | INTEGER | computed on close |
| pct_return | REAL | computed on close |
| r_multiple | REAL | computed on close |
| dollar_pnl | REAL | computed on close |
| status | TEXT NOT NULL | 'open' / 'closed' / 'cancelled' |

### `daily_boards`
Daily scoring snapshots — every day's board for historical reference.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| board_date | DATE NOT NULL | indexed |
| frozen_at | TIMESTAMP | NULL until 9:30 AM ET that day |
| board_json | TEXT NOT NULL | full ranked universe with scores |
| regime | TEXT | 'BULL' / 'BEAR' / 'SIDEWAYS' |
| vix_close | REAL | |
| tnx_close | REAL | |

### `equity_curve`
Daily bankroll snapshots for performance tracking.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| user_id | INTEGER FK users.id | |
| snapshot_date | DATE NOT NULL | |
| bankroll | REAL NOT NULL | trading capital only |
| open_pnl | REAL | unrealized on open plays |
| realized_pnl_ytd | REAL | |
| play_count_ytd | INTEGER | |
| win_count_ytd | INTEGER | |

### `preferences`
Per-user customizations.

| Column | Type | Notes |
|---|---|---|
| user_id | INTEGER FK users.id PK | |
| watchlist_additions_json | TEXT | extra tickers beyond universe |
| universe_exclusions_json | TEXT | tickers to drop from universe |
| risk_overrides_json | TEXT | custom position sizing |
| notification_email | TEXT | for ledger updates |
| notification_slack_webhook | TEXT | optional |

---

## Indexes

```sql
CREATE INDEX idx_plays_user_status ON plays(user_id, status);
CREATE INDEX idx_plays_entry_date ON plays(entry_date);
CREATE INDEX idx_plays_ticker ON plays(ticker);
CREATE INDEX idx_positions_account ON positions(account_id);
CREATE INDEX idx_daily_boards_date ON daily_boards(board_date DESC);
CREATE INDEX idx_equity_curve_user_date ON equity_curve(user_id, snapshot_date DESC);
```

---

## Computed views (Phase 3+)

### `performance_rolling_30d`
Win rate, avg R, expectancy over last 30 days of closed plays.

### `tier_performance`
Win rate and R/R broken out by LOCK/LIVE for paper vs live mode.

### `open_exposure`
Sum of (current_value * direction) for all open plays — for risk monitoring.

---

## Encryption notes

OAuth tokens and Plaid access tokens MUST be encrypted at rest in Phase 5. Use `cryptography.fernet` with a key stored in environment variable `BOARD_MARKET_KEY` (not in repo). Decrypt on use, never log.
