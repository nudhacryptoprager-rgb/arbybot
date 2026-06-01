#!/usr/bin/env python3
"""Quote a bounded set of inventory routes without cycle fanout (M9 QSR RCA).

Probes one forward leg per selected route via raw HTTP eth_call — same path as
``--quote-backend raw_http`` in the M9 runner. Use this to separate RPC/provider
issues from adapter bugs before another full soak.

Usage:
  py -3.11 scripts/m9_quote_route_diagnostic.py --limit 40
  py -3.11 scripts/m9_quote_route_diagnostic.py --pair-contains AERO --pair-contains cbBTC
  py -3.11 scripts/m9_quote_route_diagnostic.py --source m8_sniper --limit 20
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

log = logging.getLogger("m9_quote_route_diagnostic")

_DEFAULT_INVENTORY = "data/runs/_rolling/m9_bridge_inventory_latest.json"
_DEFAULT_CONFIG = "config/exotic_base_anchor.yaml"
_DEFAULT_OUTPUT = "data/runs/_rolling/m9_quote_route_diagnostic_latest.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M9 per-route quote diagnostic (no cycle fanout)")
    p.add_argument("--chain", default="base")
    p.add_argument("--inventory", default=_DEFAULT_INVENTORY)
    p.add_argument("--config", default=_DEFAULT_CONFIG)
    p.add_argument("--output", default=_DEFAULT_OUTPUT)
    p.add_argument("--limit", type=int, default=40, help="Max routes to probe")
    p.add_argument(
        "--pair-contains",
        action="append",
        default=[],
        help="Only routes whose pair_id contains this substring (repeatable)",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Filter active_routes by source field (e.g. m8_sniper)",
    )
    p.add_argument("--size-usd", type=float, default=100.0, help="Probe notional in USD")
    p.add_argument("--require-factory-verified", action="store_true")
    return p.parse_args()


def resolve_diagnostic_rpc(
    chain: str,
    env: Optional[Dict[str, str]] = None,
) -> tuple[str, str, Dict[str, Any]]:
    """Resolve HTTP RPC the same way as ``m9.graph_arb.runner`` (env-aware).

    Must pass ``chain_id`` + ``network`` — calling ``resolve_rpc_http("base")`` as a
    positional arg wrongly binds the string to ``chain_id`` and ignores ``BASE_RPC``.
    """
    from core.rpc_urls import _CHAIN_KEY_TO_ID, resolve_rpc_http

    env_map = dict(env if env is not None else os.environ)
    chain_key = chain.lower()
    chain_id = _CHAIN_KEY_TO_ID.get(chain_key)
    url, provider, diag = resolve_rpc_http(
        chain_id=chain_id,
        network=chain_key,
        env=env_map,
    )
    if not url:
        raise RuntimeError(
            f"No RPC URL for chain={chain!r} (chain_id={chain_id}). "
            f"Set BASE_RPC or ALCHEMY_API_KEY. diagnostics={diag}"
        )
    return url, provider, diag


def _select_edges(
    inventory_path: str,
    config_path: str,
    *,
    pair_contains: List[str],
    source: Optional[str],
    limit: int,
    require_factory_verified: bool,
) -> List[Any]:
    from m9.graph_arb.builder import build_graph_from_inventory
    from m9.graph_arb.models import GraphEdge

    allowed_pools: Optional[set] = None
    if source:
        with open(inventory_path, encoding="utf-8") as fh:
            inv = json.load(fh)
        allowed_pools = {
            r.get("pool_address", "").lower()
            for r in inv.get("active_routes", [])
            if r.get("source") == source and r.get("pool_address")
        }

    adjacency = build_graph_from_inventory(
        inventory_path=inventory_path,
        config_path=config_path,
        require_factory_verified=require_factory_verified,
        lane="discovery",
    )
    seen_route: set = set()
    edges: List[GraphEdge] = []
    for token_edges in adjacency.values():
        for edge_list in token_edges.values():
            for edge in edge_list:
                if edge.route_id in seen_route:
                    continue
                if allowed_pools is not None and edge.pool_address.lower() not in allowed_pools:
                    continue
                if pair_contains and not any(
                    sub.upper() in edge.pair_id.upper() for sub in pair_contains
                ):
                    continue
                seen_route.add(edge.route_id)
                edges.append(edge)
                if len(edges) >= limit:
                    return edges
    return edges


def run_diagnostic(args: argparse.Namespace) -> Dict[str, Any]:
    from m8_1.stable_anchor.quote_probe import size_usd_to_amount_in
    from m9.graph_arb.quoter import _make_dex_route, _make_token_info
    from m9.graph_arb.raw_http_probe import probe_quote_raw_http

    rpc_url, rpc_provider, rpc_diag = resolve_diagnostic_rpc(args.chain)
    edges = _select_edges(
        args.inventory,
        args.config,
        pair_contains=args.pair_contains or [],
        source=args.source,
        limit=args.limit,
        require_factory_verified=args.require_factory_verified,
    )
    log.info("Probing %d routes via %s", len(edges), rpc_url[:48])

    rows: List[Dict[str, Any]] = []
    ok_count = 0
    for edge in edges:
        route = _make_dex_route(edge)
        token_in = _make_token_info(edge.token_in_sym, edge.token_in_addr, edge.token_in_decimals)
        token_out = _make_token_info(edge.token_out_sym, edge.token_out_addr, edge.token_out_decimals)
        try:
            amount_in = size_usd_to_amount_in(token_in, args.size_usd)
        except ValueError:
            amount_in = 10 ** min(token_in.decimals, 6)
        result = probe_quote_raw_http(rpc_url, route, token_in, token_out, amount_in)
        if result.ok:
            ok_count += 1
        rows.append(
            {
                "route_id": edge.route_id,
                "pair_id": edge.pair_id,
                "dex_id": edge.dex_id,
                "adapter_type": edge.adapter_type,
                "pool_address": edge.pool_address,
                "token_in": edge.token_in_sym,
                "token_out": edge.token_out_sym,
                "ok": result.ok,
                "reject_reason": result.reject_reason,
                "raw_error": (result.raw_error or "")[:200] or None,
                "amount_out": result.amount_out if result.ok else 0,
            }
        )

    qsr = ok_count / len(rows) if rows else 0.0
    by_reject: Dict[str, int] = {}
    for row in rows:
        if not row["ok"] and row["reject_reason"]:
            by_reject[row["reject_reason"]] = by_reject.get(row["reject_reason"], 0) + 1

    report = {
        "schema_family": "m9_quote_route_diagnostic",
        "chain": args.chain,
        "inventory_path": args.inventory,
        "config_path": args.config,
        "rpc_url": rpc_url,
        "rpc_url_prefix": rpc_url[:48],
        "rpc_provider": rpc_provider,
        "rpc_source": rpc_diag.get("source"),
        "routes_probed": len(rows),
        "routes_ok": ok_count,
        "route_qsr": round(qsr, 4),
        "by_reject_reason": by_reject,
        "rows": rows,
    }
    return report


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _parse_args()
    try:
        report = run_diagnostic(args)
    except Exception as exc:  # noqa: BLE001
        log.error("Diagnostic failed: %s", exc)
        return 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    log.info(
        "Wrote %s — route_qsr=%.4f (%d/%d ok)",
        out,
        report["route_qsr"],
        report["routes_ok"],
        report["routes_probed"],
    )
    for row in report["rows"][:12]:
        if not row["ok"]:
            log.info(
                "FAIL %s %s %s: %s",
                row["pair_id"],
                row["adapter_type"],
                row["reject_reason"],
                row["raw_error"],
            )
    return 0 if report["routes_probed"] > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
