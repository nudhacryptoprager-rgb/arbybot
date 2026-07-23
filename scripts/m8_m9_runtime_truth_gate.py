#!/usr/bin/env python3
"""M8 -> M9 runtime truth admission gate (hard).

Refuses a cross-artifact runtime bundle when the M8 sniper artifact is a
stub/partial document (e.g. ``0xabc`` placeholder pool), when any M8 -> M9
input artifact is missing/stale, or when artifacts come from mixed runtime
windows.  All blockers are classified ``CODE_ARTIFACT_CONTRACT`` — never a
market blocker.

Exit codes:
  0 - PASS (coherent evidence bundle)
  1 - BLOCKED (stub/schema/freshness/window integrity failure)
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

from monitoring.runtime_truth_gate import (  # noqa: E402
    SESSION_WINDOW_SECONDS,
    WINDOW_MISMATCH_SECONDS,
    evaluate_runtime_truth_gate,
)

_DEFAULT_PATHS = {
    "sniper": REPO_ROOT / "data/runs/_rolling/new_pool_sniper_latest.json",
    "anchor": REPO_ROOT / "data/runs/_rolling/m8_1_stable_anchor_latest.json",
    "hints": REPO_ROOT / "data/runs/_rolling/m8_external_pool_hints_latest.json",
    "expansion": REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    "m8_3": REPO_ROOT / "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
    "bridge": REPO_ROOT / "data/tmp/m9_bridge_inventory_production_latest.json",
}


def _load(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="M8->M9 runtime truth admission gate")
    ap.add_argument("--sniper", default=str(_DEFAULT_PATHS["sniper"]))
    ap.add_argument("--anchor", default=str(_DEFAULT_PATHS["anchor"]))
    ap.add_argument("--hints", default=str(_DEFAULT_PATHS["hints"]))
    ap.add_argument("--expansion", default=str(_DEFAULT_PATHS["expansion"]))
    ap.add_argument("--m8-3-registry", default=str(_DEFAULT_PATHS["m8_3"]))
    ap.add_argument("--bridge", default=str(_DEFAULT_PATHS["bridge"]))
    ap.add_argument(
        "--window-seconds",
        type=int,
        default=WINDOW_MISMATCH_SECONDS,
        help="Max pairwise run_timestamp delta for one runtime window when no "
             "shared session_id binds the artifacts (default 48 min).",
    )
    ap.add_argument(
        "--session-window-seconds",
        type=int,
        default=SESSION_WINDOW_SECONDS,
        help="Max pairwise run_timestamp delta when a shared session_id binds "
             "the artifacts (default 90 min, allows serial M8->M8.1->M8.2->"
             "M8.3->bridge pipelines).",
    )
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/m8_m9_runtime_truth_gate_latest.json"),
    )
    args = ap.parse_args()

    verdict = evaluate_runtime_truth_gate(
        sniper=_load(Path(args.sniper)),
        anchor=_load(Path(args.anchor)),
        hints=_load(Path(args.hints)),
        expansion=_load(Path(args.expansion)),
        m8_3_registry=_load(Path(args.m8_3_registry)),
        bridge=_load(Path(args.bridge)),
        window_seconds=int(args.window_seconds),
        session_window_seconds=int(args.session_window_seconds),
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdict, indent=2), encoding="utf-8")

    print("truth_status:", verdict["truth_status"])
    print("blocker_class:", verdict["blocker_class"])
    print("blockers:", verdict["blockers"])
    print("session_id:", verdict.get("session_id"))
    print("window_seconds:", verdict.get("window_seconds"))
    print("written:", out)
    return 0 if verdict["truth_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
