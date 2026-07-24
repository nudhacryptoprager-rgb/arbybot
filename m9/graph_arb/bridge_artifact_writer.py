"""Bridge inventory artifact writer (extracted module)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def write_bridge_inventory_artifact(
    output_artifact: Dict[str, Any],
    output_path: str | Path,
    *,
    graph_handoff_only: bool = False,
    bridge_source_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metrics = dict(bridge_source_metrics or output_artifact.get("bridge_source_metrics") or {})
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from core.pipeline_provenance import apply_pipeline_provenance

    ts = output_artifact.get("generated_at_utc")
    if not ts:
        rc = output_artifact.get("run_context") or {}
        ts = rc.get("run_timestamp") if isinstance(rc, dict) else None
    output_artifact = apply_pipeline_provenance(output_artifact, run_timestamp=ts)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_artifact, f, ensure_ascii=False, indent=2)

    if graph_handoff_only:
        try:
            from m9.graph_arb.topology_diagnostic import quick_cycle_count

            _after_builder = quick_cycle_count(
                str(out_path),
                cycle_lengths=(2, 3, 4),
                lane="discovery",
            )
            metrics["graph_handoff_cycle_potential_after_builder"] = _after_builder
            output_artifact["graph_handoff_cycle_potential_after_builder"] = _after_builder
            output_artifact["bridge_source_metrics"] = metrics
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output_artifact, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            metrics["graph_handoff_topology_error"] = str(exc)[:200]
    return metrics
