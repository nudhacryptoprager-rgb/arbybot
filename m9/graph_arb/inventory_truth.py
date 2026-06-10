"""Enrich bridge inventory with quote-size truth fields before graph build."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_DEFAULT_OUT = "data/tmp/m9_inventory_truth_enriched.json"


def enrich_inventory_for_quote_truth(
    inventory_path: str,
    config_path: str,
    *,
    w3: Any = None,
    token_prices: Optional[Dict[str, float]] = None,
    output_path: str = _DEFAULT_OUT,
    max_distinct_depth_probes: int = 50,
) -> str:
    """Write enriched inventory with decimals (+ optional depth) and return path."""
    from m8_1.stable_anchor.config_loader import load_config
    from m9.graph_arb.distinct_depth_probe import enrich_route_depth_if_missing, needs_distinct_depth_probe
    from m9.graph_arb.token_decimals import enrich_routes_decimals, load_decimals_cache
    from m9.graph_arb.token_price_fetcher import build_dual_key_price_map

    inv_p = Path(inventory_path)
    if not inv_p.exists():
        return inventory_path

    with inv_p.open(encoding="utf-8") as fh:
        inv = json.load(fh)

    cfg = None
    if Path(config_path).exists():
        try:
            cfg = load_config(config_path)
        except Exception as exc:
            log.debug("inventory truth: config load failed: %s", exc)

    cache = load_decimals_cache()
    routes = inv.get("active_routes") or []
    _depth_probed = 0
    prices = token_prices or build_dual_key_price_map({})

    inv["decimals_source_histogram"] = enrich_routes_decimals(
        routes, cfg=cfg, cache=cache, w3=w3, persist_cache=True
    )
    for route in routes:
        if (
            w3 is not None
            and needs_distinct_depth_probe(route)
            and _depth_probed < max_distinct_depth_probes
        ):
            if enrich_route_depth_if_missing(
                route, w3, prices, cfg=cfg, decimals_cache=cache
            ):
                _depth_probed += 1

    inv["quote_truth_enriched"] = True
    inv["quote_truth_routes_with_decimals"] = sum(
        1
        for r in routes
        if r.get("token0_decimals") is not None and r.get("token1_decimals") is not None
    )
    inv["quote_truth_distinct_depth_probed"] = _depth_probed

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", encoding="utf-8") as fh:
        json.dump(inv, fh, ensure_ascii=False, indent=2)

    return str(out_p)
