#!/usr/bin/env python3
"""Enrich bridge route token decimals via on-chain ERC20 calls + cache."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

log = logging.getLogger("m9_enrich_bridge_decimals")


def main() -> int:
    p = argparse.ArgumentParser(description="Enrich bridge routes with on-chain decimals")
    p.add_argument(
        "--inventory",
        default="data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
    )
    p.add_argument("--output", default=None, help="Default: overwrite --inventory")
    p.add_argument("--chain", default="base")
    p.add_argument("--config", default="config/exotic_base_anchor.yaml")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from core.env import load_root_dotenv
    from core.rpc_urls import apply_productive_rpc_env, resolve_productive_http_rpc
    from m8_1.stable_anchor.config_loader import load_config
    from m9.graph_arb.token_decimals import enrich_routes_decimals, load_decimals_cache
    from web3 import Web3

    load_root_dotenv()
    os.environ.update(apply_productive_rpc_env(args.chain))
    rpc = resolve_productive_http_rpc(args.chain)
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))

    inv_path = Path(args.inventory)
    if not inv_path.is_file():
        log.error("Inventory not found: %s", inv_path)
        return 1
    doc = json.loads(inv_path.read_text(encoding="utf-8"))
    routes = list(doc.get("active_routes") or [])
    exploration = list(doc.get("exploration_routes") or [])
    all_routes = routes + exploration
    if not all_routes:
        log.error("No routes to enrich")
        return 1

    cfg = load_config(Path(args.config))
    cache = load_decimals_cache()
    before_unknown = sum(
        1
        for r in all_routes
        if r.get("token0_decimals") is None or r.get("token1_decimals") is None
    )
    hist = enrich_routes_decimals(
        all_routes,
        cfg=cfg,
        cache=cache,
        w3=w3,
        topology_probe=False,
        persist_cache=not args.dry_run,
    )
    after_unknown = sum(
        1
        for r in all_routes
        if r.get("token0_decimals") is None or r.get("token1_decimals") is None
    )
    log.info(
        "Decimals enriched: routes=%d unknown_before=%d unknown_after=%d hist=%s",
        len(all_routes),
        before_unknown,
        after_unknown,
        hist,
    )
    if args.dry_run:
        return 0
    out = Path(args.output or args.inventory)
    doc["active_routes"] = routes
    if exploration:
        doc["exploration_routes"] = exploration
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    log.info("Written %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
