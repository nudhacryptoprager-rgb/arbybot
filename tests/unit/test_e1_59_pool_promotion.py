"""E1.59 step #7: pool-level DISC->PROD promotion + TTL."""

from __future__ import annotations

import pytest

from m7.orderflow import disc_to_prod_pool_promotion as pp


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_POOL_PROMOTION", "1")
    monkeypatch.setenv("ARBY_POOL_PROMOTION_TTL_S", "600")
    pp.reset()
    yield


def test_disabled_does_not_persist(monkeypatch):
    monkeypatch.setenv("ARBY_POOL_PROMOTION", "0")
    pp.reset()
    rec = pp.observe_profitable(
        pool="0xPool", pair="TIG/WETH", profit_bps=120.0, now=100.0
    )
    assert rec.pool == "0xPool"
    assert pp.snapshot()["active_count"] == 0
    assert pp.active_promotions() == []


def test_pool_required():
    with pytest.raises(ValueError):
        pp.observe_profitable(pool="", pair="X/Y")


def test_first_observation_creates_record():
    rec = pp.observe_profitable(
        pool="0xPool",
        pair="TIG/WETH",
        router="0xRouter",
        fee_tier=3000,
        token_in="0xWETH",
        token_out="0xTIG",
        chain="base",
        profit_bps=150.0,
        session_id="sess1",
        now=100.0,
    )
    assert rec.profitable_count == 1
    assert rec.last_profit_bps == 150.0
    assert rec.observed_in_session == "sess1"
    promos = pp.active_promotions(now=100.0)
    assert len(promos) == 1
    assert promos[0].pool == "0xPool"


def test_repeat_observation_updates_existing():
    pp.observe_profitable(pool="0xPool", pair="TIG/WETH", profit_bps=100.0, now=100.0)
    rec = pp.observe_profitable(
        pool="0xPool", pair="TIG/WETH", profit_bps=200.0, now=200.0
    )
    assert rec.profitable_count == 2
    assert rec.last_profit_bps == 200.0
    assert rec.last_profitable_at == 200.0
    assert rec.first_observed_at == 100.0
    assert len(pp.active_promotions(now=200.0)) == 1


def test_ttl_expiry():
    pp.observe_profitable(pool="0xPool", pair="TIG/WETH", now=100.0)
    # Within TTL.
    assert len(pp.active_promotions(now=100.0 + 599.0)) == 1
    # Past TTL.
    assert len(pp.active_promotions(now=100.0 + 700.0)) == 0


def test_ttl_env_override(monkeypatch):
    monkeypatch.setenv("ARBY_POOL_PROMOTION_TTL_S", "60")
    pp.reset()
    pp.observe_profitable(pool="0xPool", now=100.0)
    assert len(pp.active_promotions(now=100.0 + 30.0)) == 1
    assert len(pp.active_promotions(now=100.0 + 90.0)) == 0


def test_pool_address_case_insensitive():
    pp.observe_profitable(pool="0xABCDEF", now=100.0)
    pp.observe_profitable(pool="0xabcdef", now=110.0)
    promos = pp.active_promotions(now=110.0)
    assert len(promos) == 1
    assert promos[0].profitable_count == 2


def test_snapshot_payload():
    pp.observe_profitable(pool="0xP1", pair="A/B", router="0xR", profit_bps=100.0, now=100.0)
    pp.observe_profitable(pool="0xP2", pair="C/D", router="0xR", profit_bps=200.0, now=110.0)
    pp.observe_profitable(pool="0xP1", pair="A/B", router="0xR", profit_bps=120.0, now=120.0)
    snap = pp.snapshot(now=120.0)
    assert snap["active_count"] == 2
    assert snap["pairs_unique_count"] == 2
    assert snap["routers_unique_count"] == 1
    assert snap["ttl_s"] == 600
    pools = [p["pool"] for p in snap["promotions"]]
    # Most recent first.
    assert pools[0] == "0xP1"


def test_disabled_snapshot_empty(monkeypatch):
    monkeypatch.setenv("ARBY_POOL_PROMOTION", "0")
    pp.reset()
    pp.observe_profitable(pool="0xP", now=100.0)
    snap = pp.snapshot()
    assert snap["active_count"] == 0
    assert snap["promotions"] == []


def test_reset_clears():
    pp.observe_profitable(pool="0xP", now=100.0)
    pp.reset()
    assert pp.active_promotions() == []


def test_routing_identity_refreshed():
    pp.observe_profitable(pool="0xP", pair=None, router=None, fee_tier=None, now=100.0)
    pp.observe_profitable(
        pool="0xP", pair="X/Y", router="0xR", fee_tier=500, token_in="0xA", token_out="0xB",
        now=110.0,
    )
    promos = pp.active_promotions(now=110.0)
    assert promos[0].pair == "X/Y"
    assert promos[0].router == "0xR"
    assert promos[0].fee_tier == 500
    assert promos[0].token_in == "0xA"
    assert promos[0].token_out == "0xB"
