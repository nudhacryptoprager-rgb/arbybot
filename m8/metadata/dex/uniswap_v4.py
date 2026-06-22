"""Uniswap V4 route metadata worker."""
from __future__ import annotations

from typing import Any, List, Optional

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields


def _zero_address() -> str:
    return "0x" + "0" * 40


def _native_eth_sentinel() -> str:
    return "0x" + "e" * 40


class UniswapV4DexWorker(DexMetadataWorker):
    worker_id = "uniswap_v4"
    dex_patterns = ("uniswap_v4",)

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        missing: List[str] = []
        for f in ("pool_address", "token0_addr", "token1_addr", "fee", "tick_spacing"):
            missing.extend(_require_fields(route, (f,)) if f not in missing else [])
        hooks = route.get("hooks")
        if hooks is None:
            missing.append("hooks")
        native_alias = _native_alias(route)
        hooks_safe = _hooks_class(hooks)
        c0 = route.get("token0_addr")
        c1 = route.get("token1_addr")
        fee = route.get("fee")
        meta = {
            "pool_key": {
                "currency0": c0,
                "currency1": c1,
                "fee": fee,
                "tick_spacing": route.get("tick_spacing"),
                "hooks": hooks,
            },
            "currency0": c0,
            "currency1": c1,
            "fee": fee,
            "tick_spacing": route.get("tick_spacing"),
            "hooks": hooks,
            "hooks_class": hooks_safe,
            "hook_permissions": route.get("hook_permissions") or route.get("v4_hook_permissions"),
            "dynamic_fee_flag": bool(route.get("dynamic_fee") or route.get("v4_dynamic_fee")),
            "native_alias": native_alias,
            "native_alias_normalized": native_alias or "none",
            "direction_support": "bidirectional",
            "pool_address": route.get("pool_address"),
            "factory_verified": route.get("factory_verified"),
            "init_state_available": bool(route.get("pool_address") and c0 and c1 and fee is not None),
        }
        ready = not missing and hooks_safe != "unknown_unsafe"
        err = None if ready else ("DEX_ROUTE_METADATA_PARTIAL" if missing else "DEX_ROUTE_METADATA_MISSING")
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=err,
            missing_fields=missing if missing else ([] if ready else ["hooks_policy"]),
            quoteability_hint="v4_pool_key" if ready else None,
        )


def _native_alias(route: dict) -> Optional[str]:
    for leg in ("token0", "token1", "token0_addr", "token1_addr"):
        val = str(route.get(leg) or "").lower()
        if val in ("eth", "native", _native_eth_sentinel()):
            return "native_eth_alias"
    return None


def _hooks_class(hooks: object) -> str:
    if hooks is None:
        return "missing"
    h = str(hooks).lower()
    if h in ("", _zero_address()):
        return "no_hooks"
    if "unknown" in h:
        return "unknown_unsafe"
    return "known_or_whitelisted"
