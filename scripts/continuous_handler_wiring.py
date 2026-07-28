"""Wire continuous pipeline handlers from the scripts layer (import-boundary safe)."""
from __future__ import annotations

import os
from core.continuous_pipeline import ContinuousOrchestrator
from state.repository import StateRepository


def wire_production_handlers_if_needed(
    orchestrator: ContinuousOrchestrator,
    repository: StateRepository,
) -> None:
    """Register production adapters when stub mode is off."""
    if os.environ.get("ARBY_CONTINUOUS_STUB_ADAPTERS") == "1":
        return
    from scripts.continuous_adapters import PRODUCTION_HANDLERS

    for worker, fn in PRODUCTION_HANDLERS.items():
        orchestrator.register_handler(worker, lambda p, _fn=fn: _fn(repository, p))


def build_wired_orchestrator(
    session_id: str,
    *,
    repository: StateRepository | None = None,
) -> ContinuousOrchestrator:
    from core.continuous_broker import build_orchestrator

    orch = build_orchestrator(session_id, repository=repository)
    wire_production_handlers_if_needed(orch, orch.repository)
    return orch
