"""Live execution pilot — places REAL Schwab orders, hard-capped at $100.

Full-auto: ranks the board's tradable (LOCK/LIVE) setups, buys whole shares
within LIVE_CAPITAL_CAP, and attaches a protective sell-stop to each entry.

THREE INDEPENDENT SAFETY GATES — all must pass before a real order is sent:
  1. LIVE_TRADING_ENABLED truthy            (master kill switch; off by default)
  2. Schwab OAuth tokens present            (you logged in)
  3. deployed + cost <= LIVE_CAPITAL_CAP    (hard $100 ceiling, by construction)

Nothing trades until you set the flag, complete the Schwab login, fund the cap,
and set SCHWAB_ACCOUNT_HASH. Equities/ETFs only; whole shares only (Schwab API
market orders take integer quantity), so names priced above the remaining cap
are skipped — at $100 that may be most of the board until you raise the cap.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from connectors import schwab


ROOT = Path(__file__).resolve().parent.parent
BOARD_PATH = ROOT / "data" / "board_today.json"
STATE_PATH = ROOT / ".state" / "live_pilot.json"

STOP_LOSS_PCT = 0.08
TARGET_GAIN_PCT = 0.16
DEFAULT_CAP = 100.0


def capital_cap() -> float:
    """Hard ceiling on total real capital the bot may deploy. Default $100."""
    try:
        return float(os.environ.get("LIVE_CAPITAL_CAP", DEFAULT_CAP))
    except ValueError:
        return DEFAULT_CAP


def account_hash() -> str | None:
    return os.environ.get("SCHWAB_ACCOUNT_HASH") or None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _board() -> dict[str, Any]:
    if not BOARD_PATH.exists():
        raise FileNotFoundError("Generate data/board_today.json before running the live pilot")
    return json.loads(BOARD_PATH.read_text(encoding="utf-8"))


def _write_state(state: dict[str, Any]) -> dict[str, Any]:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)
    return state


def idle_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "mode": "live",
        "capital_cap": capital_cap(),
        "deployed": 0.0,
        "positions": [],
        "history": [],
    }


def live_status() -> dict[str, Any]:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else idle_state()
    state["capital_cap"] = capital_cap()
    state["live_trading_enabled"] = schwab.live_trading_enabled()
    state["authorized"] = schwab.load_tokens() is not None
    state["account_configured"] = account_hash() is not None
    state["headroom"] = round(capital_cap() - state.get("deployed", 0.0), 2)
    return state


def _client() -> "schwab.SchwabClient":
    tokens = schwab.load_tokens()
    if not tokens:
        raise RuntimeError("Schwab is not authenticated — complete the OAuth login first")
    return schwab.SchwabClient(tokens["access_token"])


def run_live_cycle(client: Any | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Place real entries (and protective stops) for tradable setups, never
    exceeding the capital cap. dry_run=True plans the trades but sends nothing.

    `client` is injectable for tests; when None and not dry_run a real
    authenticated SchwabClient is built.
    """
    if not dry_run and not schwab.live_trading_enabled():
        raise RuntimeError("LIVE_TRADING_ENABLED is false — refusing to place real orders")

    cap = capital_cap()
    board = _board()
    state = live_status()
    if state["status"] == "idle":
        state["status"] = "active"
        state.setdefault("created_at", _now())

    acct = account_hash()
    if not dry_run:
        if not acct:
            raise RuntimeError("Set SCHWAB_ACCOUNT_HASH to the funded account before going live")
        if client is None:
            client = _client()

    deployed = float(state.get("deployed", 0.0))
    open_tickers = {p["ticker"] for p in state["positions"]}
    placed: list[dict[str, Any]] = []

    setups = sorted(
        (s for s in board.get("setups", []) if s.get("tier") in ("LOCK", "LIVE")),
        key=lambda s: float(s.get("score", 0)),
        reverse=True,
    )

    for setup in setups:
        ticker = setup.get("ticker")
        price = float(setup.get("price") or 0)
        if not ticker or price <= 0 or ticker in open_tickers:
            continue

        headroom = cap - deployed
        qty = int(headroom // price)  # whole shares only
        if qty < 1:
            continue  # cannot afford one share within the remaining cap
        cost = qty * price
        # HARD INVARIANT — by construction qty <= headroom/price, but assert anyway.
        if deployed + cost > cap + 1e-6:
            continue

        stop_price = round(price * (1 - STOP_LOSS_PCT), 2)
        target_price = round(price * (1 + TARGET_GAIN_PCT), 2)
        entry = {
            "ticker": ticker,
            "tier": setup.get("tier"),
            "score": float(setup.get("score", 0)),
            "qty": qty,
            "entry_price": round(price, 4),
            "cost_basis": round(cost, 2),
            "stop_price": stop_price,
            "target_price": target_price,
            "placed_at": _now(),
            "status": "dry_run" if dry_run else "submitted",
            "entry_order_id": None,
            "stop_order_id": None,
        }

        if not dry_run:
            buy = client.place_order(acct, schwab.build_equity_market_order(ticker, qty, "BUY"))
            entry["entry_order_id"] = buy.get("order_id")
            stop = client.place_order(acct, schwab.build_stop_loss_order(ticker, qty, stop_price))
            entry["stop_order_id"] = stop.get("order_id")

        placed.append(entry)
        deployed += cost
        open_tickers.add(ticker)

    state["positions"].extend(placed)
    state["deployed"] = round(deployed, 2)
    state["headroom"] = round(cap - deployed, 2)
    state["last_run_at"] = _now()
    state["last_run_as_of"] = board.get("as_of")
    state["last_run_placed"] = len(placed)
    state["last_run_dry"] = dry_run
    if not dry_run:
        _write_state(state)
    return state


def reconcile_live(client: Any | None = None) -> dict[str, Any]:
    """Refresh open positions from the broker (last price, closed fills)."""
    state = live_status()
    acct = account_hash()
    if not acct:
        raise RuntimeError("Set SCHWAB_ACCOUNT_HASH before reconciling")
    if client is None:
        client = _client()
    broker_positions = {
        p.get("instrument", {}).get("symbol"): p
        for p in client.get_positions(acct)
    }
    for position in state["positions"]:
        bp = broker_positions.get(position["ticker"])
        position["broker_open"] = bp is not None
        if bp is not None:
            position["last_price"] = bp.get("marketValue")
    state["last_reconciled_at"] = _now()
    return _write_state(state)


def reset_live() -> dict[str, Any]:
    """Clear local live-pilot state. Does NOT cancel live broker orders."""
    if STATE_PATH.exists():
        STATE_PATH.unlink()
    return idle_state()
