from pathlib import Path
import json

from scripts.ci_m5_gate import validate_report


def make_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2), encoding="utf8")


def test_quotes_total_mismatch(tmp_path: Path):
    # create scan and truth artifacts with differing quotes_total
    scan = tmp_path / "scan.json"
    truth = tmp_path / "truth.json"
    rejects = tmp_path / "rejects.json"

    make_json(scan, {"quotes_total": 10, "current_block": 100})
    make_json(truth, {"quotes_total": 9, "current_block": 100})
    make_json(rejects, {"total_rejects": 0, "rejects": []})

    daily = tmp_path / "daily.json"
    daily_obj = {
        "schema_version": "m5:daily:v1",
        "generated_at": "2026-02-05T00:00:00+00:00",
        "trades_count": 10,
        "paper_net_pnl_usdc": 0.0,
        "paper_win_rate": 0.5,
        "health": {"rpc": {}, "dex": {}, "system": {}},
        "artifacts": {
            "scan_path": str(scan),
            "truth_report_path": str(truth),
            "reject_histogram_path": str(rejects),
        },
    }
    make_json(daily, daily_obj)

    errs = validate_report(daily)
    assert any("quotes_total_mismatch" in e for e in errs), f"expected quotes_total_mismatch, got {errs}"
