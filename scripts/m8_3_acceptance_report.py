#!/usr/bin/env python3
"""M8.3 strict acceptance report for token metadata registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_REGISTRY = REPO_ROOT / "data/runs/_rolling/m8_3_token_metadata_registry_latest.json"
_DEFAULT_OUT = REPO_ROOT / "data/tmp/m8_3_acceptance_report_latest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="M8.3 token metadata registry acceptance")
    ap.add_argument("--registry", default=str(_DEFAULT_REGISTRY))
    ap.add_argument("--output", default=str(_DEFAULT_OUT))
    ap.add_argument("--strict", action="store_true")
    ap.add_argument(
        "--cycle-participating-min",
        type=float,
        default=0.95,
        help="Minimum economics-grade decimals rate for cycle-participating routes",
    )
    args = ap.parse_args()

    from m8.metadata.acceptance import evaluate_m8_3_acceptance
    from m8.metadata.registry import load_registry

    registry = load_registry(args.registry)
    report = evaluate_m8_3_acceptance(
        registry,
        strict=args.strict,
        cycle_participating_min=args.cycle_participating_min,
    )
    report["registry_path"] = str(args.registry)
    report["registry_present"] = registry is not None
    if registry:
        report["generated_at_utc"] = registry.get("generated_at_utc")
        report["coverage"] = registry.get("coverage")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"goal_status: {report.get('goal_status')}")
    print(f"m8_3_blockers: {report.get('m8_3_blockers')}")
    diag = report.get("diagnostics") or {}
    if diag:
        print(f"top_missing_cycle_tokens: {len(diag.get('top_missing_cycle_tokens') or [])}")
        print(f"missing_by_error_code: {diag.get('missing_by_error_code')}")
        print(f"missing_by_source: {diag.get('missing_by_source')}")
    print(f"written: {out.resolve()}")

    if args.strict and report.get("goal_status") != "REACHED":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
