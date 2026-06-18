#!/usr/bin/env python3
"""Apply M8.3 registry decimals to bridge inventory (missing-only legacy fallback)."""
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

_DEFAULT_REGISTRY = "data/runs/_rolling/m8_3_token_metadata_registry_latest.json"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Apply M8.3 registry to bridge routes (legacy missing-only fallback optional)"
    )
    p.add_argument(
        "--inventory",
        default="data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
    )
    p.add_argument("--output", default=None, help="Default: overwrite --inventory")
    p.add_argument("--chain", default="base")
    p.add_argument("--config", default="config/exotic_base_anchor.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--route-ids-file",
        default=None,
        help="JSON file with route_ids list",
    )
    p.add_argument(
        "--from-capacity-diagnostic",
        default=None,
        help="Capacity diagnostic JSON; enrich only enrichment_targets.route_ids",
    )
    p.add_argument(
        "--metadata-registry",
        default=_DEFAULT_REGISTRY,
        help="M8.3 rolling registry JSON (required authority)",
    )
    p.add_argument(
        "--legacy-missing-only-fallback",
        action="store_true",
        help="Fill only missing legs without M8.3 provenance via legacy resolver",
    )
    p.add_argument(
        "--legacy-onchain",
        action="store_true",
        help="Allow on-chain ERC20 in legacy missing-only fallback",
    )
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from m8.metadata.registry import apply_registry_to_routes, load_registry

    inv_path = Path(args.inventory)
    if not inv_path.is_file():
        log.error("Inventory not found: %s", inv_path)
        return 1
    doc = json.loads(inv_path.read_text(encoding="utf-8"))
    routes = list(doc.get("active_routes") or [])
    exploration = list(doc.get("exploration_routes") or [])
    all_routes = routes + exploration

    target_ids: set[str] | None = None
    if args.from_capacity_diagnostic:
        cap_doc = json.loads(Path(args.from_capacity_diagnostic).read_text(encoding="utf-8"))
        targets = cap_doc.get("enrichment_targets") or cap_doc
        target_ids = {str(r) for r in (targets.get("route_ids") or [])}
    elif args.route_ids_file:
        rid_doc = json.loads(Path(args.route_ids_file).read_text(encoding="utf-8"))
        if isinstance(rid_doc, list):
            target_ids = {str(r) for r in rid_doc}
        else:
            targets = rid_doc.get("enrichment_targets") or rid_doc
            target_ids = {str(r) for r in (targets.get("route_ids") or [])}
    if target_ids is not None:
        all_routes = [r for r in all_routes if str(r.get("route_id") or "") in target_ids]
        log.info("Targeted apply: route_ids=%d matched_routes=%d", len(target_ids), len(all_routes))
    if not all_routes:
        log.error("No routes to enrich")
        return 1

    metadata_registry = load_registry(args.metadata_registry)
    if not metadata_registry:
        log.error("M8.3 metadata registry required but missing: %s", args.metadata_registry)
        return 1
    applied = apply_registry_to_routes(all_routes, metadata_registry)
    log.info("M8.3 registry applied: %s", applied)

    before_unknown = sum(
        1
        for r in all_routes
        if r.get("token0_decimals") is None or r.get("token1_decimals") is None
    )
    hist: dict[str, int] = {}
    if args.legacy_missing_only_fallback:
        from m8_1.stable_anchor.config_loader import load_config
        from m9.graph_arb.token_decimals import enrich_routes_decimals, load_decimals_cache

        w3 = None
        if args.legacy_onchain:
            from core.env import load_root_dotenv
            from core.rpc_urls import apply_productive_rpc_env, resolve_productive_http_rpc
            from web3 import Web3

            load_root_dotenv()
            os.environ.update(apply_productive_rpc_env(args.chain))
            rpc = resolve_productive_http_rpc(args.chain)
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
        cfg = load_config(Path(args.config))
        cache = load_decimals_cache()
        hist = enrich_routes_decimals(
            all_routes,
            cfg=cfg,
            cache=cache,
            w3=w3,
            topology_probe=False,
            persist_cache=not args.dry_run,
            missing_only=True,
            preserve_m8_3=True,
        )
        log.info("Legacy missing-only fallback hist: %s", hist)

    after_unknown = sum(
        1
        for r in all_routes
        if r.get("token0_decimals") is None or r.get("token1_decimals") is None
    )
    log.info(
        "M8.3 bridge apply: routes=%d unknown_before=%d unknown_after=%d",
        len(all_routes),
        before_unknown,
        after_unknown,
    )
    if args.dry_run:
        return 0
    out = Path(args.output or args.inventory)
    doc["active_routes"] = routes
    if exploration:
        doc["exploration_routes"] = exploration
    doc["m8_3_registry_path"] = args.metadata_registry
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    log.info("Written %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
