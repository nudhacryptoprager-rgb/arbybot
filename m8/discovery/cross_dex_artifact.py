"""Cross-DEX expansion artifact export (extracted module)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def write_artifact(artifact: Dict[str, Any], output_path: Path) -> None:
    from core.pipeline_provenance import apply_pipeline_provenance

    ts = artifact.get("generated_at_utc")
    if not ts:
        rc = artifact.get("run_context") or {}
        ts = rc.get("run_timestamp") if isinstance(rc, dict) else None
    artifact = apply_pipeline_provenance(artifact, run_timestamp=ts)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, ensure_ascii=False, indent=2)
