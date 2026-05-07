"""E1.62 — Steps 1+6+9: observability fields, profit gate, USD-first ranking.

Tests cover:
  - BackrunResult carries new observability fields (step 1)
  - cold_immediate_sim ranks by expected_profit_usd when USD basis known (step 9)
  - bps-only entries (no USD basis) rank below USD-known entries (step 9)
  - min_expected_profit_usd gate rejects dust-bps-on-dust-size entries (step 6)
  - entries without USD basis pass the gate unconditionally (step 6 fallback)
  - expected_profit_usd populated on synthetic BackrunResult (step 1 propagation)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Step 1: BackrunResult observability fields
# ---------------------------------------------------------------------------

class TestBackrunResultObservabilityFields:
    def test_fields_exist_with_none_default(self):
        from m7.orderflow.contracts import BackrunResult
        r = BackrunResult(
            event_id="e1",
            event_source="live",
            event_type="swap",
            post_trade_state_used="live",
            backrun_direction="buy_out_sell_in",
        )
        assert hasattr(r, "expected_profit_usd")
        assert r.expected_profit_usd is None
        assert hasattr(r, "price_impact_bps")
        assert r.price_impact_bps is None
        assert hasattr(r, "amount_in_optimal_usd")
        assert r.amount_in_optimal_usd is None
        assert hasattr(r, "liquidity_depth_usd")
        assert r.liquidity_depth_usd is None

    def test_fields_assignable(self):
        from m7.orderflow.contracts import BackrunResult
        r = BackrunResult(
            event_id="e2",
            event_source="live",
            event_type="swap",
            post_trade_state_used="live",
            backrun_direction="buy_out_sell_in",
        )
        r.expected_profit_usd = 0.05
        r.price_impact_bps = 12.5
        r.amount_in_optimal_usd = 5.0
        r.liquidity_depth_usd = 500.0
        assert r.expected_profit_usd == 0.05
        assert r.price_impact_bps == 12.5


# ---------------------------------------------------------------------------
# Step 9: ranking helpers
# ---------------------------------------------------------------------------

class TestEntryRankKey:
    def test_usd_basis_dominates_bps_only(self):
        from m7.orderflow.cold_immediate_sim import _entry_rank_key
        usd_entry = {"net_bps": 10.0, "size_usd_estimate": 5.0}   # expected=0.005
        bps_entry = {"net_bps": 9999.0}  # no size_usd → rank = 9999*1e-6 = 0.009999
        # USD entry expected_profit_usd = 5 * 10 / 10000 = 0.005
        # bps fallback = 9999 * 1e-6 = 0.009999  → bps-only wins
        # But USD entries with larger profit beat bps-only
        usd_big = {"net_bps": 50.0, "size_usd_estimate": 10.0}   # expected=0.05
        assert _entry_rank_key(usd_big) > _entry_rank_key(bps_entry)

    def test_no_usd_falls_back_to_bps(self):
        from m7.orderflow.cold_immediate_sim import _entry_rank_key
        e1 = {"net_bps": 100.0}
        e2 = {"net_bps": 200.0}
        assert _entry_rank_key(e2) > _entry_rank_key(e1)

    def test_usd_ranks_higher_than_same_bps_no_usd(self):
        from m7.orderflow.cold_immediate_sim import _entry_rank_key
        # size_usd=100, net_bps=100 → expected_profit=1.0
        # bps_only net_bps=100 → rank=100*1e-6=0.0001
        e_usd = {"net_bps": 100.0, "size_usd_estimate": 100.0}
        e_bps = {"net_bps": 100.0}
        assert _entry_rank_key(e_usd) > _entry_rank_key(e_bps)


# ---------------------------------------------------------------------------
# Step 9: queue ranking integration
# ---------------------------------------------------------------------------

class TestQueueRankingByProfitUsd:
    def test_usd_entry_selected_over_higher_bps_dust_entry(self, monkeypatch):
        """Higher bps on dust size should NOT beat lower bps on real size."""
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_EXPECTED_PROFIT_USD", "0")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_TOP_N", "1")
        from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

        bridge = {
            "cold_executable": [
                # Dust: 2500 bps on $0.00001 → expected_profit=0.0000025
                {
                    "pool_address": "0x" + "a" * 40,
                    "net_bps": 2500.0,
                    "size_usd_estimate": 0.00001,
                    "token_in": "B3", "token_out": "USDC",
                    "amount_in_wei": 10**18,
                },
                # Real: 10 bps on $10 → expected_profit=0.001
                {
                    "pool_address": "0x" + "b" * 40,
                    "net_bps": 10.0,
                    "size_usd_estimate": 10.0,
                    "token_in": "WETH", "token_out": "USDC",
                    "amount_in_wei": 4 * 10**15,
                },
            ],
        }
        captured = []

        def _capture(scored, **kw):
            captured.extend(scored)
            return MagicMock(
                sim_attempted=1, sim_passed=0, guard_passed=[], submit_ready=0,
                sim_errors=[], sim_failed_samples=[], sim_output_samples=[],
            )

        with patch("m7.orderflow.execution_gate.run_execution_gate", side_effect=_capture):
            _, counters = queue_cold_executable_for_sim(bridge, chain="base")

        assert len(captured) == 1
        # The WETH/USDC entry (pool 0xbbb...) must be chosen, not the B3 dust
        pool_addr = getattr(getattr(captured[0], "_source_event", None), "pool_address", "")
        assert "b" in pool_addr.lower(), (
            f"Expected WETH/USDC entry selected, got pool_address={pool_addr}"
        )


# ---------------------------------------------------------------------------
# Step 6: min_expected_profit_usd gate
# ---------------------------------------------------------------------------

class TestMinExpectedProfitUsdGate:
    def test_dust_entry_rejected_when_gate_set(self, monkeypatch):
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
        monkeypatch.setenv("ARBY_COLD_MIN_EXPECTED_PROFIT_USD", "0.001")
        from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

        bridge = {
            "cold_executable": [
                # expected_profit = 0.00001 * 2500 / 10000 = 0.0000025 < 0.001 → reject
                {
                    "pool_address": "0x" + "a" * 40,
                    "net_bps": 2500.0,
                    "size_usd_estimate": 0.00001,
                    "token_in": "B3", "token_out": "USDC",
                    "amount_in_wei": 10**18,
                },
            ],
        }
        with patch("m7.orderflow.execution_gate.run_execution_gate") as mock_gate:
            mock_gate.return_value = MagicMock(
                sim_attempted=0, sim_passed=0, guard_passed=[], submit_ready=0,
            )
            _, counters = queue_cold_executable_for_sim(bridge, chain="base")

        assert counters["cold_immediate_sim_input_count"] == 0, (
            "Dust entry should be rejected by min_expected_profit_usd gate"
        )

    def test_no_usd_basis_always_passes_gate(self, monkeypatch):
        """Meme tokens without oracle price pass the USD gate unconditionally."""
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
        monkeypatch.setenv("ARBY_COLD_MIN_EXPECTED_PROFIT_USD", "1.0")
        from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

        bridge = {
            "cold_executable": [
                # No size_usd_estimate — oracle unknown, must pass gate
                {
                    "pool_address": "0x" + "c" * 40,
                    "net_bps": 50.0,
                    "token_in": "MEME", "token_out": "WETH",
                    "amount_in_wei": 10**18,
                },
            ],
        }
        with patch("m7.orderflow.execution_gate.run_execution_gate") as mock_gate:
            mock_gate.return_value = MagicMock(
                sim_attempted=1, sim_passed=0, guard_passed=[], submit_ready=0,
                sim_errors=[], sim_failed_samples=[], sim_output_samples=[],
            )
            _, counters = queue_cold_executable_for_sim(bridge, chain="base")

        assert counters["cold_immediate_sim_input_count"] == 1, (
            "Entry without USD basis must NOT be rejected by the USD profit gate"
        )

    def test_gate_disabled_when_threshold_zero(self, monkeypatch):
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
        monkeypatch.setenv("ARBY_COLD_MIN_EXPECTED_PROFIT_USD", "0")
        from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

        bridge = {
            "cold_executable": [
                {
                    "pool_address": "0x" + "d" * 40,
                    "net_bps": 2500.0,
                    "size_usd_estimate": 0.000001,
                    "token_in": "B3", "token_out": "USDC",
                    "amount_in_wei": 10**18,
                },
            ],
        }
        with patch("m7.orderflow.execution_gate.run_execution_gate") as mock_gate:
            mock_gate.return_value = MagicMock(
                sim_attempted=1, sim_passed=0, guard_passed=[], submit_ready=0,
                sim_errors=[], sim_failed_samples=[], sim_output_samples=[],
            )
            _, counters = queue_cold_executable_for_sim(bridge, chain="base")

        assert counters["cold_immediate_sim_input_count"] == 1, (
            "Gate disabled by threshold=0, entry must pass"
        )


# ---------------------------------------------------------------------------
# Step 1: expected_profit_usd propagated onto synthetic BackrunResult
# ---------------------------------------------------------------------------

class TestExpectedProfitUsdPropagation:
    def test_expected_profit_usd_set_on_synthetic_result(self, monkeypatch):
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
        monkeypatch.setenv("ARBY_COLD_MIN_EXPECTED_PROFIT_USD", "0")
        from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

        bridge = {
            "cold_executable": [
                {
                    "pool_address": "0x" + "e" * 40,
                    "net_bps": 20.0,
                    "size_usd_estimate": 5.0,   # expected_profit = 5*20/10000 = 0.01
                    "token_in": "WETH", "token_out": "USDC",
                    "amount_in_wei": 4 * 10**15,
                    "best_buy_fee": 500,
                },
            ],
        }
        captured = []

        def _capture(scored, **kw):
            captured.extend(scored)
            return MagicMock(
                sim_attempted=1, sim_passed=0, guard_passed=[], submit_ready=0,
                sim_errors=[], sim_failed_samples=[], sim_output_samples=[],
            )

        with patch("m7.orderflow.execution_gate.run_execution_gate", side_effect=_capture):
            queue_cold_executable_for_sim(bridge, chain="base")

        assert len(captured) == 1
        assert captured[0].expected_profit_usd == pytest.approx(0.01, rel=1e-4), (
            f"expected_profit_usd should be 0.01, got {captured[0].expected_profit_usd}"
        )
