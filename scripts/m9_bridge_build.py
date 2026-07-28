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
import os
import sys

# Ensure repo root is importable regardless of how the script is invoked
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


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
    p.add_argument(
        "--config",
        default=None,
        help="Config YAML path (accepted for pipeline compat; not used by bridge builder)",
    )
    p.add_argument(
        "--include-config-seed-pools",
        action="store_true",
        default=False,
        help=(
            "SMOKE / BOOTSTRAP MODE: inject Curve pools from config/adapter_metadata.yaml "
            "directly into active_routes without dynamic discovery. "
            "Do NOT use in production — production relies on m9_curve_discovery.py."
        ),
    )
    p.add_argument(
        "--expansion",
        default="data/runs/_rolling/m8_cross_dex_expansion_latest.json",
        help="M8.2 cross-DEX expansion artifact path (set empty to disable)",
    )
    p.add_argument(
        "--no-expansion",
        action="store_true",
        help="Disable M8.2 cross-DEX expansion merge",
    )
    p.add_argument(
        "--registry",
        default="data/runs/_rolling/m8_pending_pairs.json",
        help=(
            "M8.2 pending-pair registry path (cross-run single->multi venue "
            "accumulator). Promotes long-tail tokens once seen on >=2 venues."
        ),
    )
    p.add_argument(
        "--no-registry",
        action="store_true",
        default=False,
        help="Disable the M8.2 pending-pair registry (no promotion, no persistence).",
    )
    p.add_argument(
        "--registry-ttl-seconds",
        type=float,
        default=None,
        help="TTL for venue observations in the registry (default 48h).",
    )
    p.add_argument(
        "--include-expansion-duplicates-for-shadow",
        action="store_true",
        default=False,
        help=(
            "Shadow/diagnostic only: include M8.2 expansion routes even when pool "
            "already exists in base inventory (tagged shadow_dedupe_duplicate)."
        ),
    )
    p.add_argument(
        "--graph-handoff-only",
        action="store_true",
        default=False,
        help=(
            "Merge only M8.2 expansion routes from graph_topology_ready focus tokens "
            "(requires_quote_validation; no M8.2 economics claim)"
        ),
    )
    p.add_argument(
        "--no-enforce-m8-provenance",
        action="store_true",
        default=False,
        help="Legacy: keep exploration/base routes in active_routes (default: enforce on)",
    )
    p.add_argument(
        "--watchlist",
        default="data/tmp/m8_token_watchlist_latest.json",
        help="M8 token watchlist for provenance matching",
    )
    p.add_argument(
        "--strict-pre-shadow",
        action="store_true",
        default=False,
        help="Fail when depth/decimals enrichment pre-shadow blockers are present",
    )
    p.add_argument(
        "--metadata-registry",
        default="data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
        help="M8.3 token metadata registry applied during bridge build",
    )
    p.add_argument(
        "--session-aggregate",
        default=None,
        help="Path to session_aggregate.json from continuous pipeline (skips rolling M8 artifacts)",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    import logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("m9_bridge_build")

    if args.session_aggregate:
        import json
        from pathlib import Path

        from core.session_aggregate import SessionAggregate, bridge_inventory_from_aggregate

        agg_path = Path(args.session_aggregate)
        if not agg_path.is_file():
            log.error("session aggregate not found: %s", agg_path)
            return 2
        doc = json.loads(agg_path.read_text(encoding="utf-8"))
        agg = SessionAggregate(session_id=str(doc.get("session_id") or "unknown"))
        for pool in doc.get("pools") or []:
            if isinstance(pool, dict):
                agg.upsert_pool(pool)
        for token in doc.get("tokens") or []:
            if isinstance(token, dict):
                agg.upsert_token(token)
        for route in doc.get("routes") or []:
            if isinstance(route, dict):
                agg.upsert_route(route)
        bridge_doc = bridge_inventory_from_aggregate(agg)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(bridge_doc, indent=2) + "\n", encoding="utf-8")
        log.info(
            "Bridge from session aggregate: routes=%d output=%s",
            bridge_doc.get("graph_ready_total", 0),
            out_path,
        )
        return 0 if bridge_doc.get("graph_ready_total", 0) > 0 else 1

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
        include_config_seed=args.include_config_seed_pools,
        registry_path=(None if args.no_registry else args.registry),
        registry_ttl_seconds=args.registry_ttl_seconds,
        expansion_path=(None if args.no_expansion else args.expansion or None),
        include_expansion_duplicates_for_shadow=args.include_expansion_duplicates_for_shadow,
        graph_handoff_only=bool(args.graph_handoff_only),
        enforce_m8_provenance=not args.no_enforce_m8_provenance,
        watchlist_path=args.watchlist,
        metadata_registry_path=args.metadata_registry,
    )

    log.info("Bridge funnel:")
    log.info("  m8_new_pools_input       : %d", metrics["m8_new_pools_input"])
    log.info("  token_verified_count     : %d", metrics["token_verified_count"])
    log.info("  anchor_connected_count   : %d", metrics["anchor_connected_count"])
    log.info("  cross_dex_seen_count     : %d", metrics["cross_dex_seen_count"])
    log.info(
        "  active_factory_verified_routes: %d (operator primary)",
        metrics.get("active_factory_verified_routes", 0),
    )
    log.info(
        "  base_inventory_factory_verified_count: %d (legacy base-inv only)",
        metrics.get("base_inventory_factory_verified_count", metrics["factory_verified_count"]),
    )
    log.info("  factory_verified_count   : %d", metrics["factory_verified_count"])
    log.info("  depth_ok_count           : %d", metrics["depth_ok_count"])
    log.info("  graph_ready_from_m8      : %d", metrics["graph_ready_from_m8"])
    log.info("  graph_ready_from_expansion: %d", metrics.get("graph_ready_from_expansion", 0))
    log.info(
        "  expansion_deduped_existing_pool_count: %d",
        metrics.get("expansion_deduped_existing_pool_count", 0),
    )
    if metrics.get("expansion_deduped_pool_samples"):
        log.info(
            "  expansion_deduped_pool_samples: %s",
            metrics.get("expansion_deduped_pool_samples"),
        )
    log.info("  expansion_multi_venue    : %d", metrics.get("expansion_multi_venue_count", 0))
    log.info("  graph_ready_total        : %d", metrics["graph_ready_total"])
    log.info("  registry_enabled         : %s", metrics.get("registry_enabled", False))
    log.info("  registry_tokens_tracked  : %d", metrics.get("registry_tokens_tracked", 0))
    log.info("  registry_multi_venue     : %d", metrics.get("registry_multi_venue_tokens", 0))
    log.info("  registry_promoted_routes : %d", metrics.get("registry_promoted_routes", 0))
    log.info("  metadata_seeded_count    : %d  [seed=%s]",
             metrics.get("metadata_seeded_count", 0),
             metrics.get("include_config_seed", False))
    log.info(
        "  curve_discovery_loaded   : %d",
        metrics.get("curve_discovery_artifact_loaded_count", 0),
    )
    log.info(
        "  curve_discovery_admitted : %d",
        metrics.get("curve_discovery_admitted_count", 0),
    )
    log.info(
        "  curve_stable_routes      : %d",
        metrics.get("curve_stable_route_count", 0),
    )
    log.info(
        "  curve_indices_missing    : %d",
        metrics.get("curve_indices_missing_count", 0),
    )
    log.info(
        "  single_venue_blocked     : %d",
        metrics.get("structural_single_venue_blocked_count", 0),
    )
    log.info("  m8_stale                 : %s", metrics["m8_stale"])
    log.info("  m8_1_stale               : %s", metrics["m8_1_stale"])
    log.info(
        "  m8_sniper_operational    : %s",
        metrics.get("m8_sniper_artifact_operational"),
    )
    log.info(
        "  m8_direct_routes_bridge  : %d",
        metrics.get("m8_direct_routes_in_bridge", 0),
    )
    log.info(
        "  routes_decimals_unknown  : %d",
        metrics.get("routes_decimals_unknown", 0),
    )
    cap = metrics.get("route_capacity_histogram") or {}
    if cap:
        log.info(
            "  route_capacity_histogram : gte_25=%s gte_63_75=%s gte_180=%s active=%s",
            cap.get("routes_effective_depth_gte_25"),
            cap.get("routes_effective_depth_gte_63_75"),
            cap.get("routes_effective_depth_gte_180"),
            cap.get("active_routes"),
        )
    log.info("Written: %s", args.output)

    # Acceptance check
    if metrics["graph_ready_total"] == 0:
        log.error("FAIL: graph_ready_total=0 — bridge inventory is empty")
        return 1

    if metrics["graph_ready_total"] < 10:
        log.warning(
            "WARN: graph_ready_total=%d — universe too small for M9 soak "
            "(multi-venue gate may have blocked most M8 events; "
            "structural_single_venue_blocked=%d)",
            metrics["graph_ready_total"],
            metrics.get("structural_single_venue_blocked_count", 0),
        )
    if metrics.get("curve_stable_route_count", 0) == 0:
        log.warning(
            "WARN: curve_stable_route_count=0 — run scripts/m9_curve_discovery.py "
            "then rebuild bridge before discover_curve_indices.py"
        )
    if metrics.get("curve_discovery_artifact_loaded_count", 0) == 0:
        log.warning(
            "WARN: curve_discovery_artifact_loaded_count=0 — "
            "m9_curve_discovery_latest.json missing/stale/empty"
        )

    # Warn if staleness is high (non-fatal: still proceed)
    if metrics["m8_stale"]:
        log.warning(
            "WARN: m8 artifact is stale (age=%ss > %ss) — run M8 sniper to refresh",
            metrics.get("sniper_age_seconds"),
            metrics.get("m8_stale_threshold_seconds"),
        )
    if metrics["m8_1_stale"]:
        log.warning("WARN: m8_1 artifact is stale (>4h old) — run M8.1 stable-anchor to refresh")

    try:
        from m9.graph_arb.depth_telemetry import depth_known_rate, economics_blocked_by_depth_telemetry

        _routes = []
        try:
            import json
            from pathlib import Path

            _out = Path(args.output)
            if _out.exists():
                _routes = json.loads(_out.read_text(encoding="utf-8")).get("active_routes") or []
        except Exception:
            pass
        if _routes:
            _dkr = depth_known_rate(_routes)
            log.info("  depth_known_rate          : %.4f", _dkr)
            if economics_blocked_by_depth_telemetry(_dkr):
                log.warning(
                    "WARN: depth_known_rate=%.4f < 0.8 — run scripts/m9_enrich_bridge_depth.py "
                    "before M9 shadow/economics",
                    _dkr,
                )
    except Exception:
        pass

    _pre_shadow = metrics.get("pre_shadow_blockers") or []
    if _pre_shadow:
        log.warning(
            "WARN: pre_shadow_blockers=%s — run decimals/depth enrichment before shadow",
            _pre_shadow,
        )
        if args.strict_pre_shadow:
            log.error("FAIL: strict_pre_shadow gate blocked bridge handoff")
            return 1

    log.info("Bridge build: OK (graph_ready_total=%d)", metrics["graph_ready_total"])
    try:
        from m9.graph_arb.bridge_canonical import (
            CANONICAL_BRIDGE_PATH,
            sync_bridge_canonical,
        )

        if Path(args.output).resolve() == CANONICAL_BRIDGE_PATH.resolve():
            sync_bridge_canonical(Path(args.output), metrics=metrics)
            log.info("Canonical bridge pointer synced (graph_handoff → shadow_latest alias)")
    except Exception as _canon_exc:
        log.warning("WARN: bridge canonical sync skipped: %s", _canon_exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
