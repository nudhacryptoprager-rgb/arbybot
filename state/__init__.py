"""State layer — durable repository abstractions.

Canonical home for the ``StateRepository`` contract.  JSON artifacts under
``data/**`` remain the operator-facing export interface; the repository is
the transactional, idempotent system of record for inventory, jobs and
artifact pointers.

Adapters:
  - ``state.postgres.PostgresStateRepository`` — production adapter
    (optional ``postgres`` extra; lazy driver import).
"""
from __future__ import annotations

from state.repository import (
    ArtifactPointer,
    IdempotencyKey,
    JobRecord,
    StateRepository,
)

__all__ = [
    "ArtifactPointer",
    "IdempotencyKey",
    "JobRecord",
    "StateRepository",
]
