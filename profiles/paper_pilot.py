"""Local-only paper execution pilot.

This module never connects to a broker and never places orders. It consumes the
static board snapshot, opens simulated fractional-share positions, and resolves
them against later daily snapshots.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
BOARD_PATH = ROOT / "data" / "board_today.json"
STATE_PATH = ROOT / ".state" / "paper_pilot.json"

LOCK_SIZE_PCT = 0.17
LIVE_SIZE_PCT = 0.085
CASH_FLOOR_PCT = 0.40
STOP_LOSS_PCT = 0.08
TARGET_GAIN_PCT = 0.16
MAX_LOCKS = 1
MAX_LIVES = 2
MAX_HOLD_SNAPSHOTS = 20


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(state: dict[str, Any]) -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp_path.replace(STATE_PATH)
    return state


def _board() -> dict[str, Any]:
    if not BOARD_PATH.exists():
        raise FileNotFoundError("Generate data/board_today.json before running Paper Pilot")
    return _read_json(BOARD_PATH)


def idle_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "mode": "paper",
        "starting_bankroll": 100.0,
        "equity": 100.0,
        "cash": 100.0,
        "deployed": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_risk": 0.0,
        "positions": [],
        "history": [],
        "rules": _rules(),
    }


def _rules() -> dict[str, Any]:
    return {
        "lock_size_pct": LOCK_SIZE_PCT * 100,
        "live_size_pct": LIVE_SIZE_PCT * 100,
        "cash_floor_pct": CASH_FLOOR_PCT * 100,
        "stop_loss_pct": STOP_LOSS_PCT * 100,
        "target_gain_pct": TARGET_GAIN_PCT * 100,
        "max_locks": MAX_LOCKS,
        "max_lives": MAX_LIVES,
        "max_hold_snapshots": MAX_HOLD_SNAPSHOTS,
        "order_routing": False,
    }


def get_pilot() -> dict[str, Any]:
    return _read_json(STATE_PATH) if STATE_PATH.exists() else idle_state()


def _position_from_setup(setup: dict[str, Any], allocation: float, as_of: str) -> dict[str, Any]:
    entry = float(setup["price"])
    stop = float(setup.get("stop") or entry * (1 - STOP_LOSS_PCT))
    target = float(setup.get("target") or entry * (1 + TARGET_GAIN_PCT))
    shares = allocation / entry
    return {
        "ticker": setup["ticker"],
        "tier": setup["tier"],
        "score": float(setup["score"]),
        "entry_as_of": as_of,
        "entry_price": round(entry, 4),
        "last_price": round(entry, 4),
        "stop_price": round(stop, 4),
        "target_price": round(target, 4),
        "cost_basis": round(allocation, 4),
        "shares": round(shares, 8),
        "risk_dollars": round(max(entry - stop, 0) * shares, 4),
        "unrealized_pnl": 0.0,
        "snapshots_held": 0,
        "status": "open",
    }


def _open_slots(state: dict[str, Any], board: dict[str, Any]) -> None:
    positions = state["positions"]
    open_tickers = {position["ticker"] for position in positions}
    traded_tickers = {trade["ticker"] for trade in state.get("history", [])}
    lock_count = sum(position["tier"] == "LOCK" for position in positions)
    live_count = sum(position["tier"] == "LIVE" for position in positions)
    max_deployable = state["equity"] * (1 - CASH_FLOOR_PCT)
    deployed_cost = sum(position["cost_basis"] for position in positions)

    setups = sorted(board.get("setups", []), key=lambda item: float(item.get("score", 0)), reverse=True)
    for setup in setups:
        tier = setup.get("tier")
        ticker = setup.get("ticker")
        if tier not in ("LOCK", "LIVE") or ticker in open_tickers or ticker in traded_tickers:
            continue
        if tier == "LOCK" and lock_count >= MAX_LOCKS:
            continue
        if tier == "LIVE" and live_count >= MAX_LIVES:
            continue
        price = float(setup.get("price") or 0)
        if price <= 0:
            continue

        size_pct = LOCK_SIZE_PCT if tier == "LOCK" else LIVE_SIZE_PCT
        allocation = round(state["equity"] * size_pct, 4)
        allocation = min(allocation, round(max_deployable - deployed_cost, 4), state["cash"])
        if allocation <= 0:
            continue

        position = _position_from_setup(setup, allocation, board["as_of"])
        positions.append(position)
        state["cash"] = round(state["cash"] - allocation, 4)
        deployed_cost += allocation
        open_tickers.add(ticker)
        if tier == "LOCK":
            lock_count += 1
        else:
            live_count += 1


def _recalculate(state: dict[str, Any]) -> None:
    market_value = 0.0
    unrealized = 0.0
    total_risk = 0.0
    for position in state["positions"]:
        value = position["last_price"] * position["shares"]
        pnl = value - position["cost_basis"]
        position["unrealized_pnl"] = round(pnl, 4)
        market_value += value
        unrealized += pnl
        total_risk += max(position["entry_price"] - position["stop_price"], 0) * position["shares"]
    state["deployed"] = round(market_value, 2)
    state["unrealized_pnl"] = round(unrealized, 2)
    state["total_risk"] = round(total_risk, 2)
    state["equity"] = round(state["cash"] + market_value, 2)


def start_pilot(bankroll: float = 100.0) -> dict[str, Any]:
    bankroll = round(float(bankroll), 2)
    if not 10 <= bankroll <= 1000:
        raise ValueError("Paper bankroll must be between $10 and the $1,000 validation cap")
    board = _board()
    state = {
        **idle_state(),
        "status": "active",
        "starting_bankroll": bankroll,
        "equity": bankroll,
        "cash": bankroll,
        "created_at": _now(),
        "last_reconciled_at": _now(),
        "last_reconciled_as_of": board["as_of"],
    }
    _open_slots(state, board)
    _recalculate(state)
    if not state["positions"]:
        state["status"] = "waiting"
    return _write_state(state)


def reconcile_pilot() -> dict[str, Any]:
    state = get_pilot()
    if state["status"] == "idle":
        raise ValueError("Start the paper pilot before reconciling it")
    board = _board()
    setup_map = {setup["ticker"]: setup for setup in board.get("setups", [])}
    still_open = []

    for position in state["positions"]:
        setup = setup_map.get(position["ticker"])
        if not setup:
            still_open.append(position)
            continue
        current = float(setup["price"])
        position["last_price"] = round(current, 4)
        if board["as_of"] != state.get("last_reconciled_as_of"):
            position["snapshots_held"] += 1

        exit_reason = None
        exit_price = None
        if current <= position["stop_price"]:
            exit_reason = "STOP_CLOSE"
            exit_price = current
        elif current >= position["target_price"]:
            exit_reason = "TARGET"
            exit_price = position["target_price"]
        elif position["snapshots_held"] >= MAX_HOLD_SNAPSHOTS:
            exit_reason = "TIME"
            exit_price = current

        if exit_reason is None:
            still_open.append(position)
            continue

        proceeds = exit_price * position["shares"]
        pnl = proceeds - position["cost_basis"]
        state["cash"] = round(state["cash"] + proceeds, 4)
        state["realized_pnl"] = round(state["realized_pnl"] + pnl, 4)
        state["history"].append({
            **position,
            "status": "closed",
            "exit_as_of": board["as_of"],
            "exit_price": round(exit_price, 4),
            "exit_reason": exit_reason,
            "dollar_pnl": round(pnl, 4),
            "return_pct": round(pnl / position["cost_basis"] * 100, 2),
        })

    state["positions"] = still_open
    _recalculate(state)
    _open_slots(state, board)
    _recalculate(state)
    state["status"] = "active" if state["positions"] else "waiting"
    state["last_reconciled_at"] = _now()
    state["last_reconciled_as_of"] = board["as_of"]
    return _write_state(state)


def reset_pilot() -> dict[str, Any]:
    if STATE_PATH.exists():
        STATE_PATH.unlink()
    return idle_state()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Paper Pilot")
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("--bankroll", type=float, default=100.0)
    subparsers.add_parser("refresh")
    subparsers.add_parser("status")
    subparsers.add_parser("reset")
    args = parser.parse_args()

    if args.command == "start":
        state = start_pilot(args.bankroll)
    elif args.command == "refresh":
        state = reconcile_pilot()
    elif args.command == "reset":
        state = reset_pilot()
    else:
        state = get_pilot()
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
