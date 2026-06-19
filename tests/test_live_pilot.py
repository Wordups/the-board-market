"""Safety-invariant tests for the live execution pilot.

These never touch a real broker — a fake client records calls. They lock down the
three things that protect real capital: the kill switch, the $100 cap, and that
dry-run sends nothing.
"""

import pytest

from profiles import live_pilot
from connectors import schwab


BOARD = {
    "as_of": "2026-06-18",
    "setups": [
        {"ticker": "ARM", "tier": "LIVE", "score": 74, "price": 40.0},
        {"ticker": "CHEAP", "tier": "LIVE", "score": 73, "price": 15.0},
        {"ticker": "EXPENSIVE", "tier": "LIVE", "score": 72, "price": 200.0},
        {"ticker": "BENCHX", "tier": "BENCH", "score": 50, "price": 5.0},
    ],
}


class FakeClient:
    def __init__(self):
        self.orders = []

    def place_order(self, account_hash, order):
        self.orders.append(order)
        return {"order_id": f"ord-{len(self.orders)}", "status": 201}


@pytest.fixture
def live_env(tmp_path, monkeypatch):
    monkeypatch.setattr(live_pilot, "_board", lambda: BOARD)
    monkeypatch.setattr(live_pilot, "STATE_PATH", tmp_path / "live_pilot.json")
    monkeypatch.setattr(schwab, "load_tokens", lambda: None)  # don't read real token file
    monkeypatch.setenv("LIVE_CAPITAL_CAP", "100")
    monkeypatch.setenv("SCHWAB_ACCOUNT_HASH", "TESTHASH")
    yield monkeypatch


def test_kill_switch_blocks_real_orders(live_env):
    live_env.delenv("LIVE_TRADING_ENABLED", raising=False)
    client = FakeClient()
    with pytest.raises(RuntimeError, match="LIVE_TRADING_ENABLED"):
        live_pilot.run_live_cycle(client=client, dry_run=False)
    assert client.orders == []  # nothing was sent


def test_capital_cap_is_never_exceeded(live_env):
    live_env.setenv("LIVE_TRADING_ENABLED", "true")
    client = FakeClient()
    state = live_pilot.run_live_cycle(client=client, dry_run=False)

    # Best-affordable across ALL tiers, ranked by score, never exceeding the cap:
    #   ARM(74) floor(100/40)=2 -> $80 ; CHEAP(73) floor(20/15)=1 -> $15 ($95) ;
    #   EXPENSIVE(72) $200 unaffordable -> skip ; BENCHX(50) floor(5/5)=1 -> $5 ($100).
    tickers = {p["ticker"]: p for p in state["positions"]}
    assert set(tickers) == {"ARM", "CHEAP", "BENCHX"}
    assert tickers["ARM"]["qty"] == 2
    assert tickers["CHEAP"]["qty"] == 1
    assert tickers["BENCHX"]["qty"] == 1
    assert state["deployed"] == 100.0  # exactly at the cap, never over
    assert state["deployed"] <= live_pilot.capital_cap()
    assert "EXPENSIVE" not in tickers  # unaffordable high-score name skipped
    # 3 entries -> 3 buys + 3 protective stops
    assert len(client.orders) == 6


def test_min_score_floor_excludes_low_scores(live_env):
    live_env.setenv("LIVE_TRADING_ENABLED", "true")
    live_env.setenv("LIVE_MIN_SCORE", "70")  # exclude BENCHX(50)
    client = FakeClient()
    state = live_pilot.run_live_cycle(client=client, dry_run=False)
    tickers = {p["ticker"] for p in state["positions"]}
    assert "BENCHX" not in tickers  # below the score floor
    assert tickers == {"ARM", "CHEAP"}


def test_dry_run_sends_no_orders(live_env):
    live_env.setenv("LIVE_TRADING_ENABLED", "true")
    client = FakeClient()
    state = live_pilot.run_live_cycle(client=client, dry_run=True)
    assert client.orders == []  # planned only
    assert state["last_run_dry"] is True
    assert state["deployed"] <= live_pilot.capital_cap()
    # state file should NOT be written on a dry run
    assert not live_pilot.STATE_PATH.exists()


def test_place_order_connector_gate(monkeypatch):
    """Even bypassing the engine, the connector refuses orders when the kill
    switch is off."""
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)

    class _Resp:
        headers = {"location": "/x/1"}
        status_code = 201

        def raise_for_status(self):
            pass

    client = schwab.SchwabClient.__new__(schwab.SchwabClient)  # skip __init__/httpx
    with pytest.raises(schwab.SchwabAuthError, match="disabled"):
        client.place_order("acct", {"orderType": "MARKET"})
