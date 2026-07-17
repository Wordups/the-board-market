"""
The Board: Markets — Profit outlook + parlay ladder (v3, REPORT-ONLY)

Pure math, no I/O. Two exports consumed by generate_board.py:

    profit_outlook_for(tier) -> dict
        Per-setup economics at the satellite standard structure
        (stop -8% / target +16% = 2:1) priced at the tier's target win rate.

    build_parlay_ladder(setups) -> dict
        Report-only ladder of hypothetical multi-leg combos built from
        satellite-eligible setups (score >= 60, no reject_zone, not
        listing-capped). No parlay venue is connected — the block exists to
        show what the tier win rates imply as fair odds. Deterministic:
        eligible names sort by (-score, ticker).
"""

from __future__ import annotations

# Tier target win rates (calibration targets, per contract v3).
TIER_WIN_RATE = {"LOCK": 0.65, "LIVE": 0.60, "BENCH": 0.50}

SATELLITE_FLOOR = 60          # unchanged v2 floor — do not edit
LADDER_LEG_COUNTS = (2, 3, 4, 6)
LADDER_RUNGS = (200, 600, 1000, 2000, 10000)
EXECUTION_NOTE = "REPORT_ONLY — no parlay venue connected"


def profit_outlook_for(tier: str) -> dict:
    """Stop/target/RR/EV-per-$100 at the tier's target win rate."""
    win_rate = TIER_WIN_RATE.get(tier, 0.50)
    return {
        "stop_pct": -8,
        "target_pct": 16,
        "rr": "2:1",
        "ev_per_100": round(win_rate * 16 - (1 - win_rate) * 8, 2),
    }


def american_from_prob(p: float) -> int | None:
    """
    Fair American odds for probability p, rounded to the nearest 25.
    p < 0.5 -> +100*(1-p)/p ; p >= 0.5 -> -100*p/(1-p).
    """
    if p is None or p <= 0 or p >= 1:
        return None
    if p < 0.5:
        raw = 100 * (1 - p) / p
    else:
        raw = -100 * p / (1 - p)
    return int(round(raw / 25) * 25)


def nearest_rung(fair_american: int | None) -> str | None:
    """Label by the nearest standard ladder rung (ties go to the lower rung)."""
    if fair_american is None:
        return None
    rung = min(LADDER_RUNGS, key=lambda r: (abs(r - fair_american), r))
    return f"+{rung}"


def satellite_eligible(setup: dict) -> bool:
    return (
        setup.get("score", 0) >= SATELLITE_FLOOR
        and not setup.get("reject_zone")
        and not setup.get("listing_capped")
    )


def build_parlay_ladder(setups: list[dict]) -> dict:
    """Build the report-only parlay ladder block for board_today.json."""
    eligible = sorted(
        (s for s in setups if satellite_eligible(s)),
        key=lambda s: (-s.get("score", 0), s.get("ticker", "")),
    )

    rungs = []
    for n_legs in LADDER_LEG_COUNTS:
        if len(eligible) < n_legs:
            continue
        legs = eligible[:n_legs]
        combined = 1.0
        for s in legs:
            combined *= TIER_WIN_RATE.get(s.get("tier"), 0.50)
        fair = american_from_prob(combined)
        rungs.append({
            "n_legs": n_legs,
            "legs": [
                {
                    "ticker": s.get("ticker"),
                    "score": s.get("score"),
                    "tier": s.get("tier"),
                    "win_rate": TIER_WIN_RATE.get(s.get("tier"), 0.50),
                }
                for s in legs
            ],
            "combined_prob": round(combined, 4),
            "fair_american": fair,
            "rung": nearest_rung(fair),
        })

    return {
        "execution": EXECUTION_NOTE,
        "eligible_count": len(eligible),
        "rungs": rungs,
    }
