#!/usr/bin/env python3
"""Token-level trace: M8 sniper event → registry → expansion → bridge → M9 cycles."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from monitoring.sniper_artifacts import assess_sniper_artifact_for_m9

_ANCHOR_TOKENS = frozenset(
    {"USDC", "USDT", "DAI", "EURC", "WETH", "WETH_BASE", "cbBTC", "USDbC", "USDBC"}
)


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _exotic_token_addrs(event: Dict[str, Any]) -> List[str]:
    addrs: List[str] = []
    for side in ("0", "1"):
        sym = str(event.get(f"token{side}_symbol") or "").upper()
        addr = (event.get(f"token{side}") or event.get(f"token{side}_address") or "").lower()
        if addr and sym not in _ANCHOR_TOKENS:
            addrs.append(addr)
    return addrs


def _route_touches_token(route: Dict[str, Any], token_addr: str) -> bool:
    addr = token_addr.lower()
    for key in ("token0_address", "token1_address", "token0", "token1"):
        val = route.get(key)
        if val and str(val).lower() == addr:
            return True
    return False


def _cycle_pool_addrs(cycle_entry: Dict[str, Any]) -> Set[str]:
    pools: Set[str] = set()
    for leg in cycle_entry.get("legs") or cycle_entry.get("leg_results") or []:
        p = leg.get("pool_address") or leg.get("pool")
        if p:
            pools.add(str(p).lower())
    edges = cycle_entry.get("edges") or []
    for edge in edges:
        p = edge.get("pool_address") or edge.get("pool")
        if p:
            pools.add(str(p).lower())
    return pools


_REJECT_CATEGORY = {
    "EXOTIC_TOKEN_ADDRESS_MISSING": "metadata",
    "NO_BRIDGE_ROUTE_FOR_TOKEN": "provenance",
    "NO_EXPANSION_ROUTE_FOR_TOKEN": "provenance",
    "REGISTRY_NOT_PROMOTED": "provenance",
    "NO_M9_CYCLE_FOR_POOL": "no_cycle",
    "QUOTE_FAILED": "quote_fail",
    "CYCLE_QUOTE_FAILED": "quote_fail",
    "QUARANTINE_BLOCKED": "quarantine",
}


def _reject_category(reason: Optional[str]) -> str:
    if not reason:
        return "reached"
    return _REJECT_CATEGORY.get(reason, "other")


def _classify_event_reject(
    *,
    exotic_addrs: List[str],
    expansion_hits: List[Dict[str, Any]],
    bridge_hits: List[Dict[str, Any]],
    registry_rows: List[Dict[str, Any]],
    cycle_ids: List[str],
) -> str:
    if not exotic_addrs:
        return "EXOTIC_TOKEN_ADDRESS_MISSING"
    if not expansion_hits and not bridge_hits:
        return "NO_BRIDGE_ROUTE_FOR_TOKEN"
    if not expansion_hits:
        return "NO_EXPANSION_ROUTE_FOR_TOKEN"
    if registry_rows and not any(r.get("promoted") for r in registry_rows):
        if not bridge_hits:
            return "REGISTRY_NOT_PROMOTED"
    if not bridge_hits:
        return "NO_BRIDGE_ROUTE_FOR_TOKEN"
    if not cycle_ids:
        return "NO_M9_CYCLE_FOR_POOL"
    return "REACHED_M9_CYCLE"


def build_token_trace_report(
    *,
    sniper: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]],
    bridge: Optional[Dict[str, Any]],
    shadow: Optional[Dict[str, Any]],
    registry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Trace each sniper event through downstream layers."""
    sniper_assessment = assess_sniper_artifact_for_m9(sniper)
    events = list((sniper or {}).get("recent_events") or [])
    expansion_routes = list(
        (expansion or {}).get("routes_admitted")
        or (expansion or {}).get("active_routes")
        or []
    )
    bridge_routes = list((bridge or {}).get("active_routes") or [])
    bsm = (bridge or {}).get("bridge_source_metrics") or {}
    registry_tokens = (registry or {}).get("tokens") or {}

    cycles_by_pool: Dict[str, List[str]] = defaultdict(list)
    for opp in (shadow or {}).get("top_opportunities") or []:
        cid = str(opp.get("cycle_id") or "")
        for pool in _cycle_pool_addrs(opp):
            if cid:
                cycles_by_pool[pool].append(cid)
    # Also index pools mentioned on quoted cycle rows when present.
    for row in (shadow or {}).get("quoted_cycle_samples") or []:
        cid = str(row.get("cycle_id") or "")
        for pool in _cycle_pool_addrs(row):
            if cid:
                cycles_by_pool[pool].append(cid)

    reject_hist: Counter[str] = Counter()
    category_hist: Counter[str] = Counter()
    traces: List[Dict[str, Any]] = []
    for event in events:
        event_id = event.get("event_id")
        pool = (event.get("pool") or "").lower()
        exotic_addrs = _exotic_token_addrs(event)
        expansion_hits = [
            {
                "pool_address": r.get("pool_address"),
                "dex_id": r.get("dex_id"),
                "source": r.get("source"),
            }
            for r in expansion_routes
            if any(_route_touches_token(r, a) for a in exotic_addrs)
            or (pool and str(r.get("pool_address") or "").lower() == pool)
        ]
        bridge_hits = [
            {
                "pool_address": r.get("pool_address"),
                "dex_id": r.get("dex_id"),
                "source": r.get("source"),
                "origin_source": r.get("origin_source"),
            }
            for r in bridge_routes
            if any(_route_touches_token(r, a) for a in exotic_addrs)
            or (pool and str(r.get("pool_address") or "").lower() == pool)
        ]
        registry_rows = []
        for addr in exotic_addrs:
            row = registry_tokens.get(addr)
            if row:
                registry_rows.append(
                    {
                        "token_address": addr,
                        "venue_count": len(row.get("venues") or []),
                        "promoted": bool(row.get("promoted")),
                        "last_seen_ts": row.get("last_seen_ts"),
                    }
                )
        cycle_ids = sorted(set(cycles_by_pool.get(pool, [])))
        reject_reason = _classify_event_reject(
            exotic_addrs=exotic_addrs,
            expansion_hits=expansion_hits,
            bridge_hits=bridge_hits,
            registry_rows=registry_rows,
            cycle_ids=cycle_ids,
        )
        if reject_reason == "REACHED_M9_CYCLE":
            reject_reason = None
        reject_hist[reject_reason or "REACHED_M9_CYCLE"] += 1
        category_hist[_reject_category(reject_reason)] += 1
        traces.append(
            {
                "event_id": event_id,
                "pool": pool,
                "dex": event.get("dex"),
                "token0_symbol": event.get("token0_symbol"),
                "token1_symbol": event.get("token1_symbol"),
                "exotic_token_addrs": exotic_addrs,
                "registry": registry_rows,
                "expansion_routes": expansion_hits[:12],
                "bridge_routes": bridge_hits[:12],
                "cycle_ids": cycle_ids[:20],
                "reject_reason": reject_reason,
                "reject_category": _reject_category(reject_reason),
                "reached_m9_cycle": bool(cycle_ids),
            }
        )

    reached = sum(1 for t in traces if t.get("reached_m9_cycle"))
    bsm_shadow = (shadow or {}).get("bridge_source_metrics") or {}
    return {
        "schema_version": "m8_to_m9_token_trace.2",
        "sniper_assessment": sniper_assessment,
        "reject_reason_histogram": dict(reject_hist),
        "reject_category_histogram": dict(category_hist),
        "summary": {
            "events_traced": len(traces),
            "reached_m9_cycle": reached,
            "bridge_m8_direct_routes": bsm.get("m8_direct_routes_in_bridge"),
            "m8_direct_cycles_found": bsm_shadow.get("m8_direct_cycles_found")
            or bsm_shadow.get("cycles_with_direct_sniper_pool")
            or bsm.get("m8_direct_cycles_found"),
            "m8_direct_cycles_quoteable": bsm_shadow.get("m8_direct_cycles_quoteable"),
            "cycles_with_m8_pool": bsm_shadow.get("cycles_with_m8_pool")
            or bsm.get("cycles_with_m8_pool"),
            "cycles_with_m8_derived_pool": bsm_shadow.get("cycles_with_m8_derived_pool"),
            "graph_ready_from_m8": bsm.get("graph_ready_from_m8"),
            "m8_stale": bsm.get("m8_stale"),
            "shadow_duration_fulfilled": (shadow or {}).get("duration_fulfilled"),
        },
        "token_traces": traces,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="M8→M9 per-token trace report")
    ap.add_argument(
        "--sniper",
        default=str(REPO_ROOT / "data/runs/_rolling/new_pool_sniper_latest.json"),
    )
    ap.add_argument(
        "--expansion",
        default=str(REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json"),
    )
    ap.add_argument(
        "--bridge",
        default=str(REPO_ROOT / "data/tmp/m9_bridge_inventory_graph_handoff_latest.json"),
    )
    ap.add_argument(
        "--shadow",
        default=str(REPO_ROOT / "data/tmp/m9_graph_handoff_quote_validation_10m.json"),
    )
    ap.add_argument(
        "--registry",
        default=str(REPO_ROOT / "data/runs/_rolling/m8_pending_pairs.json"),
    )
    ap.add_argument(
        "--output",
        default=str(REPO_ROOT / "data/tmp/m8_to_m9_token_trace_latest.json"),
    )
    args = ap.parse_args()

    report = build_token_trace_report(
        sniper=_load(Path(args.sniper)),
        expansion=_load(Path(args.expansion)),
        bridge=_load(Path(args.bridge)),
        shadow=_load(Path(args.shadow)),
        registry=_load(Path(args.registry)),
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print("written:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
