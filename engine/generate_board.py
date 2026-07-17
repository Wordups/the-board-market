"""Generate the static board snapshot consumed by the web dashboard."""

import json
import sys
from datetime import datetime
from pathlib import Path

from data_pull import pull_all
from score import score_setup
from universe import ALL_TICKERS, SECTOR_MAP


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "board_today.json"
CHARTS_OUTPUT = ROOT / "data" / "charts_today.json"
CHART_DAYS = 60

# Windows' legacy console encoding cannot render symbols used by data_pull.py.
# Replace only unsupported console glyphs; JSON output remains UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


def latest_value(frame) -> float:
    return float(frame["Close"].iloc[-1])


def breakout_read(frame) -> dict:
    """20-day-high breakout setup: trigger level, distance, and volume-confirmed state.

    Trigger uses the prior 20 sessions (excludes the latest bar) so a bar that
    clears it counts as the breakout rather than raising its own trigger.
    """
    if len(frame) < 25:
        return {"trigger": None, "pct_to_trigger": None, "vol_ratio": None, "confirmed": False}
    prior = frame.iloc[-21:-1]
    trigger = float(prior["High"].max())
    close = float(frame["Close"].iloc[-1])
    avg_vol = float(prior["Volume"].mean())
    vol = float(frame["Volume"].iloc[-1])
    vol_ratio = vol / avg_vol if avg_vol else 0.0
    return {
        "trigger": round(trigger, 2),
        "pct_to_trigger": round((trigger / close - 1) * 100, 2) if close else None,
        "vol_ratio": round(vol_ratio, 2),
        "confirmed": bool(close > trigger and vol_ratio >= 1.5),
    }


def chart_payload(frame, days: int = CHART_DAYS) -> dict:
    """Compact per-ticker chart data: [date, o, h, l, c, v] rows + aligned MAs."""
    ma20_full = frame["Close"].rolling(20).mean()
    ma50_full = frame["Close"].rolling(50).mean()
    tail = frame.tail(days)
    candles, ma20, ma50 = [], [], []
    for idx, row in tail.iterrows():
        candles.append([
            idx.strftime("%Y-%m-%d"),
            round(float(row["Open"]), 2),
            round(float(row["High"]), 2),
            round(float(row["Low"]), 2),
            round(float(row["Close"]), 2),
            int(row["Volume"]),
        ])
        m20 = ma20_full.loc[idx]
        m50 = ma50_full.loc[idx]
        ma20.append(round(float(m20), 2) if m20 == m20 else None)
        ma50.append(round(float(m50), 2) if m50 == m50 else None)
    return {"candles": candles, "ma20": ma20, "ma50": ma50}


def generate() -> dict:
    data = pull_all()
    required = ("SPY", "^VIX", "^TNX")
    missing = [ticker for ticker in required if ticker not in data]
    if missing:
        raise RuntimeError(f"Missing required market context: {', '.join(missing)}")

    spy = data["SPY"]
    vix = latest_value(data["^VIX"])
    tnx = latest_value(data["^TNX"])
    as_of = spy.index[-1].to_pydatetime()
    setups = []
    charts = {}

    for ticker in ALL_TICKERS:
        frame = data.get(ticker)
        if frame is None or frame.empty:
            continue
        scored = score_setup(ticker, frame, spy, vix, tnx, as_of)
        price = float(scored["price"])
        previous = float(frame["Close"].iloc[-2]) if len(frame) > 1 else price
        tier = scored["tier"]
        setups.append({
            **scored,
            "sector": SECTOR_MAP.get(ticker, "unclassified"),
            "change_pct": round((price / previous - 1) * 100, 2) if previous else 0,
            "entry_low": round(price * 0.995, 2),
            "entry_high": round(price * 1.005, 2),
            "stop": round(price * 0.92, 2),
            "target": round(price * 1.16, 2),
            "allocation_pct": 17 if tier == "LOCK" else 8.5 if tier == "LIVE" else 0,
            "breakout": breakout_read(frame),
        })
        charts[ticker] = chart_payload(frame)

    setups.sort(key=lambda item: item["score"], reverse=True)
    snapshot = {
        "status": "model",
        "as_of": as_of.strftime("%Y-%m-%d"),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "integrity": "Phase 1 · partial",
        "context": {
            "regime": setups[0]["regime"] if setups else "UNKNOWN",
            "vix": round(vix, 2),
            "tnx": round(tnx, 2),
        },
        "rules": {
            "lock_threshold": 85,
            "live_threshold": 71,
            "stop_loss_pct": 8,
            "target_gain_pct": 16,
            "capital_cap": 1000,
            "cash_floor_pct": 40,
        },
        "limitations": [
            "Smart Money is a neutral placeholder until Form 4 and 13F feeds are wired.",
            "Catalyst scoring is sector baseline only; verify earnings dates manually.",
            "Prices are last available daily closes and may be delayed.",
        ],
        "setups": setups,
    }
    OUTPUT.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    CHARTS_OUTPUT.write_text(
        json.dumps({"as_of": snapshot["as_of"], "days": CHART_DAYS, "tickers": charts},
                   separators=(",", ":")),
        encoding="utf-8",
    )
    return snapshot


if __name__ == "__main__":
    board = generate()
    qualified = sum(item["tier"] in ("LOCK", "LIVE") for item in board["setups"])
    print(f"Wrote {len(board['setups'])} setups to {OUTPUT}")
    print(f"Qualified: {qualified} | As of: {board['as_of']}")
