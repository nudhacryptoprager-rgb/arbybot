#!/usr/bin/env python3
"""Evaluate the production promotion ladder from rolling evidence.

Read-only report: loads canonical rolling artifacts, maps them to
``LadderEvidence`` and prints the ladder verdict.  Auto-execution stays
forbidden by default; ``--require-execution-unlock`` exits 1 when the
unlock conditions are not met (they currently are not).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from execution.promotion_ladder import (  # noqa: E402
    LadderEvidence,
    evaluate_ladder,
)

_DEFAULT = {
    "stability": REPO_ROOT / "data/runs/_rolling/m4_stability_agg.json",
    "run_summary": REPO_ROOT / "data/runs/_rolling/run_summary_latest.json",
    "m9_acceptance": REPO_ROOT / "data/tmp/m9_lane_acceptance_report_latest.json",
    "resilience": REPO_ROOT / "data/tmp/resilience_checks_latest.json",
}


def _load(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_evidence(
    *,
    stability: Optional[Dict[str, Any]],
    run_summary: Optional[Dict[str, Any]],
    m9_acceptance: Optional[Dict[str, Any]],
    resilience_doc: Optional[Dict[str, Any]],
) -> LadderEvidence:
    """Map canonical rolling artifacts to LadderEvidence (conservative)."""
    runs = (stability or {}).get("runs") or []
    agg_pass = str((stability or {}).get("agg_status") or "") == "PASS"
    positive_runs = sum(
        1
        for r in runs
        if isinstance(r, dict)
        and (r.get("total_net_usdc") or 0) > 0
        and r.get("run_mode") == "REGISTRY_REAL"
        and not r.get("block_is_synthetic", True)
    )
    cycles_quoteable = int(
        ((m9_acceptance or {}).get("quote_liveness_metrics") or {}).get("cycles_quoteable") or 0
    )
    resilience = dict((resilience_doc or {}).get("checks") or {})
    metrics = (run_summary or {}).get("metrics") or {}
    return LadderEvidence(
        code_gates_pass=agg_pass,
        shadow_runs=len(runs),
        shadow_agg_status_pass=agg_pass,
        cycles_quoteable=cycles_quoteable,
        simulation_positive_runs=positive_runs,
        simulation_repeatable=bool(
            positive_runs >= 5 and (m9_acceptance or {}).get("quote_liveness_metrics")
        ),
        resilience=resilience,
        kill_switch_active=bool(metrics.get("kill_switch_active", True)),
        execution_enabled=bool(metrics.get("execution_enabled", False)),
        human_unlock=bool((resilience_doc or {}).get("human_unlock", False)),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Promotion ladder evaluation")
    ap.add_argument("--stability", default=str(_DEFAULT["stability"]))
    ap.add_argument("--run-summary", default=str(_DEFAULT["run_summary"]))
    ap.add_argument("--m9-acceptance", default=str(_DEFAULT["m9_acceptance"]))
    ap.add_argument("--resilience", default=str(_DEFAULT["resilience"]))
    ap.add_argument(
        "--require-execution-unlock",
        action="store_true",
        help="exit 1 when execution unlock conditions are not met",
    )
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/promotion_ladder_latest.json"),
    )
    args = ap.parse_args()

    evidence = build_evidence(
        stability=_load(Path(args.stability)),
        run_summary=_load(Path(args.run_summary)),
        m9_acceptance=_load(Path(args.m9_acceptance)),
        resilience_doc=_load(Path(args.resilience)),
    )
    verdict = evaluate_ladder(evidence)
    payload = verdict.to_dict()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("current_stage:", payload["current_stage"])
    print("next_stage:", payload["next_stage"])
    print("promotion_allowed:", payload["promotion_allowed"])
    print("blockers:", payload["blockers"])
    print("execution_unlock_allowed:", payload["execution_unlock_allowed"])
    if payload["safety"].get("contract_violation"):
        print("CONTRACT_VIOLATION:", payload["safety"]["contract_violation"])
    print("written:", out)

    if args.require_execution_unlock and not payload["execution_unlock_allowed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
