import json
import tempfile
from pathlib import Path

from scripts.generate_daily_report import aggregate_run


def make_minimal_run(tmp_path: Path) -> Path:
    run = tmp_path / "run1"
    run.mkdir()
    # minimal scan
    scan = {"quotes_total": 2, "quotes_fetched": 2}
    truth = {
        "quotes_total": 2,
        "price_sanity_passed": 1,
        "pnl": {"net_pnl_usdc": 12.5},
        "health": {"rpc": {"success_rate": 1.0}},
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
    # M5 reports use paper_net_pnl_usdc
    assert rpt.get("paper_net_pnl_usdc") == 12.5
    assert isinstance(rpt["top_reject_reasons"], list)
