from pathlib import Path
import json

from scripts.ci_m5_gate import validate_report


def make_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2), encoding="utf8")


def test_schema_version_mismatch(tmp_path: Path):
    daily = tmp_path / "daily.json"
    obj = {"schema_version": "m4:daily:v1", "runs_included": 1, "paper_net_pnl_usdc": 0.0, "paper_win_rate": 0.5, "health": {"rpc": {}, "dex": {}, "system": {}}, "checks_count": 0}
    make_json(daily, obj)
    errs = validate_report(daily)
    assert any("schema_version_missing_or_invalid" in e for e in errs), f"expected schema_version_missing_or_invalid, got {errs}"
