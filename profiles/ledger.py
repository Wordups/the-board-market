"""
The Board Market — Ledger

Logs trades (paper and live), tracks status, computes P/L on close.
Phase 3. Builds on profile/db.py.
"""

import json
from datetime import date, datetime
from typing import Optional, Literal

from .db import db_cursor


TIER = Literal["LOCK", "LIVE", "STACK"]
MODE = Literal["paper", "live"]
HORIZON = Literal["day_swing", "swing", "position"]
EXIT_REASON = Literal["STOP", "TARGET", "TIME", "GAP_STOP", "MANUAL"]


# Position sizing defaults — overridden by user preferences if set
DEFAULT_SIZING = {
    "LOCK": 0.17,
    "LIVE": 0.085,
    "STACK": 0.20,
}

STOP_LOSS_PCT = 0.08
TAKE_PROFIT_R = 2.0  # exit at 2R gain


def create_play(
    user_id: int,
    ticker: str,
    tier: TIER,
    mode: MODE,
    setup_score: float,
    entry_price: float,
    bankroll: float,
    horizon: HORIZON = "swing",
    factors: Optional[dict] = None,
    flags: Optional[list] = None,
    catalyst: Optional[str] = None,
    custom_size_pct: Optional[float] = None,
) -> dict:
    """Log a new play. Computes stop, target, size from defaults."""

    size_pct = custom_size_pct or DEFAULT_SIZING[tier]
    size_dollars = round(bankroll * size_pct, 2)
    size_shares = round(size_dollars / entry_price, 4)
    stop_price = round(entry_price * (1 - STOP_LOSS_PCT), 2)
    target_price = round(entry_price * (1 + STOP_LOSS_PCT * TAKE_PROFIT_R), 2)

    with db_cursor() as c:
        c.execute(
            """
            INSERT INTO plays (
                user_id, ticker, tier, mode, setup_score,
                factors_json, flags_json, catalyst,
                entry_date, entry_price, stop_price, target_price,
                size_dollars, size_shares, horizon, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
            """,
            (
                user_id, ticker.upper(), tier, mode, setup_score,
                json.dumps(factors) if factors else None,
                json.dumps(flags) if flags else None,
                catalyst,
                date.today().isoformat(), entry_price, stop_price, target_price,
                size_dollars, size_shares, horizon,
            ),
        )
        play_id = c.lastrowid

    return get_play(play_id)


def close_play(
    play_id: int,
    exit_price: float,
    exit_reason: EXIT_REASON,
    exit_date: Optional[date] = None,
) -> dict:
    """Close an open play. Computes pct_return, R, dollar_pnl, held_days."""

    exit_date = exit_date or date.today()

    with db_cursor() as c:
        play = c.execute(
            "SELECT * FROM plays WHERE id = ? AND status = 'open'",
            (play_id,),
        ).fetchone()

        if play is None:
            raise ValueError(f"No open play with id {play_id}")

        entry_price = play["entry_price"]
        size_dollars = play["size_dollars"]
        pct_return = (exit_price - entry_price) / entry_price
        r_multiple = pct_return / STOP_LOSS_PCT
        dollar_pnl = size_dollars * pct_return
        held_days = (exit_date - date.fromisoformat(play["entry_date"])).days

        c.execute(
            """
            UPDATE plays SET
                exit_date = ?, exit_price = ?, exit_reason = ?,
                held_days = ?, pct_return = ?, r_multiple = ?,
                dollar_pnl = ?, status = 'closed', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                exit_date.isoformat(), exit_price, exit_reason,
                held_days, round(pct_return * 100, 2), round(r_multiple, 2),
                round(dollar_pnl, 2), play_id,
            ),
        )

    return get_play(play_id)


def get_play(play_id: int) -> Optional[dict]:
    """Single play by id with parsed JSON fields."""
    with db_cursor() as c:
        row = c.execute("SELECT * FROM plays WHERE id = ?", (play_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        if out.get("factors_json"):
            out["factors"] = json.loads(out["factors_json"])
        if out.get("flags_json"):
            out["flags"] = json.loads(out["flags_json"])
        return out


def list_plays(
    user_id: int,
    status: Optional[str] = None,
    tier: Optional[TIER] = None,
    mode: Optional[MODE] = None,
    since: Optional[date] = None,
    limit: int = 100,
) -> list[dict]:
    """List plays with filters."""
    sql = "SELECT * FROM plays WHERE user_id = ?"
    params: list = [user_id]

    if status:
        sql += " AND status = ?"
        params.append(status)
    if tier:
        sql += " AND tier = ?"
        params.append(tier)
    if mode:
        sql += " AND mode = ?"
        params.append(mode)
    if since:
        sql += " AND entry_date >= ?"
        params.append(since.isoformat())

    sql += " ORDER BY entry_date DESC, id DESC LIMIT ?"
    params.append(limit)

    with db_cursor() as c:
        rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def cancel_play(play_id: int) -> dict:
    """Cancel an open play (didn't actually enter). Marks as cancelled."""
    with db_cursor() as c:
        c.execute(
            """
            UPDATE plays SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status = 'open'
            """,
            (play_id,),
        )
    return get_play(play_id)
