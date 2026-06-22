"""Algebra route metadata worker."""
from __future__ import annotations

from typing import Any

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields
from m8.metadata.dex.pool_static import amm_pool_static_metadata


class AlgebraDexWorker(DexMetadataWorker):
    worker_id = "algebra"
    dex_patterns = ("algebra", "quickswap_algebra")

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        missing = _require_fields(route, ("pool_address", "token0_addr", "token1_addr"))
        meta = amm_pool_static_metadata(route)
        meta["algebra_dynamic_fee"] = route.get("algebra_dynamic_fee") or route.get("dynamic_fee")
        ready = not missing
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="algebra_pool" if ready else None,
        )
