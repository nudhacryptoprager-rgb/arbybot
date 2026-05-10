"""E1.80 — try_promote_from_cold_signal: dynamic cold→hot promotion."""
from __future__ import annotations

import pytest

import m7.orderflow.disc_to_prod_pool_promotion as pp


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    pp.reset()
    monkeypatch.setenv("ARBY_POOL_PROMOTION", "1")
    monkeypatch.delenv("ARBY_POOL_PROMOTION_AUTO_BPS", raising=False)
    yield
    pp.reset()


def test_promotes_when_above_default_threshold():
    rec = pp.try_promote_from_cold_signal(
        pool="0xPool1", net_bps=25.0, pair="cbXRP/WETH", chain="base", now=100.0
    )
    assert rec is not None
    assert rec.last_profit_bps == pytest.approx(25.0)
    assert rec.observed_in_session == "cold_signal_auto"
    assert len(pp.active_promotions(now=100.0)) == 1


def test_skips_below_threshold():
    rec = pp.try_promote_from_cold_signal(
        pool="0xPool2", net_bps=10.0, pair="X/Y", chain="base", now=100.0
    )
    assert rec is None
    assert pp.active_promotions(now=100.0) == []


def test_custom_threshold_via_env(monkeypatch):
    monkeypatch.setenv("ARBY_POOL_PROMOTION_AUTO_BPS", "50")
    # 30 bps now below custom threshold of 50
    assert pp.try_promote_from_cold_signal(pool="0xPool3", net_bps=30.0, now=100.0) is None
    # 60 bps above threshold
    assert pp.try_promote_from_cold_signal(pool="0xPool4", net_bps=60.0, now=100.0) is not None


def test_skips_when_feature_off(monkeypatch):
    monkeypatch.setenv("ARBY_POOL_PROMOTION", "0")
    assert pp.try_promote_from_cold_signal(pool="0xPool5", net_bps=999.0) is None


def test_skips_on_missing_pool_or_bps():
    assert pp.try_promote_from_cold_signal(pool="", net_bps=100.0) is None
    assert pp.try_promote_from_cold_signal(pool="0xP", net_bps=None) is None


def test_handles_invalid_net_bps_types():
    assert pp.try_promote_from_cold_signal(pool="0xP", net_bps="not_a_number") is None  # type: ignore[arg-type]
    assert pp.try_promote_from_cold_signal(pool="0xP", net_bps=float("nan")) is None
