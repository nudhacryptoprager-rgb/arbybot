"""Per-DEX quality matrix: discovery → verify → quote → cycle economics."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set

from m9.graph_arb.adapter_families import (
    DEX_TO_FAMILY,
    balancer_route_metadata_complete,
    family_contract,
    family_for_dex,
)
from m9.graph_arb.expansion_admission import is_sane_measured_depth
from m9.graph_arb.pool_quality import productive_admission_ok

_QUOTE_OK_PREFIXES = ("QUOTE_OK", "OK", "PASS", "SUCCESS")


def _status_quoteable(status: Any) -> bool:
    qss = str(status or "")
    if not qss or qss in ("not_run", "skipped_registry", ""):
        return False
    upper = qss.upper()
    return any(upper.startswith(p) for p in _QUOTE_OK_PREFIXES)


def _top_rejects(errors: Dict[str, int], n: int = 3) -> Dict[str, int]:
    items = sorted(errors.items(), key=lambda kv: -int(kv[1]))[:n]
    return {str(k): int(v) for k, v in items}


def configured_dex_ids(config: Optional[Dict[str, Any]]) -> List[str]:
    if not config:
        return sorted(DEX_TO_FAMILY.keys())
    dexes = config.get("dexes") or {}
    enabled = [
        str(dex_id)
        for dex_id, row in dexes.items()
        if isinstance(row, dict) and row.get("enabled", True)
    ]
    return sorted(enabled)


def _empty_row(dex_id: str) -> Dict[str, Any]:
    fam = family_for_dex(dex_id)
    return {
        "dex_id": dex_id,
        "adapter_family": fam,
        "family_contract": family_contract(fam),
        "discovered": 0,
        "verified": 0,
        "depth_ok": 0,
        "route_quote_ok": 0,
        "productive_quote_ok": 0,
        "measured_depth_sane": 0,
        "productive_admitted": 0,
        "route_quoteable_in_cycles": 0,
        "cycle_quoteable": 0,
        "econ_size_quoteable": 0,
        "bridge_active_routes": 0,
        "cycles_found": 0,
        "cycles_quoteable": 0,
        "qsr": None,
        "reject_top3": {},
        "m8_participation_routes": 0,
        "hint_only_routes": 0,
        "metadata_complete": True,
    }


def _aggregate_routes_by_dex(
    routes: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    agg: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "bridge_active": 0,
            "verified": 0,
            "depth_ok": 0,
            "route_quote_ok": 0,
            "productive_quote_ok": 0,
            "measured_depth_sane": 0,
            "productive_admitted": 0,
            "m8": 0,
            "hint_only": 0,
            "metadata_incomplete": 0,
        }
    )
    for route in routes:
        dex = str(route.get("dex_id") or "unknown")
        bucket = agg[dex]
        bucket["bridge_active"] += 1
        if route.get("factory_verified"):
            bucket["verified"] += 1
        if route.get("depth_probe_ok") or (
            route.get("effective_depth_usd") is not None
            and float(route.get("effective_depth_usd") or 0) > 0
        ):
            bucket["depth_ok"] += 1
        if _status_quoteable(route.get("quote_smoke_status") or route.get("quote_smoke")):
            bucket["route_quote_ok"] += 1
        if _status_quoteable(route.get("productive_quote_status")):
            bucket["productive_quote_ok"] += 1
        if is_sane_measured_depth(route):
            bucket["measured_depth_sane"] += 1
        if productive_admission_ok(route):
            bucket["productive_admitted"] += 1
        if route.get("source") == "m8_sniper":
            bucket["m8"] += 1
        hint = str(route.get("hint_status") or "")
        if hint and hint.startswith("HINT_") and "VERIFIED" not in hint:
            bucket["hint_only"] += 1
        if not balancer_route_metadata_complete(route):
            bucket["metadata_incomplete"] += 1
    return agg


def _expansion_counts(expansion: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    summary = (expansion or {}).get("summary") or {}
    discovered = dict(summary.get("pools_found_by_dex") or summary.get("admitted_by_dex") or {})
    quoteable = dict(summary.get("quoteable_by_dex") or {})
    verified = dict(summary.get("resolved_by_dex") or {})
    return {
        "discovered": {str(k): int(v) for k, v in discovered.items()},
        "quoteable": {str(k): int(v) for k, v in quoteable.items()},
        "verified": {str(k): int(v) for k, v in verified.items()},
    }


def _shadow_cycle_stats(shadow: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Per-adapter-family cycle stats from shadow artifact."""
    by_family = dict((shadow or {}).get("cycles_by_adapter_family") or {})
    edge_hist = list((shadow or {}).get("edge_error_histogram") or [])
    reject_by_dex: Dict[str, Counter[str]] = defaultdict(Counter)
    for edge in edge_hist:
        rid = str(edge.get("route_id") or "")
        dex = rid.split(":", 1)[0] if ":" in rid else str(edge.get("dex_id") or "unknown")
        for reason, count in (edge.get("errors") or {}).items():
            reject_by_dex[dex][str(reason)] += int(count)

    cycles_found = int((shadow or {}).get("cycles_found") or 0)
    cycles_quoteable = int((shadow or {}).get("cycles_quoteable") or 0)
    qsr = (shadow or {}).get("qsr")

    out: Dict[str, Dict[str, Any]] = {}
    for dex in set(list(reject_by_dex.keys()) + list(by_family.keys())):
        out[dex] = {
            "cycles_found": int(by_family.get(dex, 0)),
            "cycles_quoteable": 0,
            "qsr": None,
            "reject_top3": dict(reject_by_dex.get(dex, {})),
        }
    if cycles_found and cycles_quoteable:
        for dex in out:
            out[dex]["qsr"] = round(
                out[dex]["cycles_quoteable"] / max(out[dex]["cycles_found"], 1), 4
            )
    global_qsr = qsr
    return {
        "_global": {
            "cycles_found": cycles_found,
            "cycles_quoteable": cycles_quoteable,
            "qsr": global_qsr,
        },
        "by_dex_rejects": {k: dict(v) for k, v in reject_by_dex.items()},
        "by_family_cycles": by_family,
    }


def _econ_floor_usd(shadow: Optional[Dict[str, Any]]) -> float:
    try:
        from m9.graph_arb.size_truth import economic_size_floor_usd

        cost = (shadow or {}).get("cost_model") or {}
        return float(economic_size_floor_usd(**cost) if isinstance(cost, dict) else economic_size_floor_usd())
    except Exception:
        return 25.0


def _per_dex_cycle_funnel(shadow: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Route/cycle quoteability from shadow artifact (post-run)."""
    out: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {
            "route_quoteable_in_cycles": 0,
            "cycle_quoteable": 0,
            "econ_size_quoteable": 0,
        }
    )
    if not shadow:
        return {}
    econ_floor = _econ_floor_usd(shadow)
    for qr in shadow.get("top_cycles") or []:
        if not isinstance(qr, dict):
            continue
        status = str(qr.get("status") or "")
        size = float(qr.get("market_size_usd") or qr.get("size_usd") or 0)
        quoteable = status in ("POSITIVE_GROSS", "NEGATIVE_GROSS")
        econ_ok = quoteable and size >= econ_floor
        dexes_in_cycle: Set[str] = set()
        for leg in qr.get("legs") or []:
            if not isinstance(leg, dict):
                continue
            dex = str(leg.get("dex_id") or "")
            if dex:
                dexes_in_cycle.add(dex)
        for dex in dexes_in_cycle:
            out[dex]["route_quoteable_in_cycles"] += 1
            if quoteable:
                out[dex]["cycle_quoteable"] += 1
            if econ_ok:
                out[dex]["econ_size_quoteable"] += 1
    return {k: dict(v) for k, v in out.items()}


def build_dex_quality_matrix(
    *,
    config: Optional[Dict[str, Any]] = None,
    bridge: Optional[Dict[str, Any]] = None,
    expansion: Optional[Dict[str, Any]] = None,
    shadow: Optional[Dict[str, Any]] = None,
    productive_dexes: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Build per-dex_id quality matrix artifact."""
    dex_ids = configured_dex_ids(config)
    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    routes = list((bridge or {}).get("active_routes") or [])
    route_agg = _aggregate_routes_by_dex(routes)
    exp = _expansion_counts(expansion)
    shadow_stats = _shadow_cycle_stats(shadow)
    global_shadow = shadow_stats.get("_global") or {}
    cycle_funnel = _per_dex_cycle_funnel(shadow)
    _productive_dexes = productive_dexes or frozenset()

    matrix: Dict[str, Dict[str, Any]] = {}
    for dex_id in dex_ids:
        row = _empty_row(dex_id)
        ra = route_agg.get(dex_id, {})
        row["discovered"] = int(exp["discovered"].get(dex_id, 0))
        row["verified"] = max(
            int(exp["verified"].get(dex_id, 0)),
            int(ra.get("verified", 0)),
        )
        row["depth_ok"] = int(ra.get("depth_ok", 0))
        row["route_quote_ok"] = max(
            int(exp["quoteable"].get(dex_id, 0)),
            int(ra.get("route_quote_ok", 0)),
        )
        row["productive_quote_ok"] = int(ra.get("productive_quote_ok", 0))
        row["measured_depth_sane"] = int(ra.get("measured_depth_sane", 0))
        row["productive_admitted"] = int(ra.get("productive_admitted", 0))
        cf = cycle_funnel.get(dex_id, {})
        row["route_quoteable_in_cycles"] = int(cf.get("route_quoteable_in_cycles", 0))
        row["cycle_quoteable"] = int(cf.get("cycle_quoteable", 0))
        row["econ_size_quoteable"] = int(cf.get("econ_size_quoteable", 0))
        row["bridge_active_routes"] = int(ra.get("bridge_active", 0))
        row["m8_participation_routes"] = int(ra.get("m8", 0))
        row["hint_only_routes"] = int(ra.get("hint_only", 0))
        row["metadata_complete"] = int(ra.get("metadata_incomplete", 0)) == 0
        rejects = shadow_stats.get("by_dex_rejects", {}).get(dex_id, {})
        row["reject_top3"] = _top_rejects(rejects)
        fam_cycles = shadow_stats.get("by_family_cycles", {}).get(dex_id)
        if fam_cycles is not None:
            row["cycles_found"] = int(fam_cycles)
        matrix[dex_id] = row

    visible_in_bridge = sum(1 for r in matrix.values() if r["bridge_active_routes"] > 0)
    blockers: List[str] = []
    if int(global_shadow.get("cycles_quoteable") or 0) == 0:
        blockers.append("NO_QUOTEABLE_CYCLES")
    weak = [
        dex
        for dex, row in matrix.items()
        if row["verified"] > 0 and row["productive_quote_ok"] == 0
    ]
    if weak:
        blockers.append("VERIFIED_BUT_NOT_PRODUCTIVE_QUOTE")
    missing_discovery = [
        dex
        for dex in dex_ids
        if matrix[dex]["discovered"] == 0
        and matrix[dex]["bridge_active_routes"] == 0
        and dex in DEX_TO_FAMILY
    ]
    if missing_discovery:
        blockers.append("CONFIGURED_DEX_NO_DISCOVERY_EVIDENCE")

    _distinct_dexes = {"curve_stable", "balancer_vault", "maverick_v2"}
    _exp_summary = (expansion or {}).get("summary") or {}
    _pools_by_dex = _exp_summary.get("pools_found_by_dex") or {}
    _distinct_found = sum(int(_pools_by_dex.get(d, 0) or 0) for d in _distinct_dexes)
    _distinct_active = int(bsm.get("active_distinct_pricing_routes") or 0)
    _distinct_quoteable = sum(
        int(matrix.get(d, {}).get("productive_quote_ok") or 0) for d in _distinct_dexes
    )
    _shadow_cm_quoteable = int(
        (shadow or {}).get("cross_mechanic_cycles_quoteable") or 0
    )
    _distinct_in_cycles = _shadow_cm_quoteable if _shadow_cm_quoteable > 0 else sum(
        int(matrix.get(d, {}).get("cycles_quoteable") or 0) for d in _distinct_dexes
    )

  # Per-route funnel snapshot for distinct-pricing RCA (step 1 matrix).
    funnel_rows: Dict[str, Dict[str, int]] = {}
    for route in routes:
        dex = str(route.get("dex_id") or "unknown")
        bucket = funnel_rows.setdefault(
            dex,
            {
                "found": 0,
                "verified": 0,
                "measured_depth": 0,
                "productive_admitted": 0,
                "route_quoteable": 0,
            },
        )
        bucket["found"] += 1
        if route.get("factory_verified"):
            bucket["verified"] += 1
        if is_sane_measured_depth(route):
            bucket["measured_depth"] += 1
        if productive_admission_ok(route):
            bucket["productive_admitted"] += 1
        if _status_quoteable(route.get("productive_quote_status")):
            bucket["route_quoteable"] += 1
    for dex, cf in cycle_funnel.items():
        fr = funnel_rows.setdefault(dex, {})
        fr["in_cycles"] = int(cf.get("route_quoteable_in_cycles", 0))
        fr["cycle_quoteable"] = int(cf.get("cycle_quoteable", 0))
        fr["econ_size_quoteable"] = int(cf.get("econ_size_quoteable", 0))

    return {
        "schema_version": "m9_dex_quality_matrix.2",
        "per_dex_funnel": funnel_rows,
        "configured_dex_count": len(dex_ids),
        "visible_in_bridge_count": visible_in_bridge,
        "distinct_pricing": {
            "distinct_pricing_found": _distinct_found,
            "distinct_pricing_active": _distinct_active,
            "distinct_pricing_quoteable": _distinct_quoteable,
            "distinct_pricing_in_cycles": _distinct_in_cycles,
        },
        "expansion_dex_ids_checked": list(
            ((expansion or {}).get("summary") or {}).get("dex_ids_checked") or []
        ),
        "global_shadow": global_shadow,
        "distinct_pricing_lane": {
            k: bsm.get(k)
            for k in (
                "curve_lane_ready",
                "balancer_lane_ready",
                "maverick_lane_ready",
                "productive_curve_quoteable_routes",
                "productive_balancer_quoteable_routes",
                "productive_maverick_quoteable_routes",
            )
            if bsm.get(k) is not None
        },
        "expansion_distinct_lane": {
            k: ((expansion or {}).get("summary") or {}).get(k)
            for k in (
                "curve_lane_ready",
                "curve_routes_ready",
                "balancer_lane_ready",
                "maverick_lane_ready",
            )
            if ((expansion or {}).get("summary") or {}).get(k) is not None
        },
        "matrix": matrix,
        "blockers": blockers,
        "goal_status": "BLOCKED" if blockers else "PARTIAL",
    }
