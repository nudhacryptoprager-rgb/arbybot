"""
Unit tests for scripts/inspect_run_dir.py

Tests the parsing logic with minimal fixtures (no data/runs artifacts).
"""
import json
import tempfile
from pathlib import Path

import pytest


def test_inspect_run_dir_opportunity_engine_parsing():
    """
    Contract: inspect_run_dir must read opportunity_engine from
    truth_report.stats.opportunity_engine.summary.* (v3.2.11 schema).
    """
    # Import at test time to avoid import errors
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    # Create temp runDir with minimal truth_report and run_summary
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        # Minimal truth_report with v3.2.11 schema
        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 123456,
            "spread_signals": [{"id": 1}, {"id": 2}],
            "stats": {
                "quotes_total": 10,
                "quotes_fetched": 9,
                "dexes_active": 2,
                "no_data_reason": None,
                "opportunity_engine": {
                    "enabled": True,
                    "one_leg_profit_is_diagnostic": True,
                    "summary": {
                        "total_opportunities": 11,
                        "profitable_count": 9,
                        "gated_count": 7,
                        "rejected_count": 4,
                        "best_net_profit_usd": 4.02,
                    },
                },
            },
            "config_params": {
                "min_spread_bps": 10,
                "paper_size_usd": 250,
                "config_path": "config/test.yaml",
            },
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        # Minimal run_summary
        run_summary = {
            "status": "PASS",
            "profit_status": "PASS",
            "drift_status": "PASS",
            "quality_status": "WARN",
            "reasons": [],
            "quality_reasons": ["WARN_PROFIT_DIAGNOSTIC"],
            "run_context": {
                "run_timestamp": "2026-01-01T12:00:00Z",
                "run_dir_name": "test_run_dir",
            },
        }
        (reports_dir / "run_summary_20260101_120000.json").write_text(
            json.dumps(run_summary)
        )

        # Inspect
        result = inspect_run_dir(run_dir)

        # Assertions: opportunity_engine must reflect summary sub-object
        opp = result["opportunity_engine"]
        assert opp["total"] == 11, f"Expected total=11, got {opp['total']}"
        assert opp["profitable"] == 9, f"Expected profitable=9, got {opp['profitable']}"
        assert opp["gated"] == 7, f"Expected gated=7, got {opp['gated']}"
        assert opp["rejected"] == 4, f"Expected rejected=4, got {opp['rejected']}"
        assert opp["best_net_profit_usd"] == 4.02
        assert opp["one_leg_profit_is_diagnostic"] is True

        # Assertions: quality_reasons extracted
        assert result["quality_reasons"] == ["WARN_PROFIT_DIAGNOSTIC"]

        # Assertions: run_dir_name fallback
        assert result["run_dir_name"] == "test_run_dir"


def test_inspect_run_dir_run_dir_name_fallback():
    """
    Contract: run_dir_name falls back to run_dir.name if not in run_context.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir) / "my_custom_run_dir"
        run_dir.mkdir()
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        # Minimal truth_report
        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 1,
            "spread_signals": [],
            "stats": {"quotes_total": 1, "quotes_fetched": 1, "dexes_active": 1},
            "config_params": {},
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        # run_summary WITHOUT run_dir_name
        run_summary = {
            "status": "PASS",
            "run_context": {
                "run_timestamp": "2026-01-01T12:00:00Z",
                # run_dir_name is MISSING
            },
        }
        (reports_dir / "run_summary_20260101_120000.json").write_text(
            json.dumps(run_summary)
        )

        result = inspect_run_dir(run_dir)

        # Fallback must use run_dir.name
        assert result["run_dir_name"] == "my_custom_run_dir"


def test_inspect_run_dir_missing_artifacts():
    """
    Contract: inspect_run_dir correctly reports missing artifacts.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        # Only create truth_report (no scan, reject_histogram, run_summary)
        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 1,
            "spread_signals": [],
            "stats": {"quotes_total": 0, "quotes_fetched": 0, "dexes_active": 0},
            "config_params": {},
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        result = inspect_run_dir(run_dir)

        assert "truth_report" in result["artifacts_present"]
        assert "scan" in result["artifacts_missing"]
        assert "reject_histogram" in result["artifacts_missing"]
        assert "run_summary" in result["artifacts_missing"]


def test_inspect_run_dir_best_spread_economics():
    """
    v3.2.16: Contract: inspect_run_dir must extract best_spread_economics
    from truth_report.spread_signals (NOT top_opportunities!).
    
    This provides RCA data when passed_to_roundtrip=0 (e.g., best spread_minus_required_bps).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        # v3.2.16: spread_signals is the source (not top_opportunities)
        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 123456,
            "spread_signals": [
                {
                    "pair": "WETH/USDC",
                    "route": "uniswap_v3->sushiswap_v3",
                    "spread_bps": 15.5,
                    "min_required_spread_bps": 25.0,
                    "spread_minus_required_bps": -9.5,
                    "is_roundtrip_viable": False,
                    "lp_fee_bps_roundtrip": 10.0,
                },
                {
                    "pair": "WBTC/WETH",
                    "route": "sushiswap_v3->uniswap_v3",
                    "spread_bps": 30.0,
                    "min_required_spread_bps": 22.0,
                    "spread_minus_required_bps": 8.0,  # Best margin
                    "is_roundtrip_viable": True,
                },
                {
                    "pair": "ARB/WETH",
                    "route": "uniswap_v3->sushiswap_v3",
                    "spread_bps": 5.0,
                    "min_required_spread_bps": 25.0,
                    "spread_minus_required_bps": -20.0,
                    "is_roundtrip_viable": False,
                },
            ],
            "stats": {
                "quotes_total": 10,
                "quotes_fetched": 8,
                "dexes_active": 2,
                "opportunity_engine": {
                    "enabled": True,
                    "one_leg_profit_is_diagnostic": True,
                    "summary": {
                        "total_opportunities": 3,
                        "profitable_count": 2,
                        "gated_count": 1,
                    },
                    "top_opportunities": [],  # Empty - source is spread_signals
                },
            },
            "config_params": {},
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        result = inspect_run_dir(run_dir)

        # Best spread economics must be the one with highest spread_minus_required_bps
        best = result.get("best_spread_economics")
        assert best is not None, "best_spread_economics must be present"
        assert best["pair"] == "WBTC/WETH", f"Expected WBTC/WETH (best margin), got {best['pair']}"
        assert best["spread_minus_required_bps"] == 8.0
        assert best["spread_bps"] == 30.0
        assert best["min_required_spread_bps"] == 22.0
        assert best["is_roundtrip_viable"] is True
        assert best["source"] == "spread_signals"  # v3.2.16: source tracking


def test_inspect_run_dir_best_spread_economics_none():
    """
    v3.2.16: Contract: best_spread_economics=None when no spread_signals.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 123456,
            "spread_signals": [],  # Empty - no spread signals
            "stats": {
                "quotes_total": 5,
                "quotes_fetched": 3,
                "dexes_active": 1,
                "opportunity_engine": {
                    "enabled": True,
                    "summary": {"total_opportunities": 0},
                    "top_opportunities": [],  # Empty
                },
            },
            "config_params": {},
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        result = inspect_run_dir(run_dir)

        assert result.get("best_spread_economics") is None, \
            "best_spread_economics must be None when no spread_signals"


def test_inspect_run_dir_best_spread_economics_margin_vs_profit():
    """
    v3.2.16: Regression test: best margin != top profit.
    
    spread_signals are used for best margin (RCA), NOT top_opportunities (profit-ranked).
    This ensures wstETH/WETH with -11 bps margin is shown over WETH/USDT with -74 bps
    even when WETH/USDT has higher profit.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        # Spread signals: wstETH/WETH has BEST margin (-11), but WETH/USDT has higher profit
        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 123456,
            "spread_signals": [
                {
                    "pair": "WETH/USDT",
                    "route": "sushiswap_v3->uniswap_v3",
                    "spread_bps": 58.0,  # Higher profit potential
                    "min_required_spread_bps": 132.0,
                    "spread_minus_required_bps": -74.0,  # Worse margin
                    "is_roundtrip_viable": False,
                    "lp_fee_bps_roundtrip": 10.0,
                    "effective_slippage_bps": 116.0,
                },
                {
                    "pair": "wstETH/WETH",
                    "route": "sushiswap_v3->uniswap_v3",
                    "spread_bps": 1.0,  # Lower profit
                    "min_required_spread_bps": 13.0,
                    "spread_minus_required_bps": -11.0,  # BEST margin (closest to viability)
                    "is_roundtrip_viable": False,
                    "lp_fee_bps_roundtrip": 2.0,
                    "effective_slippage_bps": 5.0,
                },
            ],
            "stats": {
                "quotes_total": 9,
                "quotes_fetched": 9,
                "dexes_active": 2,
                "opportunity_engine": {
                    "enabled": True,
                    "summary": {"total_opportunities": 2, "profitable_count": 2},
                    # top_opportunities is profit-ranked - WETH/USDT first
                    "top_opportunities": [
                        {
                            "pair": "WETH/USDT",  # This would be selected if using top_opportunities
                            "spread_bps": 58.0,
                            "spread_minus_required_bps": -74.0,
                        },
                        {
                            "pair": "wstETH/WETH",
                            "spread_bps": 1.0,
                            "spread_minus_required_bps": -11.0,
                        },
                    ],
                },
            },
            "config_params": {},
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        result = inspect_run_dir(run_dir)

        best = result.get("best_spread_economics")
        assert best is not None
        # MUST be wstETH/WETH (best margin), NOT WETH/USDT (higher profit)
        assert best["pair"] == "wstETH/WETH", \
            f"Expected wstETH/WETH (best margin), got {best['pair']}"
        assert best["spread_minus_required_bps"] == -11.0
        assert best["min_required_spread_bps"] == 13.0
        assert best["lp_fee_bps_roundtrip"] == 2.0


def test_inspect_run_dir_roundtrip_lp_filter_extended_fields():
    """
    v3.2.15: Contract: roundtrip_lp_filter must include margin_filtered_count
    and unique_pairs_considered for reviewer RCA.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 123456,
            "spread_signals": [],
            "stats": {
                "quotes_total": 20,
                "quotes_fetched": 18,
                "dexes_active": 3,
                "roundtrip_lp_filter": {
                    "candidates_considered": 15,
                    "cross_dex_count": 10,
                    "lp_viable_count": 6,
                    "passed_to_roundtrip": 2,
                    "margin_filtered_count": 4,
                    "unique_pairs_considered": 8,
                },
                "opportunity_engine": {
                    "enabled": True,
                    "summary": {"total_opportunities": 5},
                    "top_opportunities": [],
                },
            },
            "config_params": {},
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        result = inspect_run_dir(run_dir)

        lp_filter = result.get("roundtrip_lp_filter")
        assert lp_filter is not None
        assert lp_filter["margin_filtered_count"] == 4
        assert lp_filter["unique_pairs_considered"] == 8
        assert lp_filter["passed_to_roundtrip"] == 2


def test_inspect_run_dir_best_spread_economics_cost_breakdown():
    """
    v3.2.16: Contract: best_spread_economics must include cost breakdown
    (gas_bps, lp_fee_bps_roundtrip, effective_slippage_bps, safety_bps).
    
    gas_bps should be computed from gas_usd_estimate/size_usd if not present directly.
    Source: spread_signals (NOT top_opportunities).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.inspect_run_dir import inspect_run_dir

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        reports_dir = run_dir / "reports"
        reports_dir.mkdir()

        truth_report = {
            "schema_version": "3.0.0",
            "chain_key": "arbitrum_one",
            "chain_id": 42161,
            "current_block": 123456,
            # v3.2.16: spread_signals is the source for best_spread_economics
            "spread_signals": [
                {
                    "pair": "WETH/USDC",
                    "route": "uniswap_v3->sushiswap_v3",
                    "spread_bps": 25.0,
                    "min_required_spread_bps": 70.0,
                    "spread_minus_required_bps": -45.0,
                    "is_roundtrip_viable": False,
                    # Cost breakdown fields
                    "lp_fee_bps_roundtrip": 60.0,  # 30+30 bps for 3000 tier
                    "effective_slippage_bps": 5.0,
                    "gas_usd_estimate": 0.125,  # $0.125 gas cost
                    "size_usd": 250.0,  # $250 notional
                    # gas_bps not present - should be computed: 0.125/250*10000 = 5 bps
                },
            ],
            "stats": {
                "quotes_total": 10,
                "quotes_fetched": 8,
                "dexes_active": 2,
                "opportunity_engine": {
                    "enabled": True,
                    "summary": {"total_opportunities": 2},
                    "top_opportunities": [],
                },
            },
            "config_params": {},
        }
        (reports_dir / "truth_report_20260101_120000.json").write_text(
            json.dumps(truth_report)
        )

        result = inspect_run_dir(run_dir)

        best = result.get("best_spread_economics")
        assert best is not None
        assert best["lp_fee_bps_roundtrip"] == 60.0
        assert best["effective_slippage_bps"] == 5.0
        assert best["safety_bps"] == 2.0  # Default from min_required formula
        # gas_bps computed: 0.125 / 250 * 10000 = 5.0
        assert best["gas_bps"] == 5.0, f"Expected gas_bps=5.0, got {best['gas_bps']}"
