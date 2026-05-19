"""
Event type registry for the-board-market source.

Authoritative list of every event type this product can emit. Keep in sync
with docs/EVENTS.md. Subscribers reading this product's events should be
able to expect ONLY these types from src="board-market".
"""

# type → (current_version, severity, description)
EVENT_TYPES = {
    # ─── Play lifecycle ───
    "play.created": (
        1, "MEDIUM",
        "New play logged to the ledger (paper or live)."
    ),
    "play.stop_hit": (
        1, "CRITICAL",
        "Open play exited because the stop loss triggered."
    ),
    "play.target_hit": (
        1, "CRITICAL",
        "Open play exited because the take-profit target hit."
    ),
    "play.time_exit": (
        1, "HIGH",
        "Open play closed after max-hold window (20 trading days)."
    ),
    "play.cancelled": (
        1, "LOW",
        "Play voided before entry executed."
    ),
    "play.gap_stop": (
        1, "CRITICAL",
        "Play exited on a gap-down open below the stop price."
    ),

    # ─── Board lifecycle ───
    "board.published": (
        1, "MEDIUM",
        "Pre-market board scored and ready (7:30 AM ET)."
    ),
    "board.frozen": (
        1, "MEDIUM",
        "Daily board frozen at the 9:30 AM ET market open."
    ),
    "board.eod_closed": (
        1, "MEDIUM",
        "End-of-day resolution complete; ledger updated."
    ),

    # ─── Signal events ───
    "signal.score_changed": (
        1, "HIGH",
        "Open play's setup score moved by 10+ points (boost or decay)."
    ),
    "signal.congressional_cluster": (
        1, "HIGH",
        "3+ congressional members bought a watchlist ticker within 30 days."
    ),
    "signal.earnings_proximity": (
        1, "HIGH",
        "Open position's earnings date is within 5 trading days."
    ),
    "signal.insider_buy": (
        1, "HIGH",
        "Form 4 buy by officer or director exceeding $50K on watchlist ticker."
    ),
    "signal.material_event": (
        1, "CRITICAL",
        "8-K or other material filing on a ticker with an open position."
    ),

    # ─── Risk events ───
    "risk.drawdown_threshold": (
        1, "CRITICAL",
        "Bankroll dropped past a configured drawdown threshold (15/30/50%)."
    ),
    "risk.position_limit": (
        1, "HIGH",
        "Attempted to open a play that would exceed concurrency limits."
    ),
    "risk.cash_floor": (
        1, "HIGH",
        "Cash sleeve dropped below the 40% floor."
    ),
}
