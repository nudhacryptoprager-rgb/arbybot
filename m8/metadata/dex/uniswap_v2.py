"""Uniswap V2 route metadata worker."""
from __future__ import annotations

from m8.metadata.dex.base import GenericPoolRouteWorker


class UniswapV2DexWorker(GenericPoolRouteWorker):
    def __init__(self) -> None:
        super().__init__("uniswap_v2", ("uniswap_v2", "sushiswap", "pancake_v2"))
