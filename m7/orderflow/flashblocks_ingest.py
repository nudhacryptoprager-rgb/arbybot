"""M7.E1.51 slice-6 — Flashblocks pre-confirmation intake (stub).

Purpose
-------
Base sequencer exposes "flashblocks" — pre-confirmed transaction batches
delivered before the full block is propagated. Subscribing to
``newFlashblockTransactions`` (or its provider-specific equivalent) gives
the indexer a ~200-300ms head start versus ``eth_subscribe newHeads`` on
public RPC.

This module is an **additive stub** — it defines the contract so that
later slices can plug a real subscriber without touching the hot lane
WS recv loop. The default subscriber is a no-op.

Wiring contract
---------------
A flashblock is delivered as a list of pseudo-logs::

    [
        {"address": "0xpool...", "data": "0x...", "blockNumber": <preConfirmedBlock>,
         "logIndex": <i>, "preConfirmed": True},
        ...
    ]

The intake function is expected to feed the same registry sink as the
final-block path::

    feed_raw_logs(chain, flashblock_logs)

with the additional invariant that ``preConfirmed`` states are tagged
in the registry via ``state.captured_at`` ordering only. The registry
already drops stale writes via the ``(block_number, log_index)`` key,
so a later final-block log naturally overrides a flashblock estimate.

Provider notes
--------------
- Base official sequencer publishes flashblocks via WebSocket subscription
  topic ``newFlashblockTransactions`` (provider-specific name varies).
- BloXroute / Merkle.io expose private flashblock streams on paid tiers.
- Public RPC providers do NOT expose flashblocks. Self-host plan: see
  ``docs/m7/SELF_HOST_BASE_NODE.md`` (slice-7).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from m7.orderflow.pool_price_state import feed_raw_logs


def consume_flashblock(
    chain: str,
    flashblock_logs: Iterable[Dict[str, Any]],
) -> Dict[str, int]:
    """Feed flashblock pseudo-logs into the local price-state registry.

    Returns the same counter dict shape as ``feed_raw_logs``::

        {"v3_updates": int, "v2_updates": int, "skipped": int}

    Never raises. If the input is None or non-iterable, returns zero
    counters.
    """
    try:
        logs = list(flashblock_logs) if flashblock_logs else []
    except Exception:
        return {"v3_updates": 0, "v2_updates": 0, "skipped": 0}
    return feed_raw_logs(chain, logs)


class FlashblockSubscriber:
    """Stub subscriber. Real implementation lands in slice-6b.

    The subscriber is expected to call ``consume_flashblock(chain, logs)``
    on every received flashblock. The default ``run`` is a no-op so the
    module can be imported without any provider configured.
    """

    def __init__(self, chain: str, ws_url: Optional[str] = None) -> None:
        self.chain = chain
        self.ws_url = ws_url

    async def run(self) -> None:
        # Real implementation would aiohttp-WS subscribe here.
        return None


__all__ = ["consume_flashblock", "FlashblockSubscriber"]
