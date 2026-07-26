"""StateRepository factory — explicit backends for vertical migration."""
from __future__ import annotations

import os
from typing import Optional

from state.repository import StateRepository

__all__ = ["create_state_repository"]


def create_state_repository(*, backend: Optional[str] = None) -> StateRepository:
    resolved = (backend or os.environ.get("ARBY_STATE_REPOSITORY_BACKEND", "in_memory")).strip()
    if resolved == "postgres":
        dsn = os.environ.get("ARBY_STATE_REPOSITORY_DSN", "").strip()
        if not dsn:
            raise ValueError("ARBY_STATE_REPOSITORY_DSN required for postgres backend")
        from state.postgres import PostgresStateRepository

        return PostgresStateRepository(dsn)
    if resolved == "in_memory":
        from state.in_memory import InMemoryStateRepository

        return InMemoryStateRepository()
    raise ValueError(f"unsupported state repository backend: {resolved}")
