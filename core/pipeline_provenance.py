"""Pipeline session provenance for M8→M9 orchestration.

``start.py`` sets ``ARBY_PIPELINE_SESSION_ID`` for every pipeline child step.
Artifact writers call :func:`apply_pipeline_provenance` so downstream truth
gates can bind a serial M8→M9 bundle to one session id.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

ENV_PIPELINE_SESSION_ID = "ARBY_PIPELINE_SESSION_ID"

__all__ = [
    "ENV_PIPELINE_SESSION_ID",
    "apply_pipeline_provenance",
    "new_pipeline_session_id",
    "pipeline_session_id",
    "stamp_run_context",
]


def new_pipeline_session_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pipeline_session_id() -> Optional[str]:
    raw = os.environ.get(ENV_PIPELINE_SESSION_ID, "").strip()
    return raw or None


def stamp_run_context(
    run_context: Optional[Dict[str, Any]] = None,
    *,
    run_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    rc = dict(run_context or {})
    if run_timestamp and not rc.get("run_timestamp"):
        rc["run_timestamp"] = run_timestamp
    sid = pipeline_session_id()
    if sid:
        rc["session_id"] = sid
    return rc


def apply_pipeline_provenance(
    artifact: Dict[str, Any],
    *,
    run_timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    out = dict(artifact)
    ts = run_timestamp or out.get("generated_at_utc")
    out["run_context"] = stamp_run_context(out.get("run_context"), run_timestamp=ts)
    sid = pipeline_session_id()
    if sid and not out.get("session_id"):
        out["session_id"] = sid
    return out
