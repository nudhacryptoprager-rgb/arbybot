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
    "radar": REPO_ROOT / "data/runs/_rolling/m8_radar_pool_candidates_latest.json",
    "expansion": REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json",
}

_GRAPH_HANDOFF_CYCLE_POTENTIAL_MIN = 12

_QUALITY_GATES = {
    "subgraph_ready_tokens_min": 3,
    "mirror_quote_ready_tokens_min": 1,
    "graph_topology_ready_tokens_min": 1,
    "verified_second_pool_count_min": 10,
    "multi_venue_tokens_min": 14,
    "connector_routes_count_min": 1,
}

_M8_2_BLOCKERS = frozenset(
    {
        "SUBGRAPH_READY_LOW",
        "MIRROR_READY_LOW",
        "GRAPH_TOPOLOGY_READY_LOW",
        "VERIFIED_SECOND_POOL_LOW",
        "HINTS_STALE",
        "EXTERNAL_HINTS_STALE",
        "CONNECTOR_SYNTHESIS_WEAK",
        "MULTI_VENUE_TOKENS_LOW",
        "EXPANSION_FRESHNESS_ORDER_VIOLATION",
        "M8_2_EXPANSION_ARTIFACT_MISSING",
        "M8_2_HINTS_ARTIFACT_MISSING",
        "ACTIVE_SCAN_COVERAGE_INCOMPLETE",
        "CANDIDATE_DEX_COVERAGE_INCOMPLETE",
        "HIGH_STALE_HINT_RATE",
    }
)

_COVERAGE_BLOCKERS = frozenset(
    {
        "ACTIVE_SCAN_COVERAGE_INCOMPLETE",
        "CANDIDATE_DEX_COVERAGE_INCOMPLETE",
        "M8_2_EXPANSION_ARTIFACT_MISSING",
    }
)

_QUALITY_BLOCKERS = frozenset(
    {
        "SUBGRAPH_READY_LOW",
        "MIRROR_READY_LOW",
        "GRAPH_TOPOLOGY_READY_LOW",
        "VERIFIED_SECOND_POOL_LOW",
        "MULTI_VENUE_TOKENS_LOW",
        "CONNECTOR_SYNTHESIS_WEAK",
    }
)

_EXTERNAL_RADAR_BLOCKERS = frozenset(
    {
        "HINTS_STALE",
        "EXTERNAL_HINTS_STALE",
        "EXPANSION_FRESHNESS_ORDER_VIOLATION",
        "M8_2_HINTS_ARTIFACT_MISSING",
        "HIGH_STALE_HINT_RATE",
    }
)

_FRESHNESS_BLOCKERS = frozenset(_EXTERNAL_RADAR_BLOCKERS) | frozenset(
    {"HINTS_STALE", "EXTERNAL_HINTS_STALE"}
)

_HANDOFF_BLOCKERS = frozenset(_QUALITY_BLOCKERS) | frozenset({"MIRROR_READY_LOW"})

_COVERAGE_MIN_RATE = 0.98
_STALE_HINT_RATE_MAX = 0.85


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


def _per_source_yield(
    hints: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    hm = (hints or {}).get("metrics") or {}
    yield_table = dict(hm.get("per_source_verified_yield") or {})
    second_venue = dict(hm.get("second_venue_source") or {})
    for source, count in second_venue.items():
        yield_table.setdefault(source, int(count or 0))
    exp_summary = (expansion or {}).get("summary") or {}
    specialized = int(exp_summary.get("specialized_index_tokens_matched") or 0)
    if specialized:
        yield_table["specialized_index"] = specialized
    active_scan = int(exp_summary.get("active_factory_second_pool_count") or 0)
    if active_scan:
        yield_table["active_factory_scan"] = active_scan
    return yield_table


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
        "active_factory_second_pool_count": summary.get(
            "active_factory_second_pool_count"
        ),
        "connector_routes_count": summary.get("connector_routes_count"),
        "subgraph_ready_tokens": summary.get("subgraph_ready_tokens"),
        "mirror_topology_ready_tokens": summary.get("mirror_topology_ready_tokens"),
        "mirror_quote_ready_tokens": summary.get("mirror_quote_ready_tokens"),
        "same_pair_mirror_tokens": summary.get("same_pair_mirror_tokens"),
        "graph_topology_ready_tokens": summary.get("graph_topology_ready_tokens"),
        "cross_anchor_ready_tokens": summary.get("cross_anchor_ready_tokens"),
        "token_presence_graph_ready_tokens": summary.get(
            "token_presence_graph_ready_tokens"
        ),
        "connector_graph_ready_tokens": summary.get("connector_graph_ready_tokens"),
        "two_leg_mirror_ready_tokens": summary.get("two_leg_mirror_ready_tokens"),
        "graph_handoff_ready_tokens": summary.get("graph_handoff_ready_tokens"),
        "graph_handoff_cycle_potential_routes": summary.get(
            "graph_handoff_cycle_potential_routes"
        )
        or (expansion or {}).get("graph_handoff", {}).get(
            "graph_handoff_cycle_potential_routes"
        ),
        "handoff_lane": summary.get("handoff_lane")
        or (expansion or {}).get("handoff_lane"),
        "handoff_funnel": summary.get("handoff_funnel")
        or (expansion or {}).get("graph_handoff", {}).get("handoff_funnel"),
        "mirror_tokens": summary.get("mirror_tokens"),
        "v4_event_index_coverage_rate": summary.get("v4_event_index_coverage_rate"),
        "v4_event_index_hit_rate": summary.get("v4_event_index_hit_rate"),
        "hint_tokens_matched": summary.get("hint_tokens_matched"),
        "external_hints_enabled": summary.get("external_hints_enabled"),
        "second_pool_hints_found": summary.get("second_pool_hints_found"),
        "hint_to_verified_pool_rate": summary.get("hint_to_verified_pool_rate"),
        "canonical_routes_count": summary.get("canonical_routes_count"),
        "exploration_routes_count": summary.get("exploration_routes_count"),
        "routes_rejected_not_m8_derived": summary.get("routes_rejected_not_m8_derived"),
        "active_scan_coverage_rate": summary.get("active_scan_coverage_rate"),
        "scan_expected_attempts": summary.get("scan_expected_attempts"),
        "scan_actual_attempts": summary.get("scan_actual_attempts"),
        "candidate_dexes_seen": summary.get("candidate_dexes_seen"),
        "candidate_dexes_configured": summary.get("candidate_dexes_configured"),
        "unsupported_candidate_dexes": summary.get("unsupported_candidate_dexes"),
        "candidate_scan_coverage_rate": summary.get("candidate_scan_coverage_rate"),
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
    summary = (expansion or {}).get("summary") or {}
    if summary.get("routes_by_origin_source"):
        return {
            "routes_by_origin_source": dict(summary.get("routes_by_origin_source") or {}),
            "canonical_routes_count": int(summary.get("canonical_routes_count") or 0),
            "exploration_routes_count": int(summary.get("exploration_routes_count") or 0),
            "routes_rejected_not_m8_derived": int(
                summary.get("routes_rejected_not_m8_derived") or 0
            ),
            "exploration_note": (
                "exploration routes lack M8-derived provenance or verified evidence; "
                "partitioned from canonical bridge handoff"
            ),
        }

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
        "exploration_note": (
            "exploration routes lack M8-derived provenance or verified evidence"
        ),
    }


def _mirror_debug_block(expansion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sample = (expansion or {}).get("same_pair_mirror_ready_debug") or (
        (expansion or {}).get("summary") or {}
    ).get("same_pair_mirror_ready_debug") or []
    mirror_tokens = (expansion or {}).get("mirror_tokens") or (
        (expansion or {}).get("summary") or {}
    ).get("mirror_tokens") or []
    if not sample and not mirror_tokens:
        return {"sample_count": 0, "top_missing_reasons": {}, "mirror_tokens": []}
    reasons: Counter[str] = Counter()
    for row in sample:
        reasons[str(row.get("missing_reason") or "unknown")] += 1
    return {
        "sample_count": len(sample),
        "topology_ready_count": sum(
            1 for row in sample if row.get("mirror_topology_ready")
        ),
        "quote_ready_count": sum(1 for row in sample if row.get("mirror_quote_ready")),
        "top_missing_reasons": dict(reasons.most_common(8)),
        "sample": sample[:12],
        "mirror_tokens": mirror_tokens[:24],
    }


def _is_time_to_mirror_hot(expansion: Optional[Dict[str, Any]]) -> bool:
    summary = (expansion or {}).get("summary") or {}
    return (
        summary.get("expansion_lane") == "time_to_mirror_hot"
        or summary.get("scan_mode") == "hot_path_incremental"
    )


def _subgraph_debug_block(expansion: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    sample = (expansion or {}).get("subgraph_ready_debug") or (
        (expansion or {}).get("summary") or {}
    ).get("subgraph_ready_debug_sample") or []
    if not sample:
        return {"sample_count": 0, "top_missing_reasons": {}}
    reasons: Counter[str] = Counter()
    for row in sample:
        reasons[str(row.get("missing_reason") or "unknown")] += 1
    return {
        "sample_count": len(sample),
        "top_missing_reasons": dict(reasons.most_common(8)),
        "sample": sample[:12],
    }


def build_m8_2_acceptance_report(
    *,
    sniper: Optional[Dict[str, Any]],
    hints: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    radar: Optional[Dict[str, Any]] = None,
    strict: bool = True,
) -> Dict[str, Any]:
    if expansion is not None:
        from m8.discovery.graph_handoff import refresh_graph_handoff_in_expansion_doc

        refresh_graph_handoff_in_expansion_doc(expansion)
    metrics = _expansion_metrics(expansion)
    freshness = _freshness_block(sniper=sniper, hints=hints, expansion=expansion)
    provenance = _provenance_block(expansion=expansion, sniper=sniper)
    per_source_yield = _per_source_yield(hints, expansion)
    subgraph_debug = _subgraph_debug_block(expansion)
    mirror_debug = _mirror_debug_block(expansion)
    from m8.discovery.candidate_dex_registry import (
        build_candidate_coverage_audit,
        build_radar_metrics,
        load_candidate_dex_registry,
    )
    from m8.discovery.scan_telemetry import build_coverage_audit

    scan_coverage = (
        build_coverage_audit(expansion, min_coverage_rate=_COVERAGE_MIN_RATE)
        if expansion is not None
        else {"blockers": ["ACTIVE_SCAN_COVERAGE_INCOMPLETE"], "goal_status": "BLOCKED"}
    )
    candidate_registry = load_candidate_dex_registry()
    candidate_coverage = (
        build_candidate_coverage_audit(
            expansion, candidate_registry, min_coverage_rate=_COVERAGE_MIN_RATE
        )
        if expansion is not None
        else {
            "blockers": ["CANDIDATE_DEX_COVERAGE_INCOMPLETE"],
            "goal_status": "BLOCKED",
        }
    )
    radar_metrics = build_radar_metrics(hints, expansion)
    from m8.discovery.radar_layer import build_radar_funnel

    radar_funnel = build_radar_funnel(
        radar=radar, hints=hints, expansion=expansion
    )
    if expansion is not None and expansion.get("summary"):
        expansion["summary"]["radar_funnel"] = radar_funnel
    if metrics.get("candidate_scan_coverage_rate") is None:
        metrics["candidate_scan_coverage_rate"] = candidate_coverage.get(
            "candidate_scan_coverage_rate"
        )

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
    mirror_topology_ready = int(metrics.get("mirror_topology_ready_tokens") or 0)
    mirror_quote_ready = int(metrics.get("mirror_quote_ready_tokens") or 0)
    graph_topology_ready = int(metrics.get("graph_topology_ready_tokens") or 0)
    cross_anchor_ready = int(metrics.get("cross_anchor_ready_tokens") or 0)
    connector_graph_ready = int(metrics.get("connector_graph_ready_tokens") or 0)
    verified_second = int(metrics.get("verified_second_pool_count") or 0)
    multi_venue = int(metrics.get("multi_venue_tokens") or 0)
    connector_routes = int(metrics.get("connector_routes_count") or 0)
    cycle_potential = int(metrics.get("graph_handoff_cycle_potential_routes") or 0)

    subgraph_lane_ready = (
        subgraph_ready >= _QUALITY_GATES["subgraph_ready_tokens_min"]
    )
    mirror_lane_ready = (
        mirror_quote_ready >= _QUALITY_GATES["mirror_quote_ready_tokens_min"]
    )
    graph_topology_lane_ready = (
        graph_topology_ready >= _QUALITY_GATES["graph_topology_ready_tokens_min"]
    )
    if not subgraph_lane_ready:
        blockers.append("SUBGRAPH_READY_LOW")
    if not mirror_lane_ready:
        blockers.append("MIRROR_READY_LOW")
        if mirror_topology_ready > 0:
            warnings.append("MIRROR_TOPOLOGY_NOT_QUOTE_READY")
    if not graph_topology_lane_ready:
        blockers.append("GRAPH_TOPOLOGY_READY_LOW")
        if cross_anchor_ready > 0 or connector_graph_ready > 0:
            warnings.append("GRAPH_PARTIAL_TOPOLOGY_ONLY")
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

    for cov_blocker in scan_coverage.get("blockers") or []:
        blockers.append(str(cov_blocker))
    for cand_blocker in candidate_coverage.get("blockers") or []:
        blockers.append(str(cand_blocker))

    stale_rate = float(radar_metrics.get("stale_hint_rate") or 0.0)
    if stale_rate > _STALE_HINT_RATE_MAX and hints is not None:
        blockers.append("HIGH_STALE_HINT_RATE")

    blockers = sorted(set(blockers))
    if _is_time_to_mirror_hot(expansion) and mirror_lane_ready:
        if "HIGH_STALE_HINT_RATE" in blockers:
            blockers.remove("HIGH_STALE_HINT_RATE")
            if "STALE_HINT_RATE_HIGH" not in warnings:
                warnings.append("STALE_HINT_RATE_HIGH")
        blockers = sorted(set(blockers))

    coverage_blockers = sorted(b for b in blockers if b in _COVERAGE_BLOCKERS)
    quality_blockers = sorted(b for b in blockers if b in _QUALITY_BLOCKERS)
    external_radar_blockers = sorted(
        b for b in blockers if b in _EXTERNAL_RADAR_BLOCKERS
    )
    freshness_blockers = sorted(b for b in blockers if b in _FRESHNESS_BLOCKERS)
    handoff_blockers = sorted(b for b in blockers if b in _HANDOFF_BLOCKERS)
    if mirror_lane_ready:
        handoff_lane = "mirror_2leg"
    elif graph_topology_lane_ready:
        handoff_lane = "graph_topology"
    elif subgraph_lane_ready:
        handoff_lane = "subgraph_3plus"
    else:
        handoff_lane = "none"
    handoff_ready = (
        mirror_lane_ready or graph_topology_lane_ready or subgraph_lane_ready
    )
    if handoff_ready and cycle_potential < _GRAPH_HANDOFF_CYCLE_POTENTIAL_MIN:
        warnings.append("GRAPH_HANDOFF_CYCLE_POTENTIAL_LOW")
    m9_handoff_status = {
        "two_leg_mirror_ready": mirror_lane_ready,
        "graph_handoff_ready": graph_topology_lane_ready,
        "m9_quote_ready": False,
        "economics_claim": False,
        "requires_m9_quote": graph_topology_lane_ready or mirror_lane_ready,
    }
    hard_blockers = [
        b
        for b in blockers
        if b not in _QUALITY_BLOCKERS or not handoff_ready
    ]
    goal_status = "REACHED" if not hard_blockers else "BLOCKED"

    return {
        "schema_version": "m8_2_acceptance_report.6",
        "generated_at_utc": _iso_now(),
        "layer": "M8_2_expansion",
        "graph_topology_ready_tokens": graph_topology_ready,
        "cross_anchor_ready_tokens": cross_anchor_ready,
        "connector_graph_ready_tokens": connector_graph_ready,
        "token_presence_graph_ready_tokens": int(
            metrics.get("token_presence_graph_ready_tokens") or 0
        ),
        "mirror_quote_ready_tokens": mirror_quote_ready,
        "graph_handoff_cycle_potential_routes": cycle_potential,
        "handoff_funnel": metrics.get("handoff_funnel"),
        "metrics": metrics,
        "freshness": freshness,
        "provenance": provenance,
        "per_source_verified_yield": per_source_yield,
        "subgraph_ready_debug": subgraph_debug,
        "mirror_ready_debug": mirror_debug,
        "graph_topology_ready_debug": (
            (expansion or {}).get("summary", {}).get("graph_topology_ready_debug")
            or (expansion or {}).get("graph_handoff", {}).get("graph_topology_ready_debug")
            or []
        ),
        "mirror_tokens": mirror_debug.get("mirror_tokens") or metrics.get("mirror_tokens") or [],
        "handoff_lane": handoff_lane,
        "handoff_ready": handoff_ready,
        "m9_handoff_status": m9_handoff_status,
        "scan_coverage": scan_coverage,
        "candidate_coverage": candidate_coverage,
        "radar_metrics": radar_metrics,
        "radar_funnel": radar_funnel,
        "coverage_blockers": coverage_blockers,
        "quality_blockers": quality_blockers,
        "freshness_blockers": freshness_blockers,
        "handoff_blockers": handoff_blockers,
        "external_radar_blockers": external_radar_blockers,
        "time_to_mirror_hot": _is_time_to_mirror_hot(expansion),
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
    ap.add_argument("--radar", default=str(_DEFAULT_PATHS["radar"]))
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

    expansion_path = Path(args.expansion)
    expansion_doc = _load(expansion_path)
    report = build_m8_2_acceptance_report(
        sniper=_load(Path(args.sniper)),
        hints=_load(Path(args.hints)),
        expansion=expansion_doc,
        radar=_load(Path(args.radar)),
        strict=bool(args.strict),
    )
    if expansion_doc is not None:
        expansion_path.write_text(
            json.dumps(expansion_doc, ensure_ascii=False, indent=2), encoding="utf-8"
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
