import json
import tempfile
from pathlib import Path

from scripts.generate_daily_report import aggregate_run


def make_minimal_run(tmp_path: Path) -> Path:
    run = tmp_path / "run1"
    run.mkdir()
    # minimal scan
    scan = {"quotes_total": 2, "quotes_fetched": 2}
    # Add spread_signals for paper PnL calculation
    truth = {
        "quotes_total": 2,
        "price_sanity_passed": 1,
        "pnl": {"net_pnl_usdc": 12.5},
        "health": {"rpc": {"success_rate": 1.0}},
        "spread_signals": [
            {"spread_pct": 0.5, "size_usd": 1000},  # 0.5% of 1000 = 5 USD
            {"spread_pct": 0.75, "size_usd": 1000},  # 0.75% of 1000 = 7.5 USD
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
    assert isinstance(rpt["top_reject_reasons"], list)
