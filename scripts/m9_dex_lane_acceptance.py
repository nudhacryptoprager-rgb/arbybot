#!/usr/bin/env python3
"""Per-DEX lane acceptance gate — fail before long M9 economics soak."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_MATRIX = REPO_ROOT / "data/tmp/m9_dex_quality_matrix_latest.json"
_DEFAULT_ACCEPTANCE = REPO_ROOT / "data/tmp/m9_lane_acceptance_report_latest.json"


def evaluate_lane_acceptance(
    matrix_doc: Dict[str, Any],
    acceptance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return pass/fail and per-rule violations."""
    violations: List[str] = []
    matrix = matrix_doc.get("matrix") or {}

    for dex_id, row in matrix.items():
        if int(row.get("verified") or 0) > 0 and int(row.get("productive_quote_ok") or 0) == 0:
            violations.append(f"{dex_id}:verified>0_productive_quote_ok=0")
        if int(row.get("route_quote_ok") or 0) > 0 and int(row.get("productive_quote_ok") or 0) == 0:
            if dex_id in ("balancer_vault", "maverick_v2", "curve_stable"):
                violations.append(f"{dex_id}:discovery_quote_ok_but_not_productive")

    for dex_id, row in matrix.items():
        if (
            int(row.get("discovered") or 0) == 0
            and int(row.get("bridge_active_routes") or 0) == 0
            and dex_id in matrix_doc.get("expansion_dex_ids_checked", [])
        ):
            violations.append(f"{dex_id}:no_discovery_after_full_refresh")

    for dex_id, row in matrix.items():
        if row.get("adapter_family") == "balancer_vault" and not row.get(
            "metadata_complete", True
        ):
            violations.append(f"{dex_id}:balancer_metadata_incomplete")

    global_shadow = matrix_doc.get("global_shadow") or {}
    if int(global_shadow.get("cycles_quoteable") or 0) == 0:
        violations.append("global:cycles_quoteable=0")

    phantom = 0
    if acceptance:
        blockers = acceptance.get("blockers") or []
        if "PHANTOM_QUOTE_PRESENT" in blockers:
            violations.append("global:phantom_quote_present")

    exp_lane = matrix_doc.get("expansion_distinct_lane") or {}
    if exp_lane.get("curve_lane_ready") is False:
        violations.append("expansion:curve_lane_not_ready")

    bsm = {}
    if acceptance:
        for layer in acceptance.get("funnel_layers") or []:
            if layer.get("layer") == "M9_bridge":
                pass
    bridge_metrics = matrix_doc.get("bridge_provenance") or {}
    if not bridge_metrics.get("m8_provenance_enforced"):
        violations.append("provenance:m8_gate_not_enforced")
    if int(bridge_metrics.get("canonical_routes_count") or 0) == 0:
        violations.append("provenance:no_canonical_routes")

    shadow_cycles_with_m8 = 0
    if acceptance:
        for layer in acceptance.get("funnel_layers") or []:
            if layer.get("layer") == "M9_shadow":
                shadow_cycles_with_m8 = int(layer.get("cycles_with_m8_pool") or 0)
    if shadow_cycles_with_m8 == 0:
        violations.append("m8:cycles_with_m8_pool_zero")
    cm_quoteable = int(
        (matrix_doc.get("global_shadow") or {}).get("cross_mechanic_cycles_quoteable")
        or 0
    )
    if cm_quoteable == 0:
        violations.append("m8:cross_mechanic_cycles_quoteable_zero")

    passed = len(violations) == 0
    return {
        "schema_version": "m9_dex_lane_acceptance.1",
        "passed": passed,
        "violations": violations,
        "matrix_blockers": matrix_doc.get("blockers") or [],
        "recommendation": (
            "OK for 10m shadow probe"
            if passed
            else "BLOCKED: fix per-DEX lane violations before shadow soak"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 per-DEX lane acceptance gate")
    ap.add_argument("--matrix", default=str(_DEFAULT_MATRIX))
    ap.add_argument("--acceptance", default=str(_DEFAULT_ACCEPTANCE))
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/m9_dex_lane_acceptance_latest.json"),
    )
    ap.add_argument("--strict", action="store_true", help="Exit 1 on failure")
    args = ap.parse_args()

    matrix_path = Path(args.matrix)
    if not matrix_path.exists():
        from scripts.m9_dex_quality_matrix import main as build_matrix

        build_matrix()
    matrix_doc = json.loads(matrix_path.read_text(encoding="utf-8"))

    acceptance = None
    acc_path = Path(args.acceptance)
    if acc_path.exists():
        acceptance = json.loads(acc_path.read_text(encoding="utf-8"))

    result = evaluate_lane_acceptance(matrix_doc, acceptance)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if args.strict and not result["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
