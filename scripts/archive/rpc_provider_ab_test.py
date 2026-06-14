#!/usr/bin/env python3
"""A/B harness: compare RPC providers on identical route + depth probes."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RPC provider A/B for M9 route/depth probes")
    p.add_argument("--chain", default="base")
    p.add_argument(
        "--inventory",
        default="data/runs/_rolling/m9_bridge_inventory_latest.json",
    )
    p.add_argument("--route-limit", type=int, default=50)
    p.add_argument(
        "--providers",
        default="",
        help="Comma-separated provider labels url pairs label::url,...",
    )
    p.add_argument("--output", default="data/tmp/rpc_provider_ab_test_latest.json")
    return p.parse_args()


def _providers_from_env(chain: str = "base") -> List[Tuple[str, str]]:
    from core.rpc_urls import classify_provider, iter_dedicated_http_providers

    providers = iter_dedicated_http_providers(chain)
    if providers:
        return providers
    # Diagnostics-only third parties when explicitly configured
    out: List[Tuple[str, str]] = []
    for key in ("QUICKNODE_BASE_HTTP", "CHAINSTACK_BASE_HTTP"):
        url = (os.environ.get(key) or "").strip()
        if url:
            out.append((classify_provider(url), url))
    return out


def _probe_archive(rpc_url: str, chain_id: int = 8453) -> Tuple[bool, Optional[str]]:
    import urllib.request

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBlockByNumber",
            "params": ["0x1", False],
        }
    ).encode()
    req = urllib.request.Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        if "error" in data:
            return False, str(data["error"])
        return bool(data.get("result")), None
    except Exception as exc:
        return False, str(exc)[:200]


def _route_probes(rpc_url: str, routes: List[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    from m9.graph_arb.quoter import _make_dex_route, _make_token_info
    from m9.graph_arb.raw_http_probe import probe_quote_raw_http
    from m8_1.stable_anchor.quote_probe import size_usd_to_amount_in

    latencies: List[float] = []
    ok = 0
    err_429 = 0
    err_408 = 0
    err_5xx = 0
    err_403 = 0
    for route in routes[:limit]:
        from m9.graph_arb.models import GraphEdge

        edge = GraphEdge(
            token_in_sym=route.get("token0", "USDC"),
            token_out_sym=route.get("token1", "WETH"),
            token_in_addr=route.get("token0_addr", "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"),
            token_out_addr=route.get("token1_addr", "0x4200000000000000000000000000000000000006"),
            token_in_decimals=6,
            token_out_decimals=18,
            route_id=route.get("route_id", "r"),
            dex_id=route.get("dex_id", "uniswap_v3"),
            adapter_type=route.get("adapter_type", "uniswap_v3"),
            fee=int(route.get("fee") or 500),
            tick_spacing=route.get("tick_spacing"),
            quoter_addr=route.get("quoter_addr", "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a"),
            pool_address=route.get("pool_address", "0x" + "0" * 40),
            fee_bps=30.0,
            factory_class=route.get("factory_class", "EFFICIENT_BASELINE"),
            pair_id=route.get("pair_id", "USDC_WETH"),
            factory_verified=True,
        )
        dex_route = _make_dex_route(edge)
        tin = _make_token_info(edge.token_in_sym, edge.token_in_addr, edge.token_in_decimals)
        tout = _make_token_info(edge.token_out_sym, edge.token_out_addr, edge.token_out_decimals)
        try:
            amount_in = size_usd_to_amount_in(tin, 100.0)
        except ValueError:
            amount_in = 10**6
        t0 = time.monotonic()
        result = probe_quote_raw_http(rpc_url, dex_route, tin, tout, amount_in)
        latencies.append(time.monotonic() - t0)
        if result.ok:
            ok += 1
        else:
            err = (result.raw_error or "").lower()
            if "429" in err:
                err_429 += 1
            elif "408" in err:
                err_408 += 1
            elif "403" in err:
                err_403 += 1
            elif "500" in err or "502" in err or "503" in err:
                err_5xx += 1
    denom = max(min(len(routes[:limit]), limit), 1)
    p95_ms: Optional[float] = None
    if latencies:
        if len(latencies) > 1:
            p95_ms = round(sorted(latencies)[min(int(len(latencies) * 0.95), len(latencies) - 1)] * 1000, 1)
        else:
            p95_ms = round(latencies[0] * 1000, 1)
    return {
        "route_qsr": round(ok / denom, 4),
        "p50_ms": round(statistics.median(latencies) * 1000, 1) if latencies else None,
        "p95_ms": p95_ms,
        "http_403": err_403,
        "http_408": err_408,
        "http_429": err_429,
        "http_5xx": err_5xx,
        "probes": denom,
    }


def main() -> int:
    from core.env import load_root_dotenv

    load_root_dotenv()
    args = _parse_args()

    from core.rpc_urls import classify_provider, print_rpc_env_contract

    print_rpc_env_contract(args.chain)

    inv_path = Path(args.inventory)
    if not inv_path.exists():
        print(f"Inventory missing: {inv_path}", file=sys.stderr)
        return 1
    routes = json.loads(inv_path.read_text(encoding="utf-8")).get("active_routes", [])

    providers = _providers_from_env(args.chain)
    if args.providers:
        providers = []
        for part in args.providers.split(","):
            part = part.strip()
            if "::" in part:
                label, url = part.split("::", 1)
                providers.append((label.strip(), url.strip()))

    if not providers:
        print("No provider URLs configured (BASE_RPC / BASE_RPC_PRIMARY / ...)", file=sys.stderr)
        return 1

    report: Dict[str, Any] = {
        "schema_family": "rpc_provider_ab_test.1",
        "chain": args.chain,
        "route_limit": args.route_limit,
        "providers": {},
    }

    for label, url in providers:
        from core.rpc_urls import is_public_rpc_url

        prov_class = classify_provider(url)
        archive_ok, archive_err = _probe_archive(url)
        entry: Dict[str, Any] = {
            "provider_class": prov_class,
            "label": label,
            "url_prefix": url[:48] + "...",
            "is_public": is_public_rpc_url(url),
            "archive_ok": archive_ok,
            "archive_error": archive_err,
        }
        entry.update(_route_probes(url, routes, args.route_limit))
        report["providers"][label] = entry
        print(
            f"{prov_class}/{label}: route_qsr={entry['route_qsr']} p95_ms={entry.get('p95_ms')} "
            f"403={entry['http_403']} 408={entry['http_408']} 429={entry['http_429']} "
            f"archive_ok={archive_ok}",
            flush=True,
        )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
