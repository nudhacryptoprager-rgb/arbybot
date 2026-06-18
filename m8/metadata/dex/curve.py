"""Curve route metadata worker."""
from __future__ import annotations

from typing import Any, List

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields


class CurveDexWorker(DexMetadataWorker):
    worker_id = "curve"
    dex_patterns = ("curve_stable", "curve")

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        missing = _require_fields(route, ("pool_address",))
        coin_indices = route.get("coin_indices") or {}
        if not coin_indices or len(coin_indices) < 2:
            missing.append("coin_indices")
        underlying = route.get("underlying_coins") or route.get("curve_underlying")
        wrapped = route.get("wrapped_coins") or route.get("curve_wrapped")
        rates = route.get("curve_rates") or route.get("rates")
        meta = {
            "pool_address": route.get("pool_address"),
            "coin_indices": dict(coin_indices) if isinstance(coin_indices, dict) else {},
            "underlying_coins": underlying,
            "wrapped_coins": wrapped,
            "rates": rates,
            "stable": route.get("stable"),
        }
        ready = not missing
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="curve_coin_indices" if ready else None,
        )
