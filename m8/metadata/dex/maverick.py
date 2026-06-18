"""Maverick route metadata worker."""
from __future__ import annotations

from typing import Any, List

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields


class MaverickDexWorker(DexMetadataWorker):
    worker_id = "maverick"
    dex_patterns = ("maverick_v2", "maverick")

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        missing = _require_fields(route, ("pool_address", "token0_addr", "token1_addr"))
        token_a = route.get("token_a_address") or route.get("maverick_token_a")
        token_b = route.get("token_b_address") or route.get("maverick_token_b")
        if not token_a:
            missing.append("token_a_address")
        if not token_b:
            missing.append("token_b_address")
        probe_by_tin = route.get("maverick_probe_by_token_in") or {}
        direction_capacity = {
            "probe_by_token_in": probe_by_tin,
            "min_quoteable_raw": route.get("maverick_min_quoteable_amount_raw"),
            "max_quoteable_raw": route.get("maverick_max_quoteable_amount_raw"),
            "pool_lane_probe_amount": route.get("maverick_pool_lane_probe_amount"),
        }
        has_direction = bool(probe_by_tin) or route.get("maverick_min_quoteable_amount_raw") is not None
        meta = {
            "pool_address": route.get("pool_address"),
            "token_a": token_a or route.get("token0_addr"),
            "token_b": token_b or route.get("token1_addr"),
            "direction_capacity": direction_capacity,
            "direction_support": "directional" if has_direction else "unknown",
        }
        ready = not missing
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="maverick_direction" if ready and has_direction else None,
        )
