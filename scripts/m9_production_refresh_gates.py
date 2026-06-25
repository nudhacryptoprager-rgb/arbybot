#!/usr/bin/env python3
"""Runtime gates for M8→M9 production refresh pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_FRESH_SUBSET = REPO_ROOT / "data/tmp/m8_fresh_delta_token_subset.json"
_DEFAULT_REGISTRY = REPO_ROOT / "data/runs/_rolling/m8_3_token_metadata_registry_latest.json"
_DEFAULT_CAPACITY = REPO_ROOT / "data/tmp/m9_capacity_cycle_diagnostic_latest.json"
_DEFAULT_M83_ACCEPT = REPO_ROOT / "data/tmp/m8_3_acceptance_report_latest.json"


def _load(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def gate_fresh_delta_subset(
    path: Path,
    *,
    min_fresh_delta: int = 1,
    require_audit_excluded: bool = True,
) -> int:
    doc = _load(path)
    if not doc:
        print(f"FAIL fresh_delta_gate: missing {path}", file=sys.stderr)
        return 1
    meta = doc.get("lane_meta") or {}
    fresh = int(meta.get("fresh_delta_count") or 0)
    wide = int(meta.get("wide_recall_count") or 0)
    selected = len(doc.get("tokens") or [])
    if selected <= 0:
        selected = fresh + wide
    print(
        json.dumps(
            {
                "gate": "fresh_delta_subset",
                "path": str(path),
                "fresh_delta_count": fresh,
                "wide_recall_count": wide,
                "selected_tokens": selected,
                "audit_excluded": meta.get("audit_excluded"),
            },
            indent=2,
        )
    )
    if selected <= 0:
        print("FAIL fresh_delta_gate: no tokens selected for radar", file=sys.stderr)
        return 1
    if fresh < min_fresh_delta:
        print(
            f"WARN fresh_delta_gate: fresh_delta_count={fresh} < {min_fresh_delta} "
            "(wide_recall may dominate)",
            file=sys.stderr,
        )
    if require_audit_excluded and meta.get("audit_excluded") is not True:
        print("WARN fresh_delta_gate: audit_excluded not true", file=sys.stderr)
    return 0


def gate_negative_cache_stats(path: Path) -> int:
    doc = _load(path)
    if not doc:
        print(f"FAIL negative_cache_gate: missing registry {path}", file=sys.stderr)
        return 1
    block = doc.get("negative_cache") or {}
    stats = block.get("stats") or {}
    row = {
        "gate": "negative_cache_stats",
        "path": str(path),
        "entry_count": stats.get("entry_count", len(block.get("entries") or {})),
        "hits": stats.get("hits"),
        "misses": stats.get("misses"),
        "bypass_count": stats.get("bypass_count"),
        "ttl_s": block.get("ttl_s"),
    }
    print(json.dumps(row, indent=2))
    return 0


def gate_m83_acceptance(path: Path, *, require_reached: bool = True) -> int:
    doc = _load(path)
    goal = str(doc.get("goal_status") or "")
    print(
        json.dumps(
            {
                "gate": "m8_3_acceptance",
                "path": str(path),
                "goal_status": goal,
                "blockers": doc.get("blockers") or [],
            },
            indent=2,
        )
    )
    if require_reached and goal != "REACHED":
        print(f"FAIL m8_3_acceptance_gate: goal_status={goal!r}", file=sys.stderr)
        return 1
    return 0


def gate_capacity_shadow(
    path: Path,
    *,
    profile_names: Optional[tuple[str, ...]] = None,
) -> int:
    from m9.graph_arb.cycle_capacity import shadow_gate_blocked

    doc = _load(path)
    if not doc:
        print(f"FAIL capacity_gate: missing {path}", file=sys.stderr)
        return 1
    blocked, reason = shadow_gate_blocked(doc, profile_names=profile_names or ())
    top = (doc.get("top_bottleneck_legs") or [])[:5]
    hist = (doc.get("enrichment_targets") or {}).get("route_ids_count")
    print(
        json.dumps(
            {
                "gate": "capacity_shadow",
                "path": str(path),
                "shadow_gate": doc.get("shadow_gate")
                or {"blocked": blocked, "reason": reason},
                "cycles_at_production_floor": doc.get("cycles_at_production_floor"),
                "cycles_by_profile": doc.get("cycles_by_profile"),
                "top_bottleneck_legs_sample": top,
                "enrichment_route_ids_count": hist,
                "shadow_allowed": not blocked,
            },
            indent=2,
        )
    )
    if blocked:
        print(f"INFO capacity_gate: shadow blocked ({reason})", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="M8→M9 production refresh runtime gates")
    ap.add_argument(
        "gate",
        choices=(
            "fresh_delta_subset",
            "negative_cache_stats",
            "m8_3_acceptance",
            "capacity_shadow",
        ),
    )
    ap.add_argument("--fresh-subset", default=str(_DEFAULT_FRESH_SUBSET))
    ap.add_argument("--registry", default=str(_DEFAULT_REGISTRY))
    ap.add_argument("--m8-3-acceptance", default=str(_DEFAULT_M83_ACCEPT))
    ap.add_argument("--capacity", default=str(_DEFAULT_CAPACITY))
    args = ap.parse_args()

    if args.gate == "fresh_delta_subset":
        return gate_fresh_delta_subset(Path(args.fresh_subset))
    if args.gate == "negative_cache_stats":
        return gate_negative_cache_stats(Path(args.registry))
    if args.gate == "m8_3_acceptance":
        return gate_m83_acceptance(Path(args.m8_3_acceptance))
    if args.gate == "capacity_shadow":
        return gate_capacity_shadow(Path(args.capacity))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
