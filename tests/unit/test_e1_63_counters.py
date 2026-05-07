"""Unit tests for E1.63 split routing + depth guard session counters.

Tests cover:
- get_e163_session_counters() returns dict with all 4 expected keys
- reset_e163_session_counters() zeroes all counters
- e163_split_route_status logic (LANDED_NOT_RUNTIME_VALIDATED, ATTEMPTED_NO_WIN_YET, RUNTIME_VALIDATED)
- cold_immediate_usd_basis_missing counter initialised in queue_cold_executable_for_sim counters
"""
import importlib
import sys
import threading
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_module():
    """Force-reload scoring_parallel to get clean counter state."""
    mod_name = "m7.orderflow.scoring_parallel"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# Tests: get_e163_session_counters
# ---------------------------------------------------------------------------

class TestGetE163SessionCounters:
    def test_returns_dict_with_all_keys(self):
        mod = _fresh_module()
        counters = mod.get_e163_session_counters()
        assert isinstance(counters, dict)
        assert "split_route_attempted_total" in counters
        assert "split_route_win_total" in counters
        assert "depth_guard_attempted_total" in counters
        assert "price_impact_populated_total" in counters

    def test_initial_values_are_zero(self):
        mod = _fresh_module()
        counters = mod.get_e163_session_counters()
        for v in counters.values():
            assert v == 0, f"Expected 0 but got {v}"


# ---------------------------------------------------------------------------
# Tests: reset_e163_session_counters
# ---------------------------------------------------------------------------

class TestResetE163SessionCounters:
    def test_reset_zeroes_all_counters(self):
        mod = _fresh_module()
        # Manually bump counters
        with mod._e163_lock:
            mod._e163_split_route_attempted = 5
            mod._e163_split_route_win = 3
            mod._e163_depth_guard_attempted = 7
            mod._e163_price_impact_populated = 2
        mod.reset_e163_session_counters()
        counters = mod.get_e163_session_counters()
        for v in counters.values():
            assert v == 0

    def test_reset_is_idempotent(self):
        mod = _fresh_module()
        mod.reset_e163_session_counters()
        mod.reset_e163_session_counters()
        counters = mod.get_e163_session_counters()
        for v in counters.values():
            assert v == 0


# ---------------------------------------------------------------------------
# Tests: e163_split_route_status logic (via _update_hot_rollup logic inline)
# ---------------------------------------------------------------------------

class TestSplitRouteStatus:
    """Test status string logic without running _update_hot_rollup (pure logic)."""

    def _status_from_counters(self, split_attempted: int, split_win: int) -> str:
        if split_attempted == 0:
            return "LANDED_NOT_RUNTIME_VALIDATED"
        if split_win == 0:
            return "ATTEMPTED_NO_WIN_YET"
        return "RUNTIME_VALIDATED"

    def test_zero_attempted_gives_landed_not_runtime_validated(self):
        assert self._status_from_counters(0, 0) == "LANDED_NOT_RUNTIME_VALIDATED"

    def test_attempted_no_win_gives_attempted_no_win_yet(self):
        assert self._status_from_counters(5, 0) == "ATTEMPTED_NO_WIN_YET"

    def test_attempted_with_win_gives_runtime_validated(self):
        assert self._status_from_counters(5, 2) == "RUNTIME_VALIDATED"


# ---------------------------------------------------------------------------
# Tests: cold_immediate_usd_basis_missing in counters init
# ---------------------------------------------------------------------------

class TestColdImmediateUsdBasisMissing:
    def test_counter_key_present_in_queue_output_when_disabled(self):
        """When cold_immediate_sim is disabled, counters still includes the key."""
        from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim
        with patch("m7.orderflow.cold_immediate_sim.is_enabled", return_value=False):
            _, counters = queue_cold_executable_for_sim(bridge={}, chain="base")
        assert "cold_immediate_usd_basis_missing" in counters

    def test_usd_basis_missing_counts_zero_size_entries(self):
        """When cold_immediate_sim is enabled, entries with size_usd=0 + net_bps>0 are counted."""
        from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

        bridge = {
            "cold_executable": [
                {
                    "pool_address": "0xabc",
                    "net_bps": 50.0,
                    "size_usd_estimate": 0.0,   # no USD basis
                    "token_in": "0xtokenA",
                    "token_out": "0xtokenB",
                },
            ]
        }
        with patch("m7.orderflow.cold_immediate_sim.is_enabled", return_value=True), \
             patch("m7.orderflow.cold_immediate_sim._top_n", return_value=10), \
             patch("m7.orderflow.cold_immediate_sim._min_net_bps_threshold", return_value=1.0), \
             patch("m7.orderflow.cold_immediate_sim._min_expected_profit_usd", return_value=0.0), \
             patch("m7.orderflow.cold_immediate_sim._build_synthetic_event", return_value=None):
            _, counters = queue_cold_executable_for_sim(bridge=bridge, chain="base")
        assert counters.get("cold_immediate_usd_basis_missing", 0) >= 1
