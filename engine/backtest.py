"""
The Board: Markets — Backtest Engine

Runs the scoring engine across historical data day-by-day with strict
point-in-time discipline. Simulates entries at next-day open, applies
slippage, tracks outcomes, segregates results by year and regime.

Pass criteria (committed before running):
  - LOCK win rate ≥ 65%
  - LIVE win rate ≥ 55%
  - Average R/R ≥ 1.8:1 net of slippage
  - Max drawdown ≤ 25% of starting bankroll
  - Positive returns in ≥ 4 of 5 years
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

from universe import ALL_TICKERS, MACRO_CONTEXT, SECTOR_MAP
from data_pull import pull_all, get_point_in_time_slice
from score import score_setup

# Configurable parameters
STARTING_BANKROLL = 1000
LOCK_SIZE_PCT = 0.17   # ~$170 per Lock at start
LIVE_SIZE_PCT = 0.085  # ~$85 per Live
STOP_LOSS_PCT = 0.08
TAKE_PROFIT_R = 2.0    # exit at 2R gain
MAX_HOLD_DAYS = 20
STOCK_SLIPPAGE = 0.0015  # 0.15% per side
OPTIONS_SLIPPAGE = 0.05  # 5% spread per round trip — not used Phase 1


def simulate_trade(entry_price: float, entry_date: datetime,
                   df_future: pd.DataFrame, size_dollars: float,
                   tier: str) -> dict:
    """
    Simulate a single trade outcome.
    Entry: next bar open with slippage.
    Exit: -8% stop OR +16% target (2R) OR 20 trading days.
    """
    if df_future.empty or len(df_future) < 2:
        return None

    # Realistic entry: next day open + slippage
    raw_entry = df_future["Open"].iloc[0]
    actual_entry = raw_entry * (1 + STOCK_SLIPPAGE)

    stop_price = actual_entry * (1 - STOP_LOSS_PCT)
    target_price = actual_entry * (1 + STOP_LOSS_PCT * TAKE_PROFIT_R)

    # Walk forward through future bars
    exit_price = None
    exit_reason = None
    exit_date = None
    held_days = 0

    for i, (idx, row) in enumerate(df_future.iloc[1:MAX_HOLD_DAYS + 1].iterrows()):
        held_days = i + 1
        low = row["Low"]
        high = row["High"]

        # Gap-down handling: if open below stop, fill at open
        if row["Open"] <= stop_price:
            exit_price = row["Open"] * (1 - STOCK_SLIPPAGE)
            exit_reason = "GAP_STOP"
            exit_date = idx
            break

        # Intraday stop hit
        if low <= stop_price:
            exit_price = stop_price * (1 - STOCK_SLIPPAGE)
            exit_reason = "STOP"
            exit_date = idx
            break

        # Target hit
        if high >= target_price:
            exit_price = target_price * (1 - STOCK_SLIPPAGE)
            exit_reason = "TARGET"
            exit_date = idx
            break

    # Time exit if no stop/target
    if exit_price is None:
        if len(df_future) >= 2:
            last_bar = df_future.iloc[min(MAX_HOLD_DAYS, len(df_future) - 1)]
            exit_price = last_bar["Close"] * (1 - STOCK_SLIPPAGE)
            exit_reason = "TIME"
            exit_date = df_future.index[min(MAX_HOLD_DAYS, len(df_future) - 1)]
            held_days = MAX_HOLD_DAYS

    if exit_price is None:
        return None

    pct_return = (exit_price - actual_entry) / actual_entry
    dollar_pnl = size_dollars * pct_return
    r_multiple = pct_return / STOP_LOSS_PCT

    return {
        "tier": tier,
        "entry_date": entry_date.strftime("%Y-%m-%d"),
        "exit_date": exit_date.strftime("%Y-%m-%d") if exit_date else None,
        "entry_price": round(actual_entry, 2),
        "exit_price": round(exit_price, 2),
        "stop_price": round(stop_price, 2),
        "target_price": round(target_price, 2),
        "held_days": held_days,
        "exit_reason": exit_reason,
        "size_dollars": round(size_dollars, 2),
        "pct_return": round(pct_return * 100, 2),
        "r_multiple": round(r_multiple, 2),
        "dollar_pnl": round(dollar_pnl, 2),
        "win": pct_return > 0,
    }


def run_backtest(start_date: str, end_date: str,
                 max_concurrent_locks: int = 1,
                 max_concurrent_lives: int = 2) -> dict:
    """Run the full backtest."""

    print(f"\n{'=' * 60}")
    print(f"BOARD: MARKETS — BACKTEST")
    print(f"{start_date} → {end_date}")
    print(f"{'=' * 60}\n")

    # Load all data
    data = pull_all()
    if "SPY" not in data:
        raise RuntimeError("SPY required for relative strength scoring")

    spy = data["SPY"]
    vix = data.get("^VIX")
    tnx = data.get("^TNX")

    # Build trading day calendar from SPY
    cal = spy[(spy.index >= start_date) & (spy.index <= end_date)].index

    bankroll = STARTING_BANKROLL
    equity_curve = [(cal[0].strftime("%Y-%m-%d"), bankroll)]
    all_trades = []
    open_positions = {}  # ticker -> trade dict

    print(f"Backtesting {len(cal)} trading days across {len(ALL_TICKERS)} tickers...")

    for day_i, current_day in enumerate(cal):
        if day_i % 50 == 0:
            print(f"  Day {day_i}/{len(cal)} — {current_day.date()} — Bankroll: ${bankroll:.0f}")

        # Macro context for this day (point-in-time)
        vix_value = 20.0  # default
        tnx_value = 4.0
        if vix is not None:
            vix_slice = get_point_in_time_slice(vix, current_day)
            if len(vix_slice):
                vix_value = float(vix_slice["Close"].iloc[-1])
        if tnx is not None:
            tnx_slice = get_point_in_time_slice(tnx, current_day)
            if len(tnx_slice):
                tnx_value = float(tnx_slice["Close"].iloc[-1])

        spy_slice = get_point_in_time_slice(spy, current_day)

        # Count open positions by tier
        open_locks = sum(1 for t in open_positions.values() if t["tier"] == "LOCK")
        open_lives = sum(1 for t in open_positions.values() if t["tier"] == "LIVE")

        # Score all candidates
        day_scores = []
        for ticker in ALL_TICKERS:
            if ticker in open_positions:
                continue
            if ticker not in data:
                continue

            df_slice = get_point_in_time_slice(data[ticker], current_day)
            if len(df_slice) < 200:
                continue

            result = score_setup(
                ticker=ticker,
                df=df_slice,
                spy_df=spy_slice,
                vix=vix_value,
                tnx=tnx_value,
                as_of=current_day,
            )

            if result["tier"] in ("LOCK", "LIVE"):
                day_scores.append(result)

        # Sort by score, take top setups respecting concurrent limits
        day_scores.sort(key=lambda x: x["score"], reverse=True)

        for setup in day_scores:
            ticker = setup["ticker"]
            tier = setup["tier"]

            # Concurrency limits
            if tier == "LOCK" and open_locks >= max_concurrent_locks:
                continue
            if tier == "LIVE" and open_lives >= max_concurrent_lives:
                continue

            # Position sizing
            size = bankroll * (LOCK_SIZE_PCT if tier == "LOCK" else LIVE_SIZE_PCT)
            if size > bankroll * 0.4:  # never deploy >40% on one play
                size = bankroll * 0.4

            # Need at least one bar after current_day to enter
            df_future = data[ticker][data[ticker].index > current_day]
            if len(df_future) < 2:
                continue

            trade = simulate_trade(
                entry_price=setup["price"],
                entry_date=current_day,
                df_future=df_future,
                size_dollars=size,
                tier=tier,
            )

            if trade is None:
                continue

            trade["ticker"] = ticker
            trade["setup_score"] = setup["score"]
            trade["sector"] = SECTOR_MAP.get(ticker, "unknown")
            trade["regime_at_entry"] = setup["regime"]
            trade["vix_at_entry"] = round(vix_value, 2)
            trade["flags"] = setup["flags"]

            open_positions[ticker] = trade

            if tier == "LOCK":
                open_locks += 1
            else:
                open_lives += 1

        # Resolve positions whose exit_date is on or before current_day
        to_close = []
        for ticker, trade in open_positions.items():
            exit_dt = pd.Timestamp(trade["exit_date"])
            if exit_dt <= current_day:
                to_close.append(ticker)

        for ticker in to_close:
            trade = open_positions.pop(ticker)
            bankroll += trade["dollar_pnl"]
            all_trades.append(trade)

        equity_curve.append((current_day.strftime("%Y-%m-%d"), round(bankroll, 2)))

    # Close any remaining positions at final price
    for ticker, trade in open_positions.items():
        all_trades.append(trade)
        bankroll += trade["dollar_pnl"]

    return analyze_results(all_trades, equity_curve, STARTING_BANKROLL)


def analyze_results(trades: list, equity_curve: list, starting_bankroll: float) -> dict:
    """Compute performance metrics broken down by tier, year, sector, regime."""
    if not trades:
        return {"error": "No trades executed"}

    df = pd.DataFrame(trades)
    df["entry_date"] = pd.to_datetime(df["entry_date"])
    df["year"] = df["entry_date"].dt.year

    def stats(subset: pd.DataFrame) -> dict:
        if len(subset) == 0:
            return {"trades": 0}
        wins = subset[subset["win"]]
        losses = subset[~subset["win"]]
        avg_win = wins["pct_return"].mean() if len(wins) else 0
        avg_loss = losses["pct_return"].mean() if len(losses) else 0
        avg_win_r = wins["r_multiple"].mean() if len(wins) else 0
        avg_loss_r = losses["r_multiple"].mean() if len(losses) else 0
        # Reward:risk payoff ratio — avg winning R over avg losing R magnitude.
        # Distinct from expectancy_r (per-trade R expectation); the 1.8 pass
        # criterion is a payoff ratio, not an expectancy.
        rr_ratio = (avg_win_r / abs(avg_loss_r)) if avg_loss_r else 0
        return {
            "trades": len(subset),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(subset) * 100, 1),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "avg_win_r": round(avg_win_r, 2),
            "avg_loss_r": round(avg_loss_r, 2),
            "rr_ratio": round(rr_ratio, 2),
            "expectancy_r": round(subset["r_multiple"].mean(), 2),
            "total_pnl": round(subset["dollar_pnl"].sum(), 2),
            "expectancy_pct": round(subset["pct_return"].mean(), 2),
        }

    # Equity curve metrics
    eq_values = [v for _, v in equity_curve]
    peak = eq_values[0]
    max_dd = 0
    for v in eq_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    final_bankroll = eq_values[-1]
    total_return = (final_bankroll - starting_bankroll) / starting_bankroll * 100

    return {
        "summary": {
            "starting_bankroll": starting_bankroll,
            "final_bankroll": round(final_bankroll, 2),
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "total_trades": len(trades),
        },
        "overall": stats(df),
        "by_tier": {
            "LOCK": stats(df[df["tier"] == "LOCK"]),
            "LIVE": stats(df[df["tier"] == "LIVE"]),
        },
        "by_year": {
            int(year): stats(df[df["year"] == year])
            for year in sorted(df["year"].unique())
        },
        "by_sector": {
            sec: stats(df[df["sector"] == sec])
            for sec in df["sector"].unique()
        },
        "by_regime": {
            reg: stats(df[df["regime_at_entry"] == reg])
            for reg in df["regime_at_entry"].unique()
        },
        "by_exit_reason": {
            reason: int((df["exit_reason"] == reason).sum())
            for reason in df["exit_reason"].unique()
        },
        "equity_curve": equity_curve,
        "trades": trades,
    }


def check_pass_criteria(results: dict) -> dict:
    """Apply the pre-committed pass/fail criteria."""
    if "error" in results:
        return {"pass": False, "reason": results["error"]}

    lock_wr = results["by_tier"]["LOCK"].get("win_rate", 0)
    live_wr = results["by_tier"]["LIVE"].get("win_rate", 0)
    max_dd = results["summary"]["max_drawdown_pct"]
    rr_ratio = results["overall"].get("rr_ratio", 0)
    positive_years = sum(
        1 for y in results["by_year"].values()
        if y.get("total_pnl", 0) > 0
    )

    criteria = {
        "lock_win_rate_65": (lock_wr >= 65, f"LOCK WR: {lock_wr}% (need ≥65%)"),
        "live_win_rate_55": (live_wr >= 55, f"LIVE WR: {live_wr}% (need ≥55%)"),
        "avg_r_1.8": (rr_ratio >= 1.8, f"R/R ratio: {rr_ratio} (need ≥1.8)"),
        "max_dd_25": (max_dd <= 25, f"Max DD: {max_dd}% (need ≤25%)"),
        "four_of_five_years": (positive_years >= 4, f"Positive years: {positive_years}/5 (need ≥4)"),
    }

    all_pass = all(p for p, _ in criteria.values())

    return {
        "pass": all_pass,
        "criteria": {k: {"passed": p, "detail": d} for k, (p, d) in criteria.items()},
        "verdict": (
            "✅ READY FOR LIVE TRADING" if all_pass
            else "❌ MODEL NEEDS TUNING — DO NOT DEPLOY CAPITAL"
        ),
    }


if __name__ == "__main__":
    end = datetime.now()
    start = end - timedelta(days=5 * 365)

    results = run_backtest(
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
    )

    pass_check = check_pass_criteria(results)
    results["pass_criteria"] = pass_check

    out_path = Path(__file__).parent.parent / "data" / "backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print(f"RESULTS")
    print(f"{'=' * 60}")
    print(f"Final bankroll: ${results['summary']['final_bankroll']}")
    print(f"Total return:   {results['summary']['total_return_pct']}%")
    print(f"Max drawdown:   {results['summary']['max_drawdown_pct']}%")
    print(f"Total trades:   {results['summary']['total_trades']}")
    print(f"\nBy tier:")
    for tier, s in results["by_tier"].items():
        print(f"  {tier}: {s.get('trades', 0)} trades, WR {s.get('win_rate', 0)}%, "
              f"R/R {s.get('rr_ratio', 0)}, Expectancy(R) {s.get('expectancy_r', 0)}")
    print(f"\n{pass_check['verdict']}")
    for k, v in pass_check["criteria"].items():
        mark = "✅" if v["passed"] else "❌"
        print(f"  {mark} {v['detail']}")
    print(f"\nFull results: {out_path}")
