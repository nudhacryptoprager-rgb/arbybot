"""DexMetadataWorker interface — route/pool metadata only, no token decimals authority."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional, Sequence

from m8.metadata.contracts import DexRouteMetadataResult, MetadataTask


def route_dex_family(route: Dict[str, Any]) -> str:
    return str(route.get("adapter_type") or route.get("dex_id") or "unknown")


def route_id_of(route: Dict[str, Any]) -> str:
    return str(route.get("route_id") or route.get("pair_id") or "")


class DexMetadataWorker(ABC):
    """Child worker: collects DEX-specific route metadata; never writes token registry."""

    worker_id: str
    dex_patterns: Sequence[str]

    def matches(self, route: Dict[str, Any]) -> bool:
        fam = route_dex_family(route).lower()
        dex_id = str(route.get("dex_id") or "").lower()
        for pat in self.dex_patterns:
            p = pat.lower()
            if fam == p or dex_id == p or fam.startswith(p) or dex_id.startswith(p):
                return True
        return False

    def build_task(self, route: Dict[str, Any], *, scope: str = "all_routes") -> Optional[MetadataTask]:
        rid = route_id_of(route)
        if not rid:
            return None
        return MetadataTask(
            task_id=f"{self.worker_id}:{rid}",
            kind="dex_route",
            worker_id=self.worker_id,
            route_id=rid,
            route=dict(route),
            scope=scope,
        )

    @abstractmethod
    def process(self, task: MetadataTask, *, w3: Any = None) -> DexRouteMetadataResult:
        ...

    def _result(
        self,
        task: MetadataTask,
        *,
        ready: bool,
        metadata: Dict[str, Any],
        error_code: Optional[str] = None,
        missing_fields: Optional[List[str]] = None,
        quoteability_hint: Optional[str] = None,
    ) -> DexRouteMetadataResult:
        route = task.route or {}
        return DexRouteMetadataResult(
            route_id=task.route_id or route_id_of(route),
            worker_id=self.worker_id,
            dex_family=route_dex_family(route),
            ready=ready,
            metadata=metadata,
            error_code=error_code,
            missing_fields=missing_fields or [],
            quoteability_hint=quoteability_hint,
        )


def _require_fields(route: Dict[str, Any], fields: Iterable[str]) -> List[str]:
    missing: List[str] = []
    for f in fields:
        val = route.get(f)
        if val is None or val == "" or val == [] or val == {}:
            missing.append(f)
    return missing


class GenericPoolRouteWorker(DexMetadataWorker):
    """Minimal route metadata for standard AMM pools (v2/v3-like)."""

    def __init__(self, worker_id: str, dex_patterns: Sequence[str]) -> None:
        self.worker_id = worker_id
        self.dex_patterns = dex_patterns

    def process(self, task: MetadataTask, *, w3: Any = None) -> DexRouteMetadataResult:
        route = task.route or {}
        missing = _require_fields(route, ("token0_addr", "token1_addr", "pool_address"))
        meta = {
            "pool_address": route.get("pool_address"),
            "token0_addr": route.get("token0_addr"),
            "token1_addr": route.get("token1_addr"),
            "fee": route.get("fee"),
            "direction_support": "bidirectional",
        }
        ready = not missing
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="generic_pool" if ready else None,
        )


def all_dex_workers() -> List[DexMetadataWorker]:
    from m8.metadata.dex.balancer import BalancerDexWorker
    from m8.metadata.dex.curve import CurveDexWorker
    from m8.metadata.dex.maverick import MaverickDexWorker
    from m8.metadata.dex.uniswap_v2 import UniswapV2DexWorker
    from m8.metadata.dex.uniswap_v3 import UniswapV3DexWorker
    from m8.metadata.dex.uniswap_v4 import UniswapV4DexWorker
    from m8.metadata.dex.algebra import AlgebraDexWorker
    from m8.metadata.dex.aerodrome import AerodromeDexWorker

    return [
        UniswapV4DexWorker(),
        BalancerDexWorker(),
        MaverickDexWorker(),
        CurveDexWorker(),
        UniswapV3DexWorker(),
        UniswapV2DexWorker(),
        AlgebraDexWorker(),
        AerodromeDexWorker(),
    ]


def token_erc20_worker():
    from m8.metadata.dex.erc20 import Erc20TokenWorker

    return Erc20TokenWorker()


def assign_route_worker(route: Dict[str, Any], workers: Sequence[DexMetadataWorker]) -> Optional[DexMetadataWorker]:
    for w in workers:
        if w.matches(route):
            return w
    return None
