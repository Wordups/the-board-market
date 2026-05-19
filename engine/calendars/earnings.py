"""
The Board: Markets — Earnings Calendar
P2.01

Maintains a cached list of upcoming and historical earnings dates per ticker.

Primary source:  yfinance Ticker.earnings_dates  (includes past + future)
Fallback:        Nasdaq earnings calendar JSON endpoint

Cache file:      data/earnings_calendar.json
                 { "<TICKER>": ["YYYY-MM-DD", ...], "_fetched_at": "..." }

Refresh policy:  24h staleness. Backtest path treats the cache as ground truth
                 (point-in-time discipline is enforced by as_of comparison).

Public API:
    refresh_calendar(force=False) -> dict
    days_to_next_earnings(ticker, as_of) -> int | None

The downgrade rule in score.py is already wired (earnings within 5 days -> -30);
this module just supplies the data.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "earnings_calendar.json"
CACHE_TTL_HOURS = 24

# How far back/forward to keep per ticker. Backtests need history; live needs future.
LOOKBACK_DAYS = 5 * 365
LOOKAHEAD_DAYS = 180


def _to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    cache["_fetched_at"] = datetime.utcnow().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _cache_age_hours(cache: dict) -> float:
    ts = cache.get("_fetched_at")
    if not ts:
        return float("inf")
    try:
        return (datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except ValueError:
        return float("inf")


def _fetch_yfinance(ticker: str) -> list[str]:
    """Returns ISO date strings, sorted ascending."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    df = t.earnings_dates  # property; may raise or return None
    if df is None or len(df) == 0:
        return []
    dates: set[date] = set()
    for idx in df.index:
        d = _to_date(idx)
        if d is None:
            continue
        dates.add(d)
    return sorted(d.isoformat() for d in dates)


def _fetch_nasdaq(ticker: str) -> list[str]:
    """
    Fallback: hit the Nasdaq calendar endpoint for the next 12 months by date
    and pick out rows matching the ticker. Best-effort — returns [] on failure.
    """
    try:
        import httpx
    except ImportError:
        return []

    found: set[date] = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (the-board-market backtest research)",
        "Accept": "application/json",
    }
    today = date.today()
    # Sample twice a month for ~6 months
    for offset_days in range(0, 180, 14):
        day = (today + timedelta(days=offset_days)).isoformat()
        url = f"https://api.nasdaq.com/api/calendar/earnings?date={day}"
        try:
            with httpx.Client(timeout=10) as c:
                r = c.get(url, headers=headers)
                if r.status_code != 200:
                    continue
                data = r.json()
        except Exception:
            continue
        rows = (data.get("data") or {}).get("rows") or []
        for row in rows:
            if (row.get("symbol") or "").upper() == ticker.upper():
                d = _to_date(row.get("date") or day)
                if d:
                    found.add(d)
    return sorted(d.isoformat() for d in found)


def _refresh_ticker(ticker: str) -> list[str]:
    dates = _fetch_yfinance(ticker)
    if dates:
        return dates
    return _fetch_nasdaq(ticker)


def refresh_calendar(tickers: Iterable[str] | None = None,
                     force: bool = False) -> dict:
    """
    Refresh the cached earnings calendar. Reads existing cache to avoid re-pulling
    fresh entries. If `tickers` is None, refreshes every ticker already present
    in the cache plus the project universe.
    """
    cache = _load_cache()
    if not force and _cache_age_hours(cache) < CACHE_TTL_HOURS:
        return cache

    if tickers is None:
        try:
            from universe import ALL_TICKERS
        except ImportError:
            from engine.universe import ALL_TICKERS
        tickers = ALL_TICKERS

    for ticker in tickers:
        fresh = _refresh_ticker(ticker)
        if fresh:
            cache[ticker] = fresh
        elif ticker not in cache:
            cache[ticker] = []

    _save_cache(cache)
    return cache


def days_to_next_earnings(ticker: str, as_of: date | datetime) -> int | None:
    """
    Days from `as_of` to the next earnings event for `ticker`.
    Returns None if no upcoming date is known. Same-day earnings returns 0.

    Point-in-time safe: only looks at dates strictly >= as_of in the cache.
    """
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        return None

    cache = _load_cache()
    dates_iso = cache.get(ticker)
    if not dates_iso:
        return None

    for iso in dates_iso:
        d = _to_date(iso)
        if d is None:
            continue
        if d >= as_of_d:
            return (d - as_of_d).days
    return None


if __name__ == "__main__":
    import sys

    force = "--force" in sys.argv
    print(f"Refreshing earnings calendar (force={force})...")
    cache = refresh_calendar(force=force)
    n_tickers = sum(1 for k in cache if not k.startswith("_"))
    print(f"Cached {n_tickers} tickers -> {CACHE_FILE}")

    today = date.today()
    print(f"\nNext earnings (as of {today}):")
    for tkr in sorted(k for k in cache if not k.startswith("_"))[:15]:
        d = days_to_next_earnings(tkr, today)
        dates_iso = cache.get(tkr, [])
        next_iso = next((x for x in dates_iso if _to_date(x) and _to_date(x) >= today), None)
        print(f"  {tkr:6s}  next={next_iso or '—'}  days={d if d is not None else '—'}")
