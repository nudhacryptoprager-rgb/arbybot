import json
import tempfile
from pathlib import Path

from scripts.generate_daily_report import aggregate_run


def make_minimal_run(tmp_path: Path) -> Path:
    run = tmp_path / "run1"
    run.mkdir()
    # minimal scan
    scan = {"quotes_total": 2, "quotes_fetched": 2}
    # Add spread_signals for paper PnL calculation (new schema with paper estimates)
    truth = {
        "quotes_total": 2,
        "price_sanity_passed": 1,
        "pnl": {"net_pnl_usdc": 12.5},
        "health": {"rpc": {"success_rate": 1.0}},
        "spread_signals": [
            {
                "pair": "WETH/USDC",
                "spread_pct": 0.5,  # 0.5% 
                "spread_bps_exact": 50.0,
                "spread_bps_int": 50,
                "size_usd": 1000,
                "gross_pnl_usdc_est": 5.0,
                "net_pnl_usdc_est": 3.9,  # gross - gas - slippage
                "is_gross_positive": True,
                "is_net_positive_est": True,
            },
            {
                "pair": "WETH/USDC",
                "spread_pct": 0.75,  # 0.75%
                "spread_bps_exact": 75.0,
                "spread_bps_int": 75,
                "size_usd": 1000,
                "gross_pnl_usdc_est": 7.5,
                "net_pnl_usdc_est": 6.4,  # gross - gas - slippage
                "is_gross_positive": True,
                "is_net_positive_est": True,
            },
        ],  # Total gross = 12.5 USD
    }
    reject = {"rejects": [{"error": "deviation_exceeded"}, {"suspect_reason": "way_below_expected"}]}
    (run / "scan_1.json").write_text(json.dumps(scan))
    (run / "truth_report_1.json").write_text(json.dumps(truth))
    (run / "reject_histogram_1.json").write_text(json.dumps(reject))
    return run


def test_aggregate_minimal(tmp_path):
    run = make_minimal_run(tmp_path)
    rpt = aggregate_run(run)
    assert rpt["schema_version"] == "m5:daily:v1"
    assert rpt["runs_included"] == 1
    # M5 reports use paper_net_pnl_usdc calculated from spread_signals
    # gross = 5 + 7.5 = 12.5, no gas/slippage → net = 12.5
    assert rpt.get("paper_net_pnl_usdc") == 12.5
    assert rpt.get("gross_spread_usdc") == 12.5
    assert rpt.get("spread_signals_count") == 2
    # top_signal should have the best spread
    top_signal = rpt.get("top_signal")
    assert top_signal is not None
    # Now uses spread_bps_exact and spread_bps_int
    assert top_signal.get("spread_bps_exact") == 75.0  # best one
    assert top_signal.get("spread_bps_int") == 75
    assert isinstance(rpt["top_reject_reasons"], list)
