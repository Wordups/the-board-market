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

# Windows' legacy console encoding cannot render symbols used by data_pull.py.
# Replace only unsupported console glyphs; JSON output remains UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


def latest_value(frame) -> float:
    return float(frame["Close"].iloc[-1])


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
        })

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
    return snapshot


if __name__ == "__main__":
    board = generate()
    qualified = sum(item["tier"] in ("LOCK", "LIVE") for item in board["setups"])
    print(f"Wrote {len(board['setups'])} setups to {OUTPUT}")
    print(f"Qualified: {qualified} | As of: {board['as_of']}")
