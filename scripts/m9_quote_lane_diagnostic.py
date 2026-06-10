#!/usr/bin/env python3
"""Quote-lane diagnostic: pool smoke (Balancer/Maverick) or cycle RCA from shadow artifact."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

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


def build_cycle_rca(artifact: Dict[str, Any]) -> Dict[str, Any]:
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

    return {
        "schema_version": "m9_quote_lane_rca.1",
        "source_artifact": str(_DEFAULT_SHADOW),
        "summary": {
            "cycles_found": cycles_found,
            "cycles_quoteable": cycles_quoteable,
            "cycles_found_vs_quoteable_gap": max(cycles_found - cycles_quoteable, 0),
            "cross_mechanic_cycles": int(cross_mechanic_cycles or 0),
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
    payload = build_cycle_rca(artifact)
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
