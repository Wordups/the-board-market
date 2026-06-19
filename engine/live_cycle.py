"""Unattended daily LIVE cycle — PRIVATE backend ONLY.

Refreshes the board, runs the $100-capped live execution, then reconciles open
positions. Schedule it on the private machine (cron / Windows Task Scheduler).

NEVER run this on public CI / GitHub Actions: it requires Schwab OAuth tokens and
LIVE_TRADING_ENABLED, which must never live in a public runner. If the kill switch
is off it just refreshes the board and places nothing (safe no-op).
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generate_board import generate  # noqa: E402
from connectors import schwab  # noqa: E402
from profiles import live_pilot  # noqa: E402


def main() -> None:
    board = generate()
    as_of = board.get("as_of")

    if not schwab.live_trading_enabled():
        print(f"Board refreshed for {as_of}. LIVE_TRADING_ENABLED is off — no orders placed.")
        return
    if schwab.load_tokens() is None:
        print(f"Board refreshed for {as_of}. Schwab not authenticated — run the OAuth login first.")
        return
    if live_pilot.account_hash() is None:
        print(f"Board refreshed for {as_of}. SCHWAB_ACCOUNT_HASH not set — refusing to trade.")
        return

    state = live_pilot.run_live_cycle()
    cap = state.get("capital_cap")
    print(
        f"Live cycle {as_of}: placed {state.get('last_run_placed', 0)} setup(s) | "
        f"deployed ${state.get('deployed', 0):.2f} / ${cap}"
    )

    try:
        live_pilot.reconcile_live()
        print("Reconciled open positions against the broker.")
    except Exception as exc:  # noqa: BLE001 — reconciliation is best-effort
        print(f"Reconcile skipped: {exc}")


if __name__ == "__main__":
    main()
