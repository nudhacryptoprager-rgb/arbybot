#!/usr/bin/env python3
"""Isolated quote-lane diagnostic for Balancer/Maverick (no M9 cycle scan)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 distinct-pricing quote lane diagnostic")
    ap.add_argument("--dex", required=True, choices=["balancer_vault", "maverick_v2"])
    ap.add_argument("--chain", default="base")
    ap.add_argument("--output", default=None)
    ap.add_argument("--max-pools", type=int, default=5)
    args = ap.parse_args()

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


if __name__ == "__main__":
    sys.exit(main())
