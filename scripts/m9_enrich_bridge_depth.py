#!/usr/bin/env python3
"""CLI: Enrich M8 long-tail routes in the bridge inventory with effective_depth_usd.

Package #8 groundwork for depth-aware sizing. The M8→M9 bridge adds sniped
long-tail routes with ``effective_depth_usd=None`` (they are not in the base
depth-enriched inventory). This script probes only those missing routes with a
price-agnostic anchor-side marginal depth probe and writes the inventory back.

Already-enriched base routes (effective_depth_usd already set) are left untouched.

Reads / writes (in place by default):
  - data/runs/_rolling/m9_bridge_inventory_latest.json

Usage:
  py -3.11 scripts/m9_enrich_bridge_depth.py
  py -3.11 scripts/m9_enrich_bridge_depth.py --inventory PATH --output PATH
  py -3.11 scripts/m9_enrich_bridge_depth.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

log = logging.getLogger("m9_enrich_bridge_depth")


def _load_dex_quoters(dexes_path: str, chain: str) -> Dict[str, str]:
    """Build a dex_id -> quoter address map from config/dexes.yaml for one chain."""
    quoters: Dict[str, str] = {}
    try:
        import yaml
        with open(dexes_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load %s: %s", dexes_path, exc)
        return quoters
    chain_block = raw.get(chain, {}) or {}
    for dex_id, dex_cfg in chain_block.items():
        if not isinstance(dex_cfg, dict):
            continue
        q = dex_cfg.get("quoter_v2") or dex_cfg.get("quoter")
        if q:
            quoters[dex_id] = q
    return quoters


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enrich M8 bridge routes with effective_depth_usd")
    p.add_argument("--chain", default="base", help="Chain identifier (default: base)")
    p.add_argument(
        "--inventory",
        default="data/runs/_rolling/m9_bridge_inventory_latest.json",
        help="Bridge inventory JSON to enrich",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output path (default: overwrite --inventory)",
    )
    p.add_argument(
        "--dexes",
        default="config/dexes.yaml",
        help="DEX config YAML for quoter addresses",
    )
    p.add_argument("--probe-size-usd", type=float, default=100.0)
    p.add_argument("--ref-size-usd", type=float, default=2.0)
    p.add_argument("--dry-run", action="store_true", help="Probe but do not write")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Resolve RPC URL (same policy as pool_depth_probe)
    rpc_url: Optional[str] = os.environ.get("BASE_RPC", "https://mainnet.base.org")
    try:
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
        chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, _, _ = resolve_rpc_http(
            chain_id=chain_id, network=args.chain, env=dict(os.environ)
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not resolve RPC via core.rpc_urls: %s — using BASE_RPC env", exc)
    if not rpc_url:
        log.error("No RPC URL available. Set BASE_RPC env var.")
        return 1

    inv_path = Path(args.inventory)
    if not inv_path.exists():
        log.error("Inventory not found: %s", inv_path)
        return 1
    with inv_path.open("r", encoding="utf-8") as fh:
        inventory = json.load(fh)

    routes = inventory.get("active_routes", [])
    dex_quoters = _load_dex_quoters(args.dexes, args.chain)
    log.info(
        "Enriching %d active routes (quoters loaded: %d) at $%.0f...",
        len(routes), len(dex_quoters), args.probe_size_usd,
    )

    from m9.graph_arb.pool_depth_probe import enrich_routes_missing_depth

    counts = enrich_routes_missing_depth(
        routes,
        rpc_url=rpc_url,
        dex_quoters=dex_quoters,
        probe_size_usd=args.probe_size_usd,
        ref_size_usd=args.ref_size_usd,
    )

    log.info(
        "Depth enrichment: candidates=%d probed_ok=%d failed=%d no_anchor=%d "
        "skipped_v4=%d toxic=%d low_depth=%d",
        counts["candidates"], counts["probed_ok"], counts["probe_failed"],
        counts["no_anchor"], counts["skipped_v4"], counts["toxic"], counts["low_depth"],
    )

    if args.dry_run:
        log.info("Dry-run: not writing inventory")
        return 0

    out_path = Path(args.output or args.inventory)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(inventory, fh, indent=2, ensure_ascii=False)
    log.info("Enriched bridge inventory written to %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
