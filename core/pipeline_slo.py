"""Per-step SLO telemetry for long M8→M9 pipelines."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_SLO_PATH = Path("data/tmp/pipeline_slo_latest.json")
_BATCH_STEP_RE = re.compile(r".*_batch_(\d+)$")


def record_step_slo(
    records: List[Dict[str, Any]],
    *,
    step_name: str,
    duration_s: float,
    queue_delay_s: float = 0.0,
    rpc_wait_s: Optional[float] = None,
    provider_errors: int = 0,
    cache_hits: int = 0,
    cache_misses: int = 0,
    routes_per_s: Optional[float] = None,
    status: str = "completed",
    failure_reason: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    row: Dict[str, Any] = {
        "step": step_name,
        "status": status,
        "duration_s": round(float(duration_s), 2),
        "queue_delay_s": round(float(queue_delay_s), 2),
        "provider_errors": int(provider_errors),
        "cache_hits": int(cache_hits),
        "cache_misses": int(cache_misses),
        "completed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if rpc_wait_s is not None:
        row["rpc_wait_s"] = round(float(rpc_wait_s), 2)
    if routes_per_s is not None:
        row["routes_per_s"] = round(float(routes_per_s), 3)
    if failure_reason:
        row["failure_reason"] = str(failure_reason)
    if extra:
        row.update(extra)
    records.append(row)


def _aggregate_batch_work_duration(records: List[Dict[str, Any]]) -> Dict[str, float]:
    """Sum per-step ``duration_s`` for each batch index (work time, not wall-clock)."""
    batch_totals: Dict[str, float] = {}
    for row in records:
        match = _BATCH_STEP_RE.match(str(row.get("step") or ""))
        if not match:
            continue
        batch_key = match.group(1)
        batch_totals[batch_key] = round(
            batch_totals.get(batch_key, 0.0) + float(row.get("duration_s") or 0.0),
            2,
        )
    return batch_totals


class PipelineSloTracker:
    """Accumulates step SLO rows and writes a rolling artifact."""

    def __init__(self, path: Path = DEFAULT_SLO_PATH) -> None:
        self.path = path
        self.records: List[Dict[str, Any]] = []
        self._step_queue_t0 = time.monotonic()
        self.pipeline_t0 = time.monotonic()
        self.pipeline_status = "completed"
        self.failure_step: Optional[str] = None
        self.failure_reason: Optional[str] = None
        self.resumed_from_step: Optional[str] = None

    def set_resume_context(self, resume_from: Optional[str]) -> None:
        self.resumed_from_step = str(resume_from).strip() if resume_from else None

    def begin_step(self) -> float:
        now = time.monotonic()
        delay = max(0.0, now - self._step_queue_t0)
        self._step_queue_t0 = now
        return delay

    def end_step(
        self,
        step_name: str,
        step_t0: float,
        queue_delay_s: float,
        *,
        status: str = "completed",
        failure_reason: Optional[str] = None,
        rpc_wait_s: Optional[float] = None,
        provider_errors: int = 0,
        cache_hits: int = 0,
        cache_misses: int = 0,
        routes_per_s: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        duration = max(0.0, time.monotonic() - step_t0)
        record_step_slo(
            self.records,
            step_name=step_name,
            duration_s=duration,
            queue_delay_s=queue_delay_s,
            status=status,
            failure_reason=failure_reason,
            rpc_wait_s=rpc_wait_s,
            provider_errors=provider_errors,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            routes_per_s=routes_per_s,
            extra=extra,
        )
        self._step_queue_t0 = time.monotonic()

    def record_skipped(self, step_name: str, *, reason: str) -> None:
        record_step_slo(
            self.records,
            step_name=step_name,
            duration_s=0.0,
            queue_delay_s=0.0,
            status="skipped",
            failure_reason=reason,
        )

    def mark_failed(self, step_name: str, reason: str) -> None:
        self.pipeline_status = "failed"
        self.failure_step = step_name
        self.failure_reason = reason

    def write(
        self,
        *,
        session_id: Optional[str] = None,
        pipeline_mode: Optional[str] = None,
        resumed_from_step: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "schema_version": "pipeline_slo.4",
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": session_id,
            "pipeline_mode": pipeline_mode,
            "pipeline_status": self.pipeline_status,
            "failure_step": self.failure_step,
            "failure_reason": self.failure_reason,
            "resumed_from_step": resumed_from_step or self.resumed_from_step,
            "session_wall_clock_s": round(time.monotonic() - self.pipeline_t0, 2),
            "batch_work_duration_s": _aggregate_batch_work_duration(self.records),
            "steps": list(self.records),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
