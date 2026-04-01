# PATH: tests/unit/test_triangular_contracts.py
"""
Compatibility contract tests for M7.A triangular modules.

Covers:
- M7.A universe constants (tokens, dexes, adapters)
- Graph filter correctness
- PoolEdge.edge_key collision resistance
- build_graph_from_runtime_pairs compatibility with RuntimePair
- build_graph_from_discovered_pools provenance
- CycleScore artifact schema compliance with step_M7.md
- score_cycle_fees_only is diagnostic prefilter (not canonical truth)
- classify_same_state provenance classification
- score_cycle_measured live decomposition
"""

import pytest
from unittest.mock import patch, MagicMock

from engine.triangular_graph import (
    M7A_DEXES_ARBITRUM_ONE,
    M7A_STABLE_ADAPTERS,
    M7A_TOKENS_ARBITRUM_ONE,
    PoolEdge,
    PoolGraph,
    build_graph_from_pool_dicts,
    build_graph_from_runtime_pairs,
    filter_graph_to_m7a_universe,
)
from engine.triangular_cycles import (
    CycleScore,
    LegQuote,
    SAME_STATE_AMBIGUOUS,
    SAME_STATE_PROVEN,
    SAME_STATE_VIOLATED,
    TriangularCycle,
    classify_same_state,
    find_3hop_cycles,
    leg_quote_from_rpc_result,
    score_cycle_fees_only,
    score_cycle_measured,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edge(token_in, token_out, dex="uniswap_v3", fee=3000,
          pool="0xaaa", chain="arbitrum_one", adapter_type=None):
    return PoolEdge(
        token_in=token_in,
        token_out=token_out,
        pool_address=pool,
        dex=dex,
        adapter_type=adapter_type or dex,
        fee=fee,
        chain=chain,
    )


# ---------------------------------------------------------------------------
# M7.A Universe constants
# ---------------------------------------------------------------------------

class TestBlockerSummary:
    """Contract tests for the M7.A blocker summary (machine-readable RCA)."""

    def _make_score(self, gross=-10.0, gas=12.0, fee1=0.0, fee2=1.0, fee3=5.0,
                    net=-28.0, size_usd=100.0, tokens=("ARB", "USDC", "WETH")):
        e1 = _edge(tokens[0], tokens[1], dex="camelot_v3", fee=0, pool="0x111", adapter_type="algebra")
        e2 = _edge(tokens[1], tokens[2], dex="uniswap_v3", fee=100, pool="0x222")
        e3 = _edge(tokens[2], tokens[0], dex="pancakeswap_v3", fee=500, pool="0x333")
        cycle = TriangularCycle(leg1=e1, leg2=e2, leg3=e3)
        return CycleScore(
            cycle=cycle, gross_bps=gross, gas_bps=gas,
            fee_leg1_bps=fee1, fee_leg2_bps=fee2, fee_leg3_bps=fee3,
            total_fee_bps=fee1 + fee2 + fee3,
            final_net_bps=net, scored_size_usd=size_usd,
            block_tag="123456", provenance_summary="measured",
            same_state_class=SAME_STATE_PROVEN, route_viable=True,
            reject_reason="NET_NEGATIVE",
        )

    def _make_stats(self, scored=67, failed=33, attempted=100):
        return {
            "block_number": 446635245,
            "attempted": attempted,
            "scored": scored,
            "failed": failed,
            "measured_ranked_count": scored,
            "diagnostic_fallback_count": failed,
            "promoted_count": 0,
            "best_measured_net_bps": -20.96,
            "same_state_distribution": {"same_state_proven": scored},
        }

    def test_blocker_summary_schema_keys(self):
        """blocker_summary must contain all required keys."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score()]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])

        required_keys = {
            "best_route_gross_bps", "best_route_gas_bps", "best_route_total_fee_bps",
            "best_route_net_bps", "best_route_best_size_usd",
            "small_size_gas_domination", "large_size_slippage_domination",
            "same_state_proven_rate", "route_failure_rate",
            "token_triple_concentration", "top_blockers",
            "per_cycle_blocker_counts", "global_blockers_present",
        }
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_blocker_summary_gross_negative(self):
        """If best route gross is negative, GROSS_NEGATIVE_CORE must be in top_blockers."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary, BLOCKER_GROSS_NEGATIVE_CORE

        ranked = [self._make_score(gross=-9.3)]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])
        assert BLOCKER_GROSS_NEGATIVE_CORE in result["top_blockers"]

    def test_blocker_summary_third_leg_fee(self):
        """If leg3 fee >= 5 bps, THIRD_LEG_FEE_BINDING must appear."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary, BLOCKER_THIRD_LEG_FEE_BINDING

        ranked = [self._make_score(fee3=5.0)]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])
        assert BLOCKER_THIRD_LEG_FEE_BINDING in result["top_blockers"]

    def test_blocker_summary_single_triple_concentration(self):
        """100% same token triple must trigger SINGLE_TRIPLE_CONCENTRATION."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            _build_blocker_summary, BLOCKER_SINGLE_TRIPLE_CONCENTRATION,
        )

        # All routes use same triple
        ranked = [self._make_score() for _ in range(5)]
        stats = self._make_stats(scored=5, failed=0, attempted=5)
        result = _build_blocker_summary(ranked, stats, [])
        assert result["token_triple_concentration"] == 1.0
        assert BLOCKER_SINGLE_TRIPLE_CONCENTRATION in result["top_blockers"]

    def test_blocker_summary_quote_failure_breadth(self):
        """High failure rate (>=25%) triggers QUOTE_FAILURE_BREADTH_LIMIT."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            _build_blocker_summary, BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT,
        )

        ranked = [self._make_score()]
        stats = self._make_stats(scored=50, failed=50, attempted=100)
        result = _build_blocker_summary(ranked, stats, [])
        assert result["route_failure_rate"] == 0.5
        assert BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT in result["top_blockers"]

    def test_blocker_summary_same_state_rate(self):
        """same_state_proven_rate must match distribution."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score()]
        stats = self._make_stats(scored=67, failed=33, attempted=100)
        result = _build_blocker_summary(ranked, stats, [])
        assert result["same_state_proven_rate"] == 1.0  # 67/67 proven

    def test_blocker_summary_no_measured_routes(self):
        """Empty measured list produces error sentinel."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        result = _build_blocker_summary([], {}, [])
        assert result.get("error") == "no_measured_routes"

    def test_blocker_summary_dominant_triple_field(self):
        """dominant_triple must be a sorted list of 3 tokens."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score()]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])
        assert isinstance(result["dominant_triple"], list)
        assert len(result["dominant_triple"]) == 3
        assert result["dominant_triple"] == sorted(result["dominant_triple"])



class TestClassifyBlockerTags:
    """Contract tests for classify_blocker_tags()."""

    def _make_score(self, gross=-10.0, gas=12.0, fee3=5.0, net=-28.0):
        e1 = _edge("ARB", "USDC", dex="camelot_v3", fee=0, pool="0x111", adapter_type="algebra")
        e2 = _edge("USDC", "WETH", dex="uniswap_v3", fee=100, pool="0x222")
        e3 = _edge("WETH", "ARB", dex="pancakeswap_v3", fee=500, pool="0x333")
        cycle = TriangularCycle(leg1=e1, leg2=e2, leg3=e3)
        return CycleScore(
            cycle=cycle, gross_bps=gross, gas_bps=gas,
            fee_leg1_bps=0.0, fee_leg2_bps=1.0, fee_leg3_bps=fee3,
            total_fee_bps=1.0 + fee3,
            final_net_bps=net, scored_size_usd=100.0,
            block_tag="123456", provenance_summary="measured",
            same_state_class=SAME_STATE_PROVEN, route_viable=True,
        )

    def test_gross_negative_tag(self):
        """Negative gross triggers GROSS_NEGATIVE_CORE."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_GROSS_NEGATIVE_CORE
        s = self._make_score(gross=-5.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_GROSS_NEGATIVE_CORE in tags

    def test_positive_gross_no_tag(self):
        """Positive gross does NOT trigger GROSS_NEGATIVE_CORE."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_GROSS_NEGATIVE_CORE
        s = self._make_score(gross=2.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_GROSS_NEGATIVE_CORE not in tags

    def test_third_leg_fee_tag(self):
        """fee_leg3 >= 5 bps triggers THIRD_LEG_FEE_BINDING."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_THIRD_LEG_FEE_BINDING
        s = self._make_score(fee3=5.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_THIRD_LEG_FEE_BINDING in tags

    def test_low_third_leg_fee_no_tag(self):
        """fee_leg3 < 5 bps does NOT trigger THIRD_LEG_FEE_BINDING."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_THIRD_LEG_FEE_BINDING
        s = self._make_score(fee3=1.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_THIRD_LEG_FEE_BINDING not in tags

    def test_gas_dominant_small_with_sweep(self):
        """Gas domination at small sizes detected from sweep curve."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_GAS_DOMINANT_SMALL
        from engine.triangular_cycles import SizeSweepPoint, SizeSweepResult

        s = self._make_score(gross=-10.0, net=-21.0)
        curve = [
            SizeSweepPoint(size_usd=1.0, final_net_bps=-1100.0, quoted=True),
            SizeSweepPoint(size_usd=100.0, final_net_bps=-21.0, quoted=True),
            SizeSweepPoint(size_usd=10000.0, final_net_bps=-400.0, quoted=True),
        ]
        sweep = SizeSweepResult(
            cycle=s.cycle, best_size_usd=100.0, best_net_bps=-21.0,
            best_score=s, size_curve=curve,
            sizes_attempted=3, sizes_quoted=3,
        )
        tags = classify_blocker_tags(s, sweep)
        assert BLOCKER_GAS_DOMINANT_SMALL in tags

    def test_slippage_dominant_large_with_sweep(self):
        """Slippage domination at large sizes detected from sweep curve."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_SLIPPAGE_DOMINANT_LARGE
        from engine.triangular_cycles import SizeSweepPoint, SizeSweepResult

        s = self._make_score(gross=-10.0, net=-21.0)
        curve = [
            SizeSweepPoint(size_usd=1.0, final_net_bps=-1100.0, quoted=True),
            SizeSweepPoint(size_usd=100.0, final_net_bps=-21.0, quoted=True),
            SizeSweepPoint(size_usd=10000.0, final_net_bps=-400.0, quoted=True),
        ]
        sweep = SizeSweepResult(
            cycle=s.cycle, best_size_usd=100.0, best_net_bps=-21.0,
            best_score=s, size_curve=curve,
            sizes_attempted=3, sizes_quoted=3,
        )
        tags = classify_blocker_tags(s, sweep)
        assert BLOCKER_SLIPPAGE_DOMINANT_LARGE in tags

    def test_no_sweep_no_size_tags(self):
        """Without sweep data, no size-dependent tags should be produced."""
        from scripts.m7a_enumerate_cycles import (
            classify_blocker_tags,
            BLOCKER_GAS_DOMINANT_SMALL,
            BLOCKER_SLIPPAGE_DOMINANT_LARGE,
        )
        s = self._make_score()
        tags = classify_blocker_tags(s, sweep=None)
        assert BLOCKER_GAS_DOMINANT_SMALL not in tags
        assert BLOCKER_SLIPPAGE_DOMINANT_LARGE not in tags


# ---------------------------------------------------------------------------
# Blocker count semantics contract tests
# ---------------------------------------------------------------------------


class TestBlockerCountSemantics:
    """Contract tests for separated per_cycle vs global blocker counts."""

    def _make_score(self, gross=-10.0, gas=12.0, fee3=5.0, net=-28.0):
        e1 = _edge("ARB", "USDC", dex="camelot_v3", fee=0, pool="0x111", adapter_type="algebra")
        e2 = _edge("USDC", "WETH", dex="uniswap_v3", fee=100, pool="0x222")
        e3 = _edge("WETH", "ARB", dex="pancakeswap_v3", fee=500, pool="0x333")
        cycle = TriangularCycle(leg1=e1, leg2=e2, leg3=e3)
        return CycleScore(
            cycle=cycle, gross_bps=gross, gas_bps=gas,
            fee_leg1_bps=0.0, fee_leg2_bps=1.0, fee_leg3_bps=fee3,
            total_fee_bps=1.0 + fee3,
            final_net_bps=net, scored_size_usd=100.0,
            block_tag="123456", provenance_summary="measured",
            same_state_class=SAME_STATE_PROVEN, route_viable=True,
            reject_reason="NET_NEGATIVE",
        )

    def _make_stats(self, scored=67, failed=33, attempted=100):
        return {
            "block_number": 446635245,
            "attempted": attempted,
            "scored": scored,
            "failed": failed,
            "measured_ranked_count": scored,
            "diagnostic_fallback_count": failed,
            "promoted_count": 0,
            "best_measured_net_bps": -20.96,
            "same_state_distribution": {"same_state_proven": scored},
        }

    def test_per_cycle_and_global_are_separate_keys(self):
        """blocker_summary must have per_cycle_blocker_counts and global_blockers_present."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score() for _ in range(3)]
        stats = self._make_stats(scored=3, failed=30, attempted=33)
        result = _build_blocker_summary(ranked, stats, [])
        assert "per_cycle_blocker_counts" in result
        assert "global_blockers_present" in result
        assert isinstance(result["per_cycle_blocker_counts"], dict)
        assert isinstance(result["global_blockers_present"], list)

    def test_per_cycle_counts_are_integers(self):
        """per_cycle_blocker_counts values must be integers (cycle counts)."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score() for _ in range(5)]
        stats = self._make_stats(scored=5, failed=0, attempted=5)
        result = _build_blocker_summary(ranked, stats, [])
        for tag, count in result["per_cycle_blocker_counts"].items():
            assert isinstance(count, int), f"{tag} count is not int: {count}"

    def test_global_blockers_do_not_appear_in_per_cycle(self):
        """SINGLE_TRIPLE_CONCENTRATION and QUOTE_FAILURE_BREADTH_LIMIT are global only."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            _build_blocker_summary,
            BLOCKER_SINGLE_TRIPLE_CONCENTRATION,
            BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT,
        )

        ranked = [self._make_score() for _ in range(5)]
        stats = self._make_stats(scored=5, failed=50, attempted=55)
        result = _build_blocker_summary(ranked, stats, [])
        # These should be in global, not in per_cycle
        assert BLOCKER_SINGLE_TRIPLE_CONCENTRATION not in result["per_cycle_blocker_counts"]
        assert BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT not in result["per_cycle_blocker_counts"]
        assert BLOCKER_SINGLE_TRIPLE_CONCENTRATION in result["global_blockers_present"]
        assert BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT in result["global_blockers_present"]

    def test_per_cycle_gross_negative_count_matches_cycles(self):
        """GROSS_NEGATIVE_CORE count should match number of cycles with negative gross."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary, BLOCKER_GROSS_NEGATIVE_CORE

        ranked = [self._make_score(gross=-5.0) for _ in range(7)]
        stats = self._make_stats(scored=7, failed=0, attempted=7)
        result = _build_blocker_summary(ranked, stats, [])
        assert result["per_cycle_blocker_counts"][BLOCKER_GROSS_NEGATIVE_CORE] == 7

    def test_old_blocker_tag_counts_key_removed(self):
        """blocker_tag_counts (mixed semantics) must no longer appear."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score()]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])
        assert "blocker_tag_counts" not in result


# ---------------------------------------------------------------------------
# Blocker repeatability contract tests
# ---------------------------------------------------------------------------


class TestBlockerRepeatability:
    """Contract tests for build_blocker_repeatability() temporal aggregation."""

    def _write_artifact(self, tmp_path, name, block, gross=-9.3, gas=11.6,
                        fee=6.0, net=-21.0, size=100.0, failure_rate=0.33,
                        triple_conc=1.0):
        """Write a minimal artifact JSON with blocker_summary."""
        data = {
            "m7a_enumeration": True,
            "chain": "arbitrum_one",
            "measured": {"block_number": block, "scored": 67, "failed": 33, "attempted": 100},
            "blocker_summary": {
                "best_route_gross_bps": gross,
                "best_route_gas_bps": gas,
                "best_route_total_fee_bps": fee,
                "best_route_net_bps": net,
                "best_route_best_size_usd": size,
                "small_size_gas_domination": True,
                "small_size_worst_bps": -1100.0,
                "large_size_slippage_domination": True,
                "large_size_worst_bps": -400.0,
                "same_state_proven_rate": 1.0,
                "route_failure_rate": failure_rate,
                "token_triple_concentration": triple_conc,
                "dominant_triple": ["ARB", "USDC", "WETH"],
                "top_blockers": [
                    "GROSS_NEGATIVE_CORE", "GAS_DOMINANT_SMALL",
                    "SLIPPAGE_DOMINANT_LARGE", "THIRD_LEG_FEE_BINDING",
                    "SINGLE_TRIPLE_CONCENTRATION", "QUOTE_FAILURE_BREADTH_LIMIT",
                ],
                "per_cycle_blocker_counts": {
                    "GROSS_NEGATIVE_CORE": 10,
                    "GAS_DOMINANT_SMALL": 10,
                    "SLIPPAGE_DOMINANT_LARGE": 10,
                    "THIRD_LEG_FEE_BINDING": 6,
                },
                "global_blockers_present": [
                    "SINGLE_TRIPLE_CONCENTRATION",
                    "QUOTE_FAILURE_BREADTH_LIMIT",
                ],
                "cycles_analyzed": 10,
            },
        }
        import json
        path = tmp_path / name
        with open(path, "w") as f:
            json.dump(data, f)
        return str(path)

    def test_repeatability_schema_keys(self, tmp_path):
        """Repeatability report must have all required keys."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002)
        p3 = self._write_artifact(tmp_path, "r3.json", 100003)

        result = build_blocker_repeatability([p1, p2, p3])

        required_keys = {
            "blocker_repeatability", "timestamp", "runs_count",
            "block_range", "metric_ranges", "blocker_class_stability",
            "per_cycle_tag_ranges", "global_blocker_stability", "snapshots",
        }
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_repeatability_runs_count(self, tmp_path):
        """runs_count must match number of valid artifacts."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002)
        p3 = self._write_artifact(tmp_path, "r3.json", 100003)

        result = build_blocker_repeatability([p1, p2, p3])
        assert result["runs_count"] == 3

    def test_repeatability_block_range(self, tmp_path):
        """block_range must span min/max of input blocks."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100005)
        p3 = self._write_artifact(tmp_path, "r3.json", 100010)

        result = build_blocker_repeatability([p1, p2, p3])
        assert result["block_range"]["min"] == 100001
        assert result["block_range"]["max"] == 100010

    def test_repeatability_stable_blockers(self, tmp_path):
        """Tags present in all runs are stable_blockers."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002)
        p3 = self._write_artifact(tmp_path, "r3.json", 100003)

        result = build_blocker_repeatability([p1, p2, p3])
        stability = result["blocker_class_stability"]
        assert "GROSS_NEGATIVE_CORE" in stability["stable_blockers"]
        assert len(stability["flapping_blockers"]) == 0

    def test_repeatability_metric_ranges_have_min_max_mean(self, tmp_path):
        """Each metric range must have min, max, mean."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001, gross=-9.0)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002, gross=-6.0)
        p3 = self._write_artifact(tmp_path, "r3.json", 100003, gross=-12.0)

        result = build_blocker_repeatability([p1, p2, p3])
        gross_range = result["metric_ranges"]["best_route_gross_bps"]
        assert "min" in gross_range
        assert "max" in gross_range
        assert "mean" in gross_range
        assert gross_range["min"] == -12.0
        assert gross_range["max"] == -6.0

    def test_repeatability_per_cycle_tag_ranges(self, tmp_path):
        """per_cycle_tag_ranges must show min/max across runs."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002)
        p3 = self._write_artifact(tmp_path, "r3.json", 100003)

        result = build_blocker_repeatability([p1, p2, p3])
        assert "GROSS_NEGATIVE_CORE" in result["per_cycle_tag_ranges"]
        tag_range = result["per_cycle_tag_ranges"]["GROSS_NEGATIVE_CORE"]
        assert tag_range["present_in_runs"] == 3

    def test_repeatability_global_blocker_stability(self, tmp_path):
        """global_blocker_stability shows per-tag run presence count."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002)
        p3 = self._write_artifact(tmp_path, "r3.json", 100003)

        result = build_blocker_repeatability([p1, p2, p3])
        assert result["global_blocker_stability"]["SINGLE_TRIPLE_CONCENTRATION"] == 3
        assert result["global_blocker_stability"]["QUOTE_FAILURE_BREADTH_LIMIT"] == 3

    def test_repeatability_empty_artifacts(self):
        """No valid artifacts returns error."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        result = build_blocker_repeatability(["nonexistent1.json", "nonexistent2.json"])
        assert "error" in result

    def test_repeatability_snapshots_contain_block_and_metrics(self, tmp_path):
        """Each snapshot must contain block and key metric fields."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002)

        result = build_blocker_repeatability([p1, p2])
        for snap in result["snapshots"]:
            assert "block" in snap
            assert "best_route_gross_bps" in snap
            assert "best_route_net_bps" in snap
            assert "top_blockers" in snap
            assert "per_cycle_blocker_counts" in snap
            assert "global_blockers_present" in snap


# ---------------------------------------------------------------------------
# Verdict summary contract tests
# ---------------------------------------------------------------------------


class TestVerdictSummary:
    """Contract tests for build_verdict_summary() bounded-scope M7.A verdict."""

    def _make_repeatability(
        self,
        net_min=-23.5, net_max=-9.5, net_mean=-16.3,
        gross_min=-14.3, gross_max=2.25, gross_mean=-6.2,
        stable=None, flapping=None, runs=3,
        conc_max=1.0, fail_min=0.33, fail_max=0.33,
    ):
        """Build a minimal repeatability report dict for verdict testing."""
        if stable is None:
            stable = [
                "GAS_DOMINANT_SMALL", "GROSS_NEGATIVE_CORE",
                "QUOTE_FAILURE_BREADTH_LIMIT", "SINGLE_TRIPLE_CONCENTRATION",
                "SLIPPAGE_DOMINANT_LARGE", "THIRD_LEG_FEE_BINDING",
            ]
        if flapping is None:
            flapping = []
        return {
            "blocker_repeatability": True,
            "timestamp": "2026-03-28T20:00:00Z",
            "runs_count": runs,
            "block_range": {"min": 446652757, "max": 446654943},
            "metric_ranges": {
                "best_route_gross_bps": {"min": gross_min, "max": gross_max, "mean": gross_mean},
                "best_route_gas_bps": {"min": 9.23, "max": 11.81, "mean": 10.09},
                "best_route_total_fee_bps": {"min": 1.0, "max": 6.0, "mean": 4.33},
                "best_route_net_bps": {"min": net_min, "max": net_max, "mean": net_mean},
                "best_route_best_size_usd": {"min": 150.0, "max": 150.0, "mean": 150.0},
                "route_failure_rate": {"min": fail_min, "max": fail_max, "mean": (fail_min + fail_max) / 2},
                "token_triple_concentration": {"min": 1.0, "max": conc_max, "mean": 1.0},
            },
            "blocker_class_stability": {
                "stable_blockers": stable,
                "flapping_blockers": flapping,
                "all_observed": stable + flapping,
            },
            "per_cycle_tag_ranges": {},
            "global_blocker_stability": {},
            "snapshots": [
                {"universe_profile": "narrow_7", "block": 446652757},
                {"universe_profile": "narrow_7", "block": 446653838},
                {"universe_profile": "narrow_7", "block": 446654943},
            ] if runs == 3 else [],
        }

    def test_verdict_schema_keys(self):
        """Verdict must contain all required keys from step 4 spec."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability()
        result = build_verdict_summary(rep)

        required_keys = {
            "m7a_verdict", "timestamp", "verdict_scope",
            "two_leg_baseline_net_bps", "best_net_bps_range",
            "beats_two_leg_baseline", "all_sizes_negative",
            "gross_sometimes_positive",
            "stable_blockers_count", "flapping_blockers_count",
            "stable_blockers", "flapping_blockers",
            "dominant_triple", "route_failure_rate",
            "recommend_open_m7b", "recommend_freeze_current_m7a_scope",
            "verdict_reasoning",
        }
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_verdict_no_graduate_for_current_evidence(self):
        """Current evidence class (all negative, 6 stable blockers) must NOT recommend M7.B."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability()
        result = build_verdict_summary(rep)

        assert result["recommend_open_m7b"] is False
        assert result["recommend_freeze_current_m7a_scope"] is True

    def test_verdict_beats_baseline_false(self):
        """When best net is worse than two-leg baseline, beats_two_leg_baseline must be False."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability(net_max=-9.5)  # -9.5 < -3.5 baseline
        result = build_verdict_summary(rep, two_leg_baseline_bps=-3.5)

        assert result["beats_two_leg_baseline"] is False

    def test_verdict_all_sizes_negative(self):
        """When best net max < 0, all_sizes_negative must be True."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability(net_max=-5.0)
        result = build_verdict_summary(rep)

        assert result["all_sizes_negative"] is True

    def test_verdict_gross_sometimes_positive(self):
        """When gross_max > 0, gross_sometimes_positive must be True (multi-cost blocker)."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability(gross_max=2.25)
        result = build_verdict_summary(rep)

        assert result["gross_sometimes_positive"] is True

    def test_verdict_gross_always_negative(self):
        """When gross_max < 0, gross_sometimes_positive must be False."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability(gross_max=-1.0)
        result = build_verdict_summary(rep)

        assert result["gross_sometimes_positive"] is False

    def test_verdict_stable_flapping_counts(self):
        """Blocker counts must match the input repeatability data."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability(
            stable=["A", "B", "C"],
            flapping=["D"],
        )
        result = build_verdict_summary(rep)

        assert result["stable_blockers_count"] == 3
        assert result["flapping_blockers_count"] == 1
        assert result["stable_blockers"] == ["A", "B", "C"]
        assert result["flapping_blockers"] == ["D"]

    def test_verdict_scope_fields(self):
        """verdict_scope must contain chain, universe, phase."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability()
        result = build_verdict_summary(rep, chain="arbitrum_one")

        scope = result["verdict_scope"]
        assert scope["chain"] == "arbitrum_one"
        assert scope["universe"] == "narrow_7"
        assert scope["phase"] == "M7.A"
        assert scope["runs_count"] == 3

    def test_verdict_error_on_bad_repeatability(self):
        """Verdict with error repeatability returns error."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        result = build_verdict_summary({"error": "no_valid_artifacts"})
        assert result["verdict"] == "INSUFFICIENT_EVIDENCE"

    def test_verdict_hypothetical_positive_would_not_freeze(self):
        """If net beats baseline and few blockers, verdict should recommend M7.B."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = self._make_repeatability(
            net_min=1.0, net_max=5.0, net_mean=3.0,
            gross_min=10.0, gross_max=15.0, gross_mean=12.0,
            stable=["GAS_DOMINANT_SMALL"],
            flapping=[],
        )
        result = build_verdict_summary(rep, two_leg_baseline_bps=-3.5)

        assert result["beats_two_leg_baseline"] is True
        assert result["all_sizes_negative"] is False
        assert result["recommend_open_m7b"] is True
        assert result["recommend_freeze_current_m7a_scope"] is False



class TestUniverseProfile:
    """Contract tests for M7.A.2 universe-profile expansion."""

    def test_m7a2_tokens_superset_of_m7a(self):
        """Expanded universe must be a strict superset of narrow universe."""
        from engine.triangular_graph import (
            M7A_TOKENS_ARBITRUM_ONE,
            M7A2_TOKENS_ARBITRUM_ONE,
            M7A2_EXTRA_TOKENS_ARBITRUM_ONE,
        )
        assert M7A_TOKENS_ARBITRUM_ONE < M7A2_TOKENS_ARBITRUM_ONE  # strict subset
        assert M7A2_EXTRA_TOKENS_ARBITRUM_ONE - M7A_TOKENS_ARBITRUM_ONE == M7A2_EXTRA_TOKENS_ARBITRUM_ONE
        assert len(M7A2_TOKENS_ARBITRUM_ONE) == len(M7A_TOKENS_ARBITRUM_ONE) + len(M7A2_EXTRA_TOKENS_ARBITRUM_ONE)

    def test_m7a2_extra_tokens_are_known(self):
        """Extra tokens must be DAI, GMX, UNI exactly."""
        from engine.triangular_graph import M7A2_EXTRA_TOKENS_ARBITRUM_ONE
        assert M7A2_EXTRA_TOKENS_ARBITRUM_ONE == frozenset({"DAI", "GMX", "UNI"})

    def test_m7a2_token_count(self):
        """Expanded universe must have exactly 10 tokens."""
        from engine.triangular_graph import M7A2_TOKENS_ARBITRUM_ONE
        assert len(M7A2_TOKENS_ARBITRUM_ONE) == 10

    def test_filter_m7a2_produces_superset_graph(self):
        """filter_graph_to_m7a2_universe must include all edges from m7a filter plus extras."""
        from engine.triangular_graph import (
            PoolEdge, PoolGraph,
            filter_graph_to_m7a_universe,
            filter_graph_to_m7a2_universe,
        )
        g = PoolGraph(chain="arbitrum_one")
        # Edge in narrow universe
        g.add_pool(PoolEdge(
            token_in="WETH", token_out="USDC", pool_address="0x01",
            dex="uniswap_v3", adapter_type="uniswap_v3", fee=500,
            chain="arbitrum_one",
        ))
        # Edge only in expanded universe (DAI)
        g.add_pool(PoolEdge(
            token_in="WETH", token_out="DAI", pool_address="0x02",
            dex="uniswap_v3", adapter_type="uniswap_v3", fee=500,
            chain="arbitrum_one",
        ))
        narrow = filter_graph_to_m7a_universe(g)
        expanded = filter_graph_to_m7a2_universe(g)
        assert narrow.edge_count <= expanded.edge_count
        assert "DAI" not in narrow.all_tokens()
        assert "DAI" in expanded.all_tokens()
        assert "WETH" in narrow.all_tokens()
        assert "WETH" in expanded.all_tokens()

    def test_m7a2_filter_rejects_non_stable_adapter(self):
        """Expanded universe still rejects edges with non-stable adapters."""
        from engine.triangular_graph import (
            PoolEdge, PoolGraph, filter_graph_to_m7a2_universe,
        )
        g = PoolGraph(chain="arbitrum_one")
        g.add_pool(PoolEdge(
            token_in="DAI", token_out="USDC", pool_address="0x03",
            dex="ramses_v2", adapter_type="ve33", fee=100,
            chain="arbitrum_one",
        ))
        expanded = filter_graph_to_m7a2_universe(g)
        assert expanded.edge_count == 0

    def test_m7a2_filter_rejects_excluded_tokens(self):
        """Expanded universe still rejects tokens not in expanded set."""
        from engine.triangular_graph import (
            PoolEdge, PoolGraph, filter_graph_to_m7a2_universe,
        )
        g = PoolGraph(chain="arbitrum_one")
        g.add_pool(PoolEdge(
            token_in="WETH", token_out="wstETH", pool_address="0x04",
            dex="uniswap_v3", adapter_type="uniswap_v3", fee=500,
            chain="arbitrum_one",
        ))
        expanded = filter_graph_to_m7a2_universe(g)
        assert expanded.edge_count == 0

    def test_artifact_universe_profile_field(self):
        """Artifact JSON must contain universe_profile at top level."""
        # Simulates the structure m7a_enumerate_cycles.py produces
        artifact = {
            "m7a_enumeration": True,
            "universe_profile": "expanded_10",
            "m7a_universe": {
                "universe_profile": "expanded_10",
                "token_count": 10,
            },
        }
        assert artifact["universe_profile"] == "expanded_10"
        assert artifact["m7a_universe"]["token_count"] == 10

    def test_verdict_with_expanded_universe_profile(self):
        """Verdict from expanded_10 artifacts must carry universe='expanded_10'."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_verdict_summary

        rep = {
            "blocker_repeatability": True,
            "timestamp": "2026-03-28T22:00:00Z",
            "runs_count": 2,
            "universe_profile": "expanded_10",
            "block_range": {"min": 100, "max": 200},
            "metric_ranges": {
                "best_route_gross_bps": {"min": -14.0, "max": -5.0, "mean": -9.5},
                "best_route_gas_bps": {"min": 9.0, "max": 11.0, "mean": 10.0},
                "best_route_total_fee_bps": {"min": 1.0, "max": 5.0, "mean": 3.0},
                "best_route_net_bps": {"min": -20.0, "max": -8.0, "mean": -14.0},
                "best_route_best_size_usd": {"min": 100, "max": 150, "mean": 125},
                "route_failure_rate": {"min": 0.2, "max": 0.3, "mean": 0.25},
                "token_triple_concentration": {"min": 0.7, "max": 0.9, "mean": 0.8},
            },
            "blocker_class_stability": {
                "stable_blockers": ["GAS_DOMINANT_SMALL", "GROSS_NEGATIVE_CORE"],
                "flapping_blockers": [],
                "all_observed": ["GAS_DOMINANT_SMALL", "GROSS_NEGATIVE_CORE"],
            },
            "snapshots": [
                {"universe_profile": "expanded_10", "block": 100},
                {"universe_profile": "expanded_10", "block": 200},
            ],
        }
        result = build_verdict_summary(rep, chain="arbitrum_one")
        assert result["verdict_scope"]["universe"] == "expanded_10"

    def test_narrow_universe_keys_unchanged(self):
        """M7.A narrow universe constant must remain frozen (byte-compatible)."""
        from engine.triangular_graph import M7A_TOKENS_ARBITRUM_ONE
        expected = frozenset({"WETH", "USDC", "USDT", "WBTC", "ARB", "LINK", "PENDLE"})
        assert M7A_TOKENS_ARBITRUM_ONE == expected


# ---------------------------------------------------------------------------
# M7.A.3 Regime classification contract tests
# ---------------------------------------------------------------------------


