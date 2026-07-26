"""Cycle selection service placeholder — sweep scheduling extracted incrementally."""
from __future__ import annotations

from typing import Any, List

__all__ = ["select_cycles_for_sweep"]


def select_cycles_for_sweep(cycles: List[Any], *, limit: int) -> List[Any]:
    return list(cycles[:limit])
