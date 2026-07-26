"""Post-depth effective execution inventory — shared by capacity, runner, shadow."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.pipeline_provenance import pipeline_session_id

log = logging.getLogger(__name__)

ENV_EFFECTIVE_INVENTORY_PATH = "ARBY_M9_EFFECTIVE_INVENTORY_PATH"
LEGACY_EFFECTIVE_INVENTORY_PATH = "data/tmp/m9_inventory_truth_enriched.json"

__all__ = (
    "ENV_EFFECTIVE_INVENTORY_PATH",
    "LEGACY_EFFECTIVE_INVENTORY_PATH",
    "assert_post_depth_inventory",
    "build_route_universe_identity",
    "prepare_effective_execution_inventory",
    "resolve_effective_inventory_path",
    "sanitize_session_token",
)


def sanitize_session_token(session_id: Optional[str]) -> str:
    sid = str(session_id or pipeline_session_id() or "unknown").strip()
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", sid)
    return (safe[:96] or "unknown").strip("_") or "unknown"


def resolve_effective_inventory_path(session_id: Optional[str] = None) -> str:
    """Session-namespaced effective inventory path (env override for pipeline binding)."""
    env = os.environ.get(ENV_EFFECTIVE_INVENTORY_PATH, "").strip()
    if env:
        return env.replace("\\", "/")
    token = sanitize_session_token(session_id)
    return f"data/tmp/m9_effective_execution_inventory_{token}.json"


def build_route_universe_identity(inventory_path: str) -> Dict[str, str]:
    """Deterministic identity of the post-depth active route universe."""
    inv = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
    route_ids = sorted(
        str(r.get("route_id") or "").strip()
        for r in (inv.get("active_routes") or [])
        if str(r.get("route_id") or "").strip()
    )
    depth = inv.get("depth_enrichment") or {}
    route_hash = hashlib.sha256("|".join(route_ids).encode("utf-8")).hexdigest()[:16]
    return {
        "route_universe_hash": route_hash,
        "post_depth_content_hash": str(depth.get("post_depth_content_hash") or ""),
    }


def assert_post_depth_inventory(doc: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Require depth enrichment metadata on bridge inventory."""
    if not doc:
        return False, ["inventory_missing"]
    depth = doc.get("depth_enrichment") or {}
    blockers: List[str] = []
    if not str(depth.get("post_depth_content_hash") or "").strip():
        blockers.append("PRE_DEPTH_INVENTORY")
    if not str(depth.get("depth_enrichment_session_id") or "").strip():
        blockers.append("DEPTH_ENRICHMENT_SESSION_ID_MISSING")
    return len(blockers) == 0, blockers


def prepare_effective_execution_inventory(
    inventory_path: str,
    config_path: str,
    *,
    chain: Optional[str] = None,
    output_path: Optional[str] = None,
    session_id: Optional[str] = None,
    require_post_depth: bool = True,
    w3: Any = None,
    token_prices: Optional[Dict[str, float]] = None,
) -> str:
    """Truth-enrich post-depth bridge inventory for capacity/runner/shadow alignment."""
    inv_p = Path(inventory_path)
    if not inv_p.is_file():
        raise FileNotFoundError(f"inventory not found: {inventory_path}")

    with inv_p.open(encoding="utf-8") as fh:
        inv = json.load(fh)

    if require_post_depth:
        ok, blockers = assert_post_depth_inventory(inv)
        if not ok:
            raise ValueError(
                f"effective inventory requires post-depth bridge ({','.join(blockers)})"
            )

    from m9.graph_arb.inventory_truth import enrich_inventory_for_quote_truth

    resolved_out = output_path or resolve_effective_inventory_path(session_id)

    resolved_w3 = w3
    resolved_prices = token_prices
    if resolved_w3 is None and chain:
        try:
            from core.rpc_urls import get_rpc_url
            from web3 import Web3

            url = get_rpc_url(chain)
            if url:
                resolved_w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
        except Exception as exc:
            log.debug("effective inventory: rpc connect skipped: %s", exc)

    if resolved_prices is None:
        try:
            from m9.graph_arb.token_price_fetcher import (
                build_dual_key_price_map,
                extend_price_map_from_inventory,
                fetch_token_prices_usd,
            )

            price_result = fetch_token_prices_usd(timeout_s=3.0)
            resolved_prices = extend_price_map_from_inventory(
                str(inv_p),
                config_path,
                price_result.prices_by_address
                or build_dual_key_price_map(price_result.prices),
            )
        except Exception as exc:
            log.debug("effective inventory: price map skipped: %s", exc)
            resolved_prices = None

    out = enrich_inventory_for_quote_truth(
        str(inv_p),
        config_path,
        w3=resolved_w3,
        token_prices=resolved_prices,
        output_path=resolved_out,
    )
    log.info("Prepared effective execution inventory: %s -> %s", inventory_path, out)
    return out
