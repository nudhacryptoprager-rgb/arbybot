"""Balancer route metadata worker."""
from __future__ import annotations

from typing import Any, List

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields


class BalancerDexWorker(DexMetadataWorker):
    worker_id = "balancer"
    dex_patterns = ("balancer_vault", "balancer_stable", "balancer_weighted", "balancer_")

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        assets = route.get("balancer_assets") or route.get("tokens") or []
        missing: List[str] = []
        if not assets:
            missing.append("balancer_assets")
        if not route.get("pool_address") and not route.get("pool_id"):
            missing.append("pool_address")
        token_order = list(assets) if isinstance(assets, list) else []
        meta = {
            "pool_address": route.get("pool_address"),
            "pool_id": route.get("pool_id"),
            "vault": route.get("balancer_vault") or route.get("vault"),
            "tokens_order": token_order,
            "token_order": token_order,
            "rate_providers": route.get("rate_providers") or route.get("balancer_rate_providers"),
            "scaling_factors": route.get("scaling_factors") or route.get("balancer_scaling_factors"),
            "paused": route.get("paused") or route.get("balancer_paused"),
            "weights": route.get("weights") or route.get("balancer_weights"),
            "pool_type": route.get("pool_kind") or route.get("balancer_pool_kind") or route.get("adapter_type"),
            "pool_kind": route.get("pool_kind") or route.get("balancer_pool_kind"),
            "specialization": route.get("balancer_specialization"),
            "factory_verified": route.get("factory_verified"),
        }
        ready = not missing and len(token_order) >= 2
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="balancer_vault_order" if ready else None,
        )
