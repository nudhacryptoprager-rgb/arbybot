#!/usr/bin/env python3
"""CLI: Build M8→M9 bridge inventory.

Reads:
  - data/runs/_rolling/new_pool_sniper_latest.json   (M8 sniper events)
  - data/runs/_rolling/m8_1_stable_anchor_latest.json (M8.1 anchor routes)
  - data/tmp/m9_depth_enriched_inventory.json         (base depth inventory)

Writes:
  - data/runs/_rolling/m9_bridge_inventory_latest.json

Usage:
  py -3.11 scripts/m9_bridge_build.py
  py -3.11 scripts/m9_bridge_build.py --sniper PATH --anchor PATH --base-inv PATH --output PATH
"""
from __future__ import annotations

import argparse
import json
import sys


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build M8→M9 bridge inventory")
    p.add_argument(
        "--sniper",
        default="data/runs/_rolling/new_pool_sniper_latest.json",
        help="Path to M8 new_pool_sniper artifact",
    )
    p.add_argument(
        "--anchor",
        default="data/runs/_rolling/m8_1_stable_anchor_latest.json",
        help="Path to M8.1 stable_anchor artifact",
    )
    p.add_argument(
        "--base-inv",
        default="data/tmp/m9_depth_enriched_inventory.json",
        help="Path to base depth-enriched inventory",
    )
    p.add_argument(
        "--output",
        default="data/runs/_rolling/m9_bridge_inventory_latest.json",
        help="Output path for bridge inventory",
    )
    p.add_argument("--verbose", action="store_true", help="Extra logging")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    import logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("m9_bridge_build")

    from m9.graph_arb.bridge_builder import build_bridge_inventory

    log.info("Building M8→M9 bridge inventory...")
    log.info("  sniper  : %s", args.sniper)
    log.info("  anchor  : %s", args.anchor)
    log.info("  base_inv: %s", args.base_inv)
    log.info("  output  : %s", args.output)

    metrics = build_bridge_inventory(
        sniper_path=args.sniper,
        anchor_path=args.anchor,
        base_inv_path=args.base_inv,
        output_path=args.output,
    )

    log.info("Bridge funnel:")
    log.info("  m8_new_pools_input       : %d", metrics["m8_new_pools_input"])
    log.info("  token_verified_count     : %d", metrics["token_verified_count"])
    log.info("  anchor_connected_count   : %d", metrics["anchor_connected_count"])
    log.info("  cross_dex_seen_count     : %d", metrics["cross_dex_seen_count"])
    log.info("  factory_verified_count   : %d", metrics["factory_verified_count"])
    log.info("  depth_ok_count           : %d", metrics["depth_ok_count"])
    log.info("  graph_ready_from_m8      : %d", metrics["graph_ready_from_m8"])
    log.info("  graph_ready_total        : %d", metrics["graph_ready_total"])
    log.info("  m8_stale                 : %s", metrics["m8_stale"])
    log.info("  m8_1_stale               : %s", metrics["m8_1_stale"])
    log.info("Written: %s", args.output)

    # Acceptance check
    if metrics["graph_ready_total"] == 0:
        log.error("FAIL: graph_ready_total=0 — bridge inventory is empty")
        return 1

    # Warn if staleness is high (non-fatal: still proceed)
    if metrics["m8_stale"]:
        log.warning("WARN: m8 artifact is stale (>4h old) — run M8 sniper to refresh")
    if metrics["m8_1_stale"]:
        log.warning("WARN: m8_1 artifact is stale (>4h old) — run M8.1 stable-anchor to refresh")

    log.info("Bridge build: OK (graph_ready_total=%d)", metrics["graph_ready_total"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
