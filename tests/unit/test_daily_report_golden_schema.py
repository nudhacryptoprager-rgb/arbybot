import json
from pathlib import Path

from scripts.generate_daily_report import aggregate_run


def test_golden_schema_matches_generated():
    golden_path = Path("docs/artifacts/daily_report_golden.json")
    assert golden_path.exists(), "golden daily report missing"
    golden = json.loads(golden_path.read_text(encoding="utf8"))
    src = Path(golden.get("source_run_dir"))
    assert src.exists(), "golden source_run_dir missing"
    generated = aggregate_run(src)

    # ensure same top-level keys and compatible types (None in golden acts as wildcard)
    for k, v in golden.items():
        assert k in generated, f"key {k} missing in generated report"
        if v is None:
            # golden leaves type unspecified -> accept any generated type (presence is sufficient)
            continue
        assert type(generated[k]) == type(v) or (generated[k] is None), f"type mismatch for {k}"
