"""Batched M8 refresh pipeline helpers (core layer — no milestone imports).

``--streaming`` enables ``batched_m8_refresh``: repeated sniper→M8.1→M8.2→M8.3
per batch, then a single M9 admission pass on the final batch bundle.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core.pipeline_provenance import ENV_PIPELINE_SESSION_ID

DEFAULT_SNIPER_BATCH_MINUTES = 15
DEFAULT_STREAMING_TOTAL_MINUTES = 45
DEFAULT_SNIPER_ARTIFACT = "data/runs/_rolling/new_pool_sniper_latest.json"
DEFAULT_M81_ROLLING = "data/runs/_rolling/m8_1_stable_anchor_latest.json"

STREAMING_MANIFEST_PATH = Path("data/tmp/m8_streaming_batch_manifest_latest.json")
STREAMING_ROOT_DIR = Path("data/tmp/streaming_batches")
PIPELINE_MODE_BATCHED_M8_REFRESH = "batched_m8_refresh"


def batched_m8_refresh_mode(*, streaming: bool = False) -> str:
    return PIPELINE_MODE_BATCHED_M8_REFRESH if streaming else "standard_m8_m9"


def streaming_enabled(*, env: Optional[dict] = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get("ARBY_PIPELINE_STREAMING", "")).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def resolve_sniper_minutes(
    requested_minutes: int,
    *,
    streaming: bool = False,
    batch_minutes: int = DEFAULT_SNIPER_BATCH_MINUTES,
) -> int:
    req = max(1, int(requested_minutes or DEFAULT_STREAMING_TOTAL_MINUTES))
    if not streaming:
        return req
    return max(5, min(req, int(batch_minutes)))


def resolve_streaming_batches(
    total_minutes: int,
    *,
    batch_minutes: int = DEFAULT_SNIPER_BATCH_MINUTES,
) -> List[int]:
    total = max(1, int(total_minutes))
    batch = max(5, int(batch_minutes))
    batches: List[int] = []
    remaining = total
    while remaining > 0:
        chunk = min(batch, remaining)
        batches.append(chunk)
        remaining -= chunk
    return batches or [batch]


def sanitize_session_id(session_id: str) -> str:
    sid = str(session_id or "").strip()
    if not sid:
        return "unknown_session"
    return (
        sid.replace(":", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
    )


@dataclass(frozen=True)
class StreamingBatchPaths:
    session_id: str
    batch_index: int
    batch_dir: Path
    manifest: Path
    token_subset: Path
    m81_output: Path
    m82_radar: Path
    m82_hints: Path
    m82_expansion: Path
    m83_registry: Path
    upstream_gate_output: Path


def resolve_streaming_batch_paths(
    batch_index: int,
    *,
    session_id: Optional[str] = None,
) -> StreamingBatchPaths:
    sid = str(session_id or os.environ.get(ENV_PIPELINE_SESSION_ID, "")).strip()
    safe_sid = sanitize_session_id(sid)
    batch_dir = STREAMING_ROOT_DIR / safe_sid / f"batch_{int(batch_index)}"
    return StreamingBatchPaths(
        session_id=sid,
        batch_index=int(batch_index),
        batch_dir=batch_dir,
        manifest=batch_dir / "manifest.json",
        token_subset=batch_dir / "token_subset.json",
        m81_output=batch_dir / "m8_1_stable_anchor.json",
        m82_radar=batch_dir / "m8_radar_pool_candidates.json",
        m82_hints=batch_dir / "m8_external_pool_hints.json",
        m82_expansion=batch_dir / "m8_cross_dex_expansion.json",
        m83_registry=batch_dir / "m8_3_token_metadata_registry.json",
        upstream_gate_output=batch_dir / "m8_m9_runtime_truth_gate_upstream.json",
    )


def m81_streaming_cli_args(*, batch_index: int) -> List[str]:
    """Runtime-resolved paths via --streaming-batch-index in M8.1 CLI."""
    return [
        "--probe-mode",
        "fresh_delta",
        "--streaming-batch-index",
        str(int(batch_index)),
        "--publish-rolling",
    ]
