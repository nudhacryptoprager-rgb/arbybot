"""Resolve batched-M8 streaming sentinel paths for pipeline subprocess commands."""
from __future__ import annotations

import os
from typing import Any, Optional

from core.pipeline_streaming import (
    StreamingBatchPaths,
    resolve_streaming_batch_paths,
)

STREAMING_TOKEN_SUBSET_SENTINEL = "__ARBY_STREAMING_TOKEN_SUBSET__"
STREAMING_M81_OUTPUT_SENTINEL = "__ARBY_STREAMING_M81_OUTPUT__"
STREAMING_M82_HINTS_SENTINEL = "__ARBY_STREAMING_M82_HINTS__"
STREAMING_M82_RADAR_SENTINEL = "__ARBY_STREAMING_M82_RADAR__"
STREAMING_M82_EXPANSION_SENTINEL = "__ARBY_STREAMING_M82_EXPANSION__"
STREAMING_M83_REGISTRY_SENTINEL = "__ARBY_STREAMING_M83_REGISTRY__"
STREAMING_M82_ACCEPTANCE_SENTINEL = "__ARBY_STREAMING_M82_ACCEPTANCE__"
STREAMING_BATCH_DIR_SENTINEL = "__ARBY_STREAMING_BATCH_DIR__"
STREAMING_UPSTREAM_GATE_SENTINEL = "__ARBY_STREAMING_UPSTREAM_GATE__"
STREAMING_SESSION_AGGREGATE_SENTINEL = "__ARBY_STREAMING_SESSION_AGGREGATE__"
ENV_STREAMING_FINAL_BATCH_INDEX = "ARBY_STREAMING_FINAL_BATCH_INDEX"

ROLLING_EXPANSION_PATH = "data/runs/_rolling/m8_cross_dex_expansion_latest.json"


def streaming_paths_for_step(step: dict[str, Any]) -> Optional[StreamingBatchPaths]:
    batch_index = step.get("streaming_batch_index")
    if batch_index is not None:
        return resolve_streaming_batch_paths(int(batch_index))
    if step.get("streaming_final_batch"):
        final_idx = int(os.environ.get(ENV_STREAMING_FINAL_BATCH_INDEX, "0") or "0")
        if final_idx > 0:
            return resolve_streaming_batch_paths(final_idx)
    return None


def resolve_streaming_step_cmd(step: dict[str, Any], cmd: list[str]) -> list[str]:
    paths = streaming_paths_for_step(step)
    if paths is None:
        return cmd
    resolved: list[str] = []
    for token in cmd:
        if token == STREAMING_TOKEN_SUBSET_SENTINEL:
            resolved.append(str(paths.token_subset))
        elif token == STREAMING_M81_OUTPUT_SENTINEL:
            resolved.append(str(paths.m81_output))
        elif token == STREAMING_M82_HINTS_SENTINEL:
            resolved.append(str(paths.m82_hints))
        elif token == STREAMING_M82_RADAR_SENTINEL:
            resolved.append(str(paths.m82_radar))
        elif token == STREAMING_M82_EXPANSION_SENTINEL:
            resolved.append(str(paths.m82_expansion))
        elif token == STREAMING_M83_REGISTRY_SENTINEL:
            resolved.append(str(paths.m83_registry))
        elif token == STREAMING_M82_ACCEPTANCE_SENTINEL:
            resolved.append(str(paths.m82_acceptance))
        elif token == STREAMING_BATCH_DIR_SENTINEL:
            resolved.append(str(paths.batch_dir))
        elif token == STREAMING_UPSTREAM_GATE_SENTINEL:
            resolved.append(str(paths.upstream_gate_output))
        elif token == STREAMING_SESSION_AGGREGATE_SENTINEL:
            from core.session_aggregate import session_aggregate_path

            resolved.append(str(session_aggregate_path(paths.session_id)))
        else:
            resolved.append(token)
    return resolved


def batched_final_truth_gate_args() -> list[str]:
    return [
        "--anchor",
        STREAMING_M81_OUTPUT_SENTINEL,
        "--hints",
        STREAMING_M82_HINTS_SENTINEL,
        "--expansion",
        STREAMING_M82_EXPANSION_SENTINEL,
        "--m8-3-registry",
        STREAMING_M83_REGISTRY_SENTINEL,
    ]


def batched_session_aggregate_bridge_args() -> list[str]:
    return [
        "--anchor",
        STREAMING_M81_OUTPUT_SENTINEL,
        "--expansion",
        STREAMING_M82_EXPANSION_SENTINEL,
        "--session-aggregate",
        STREAMING_SESSION_AGGREGATE_SENTINEL,
    ]


def batched_final_bridge_args() -> list[str]:
    return [
        "--anchor",
        STREAMING_M81_OUTPUT_SENTINEL,
        "--expansion",
        STREAMING_M82_EXPANSION_SENTINEL,
    ]


def batched_final_lane_acceptance_args(*, skip_shadow: bool = False) -> list[str]:
    cmd = [
        "--anchor",
        STREAMING_M81_OUTPUT_SENTINEL,
        "--expansion",
        STREAMING_M82_EXPANSION_SENTINEL,
        "--m8-2-report",
        STREAMING_M82_ACCEPTANCE_SENTINEL,
        "--m8-3-registry",
        STREAMING_M83_REGISTRY_SENTINEL,
    ]
    if skip_shadow:
        cmd.append("--skip-shadow")
    return cmd
