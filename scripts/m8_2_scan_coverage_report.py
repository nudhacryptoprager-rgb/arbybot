#!/usr/bin/env python3
"""Audit M8.2 token × dex × anchor active-scan coverage from expansion artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from m8.discovery.scan_telemetry import build_coverage_audit  # noqa: E402

_DEFAULT_EXPANSION = REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="M8.2 active-scan coverage audit")
    ap.add_argument("--expansion", default=str(_DEFAULT_EXPANSION))
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/m8_2_scan_coverage_latest.json"),
    )
    ap.add_argument(
        "--min-coverage-rate",
        type=float,
        default=0.98,
        help="Minimum scan_actual/scan_expected ratio",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 when coverage audit blockers present",
    )
    args = ap.parse_args()

    path = Path(args.expansion)
    if not path.exists():
        print("expansion artifact missing:", path)
        return 2

    expansion = json.loads(path.read_text(encoding="utf-8"))
    report = build_coverage_audit(expansion, min_coverage_rate=float(args.min_coverage_rate))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("coverage_rate:", report.get("active_scan_coverage_rate"))
    print("missing_dexes:", report.get("missing_dexes"))
    print("attempted_by_dex:", report.get("active_scan_attempted_by_dex"))
    print("no_pool_by_dex:", report.get("active_scan_no_pool_by_dex"))
    print("blockers:", report.get("blockers"))
    print("written:", out)
    if args.strict and report.get("blockers"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
