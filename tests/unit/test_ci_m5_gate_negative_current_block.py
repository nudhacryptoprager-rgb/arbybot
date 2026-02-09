import json
import tempfile
from pathlib import Path

import pytest

from scripts.generate_daily_report import aggregate_run
from scripts.ci_m5_gate import validate_report


@pytest.mark.skip(reason="current_block mismatch validation not yet implemented in M5 gate")
def test_gate_fails_on_current_block_mismatch(tmp_path: Path):
    # pick a real run
    runs = Path('data/runs')
    latest = max([d for d in runs.iterdir() if d.is_dir()], key=lambda p: p.stat().st_mtime)
    report = aggregate_run(latest)

    # write a copy with modified current_block to force mismatch
    rp_copy = tmp_path / 'bad_report.json'
    report_bad = dict(report)
    # inject fake current_block if absent
    report_bad['current_block'] = 42_000_000
    rp_copy.write_text(json.dumps(report_bad), encoding='utf8')

    errs = validate_report(rp_copy)
    assert any('current_block_mismatch' in e or 'artifact_consistency_error' in e for e in errs)
