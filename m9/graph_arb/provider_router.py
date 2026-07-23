"""Backward-compatible re-export shim.

The ProviderRouter implementation lives in ``core.provider_router_impl``
(core layer owns RPC routing; milestone packages import core, not the
reverse).  Existing consumers importing from
``m9.graph_arb.provider_router`` keep working unchanged.
"""
from __future__ import annotations

from core.provider_router_impl import (  # noqa: F401
    ProviderRouter,
    _mask,
    _ProviderStats,
)

__all__ = ["ProviderRouter", "_ProviderStats", "_mask"]
