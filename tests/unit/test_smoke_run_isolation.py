# FILE: tests/unit/test_smoke_run_isolation.py
"""
Unit tests for SMOKE run isolation (NORM-only rolling policy).

Tests verify that:
1. SMOKE runs are NOT added to the rolling aggregator
2. NORMAL runs ARE added to the rolling aggregator
3. run_kind is correctly propagated from config to artifacts

v3.2.10: SMOKE run isolation for clean rolling metrics.
"""

import json
import pytest
import tempfile
from pathlib import Path

from m4.rolling_store import emit_to_aggregator_light, ensure_rolling_agg_exists


class TestSmokeRunIsolation:
    """Test SMOKE runs are excluded from rolling window."""
    
    def test_smoke_run_not_added_to_aggregator(self, tmp_path: Path):
        """SMOKE runs should be skipped and not added to aggregator runs list."""
        agg_path = tmp_path / "m4_stability_agg.json"
        
        # Create a SMOKE run_summary
        smoke_run_summary = {
            "run_id": "smoke_20260304_100000",
            "run_kind": "SMOKE",  # This should be excluded
            "status": "NO_DATA",
            "reasons": ["NO_DATA"],
            "metrics": {
                "signals_count": 0,
                "included_signals_count": 0,
                "excluded_signals_count": 0,
                "total_net_usdc": 0.0,
                "mae_net_usdc": 0.0,
                "est_sign_correct_rate": 1.0,
                "fragile_rate": 0.0,
            },
            "inputs": {
                "chain_key": "linea",
                "chain_id": 59144,
                "run_kind": "SMOKE",
            },
            "run_context": {
                "run_timestamp": "2026-03-04T10:00:00+00:00",
            },
        }
        
        # Emit to aggregator
        agg_data = emit_to_aggregator_light(smoke_run_summary, agg_path)
        
        # SMOKE run should NOT be added
        runs_ids = [r.get("run_id") for r in agg_data.get("runs", [])]
        assert "smoke_20260304_100000" not in runs_ids, \
            "SMOKE run should be excluded from aggregator runs list"
        assert len(agg_data.get("runs", [])) == 0, \
            "Aggregator should have 0 runs after SMOKE run"
    
    def test_normal_run_added_to_aggregator(self, tmp_path: Path):
        """NORMAL runs should be added to aggregator runs list."""
        agg_path = tmp_path / "m4_stability_agg.json"
        
        # Create a NORMAL run_summary
        normal_run_summary = {
            "run_id": "normal_20260304_100000",
            "run_kind": "NORMAL",  # This should be included
            "status": "PASS",
            "reasons": [],
            "metrics": {
                "signals_count": 5,
                "included_signals_count": 5,
                "excluded_signals_count": 0,
                "total_net_usdc": 1.5,
                "mae_net_usdc": 0.02,
                "est_sign_correct_rate": 0.8,
                "fragile_rate": 0.1,
            },
            "inputs": {
                "chain_key": "arbitrum_one",
                "chain_id": 42161,
                "run_kind": "NORMAL",
                "pairs": ["WETH/USDC"],
                "routes": ["uniswap_v3->sushiswap_v3"],
            },
            "run_context": {
                "run_timestamp": "2026-03-04T10:00:00+00:00",
            },
        }
        
        # Emit to aggregator
        agg_data = emit_to_aggregator_light(normal_run_summary, agg_path)
        
        # NORMAL run should be added
        runs_ids = [r.get("run_id") for r in agg_data.get("runs", [])]
        assert "normal_20260304_100000" in runs_ids, \
            "NORMAL run should be added to aggregator runs list"
        assert len(agg_data.get("runs", [])) == 1, \
            "Aggregator should have 1 run after NORMAL run"
    
    def test_smoke_run_default_kind_is_normal(self, tmp_path: Path):
        """When run_kind is not set, default to NORMAL (included in rolling)."""
        agg_path = tmp_path / "m4_stability_agg.json"
        
        # Create a run_summary WITHOUT run_kind (should default to NORMAL)
        run_summary_no_kind = {
            "run_id": "default_20260304_100000",
            # NOTE: No run_kind field - should default to NORMAL
            "status": "PASS",
            "reasons": [],
            "metrics": {
                "signals_count": 3,
                "included_signals_count": 3,
                "excluded_signals_count": 0,
                "total_net_usdc": 0.5,
                "mae_net_usdc": 0.01,
                "est_sign_correct_rate": 1.0,
                "fragile_rate": 0.0,
            },
            "inputs": {
                "chain_key": "arbitrum_one",
                "chain_id": 42161,
                "pairs": ["WETH/USDC"],
                "routes": ["uniswap_v3->sushiswap_v3"],
            },
            "run_context": {
                "run_timestamp": "2026-03-04T10:00:00+00:00",
            },
        }
        
        # Emit to aggregator
        agg_data = emit_to_aggregator_light(run_summary_no_kind, agg_path)
        
        # Should be treated as NORMAL and added
        runs_ids = [r.get("run_id") for r in agg_data.get("runs", [])]
        assert "default_20260304_100000" in runs_ids, \
            "Run without run_kind should default to NORMAL and be added"
    
    def test_smoke_run_does_not_pollute_chain_keys(self, tmp_path: Path):
        """SMOKE runs should not affect chain_keys in quick_stats."""
        agg_path = tmp_path / "m4_stability_agg.json"
        
        # First add a normal arbitrum run
        normal_run = {
            "run_id": "normal_arb_20260304_100000",
            "run_kind": "NORMAL",
            "status": "PASS",
            "reasons": [],
            "metrics": {
                "signals_count": 5,
                "included_signals_count": 5,
                "excluded_signals_count": 0,
                "total_net_usdc": 1.0,
                "mae_net_usdc": 0.01,
                "est_sign_correct_rate": 1.0,
                "fragile_rate": 0.0,
            },
            "inputs": {
                "chain_key": "arbitrum_one",
                "chain_id": 42161,
                "pairs": ["WETH/USDC"],
                "routes": ["uniswap_v3->sushiswap_v3"],
            },
            "run_context": {
                "run_timestamp": "2026-03-04T10:00:00+00:00",
            },
        }
        emit_to_aggregator_light(normal_run, agg_path)
        
        # Now try to add a SMOKE linea run (should be skipped)
        smoke_run = {
            "run_id": "smoke_linea_20260304_100001",
            "run_kind": "SMOKE",
            "status": "NO_DATA",
            "reasons": ["NO_DATA"],
            "metrics": {
                "signals_count": 0,
                "included_signals_count": 0,
                "excluded_signals_count": 0,
                "total_net_usdc": 0.0,
                "mae_net_usdc": 0.0,
                "est_sign_correct_rate": 1.0,
                "fragile_rate": 0.0,
            },
            "inputs": {
                "chain_key": "linea",
                "chain_id": 59144,
                "run_kind": "SMOKE",
            },
            "run_context": {
                "run_timestamp": "2026-03-04T10:00:01+00:00",
            },
        }
        agg_data = emit_to_aggregator_light(smoke_run, agg_path)
        
        # Chain keys should only contain arbitrum_one (not linea)
        quick_stats = agg_data.get("quick_stats", {})
        chain_keys = quick_stats.get("chain_keys", [])
        chain_key = quick_stats.get("chain_key")
        
        assert chain_key == "arbitrum_one", \
            f"chain_key should be 'arbitrum_one' not '{chain_key}'"
        assert "linea" not in chain_keys, \
            f"'linea' should not be in chain_keys: {chain_keys}"
        assert chain_keys == ["arbitrum_one"], \
            f"chain_keys should be ['arbitrum_one'] not {chain_keys}"


class TestRunKindPropagation:
    """Test run_kind is correctly propagated through the pipeline."""
    
    def test_config_run_kind_smoke_value(self):
        """Verify SMOKE is a valid run_kind value."""
        from m4.policy import RunKind
        assert RunKind.SMOKE == "SMOKE"
        assert RunKind.NORMAL == "NORMAL"
        assert RunKind.COVERAGE == "COVERAGE"
    
    def test_truth_report_includes_run_kind(self, tmp_path: Path):
        """build_truth_data should include run_kind in config_params."""
        from strategy.artifacts import build_truth_data
        
        config = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "run_kind": "SMOKE",  # Should be propagated
            "min_spread_bps": 10,
            "paper_size_usd": 1000,
        }
        stats = {
            "quotes_total": 0,
            "quotes_fetched": 0,
            "dexes_active": 0,
            "price_sanity_passed": 0,
            "price_sanity_failed": 0,
            "price_stability_factor": 1.0,
            "rpc_errors": 0,
            "rpc_success_rate": 1.0,
        }
        
        truth_data = build_truth_data(
            config=config,
            stats=stats,
            current_block=100,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=10,
        )
        
        config_params = truth_data.get("config_params", {})
        assert config_params.get("run_kind") == "SMOKE", \
            f"run_kind should be in config_params: {config_params}"
