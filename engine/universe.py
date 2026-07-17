"""
The Board: Markets — Universe Definition
~45 tickers across structural growth, sector breadth, macro, and crypto exposure.

Curation logic:
- Multi-year persistence (not flash-in-pan names)
- Liquid options chains for spread plays
- Sector breadth for rotation setups
- Macro hedges (TLT, GLD) for regime-change scoring
- BTC exposure via IBIT (no crypto exchange dependency)
"""

UNIVERSE = {
    # Mega-cap structural — the trend backbone
    "mega_cap": [
        "NVDA", "MSFT", "GOOGL", "AAPL", "META",
        "AMZN", "TSLA", "AVGO", "LLY", "COST"
    ],

    # Secondary growth / mid-cap momentum — where setups fire most
    "growth_momentum": [
        "AMD", "CRWD", "PANW", "NOW", "ANET",
        "ARM", "MU", "SMCI"
    ],

    # Financials — rate-sensitive, earnings-driven
    "financials": ["JPM", "GS", "V", "MA"],

    # Energy — geopolitical hedge
    "energy": ["XOM", "CVX", "SLB", "OXY"],

    # Defense — second geopolitical hedge
    "defense": ["LMT", "RTX", "NOC"],

    # Sector ETFs — macro/rotation plays
    "sector_etfs": [
        "XLE", "XLF", "XLK", "XLV",
        "XLI", "XLU", "XLP", "XLY"
    ],

    # Macro / volatility instruments
    "macro": ["SPY", "QQQ", "IWM", "TLT", "GLD"],

    # Crypto exposure via stock-market wrappers
    "crypto": ["IBIT", "MSTR", "COIN"],
}

# Flatten for easy iteration
CURATED_TICKERS = [t for category in UNIVERSE.values() for t in category]

# Full S&P 500 expansion — the curated list stays first (its sector labels win),
# then every S&P 500 name not already present. ~540 tickers total.
from sp500_constituents import SP500_SECTORS, SP500_TICKERS

ALL_TICKERS = CURATED_TICKERS + [t for t in SP500_TICKERS if t not in CURATED_TICKERS]

# Macro context tickers — always pulled, never traded
MACRO_CONTEXT = ["^VIX", "^TNX", "^GSPC", "DX-Y.NYB"]

# GICS -> internal sector labels, so regime/catalyst scoring applies to the
# S&P 500 expansion. Unmapped GICS sectors keep their name (scored neutral).
GICS_TO_INTERNAL = {
    "information_technology": "tech_growth",
    "communication_services": "tech_mega",
    "consumer_discretionary": "consumer",
    "consumer_staples": "consumer",
    "financials": "financials",
    "energy": "energy",
    "health_care": "healthcare",
}

# Sector mapping for downgrade logic and rotation analysis.
# GICS sectors for the S&P 500 expansion; curated labels override below.
SECTOR_MAP = {
    **{t: GICS_TO_INTERNAL.get(s, s) for t, s in SP500_SECTORS.items()},
    **{t: "tech_mega" for t in UNIVERSE["mega_cap"][:7]},
    **{t: "healthcare" for t in ["LLY"]},
    **{t: "consumer" for t in ["COST", "AMZN"]},
    **{t: "tech_growth" for t in UNIVERSE["growth_momentum"]},
    **{t: "financials" for t in UNIVERSE["financials"]},
    **{t: "energy" for t in UNIVERSE["energy"]},
    **{t: "defense" for t in UNIVERSE["defense"]},
    **{t: "etf_sector" for t in UNIVERSE["sector_etfs"]},
    **{t: "etf_macro" for t in UNIVERSE["macro"]},
    **{t: "crypto" for t in UNIVERSE["crypto"]},
}

if __name__ == "__main__":
    print(f"Universe size: {len(ALL_TICKERS)} tickers")
    print(f"Macro context: {len(MACRO_CONTEXT)} indicators")
    for category, tickers in UNIVERSE.items():
        print(f"  {category}: {len(tickers)} — {', '.join(tickers)}")
