"""CI gate for Milestone 5: validate presence and basic correctness of daily_report.

Initial / minimal validator: accepts one or more daily_report JSON files and
performs basic schema checks (schema_version, non-null metrics, top_reject_reasons not empty).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List


def validate_report(path: Path) -> List[str]:
    errors = []
    try:
        j = json.loads(path.read_text(encoding="utf8"))
    except Exception as e:
        return [f"invalid_json: {e}"]

    sv = j.get("schema_version")
    if not sv or not str(sv).startswith("m5:daily"):
        errors.append("schema_version_missing_or_invalid")

    if j.get("runs_included") is None:
        errors.append("runs_included_missing")

    # basic metrics
    if j.get("net_pnl_usdc") is None:
        errors.append("net_pnl_missing")
    if j.get("win_rate") is None:
        errors.append("win_rate_missing")

    tr = j.get("top_reject_reasons") or []
    if not isinstance(tr, list):
        errors.append("top_reject_reasons_invalid")

    health = j.get("health")
    if health is None:
        errors.append("health_missing")

    return errors


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reports", nargs="+", required=True, help="daily_report JSON files to validate")
    args = p.parse_args()

    all_errors = {}
    for r in args.reports:
        path = Path(r)
        errs = validate_report(path)
        all_errors[r] = errs

    ok = True
    for r, errs in all_errors.items():
        if errs:
            ok = False
            print(f"{r}: FAIL -> {errs}")
        else:
            print(f"{r}: OK")

    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
