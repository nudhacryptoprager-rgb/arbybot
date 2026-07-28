"""Process-wide StateRepository singleton for continuous pipeline workers."""
from __future__ import annotations

import os
from typing import Optional

from state.factory import create_state_repository
from state.repository import StateRepository

_SHARED: Optional[StateRepository] = None


def get_shared_repository(*, backend: Optional[str] = None) -> StateRepository:
    """Return one repository instance per process (all workers share the queue)."""
    global _SHARED
    if _SHARED is None:
        resolved = backend or os.environ.get("ARBY_STATE_REPOSITORY_BACKEND", "in_memory")
        if os.environ.get("ARBY_CONTINUOUS_PRODUCTION") == "1" and resolved != "postgres":
            raise ValueError(
                "continuous production requires ARBY_STATE_REPOSITORY_BACKEND=postgres"
            )
        _SHARED = create_state_repository(backend=resolved)
    return _SHARED


def reset_shared_repository() -> None:
    """Test helper — drop cached singleton."""
    global _SHARED
    _SHARED = None
