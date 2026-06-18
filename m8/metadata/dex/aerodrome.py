"""Aerodrome route metadata worker."""
from __future__ import annotations

from m8.metadata.dex.base import GenericPoolRouteWorker


class AerodromeDexWorker(GenericPoolRouteWorker):
    def __init__(self) -> None:
        super().__init__("aerodrome", ("aerodrome", "velodrome", "solidly"))
