"""Streaming M8→M9 batch scheduling helpers (core layer — no milestone imports)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

DEFAULT_SNIPER_BATCH_MINUTES = 15
DEFAULT_STREAMING_TOTAL_MINUTES = 45
DEFAULT_SNIPER_ARTIFACT = "data/runs/_rolling/new_pool_sniper_latest.json"

STREAMING_MANIFEST_PATH = Path("data/tmp/m8_streaming_batch_manifest_latest.json")
STREAMING_MANIFEST_DIR = Path("data/tmp/streaming_batches")
STREAMING_SUBSET_DIR = Path("data/tmp/streaming_subsets")


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
    """Cap sniper duration per batch when streaming is enabled."""
    req = max(1, int(requested_minutes or DEFAULT_STREAMING_TOTAL_MINUTES))
    if not streaming:
        return req
    return max(5, min(req, int(batch_minutes)))


def resolve_streaming_batches(
    total_minutes: int,
    *,
    batch_minutes: int = DEFAULT_SNIPER_BATCH_MINUTES,
) -> List[int]:
    """Split a long sniper window into sessioned batch durations."""
    total = max(1, int(total_minutes))
    batch = max(5, int(batch_minutes))
    batches: List[int] = []
    remaining = total
    while remaining > 0:
        chunk = min(batch, remaining)
        batches.append(chunk)
        remaining -= chunk
    return batches or [batch]


def streaming_batch_manifest_path(batch_index: int) -> Path:
    return STREAMING_MANIFEST_DIR / f"m8_streaming_batch_manifest_batch_{int(batch_index)}.json"


def streaming_token_subset_path(batch_index: int) -> Path:
    return STREAMING_SUBSET_DIR / f"m8_streaming_token_subset_batch_{int(batch_index)}.json"


def m81_streaming_cli_args(*, batch_index: int) -> List[str]:
    """CLI flags for M8.1 when streaming pipeline is active."""
    manifest = streaming_batch_manifest_path(batch_index)
    subset = streaming_token_subset_path(batch_index)
    return [
        "--probe-mode",
        "fresh_delta",
        "--token-subset-file",
        str(subset),
        "--streaming-manifest",
        str(manifest),
    ]
