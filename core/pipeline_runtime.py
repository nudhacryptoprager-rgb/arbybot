"""Pipeline runtime helpers for internal streaming gates (extracted from start.py)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.pipeline_provenance import ENV_PIPELINE_SESSION_ID
from core.pipeline_streaming import resolve_streaming_batch_paths


def run_streaming_batch_upstream_gate(step: dict[str, Any]) -> int:
    batch_index = int(step.get("streaming_batch_index", 1))
    session_id = os.environ.get(ENV_PIPELINE_SESSION_ID, "").strip()
    paths = resolve_streaming_batch_paths(batch_index, session_id=session_id)
    from monitoring.runtime_truth_gate import evaluate_runtime_truth_gate

    def _load(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    verdict = evaluate_runtime_truth_gate(
        sniper=_load(Path("data/runs/_rolling/new_pool_sniper_latest.json")),
        anchor=_load(paths.m81_output),
        hints=_load(paths.m82_hints),
        expansion=_load(paths.m82_expansion),
        m8_3_registry=_load(paths.m83_registry),
        phase="upstream",
    )
    paths.upstream_gate_output.parent.mkdir(parents=True, exist_ok=True)
    paths.upstream_gate_output.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    print("phase:", verdict.get("phase"))
    print("truth_status:", verdict.get("truth_status"))
    print("written:", paths.upstream_gate_output)
    return 0 if verdict.get("truth_status") == "PASS" else 1
