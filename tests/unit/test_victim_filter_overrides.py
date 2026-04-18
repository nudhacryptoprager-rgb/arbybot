"""
E1.34 P1.2: Victim-filter tightening via env overrides.

Verifies:
- Defaults preserve legacy behavior (MIN_EVENT_SIZE_USD=500, impact floor 0.1 bps).
- ARBY_VICTIM_MIN_USD raises the USD floor; events below are rejected as EVENT_TOO_SMALL.
- ARBY_VICTIM_MIN_IMPACT_BPS raises the bps floor; below → INSUFFICIENT_IMPACT.
- Invalid values (non-numeric, negative) fall back cleanly to defaults.
- get_victim_min_size_usd / get_victim_min_impact_bps helpers are env-live
  (no module reload needed).
"""
from __future__ import annotations

import pytest

from m7.orderflow.contracts import OrderflowEvent
from m7.orderflow.pricing import classify_event_viability
from m7.shared.constants import (
    MIN_EVENT_SIZE_USD,
    REJECT_EVENT_TOO_SMALL,
    REJECT_INSUFFICIENT_IMPACT,
    SIGNIFICANT_IMPACT_BPS,
    get_victim_min_impact_bps,
    get_victim_min_size_usd,
)


_ENV_VARS = ("ARBY_VICTIM_MIN_USD", "ARBY_VICTIM_MIN_IMPACT_BPS")


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def _mk_event(size_usd: float, impact_bps: float) -> OrderflowEvent:
    return OrderflowEvent(
        event_id="victim-test",
        event_type="swap",
        chain="base",
        block_number=1,
        tx_hash="0xabc",
        token_in="USDC",
        token_out="WETH",
        amount_in_wei=10**6,
        amount_out_wei=10**18,
        dex="uniswap_v3",
        pool_address="0x0",
        fee_tier=500,
        estimated_size_usd=size_usd,
        estimated_impact_bps=impact_bps,
        timestamp="2026-04-17T00:00:00Z",
    )


class TestVictimSizeFloor:
    def test_default_accepts_500_usd_event(self):
        ev = _mk_event(size_usd=MIN_EVENT_SIZE_USD, impact_bps=10.0)
        assert classify_event_viability(ev) is None

    def test_default_rejects_below_500_usd(self):
        ev = _mk_event(size_usd=MIN_EVENT_SIZE_USD - 1, impact_bps=10.0)
        assert classify_event_viability(ev) == REJECT_EVENT_TOO_SMALL

    def test_env_override_raises_floor(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_USD", "10000")
        # 5k event was viable under default 500 floor, now rejected.
        ev = _mk_event(size_usd=5_000.0, impact_bps=10.0)
        assert classify_event_viability(ev) == REJECT_EVENT_TOO_SMALL
        # 10k event passes.
        ev_big = _mk_event(size_usd=10_000.0, impact_bps=10.0)
        assert classify_event_viability(ev_big) is None

    def test_env_override_lowers_floor(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_USD", "100")
        ev = _mk_event(size_usd=200.0, impact_bps=10.0)
        assert classify_event_viability(ev) is None

    def test_invalid_env_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_USD", "not_a_number")
        assert get_victim_min_size_usd() == MIN_EVENT_SIZE_USD

    def test_negative_env_value_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_USD", "-10")
        assert get_victim_min_size_usd() == MIN_EVENT_SIZE_USD


class TestVictimImpactFloor:
    def test_default_accepts_low_impact_when_large(self):
        # Legacy 0.1-bps floor applies when no env override.
        ev = _mk_event(size_usd=1_000.0, impact_bps=0.5)
        assert classify_event_viability(ev) is None

    def test_default_rejects_sub_tenth_bps(self):
        ev = _mk_event(size_usd=1_000.0, impact_bps=0.05)
        assert classify_event_viability(ev) == REJECT_INSUFFICIENT_IMPACT

    def test_env_override_tightens_impact_floor(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_IMPACT_BPS", "15")
        # 10 bps was fine under default 0.1 floor, now rejected.
        ev = _mk_event(size_usd=1_000.0, impact_bps=10.0)
        assert classify_event_viability(ev) == REJECT_INSUFFICIENT_IMPACT
        ev_ok = _mk_event(size_usd=1_000.0, impact_bps=20.0)
        assert classify_event_viability(ev_ok) is None

    def test_env_override_value_matches_default_uses_legacy_floor(self, monkeypatch):
        """Setting the env to exactly SIGNIFICANT_IMPACT_BPS keeps legacy 0.1 floor."""
        monkeypatch.setenv(
            "ARBY_VICTIM_MIN_IMPACT_BPS", str(SIGNIFICANT_IMPACT_BPS)
        )
        ev = _mk_event(size_usd=1_000.0, impact_bps=0.5)
        assert classify_event_viability(ev) is None

    def test_invalid_impact_env_falls_back(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_IMPACT_BPS", "garbage")
        assert get_victim_min_impact_bps() == SIGNIFICANT_IMPACT_BPS


class TestCombinedOverrides:
    def test_both_floors_active(self, monkeypatch):
        monkeypatch.setenv("ARBY_VICTIM_MIN_USD", "10000")
        monkeypatch.setenv("ARBY_VICTIM_MIN_IMPACT_BPS", "15")
        # Small size dominates size check first.
        ev_small = _mk_event(size_usd=5_000.0, impact_bps=20.0)
        assert classify_event_viability(ev_small) == REJECT_EVENT_TOO_SMALL
        # Big size but low impact.
        ev_flat = _mk_event(size_usd=50_000.0, impact_bps=5.0)
        assert classify_event_viability(ev_flat) == REJECT_INSUFFICIENT_IMPACT
        # Both pass.
        ev_ok = _mk_event(size_usd=50_000.0, impact_bps=20.0)
        assert classify_event_viability(ev_ok) is None
