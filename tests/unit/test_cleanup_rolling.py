#!/usr/bin/env python3
"""
Tests for scripts/cleanup_rolling.py

v3.2.23: Add tests for regenerate_quick_stats full contract compliance.
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.cleanup_rolling import regenerate_quick_stats


class TestRegenerateQuickStatsContract:
    """Tests for regenerate_quick_stats full contract compliance."""
    
    def test_empty_runs_returns_full_contract(self):
        """Test that empty runs returns all required fields."""
        result = regenerate_quick_stats([], "arbitrum_one")
        
        # v3.2.23: Must have all contract fields
        required_fields = [
            "runs_in_window", "pass_count", "fail_count", "no_data_count",
            "data_run_count", "warn_count_core", "low_sample_count",
            "pass_rate", "effective_pass_rate", "data_run_rate", "no_data_rate",
            "warn_rate_core", "low_sample_rate", "fail_rate", "total_signals",
            "fragile_rate_p50", "fragile_rate_p90", "mae_p90", "total_net_usdc",
            "avg_net_usdc", "net_p10", "mae_p50", "unique_net_values",
            "net_diversity_rate", "unique_pairs", "unique_routes",
            "unique_routes_cross_dex", "infra_fail_count", "infra_fail_rate",
            "coverage_runs_count", "coverage_signals_total", "coverage_net_usdc",
            "signals_per_run_p50", "signals_per_run_p90", "signals_per_run_avg",
            "chain_key", "chain_keys",
        ]
        
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"
        
        assert result["chain_key"] == "arbitrum_one"
        assert result["chain_keys"] == ["arbitrum_one"]
    
    def test_single_pass_run(self):
        """Test computation with a single passing run."""
        runs = [
            {
                "run_id": "run_1",
                "run_status": "PASS",
                "run_kind": "NORMAL",
                "is_data_run": True,
                "signals_count": 5,
                "included_signals_count": 5,
                "net_usdc": 10.0,
                "mae": 0.5,
                "fragile_rate": 0.1,
                "reasons": [],
                "included_pairs": ["WETH/USDC"],
                "included_routes": ["route_1"],
            }
        ]
        
        result = regenerate_quick_stats(runs, "arbitrum_one")
        
        assert result["pass_count"] == 1
        assert result["fail_count"] == 0
        assert result["data_run_count"] == 1
        assert result["total_signals"] == 5
        assert result["total_net_usdc"] == 10.0
        assert result["pass_rate"] == 1.0
        assert result["effective_pass_rate"] == 1.0
        assert result["data_run_rate"] == 1.0
    
    def test_mixed_runs_with_no_data(self):
        """Test computation with NO_DATA runs."""
        runs = [
            {
                "run_id": "run_1",
                "run_status": "PASS",
                "run_kind": "NORMAL",
                "is_data_run": True,
                "signals_count": 5,
                "included_signals_count": 5,
                "net_usdc": 10.0,
                "mae": 0.5,
                "fragile_rate": 0.1,
                "reasons": [],
            },
            {
                "run_id": "run_2",
                "run_status": "NO_DATA",
                "run_kind": "NORMAL",
                "is_data_run": False,
                "signals_count": 0,
                "included_signals_count": 0,
                "net_usdc": 0.0,
                "mae": 0.0,
                "fragile_rate": 0.0,
                "reasons": ["NO_DATA"],
            },
        ]
        
        result = regenerate_quick_stats(runs, "arbitrum_one")
        
        assert result["no_data_count"] == 1
        assert result["data_run_count"] == 1
        assert result["no_data_rate"] == 0.5
        assert result["data_run_rate"] == 0.5
    
    def test_coverage_runs_separated(self):
        """Test that COVERAGE runs are tracked separately."""
        runs = [
            {
                "run_id": "normal_1",
                "run_kind": "NORMAL",
                "is_data_run": True,
                "signals_count": 5,
                "included_signals_count": 5,
                "net_usdc": 10.0,
                "mae": 0.5,
                "fragile_rate": 0.1,
                "reasons": [],
            },
            {
                "run_id": "coverage_1",
                "run_kind": "COVERAGE",
                "is_data_run": True,
                "signals_count": 3,
                "included_signals_count": 3,
                "net_usdc": 5.0,
                "mae": 0.3,
                "fragile_rate": 0.1,
                "reasons": [],
            },
        ]
        
        result = regenerate_quick_stats(runs, "arbitrum_one")
        
        # COVERAGE runs tracked separately
        assert result["coverage_runs_count"] == 1
        assert result["coverage_signals_total"] == 3
        assert result["coverage_net_usdc"] == 5.0
        
        # NORMAL runs for main KPIs
        # data_run_count should be 1 (only NORMAL run)
        assert result["data_run_count"] == 1
    
    def test_low_sample_runs(self):
        """Test that low sample runs are counted."""
        runs = [
            {
                "run_id": "low_sample_1",
                "run_kind": "NORMAL",
                "is_data_run": False,
                "signals_count": 2,  # Below MIN_SIGNALS_FOR_PASS
                "included_signals_count": 2,
                "net_usdc": 1.0,
                "reasons": ["WARN_LOW_SAMPLE"],
            },
        ]
        
        result = regenerate_quick_stats(runs, "arbitrum_one")
        
        assert result["low_sample_count"] >= 1
        assert result["low_sample_rate"] > 0
    
    def test_diversity_metrics(self):
        """Test unique pairs/routes diversity calculation."""
        runs = [
            {
                "run_id": "run_1",
                "run_kind": "NORMAL",
                "is_data_run": True,
                "signals_count": 5,
                "included_signals_count": 5,
                "net_usdc": 10.0,
                "reasons": [],
                "included_pairs": ["WETH/USDC", "WBTC/USDC"],
                "included_routes": ["route_1", "route_2"],
            },
            {
                "run_id": "run_2",
                "run_kind": "NORMAL",
                "is_data_run": True,
                "signals_count": 3,
                "included_signals_count": 3,
                "net_usdc": 5.0,
                "reasons": [],
                "included_pairs": ["WETH/USDC", "ARB/USDC"],  # 1 overlap
                "included_routes": ["route_1", "route_3"],    # 1 overlap
            },
        ]
        
        result = regenerate_quick_stats(runs, "arbitrum_one")
        
        # Should have unique pairs across all runs
        assert result["unique_pairs"] == 3  # WETH/USDC, WBTC/USDC, ARB/USDC
        assert result["unique_routes"] == 3   # route_1, route_2, route_3


class TestQuickStatsPercentiles:
    """Tests for percentile calculations in quick_stats."""
    
    def test_percentile_values(self):
        """Test that percentile values are calculated correctly."""
        runs = [
            {"run_kind": "NORMAL", "is_data_run": True, "signals_count": i * 2, 
             "included_signals_count": i * 2, "net_usdc": i * 5.0, 
             "mae": i * 0.1, "fragile_rate": i * 0.05, "reasons": []}
            for i in range(1, 11)  # 10 runs with increasing values
        ]
        
        result = regenerate_quick_stats(runs, "arbitrum_one")
        
        # Percentile fields should exist and be numeric
        assert "fragile_rate_p50" in result
        assert "fragile_rate_p90" in result
        assert "mae_p50" in result
        assert "mae_p90" in result
        assert "signals_per_run_p50" in result
        assert "signals_per_run_p90" in result
        
        # p90 should be >= p50
        assert result["fragile_rate_p90"] >= result["fragile_rate_p50"]
        assert result["mae_p90"] >= result["mae_p50"]
        assert result["signals_per_run_p90"] >= result["signals_per_run_p50"]
