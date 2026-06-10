#!/usr/bin/env python3
"""Quote-lane diagnostic: pool smoke (Balancer/Maverick) or cycle RCA from shadow artifact."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_SHADOW = REPO_ROOT / "data/tmp/m9_graph_bridge_shadow_latest.json"
_DEFAULT_OUT = REPO_ROOT / "data/tmp/m9_quote_lane_rca_latest.json"


def _adapter_family(route_id: str, edge: Dict[str, Any]) -> str:
    rid = str(route_id or edge.get("route_id") or "")
    dex = str(edge.get("dex_id") or "")
    if rid.startswith("curve") or dex.startswith("curve"):
        return "curve"
    if "balancer" in rid or "balancer" in dex:
        return "balancer"
    if "maverick" in rid or "maverick" in dex:
        return "maverick"
    if "uniswap_v4" in rid or dex == "uniswap_v4":
        return "uniswap_v4"
    if "uniswap_v3" in rid or dex == "uniswap_v3":
        return "uniswap_v3"
    if "aerodrome" in rid or dex == "aerodrome":
        return "aerodrome"
    return dex or "unknown"


def _cycle_length_from_id(cycle_id: str) -> int:
    parts = str(cycle_id or "").split(":")
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def _adapter_rca_from_quote_diagnostics(
    artifact: Dict[str, Any],
    family: str,
    *,
    primary_reason: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Deep RCA rows from runner quote_failure_diagnostics.top_routes."""
    qfd = artifact.get("quote_failure_diagnostics") or {}
    rows: List[Dict[str, Any]] = []
    for row in qfd.get("top_routes") or []:
        if not isinstance(row, dict):
            continue
        dex = str(row.get("dex_id") or row.get("adapter_type") or "")
        if _adapter_family(str(row.get("route_id") or ""), {"dex_id": dex}) != family:
            continue
        errors = row.get("errors") or {}
        if not errors.get(primary_reason) and primary_reason not in errors:
            continue
        inv_meta: Dict[str, Any] = {}
        rows.append(
            {
                "route_id": row.get("route_id"),
                "pool_address": row.get("pool_address"),
                "pair_id": row.get("pair_id"),
                "dex_id": row.get("dex_id"),
                "adapter_type": row.get("adapter_type"),
                "top_reject_reason": primary_reason,
                "error_counts": {str(k): int(v) for k, v in errors.items()},
                "sample_raw_error": row.get("sample_raw_error"),
                "http_status": row.get("http_status"),
                **inv_meta,
            }
        )
    return rows[:limit]


def _enrich_balancer_rca(
    rows: List[Dict[str, Any]],
    inventory: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not inventory:
        return rows
    by_pool = {
        str(r.get("pool_address", "")).lower(): r
        for r in inventory.get("active_routes") or []
        if r.get("pool_address")
    }
    enriched = []
    for row in rows:
        pool = str(row.get("pool_address") or "").lower()
        inv = by_pool.get(pool) or {}
        enriched.append(
            {
                **row,
                "pool_id": inv.get("pool_id") or row.get("pool_id"),
                "vault_address": inv.get("vault_address"),
                "token0_addr": inv.get("token0_addr"),
                "token1_addr": inv.get("token1_addr"),
                "balancer_query_target": "BalancerQueries.querySwap",
            }
        )
    return enriched


def _build_m8_cycle_trace(
    artifact: Dict[str, Any],
    inventory: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Why M8 pools may not appear in quoted cycles."""
    m8_part = artifact.get("m8_participation") or {}
    m8_routes: List[Dict[str, Any]] = []
    if inventory:
        m8_routes = [
            r
            for r in inventory.get("active_routes") or []
            if r.get("source") == "m8_sniper"
        ]
    edges_in_graph = int(m8_part.get("graph_edges_from_m8") or 0)
    cycles_with_m8 = int(m8_part.get("cycles_with_m8_pool") or 0)
    cycles_with_direct = int(m8_part.get("cycles_with_direct_sniper_pool") or 0)
    cycles_with_derived = int(m8_part.get("cycles_with_m8_derived_pool") or 0)
    pool_rows = []
    for r in m8_routes[:12]:
        pool_rows.append(
            {
                "pool_address": r.get("pool_address"),
                "route_id": r.get("route_id"),
                "token0": r.get("token0"),
                "token1": r.get("token1"),
                "dex_id": r.get("dex_id"),
                "freshness_window": r.get("freshness_window"),
            }
        )
    hints: List[str] = []
    if m8_routes and edges_in_graph == 0:
        hints.append("m8_routes_present_but_zero_graph_edges")
    if edges_in_graph > 0 and cycles_with_m8 == 0:
        hints.append("m8_edges_in_graph_but_no_cycle_quotes_traversed_m8_pool")
    if not m8_routes:
        hints.append("no_m8_sniper_routes_in_active_bridge_inventory")
    return {
        "m8_sniper_routes_in_inventory": len(m8_routes),
        "graph_edges_from_m8": edges_in_graph,
        "graph_ready_from_m8": m8_part.get("graph_ready_from_m8"),
        "cycles_with_m8_pool": cycles_with_m8,
        "cycles_with_direct_sniper_pool": cycles_with_direct,
        "cycles_with_m8_derived_pool": cycles_with_derived,
        "m8_pool_addrs_tracked": m8_part.get("m8_pool_addrs_tracked"),
        "m8_route_samples": pool_rows,
        "diagnostic_hints": hints,
    }


def _build_micro_size_policy(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """Requested vs effective sizes and depth rejects."""
    sizes = list(artifact.get("sizes_usd") or [])
    reject = dict(artifact.get("cycle_reject_histogram") or {})
    oversized = int(reject.get("OVERSIZED_VS_DEPTH", 0))
    phantom = int(reject.get("PHANTOM_QUOTE_BPS_OVERFLOW", 0))
    cycles_found = int(artifact.get("cycles_found") or 0)
    top = artifact.get("top_cycles") or []
    size_hist: Counter[float] = Counter()
    for cyc in top:
        if isinstance(cyc, dict) and cyc.get("size_usd") is not None:
            size_hist[float(cyc["size_usd"])] += 1
    return {
        "configured_sizes_usd": sizes,
        "smallest_configured_usd": min(sizes) if sizes else None,
        "oversized_vs_depth_count": oversized,
        "phantom_overflow_count": phantom,
        "oversized_rate": round(oversized / cycles_found, 4) if cycles_found else 0.0,
        "top_cycle_size_histogram": dict(size_hist),
        "policy_hint": (
            "depth_cap_dominates_before_quoteable"
            if oversized > cycles_found // 3
            else None
        ),
    }


def _top_route_failures(
    edge_hist: List[Dict[str, Any]],
    route_hist: Dict[str, Any],
    family: str,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Top failing routes for a given adapter family."""
    rows: List[Dict[str, Any]] = []
    for edge in edge_hist:
        rid = str(edge.get("route_id") or "")
        if _adapter_family(rid, edge) != family:
            continue
        errors = edge.get("errors") or {}
        if not errors:
            continue
        top_reason = max(errors.items(), key=lambda kv: int(kv[1]))[0]
        rows.append(
            {
                "route_id": rid,
                "pool_address": edge.get("pool_address"),
                "pool_id": edge.get("pool_id"),
                "dex_id": edge.get("dex_id"),
                "top_reject_reason": top_reason,
                "error_counts": {str(k): int(v) for k, v in errors.items()},
            }
        )
    if len(rows) < limit:
        for route_id, errors in route_hist.items():
            if _adapter_family(str(route_id), {}) != family:
                continue
            if not isinstance(errors, dict) or not errors:
                continue
            top_reason = max(errors.items(), key=lambda kv: int(kv[1]))[0]
            rows.append(
                {
                    "route_id": route_id,
                    "top_reject_reason": top_reason,
                    "error_counts": {str(k): int(v) for k, v in errors.items()},
                }
            )
    return rows[:limit]


def build_cycle_rca(
    artifact: Dict[str, Any],
    inventory: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Break down cycles_quoteable=0 from a bridge-shadow graph artifact."""
    cycles_found = int(artifact.get("cycles_found") or 0)
    cycles_quoteable = int(artifact.get("cycles_quoteable") or 0)
    cycle_reject = dict(artifact.get("cycle_reject_histogram") or {})
    route_hist = artifact.get("route_error_histogram") or {}
    edge_hist: List[Dict[str, Any]] = list(artifact.get("edge_error_histogram") or [])

    by_adapter: Counter[str] = Counter()
    by_reject: Counter[str] = Counter()
    by_leg_index: Counter[int] = Counter()
    for edge in edge_hist:
        route_id = str(edge.get("route_id") or "")
        family = _adapter_family(route_id, edge)
        errors = edge.get("errors") or {}
        for reason, count in errors.items():
            by_adapter[family] += int(count)
            by_reject[str(reason)] += int(count)
            by_leg_index[0] += int(count)

    route_level: Dict[str, Dict[str, int]] = {}
    for route_id, errors in route_hist.items():
        if not isinstance(errors, dict):
            continue
        family = _adapter_family(str(route_id), {})
        route_level[str(route_id)] = {str(k): int(v) for k, v in errors.items()}
        for reason, count in errors.items():
            by_adapter[family] += int(count)
            by_reject[str(reason)] += int(count)

    by_cycle_length: Dict[str, int] = dict(artifact.get("cycles_by_length") or {})
    by_adapter_family_cycles: Dict[str, int] = dict(
        artifact.get("cycles_by_adapter_family") or {}
    )

    top_cycles = artifact.get("top_cycles") or []
    sample_failures: List[Dict[str, Any]] = []
    for qr in top_cycles[:20]:
        if not isinstance(qr, dict):
            continue
        status = str(qr.get("status") or "")
        if status in ("POSITIVE_GROSS", "NEGATIVE_GROSS"):
            continue
        legs = []
        for idx, leg in enumerate(qr.get("legs") or []):
            if not isinstance(leg, dict):
                continue
            if leg.get("ok"):
                continue
            legs.append(
                {
                    "leg_index": idx,
                    "route_id": leg.get("route_id"),
                    "reject_reason": leg.get("reject_reason"),
                    "dex_id": leg.get("dex_id"),
                }
            )
        sample_failures.append(
            {
                "cycle_id": qr.get("cycle_id"),
                "cycle_length": qr.get("length") or _cycle_length_from_id(
                    str(qr.get("cycle_id") or "")
                ),
                "status": status,
                "reject_reason": qr.get("reject_reason"),
                "failed_legs": legs,
            }
        )

    m8_part = artifact.get("m8_participation") or {}
    bridge_shadow = artifact.get("bridge_shadow") or {}
    cross_mechanic_cycles = (
        artifact.get("cross_mechanic_cycles")
        if artifact.get("cross_mechanic_cycles") is not None
        else m8_part.get("cross_mechanic_cycles")
        if m8_part.get("cross_mechanic_cycles") is not None
        else bridge_shadow.get("cross_mechanic_cycles")
    )

    root_cause_hints: List[str] = []
    if cycles_quoteable == 0 and cycles_found > 0:
        if by_reject.get("QUOTE_REVERT", 0) > by_reject.get("QUOTE_RPC_ERROR", 0):
            root_cause_hints.append("dominant_leg_reject=QUOTE_REVERT (ABI/path/config)")
        if by_adapter.get("curve", 0) > sum(
            by_adapter.get(k, 0) for k in ("balancer", "maverick")
        ):
            root_cause_hints.append("curve_lane_dominates_failures")
        if cycle_reject.get("OVERSIZED_VS_DEPTH", 0) > 0:
            root_cause_hints.append("oversized_vs_depth_excludes_quoteable_denominator")
        if int(cross_mechanic_cycles or 0) == 0:
            root_cause_hints.append("no_cross_mechanic_cycles_in_graph")

    cm_diag: Dict[str, Any] = {}
    if inventory:
        active = inventory.get("active_routes") or []
        cm_pools = {
            str(r.get("pool_address", "")).lower()
            for r in active
            if r.get("cross_mechanic") and r.get("pool_address")
        }
        cm_diag = {
            "cross_mechanic_routes_in_inventory": sum(
                1 for r in active if r.get("cross_mechanic")
            ),
            "cross_mechanic_unique_pools": len(cm_pools),
            "cross_mechanic_cycles_in_shadow": int(cross_mechanic_cycles or 0),
            "hypothesis": (
                "cross_mechanic_pools_present_but_cycles_do_not_traverse_them"
                if cm_pools and int(cross_mechanic_cycles or 0) == 0
                else None
            ),
        }

    cm_found = int(
        artifact.get("cross_mechanic_cycles_found")
        or cross_mechanic_cycles
        or 0
    )
    cm_quoteable = int(artifact.get("cross_mechanic_cycles_quoteable") or 0)
    phantom_diag = artifact.get("phantom_quote_diagnostics") or {}
    phantom_count = int(
        phantom_diag.get("phantom_count")
        or cycle_reject.get("PHANTOM_QUOTE_BPS_OVERFLOW", 0)
        or 0
    )
    balancer_rca = _enrich_balancer_rca(
        _adapter_rca_from_quote_diagnostics(
            artifact, "balancer", primary_reason="QUOTE_REVERT"
        )
        or _top_route_failures(edge_hist, route_hist, "balancer"),
        inventory,
    )
    maverick_rca = _adapter_rca_from_quote_diagnostics(
        artifact, "maverick", primary_reason="QUOTE_RPC_ERROR"
    ) or _top_route_failures(edge_hist, route_hist, "maverick")

    return {
        "schema_version": "m9_quote_lane_rca.2",
        "source_artifact": str(_DEFAULT_SHADOW),
        "summary": {
            "cycles_found": cycles_found,
            "cycles_quoteable": cycles_quoteable,
            "cycles_found_vs_quoteable_gap": max(cycles_found - cycles_quoteable, 0),
            "cross_mechanic_cycles": int(cross_mechanic_cycles or 0),
            "cross_mechanic_cycles_found": cm_found,
            "cross_mechanic_cycles_quoteable": cm_quoteable,
            "phantom_quote_count": phantom_count,
            "qsr": artifact.get("qsr"),
        },
        "cycle_reject_histogram": cycle_reject,
        "by_adapter_family_leg_errors": dict(by_adapter),
        "by_reject_reason": dict(by_reject),
        "by_cycle_length": by_cycle_length,
        "cycles_by_adapter_family": by_adapter_family_cycles,
        "route_error_histogram": route_level,
        "edge_error_histogram_top": edge_hist[:25],
        "sample_cycle_failures": sample_failures,
        "balancer_top_revert_routes": balancer_rca,
        "maverick_top_rpc_error_routes": maverick_rca,
        "phantom_quote_diagnostics": phantom_diag,
        "m8_cycle_trace": _build_m8_cycle_trace(artifact, inventory),
        "micro_size_policy": _build_micro_size_policy(artifact),
        "cross_mechanic_diagnostic": cm_diag,
        "root_cause_hints": root_cause_hints,
        "interpretation": (
            "cycles_found counts attempted cycle quotes; cycles_quoteable counts "
            "cycles with POSITIVE_GROSS or NEGATIVE_GROSS status only."
        ),
    }


def _run_pool_lane(args: argparse.Namespace) -> int:
    from m8.discovery.specialized_index_rpc import resolve_productive_rpc

    rpc = resolve_productive_rpc(args.chain)
    if not rpc:
        print("ERROR: no RPC", file=sys.stderr)
        return 1

    results = []
    if args.dex == "balancer_vault":
        from m8.discovery.balancer_indexer import build_balancer_index, load_balancer_config

        verified, metrics = build_balancer_index(
            chain=args.chain,
            rpc_url=rpc,
            watchlist_tokens=set(),
            connector_tokens=set(),
            use_graphql=True,
            verify_vault=True,
            quote_smoke=True,
        )
        for row in verified[: args.max_pools]:
            results.append(
                {
                    "pool_id": row.get("pool_id"),
                    "probe_status": row.get("probe_status"),
                    "quote_smoke_status": row.get("quote_smoke_status"),
                }
            )
        out_default = load_balancer_config(args.chain).get(
            "quote_debug_artifact", "data/tmp/m9_balancer_quote_debug_latest.json"
        )
    else:
        from m8.discovery.maverick_indexer import build_maverick_index, load_maverick_config

        cfg = load_maverick_config(args.chain)
        verified, metrics = build_maverick_index(
            chain=args.chain,
            rpc_url=rpc,
            watchlist_tokens=set(),
            connector_tokens=set(),
            scan_factory_pagination=True,
            verify_factory=True,
            quote_smoke=True,
        )
        for row in verified[: args.max_pools]:
            results.append(
                {
                    "pool_address": row.get("pool_address"),
                    "probe_status": row.get("probe_status"),
                    "quote_smoke_status": row.get("quote_smoke_status"),
                }
            )
        out_default = cfg.get("quote_debug_artifact", "data/tmp/m9_maverick_quote_debug_latest.json")

    payload = {
        "mode": "pool_lane",
        "dex": args.dex,
        "chain": args.chain,
        "metrics": metrics,
        "sample_pools": results,
    }
    out_path = Path(args.output or out_default)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


def _run_cycle_rca(args: argparse.Namespace) -> int:
    art_path = Path(args.artifact or _DEFAULT_SHADOW)
    if not art_path.exists():
        print(f"ERROR: shadow artifact not found: {art_path}", file=sys.stderr)
        return 1
    artifact = json.loads(art_path.read_text(encoding="utf-8"))
    inv_path = Path(
        getattr(args, "inventory", None)
        or REPO_ROOT / "data/tmp/m9_bridge_inventory_shadow_latest.json"
    )
    inventory = (
        json.loads(inv_path.read_text(encoding="utf-8")) if inv_path.exists() else None
    )
    payload = build_cycle_rca(artifact, inventory=inventory)
    payload["source_artifact"] = str(art_path)
    out_path = Path(args.output or _DEFAULT_OUT)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2))
    print(json.dumps(payload["by_adapter_family_leg_errors"], indent=2))
    print(json.dumps(payload["by_reject_reason"], indent=2))
    if payload["root_cause_hints"]:
        print("root_cause_hints:", payload["root_cause_hints"])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 quote lane diagnostic (pool or cycle RCA)")
    ap.add_argument(
        "--mode",
        choices=["cycle-rca", "pool_lane"],
        default="cycle-rca",
        help="cycle-rca: parse shadow artifact; pool_lane: Balancer/Maverick smoke",
    )
    ap.add_argument("--dex", choices=["balancer_vault", "maverick_v2"], default=None)
    ap.add_argument("--chain", default="base")
    ap.add_argument("--output", default=None)
    ap.add_argument("--artifact", default=None, help="Bridge shadow graph artifact for cycle-rca")
    ap.add_argument("--inventory", default=None, help="Bridge inventory for cross-mechanic RCA")
    ap.add_argument("--max-pools", type=int, default=5)
    args = ap.parse_args()

    if args.mode == "cycle-rca":
        return _run_cycle_rca(args)
    if not args.dex:
        print("ERROR: --dex required for pool_lane mode", file=sys.stderr)
        return 1
    return _run_pool_lane(args)


if __name__ == "__main__":
    sys.exit(main())
