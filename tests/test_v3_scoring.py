"""v3 scoring upgrades: smart money fallback, listing cap, reject_zone,
profit outlook EV math, and the report-only parlay ladder.

All network surfaces (SEC EDGAR, yfinance earnings feed) are isolated by
pointing the module cache files at empty temp paths or passing explicit
earnings_dates — no test ever performs I/O beyond the temp dir.
"""

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

ENGINE_DIR = Path(__file__).resolve().parents[1] / "engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import parlay  # noqa: E402
import score  # noqa: E402
from calendars import earnings as earnings_mod  # noqa: E402
from signals import insider  # noqa: E402


AS_OF_D = date(2026, 7, 17)


def make_df(closes, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=len(closes))
    closes = [float(c) for c in closes]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
            "Volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


@pytest.fixture
def offline_caches(tmp_path, monkeypatch):
    """No insider cache, no earnings cache — the network-degraded run."""
    monkeypatch.setattr(insider, "CACHE_FILE", tmp_path / "no_insider.json")
    monkeypatch.setattr(earnings_mod, "CACHE_FILE", tmp_path / "no_earnings.json")


def seed_insider_cache(tmp_path, monkeypatch, entry, ticker="AAPL"):
    cache_file = tmp_path / "insider_filings.json"
    import json

    cache_file.write_text(json.dumps({ticker: entry, "_fetched_at": "2026-07-17T00:00:00"}))
    monkeypatch.setattr(insider, "CACHE_FILE", cache_file)


# ─────────────────── Smart Money ───────────────────

class TestSmartMoney:
    def test_neutral_fallback_when_cache_missing(self, offline_caches):
        sm, notes = insider.smart_money_signal("AAPL", AS_OF_D)
        assert sm == 7.0
        assert "SMART_MONEY_UNAVAILABLE" in notes

    def test_neutral_fallback_when_fetch_failed(self, tmp_path, monkeypatch):
        seed_insider_cache(tmp_path, monkeypatch,
                           {"cik": "0000320193", "filings": [], "error": "FETCH_FAILED"})
        sm, notes = insider.smart_money_signal("AAPL", AS_OF_D)
        assert sm == 7.0
        assert "SMART_MONEY_UNAVAILABLE" in notes

    def test_score_setup_smart_money_degrades_not_zero(self, offline_caches):
        df = make_df([100.0] * 250)
        result = score.score_setup("NVDA", df, df, vix=15.0, tnx=4.0,
                                   as_of=datetime(2026, 7, 17), earnings_dates=[])
        assert result["factors"]["smart_money"] == 7.0
        assert "SMART_MONEY_UNAVAILABLE" in result["notes"]["smart_money"]

    def test_officer_cluster_buying_scores_real(self, tmp_path, monkeypatch):
        seed_insider_cache(tmp_path, monkeypatch, {
            "cik": "0000320193",
            "filings": [
                {"date": "2026-07-01", "code": "P", "value": 300_000.0,
                 "owner": "COOK TIM", "is_officer": True, "is_director": False},
                {"date": "2026-06-20", "code": "P", "value": 300_000.0,
                 "owner": "DOE JANE", "is_officer": False, "is_director": True},
            ],
        })
        sm, notes = insider.smart_money_signal("AAPL", AS_OF_D)
        # base 4 + (cluster-of-2 +6, officer/director +4) x dollar scale 1.0 = 14
        assert sm == 14.0
        assert "CLUSTER_2_BUYERS" in notes
        assert "OFFICER_DIRECTOR_BUY" in notes

    def test_net_selling_regime_caps_at_baseline_4(self, tmp_path, monkeypatch):
        seed_insider_cache(tmp_path, monkeypatch, {
            "cik": "0000320193",
            "filings": [
                {"date": "2026-07-01", "code": "S", "value": 5_000_000.0,
                 "owner": "COOK TIM", "is_officer": True, "is_director": False},
            ],
        })
        sm, _ = insider.smart_money_signal("AAPL", AS_OF_D)
        assert sm == 4.0


# ─────────────────── Listing cap ───────────────────

class TestListingCap:
    def test_short_history_capped_at_bench(self, offline_caches):
        df = make_df([100.0] * 10)
        result = score.score_setup("NVDA", df, df, vix=12.0, tnx=4.0,
                                   as_of=datetime(2026, 7, 17), earnings_dates=[])
        assert result["tier"] == "BENCH"
        assert result["listing_capped"] is True
        assert "LISTING_CAP (<25 sessions)" in result["flags"]

    def test_full_history_not_capped(self, offline_caches):
        df = make_df([100.0] * 250)
        result = score.score_setup("NVDA", df, df, vix=12.0, tnx=4.0,
                                   as_of=datetime(2026, 7, 17), earnings_dates=[])
        assert result["listing_capped"] is False
        assert "LISTING_CAP (<25 sessions)" not in result["flags"]


# ─────────────────── Entry-zone rejection ───────────────────

class TestRejectZone:
    def test_chalk_when_extended_above_ma20(self, offline_caches):
        closes = [100.0] * 249 + [150.0]  # close 150 vs MA20 ~102.5 -> chalk
        df = make_df(closes)
        result = score.score_setup("NVDA", df, df, vix=12.0, tnx=4.0,
                                   as_of=datetime(2026, 7, 17), earnings_dates=[])
        assert result["reject_zone"] == "chalk"
        assert "REJECT_ZONE_CHALK" in result["flags"]

    def test_longshot_below_ma200_stacked_bear(self):
        closes = [300.0 - i * 0.8 for i in range(250)]  # monotonic decline to 100.8
        df = make_df(closes)
        assert score.entry_reject_zone(df) == "longshot"

    def test_none_in_healthy_uptrend(self):
        closes = [100.0 + i * 0.1 for i in range(250)]  # gentle rise, near MA20
        df = make_df(closes)
        assert score.entry_reject_zone(df) is None


# ─────────────────── Profit outlook EV math ───────────────────

class TestProfitOutlook:
    def test_ev_per_100_by_tier(self):
        assert parlay.profit_outlook_for("LIVE")["ev_per_100"] == 6.4
        assert parlay.profit_outlook_for("LOCK")["ev_per_100"] == 7.6
        assert parlay.profit_outlook_for("BENCH")["ev_per_100"] == 4.0

    def test_structure(self):
        outlook = parlay.profit_outlook_for("LIVE")
        assert outlook == {"stop_pct": -8, "target_pct": 16, "rr": "2:1",
                           "ev_per_100": 6.4}


# ─────────────────── Parlay ladder ───────────────────

def setup_row(ticker, tier="LIVE", score_val=74, **extra):
    return {"ticker": ticker, "tier": tier, "score": score_val,
            "reject_zone": None, "listing_capped": False, **extra}


class TestParlayLadder:
    def test_two_leg_live_math(self):
        ladder = parlay.build_parlay_ladder([setup_row("AAA"), setup_row("BBB", score_val=73)])
        assert ladder["execution"] == "REPORT_ONLY — no parlay venue connected"
        assert len(ladder["rungs"]) == 1  # only enough names for the 2-leg rung
        rung = ladder["rungs"][0]
        assert rung["n_legs"] == 2
        assert rung["combined_prob"] == pytest.approx(0.36)
        # fair odds 100*(1-p)/p = ~+177.8 -> nearest 25 = +175 -> rung label +200
        assert rung["fair_american"] == 175
        assert rung["rung"] == "+200"

    def test_eligibility_filters(self):
        setups = [
            setup_row("GOOD1"),
            setup_row("GOOD2"),
            setup_row("LOWSC", score_val=59),                    # under the 60 floor
            setup_row("CHALK", reject_zone="chalk"),             # rejected zone
            setup_row("FRESH", listing_capped=True),             # listing-capped
        ]
        ladder = parlay.build_parlay_ladder(setups)
        assert ladder["eligible_count"] == 2
        legs = {leg["ticker"] for leg in ladder["rungs"][0]["legs"]}
        assert legs == {"GOOD1", "GOOD2"}

    def test_deterministic_ordering_and_leg_counts(self):
        setups = [setup_row(t, score_val=74) for t in ("ZZZ", "AAA", "MMM",
                                                       "BBB", "CCC", "DDD")]
        ladder = parlay.build_parlay_ladder(setups)
        assert [r["n_legs"] for r in ladder["rungs"]] == [2, 3, 4, 6]
        # equal scores tie-break alphabetically for deterministic output
        assert [leg["ticker"] for leg in ladder["rungs"][0]["legs"]] == ["AAA", "BBB"]
        assert [leg["ticker"] for leg in ladder["rungs"][3]["legs"]] == [
            "AAA", "BBB", "CCC", "DDD", "MMM", "ZZZ"]

    def test_american_odds_rounding(self):
        assert parlay.american_from_prob(0.36) == 175
        assert parlay.american_from_prob(0.60) == -150
        assert parlay.nearest_rung(175) == "+200"
        assert parlay.nearest_rung(700) == "+600"
        assert parlay.nearest_rung(6001) == "+10000"


# ─────────────────── Catalyst event layer ───────────────────

class TestCatalyst:
    def test_baseline_rescaled_to_0_8_when_no_events(self):
        df = make_df([100.0] * 250)
        cat, notes = score.catalyst_score("NVDA", datetime(2026, 7, 17),
                                          df=df, earnings_dates=[])
        # tech_mega legacy 12/15 -> 6.4/8; no events
        assert cat == pytest.approx(6.4)
        assert "SECTOR_BASE_tech_mega" in notes

    def test_post_earnings_beat_drift_window(self):
        closes = [100.0] * 245 + [106.0] * 5  # +6% reaction, then 4 drift sessions
        df = make_df(closes)
        earnings_date = df.index[-6].date()  # earnings on the last flat session
        as_of = df.index[-1].to_pydatetime()
        cat, notes = score.catalyst_score("NVDA", as_of, df=df,
                                          earnings_dates=[earnings_date])
        # base 6.4 + drift +9 (reaction in [5%, 8%)) = 15.4
        assert cat == pytest.approx(15.4)
        assert any(n.startswith("PED_DRIFT_") for n in notes)

    def test_unavailable_calendar_degrades_to_baseline(self, offline_caches):
        df = make_df([100.0] * 250)
        cat, notes = score.catalyst_score("NVDA", datetime(2026, 7, 17), df=df)
        assert cat == pytest.approx(6.4)
        assert "CATALYST_EVENTS_UNAVAILABLE" in notes
