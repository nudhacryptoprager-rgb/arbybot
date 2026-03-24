# tests/unit/test_signal_funnel.py
"""
R39h: Signal funnel observability tests.

Verifies that the intent→excludes→cross_dex→signals→RT funnel is tracked
through discovery/runtime.py → chain_stats.py → long_scan_summary.py.
"""
import pytest


class TestRuntimeStatsIntentPairsCount:
    """intent_pairs_count field in RuntimeStats."""

    def test_field_exists_and_defaults_zero(self):
        from discovery.runtime import RuntimeStats

        stats = RuntimeStats()
        assert stats.intent_pairs_count == 0

    def test_to_dict_includes_intent_pairs_count(self):
        from discovery.runtime import RuntimeStats

        stats = RuntimeStats(intent_pairs_count=7)
        d = stats.to_dict()
        assert d["intent_pairs_count"] == 7


class TestChainStatsFunnelFields:
    """chain_stats.new_chain_stats() includes funnel fields."""

    def test_new_chain_stats_has_funnel_fields(self):
        from strategy.chain_stats import new_chain_stats

        cs = new_chain_stats()
        assert "last_intent_pairs_count" in cs
        assert cs["last_intent_pairs_count"] is None
        assert "last_pairs_after_excludes" in cs
        assert cs["last_pairs_after_excludes"] is None

    def test_update_chain_stats_extracts_funnel(self):
        from strategy.chain_stats import new_chain_stats, update_chain_stats

        cs = new_chain_stats()
        scan_stats = {
            "discovery_runtime": {
                "pairs_evaluated": 9,
                "pairs_resolved": 7,
                "cross_dex_pairs_count": 5,
                "pairs_skipped_no_tokens": 0,
                "pairs_skipped_no_pool": 1,
                "pairs_skipped_single_dex": 1,
                "pairs_skipped_excluded": 2,
                "intent_pairs_count": 11,
            }
        }
        update_chain_stats(
            cs,
            exit_code=0,
            run_dir=None,
            summary={"status": "PASS"},
            gate_result={"cross_dex_pairs_count": 5},
            scan_stats=scan_stats,
            truth_report=None,
        )
        assert cs["last_intent_pairs_count"] == 11
        assert cs["last_pairs_after_excludes"] == 7  # 9 evaluated - 2 excluded
        assert cs["last_cross_dex_pairs_count"] == 5
        # Check nested dict also has it
        assert cs["last_discovery_runtime"]["intent_pairs_count"] == 11

    def test_update_chain_stats_fallback_to_pairs_evaluated(self):
        """When intent_pairs_count is 0 (legacy), fall back to pairs_evaluated."""
        from strategy.chain_stats import new_chain_stats, update_chain_stats

        cs = new_chain_stats()
        scan_stats = {
            "discovery_runtime": {
                "pairs_evaluated": 5,
                "pairs_resolved": 3,
                "cross_dex_pairs_count": 2,
                "pairs_skipped_no_tokens": 0,
                "pairs_skipped_no_pool": 1,
                "pairs_skipped_single_dex": 1,
                "pairs_skipped_excluded": 0,
                # No intent_pairs_count (legacy artifact)
            }
        }
        update_chain_stats(
            cs,
            exit_code=0,
            run_dir=None,
            summary={"status": "PASS"},
            gate_result=None,
            scan_stats=scan_stats,
            truth_report=None,
        )
        # Falls back to pairs_evaluated
        assert cs["last_intent_pairs_count"] == 5
        assert cs["last_pairs_after_excludes"] == 5  # 5 - 0


class TestLongScanSummaryFunnel:
    """build_summary() includes signal_funnel at top level and per-chain."""

    def _make_per_chain(self) -> dict:
        from strategy.chain_stats import new_chain_stats

        arb = new_chain_stats()
        arb["config"] = "real_minimal.yaml"
        arb["runs"] = 5
        arb["pass"] = 5
        arb["included_signals_total"] = 30
        arb["roundtrip_evaluated_total"] = 3
        arb["last_intent_pairs_count"] = 11
        arb["last_pairs_after_excludes"] = 9
        arb["last_cross_dex_pairs_count"] = 7

        base = new_chain_stats()
        base["config"] = "onboard_base_stage2.yaml"
        base["runs"] = 3
        base["pass"] = 2
        base["no_data"] = 1
        base["included_signals_total"] = 5
        base["roundtrip_evaluated_total"] = 0
        base["last_intent_pairs_count"] = 9
        base["last_pairs_after_excludes"] = 7
        base["last_cross_dex_pairs_count"] = 4

        return {"arbitrum_one": arb, "base": base}

    def test_build_summary_has_signal_funnel(self):
        from strategy.long_scan_summary import build_summary

        per_chain = self._make_per_chain()
        summary = build_summary(per_chain, wall_seconds=60.0, warnings=[])

        assert "signal_funnel" in summary
        sf = summary["signal_funnel"]
        assert sf["intent_pairs_total"] == 20  # 11 + 9
        assert sf["pairs_after_excludes_total"] == 16  # 9 + 7
        assert sf["cross_dex_pairs_total"] == 11  # 7 + 4
        assert sf["spread_signals_total"] == 35  # 30 + 5
        assert sf["rt_evaluated_total"] == 3  # 3 + 0

    def test_per_chain_signal_funnel(self):
        from strategy.long_scan_summary import build_summary

        per_chain = self._make_per_chain()
        summary = build_summary(per_chain, wall_seconds=60.0, warnings=[])

        arb_sf = summary["per_chain"]["arbitrum_one"]["signal_funnel"]
        assert arb_sf["intent_pairs"] == 11
        assert arb_sf["pairs_after_excludes"] == 9
        assert arb_sf["cross_dex_pairs"] == 7
        assert arb_sf["spread_signals"] == 30
        assert arb_sf["rt_evaluated"] == 3

        base_sf = summary["per_chain"]["base"]["signal_funnel"]
        assert base_sf["intent_pairs"] == 9
        assert base_sf["cross_dex_pairs"] == 4

    def test_schema_version_updated(self):
        from strategy.long_scan_summary import build_summary

        per_chain = self._make_per_chain()
        summary = build_summary(per_chain, wall_seconds=10.0, warnings=[])
        assert "v1.15" in summary["schema"]
