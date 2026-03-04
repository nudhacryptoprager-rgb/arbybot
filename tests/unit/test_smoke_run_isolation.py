# FILE: tests/unit/test_smoke_run_isolation.py
"""
Unit tests for SMOKE/COVERAGE run isolation (NORM-only rolling policy).

Tests verify that:
1. SMOKE runs are NOT added to the rolling aggregator
2. COVERAGE runs are NOT added to the rolling aggregator
3. NORMAL runs ARE added to the rolling aggregator
4. run_kind is correctly propagated from config to artifacts
5. inspect_rolling reads chain_keys from correct source

v3.2.11: Extended NORM-only policy (SMOKE + COVERAGE excluded).
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


class TestCoverageRunIsolation:
    """Test COVERAGE runs are excluded from rolling window (v3.2.11)."""
    
    def test_coverage_run_not_added_to_aggregator(self, tmp_path: Path):
        """COVERAGE runs should be skipped and not added to aggregator runs list."""
        agg_path = tmp_path / "m4_stability_agg.json"
        
        # Create a COVERAGE run_summary
        coverage_run_summary = {
            "run_id": "coverage_20260304_100000",
            "run_kind": "COVERAGE",  # This should be excluded
            "status": "PASS",
            "reasons": [],
            "metrics": {
                "signals_count": 10,
                "included_signals_count": 10,
                "excluded_signals_count": 0,
                "total_net_usdc": 5.0,
                "mae_net_usdc": 0.05,
                "est_sign_correct_rate": 1.0,
                "fragile_rate": 0.0,
            },
            "inputs": {
                "chain_key": "linea",
                "chain_id": 59144,
                "run_kind": "COVERAGE",
                "pairs": ["WETH/USDC", "WBTC/WETH"],
                "routes": ["lynex_v3->lynex_v3"],
            },
            "run_context": {
                "run_timestamp": "2026-03-04T10:00:00+00:00",
            },
        }
        
        # Emit to aggregator
        agg_data = emit_to_aggregator_light(coverage_run_summary, agg_path)
        
        # COVERAGE run should NOT be added
        runs_ids = [r.get("run_id") for r in agg_data.get("runs", [])]
        assert "coverage_20260304_100000" not in runs_ids, \
            "COVERAGE run should be excluded from aggregator runs list"
        assert len(agg_data.get("runs", [])) == 0, \
            "Aggregator should have 0 runs after COVERAGE run"
    
    def test_coverage_run_does_not_pollute_chain_keys(self, tmp_path: Path):
        """COVERAGE runs should not affect chain_keys in quick_stats."""
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
        
        # Now try to add a COVERAGE linea run (should be skipped)
        coverage_run = {
            "run_id": "coverage_linea_20260304_100001",
            "run_kind": "COVERAGE",
            "status": "PASS",
            "reasons": [],
            "metrics": {
                "signals_count": 10,
                "included_signals_count": 10,
                "excluded_signals_count": 0,
                "total_net_usdc": 5.0,
                "mae_net_usdc": 0.05,
                "est_sign_correct_rate": 1.0,
                "fragile_rate": 0.0,
            },
            "inputs": {
                "chain_key": "linea",
                "chain_id": 59144,
                "run_kind": "COVERAGE",
                "pairs": ["WETH/USDC"],
                "routes": ["lynex_v3->lynex_v3"],
            },
            "run_context": {
                "run_timestamp": "2026-03-04T10:00:01+00:00",
            },
        }
        agg_data = emit_to_aggregator_light(coverage_run, agg_path)
        
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
    
    def test_coverage_run_does_not_affect_data_run_rate(self, tmp_path: Path):
        """COVERAGE runs should not affect data_run_rate calculation."""
        agg_path = tmp_path / "m4_stability_agg.json"
        
        # Add 5 normal runs with data
        for i in range(5):
            normal_run = {
                "run_id": f"normal_run_{i}",
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
                    "run_timestamp": f"2026-03-04T10:0{i}:00+00:00",
                },
            }
            emit_to_aggregator_light(normal_run, agg_path)
        
        # Check data_run_rate before coverage runs
        agg_data = ensure_rolling_agg_exists(agg_path)
        data_run_rate_before = agg_data.get("quick_stats", {}).get("data_run_rate", 0)
        
        # Add 5 COVERAGE runs (should be skipped entirely)
        for i in range(5):
            coverage_run = {
                "run_id": f"coverage_run_{i}",
                "run_kind": "COVERAGE",
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
                    "run_kind": "COVERAGE",
                },
                "run_context": {
                    "run_timestamp": f"2026-03-04T11:0{i}:00+00:00",
                },
            }
            emit_to_aggregator_light(coverage_run, agg_path)
        
        # data_run_rate should be unchanged (COVERAGE runs skipped)
        agg_data = ensure_rolling_agg_exists(agg_path)
        data_run_rate_after = agg_data.get("quick_stats", {}).get("data_run_rate", 0)
        
        assert data_run_rate_after == data_run_rate_before, \
            f"data_run_rate changed from {data_run_rate_before} to {data_run_rate_after} after COVERAGE runs"
        assert agg_data.get("runs_in_window") == 5, \
            f"runs_in_window should be 5 (COVERAGE skipped), got {agg_data.get('runs_in_window')}"


class TestInspectRollingChainKeys:
    """Test inspect_rolling.py reads chain_keys from correct source (v3.2.11)."""
    
    def test_inspect_rolling_chain_keys_from_agg_quick_stats(self, tmp_path: Path):
        """
        inspect_rolling --json should show chain_keys from agg.quick_stats, not _latest.
        
        This ensures chain_keys reflects the aggregate window state, not just latest run.
        """
        # This is a structural test - we verify the print_summary function
        # uses agg_qs.get("chain_keys") not artifacts.get("latest").get("chain_keys")
        
        from scripts.inspect_rolling import print_summary
        import io
        import sys
        
        # Create mock artifacts that simulate the bug scenario:
        # - agg.quick_stats.chain_keys = ['arbitrum_one', 'linea']
        # - _latest.chain_keys = [] (empty/missing)
        mock_artifacts = {
            "agg": {
                "agg_status": "PASS",
                "agg_reasons": [],
                "runs_in_window": 10,
                "quick_stats": {
                    "total_net_usdc": 50.0,
                    "unique_pairs": 5,
                    "unique_routes_cross_dex": 2,
                    "chain_key": "MIXED",
                    # This is the canonical source
                    "chain_keys": ["arbitrum_one", "linea"],
                },
            },
            "latest": {
                "data_run_rate": 0.8,
                # This might be empty or stale
                "chain_keys": [],  # Bug scenario: _latest has empty chain_keys
                "inputs": {
                    "chain_key": "arbitrum_one",
                },
            },
            "run_summary": {
                "inputs": {"run_dir_name": "test_run"},
                "run_context": {"run_timestamp": "2026-03-04T10:00:00Z"},
                "metrics": {
                    "included_signals_count": 5,
                    "excluded_signals_count": 0,
                },
            },
        }
        
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = captured = io.StringIO()
        
        try:
            print_summary(mock_artifacts, excluded=[], as_json=True)
            output = captured.getvalue()
        finally:
            sys.stdout = old_stdout
        
        import json
        result = json.loads(output)
        
        # chain_keys should come from agg.quick_stats (canonical source)
        assert result["rolling"]["chain_keys"] == ["arbitrum_one", "linea"], \
            f"chain_keys should be from agg.quick_stats: {result['rolling']['chain_keys']}"
        
        # window_chain_key should show MIXED (aggregate state)
        assert result["rolling"]["window_chain_key"] == "MIXED", \
            f"window_chain_key should be 'MIXED': {result['rolling']['window_chain_key']}"
        
        # latest_chain_key should show the current run's chain
        assert result["rolling"]["latest_chain_key"] == "arbitrum_one", \
            f"latest_chain_key should be 'arbitrum_one': {result['rolling']['latest_chain_key']}"
