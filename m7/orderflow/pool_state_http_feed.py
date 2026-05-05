"""E1.59 step #5: HTTP pending-logs feed into ``pool_price_state``.

Reviewer 3h-soak finding: ``pool_price_state.updates_total=0`` because the
hot WS lane never delivered Swap/Sync events (rate limits + 405). This
module bridges the HTTP-only Flashblocks lane (step #3) into the price
state registry (``m7.orderflow.pool_price_state.feed_raw_logs``), so
``updates_total`` can advance even when WS is unavailable.

Default OFF — opt-in via ``ARBY_POOL_STATE_HTTP_FEED=1``. Requires
``ARBY_FLASHBLOCKS_HTTP_LANE=1`` to actually fetch.

Public API:
  * ``poll_and_feed(rpc_url, chain, addresses, topics, http_post)`` ->
    dict with feed counters (delegated from ``feed_raw_logs``).
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Dict, List, Optional, Sequence

from chains import flashblocks_http
from m7.orderflow.pool_price_state import feed_raw_logs

logger = logging.getLogger("m7.orderflow.pool_state_http_feed")

# V3 Swap topic0 / V2 Sync topic0 — re-exported for callers that don't
# want to import from pool_price_state directly.
V3_SWAP_TOPIC0 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
V2_SYNC_TOPIC0 = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"

DEFAULT_TOPICS_ANY: List[str] = [V3_SWAP_TOPIC0, V2_SYNC_TOPIC0]


def is_enabled() -> bool:
    return os.environ.get("ARBY_POOL_STATE_HTTP_FEED", "0") == "1"


def poll_and_feed(
    *,
    rpc_url: str,
    chain: str,
    addresses: Sequence[str],
    topics: Optional[Sequence[Optional[object]]] = None,
    http_post: Callable[[str, dict, float], dict],
    timeout_s: float = 5.0,
) -> Dict[str, int]:
    """Poll pending logs via the HTTP lane and feed them into the registry.

    Returns a counters dict. When the feature flag is OFF, returns
    zeroed counters and does not call out.
    """
    zero = {"v3_updates": 0, "v2_updates": 0, "skipped": 0, "fetched": 0}
    if not is_enabled():
        return zero
    # Default topic filter — first topic position OR-list of v3 swap +
    # v2 sync per eth_getLogs filter semantics. See:
    # https://docs.base.org/base-chain/api-reference/ethereum-json-rpc-api/eth_getLogs
    if topics is None:
        topics = [DEFAULT_TOPICS_ANY]

    logs = flashblocks_http.fetch_pending_pool_logs(
        rpc_url=rpc_url,
        addresses=addresses,
        topics=topics,
        http_post=http_post,
        timeout_s=timeout_s,
    )
    if not logs:
        return zero
    try:
        counters = feed_raw_logs(chain=chain, logs=logs)
    except Exception as exc:
        logger.debug("pool_state_http_feed: feed_raw_logs failed: %s", str(exc)[:120])
        return zero
    counters["fetched"] = len(logs)
    return counters


__all__ = [
    "DEFAULT_TOPICS_ANY",
    "V2_SYNC_TOPIC0",
    "V3_SWAP_TOPIC0",
    "is_enabled",
    "poll_and_feed",
]
