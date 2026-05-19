"""
The Board Market — Performance Analytics

Computes metrics from the ledger. Phase 3.
Read-only: never writes to plays table. Equity curve writes go through eod-resolve job.
"""

from datetime import date, timedelta
from typing import Optional

from .db import db_cursor


def closed_plays(user_id: int, since: Optional[date] = None) -> list[dict]:
    """All closed plays for a user, optionally since a date."""
    sql = "SELECT * FROM plays WHERE user_id = ? AND status = 'closed'"
    params: list = [user_id]
    if since:
        sql += " AND exit_date >= ?"
        params.append(since.isoformat())
    sql += " ORDER BY exit_date DESC"
    with db_cursor() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def compute_stats(plays: list[dict]) -> dict:
    """Win rate, R/R payoff ratio, expectancy from a list of closed plays."""
    if not plays:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_win_pct": 0.0,
            "avg_loss_pct": 0.0,
            "avg_win_r": 0.0,
            "avg_loss_r": 0.0,
            "rr_ratio": 0.0,
            "expectancy_r": 0.0,
            "total_pnl": 0.0,
            "expectancy_pct": 0.0,
        }

    wins = [p for p in plays if (p.get("pct_return") or 0) > 0]
    losses = [p for p in plays if (p.get("pct_return") or 0) <= 0]

    def avg(items, key):
        if not items:
            return 0.0
        return sum(i.get(key) or 0 for i in items) / len(items)

    avg_win_r = avg(wins, "r_multiple")
    avg_loss_r = avg(losses, "r_multiple")
    rr_ratio = (avg_win_r / abs(avg_loss_r)) if avg_loss_r else 0.0

    return {
        "trades": len(plays),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(plays) * 100, 1),
        "avg_win_pct": round(avg(wins, "pct_return"), 2),
        "avg_loss_pct": round(avg(losses, "pct_return"), 2),
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "rr_ratio": round(rr_ratio, 2),
        "expectancy_r": round(avg(plays, "r_multiple"), 2),
        "total_pnl": round(sum(p.get("dollar_pnl") or 0 for p in plays), 2),
        "expectancy_pct": round(avg(plays, "pct_return"), 2),
    }


def performance_summary(user_id: int, period: str = "30d") -> dict:
    """
    Rolling performance over period. Breakdowns by tier and mode.
    period: '30d' | '90d' | 'ytd' | 'all'
    """
    if period == "30d":
        since = date.today() - timedelta(days=30)
    elif period == "90d":
        since = date.today() - timedelta(days=90)
    elif period == "ytd":
        since = date(date.today().year, 1, 1)
    elif period == "all":
        since = None
    else:
        raise ValueError(f"Unknown period: {period}")

    plays = closed_plays(user_id, since)

    return {
        "period": period,
        "since": since.isoformat() if since else None,
        "overall": compute_stats(plays),
        "by_tier": {
            tier: compute_stats([p for p in plays if p.get("tier") == tier])
            for tier in ("LOCK", "LIVE", "STACK")
        },
        "by_mode": {
            mode: compute_stats([p for p in plays if p.get("mode") == mode])
            for mode in ("paper", "live")
        },
        "by_exit_reason": {
            reason: len([p for p in plays if p.get("exit_reason") == reason])
            for reason in ("STOP", "TARGET", "TIME", "GAP_STOP", "MANUAL")
        },
    }


def equity_curve(user_id: int, since: Optional[date] = None) -> list[dict]:
    """Daily equity snapshots."""
    sql = "SELECT * FROM equity_curve WHERE user_id = ?"
    params: list = [user_id]
    if since:
        sql += " AND snapshot_date >= ?"
        params.append(since.isoformat())
    sql += " ORDER BY snapshot_date ASC"
    with db_cursor() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def max_drawdown(user_id: int, since: Optional[date] = None) -> dict:
    """Compute max drawdown over the equity curve."""
    curve = equity_curve(user_id, since)
    if not curve:
        return {"max_dd_pct": 0.0, "peak": 0.0, "trough": 0.0}

    peak = curve[0]["bankroll"]
    max_dd = 0.0
    trough = peak
    for snap in curve:
        v = snap["bankroll"]
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak else 0
        if dd > max_dd:
            max_dd = dd
            trough = v

    return {
        "max_dd_pct": round(max_dd * 100, 2),
        "peak": round(peak, 2),
        "trough": round(trough, 2),
    }
