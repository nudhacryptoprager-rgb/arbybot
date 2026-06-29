#!/usr/bin/env python3
"""CLI: Enrich M8 long-tail routes in the bridge inventory with effective_depth_usd.

Package #8 groundwork for depth-aware sizing. The M8→M9 bridge adds sniped
long-tail routes with ``effective_depth_usd=None`` (they are not in the base
depth-enriched inventory). This script probes only those missing routes with a
price-agnostic anchor-side marginal depth probe and writes the inventory back.

Already-enriched base routes (effective_depth_usd already set) are left untouched
unless ``--force-reprobe`` is used to refresh legacy single-rung depth rows.

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
    p.add_argument(
        "--sleep-ms",
        type=int,
        default=120,
        help="Pause between per-route depth probes (429 backoff)",
    )
    p.add_argument("--dry-run", action="store_true", help="Probe but do not write")
    p.add_argument(
        "--force-reprobe",
        action="store_true",
        help=(
            "Re-probe legacy depth rows that have effective_depth_usd but no "
            "depth_probe_status (this refreshes the old single-rung $100 cap)."
        ),
    )
    p.add_argument(
        "--allow-public-rpc",
        action="store_true",
        help=(
            "Permit falling back to the rate-limited public mainnet.base.org endpoint. "
            "By default the script hard-fails when no dedicated BASE_RPC is configured, "
            "to avoid silent 429-throttled depth probes."
        ),
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--route-ids-file",
        default=None,
        help="JSON file with route_ids list for targeted depth enrichment",
    )
    p.add_argument(
        "--from-capacity-diagnostic",
        default=None,
        help="Capacity diagnostic JSON; probe only enrichment_targets.route_ids",
    )
    p.add_argument(
        "--prioritize-false-positive-reprobe",
        action="store_true",
        help=(
            "Re-probe only false_positive_depth_cap_band / depth_reprobe_required "
            "routes via full marginal ladder (implies --force-reprobe)."
        ),
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from core.env import load_root_dotenv

    load_root_dotenv()
    rpc_url: Optional[str] = None
    try:
        from core.rpc_urls import apply_productive_rpc_env, is_public_rpc_url, resolve_productive_http_rpc

        os.environ.update(apply_productive_rpc_env(args.chain))
        rpc_url = resolve_productive_http_rpc(args.chain)
        _resolved_is_public = is_public_rpc_url(rpc_url)
    except RuntimeError:
        from core.rpc_urls import is_public_rpc_url, resolve_rpc_http, _CHAIN_KEY_TO_ID

        chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, _, _ = resolve_rpc_http(
            chain_id=chain_id, network=args.chain, env=dict(os.environ)
        )
        _resolved_is_public = is_public_rpc_url(rpc_url)
    if not rpc_url:
        log.error("No RPC URL available. Set BASE_RPC_PRIMARY or ALCHEMY_API_KEY.")
        return 1

    if _resolved_is_public and not args.allow_public_rpc:
        log.error(
            "Refusing to enrich depth via public RPC (rate-limited). "
            "Set BASE_RPC_PRIMARY / ALCHEMY_API_KEY, or pass --allow-public-rpc.",
        )
        return 1
    if _resolved_is_public:
        log.warning(
            "Using public RPC for depth enrichment (--allow-public-rpc); expect throttling.",
        )

    inv_path = Path(args.inventory)
    if not inv_path.exists():
        log.error("Inventory not found: %s", inv_path)
        return 1
    with inv_path.open("r", encoding="utf-8") as fh:
        inventory = json.load(fh)

    routes = inventory.get("active_routes", [])
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
        routes = [r for r in routes if str(r.get("route_id") or "") in target_ids]
        log.info(
            "Targeted depth enrichment: route_ids=%d matched_routes=%d",
            len(target_ids),
            len(routes),
        )
    dex_quoters = _load_dex_quoters(args.dexes, args.chain)
    force_reprobe = bool(args.force_reprobe or args.prioritize_false_positive_reprobe)
    log.info(
        "Enriching %d active routes (quoters loaded: %d) at $%.0f, force_reprobe=%s "
        "prioritize_false_positive_reprobe=%s...",
        len(routes),
        len(dex_quoters),
        args.probe_size_usd,
        force_reprobe,
        args.prioritize_false_positive_reprobe,
    )

    from m9.graph_arb.pool_depth_probe import enrich_routes_missing_depth

    counts = enrich_routes_missing_depth(
        routes,
        rpc_url=rpc_url,
        dex_quoters=dex_quoters,
        probe_size_usd=args.probe_size_usd,
        ref_size_usd=args.ref_size_usd,
        sleep_s=max(0.0, args.sleep_ms / 1000.0),
        force_reprobe=force_reprobe,
        prioritized_reprobe_only=bool(args.prioritize_false_positive_reprobe),
    )

    from m9.graph_arb.depth_telemetry import depth_known_rate, economics_blocked_by_depth_telemetry

    _dkr = depth_known_rate(routes)
    log.info(
        "Depth enrichment: candidates=%d force_reprobe=%d probed_ok=%d distinct_ok=%d failed=%d "
        "no_anchor=%d skipped_v4=%d toxic=%d low_depth=%d depth_known_rate=%.4f "
        "v4_candidates=%d v4_ok=%d v4_failed=%d",
        counts["candidates"], counts.get("force_reprobe_candidates", 0),
        counts["probed_ok"], counts.get("distinct_depth_ok", 0),
        counts["probe_failed"], counts["no_anchor"], counts["skipped_v4"],
        counts["toxic"], counts["low_depth"], _dkr,
        counts["v4_depth_candidates"], counts["v4_depth_probe_ok"],
        counts["v4_depth_probe_failed"],
    )
    metrics = inventory.setdefault("bridge_source_metrics", {})
    metrics["depth_known_rate"] = _dkr
    metrics["depth_known_count"] = sum(
        1 for r in routes if r.get("effective_depth_usd") is not None
    )
    metrics["depth_active_routes"] = len(routes)
    metrics["depth_force_reprobe_enabled"] = force_reprobe
    metrics["depth_prioritize_false_positive_reprobe"] = bool(
        args.prioritize_false_positive_reprobe
    )
    metrics["depth_force_reprobe_candidates"] = counts.get("force_reprobe_candidates", 0)
    metrics["economics_conclusion_blocked"] = economics_blocked_by_depth_telemetry(_dkr)
    metrics["v4_depth_candidates"] = counts["v4_depth_candidates"]
    metrics["v4_depth_probe_ok"] = counts["v4_depth_probe_ok"]
    metrics["v4_depth_probe_failed"] = counts["v4_depth_probe_failed"]
    metrics["v4_depth_skipped_unsupported"] = counts["skipped_v4"]
    metrics["multicall_saved_calls_estimate"] = counts.get("multicall_saved_calls_estimate", 0)
    try:
        from m9.graph_arb.bridge_builder import _route_capacity_histogram

        metrics["route_capacity_histogram"] = _route_capacity_histogram(routes)
        log.info(
            "route_capacity_histogram: %s",
            metrics["route_capacity_histogram"],
        )
    except Exception:
        pass
    try:
        from m9.graph_arb.pool_quality import annotate_routes_pool_quality

        metrics["pool_quality_histogram"] = annotate_routes_pool_quality(routes)
    except Exception:
        pass

    from m9.graph_arb.depth_contract import normalize_route_depth_contract
    from m9.graph_arb.narrow_universe_gate import depth_probe_status_histogram

    for route in routes:
        normalize_route_depth_contract(route)

    inventory["depth_probe_status_histogram"] = depth_probe_status_histogram(routes)

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
