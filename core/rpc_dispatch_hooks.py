"""Thread-local hooks for marking actual RPC transport dispatch (SLO instrumentation)."""
from __future__ import annotations

import threading
from typing import Callable, Optional

_tls = threading.local()

__all__ = [
    "clear_on_rpc_dispatch",
    "notify_rpc_dispatch",
    "set_on_rpc_dispatch",
]


def set_on_rpc_dispatch(callback: Optional[Callable[[], None]]) -> None:
    _tls.on_rpc_dispatch = callback


def clear_on_rpc_dispatch() -> None:
    if hasattr(_tls, "on_rpc_dispatch"):
        delattr(_tls, "on_rpc_dispatch")


def notify_rpc_dispatch() -> None:
    callback = getattr(_tls, "on_rpc_dispatch", None)
    if callback is not None:
        callback()
