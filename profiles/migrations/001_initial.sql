-- The Board Market — Initial Schema
-- Phase 3 migration. SQLite. See docs/SCHEMA.md for full spec.

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login      TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id                 INTEGER NOT NULL REFERENCES users(id),
    provider                TEXT NOT NULL CHECK (provider IN ('schwab_api', 'plaid', 'manual_csv')),
    account_type            TEXT NOT NULL CHECK (account_type IN ('trading', 'roth', 'other')),
    nickname                TEXT,
    oauth_access_token      TEXT,        -- encrypted at rest
    oauth_refresh_token     TEXT,        -- encrypted at rest
    oauth_expires_at        TIMESTAMP,
    plaid_access_token      TEXT,        -- encrypted at rest
    last_synced_at          TIMESTAMP,
    is_active               BOOLEAN DEFAULT 1,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS positions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES accounts(id),
    ticker              TEXT NOT NULL,
    quantity            REAL NOT NULL,
    avg_cost            REAL NOT NULL,
    market_value        REAL,
    unrealized_pnl      REAL,
    as_of               TIMESTAMP NOT NULL,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    ticker          TEXT NOT NULL,
    tier            TEXT NOT NULL CHECK (tier IN ('LOCK', 'LIVE', 'STACK')),
    mode            TEXT NOT NULL CHECK (mode IN ('paper', 'live')),
    setup_score     REAL NOT NULL,
    factors_json    TEXT,
    flags_json      TEXT,
    catalyst        TEXT,
    entry_date      DATE NOT NULL,
    entry_price     REAL NOT NULL,
    stop_price      REAL NOT NULL,
    target_price    REAL NOT NULL,
    size_dollars    REAL NOT NULL,
    size_shares     REAL,
    horizon         TEXT CHECK (horizon IN ('day_swing', 'swing', 'position')),
    exit_date       DATE,
    exit_price      REAL,
    exit_reason     TEXT CHECK (exit_reason IN ('STOP', 'TARGET', 'TIME', 'GAP_STOP', 'MANUAL') OR exit_reason IS NULL),
    held_days       INTEGER,
    pct_return      REAL,
    r_multiple      REAL,
    dollar_pnl      REAL,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'cancelled')),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_boards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    board_date      DATE NOT NULL,
    frozen_at       TIMESTAMP,
    board_json      TEXT NOT NULL,
    regime          TEXT CHECK (regime IN ('BULL', 'BEAR', 'SIDEWAYS', 'UNKNOWN')),
    vix_close       REAL,
    tnx_close       REAL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS equity_curve (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id),
    snapshot_date       DATE NOT NULL,
    bankroll            REAL NOT NULL,
    open_pnl            REAL DEFAULT 0,
    realized_pnl_ytd    REAL DEFAULT 0,
    play_count_ytd      INTEGER DEFAULT 0,
    win_count_ytd       INTEGER DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS preferences (
    user_id                     INTEGER PRIMARY KEY REFERENCES users(id),
    watchlist_additions_json    TEXT DEFAULT '[]',
    universe_exclusions_json    TEXT DEFAULT '[]',
    risk_overrides_json         TEXT DEFAULT '{}',
    notification_email          TEXT,
    notification_slack_webhook  TEXT,
    updated_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_plays_user_status      ON plays(user_id, status);
CREATE INDEX IF NOT EXISTS idx_plays_entry_date       ON plays(entry_date);
CREATE INDEX IF NOT EXISTS idx_plays_ticker           ON plays(ticker);
CREATE INDEX IF NOT EXISTS idx_positions_account      ON positions(account_id);
CREATE INDEX IF NOT EXISTS idx_daily_boards_date      ON daily_boards(board_date DESC);
CREATE INDEX IF NOT EXISTS idx_equity_curve_user_date ON equity_curve(user_id, snapshot_date DESC);
