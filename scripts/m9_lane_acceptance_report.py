#!/usr/bin/env python3
"""Per-layer M8→M8.1→M8.2→M9 bridge acceptance report from rolling artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_PATHS = {
    "sniper": REPO_ROOT / "data/runs/_rolling/new_pool_sniper_latest.json",
    "anchor": REPO_ROOT / "data/runs/_rolling/m8_1_stable_anchor_latest.json",
    "expansion": REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    "bridge": REPO_ROOT / "data/tmp/m9_bridge_inventory_shadow_latest.json",
    "shadow": REPO_ROOT / "data/tmp/m9_graph_bridge_shadow_latest.json",
    "rca": REPO_ROOT / "data/tmp/m9_quote_lane_rca_latest.json",
}


def _load(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _dex_coverage(
    bridge: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    active = (bridge or {}).get("active_routes") or []
    configured = set()
    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    for dex in bsm.get("expansion_dex_ids_checked") or []:
        configured.add(str(dex))
    for r in active:
        if r.get("dex_id"):
            configured.add(str(r["dex_id"]))

    indexed = Counter()
    exp_metrics = (expansion or {}).get("metrics") or {}
    for dex, count in (exp_metrics.get("pools_found_by_dex") or {}).items():
        indexed[str(dex)] = int(count or 0)

    verified = Counter()
    for dex, count in (bsm.get("expansion_quoteable_by_dex") or {}).items():
        verified[str(dex)] = int(count or 0)

    bridge_active = Counter(str(r.get("dex_id") or "unknown") for r in active)
    cross_mechanic = Counter(
        str(r.get("dex_id") or "unknown")
        for r in active
        if r.get("cross_mechanic")
    )

    cycles_by_family = dict((shadow or {}).get("cycles_by_adapter_family") or {})
    return {
        "configured_dex_ids": sorted(configured),
        "indexed_pools_by_dex": dict(indexed),
        "verified_quoteable_by_dex": dict(verified),
        "bridge_active_routes_by_dex": dict(bridge_active),
        "cross_mechanic_routes_by_dex": dict(cross_mechanic),
        "cycles_by_adapter_family": cycles_by_family,
    }


def _cross_mechanic_topology(
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    active = (bridge or {}).get("active_routes") or []
    cm_routes = [r for r in active if r.get("cross_mechanic")]
    cm_pools = {
        str(r.get("pool_address", "")).lower()
        for r in cm_routes
        if r.get("pool_address")
    }
    cm_tokens = Counter(
        str(r.get("focus_token_symbol") or r.get("token1") or r.get("token0") or "?")
        for r in cm_routes
    )
    connector_tokens = Counter(
        str(r.get("connector_token") or "")
        for r in cm_routes
        if r.get("connector_token")
    )

    shadow_summary = {
        "cycles_found": (shadow or {}).get("cycles_found"),
        "cycles_quoteable": (shadow or {}).get("cycles_quoteable"),
        "cross_mechanic_cycles": (shadow or {}).get("cross_mechanic_cycles"),
    }
    bsm = (shadow or {}).get("bridge_source_metrics") or {}
    if bsm.get("cross_mechanic_cycles") is not None:
        shadow_summary["cross_mechanic_cycles"] = bsm.get("cross_mechanic_cycles")
    if bsm.get("expected_cross_mechanic_cycles") is not None:
        shadow_summary["expected_cross_mechanic_cycles"] = bsm.get(
            "expected_cross_mechanic_cycles"
        )

    top_cycles = (shadow or {}).get("top_cycles") or []
    cm_touched = 0
    for cyc in top_cycles:
        for leg in cyc.get("legs") or []:
            if (leg.get("pool_address") or "").lower() in cm_pools:
                cm_touched += 1
                break

    hints: List[str] = []
    if cm_routes and int(shadow_summary.get("cross_mechanic_cycles") or 0) == 0:
        if cm_touched == 0:
            hints.append("cross_mechanic_pools_not_in_sampled_cycles")
        if len(connector_tokens) < 2:
            hints.append("connector_token_diversity_low")
        leaf_only = sum(
            1 for r in cm_routes
            if not r.get("connector_token") and r.get("expansion_route_kind") == "token_presence"
        )
        if leaf_only == len(cm_routes):
            hints.append("cross_mechanic_routes_may_be_leaf_only")

    return {
        "cross_mechanic_route_count": len(cm_routes),
        "cross_mechanic_unique_pools": len(cm_pools),
        "focus_token_histogram": dict(cm_tokens.most_common(12)),
        "connector_token_histogram": dict(connector_tokens.most_common(12)),
        "shadow_cycle_summary": shadow_summary,
        "cross_mechanic_in_top_cycles_sample": cm_touched,
        "diagnostic_hints": hints,
    }


def build_acceptance_report(
    *,
    sniper: Optional[Dict[str, Any]],
    anchor: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    rca: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    sniper_metrics = (sniper or {}).get("metrics") or {}
    anchor_metrics = (anchor or {}).get("metrics") or {}
    exp_metrics = (expansion or {}).get("metrics") or {}
    bsm = (bridge or {}).get("bridge_source_metrics") or {}

    funnel_layers = [
        {
            "layer": "M8_sniper",
            "input": sniper_metrics.get("snipe_candidates_total")
            or len((sniper or {}).get("recent_events") or []),
            "status": (sniper or {}).get("status"),
            "rpc_errors": sniper_metrics.get("rpc_errors"),
        },
        {
            "layer": "M8_bridge_input",
            "m8_new_pools_input": bsm.get("m8_new_pools_input"),
            "token_verified": bsm.get("token_verified_count"),
            "anchor_connected": bsm.get("anchor_connected_count"),
            "cross_dex_seen": bsm.get("cross_dex_seen_count"),
            "multi_venue_quoteable": bsm.get("m8_multi_venue_quoteable_count"),
            "graph_ready_from_m8": bsm.get("graph_ready_from_m8"),
            "m8_funnel_reject_histogram": bsm.get("m8_funnel_reject_histogram"),
        },
        {
            "layer": "M8_1_anchor",
            "passes": anchor_metrics.get("stable_anchor_passes_total"),
            "qsr": anchor_metrics.get("qsr"),
            "status": (anchor or {}).get("status"),
        },
        {
            "layer": "M8_2_expansion",
            "routes_admitted": exp_metrics.get("routes_admitted"),
            "multi_venue_tokens": exp_metrics.get("multi_venue_tokens"),
            "connector_routes": exp_metrics.get("connector_routes"),
        },
        {
            "layer": "M9_bridge",
            "graph_ready_total": bsm.get("graph_ready_total"),
            "graph_ready_from_expansion": bsm.get("graph_ready_from_expansion"),
            "active_routes": len((bridge or {}).get("active_routes") or []),
            "cross_mechanic_routes": sum(
                1
                for r in (bridge or {}).get("active_routes") or []
                if r.get("cross_mechanic")
            ),
        },
        {
            "layer": "M9_shadow",
            "cycles_found": (shadow or {}).get("cycles_found"),
            "cycles_quoteable": (shadow or {}).get("cycles_quoteable"),
            "cycles_positive_gross": (shadow or {}).get("cycles_positive_gross"),
            "qsr": (shadow or {}).get("qsr"),
            "cross_mechanic_cycles": (shadow or {}).get("cross_mechanic_cycles"),
            "cross_mechanic_cycles_found": (
                (shadow or {}).get("cross_mechanic_cycles_found")
                or (shadow or {}).get("cross_mechanic_cycles")
            ),
            "cross_mechanic_cycles_quoteable": int(
                (shadow or {}).get("cross_mechanic_cycles_quoteable") or 0
            ),
            "cycles_with_m8_pool": (shadow or {}).get("cycles_with_m8_pool"),
        },
        {
            "layer": "M8_freshness",
            "m8_stale": bsm.get("m8_stale"),
            "sniper_age_seconds": bsm.get("sniper_age_seconds"),
            "sniper_generated_at_utc": bsm.get("sniper_generated_at_utc"),
            "m8_stale_threshold_seconds": bsm.get("m8_stale_threshold_seconds"),
            "sniper_status": (sniper or {}).get("status"),
        },
    ]

    shadow_cycles_found = int((shadow or {}).get("cycles_found") or 0)
    shadow_cycles_quoteable = int((shadow or {}).get("cycles_quoteable") or 0)
    shadow_qsr = float((shadow or {}).get("qsr") or 0.0)
    shadow_cycles_with_m8 = int((shadow or {}).get("cycles_with_m8_pool") or 0)
    phantom_count = int(
        ((shadow or {}).get("phantom_quote_diagnostics") or {}).get("phantom_count")
        or ((shadow or {}).get("cycle_reject_histogram") or {}).get(
            "PHANTOM_QUOTE_BPS_OVERFLOW", 0
        )
        or 0
    )

    blockers: List[str] = []
    if int(bsm.get("graph_ready_from_m8") or 0) == 0:
        blockers.append("M8_DIRECT_INGESTION_NOT_READY")
    elif shadow_cycles_with_m8 == 0:
        blockers.append("CYCLES_WITH_M8_POOL_ZERO")
    if shadow_cycles_found > 0 and shadow_cycles_quoteable == 0:
        blockers.append("NO_QUOTEABLE_CYCLES")
    if shadow_qsr == 0.0 and shadow_cycles_found > 0:
        blockers.append("QSR_ZERO")
    if int((shadow or {}).get("cycles_positive_gross") or 0) == 0:
        blockers.append("NO_POSITIVE_GROSS")
    cm_found = int(
        (shadow or {}).get("cross_mechanic_cycles_found")
        or (shadow or {}).get("cross_mechanic_cycles")
        or 0
    )
    cm_quoteable = int((shadow or {}).get("cross_mechanic_cycles_quoteable") or 0)
    if cm_found == 0:
        blockers.append("NO_CROSS_MECHANIC_CYCLES_IN_GRAPH")
    elif cm_quoteable == 0:
        blockers.append("NO_CROSS_MECHANIC_CYCLES_QUOTEABLE")
    if phantom_count > 0:
        blockers.append("PHANTOM_QUOTE_PRESENT")
    if bsm.get("m8_stale") and int(bsm.get("graph_ready_from_m8") or 0) > 0:
        blockers.append("M8_ARTIFACT_STALE")

    return {
        "schema_version": "m9_lane_acceptance_report.1",
        "funnel_layers": funnel_layers,
        "dex_coverage": _dex_coverage(bridge, expansion, shadow),
        "cross_mechanic_topology": _cross_mechanic_topology(bridge, shadow),
        "quote_lane_rca_summary": (rca or {}).get("summary"),
        "quote_lane_top_rejects": (rca or {}).get("by_reject_reason"),
        "quote_lane_adapter_errors": (rca or {}).get("by_adapter_family_leg_errors"),
        "blockers": blockers,
        "goal_status": "BLOCKED" if blockers else "PARTIAL",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="M8→M9 per-layer acceptance report")
    ap.add_argument("--sniper", default=str(_DEFAULT_PATHS["sniper"]))
    ap.add_argument("--anchor", default=str(_DEFAULT_PATHS["anchor"]))
    ap.add_argument("--expansion", default=str(_DEFAULT_PATHS["expansion"]))
    ap.add_argument("--bridge", default=str(_DEFAULT_PATHS["bridge"]))
    ap.add_argument("--shadow", default=str(_DEFAULT_PATHS["shadow"]))
    ap.add_argument("--rca", default=str(_DEFAULT_PATHS["rca"]))
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/m9_lane_acceptance_report_latest.json"),
    )
    args = ap.parse_args()

    report = build_acceptance_report(
        sniper=_load(Path(args.sniper)),
        anchor=_load(Path(args.anchor)),
        expansion=_load(Path(args.expansion)),
        bridge=_load(Path(args.bridge)),
        shadow=_load(Path(args.shadow)),
        rca=_load(Path(args.rca)),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["funnel_layers"], indent=2))
    print("blockers:", report["blockers"])
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
