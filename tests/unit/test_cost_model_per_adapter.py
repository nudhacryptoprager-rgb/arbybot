"""Unit tests for per-adapter cost model (m9/graph_arb/cost_model.py).

Verifies:
  - All known adapter types are in _ADAPTER_COST_BPS
  - adapter_cost_bps() returns correct values and has a default fallback
  - cycle_cost_bps() sums costs across multiple adapters
  - cycle_net_bps() = gross - cycle_cost
  - adapter_family() maps adapter types to family groups
  - build_cost_breakdown() with mock cycle_results produces correct structure
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from m9.graph_arb.cost_model import (
    _ADAPTER_COST_BPS,
    adapter_cost_bps,
    adapter_family,
    adapter_pricing_model,
    build_cost_breakdown,
    cycle_cost_bps,
    cycle_net_bps,
)


class TestAdapterCostBpsMap:
    """Verify the known adapter registry is complete."""

    EXPECTED_TYPES = [
        "ve33_volatile",
        "ve33_stable",
        "curve_stable",
        "uniswap_v3",
        "uniswap_v2",
        "balancer_weighted",
        "balancer_stable",
        "balancer_vault",
        "aerodrome_slipstream",
        "uniswap_v4_nohook",
        "uniswap_v4_hook",
        "maverick_v2",
        "dodo_pmm",
        "rfq",
    ]

    def test_known_adapters_present(self):
        for adapter_type in self.EXPECTED_TYPES:
            assert adapter_type in _ADAPTER_COST_BPS, (
                f"Missing adapter_type {adapter_type!r} in _ADAPTER_COST_BPS"
            )

    def test_all_costs_positive(self):
        for name, cost in _ADAPTER_COST_BPS.items():
            assert cost > 0, f"{name} has non-positive cost {cost}"

    def test_stable_cheaper_than_volatile(self):
        """Stable curve adapters should have lower cost than volatile ones."""
        assert _ADAPTER_COST_BPS["ve33_stable"] < _ADAPTER_COST_BPS["ve33_volatile"], (
            "ve33_stable should cost less than ve33_volatile"
        )
        assert _ADAPTER_COST_BPS["curve_stable"] <= _ADAPTER_COST_BPS["ve33_stable"], (
            "curve_stable should cost <= ve33_stable"
        )


class TestAdapterCostBps:
    """adapter_cost_bps() function tests."""

    def test_known_adapter_ve33_volatile(self):
        cost = adapter_cost_bps("ve33_volatile")
        assert cost == _ADAPTER_COST_BPS["ve33_volatile"]

    def test_known_adapter_ve33_stable(self):
        cost = adapter_cost_bps("ve33_stable")
        assert cost == _ADAPTER_COST_BPS["ve33_stable"]

    def test_known_adapter_curve_stable(self):
        cost = adapter_cost_bps("curve_stable")
        assert cost == _ADAPTER_COST_BPS["curve_stable"]

    def test_unknown_adapter_uses_default(self):
        """Unknown adapter types must fall back to a default, not raise."""
        cost = adapter_cost_bps("some_unknown_adapter_xyz")
        assert isinstance(cost, (int, float))
        assert cost > 0

    def test_empty_string_uses_default(self):
        cost = adapter_cost_bps("")
        assert isinstance(cost, (int, float))
        assert cost > 0


class TestCycleCostBps:
    """cycle_cost_bps() sums adapter costs for a multi-leg cycle."""

    def test_single_adapter(self):
        result = cycle_cost_bps(["ve33_stable"])
        assert result == _ADAPTER_COST_BPS["ve33_stable"]

    def test_two_adapters(self):
        expected = _ADAPTER_COST_BPS["ve33_stable"] + _ADAPTER_COST_BPS["uniswap_v3"]
        result = cycle_cost_bps(["ve33_stable", "uniswap_v3"])
        assert abs(result - expected) < 0.001

    def test_empty_list_returns_zero(self):
        result = cycle_cost_bps([])
        assert result == 0

    def test_mixed_known_unknown(self):
        """Unknown adapter does not raise — uses default."""
        result = cycle_cost_bps(["ve33_stable", "unknown_adapter"])
        assert isinstance(result, (int, float))
        assert result > 0


class TestCycleNetBps:
    """cycle_net_bps() = gross - cycle_cost."""

    def test_positive_net(self):
        # gross 20 bps - cost 4 bps (ve33_stable) = 16 bps
        net = cycle_net_bps(20.0, ["ve33_stable"])
        expected_cost = _ADAPTER_COST_BPS["ve33_stable"]
        assert abs(net - (20.0 - expected_cost)) < 0.001

    def test_negative_net(self):
        # gross 2 bps - cost 12 bps (ve33_volatile) = -10 bps
        net = cycle_net_bps(2.0, ["ve33_volatile"])
        expected_cost = _ADAPTER_COST_BPS["ve33_volatile"]
        assert net < 0
        assert abs(net - (2.0 - expected_cost)) < 0.001

    def test_zero_gross(self):
        net = cycle_net_bps(0.0, ["ve33_stable"])
        assert net < 0

    def test_empty_adapter_list(self):
        net = cycle_net_bps(5.0, [])
        assert abs(net - 5.0) < 0.001  # no cost deducted


class TestAdapterFamily:
    """adapter_family() returns a coarse group label."""

    def test_ve33_stable_family(self):
        fam = adapter_family("ve33_stable")
        assert isinstance(fam, str)
        assert len(fam) > 0

    def test_ve33_volatile_family(self):
        fam = adapter_family("ve33_volatile")
        assert isinstance(fam, str)
        assert len(fam) > 0

    def test_stable_and_volatile_in_same_ve33_family_or_different(self):
        """Both ve33 variants should have a deterministic family string."""
        fam_s = adapter_family("ve33_stable")
        fam_v = adapter_family("ve33_volatile")
        # Both must be non-empty strings (specific values may differ by design)
        assert fam_s and fam_v

    def test_ve33_volatile_and_stable_different_pricing_models(self):
        """Generic ve33 (volatile) and aerodrome_stable must map to DIFFERENT pricing models."""
        volatile_model = adapter_pricing_model("ve33")
        stable_model = adapter_pricing_model("aerodrome_stable")
        assert volatile_model != stable_model, (
            f"ve33 volatile ({volatile_model!r}) must differ from aerodrome_stable ({stable_model!r})"
        )
        assert volatile_model == "solidly_volatile_xyk"
        assert stable_model == "solidly_stable_curve"

    def test_curve_family_not_same_as_ve33(self):
        fam_curve = adapter_family("curve_stable")
        fam_ve33 = adapter_family("ve33_stable")
        # Curve and ve33 should be categorized as different pricing families
        assert fam_curve != fam_ve33

    def test_unknown_adapter_has_default_family(self):
        fam = adapter_family("totally_unknown_adapter")
        assert isinstance(fam, str)
        assert len(fam) > 0


class TestAdapterPricingModel:
    """adapter_pricing_model() exposes orthogonal curve topology."""

    @pytest.mark.parametrize(
        ("adapter_type", "expected_model"),
        [
            ("uniswap_v2", "cpmm_xyk"),
            ("uniswap_v3", "clmm_ticks"),
            # ve33 generic (volatile) must NOT fall into solidly_stable_curve
            ("ve33", "solidly_volatile_xyk"),
            ("ve33_volatile", "solidly_volatile_xyk"),
            ("solidly_volatile", "solidly_volatile_xyk"),
            # aerodrome_stable must map to solidly_stable_curve, not volatile
            ("ve33_stable", "solidly_stable_curve"),
            ("aerodrome_stable", "solidly_stable_curve"),
            ("solidly_stable", "solidly_stable_curve"),
            ("curve_stable", "curve_stableswap"),
            ("dodo_pmm", "pmm_oracle"),
            ("rfq", "rfq_offchain"),
            ("uniswap_v4_hook", "v4_hook_dynamic_fee"),
            ("maverick_v2", "maverick_directional"),
            ("balancer_weighted", "balancer_weighted"),
            ("balancer_stable", "balancer_stable"),
        ],
    )
    def test_known_pricing_models(self, adapter_type, expected_model):
        assert adapter_pricing_model(adapter_type) == expected_model

    def test_unknown_pricing_model_is_explicit(self):
        assert adapter_pricing_model("totally_unknown_adapter") == "unknown"


class TestBuildCostBreakdown:
    """build_cost_breakdown() with mock cycle_results."""

    def _make_cycle_result(
        self,
        gross_bps: float = 10.0,
        adapter_types: List[str] = None,
    ) -> Dict[str, Any]:
        adapter_types = adapter_types or ["ve33_stable", "uniswap_v3"]
        return {
            "gross_spread_bps": gross_bps,
            "legs": [{"adapter_type": at} for at in adapter_types],
        }

    def test_empty_input_returns_valid_structure(self):
        result = build_cost_breakdown([])
        assert "cost_breakdown_by_adapter" in result
        assert "cycles_by_adapter_family" in result
        assert "positive_cycles_by_adapter_family" in result
        assert "cycles_by_pricing_model" in result
        assert "positive_cycles_by_pricing_model" in result

    def test_single_positive_cycle(self):
        cycle = self._make_cycle_result(gross_bps=20.0, adapter_types=["ve33_stable"])
        result = build_cost_breakdown([cycle])
        breakdown = result["cost_breakdown_by_adapter"]
        assert isinstance(breakdown, dict)
        assert breakdown["ve33_stable"]["pricing_model"] == "solidly_stable_curve"
        by_family = result["cycles_by_adapter_family"]
        positive = result["positive_cycles_by_adapter_family"]
        by_model = result["cycles_by_pricing_model"]
        assert isinstance(by_family, dict)
        assert isinstance(positive, dict)
        assert by_model["solidly_stable_curve"] == 1

    def test_negative_cycle_not_in_positive_families(self):
        """Cycles with gross_bps too low should not count as positive."""
        # ve33_volatile cost is 12 bps; gross=2 bps → net negative
        cycle = self._make_cycle_result(gross_bps=2.0, adapter_types=["ve33_volatile"])
        result = build_cost_breakdown([cycle])
        positive = result["positive_cycles_by_adapter_family"]
        fam = adapter_family("ve33_volatile")
        if fam in positive:
            assert positive[fam] == 0, "Negative net cycle should not count as positive"

    def test_multiple_cycles_accumulate(self):
        cycles = [
            self._make_cycle_result(gross_bps=20.0, adapter_types=["ve33_stable"]),
            self._make_cycle_result(gross_bps=20.0, adapter_types=["ve33_stable"]),
            self._make_cycle_result(gross_bps=2.0, adapter_types=["ve33_volatile"]),
        ]
        result = build_cost_breakdown(cycles)
        by_family = result["cycles_by_adapter_family"]
        # At least one family should have count ≥ 2
        assert any(v >= 2 for v in by_family.values())

    def test_missing_adapter_type_key_is_safe(self):
        """Cycles without adapter_type do not crash build_cost_breakdown."""
        cycle = {
            "gross_spread_bps": 10.0,
            "legs": [{}],  # no adapter_type key
        }
        result = build_cost_breakdown([cycle])
        assert result is not None

    def test_duplicate_adapter_legs_are_costed_per_leg(self):
        """Two legs on the same adapter must pay cost twice, not once."""
        cycle = self._make_cycle_result(
            gross_bps=10.0,
            adapter_types=["uniswap_v3", "uniswap_v3"],
        )
        result = build_cost_breakdown([cycle])
        positive = result["positive_cycles_by_adapter_family"]
        assert positive.get("uniswap_v3", 0) == 0
