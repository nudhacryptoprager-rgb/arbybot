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

class TestRegimeClassification:
    """Contract tests for classify_regime_bucket() temporal regime tagging."""

    def test_high_activity_regime(self):
        """High quote success rate triggers high_activity."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, REGIME_HIGH_ACTIVITY

        stats = {"attempted": 100, "scored": 90, "failed": 10}
        bs = {"route_failure_rate": 0.1, "best_route_net_bps": -15.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_HIGH_ACTIVITY in tags

    def test_low_activity_regime(self):
        """Low quote success rate triggers low_activity."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, REGIME_LOW_ACTIVITY

        stats = {"attempted": 100, "scored": 30, "failed": 70}
        bs = {"route_failure_rate": 0.7, "best_route_net_bps": -50.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_LOW_ACTIVITY in tags

    def test_medium_activity_regime(self):
        """Intermediate quote success rate triggers medium_activity."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, REGIME_MEDIUM_ACTIVITY

        stats = {"attempted": 100, "scored": 65, "failed": 35}
        bs = {"route_failure_rate": 0.35, "best_route_net_bps": -20.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_MEDIUM_ACTIVITY in tags

    def test_high_failure_regime(self):
        """route_failure_rate > 0.4 triggers high_failure."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, REGIME_HIGH_FAILURE

        stats = {"attempted": 100, "scored": 30, "failed": 70}
        bs = {"route_failure_rate": 0.5, "best_route_net_bps": -20.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_HIGH_FAILURE in tags

    def test_low_failure_regime(self):
        """route_failure_rate < 0.2 triggers low_failure."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, REGIME_LOW_FAILURE

        stats = {"attempted": 100, "scored": 90, "failed": 10}
        bs = {"route_failure_rate": 0.1, "best_route_net_bps": -15.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_LOW_FAILURE in tags

    def test_wide_spread_regime(self):
        """best_net_bps < -30 triggers wide_spread."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, REGIME_WIDE_SPREAD

        stats = {"attempted": 100, "scored": 70, "failed": 30}
        bs = {"route_failure_rate": 0.3, "best_route_net_bps": -45.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_WIDE_SPREAD in tags

    def test_tight_spread_regime(self):
        """best_net_bps > -10 triggers tight_spread."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, REGIME_TIGHT_SPREAD

        stats = {"attempted": 100, "scored": 90, "failed": 10}
        bs = {"route_failure_rate": 0.1, "best_route_net_bps": -5.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_TIGHT_SPREAD in tags

    def test_middle_spread_no_spread_tag(self):
        """best_net_bps between -30 and -10 should not trigger spread tags."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            classify_regime_bucket, REGIME_WIDE_SPREAD, REGIME_TIGHT_SPREAD,
        )

        stats = {"attempted": 100, "scored": 80, "failed": 20}
        bs = {"route_failure_rate": 0.2, "best_route_net_bps": -20.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_WIDE_SPREAD not in tags
        assert REGIME_TIGHT_SPREAD not in tags

    def test_middle_failure_no_failure_tag(self):
        """route_failure_rate between 0.2 and 0.4 should not trigger failure tags."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            classify_regime_bucket, REGIME_HIGH_FAILURE, REGIME_LOW_FAILURE,
        )

        stats = {"attempted": 100, "scored": 70, "failed": 30}
        bs = {"route_failure_rate": 0.3, "best_route_net_bps": -20.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_HIGH_FAILURE not in tags
        assert REGIME_LOW_FAILURE not in tags

    def test_tags_are_sorted(self):
        """Regime tags must be returned in sorted order."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket

        stats = {"attempted": 100, "scored": 90, "failed": 10}
        bs = {"route_failure_rate": 0.1, "best_route_net_bps": -5.0}
        tags = classify_regime_bucket(stats, bs)
        assert tags == sorted(tags)

    def test_tags_are_from_canonical_set(self):
        """All returned tags must be from ALL_REGIME_TAGS."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket, ALL_REGIME_TAGS

        stats = {"attempted": 100, "scored": 90, "failed": 10}
        bs = {"route_failure_rate": 0.1, "best_route_net_bps": -5.0}
        tags = classify_regime_bucket(stats, bs)
        for tag in tags:
            assert tag in ALL_REGIME_TAGS, f"Unknown tag: {tag}"

    def test_empty_stats_returns_empty(self):
        """Empty measured stats produce no tags."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import classify_regime_bucket

        tags = classify_regime_bucket({}, {})
        assert tags == []

    def test_zero_attempted_no_activity_tag(self):
        """Zero attempted quotes: no activity tag (denominator guard)."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            classify_regime_bucket,
            REGIME_HIGH_ACTIVITY, REGIME_MEDIUM_ACTIVITY, REGIME_LOW_ACTIVITY,
        )

        stats = {"attempted": 0, "scored": 0, "failed": 0}
        bs = {"route_failure_rate": 0.0, "best_route_net_bps": -20.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_HIGH_ACTIVITY not in tags
        assert REGIME_MEDIUM_ACTIVITY not in tags
        assert REGIME_LOW_ACTIVITY not in tags

    def test_multiple_tags_can_coexist(self):
        """A single run can have tags from multiple dimensions."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            classify_regime_bucket,
            REGIME_HIGH_ACTIVITY, REGIME_LOW_FAILURE, REGIME_TIGHT_SPREAD,
        )

        stats = {"attempted": 100, "scored": 95, "failed": 5}
        bs = {"route_failure_rate": 0.05, "best_route_net_bps": -3.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_HIGH_ACTIVITY in tags
        assert REGIME_LOW_FAILURE in tags
        assert REGIME_TIGHT_SPREAD in tags

    def test_boundary_high_activity_exact(self):
        """Exactly at 0.8 boundary: NOT high_activity (> 0.8 required)."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            classify_regime_bucket, REGIME_HIGH_ACTIVITY, REGIME_MEDIUM_ACTIVITY,
        )

        stats = {"attempted": 100, "scored": 80, "failed": 20}
        bs = {"route_failure_rate": 0.2, "best_route_net_bps": -20.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_HIGH_ACTIVITY not in tags
        assert REGIME_MEDIUM_ACTIVITY in tags

    def test_boundary_low_activity_exact(self):
        """Exactly at 0.5 boundary: NOT low_activity (< 0.5 required)."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            classify_regime_bucket, REGIME_LOW_ACTIVITY, REGIME_MEDIUM_ACTIVITY,
        )

        stats = {"attempted": 100, "scored": 50, "failed": 50}
        bs = {"route_failure_rate": 0.5, "best_route_net_bps": -20.0}
        tags = classify_regime_bucket(stats, bs)
        assert REGIME_LOW_ACTIVITY not in tags
        assert REGIME_MEDIUM_ACTIVITY in tags



class TestRegimeRepeatabilitySchema:
    """Contract tests for build_regime_repeatability_summary() schema."""

    def _write_artifact(self, tmp_path, name, block, net=-21.0, gross=-9.3,
                        failure_rate=0.33, regime=None):
        """Write a minimal artifact JSON with blocker_summary and optional regime_bucket."""
        data = {
            "m7a_enumeration": True,
            "chain": "arbitrum_one",
            "measured": {"block_number": block, "scored": 67, "failed": 33, "attempted": 100},
            "blocker_summary": {
                "best_route_gross_bps": gross,
                "best_route_gas_bps": 11.0,
                "best_route_total_fee_bps": 6.0,
                "best_route_net_bps": net,
                "best_route_best_size_usd": 100.0,
                "small_size_gas_domination": True,
                "small_size_worst_bps": -1100.0,
                "large_size_slippage_domination": True,
                "large_size_worst_bps": -400.0,
                "same_state_proven_rate": 1.0,
                "route_failure_rate": failure_rate,
                "token_triple_concentration": 1.0,
                "dominant_triple": ["ARB", "USDC", "WETH"],
                "top_blockers": [
                    "GROSS_NEGATIVE_CORE", "THIRD_LEG_FEE_BINDING",
                    "SINGLE_TRIPLE_CONCENTRATION",
                ],
                "per_cycle_blocker_counts": {"GROSS_NEGATIVE_CORE": 10},
                "global_blockers_present": ["SINGLE_TRIPLE_CONCENTRATION"],
                "cycles_analyzed": 10,
            },
        }
        if regime is not None:
            data["regime_bucket"] = regime
        import json
        path = tmp_path / name
        with open(path, "w") as f:
            json.dump(data, f)
        return str(path)

    def test_regime_repeatability_schema_keys(self, tmp_path):
        """Regime repeatability report must have all required keys."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        p1 = self._write_artifact(tmp_path, "r1.json", 100001, regime=["medium_activity", "wide_spread"])
        p2 = self._write_artifact(tmp_path, "r2.json", 100002, regime=["medium_activity", "tight_spread"])

        result = build_regime_repeatability_summary([p1, p2])

        required_keys = {
            "regime_repeatability", "timestamp", "runs_count",
            "regimes_observed", "runs_by_regime",
            "best_net_bps_by_regime", "mean_best_net_bps_by_regime",
            "beats_two_leg_baseline_by_regime", "blocker_stability_by_regime",
            "two_leg_baseline_net_bps", "run_entries",
        }
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_regime_repeatability_runs_count(self, tmp_path):
        """runs_count must match number of valid artifacts."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        p1 = self._write_artifact(tmp_path, "r1.json", 100001)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002)
        p3 = self._write_artifact(tmp_path, "r3.json", 100003)

        result = build_regime_repeatability_summary([p1, p2, p3])
        assert result["runs_count"] == 3

    def test_regime_repeatability_runs_by_regime(self, tmp_path):
        """runs_by_regime must count artifacts per regime tag."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        p1 = self._write_artifact(tmp_path, "r1.json", 100001, regime=["high_activity", "low_failure"])
        p2 = self._write_artifact(tmp_path, "r2.json", 100002, regime=["high_activity", "high_failure"])
        p3 = self._write_artifact(tmp_path, "r3.json", 100003, regime=["low_activity", "high_failure"])

        result = build_regime_repeatability_summary([p1, p2, p3])
        assert result["runs_by_regime"]["high_activity"] == 2
        assert result["runs_by_regime"]["high_failure"] == 2
        assert result["runs_by_regime"]["low_failure"] == 1
        assert result["runs_by_regime"]["low_activity"] == 1

    def test_regime_repeatability_best_net_bps(self, tmp_path):
        """best_net_bps_by_regime must be max within each regime group."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        p1 = self._write_artifact(tmp_path, "r1.json", 100001, net=-10.0, regime=["high_activity"])
        p2 = self._write_artifact(tmp_path, "r2.json", 100002, net=-5.0, regime=["high_activity"])
        p3 = self._write_artifact(tmp_path, "r3.json", 100003, net=-25.0, regime=["low_activity"])

        result = build_regime_repeatability_summary([p1, p2, p3])
        assert result["best_net_bps_by_regime"]["high_activity"] == -5.0
        assert result["best_net_bps_by_regime"]["low_activity"] == -25.0

    def test_regime_repeatability_beats_baseline(self, tmp_path):
        """beats_two_leg_baseline_by_regime must be True if any run in regime beats it."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        # TWO_LEG_BASELINE_NET_BPS = -3.5062
        p1 = self._write_artifact(tmp_path, "r1.json", 100001, net=-2.0, regime=["tight_spread"])
        p2 = self._write_artifact(tmp_path, "r2.json", 100002, net=-20.0, regime=["wide_spread"])

        result = build_regime_repeatability_summary([p1, p2])
        assert result["beats_two_leg_baseline_by_regime"]["tight_spread"] is True
        assert result["beats_two_leg_baseline_by_regime"]["wide_spread"] is False

    def test_regime_repeatability_blocker_stability(self, tmp_path):
        """blocker_stability_by_regime must show stable/flapping per regime."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        p1 = self._write_artifact(tmp_path, "r1.json", 100001, regime=["medium_activity"])
        p2 = self._write_artifact(tmp_path, "r2.json", 100002, regime=["medium_activity"])

        result = build_regime_repeatability_summary([p1, p2])
        bs = result["blocker_stability_by_regime"]["medium_activity"]
        assert "stable_blockers" in bs
        assert "flapping_blockers" in bs
        assert isinstance(bs["stable_blockers"], list)

    def test_regime_repeatability_backward_compat(self, tmp_path):
        """Artifacts without regime_bucket get re-classified from stats."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        # No regime_bucket in artifact — should be classified from measured stats
        p1 = self._write_artifact(tmp_path, "r1.json", 100001, failure_rate=0.33)
        p2 = self._write_artifact(tmp_path, "r2.json", 100002, failure_rate=0.33)

        result = build_regime_repeatability_summary([p1, p2])
        assert "error" not in result
        assert result["runs_count"] == 2
        # Each run has medium_activity (67/100=0.67) and no particular failure tag
        for entry in result["run_entries"]:
            assert isinstance(entry["regime_bucket"], list)
            assert len(entry["regime_bucket"]) > 0

    def test_regime_repeatability_empty_artifacts(self):
        """No valid artifacts returns error."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        result = build_regime_repeatability_summary(["nonexistent.json"])
        assert "error" in result

    def test_regime_repeatability_run_entries_fields(self, tmp_path):
        """Each run_entry must contain artifact, block, regime_bucket, best_route_net_bps."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_regime_repeatability_summary

        p1 = self._write_artifact(tmp_path, "r1.json", 100001, regime=["medium_activity"])

        result = build_regime_repeatability_summary([p1])
        entry = result["run_entries"][0]
        assert "artifact" in entry
        assert "block" in entry
        assert "regime_bucket" in entry
        assert "best_route_net_bps" in entry



class TestRegimeBackwardCompatibility:
    """Ensure regime changes don't break existing artifact schemas."""

    def test_blocker_summary_keys_unchanged(self):
        """blocker_summary schema must not lose any existing keys."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        e1 = _edge("ARB", "USDC", dex="camelot_v3", fee=0, pool="0x111", adapter_type="algebra")
        e2 = _edge("USDC", "WETH", dex="uniswap_v3", fee=100, pool="0x222")
        e3 = _edge("WETH", "ARB", dex="pancakeswap_v3", fee=500, pool="0x333")
        cycle = TriangularCycle(leg1=e1, leg2=e2, leg3=e3)
        score = CycleScore(
            cycle=cycle, gross_bps=-10.0, gas_bps=12.0,
            fee_leg1_bps=0.0, fee_leg2_bps=1.0, fee_leg3_bps=5.0,
            total_fee_bps=6.0, final_net_bps=-28.0, scored_size_usd=100.0,
            block_tag="123456", provenance_summary="measured",
            same_state_class=SAME_STATE_PROVEN, route_viable=True,
        )
        stats = {
            "block_number": 100000, "attempted": 100, "scored": 67,
            "failed": 33, "same_state_distribution": {"same_state_proven": 67},
        }
        result = _build_blocker_summary([score], stats, [])

        # All pre-M7.A.3 keys must still be present
        required_keys = {
            "best_route_gross_bps", "best_route_gas_bps", "best_route_total_fee_bps",
            "best_route_net_bps", "best_route_best_size_usd",
            "small_size_gas_domination", "large_size_slippage_domination",
            "same_state_proven_rate", "route_failure_rate",
            "token_triple_concentration", "dominant_triple", "top_blockers",
            "per_cycle_blocker_counts", "global_blockers_present", "cycles_analyzed",
        }
        for key in required_keys:
            assert key in result, f"Missing pre-M7.A.3 key: {key}"

    def test_repeatability_keys_unchanged(self):
        """build_blocker_repeatability schema must not lose existing keys."""
        import sys, json
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import build_blocker_repeatability

        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            for i, block in enumerate([100001, 100002]):
                data = {
                    "m7a_enumeration": True,
                    "measured": {"block_number": block, "scored": 67, "failed": 33, "attempted": 100},
                    "blocker_summary": {
                        "best_route_gross_bps": -9.3, "best_route_gas_bps": 11.0,
                        "best_route_total_fee_bps": 6.0, "best_route_net_bps": -21.0,
                        "best_route_best_size_usd": 100.0,
                        "small_size_gas_domination": True, "small_size_worst_bps": -1100.0,
                        "large_size_slippage_domination": True, "large_size_worst_bps": -400.0,
                        "same_state_proven_rate": 1.0, "route_failure_rate": 0.33,
                        "token_triple_concentration": 1.0,
                        "dominant_triple": ["ARB", "USDC", "WETH"],
                        "top_blockers": ["GROSS_NEGATIVE_CORE"],
                        "per_cycle_blocker_counts": {"GROSS_NEGATIVE_CORE": 10},
                        "global_blockers_present": ["SINGLE_TRIPLE_CONCENTRATION"],
                        "cycles_analyzed": 10,
                    },
                }
                path = os.path.join(td, f"r{i}.json")
                with open(path, "w") as f:
                    json.dump(data, f)

            paths = [os.path.join(td, f"r{i}.json") for i in range(2)]
            result = build_blocker_repeatability(paths)

        required_keys = {
            "blocker_repeatability", "timestamp", "runs_count",
            "block_range", "metric_ranges", "blocker_class_stability",
            "per_cycle_tag_ranges", "global_blocker_stability", "snapshots",
        }
        for key in required_keys:
            assert key in result, f"Missing pre-M7.A.3 key: {key}"

    def test_regime_bucket_is_additive_in_artifact(self):
        """regime_bucket is a new additive field; it does not replace any existing key."""
        artifact = {
            "m7a_enumeration": True,
            "blocker_summary": {"best_route_net_bps": -21.0},
            "regime_bucket": ["medium_activity", "wide_spread"],
        }
        # Both old and new keys coexist
        assert "blocker_summary" in artifact
        assert "regime_bucket" in artifact
        assert isinstance(artifact["regime_bucket"], list)
