"""Uniswap V2 route metadata worker."""
from __future__ import annotations

from typing import Any, List

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields
from m8.metadata.dex.pool_static import amm_pool_static_metadata


class UniswapV2DexWorker(DexMetadataWorker):
    worker_id = "uniswap_v2"
    dex_patterns = ("uniswap_v2", "sushiswap", "pancake_v2")

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        missing = _require_fields(route, ("pool_address", "token0_addr", "token1_addr"))
        meta = amm_pool_static_metadata(route)
        ready = not missing
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="v2_pool" if ready else None,
        )
