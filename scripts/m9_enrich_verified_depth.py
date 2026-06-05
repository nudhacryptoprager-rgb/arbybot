#!/usr/bin/env python3
"""Merge bridge depth into verified inventory, then probe any remaining gaps."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

log = logging.getLogger("m9_enrich_verified_depth")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enrich verified inventory with depth from bridge + RPC")
    p.add_argument(
        "--verified",
        default="data/tmp/m9_verified_inventory.json",
    )
    p.add_argument(
        "--bridge",
        default="data/runs/_rolling/m9_bridge_inventory_latest.json",
    )
    p.add_argument("--chain", default="base")
    p.add_argument("--probe-size-usd", type=float, default=100.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from core.env import load_root_dotenv
    from core.rpc_urls import apply_productive_rpc_env

    load_root_dotenv()
    try:
        env = apply_productive_rpc_env(args.chain)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    os.environ.update(env)

    from m9.graph_arb.inventory_depth import merge_verified_inventory_from_bridge

    stats = merge_verified_inventory_from_bridge(
        args.verified, args.bridge, write=not args.dry_run
    )
    log.info("Bridge merge: %s", stats)

    vpath = Path(args.verified)
    verified = json.loads(vpath.read_text(encoding="utf-8"))
    routes = verified.get("active_routes", [])
    missing = [r for r in routes if r.get("effective_depth_usd") is None]
    log.info(
        "Verified active=%d with_depth=%d still_missing=%d",
        len(routes),
        stats.get("with_depth_after", 0),
        len(missing),
    )

    if not missing or args.dry_run:
        return 0

    rpc_url = env.get("BASE_RPC_PRIMARY") or env.get("BASE_RPC", "")
    from m9.graph_arb.pool_depth_probe import enrich_routes_missing_depth

    dex_quoters: dict = {}
    try:
        import yaml

        with open(_REPO / "config" / "dexes.yaml", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        for dex_id, dex_cfg in (raw.get(args.chain, {}) or {}).items():
            if isinstance(dex_cfg, dict):
                q = dex_cfg.get("quoter_v2") or dex_cfg.get("quoter")
                if q:
                    dex_quoters[dex_id] = q
    except Exception as exc:  # noqa: BLE001
        log.warning("dexes.yaml load failed: %s", exc)

    counts = enrich_routes_missing_depth(
        missing,
        rpc_url=rpc_url,
        dex_quoters=dex_quoters,
        probe_size_usd=args.probe_size_usd,
    )
    log.info("Direct probe on verified gaps: %s", counts)

    with_depth = sum(1 for r in routes if r.get("effective_depth_usd") is not None)
    stats["with_depth_final"] = with_depth
    if not args.dry_run:
        tmp = str(vpath) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(verified, fh, indent=2)
        os.replace(tmp, str(vpath))
    print(
        f"VERIFIED_DEPTH: active={len(routes)} with_depth={with_depth} "
        f"merged_from_bridge={stats.get('merged', 0)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
