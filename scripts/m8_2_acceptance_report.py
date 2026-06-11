#!/usr/bin/env python3
"""M8.2 mirror/subgraph/handoff quality acceptance (no M9 shadow/economics)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from m8.discovery.origin_source import (  # noqa: E402
    ORIGIN_EXPLORATION,
    collect_m8_token_addrs,
    partition_canonical_routes,
)

_DEFAULT_PATHS = {
    "sniper": REPO_ROOT / "data/runs/_rolling/new_pool_sniper_latest.json",
    "hints": REPO_ROOT / "data/runs/_rolling/m8_external_pool_hints_latest.json",
    "expansion": REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json",
}

_QUALITY_GATES = {
    "subgraph_ready_tokens_min": 3,
    "verified_second_pool_count_min": 10,
    "multi_venue_tokens_min": 14,
    "connector_routes_count_min": 1,
}

_M8_2_BLOCKERS = frozenset(
    {
        "SUBGRAPH_READY_LOW",
        "VERIFIED_SECOND_POOL_LOW",
        "HINTS_STALE",
        "EXTERNAL_HINTS_STALE",
        "CONNECTOR_SYNTHESIS_WEAK",
        "MULTI_VENUE_TOKENS_LOW",
        "EXPANSION_FRESHNESS_ORDER_VIOLATION",
        "M8_2_EXPANSION_ARTIFACT_MISSING",
        "M8_2_HINTS_ARTIFACT_MISSING",
    }
)


def _load(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_utc(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    normalized = str(ts).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expansion_metrics(
    expansion: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = (expansion or {}).get("summary") or {}
    metrics = (expansion or {}).get("metrics") or {}
    return {
        "m8_tokens_in": summary.get("m8_tokens_in") or summary.get("tokens_in"),
        "routes_admitted_count": summary.get("routes_admitted_count")
        or metrics.get("routes_admitted"),
        "multi_venue_tokens": summary.get("multi_venue_tokens")
        or metrics.get("multi_venue_tokens"),
        "verified_second_pool_count": summary.get("verified_second_pool_count"),
        "connector_routes_count": summary.get("connector_routes_count"),
        "subgraph_ready_tokens": summary.get("subgraph_ready_tokens"),
        "hint_tokens_matched": summary.get("hint_tokens_matched"),
        "external_hints_enabled": summary.get("external_hints_enabled"),
        "second_pool_hints_found": summary.get("second_pool_hints_found"),
        "hint_to_verified_pool_rate": summary.get("hint_to_verified_pool_rate"),
    }


def _freshness_block(
    *,
    sniper: Optional[Dict[str, Any]],
    hints: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    sniper_ts = _parse_utc((sniper or {}).get("generated_at_utc"))
    hints_ts = _parse_utc((hints or {}).get("generated_at_utc"))
    expansion_ts = _parse_utc((expansion or {}).get("generated_at_utc"))

    order_ok = True
    warnings: List[str] = []
    if sniper_ts and hints_ts and hints_ts < sniper_ts:
        order_ok = False
        warnings.append("hints_older_than_sniper")
    if hints_ts and expansion_ts and expansion_ts < hints_ts:
        order_ok = False
        warnings.append("expansion_older_than_hints")
    if sniper_ts and expansion_ts and expansion_ts < sniper_ts:
        order_ok = False
        warnings.append("expansion_older_than_sniper")

    return {
        "sniper_generated_at_utc": (sniper or {}).get("generated_at_utc"),
        "hints_generated_at_utc": (hints or {}).get("generated_at_utc"),
        "expansion_generated_at_utc": (expansion or {}).get("generated_at_utc"),
        "freshness_order_ok": order_ok,
        "warnings": warnings,
    }


def _provenance_block(
    *,
    expansion: Optional[Dict[str, Any]],
    sniper: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    routes = list((expansion or {}).get("routes_admitted") or [])
    m8_token_addrs = collect_m8_token_addrs(sniper=sniper)
    canonical, exploration = partition_canonical_routes(routes, m8_token_addrs)

    by_origin: Counter[str] = Counter()
    for route in routes:
        origin = str(route.get("origin_source") or "unknown")
        by_origin[origin] += 1

    exploration_by_origin = sum(
        1 for r in exploration if r.get("origin_source") == ORIGIN_EXPLORATION
    )

    return {
        "routes_by_origin_source": dict(by_origin),
        "canonical_routes_count": len(canonical),
        "exploration_routes_count": len(exploration),
        "routes_rejected_not_m8_derived": len(exploration),
        "exploration_origin_source_count": exploration_by_origin,
    }


def build_m8_2_acceptance_report(
    *,
    sniper: Optional[Dict[str, Any]],
    hints: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    strict: bool = True,
) -> Dict[str, Any]:
    metrics = _expansion_metrics(expansion)
    freshness = _freshness_block(sniper=sniper, hints=hints, expansion=expansion)
    provenance = _provenance_block(expansion=expansion, sniper=sniper)

    blockers: List[str] = []
    warnings: List[str] = []

    if expansion is None:
        blockers.append("M8_2_EXPANSION_ARTIFACT_MISSING")
    if hints is None:
        blockers.append("M8_2_HINTS_ARTIFACT_MISSING")
    elif not freshness["freshness_order_ok"]:
        blockers.append("HINTS_STALE")
        blockers.append("EXTERNAL_HINTS_STALE")
    elif freshness["warnings"]:
        if strict:
            blockers.append("HINTS_STALE")
        else:
            warnings.extend(freshness["warnings"])

    subgraph_ready = int(metrics.get("subgraph_ready_tokens") or 0)
    verified_second = int(metrics.get("verified_second_pool_count") or 0)
    multi_venue = int(metrics.get("multi_venue_tokens") or 0)
    connector_routes = int(metrics.get("connector_routes_count") or 0)

    if subgraph_ready < _QUALITY_GATES["subgraph_ready_tokens_min"]:
        blockers.append("SUBGRAPH_READY_LOW")
    if verified_second < _QUALITY_GATES["verified_second_pool_count_min"]:
        blockers.append("VERIFIED_SECOND_POOL_LOW")
    if multi_venue < _QUALITY_GATES["multi_venue_tokens_min"]:
        blockers.append("MULTI_VENUE_TOKENS_LOW")
    if connector_routes < _QUALITY_GATES["connector_routes_count_min"]:
        blockers.append("CONNECTOR_SYNTHESIS_WEAK")

    if not freshness.get("freshness_order_ok") and strict:
        if "EXPANSION_FRESHNESS_ORDER_VIOLATION" not in blockers:
            blockers.append("EXPANSION_FRESHNESS_ORDER_VIOLATION")

    if int(provenance.get("exploration_routes_count") or 0) > 0:
        warnings.append("M8_2_EXPLORATION_ROUTES_PRESENT")

    blockers = sorted(set(blockers))
    goal_status = "REACHED" if not blockers else "BLOCKED"

    return {
        "schema_version": "m8_2_acceptance_report.1",
        "generated_at_utc": _iso_now(),
        "layer": "M8_2_expansion",
        "metrics": metrics,
        "freshness": freshness,
        "provenance": provenance,
        "quality_gates": dict(_QUALITY_GATES),
        "blockers": blockers,
        "warnings": warnings,
        "goal_status": goal_status,
        "strict": strict,
        "m8_2_blocker_codes": sorted(_M8_2_BLOCKERS),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="M8.2 mirror/subgraph/handoff acceptance")
    ap.add_argument("--sniper", default=str(_DEFAULT_PATHS["sniper"]))
    ap.add_argument("--hints", default=str(_DEFAULT_PATHS["hints"]))
    ap.add_argument("--expansion", default=str(_DEFAULT_PATHS["expansion"]))
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/m8_2_acceptance_report_latest.json"),
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Treat freshness warnings as blockers",
    )
    args = ap.parse_args()

    report = build_m8_2_acceptance_report(
        sniper=_load(Path(args.sniper)),
        hints=_load(Path(args.hints)),
        expansion=_load(Path(args.expansion)),
        strict=bool(args.strict),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print("blockers:", report["blockers"])
    print("goal_status:", report["goal_status"])
    print("written:", out)
    return 0 if report["goal_status"] == "REACHED" else 1


if __name__ == "__main__":
    sys.exit(main())
