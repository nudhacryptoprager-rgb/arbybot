"""Uniswap V3 route metadata worker."""
from __future__ import annotations

from typing import Any, List

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields


class UniswapV3DexWorker(DexMetadataWorker):
    worker_id = "uniswap_v3"
    dex_patterns = ("uniswap_v3", "pancake_v3")

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        missing = _require_fields(route, ("pool_address", "token0_addr", "token1_addr", "fee"))
        meta = {
            "pool_address": route.get("pool_address"),
            "token0_addr": route.get("token0_addr"),
            "token1_addr": route.get("token1_addr"),
            "fee": route.get("fee"),
            "tick_spacing": route.get("tick_spacing"),
            "direction_support": "bidirectional",
        }
        ready = not missing
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="v3_pool" if ready else None,
        )
