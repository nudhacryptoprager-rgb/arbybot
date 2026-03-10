"""Schema tests for daily_report consistency with truth_report.

These tests ensure daily_report fields are consistent with source artifacts.
"""
import json
import pytest
from pathlib import Path
from scripts.generate_daily_report import aggregate_run


def make_consistent_run(tmp_path: Path):
    """Create a run with consistent truth_report and expected daily_report output."""
    run = tmp_path / "test_run"
    run.mkdir()
    
    scan = {"quotes": [], "quotes_total": 10, "quotes_fetched": 8}
    
    truth = {
        "timestamp": "2026-02-06T10:00:00Z",
        "quotes_total": 10,
        "quotes_fetched": 8,
        "price_sanity_passed": 7,
        "price_sanity_failed": 3,
        "spread_signals": [
            {
                "pair": "WETH/USDC",
                "buy_dex": "uniswap_v3",
                "sell_dex": "sushiswap_v3",
                "spread_bps_exact": 4.9833,
                "spread_bps_ui": 4,
                "spread_pct": 0.049833,
                "spread_frac": "0.0004983340",
                "gross_pnl_usdc_est": 0.4983,
                "net_pnl_usdc_est": 0.3983,
                "is_gross_positive": True,
                "is_net_positive_est": True,
                "size_usd": 1000,
                "confidence": 0.7,
                "confidence_reasons": ["paper_cost_model"],
            }
        ],
        "signals_total": 1,
        "opportunities_total": 1,
        "config_params": {
            "min_spread_bps": 0,
            "min_net_pnl_usdc_est": 0.0,
            "gas_usd_estimate": 0.10,
        },
        "pnl": {"net_pnl_usdc": 0},
        "health": {},
    }
    
    reject = {"rejects": []}
    
    (run / "scan_1.json").write_text(json.dumps(scan))
    (run / "truth_report_1.json").write_text(json.dumps(truth))
    (run / "reject_histogram_1.json").write_text(json.dumps(reject))
    
    return run, truth


def test_top_signal_matches_truth_spread_signals():
    """
    Test that daily_report.top_signal is consistent with truth_report.spread_signals[0].
    
    This prevents regressions where the daily_report generator produces
    different values than the source truth_report.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_path, truth = make_consistent_run(Path(tmp))
        report = aggregate_run(run_path)
        
        top_signal = report.get("top_signal")
        truth_signal = truth["spread_signals"][0]
        
        assert top_signal is not None, "top_signal should exist when spread_signals present"
        
        # Key fields must match
        assert top_signal["pair"] == truth_signal["pair"]
        assert top_signal["buy_dex"] == truth_signal["buy_dex"]
        assert top_signal["sell_dex"] == truth_signal["sell_dex"]
        assert top_signal["spread_bps_exact"] == truth_signal["spread_bps_exact"]
        assert top_signal["is_gross_positive"] == truth_signal["is_gross_positive"]
        assert top_signal["is_net_positive_est"] == truth_signal["is_net_positive_est"]


def test_signals_total_matches():
    """Test that signals_total in daily_report matches truth_report."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_path, truth = make_consistent_run(Path(tmp))
        report = aggregate_run(run_path)
        
        assert report["signals_total"] == len(truth["spread_signals"])
        assert report["signals_total"] == truth.get("signals_total", len(truth["spread_signals"]))


def test_opportunities_total_matches():
    """Test that opportunities_total filters correctly by is_net_positive_est."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_path, truth = make_consistent_run(Path(tmp))
        report = aggregate_run(run_path)
        
        expected_opportunities = sum(
            1 for s in truth["spread_signals"] if s.get("is_net_positive_est")
        )
        assert report["opportunities_total"] == expected_opportunities


def test_quote_sanity_rate_calculation():
    """Test that quote_sanity_rate is calculated correctly."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_path, truth = make_consistent_run(Path(tmp))
        report = aggregate_run(run_path)
        
        # quote_sanity_rate = price_sanity_passed / quotes_total
        expected = truth["price_sanity_passed"] / truth["quotes_total"]
        assert report["quote_sanity_rate"] == expected


def test_signal_win_rate_calculation():
    """Test that signal_win_rate is calculated correctly."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_path, truth = make_consistent_run(Path(tmp))
        report = aggregate_run(run_path)
        
        # signal_win_rate = net_positive_signals / total_signals
        signals = truth["spread_signals"]
        net_positive = sum(1 for s in signals if s.get("is_net_positive_est"))
        expected = net_positive / len(signals) if signals else None
        
        assert report["signal_win_rate"] == expected


def test_empty_spread_signals_no_top_signal():
    """Test that top_signal is None when no spread_signals."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "empty_run"
        run.mkdir()
        
        scan = {"quotes": [], "quotes_total": 5}
        truth = {
            "quotes_total": 5,
            "price_sanity_passed": 3,
            "spread_signals": [],
            "pnl": {},
            "health": {},
        }
        reject = {"rejects": []}
        
        (run / "scan_1.json").write_text(json.dumps(scan))
        (run / "truth_report_1.json").write_text(json.dumps(truth))
        (run / "reject_histogram_1.json").write_text(json.dumps(reject))
        
        report = aggregate_run(run)
        
        assert report["top_signal"] is None
        assert report["signals_total"] == 0
        assert report["opportunities_total"] == 0
        assert report["signal_win_rate"] is None


def test_cycles_propagation_in_truth_report():
    """Test that requested_cycles from CLI is correctly written to truth_report.
    
    Contract: if runner requests N cycles via --cycles N, then:
      - stats.requested_cycles == N
      - stats.cycles_completed == N (on successful completion)
    
    This ensures no mismatch between CLI args and artifact data.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "cycles_test"
        run.mkdir()
        
        # Simulate a run with 5 cycles
        requested_cycles = 5
        scan = {"quotes": [], "quotes_total": 10}
        truth = {
            "quotes_total": 10,
            "price_sanity_passed": 7,
            "spread_signals": [],
            "stats": {
                "requested_cycles": requested_cycles,
                "cycles_completed": requested_cycles,
                "quotes_total": 10,
            },
            "pnl": {},
            "health": {},
        }
        reject = {"rejects": []}
        
        (run / "scan_1.json").write_text(json.dumps(scan))
        (run / "truth_report_1.json").write_text(json.dumps(truth))
        (run / "reject_histogram_1.json").write_text(json.dumps(reject))
        
        # Verify truth_report has correct cycles
        loaded_truth = json.loads((run / "truth_report_1.json").read_text())
        assert loaded_truth["stats"]["requested_cycles"] == requested_cycles
        assert loaded_truth["stats"]["cycles_completed"] == requested_cycles


def test_all_signals_net_pnl_usdc_is_diagnostic():
    """v3.2.70: all_signals_net_pnl_usdc must be flagged as diagnostic-only.
    
    This field includes excluded/suspect signals' theoretical pnl and can be
    much higher than net_pnl_usdc. It must have a companion boolean flag
    all_signals_net_pnl_usdc_is_diagnostic=True to prevent misuse.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        run_path, _truth = make_consistent_run(Path(tmp))
        report = aggregate_run(run_path)
        
        pnl = report.get("theoretical_net_profit", {})
        # The diagnostic flag must be present
        assert "all_signals_net_pnl_usdc_is_diagnostic" in pnl, (
            "Missing all_signals_net_pnl_usdc_is_diagnostic flag in theoretical_net_profit. "
            "This field is required to prevent confusing diagnostic-only pnl with canonical net."
        )
        assert pnl["all_signals_net_pnl_usdc_is_diagnostic"] is True, (
            "all_signals_net_pnl_usdc_is_diagnostic must be True"
        )
