"""Post-depth effective execution inventory — shared by capacity, runner, shadow."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from m9.graph_arb.inventory_truth import _DEFAULT_OUT as EFFECTIVE_EXECUTION_INVENTORY_PATH

log = logging.getLogger(__name__)

__all__ = (
    "EFFECTIVE_EXECUTION_INVENTORY_PATH",
    "assert_post_depth_inventory",
    "prepare_effective_execution_inventory",
)


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
    output_path: str = EFFECTIVE_EXECUTION_INVENTORY_PATH,
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
        output_path=output_path,
    )
    log.info("Prepared effective execution inventory: %s -> %s", inventory_path, out)
    return out
