"""Batched M8 refresh pipeline helpers (core layer — no milestone imports).

``--streaming`` enables ``batched_m8_refresh``: repeated sniper→M8.1→M8.2→M8.3
per batch, then a single M9 admission pass on the final batch bundle.

M8 sniper coverage is limited to configured + adapter-supported DEXes in config;
expansion backlog may still track unsupported venues for later adapter work.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core.pipeline_provenance import ENV_PIPELINE_SESSION_ID

DEFAULT_SNIPER_BATCH_MINUTES = 15
DEFAULT_STREAMING_TOTAL_MINUTES = 45
DEFAULT_SNIPER_ARTIFACT = "data/runs/_rolling/new_pool_sniper_latest.json"
DEFAULT_M81_ROLLING = "data/runs/_rolling/m8_1_stable_anchor_latest.json"
# Batch-1 sniper step includes self-test replay (~12m) before the scan window.
DEFAULT_SNIPER_SELF_TEST_BUDGET_S = int(
    os.environ.get("ARBY_SNIPER_SELF_TEST_BUDGET_S", "900")
)
DEFAULT_SNIPER_STARTUP_GRACE_S = int(
    os.environ.get("ARBY_SNIPER_STARTUP_GRACE_S", "120")
)
_SNIPER_BATCH_TIMEOUT_FACTOR = float(
    os.environ.get("ARBY_SNIPER_BATCH_TIMEOUT_FACTOR", "1.47")
)

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


def resolve_sniper_batch_step_timeout_s(
    batch_minutes: int,
    *,
    batch_index: int = 1,
    timeout_config: Any = None,
) -> int:
    """Hard pipeline timeout for one sniper streaming batch (batched mode only).

    Batch 1 runs historical self-test before the scan window; batch 2+ skip
    self-test (checkpoint reuse) and only need scan duration + startup grace.
    """
    factor = _SNIPER_BATCH_TIMEOUT_FACTOR
    self_test_s = DEFAULT_SNIPER_SELF_TEST_BUDGET_S
    grace_s = DEFAULT_SNIPER_STARTUP_GRACE_S
    if timeout_config is not None:
        factor = float(getattr(timeout_config, "sniper_batch_timeout_factor", factor))
        self_test_s = int(getattr(timeout_config, "sniper_self_test_budget_s", self_test_s))
        grace_s = int(getattr(timeout_config, "sniper_startup_grace_s", grace_s))

    batch_s = max(5, int(batch_minutes or DEFAULT_SNIPER_BATCH_MINUTES)) * 60
    scan_budget_s = int(batch_s * factor)
    grace_s = max(0, grace_s)
    if int(batch_index) <= 1:
        return scan_budget_s + max(0, self_test_s) + grace_s
    return scan_budget_s + grace_s


def resolve_sniper_batch_wall_clock_s(duration_minutes: float) -> float:
    """In-process sniper deadline with buffer over the configured batch minutes."""
    base_s = max(0.1, float(duration_minutes)) * 60.0
    return base_s * 1.45


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
    m82_acceptance: Path
    upstream_gate_output: Path
    m82_checkpoint_radar: Path
    m82_checkpoint_verify: Path
    m82_secondary_subset: Path
    m82_secondary_staging: Path
    m82_checkpoint_secondary: Path
    m82_coingecko_subset: Path
    m82_coingecko_staging: Path
    m82_checkpoint_coingecko: Path


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
        m82_acceptance=batch_dir / "m8_2_acceptance_report.json",
        upstream_gate_output=batch_dir / "m8_m9_runtime_truth_gate_upstream.json",
        m82_checkpoint_radar=batch_dir / "m8_hint_refresh_checkpoint_ds_radar.json",
        m82_checkpoint_verify=batch_dir / "m8_hint_refresh_checkpoint_ds_verify.json",
        m82_secondary_subset=batch_dir / "m8_secondary_token_subset.json",
        m82_secondary_staging=batch_dir / "m8_secondary_hints_merge_staging.json",
        m82_checkpoint_secondary=batch_dir / "m8_hint_refresh_checkpoint_secondary.json",
        m82_coingecko_subset=batch_dir / "m8_coingecko_fallback_subset.json",
        m82_coingecko_staging=batch_dir / "m8_coingecko_hints_merge_staging.json",
        m82_checkpoint_coingecko=batch_dir / "m8_hint_refresh_checkpoint_cg.json",
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


def final_m82_acceptance_allows_shadow(*, session_id: Optional[str] = None) -> bool:
    """True when the final-batch M8.2 acceptance artifact authorizes M9 shadow."""
    final_idx = int(os.environ.get("ARBY_STREAMING_FINAL_BATCH_INDEX", "0") or "0")
    if final_idx <= 0:
        return True
    paths = resolve_streaming_batch_paths(final_idx, session_id=session_id)
    if not paths.m82_acceptance.is_file():
        return False
    try:
        doc = json.loads(paths.m82_acceptance.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if str(doc.get("goal_status") or "").upper() == "BLOCKED":
        return False
    return bool(doc.get("handoff_ready"))
