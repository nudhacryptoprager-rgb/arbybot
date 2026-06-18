"""Algebra route metadata worker."""
from __future__ import annotations

from m8.metadata.dex.base import GenericPoolRouteWorker


class AlgebraDexWorker(GenericPoolRouteWorker):
    def __init__(self) -> None:
        super().__init__("algebra", ("algebra", "quickswap_algebra"))
