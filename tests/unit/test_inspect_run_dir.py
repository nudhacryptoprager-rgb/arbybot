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
