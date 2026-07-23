#!/usr/bin/env python3
"""Evaluate the production promotion ladder from rolling evidence.

Read-only report: loads canonical rolling artifacts, maps them to
``LadderEvidence`` and prints the ladder verdict.  Auto-execution stays
forbidden by default; ``--require-execution-unlock`` exits 1 when the
unlock conditions are not met (they currently are not).

Step 9 fix (production-readiness review issue 9):
* ``build_evidence`` reads the canonical M4 stability field ``net_usdc``
  (previously the mapper read ``total_net_usdc`` which is absent from the
  real rolling artifact, so ``simulation_positive_runs`` was always 0).
  ``total_net_usdc`` stays supported as a legacy fallback (no behavior
  regression for pre-existing fixtures).
* ``shadow_runs`` explicitly tracks *M9 shadow soak* runs (separate notion
  from M4 stability runs). When M9 shadow artifacts are supplied via
  ``--m9-shadow`` or ``m9_shadow_artifacts=...``, those are counted; the
  M4 stability run count is exposed on the verdict ``safety`` payload as
  ``m4_stability_run_count`` for diagnostic purposes but no longer conflated
  with shadow soak. When no M9 shadow input is supplied the conservative
  fallback is to use the M4 stability run count (legacy behavior).
* ``build_evidence`` returns a ``m4_stability_run_count`` diagnostic field
  callers/tests can inspect independently of the ladder's own
  ``shadow_runs`` count."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

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


def _load_many(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in paths:
        d = _load(Path(p))
        if d is not None:
            out.append(d)
    return out


def _run_net_usdc(run: Dict[str, Any]) -> float:
    """Return the canonical M4 stability ``net_usdc`` field, falling back
    to the legacy ``total_net_usdc`` shape used by older fixtures/tests."""
    val = run.get("net_usdc")
    if val is None:
        val = run.get("total_net_usdc")
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _m9_shadow_run_count(m9_shadow_artifacts: Iterable[Dict[str, Any]]) -> int:
    """Count M9 shadow soak artifacts that actually completed a full
    duration-fufilled scan. The shadow scanner writes ``runner_outcome`` /
    ``duration_fulfilled`` on its run record; a STARTING/PENDING artifact
    must not count toward shadow soak promotion evidence."""
    n = 0
    for art in m9_shadow_artifacts or []:
        if not isinstance(art, dict):
            continue
        outcome = str(art.get("runner_outcome") or "").upper()
        duration_ok = bool(art.get("duration_fulfilled") or False)
        # Accept any explicitly COMPLETED duration-fulfilled artifact — the
        # canonical M9 shadow artifact records both fields.
        if duration_ok and outcome in ("COMPLETED", "DONE", "OK"):
            n += 1
        elif outcome == "COMPLETED" and duration_ok:
            n += 1
    return n


def build_evidence(
    *,
    stability: Optional[Dict[str, Any]],
    run_summary: Optional[Dict[str, Any]],
    m9_acceptance: Optional[Dict[str, Any]],
    resilience_doc: Optional[Dict[str, Any]],
    m9_shadow_artifacts: Optional[Iterable[Dict[str, Any]]] = None,
) -> LadderEvidence:
    """Map canonical rolling artifacts to LadderEvidence (conservative).

    Schema contract used here (canonically checked against the real
    ``data/runs/_rolling/m4_stability_agg.json`` artifact):

    * ``m4_stability.runs[*].net_usdc`` (canonical; the field the previous
      mapper queried as ``total_net_usdc`` is absent from the real artifact) —
      used for ``simulation_positive_runs``.
    * ``m4_stability.runs[*].run_mode == "REGISTRY_REAL"`` and
      ``block_is_synthetic == False`` required to count as a positive sim run.
    * M9 shadow artifacts (when supplied via ``m9_shadow_artifacts``)
      drive ``shadow_runs`` — each COMPLETED + ``duration_fulfilled=True``
      artifact counts as one shadow-soak run. Otherwise we fall back to
      ``len(m4_stability.runs)`` (the conservative legacy behavior).
    * ``m9_acceptance.quote_liveness_metrics.cycles_quoteable`` feeds
      ``cycles_quoteable``.
    * ``run_summary.metrics.kill_switch_active`` /
      ``execution_enabled`` map directly to the safety fields.
    """
    runs = (stability or {}).get("runs") or []
    agg_pass = str((stability or {}).get("agg_status") or "") == "PASS"
    positive_runs = sum(
        1
        for r in runs
        if isinstance(r, dict)
        and _run_net_usdc(r) > 0
        and r.get("run_mode") == "REGISTRY_REAL"
        and not r.get("block_is_synthetic", True)
    )
    cycles_quoteable = int(
        ((m9_acceptance or {}).get("quote_liveness_metrics") or {}).get("cycles_quoteable") or 0
    )
    resilience = dict((resilience_doc or {}).get("checks") or {})
    metrics = (run_summary or {}).get("metrics") or {}

    # Step 9: M9 shadow soak vs M4 stability run count. Prefer M9 shadow
    # when provided; else fall back to M4 stability run count (legacy).
    m9_shadow_n = _m9_shadow_run_count(m9_shadow_artifacts or [])
    shadow_runs_source = "m9_shadow" if m9_shadow_n > 0 else "m4_stability_legacy_fallback"
    shadow_runs = m9_shadow_n if m9_shadow_n > 0 else len(runs)

    return LadderEvidence(
        code_gates_pass=agg_pass,
        shadow_runs=shadow_runs,
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
        extra={
            "m4_stability_run_count": len(runs),
            "m4_simulation_positive_runs": positive_runs,
            "m9_shadow_run_count": m9_shadow_n,
            "shadow_runs_source": shadow_runs_source,
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Promotion ladder evaluation")
    ap.add_argument("--stability", default=str(_DEFAULT["stability"]))
    ap.add_argument("--run-summary", default=str(_DEFAULT["run_summary"]))
    ap.add_argument("--m9-acceptance", default=str(_DEFAULT["m9_acceptance"]))
    ap.add_argument("--resilience", default=str(_DEFAULT["resilience"]))
    ap.add_argument(
        "--m9-shadow",
        nargs="*",
        default=None,
        help="Zero or more M9 shadow-soak artifacts (e.g. "
             "data/tmp/m9_graph_handoff_quote_validation_10m.json).",
    )
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
        m9_shadow_artifacts=_load_many(args.m9_shadow or []),
    )
    verdict = evaluate_ladder(evidence)
    payload = verdict.to_dict()
    # Surface M9-vs-M4 split audited by the mapper (Step 9 fix).
    if getattr(evidence, "extra", None):
        payload["mapper_audit"] = dict(evidence.extra)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("current_stage:", payload["current_stage"])
    print("next_stage:", payload["next_stage"])
    print("promotion_allowed:", payload["promotion_allowed"])
    print("blockers:", payload["blockers"])
    print("execution_unlock_allowed:", payload["execution_unlock_allowed"])
    if payload.get("mapper_audit"):
        print("mapper_audit:", json.dumps(payload["mapper_audit"]))
    if payload["safety"].get("contract_violation"):
        print("CONTRACT_VIOLATION:", payload["safety"]["contract_violation"])
    print("written:", out)

    if args.require_execution_unlock and not payload["execution_unlock_allowed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
