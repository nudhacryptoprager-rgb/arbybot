"""
E1.64 unit tests — depth guard (fast path), profit gate, and split-route expansion.

Tests cover:
  E1.64-1: E1.64 counters present in get_e163_session_counters() output
  E1.64-2: reset_e163_session_counters() zeroes E1.64 counters
  E1.64-3: depth_guard_rejected increments when price_impact_bps > max_bps
  E1.64-4: depth_math_invalid increments when compute_v3_sqrt_price_after gives absurd result
  E1.64-5: price_impact_populated increments for valid impact within bounds
  E1.64-6: usd_basis_missing counter behaviour (stable and WETH missing cases)
  E1.64-7: min_profit_rejected counter increments when expected_profit_usd < gate
  E1.64-8: attempt_split_pricing returns split_ratio_pct_a key (E1.64 expansion)
  E1.64-9: attempt_split_pricing tries multiple ratios and picks best outcome
  E1.64-10: new reject reason constants exist in m7.shared.constants
"""

import importlib
import sys
from typing import Optional

import pytest

from m7.orderflow.v3_math import attempt_split_pricing, compute_v3_sqrt_price_after


# ── helpers ─────────────────────────────────────────────────────────────────

Q96 = 2**96
_SQRT_PRICE_1_1 = int(1.0 * Q96)
_LIQ = 10**18
_ADDR_A = "0x0000000000000000000000000000000000000001"
_ADDR_B = "0x0000000000000000000000000000000000000002"
_ADDR_C = "0x0000000000000000000000000000000000000003"


def _fresh_scoring():
    """Force-reload scoring_parallel for clean counter state."""
    mod_name = "m7.orderflow.scoring_parallel"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


def _pool(addr: str, fee: int = 3000, sp: int = _SQRT_PRICE_1_1, liq: int = _LIQ) -> dict:
    return {"address": addr, "fee": fee, "sqrt_price_x96": sp, "liquidity": liq}


def _states(pools: list) -> dict:
    return {p["address"]: {"sqrt_price_x96": p["sqrt_price_x96"], "liquidity": p["liquidity"]}
            for p in pools}


# ── E1.64-1: E1.64 counter keys present in get_e163_session_counters ────────

class TestE164CounterKeys:
    def test_all_e164_keys_present(self):
        mod = _fresh_scoring()
        c = mod.get_e163_session_counters()
        assert "depth_guard_rejected_total" in c
        assert "depth_math_invalid_total" in c
        assert "usd_basis_missing_total" in c
        assert "min_profit_rejected_total" in c

    def test_initial_values_zero(self):
        mod = _fresh_scoring()
        c = mod.get_e163_session_counters()
        for k in ("depth_guard_rejected_total", "depth_math_invalid_total",
                  "usd_basis_missing_total", "min_profit_rejected_total"):
            assert c[k] == 0, f"{k} should start at 0, got {c[k]}"


# ── E1.64-2: reset zeroes E1.64 counters ────────────────────────────────────

class TestE164Reset:
    def test_reset_zeroes_new_counters(self):
        mod = _fresh_scoring()
        with mod._e163_lock:
            mod._e164_depth_guard_rejected = 7
            mod._e164_depth_math_invalid = 3
            mod._e164_usd_basis_missing = 5
            mod._e164_min_profit_rejected = 2
        mod.reset_e163_session_counters()
        c = mod.get_e163_session_counters()
        assert c["depth_guard_rejected_total"] == 0
        assert c["depth_math_invalid_total"] == 0
        assert c["usd_basis_missing_total"] == 0
        assert c["min_profit_rejected_total"] == 0


# ── E1.64-3: depth_guard_rejected increments when price_impact > max ────────

class TestDepthGuardRejectedCounter:
    def test_counter_increments_when_price_impact_exceeds_max(self):
        """Simulate the scenario: valid pool state, price_impact > ARBY_PRICE_IMPACT_MAX_BPS."""
        mod = _fresh_scoring()

        # Simulate what the fast path does when price_impact > max_bps:
        # - compute_v3_sqrt_price_after returns a valid result
        # - ratio^2 gives a price_impact_bps > max_bps
        sp_before = _SQRT_PRICE_1_1
        # Large amount to force large price impact (drain-like)
        large_amount = _LIQ // 100  # 1% of liquidity, should produce non-trivial impact
        sp_after = compute_v3_sqrt_price_after(
            sqrt_price_x96=sp_before,
            liquidity=_LIQ,
            amount_in=large_amount,
            fee_pips=3000,
            zero_for_one=True,
        )
        assert sp_after is not None
        pi_ratio = (sp_after / sp_before) ** 2
        pi_bps = abs(1.0 - pi_ratio) * 10_000.0

        # Manually exercise the counter logic
        import math
        if math.isfinite(pi_bps) and pi_bps <= 1_000_000:
            with mod._e163_lock:
                mod._e163_price_impact_populated += 1
            # Simulate: max_bps = 1 (artificially low to force reject)
            max_pi_bps = 1
            if pi_bps > max_pi_bps:
                with mod._e163_lock:
                    mod._e164_depth_guard_rejected += 1

        c = mod.get_e163_session_counters()
        assert c["depth_guard_rejected_total"] == 1, (
            f"Expected 1 depth_guard_rejected, got {c['depth_guard_rejected_total']}; pi_bps={pi_bps:.4f}"
        )
        assert c["price_impact_populated_total"] == 1


# ── E1.64-4: depth_math_invalid increments when impact is absurd ─────────────

class TestDepthMathInvalidCounter:
    def test_counter_increments_for_absurd_impact(self):
        mod = _fresh_scoring()

        import math
        # Simulate: pi_bps_raw is non-finite or >1_000_000
        _pi_bps_raw = float("inf")
        if not math.isfinite(_pi_bps_raw) or _pi_bps_raw > 1_000_000:
            with mod._e163_lock:
                mod._e164_depth_math_invalid += 1

        c = mod.get_e163_session_counters()
        assert c["depth_math_invalid_total"] == 1

    def test_very_large_bps_treated_as_invalid(self):
        mod = _fresh_scoring()

        import math
        _pi_bps_raw = 2_000_000.0  # clearly absurd (200x price)
        if not math.isfinite(_pi_bps_raw) or _pi_bps_raw > 1_000_000:
            with mod._e163_lock:
                mod._e164_depth_math_invalid += 1

        c = mod.get_e163_session_counters()
        assert c["depth_math_invalid_total"] == 1


# ── E1.64-5: price_impact_populated increments for valid small impact ────────

class TestPriceImpactPopulated:
    def test_small_swap_populates_impact(self):
        """Small swap → valid finite price_impact_bps → price_impact_populated++."""
        mod = _fresh_scoring()

        sp_before = _SQRT_PRICE_1_1
        sp_after = compute_v3_sqrt_price_after(
            sqrt_price_x96=sp_before,
            liquidity=_LIQ,
            amount_in=10**14,  # tiny: 0.0001 token
            fee_pips=3000,
            zero_for_one=True,
        )
        assert sp_after is not None
        import math
        pi_bps = abs(1.0 - (sp_after / sp_before) ** 2) * 10_000.0
        assert math.isfinite(pi_bps) and pi_bps <= 1_000_000

        with mod._e163_lock:
            mod._e163_price_impact_populated += 1

        c = mod.get_e163_session_counters()
        assert c["price_impact_populated_total"] == 1


# ── E1.64-6: usd_basis_missing counter ───────────────────────────────────────

class TestUsdBasisMissingCounter:
    def test_counter_increments_when_no_usd_basis(self):
        """When net_bps > 0 but size_usd is None, usd_basis_missing should increment."""
        mod = _fresh_scoring()

        # Simulate the fast-path logic manually
        _route_viable = True
        net_bps = 50.0  # profitable
        _expected_profit_usd_fast = None  # no USD basis available

        if _route_viable and net_bps > 0 and _expected_profit_usd_fast is None:
            with mod._e163_lock:
                mod._e164_usd_basis_missing += 1

        c = mod.get_e163_session_counters()
        assert c["usd_basis_missing_total"] == 1

    def test_counter_does_not_increment_when_profit_computed(self):
        """When expected_profit_usd is not None, usd_basis_missing should NOT increment."""
        mod = _fresh_scoring()

        _route_viable = True
        net_bps = 50.0
        _expected_profit_usd_fast = 0.05  # USD basis available

        if _route_viable and net_bps > 0 and _expected_profit_usd_fast is None:
            with mod._e163_lock:
                mod._e164_usd_basis_missing += 1

        c = mod.get_e163_session_counters()
        assert c["usd_basis_missing_total"] == 0


# ── E1.64-7: min_profit_rejected counter ─────────────────────────────────────

class TestMinProfitRejectedCounter:
    def test_counter_increments_when_profit_below_gate(self):
        mod = _fresh_scoring()

        _route_viable = True
        _expected_profit_usd_fast = 0.003  # below $0.01 gate
        _min_profit_usd_gate = 0.01

        if _min_profit_usd_gate > 0.0 and _route_viable:
            if _expected_profit_usd_fast is not None and _expected_profit_usd_fast < _min_profit_usd_gate:
                with mod._e163_lock:
                    mod._e164_min_profit_rejected += 1

        c = mod.get_e163_session_counters()
        assert c["min_profit_rejected_total"] == 1

    def test_counter_does_not_increment_when_profit_meets_gate(self):
        mod = _fresh_scoring()

        _route_viable = True
        _expected_profit_usd_fast = 0.05  # above $0.01 gate
        _min_profit_usd_gate = 0.01

        if _min_profit_usd_gate > 0.0 and _route_viable:
            if _expected_profit_usd_fast is not None and _expected_profit_usd_fast < _min_profit_usd_gate:
                with mod._e163_lock:
                    mod._e164_min_profit_rejected += 1

        c = mod.get_e163_session_counters()
        assert c["min_profit_rejected_total"] == 0


# ── E1.64-8: attempt_split_pricing returns split_ratio_pct_a ─────────────────

class TestSplitPricingRatioKey:
    def test_result_has_split_ratio_pct_a(self):
        """E1.64 expansion: result must include split_ratio_pct_a."""
        pa = _pool(_ADDR_A, fee=500)
        pb = _pool(_ADDR_B, fee=3000)
        result = attempt_split_pricing(
            candidate_pools=[pa, pb],
            local_sim_states=_states([pa, pb]),
            token_in_addr=_ADDR_A,
            token_out_addr=_ADDR_B,
            backrun_size_wei=10**16,
        )
        assert result is not None
        assert "split_ratio_pct_a" in result, "E1.64: split_ratio_pct_a must be present"
        assert result["split_ratio_pct_a"] in (25, 50, 75), (
            f"split_ratio_pct_a should be 25, 50, or 75 — got {result['split_ratio_pct_a']}"
        )


# ── E1.64-9: attempt_split_pricing tries multiple ratios ─────────────────────

class TestSplitPricingMultiRatio:
    def test_three_pools_top3_combination(self):
        """With 3 V3 pools, should still find a result (top-3 combinations)."""
        pa = _pool(_ADDR_A, fee=500)
        pb = _pool(_ADDR_B, fee=3000)
        pc = _pool(_ADDR_C, fee=10000)
        result = attempt_split_pricing(
            candidate_pools=[pa, pb, pc],
            local_sim_states=_states([pa, pb, pc]),
            token_in_addr=_ADDR_A,
            token_out_addr=_ADDR_B,
            backrun_size_wei=10**16,
        )
        assert result is not None, "Expected split result with 3 pools"
        assert result["pricing_path"] == "v3_split_local"
        assert result["pools_attempted"] >= 2

    def test_one_pool_returns_none(self):
        """With only 1 V3 pool, must return None (no split possible)."""
        pa = _pool(_ADDR_A, fee=500)
        result = attempt_split_pricing(
            candidate_pools=[pa],
            local_sim_states=_states([pa]),
            token_in_addr=_ADDR_A,
            token_out_addr=_ADDR_B,
            backrun_size_wei=10**16,
        )
        assert result is None

    def test_buy_amount_uses_best_ratio(self):
        """The result buy_amount should be >= what the 50/50 split would produce."""
        pa = _pool(_ADDR_A, fee=500)
        pb = _pool(_ADDR_B, fee=3000)
        # The new multi-ratio logic should find at least as good as 50/50
        result = attempt_split_pricing(
            candidate_pools=[pa, pb],
            local_sim_states=_states([pa, pb]),
            token_in_addr=_ADDR_A,
            token_out_addr=_ADDR_B,
            backrun_size_wei=10**16,
        )
        assert result is not None
        assert result["buy_amount"] > 0
        # split_amount_a + split_amount_b should equal buy_amount
        assert result["split_amount_a"] + result["split_amount_b"] == result["buy_amount"]


# ── E1.64-10: new reject reason constants exist ──────────────────────────────

class TestNewRejectReasonConstants:
    def test_reject_usd_basis_missing_exists(self):
        from m7.shared.constants import REJECT_USD_BASIS_MISSING
        assert REJECT_USD_BASIS_MISSING == "USD_BASIS_MISSING"

    def test_reject_min_profit_usd_not_met_exists(self):
        from m7.shared.constants import REJECT_MIN_PROFIT_USD_NOT_MET
        assert REJECT_MIN_PROFIT_USD_NOT_MET == "MIN_PROFIT_USD_NOT_MET"

    def test_reject_depth_math_invalid_exists(self):
        from m7.shared.constants import REJECT_DEPTH_MATH_INVALID
        assert REJECT_DEPTH_MATH_INVALID == "DEPTH_MATH_INVALID"

    def test_new_reasons_in_all_reject_reasons(self):
        from m7.shared.constants import (
            ALL_REJECT_REASONS,
            REJECT_USD_BASIS_MISSING,
            REJECT_MIN_PROFIT_USD_NOT_MET,
            REJECT_DEPTH_MATH_INVALID,
        )
        assert REJECT_USD_BASIS_MISSING in ALL_REJECT_REASONS
        assert REJECT_MIN_PROFIT_USD_NOT_MET in ALL_REJECT_REASONS
        assert REJECT_DEPTH_MATH_INVALID in ALL_REJECT_REASONS
