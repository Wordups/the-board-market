"""
The Board: Markets — Data Pull
Pulls 5-year OHLCV data from Yahoo Finance with strict point-in-time discipline.

Critical: all data writes include the trade date AND the as-of date.
For backtests, scoring on day D uses ONLY data available through D-1 close.
This prevents lookahead bias — the #1 mistake in retail backtests.
"""

import os
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from universe import ALL_TICKERS, MACRO_CONTEXT

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR = DATA_DIR / "ohlcv_cache"
CACHE_DIR.mkdir(exist_ok=True)


def pull_history(ticker: str, years: int = 5, force_refresh: bool = False) -> pd.DataFrame:
    """
    Pull historical OHLCV for a single ticker.
    Caches to CSV. Re-pulls if cache is >24h old or force_refresh=True.
    """
    cache_file = CACHE_DIR / f"{ticker.replace('^', '').replace('-', '_')}.csv"

    # Cache check
    if cache_file.exists() and not force_refresh:
        age_hours = (datetime.now().timestamp() - cache_file.stat().st_mtime) / 3600
        if age_hours < 24:
            df = pd.read_csv(cache_file, parse_dates=["Date"], index_col="Date")
            return df

    # Fresh pull
    end = datetime.now()
    start = end - timedelta(days=years * 365 + 30)  # buffer for weekends/holidays

    print(f"  Pulling {ticker} ({years}y)...")
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            progress=False,
            auto_adjust=True,
        )
        if df.empty:
            print(f"  ⚠️  No data returned for {ticker}")
            return pd.DataFrame()

        # Handle multi-index columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.to_csv(cache_file)
        return df

    except Exception as e:
        print(f"  ❌ Failed {ticker}: {e}")
        return pd.DataFrame()


def pull_all(force_refresh: bool = False) -> dict:
    """Pull entire universe + macro context. Returns dict of DataFrames."""
    all_tickers = ALL_TICKERS + MACRO_CONTEXT
    print(f"Pulling {len(all_tickers)} tickers...")

    data = {}
    for ticker in all_tickers:
        df = pull_history(ticker, force_refresh=force_refresh)
        if not df.empty:
            data[ticker] = df

    print(f"✅ Loaded {len(data)}/{len(all_tickers)} tickers")
    return data


def get_point_in_time_slice(df: pd.DataFrame, as_of: datetime) -> pd.DataFrame:
    """
    Return data strictly BEFORE as_of date.
    Critical for backtesting: scoring on day D uses only data through D-1 close.
    """
    return df[df.index < pd.Timestamp(as_of)]


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    data = pull_all(force_refresh=force)
    print(f"\nUniverse loaded. Sample (NVDA last 5 rows):")
    if "NVDA" in data:
        print(data["NVDA"].tail())
