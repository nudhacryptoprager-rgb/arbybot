"""Runner provenance stamping helpers (shared by runner + terminal paths)."""
from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = ["stamp_runner_completion_provenance"]


def stamp_runner_completion_provenance(
    artifact: Dict[str, Any],
    *,
    run_timestamp: str,
    universe_contract: Optional[Dict[str, Any]],
    inventory_path: str,
    session_id: Optional[str],
) -> None:
    from core.pipeline_provenance import apply_pipeline_provenance

    provenance_out = apply_pipeline_provenance(artifact, run_timestamp=run_timestamp)
    artifact.update(provenance_out)
    if universe_contract:
        artifact["universe_contract"] = dict(universe_contract)
    if session_id:
        artifact["session_id"] = session_id
    artifact["effective_inventory_path"] = inventory_path
