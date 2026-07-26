#!/usr/bin/env python3
"""
start.py - Multi-chain time-bounded online scan orchestrator (thin).

R33: Extraction — domain logic moved to:
  - strategy/run_artifact_extract.py  (artifact I/O)
  - strategy/chain_stats.py           (per-chain aggregation, classification, guardrails)
  - strategy/long_scan_summary.py     (build_summary, frontier ranking, profit truth)
  - strategy/rolling_outputs.py       (print/write summary, hot_loop, micro-requote)

This file retains ONLY:
  - Config introspection (read_config_meta, is_primary_rolling_config)
  - Child process runner (run_gate_once)
  - CLI (parse_args, resolve_configs, main)
  - Scan loop orchestrator (_run_scan_loop, _run_one_chain, _warn_missing_chains)
  - Backward-compatible re-exports for existing `from start import X` consumers
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from application.checkpoint_store import (  # noqa: F401
    CheckpointStore,
    done_fingerprint_matches,
    fingerprint_paths,
    write_done_record,
)
from application.pipeline_stage import PipelineStage, StageResult  # noqa: F401
from application.stage_runner import run_stage_subprocess, run_with_retries  # noqa: F401
from core.batch_path_resolver import (
    ENV_STREAMING_FINAL_BATCH_INDEX,
    STREAMING_BATCH_DIR_SENTINEL,
    STREAMING_M81_OUTPUT_SENTINEL,
    STREAMING_M82_ACCEPTANCE_SENTINEL,
    STREAMING_M82_EXPANSION_SENTINEL,
    STREAMING_M82_HINTS_SENTINEL,
    STREAMING_M82_RADAR_SENTINEL,
    STREAMING_M83_REGISTRY_SENTINEL,
    STREAMING_TOKEN_SUBSET_SENTINEL,
    batched_final_bridge_args,
    batched_final_lane_acceptance_args,
    batched_final_truth_gate_args,
    resolve_streaming_step_cmd,
)
from core.pipeline_provenance import (  # noqa: F401
    ENV_PIPELINE_SESSION_ID,
    new_pipeline_session_id,
)
from core.pipeline_runtime import run_streaming_batch_upstream_gate
from core.pipeline_slo import PipelineSloTracker
from core.pipeline_streaming import (
    batched_m8_refresh_mode,
    final_m82_acceptance_allows_shadow,
    m81_streaming_cli_args,
    resolve_sniper_minutes,
    resolve_streaming_batch_paths,
    resolve_streaming_batches,
    streaming_enabled,
)
from m8.discovery.streaming_handoff import write_streaming_batch_manifest
from strategy.chain_stats import (  # noqa: F401
    SANE_ROUNDTRIP_PNL_BPS_MAX,
    SANE_ROUNDTRIP_PNL_BPS_MIN,
    _compute_blocker_evidence,
    check_guardrails,
    classify_run,
    new_chain_stats,
    update_chain_stats,
)
from strategy.long_scan_summary import (  # noqa: F401
    _compute_frontier_ranking,
    _compute_kpi_separation,
    _compute_median,
    _compute_per_chain_drift_summary,
    _compute_profit_truth_summary,
    _compute_truth_path_alignment,
    _compute_universe_split,
    _roundtrip_accounting_is_sane,
    build_summary,
    classify_chain_profit_state,
)
from strategy.rolling_outputs import (  # noqa: F401
    FULL_SWEEP_INTERVAL,
    HOT_LOOP_LATEST,
    LIVE_STREAM_MAX_EVENTS,
    _micro_requote_hot_pairs,
    _serialize_live_stream,
    print_summary,
    write_hot_loop_snapshot,
    write_summary_file,
)

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility (existing tests import from start)
# ---------------------------------------------------------------------------
from strategy.run_artifact_extract import (  # noqa: F401
    CI_M5_DIR_RE,
    delete_if_empty_run_dir,
    extract_gate_result,
    extract_run_summary,
    extract_scan_stats,
    extract_truth_report,
    prune_run_dirs,
)
from strategy.run_artifact_extract import (
    validate_chain_id_match as _validate_chain_id_match,
)

# ---------------------------------------------------------------------------
# Orchestrator constants
# ---------------------------------------------------------------------------
RUNS_DIR = Path("data") / "runs"
CI_GATE = Path("scripts") / "ci_m5_0_gate.py"
HOT_PAIRS_CACHE_DIR = Path("data") / "cache"
RUN_DIR_RE = re.compile(r"^\[ONLINE\] RunDir:\s*(.+)\s*$")
PRODUCTION_BRIDGE = "data/tmp/m9_bridge_inventory_production_latest.json"
CAPACITY_DIAGNOSTIC = "data/tmp/m9_capacity_cycle_diagnostic_latest.json"
M8_SNIPER_STREAMING_CHECKPOINT = "data/tmp/m8_sniper_streaming_checkpoint.json"
M9_SHADOW_ARTIFACT = "data/tmp/m9_graph_handoff_quote_validation_10m.json"
M9_PATIENT_SHADOW_ARTIFACT = "data/tmp/m9_patient_lane_shadow_10m.json"
M9_RCA_ARTIFACT = "data/tmp/m9_quote_lane_rca_graph_handoff_latest.json"
PIPELINE_STEP_MARKERS_DIR = Path("data/tmp/start_pipeline_steps")
ALWAYS_RERUN_PIPELINE_STEPS = frozenset(
    {
        "m8_m9_runtime_truth_gate_upstream",
        "m8_m9_runtime_truth_gate_bundle",
        "m8_m9_runtime_truth_gate_post_depth",
    }
)
UPSTREAM_ROLLING_ARTIFACTS: tuple[str, ...] = (
    "data/runs/_rolling/new_pool_sniper_latest.json",
    "data/runs/_rolling/m8_1_stable_anchor_latest.json",
    "data/runs/_rolling/m8_external_pool_hints_latest.json",
    "data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
)
M83_UPSTREAM_INVALIDATING_STEPS = frozenset(
    {
        "m8_sniper_acceptance",
        "m8_1_stable_anchor",
        "m8_1_stable_anchor_fresh_delta",
        "m8_event_stream_lane",
        "m8_onchain_factory_mirror_scan",
        "m8_mirror_discovery_recall",
        "m8_2_radar_two_phase",
        "m8_2_cross_dex_expand",
        "m8_3_registry_refresh",
    }
)
POST_BRIDGE_FINGERPRINT_PREFIXES: tuple[str, ...] = (
    "m9_enrich_",
    "m9_topology_",
    "m9_capacity_",
    "m9_shadow_",
    "m9_patient_",
    "gate_capacity_",
    "m9_lane_",
    "m8_m9_runtime_truth_gate_bundle",
)
PIPELINE_CURRENT_PATH = Path("data/tmp/start_pipeline_current.json")
M81_PROBE_METRICS_PATH = Path("data/tmp/m8_1_probe_metrics_latest.json")
_CURRENT_PIPELINE_ARGS: argparse.Namespace | None = None
PENDING_1_TO_2_QUEUE_PATH = Path("data/tmp/m8_time_to_mirror_pending_queue_latest.json")
WATCHLIST_PATH = Path("data/tmp/m8_token_watchlist_latest.json")
MIRROR_QUOTE_REPROBE_CHECKPOINT_PATH = "data/tmp/m8_mirror_quote_reprobe_progress.json"
MIRROR_SECOND_POOL_VERIFY_CHECKPOINT_PATH = (
    "data/tmp/m8_second_pool_verify_progress.json"
)
# Legacy alias kept for tests/docs that reference the old single-checkpoint name.
MIRROR_QUOTE_CHECKPOINT_PATH = MIRROR_QUOTE_REPROBE_CHECKPOINT_PATH
TIME_TO_MIRROR_SLA_PATH = Path("data/tmp/m8_time_to_mirror_sla_latest.json")
M9_TTM_NARROW_BRIDGE = "data/tmp/m9_bridge_time_to_mirror_narrow_latest.json"
M9_TTM_NARROW_DEPTH_BRIDGE = "data/tmp/m9_bridge_time_to_mirror_narrow_depth_latest.json"
M9_TTM_NARROW_CAPACITY_DIAGNOSTIC = (
    "data/tmp/m9_time_to_mirror_narrow_capacity_diagnostic_latest.json"
)
M9_TTM_NARROW_SHADOW_ARTIFACT = "data/tmp/m9_time_to_mirror_narrow_shadow_10m.json"
EXTERNAL_HINTS_ROLLING = "data/runs/_rolling/m8_external_pool_hints_latest.json"
TIME_TO_MIRROR_EXPAND_SUBSET = "data/tmp/m8_time_to_mirror_expand_subset.json"
SECOND_POOL_TRANSITION_SUBSET = "data/tmp/m8_second_pool_transition_subset.json"
DEFAULT_STEP_TIMEOUT_S = 7200
DEFAULT_RADAR_STEP_TIMEOUT_S = 7200
# Per-provider HTTP timeout passed to m8_radar secondary/coingecko phases (seconds).
DEFAULT_RADAR_SECONDARY_PROVIDER_TIMEOUT_S = 45
DEFAULT_HEARTBEAT_STALE_MINUTES = 15
TIME_TO_MIRROR_STEP_TIMINGS_PATH = Path(
    "data/tmp/m8_time_to_mirror_step_timings_latest.json"
)
EVENT_STREAM_LANE_ARTIFACT = Path("data/tmp/m8_event_stream_lane_latest.json")
MIRROR_DISCOVERY_RECALL_PATH = Path("data/tmp/m8_mirror_discovery_recall_latest.json")
MIRROR_RECALL_WIDE_PATH = Path("data/tmp/m8_mirror_recall_wide_latest.json")
EXISTENCE_VERIFY_SUBSET_PATH = Path("data/tmp/m8_existence_verify_subset.json")
RECALL_SLA_MAX_S = 180
VERIFY_SLA_MAX_S = 900
# Downstream verify steps invalidated after each fresh recall run.
RECALL_DOWNSTREAM_MARKER_STEPS: tuple[str, ...] = (
    "m8_onchain_factory_mirror_scan",
    "m8_1_stable_anchor_fresh_delta",
    "m8_mirror_selection_pass",
    "gate_selection_verified_fresh",
    "m8_2_cross_dex_expand",
    "gate_verify_sla",
    "m8_time_to_mirror_pending_queue_post_expand",
    "m8_second_pool_transition_subset",
    "m8_mirror_quote_reprobe",
    "m8_second_pool_verify",
)
SELECTION_FRESH_GATED_STEPS: frozenset[str] = frozenset(
    {
        "m8_2_cross_dex_expand",
        "m8_3_registry_refresh",
        "gate_negative_cache_stats",
        "m8_3_acceptance_strict",
        "gate_m8_3_acceptance_reached",
    }
)
PATIENT_LANE_DIAGNOSTIC_PATH = Path("data/tmp/m8_patient_lane_diagnostics_latest.json")
HOT_LOOP_EVENT_INTERVAL_S = 300


def _fresh_quote_ready_count() -> int:
    """Event-trigger gate: M9 depth/capacity only when fresh long-tail quote-ready > 0."""
    for path in (Path(M9_TTM_NARROW_BRIDGE), TIME_TO_MIRROR_SLA_PATH):
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            count = int(doc.get("fresh_long_tail_quote_ready_tokens") or 0)
            if count > 0:
                return count
            funnel = doc.get("mirror_yield_funnel") or {}
            count = int(funnel.get("fresh_long_tail_quote_ready_tokens") or 0)
            if count > 0:
                return count
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return 0


def _resolve_m9_effective_inventory_materialize_env() -> dict[str, str]:
    """Env for the single-writer effective inventory materialization stage."""
    from m9.graph_arb.effective_inventory import (
        ENV_ALLOW_LIVE_MATERIALIZE,
        resolve_effective_inventory_path,
    )

    return {
        "ARBY_M9_EFFECTIVE_INVENTORY_PATH": resolve_effective_inventory_path(),
        ENV_ALLOW_LIVE_MATERIALIZE: "1",
    }


def _resolve_m9_shadow_step_env() -> dict[str, str]:
    """Capacity-prioritized shadow with explicit lane mode for economics verdict."""
    from m9.graph_arb.effective_inventory import (
        ENV_ALLOW_LIVE_MATERIALIZE,
        resolve_effective_inventory_path,
    )

    fresh = _fresh_quote_ready_count()
    env = {
        "ARBY_M9_CAPACITY_PRIORITIZED": "1",
        "ARBY_M9_CYCLE_LENGTHS": "2,3,4",
        "ARBY_M9_EFFECTIVE_INVENTORY_PATH": resolve_effective_inventory_path(),
        ENV_ALLOW_LIVE_MATERIALIZE: "0",
    }
    if fresh > 0:
        env["ARBY_M9_SHADOW_LANE_MODE"] = "long_tail_target"
    else:
        env["ARBY_M9_SHADOW_LANE_MODE"] = "broad_graph_diagnostic"
    return env


def _target_m9_allowed_from_bridge() -> bool:
    """Hydrate M9 depth/capacity allowance from narrow bridge + quote-ready gate."""
    if _fresh_quote_ready_count() <= 0:
        return False
    path = Path(M9_TTM_NARROW_BRIDGE)
    if not path.is_file():
        return False
    try:
        from m9.graph_arb.narrow_universe_gate import target_narrow_universe_gate_blocked

        bridge = json.loads(path.read_text(encoding="utf-8"))
        blocked, _ = target_narrow_universe_gate_blocked(bridge)
        return not blocked
    except (OSError, json.JSONDecodeError, ImportError):
        return False


# Hot-path SLA: minutes-scale lane, not multi-hour wide recall.
TIME_TO_MIRROR_HOT_SLA_S = 900
HOT_LANE_PROFILES: dict[str, dict[str, Any]] = {
    "hot_delta": {
        "max_radar_tokens": 50,
        "skip_secondary": True,
        "verify_subset_max": 30,
        "m81_duration_minutes": 2.0,
        "radar_step_timeout_s": 1200,
        "expand_step_timeout_s": 1800,
        "hot_sla_max_s": TIME_TO_MIRROR_HOT_SLA_S,
        "hot_expand": True,
        "m83_max_onchain_probes": 120,
        "event_poll_max_blocks": 500,
        "hot_loop_event_interval_s": HOT_LOOP_EVENT_INTERVAL_S,
    },
    "warm_recall": {
        "max_radar_tokens": 150,
        "skip_secondary": True,
        "verify_subset_max": 50,
        "m81_duration_minutes": 3.0,
        "radar_step_timeout_s": 2400,
        "expand_step_timeout_s": 3600,
        "hot_sla_max_s": 1800,
        "hot_expand": True,
        "m83_max_onchain_probes": 250,
        "event_poll_max_blocks": 1500,
        "hot_loop_event_interval_s": HOT_LOOP_EVENT_INTERVAL_S * 2,
    },
    "mirror_recall": {
        "max_radar_tokens": 753,
        "skip_secondary": True,
        "verify_subset_max": 0,
        "m81_duration_minutes": 2.0,
        "radar_step_timeout_s": 1200,
        "expand_step_timeout_s": 3600,
        "hot_sla_max_s": 3600,
        "recall_sla_max_s": 180,
        "verify_sla_max_s": 900,
        "hot_expand": True,
        "mirror_discovery_max_recall": True,
        "token_pool_universe": True,
        "graph_closure_only": True,
        "defer_heavy_verify": True,
        "m83_max_onchain_probes": 120,
        "event_poll_max_blocks": 800,
        "hot_loop_event_interval_s": HOT_LOOP_EVENT_INTERVAL_S * 2,
    },
    "mirror_recall_fast": {
        "max_radar_tokens": 753,
        "skip_secondary": True,
        "verify_subset_max": 0,
        "hot_sla_max_s": 180,
        "recall_sla_max_s": 180,
        "verify_sla_max_s": 900,
        "hot_expand": True,
        "mirror_discovery_max_recall": True,
        "recall_only": True,
        "token_pool_universe": True,
        "graph_closure_only": True,
        "anchor_constrained": True,
        "run_quote_smoke": True,
        "quote_smoke_max_candidates": 25,
        "use_dexscreener": False,
        "defer_heavy_verify": True,
    },
    "mirror_recall_wide": {
        "max_radar_tokens": 753,
        "skip_secondary": True,
        "verify_subset_max": 0,
        "hot_sla_max_s": 600,
        "recall_sla_max_s": 300,
        "verify_sla_max_s": 900,
        "hot_expand": True,
        "mirror_discovery_max_recall": True,
        "recall_only": True,
        "token_pool_universe": True,
        "graph_closure_only": True,
        "anchor_constrained": True,
        "run_quote_smoke": True,
        "quote_smoke_max_candidates": 25,
        "use_dexscreener": True,
        "defer_heavy_verify": True,
    },
    "audit_full": {
        "max_radar_tokens": 753,
        "skip_secondary": False,
        "verify_subset_max": 50,
        "m81_duration_minutes": 5.0,
        "radar_step_timeout_s": DEFAULT_RADAR_STEP_TIMEOUT_S,
        "expand_step_timeout_s": DEFAULT_STEP_TIMEOUT_S,
        "hot_sla_max_s": 0,
        "hot_expand": False,
        "m83_max_onchain_probes": 500,
    },
}
PATIENT_LANE_ECONOMICS_PROFILE = "diagnostic_near_econ"
CROSS_CHAIN_RESEARCH_BLOCKED_EXIT = 2
# Quiet child steps may refresh these checkpoint files without stdout.
STEP_QUIET_CHECKPOINTS: dict[str, tuple[str, ...]] = {
    "m8_onchain_factory_mirror_scan": (
        "data/tmp/m8_onchain_factory_scan_latest.json",
    ),
    "m8_event_stream_lane": (
        "data/tmp/m8_event_stream_lane_latest.json",
    ),
    "m8_mirror_discovery_recall": (
        "data/tmp/m8_mirror_discovery_recall_latest.json",
    ),
    "m8_2_radar_two_phase": (
        "data/tmp/m8_hint_refresh_checkpoint_ds_radar.json",
        "data/tmp/m8_hint_refresh_checkpoint_ds_verify.json",
        "data/tmp/m8_hint_refresh_checkpoint_secondary.json",
        "data/tmp/m8_hint_refresh_checkpoint_cg.json",
    ),
    "m8_2_cross_dex_expand": ("data/tmp/m8_cross_dex_expand_progress.json",),
    "m8_mirror_quote_reprobe": (MIRROR_QUOTE_REPROBE_CHECKPOINT_PATH,),
    "m8_second_pool_verify": (MIRROR_SECOND_POOL_VERIFY_CHECKPOINT_PATH,),
    "m8_3_registry_refresh": (
        "data/tmp/m8_3_token_metadata_registry_refresh_progress.json",
    ),
}
_STREAMING_BATCH_STEP_RE = re.compile(
    r"^m8_(?:sniper_acceptance|streaming_batch_manifest|1_stable_anchor|"
    r"2_radar_two_phase|2_cross_dex_expand|3_registry_refresh|"
    r"m9_runtime_truth_gate_upstream)_batch_(\d+)$"
)

RESUME_FROM_FIRST_STEP: dict[str, str] = {
    "m8_2": "m8_2_radar_two_phase",
    "m8_2_radar": "m8_2_radar_two_phase",
    "m8_2_batch_1": "m8_2_radar_two_phase_batch_1",
    "m8_onchain_factory_mirror_scan": "m8_onchain_factory_mirror_scan",
    "m8_2_expand": "m8_2_cross_dex_expand",
    "m8_mirror_quote_reprobe": "m8_mirror_quote_reprobe",
    "m8_second_pool_verify": "m8_second_pool_verify",
    "m8_2_acceptance": "m8_2_acceptance_strict",
    "m8_3": "m8_3_registry_refresh",
    "m9": "m9_curve_discovery",
    "m9_capacity": "m9_capacity_diagnostic",
}

# R28.16: Phase event protocol — matches ARBY_PHASE: prefix from run_scan_real.py
PHASE_LINE_PREFIX = "ARBY_PHASE:"

# -- config introspection -------------------------------------------------


def read_config_meta(config_path: str) -> dict[str, Any]:
    """Return chain/run_kind from a YAML config without importing strategy code."""
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    return {
        "chain": data.get("chain", "unknown"),
        "chain_id": data.get("chain_id"),
        "run_kind": data.get("run_kind", "NORMAL"),
        "blocker_classification": data.get("blocker_classification"),
        "blocker_reason": data.get("blocker_reason"),
    }


def is_primary_rolling_config(meta: dict[str, Any]) -> bool:
    return meta["run_kind"] == "NORMAL"


# -- child process -------------------------------------------------------


def run_gate_once(
    config: str,
    cycles: int,
    prune_keep: int,
    sleep_seconds: int,
    refresh_rolling: bool,
    timeout_seconds: int,
    line_prefix: str = "",
    extra_env: dict[str, str] | None = None,
    phase_callback: Any = None,
) -> tuple[int, Path | None]:
    """Run ci_m5_0_gate.py once; return (exit_code, runDir).

    phase_callback: if provided, called with dict for each ARBY_PHASE: line
    emitted by the child process (see strategy/jobs/run_scan_real.py).
    """
    cmd = [
        sys.executable,
        str(CI_GATE),
        "--online",
        "--config",
        config,
        "--cycles",
        str(cycles),
        "--prune-keep",
        str(prune_keep),
        "--sleep-seconds",
        str(sleep_seconds),
    ]
    if refresh_rolling:
        cmd += ["--refresh-rolling", "--refresh-rolling-strict"]

    # R28.11: Thread extra env vars to subprocess (e.g. ARBY_HOT_PAIRS_FILE)
    env = None
    if extra_env:
        import os as _os
        env = _os.environ.copy()
        env.update(extra_env)

    run_dir: Path | None = None
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    assert proc.stdout is not None

    try:
        start = time.monotonic()
        for line in proc.stdout:
            stripped = line.strip()
            # R28.16: Parse phase event lines from child process
            if stripped.startswith(PHASE_LINE_PREFIX) and phase_callback is not None:
                try:
                    phase_data = json.loads(stripped[len(PHASE_LINE_PREFIX):])
                    phase_callback(phase_data)
                except Exception:
                    pass  # Malformed phase line — ignore silently
            # R28.9: Prefix worker lines for log readability
            if line_prefix:
                sys.stdout.write(f"{line_prefix} {line}")
            else:
                sys.stdout.write(line)
            m = RUN_DIR_RE.match(stripped)
            if m:
                run_dir = Path(m.group(1).strip())
            if timeout_seconds > 0 and (time.monotonic() - start) > timeout_seconds:
                proc.kill()
                print(f"[TIMEOUT] Child killed after {timeout_seconds}s")
                break
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = 3
    except Exception:
        proc.kill()
        rc = 3

    return rc, run_dir


def _py_cmd(*parts: str) -> list[str]:
    return [sys.executable, *parts]


def _productive_rpc_cmd(*parts: str) -> list[str]:
    """Run a child command under the canonical productive RPC bootstrap."""
    return [
        sys.executable,
        "scripts/bootstrap_productive_rpc_env.py",
        "--",
        sys.executable,
        *parts,
    ]


def _checkpoint_store() -> CheckpointStore:
    """Control-plane checkpoint store over the current markers dir.

    Constructed lazily so tests can monkeypatch PIPELINE_STEP_MARKERS_DIR.
    """
    return CheckpointStore(PIPELINE_STEP_MARKERS_DIR)


def _step_marker_paths(
    step_name: str,
    *,
    pipeline_mode: str | None = None,
) -> tuple[Path, Path]:
    return _checkpoint_store().marker_paths(step_name, pipeline_mode=pipeline_mode)


def _clear_stale_fail_markers(pipeline_mode: str, step_names: list[str]) -> int:
    """Drop prior .fail markers for this mode/plan so aborted runs cannot block reruns."""
    return _checkpoint_store().clear_fail_markers(pipeline_mode, step_names)


def _clear_recall_downstream_markers(pipeline_mode: str) -> int:
    """Drop downstream verify markers after a fresh recall so resume reruns verify."""
    return _checkpoint_store().clear_markers(pipeline_mode, RECALL_DOWNSTREAM_MARKER_STEPS)


def _upstream_artifacts_fingerprint() -> str:
    return fingerprint_paths(Path(p) for p in UPSTREAM_ROLLING_ARTIFACTS)


def _bundle_artifacts_fingerprint() -> str:
    paths = list(UPSTREAM_ROLLING_ARTIFACTS) + [PRODUCTION_BRIDGE]
    return fingerprint_paths(Path(p) for p in paths)


def _streaming_batch_index_from_step(step_name: str) -> int | None:
    match = _STREAMING_BATCH_STEP_RE.match(step_name)
    if not match:
        return None
    return int(match.group(1))


def _streaming_batch_manifest_fingerprint(batch_index: int) -> str | None:
    session_id = os.environ.get(ENV_PIPELINE_SESSION_ID, "").strip()
    if not session_id:
        return None
    manifest_path = resolve_streaming_batch_paths(
        batch_index,
        session_id=session_id,
    ).manifest
    if manifest_path.is_file():
        return fingerprint_paths([manifest_path])
    return None


def _pipeline_step_fingerprint(step_name: str) -> str:
    if step_name in ALWAYS_RERUN_PIPELINE_STEPS:
        return ""
    batch_index = _streaming_batch_index_from_step(step_name)
    if batch_index is not None:
        batch_fp = _streaming_batch_manifest_fingerprint(batch_index)
        if batch_fp is not None:
            return batch_fp
    if step_name == "m9_bridge_production" or any(
        step_name.startswith(prefix) for prefix in POST_BRIDGE_FINGERPRINT_PREFIXES
    ):
        return _bundle_artifacts_fingerprint()
    return _upstream_artifacts_fingerprint()


def _should_skip_done_marker(
    step_name: str,
    done_marker: Path,
    *,
    force_rerun: bool,
) -> bool:
    if force_rerun or step_name in ALWAYS_RERUN_PIPELINE_STEPS:
        return False
    if not done_marker.exists():
        return False
    expected = _pipeline_step_fingerprint(step_name)
    return done_fingerprint_matches(done_marker, expected)


def _invalidate_truth_gate_markers(
    pipeline_mode: str,
    *,
    upstream: bool = True,
    bundle: bool = True,
) -> int:
    steps: list[str] = []
    if upstream:
        steps.append("m8_m9_runtime_truth_gate_upstream")
    if bundle:
        steps.append("m8_m9_runtime_truth_gate_bundle")
    return _checkpoint_store().clear_markers(pipeline_mode, steps)


def _checkpoint_activity_since(step_name: str, since_wall_ts: float) -> bool:
    """True when a watched checkpoint file was touched after the step started."""
    return CheckpointStore.checkpoint_activity_since(
        STEP_QUIET_CHECKPOINTS.get(step_name, ()),
        since_wall_ts,
    )


def patient_lane_shadow_env() -> dict[str, str]:
    """Canonical patient-lane runner env (diagnostic sizing, no profit claim)."""
    return {
        "ARBY_M9_CYCLE_LENGTHS": "2,3,4",
        "ARBY_M9_ECONOMICS_PROFILE": PATIENT_LANE_ECONOMICS_PROFILE,
        "ARBY_M9_PATIENT_LANE": "1",
        "ARBY_M9_PROFIT_CLAIM_ALLOWED": "0",
        "ARBY_BRIDGE_ARTIFACT_MODE": "exploration_debug",
    }


def _classify_step_rpc_policy(cmd: list[str]) -> str:
    joined = " ".join(cmd)
    if "bootstrap_productive_rpc_env.py" in joined:
        return "productive_rpc:alchemy_primary+dRPC_secondary"
    if "m8_radar_two_phase_refresh.py" in joined:
        return "direct:DexScreener/async+multicall (no bootstrap)"
    if joined.endswith("check_rpc_endpoints.py") or "check_rpc_endpoints.py --chain" in joined:
        return "preflight:HTTP+WS archive probe"
    return "direct:local_py"


def _preflight_steps(*, allow_roadmap_edit: bool = False) -> list[dict[str, Any]]:
    safety_cmd = _py_cmd("scripts/check_repo_safety.py")
    if allow_roadmap_edit:
        safety_cmd.append("--allow-roadmap-edit")
    return [
        _pipeline_step("preflight_repo_safety", safety_cmd),
        _pipeline_step(
            "preflight_layer_audit",
            _py_cmd("scripts/audit_layer_responsibility.py"),
        ),
        _pipeline_step(
            "preflight_rpc_endpoints",
            _py_cmd("scripts/check_rpc_endpoints.py", "--chain", "base"),
            allow_exit_codes=(0, 2),
        ),
    ]


def _filter_steps_for_resume(
    steps: list[dict[str, Any]],
    resume_from: str,
) -> list[dict[str, Any]]:
    anchor = RESUME_FROM_FIRST_STEP.get(resume_from)
    if not anchor:
        raise ValueError(f"unknown --resume-from value: {resume_from}")
    preflight = [step for step in steps if str(step["name"]).startswith("preflight_")]
    body = [step for step in steps if not str(step["name"]).startswith("preflight_")]
    names = [step["name"] for step in body]
    if anchor not in names:
        raise ValueError(
            f"--resume-from {resume_from} anchor step {anchor!r} not in pipeline plan"
        )
    idx = names.index(anchor)
    return preflight + body[idx:]


def _print_rpc_policy_table(steps: list[dict[str, Any]]) -> None:
    print("RPC / routing policy (dry-run):")
    for step in steps:
        policy = _classify_step_rpc_policy(step["cmd"])
        ws_note = ""
        if "productive_rpc" in policy or "preflight" in policy:
            ws_note = " | WS: BASE_WSS when step needs subscriptions"
        internal = step.get("internal")
        cmd_preview = (
            f"<internal:{internal}>"
            if internal
            else " ".join(step.get("cmd") or [])
        )
        print(f"  - {step['name']}: {policy}{ws_note}")
        if cmd_preview and not internal:
            print(f"      cmd: {cmd_preview}")
        env = step.get("env") or {}
        if env:
            env_preview = ", ".join(f"{k}={v}" for k, v in env.items())
            print(f"      env: {env_preview}")
        if internal:
            print(f"      internal: {internal}")


def _pipeline_step(
    name: str,
    cmd: Iterable[str],
    *,
    allow_exit_codes: tuple[int, ...] = (0,),
    env: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
    internal: str | None = None,
    description: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "name": name,
        "cmd": list(cmd),
        "allow_exit_codes": allow_exit_codes,
        "env": dict(env or {}),
    }
    if timeout_seconds is not None:
        step["timeout_seconds"] = int(timeout_seconds)
    if internal:
        step["internal"] = internal
    if description:
        step["description"] = description
    step.update(extra)
    return step


def _resolve_step_timeout(step: dict[str, Any], args: argparse.Namespace) -> int:
    explicit = step.get("timeout_seconds")
    if explicit is not None:
        return int(explicit)
    name = str(step["name"])
    if name == "m8_2_radar_two_phase":
        radar_timeout = int(getattr(args, "radar_step_timeout_s", 0) or 0)
        if radar_timeout > 0:
            return radar_timeout
    default_timeout = int(getattr(args, "step_timeout_s", 0) or 0)
    if default_timeout > 0:
        return default_timeout
    return DEFAULT_STEP_TIMEOUT_S


def _collect_checkpoint_progress(
    step_names: list[str],
    *,
    pipeline_mode: str | None = None,
) -> dict[str, Any]:
    return _checkpoint_store().collect_progress(step_names, pipeline_mode=pipeline_mode)


def _write_pipeline_current(payload: dict[str, Any]) -> None:
    PIPELINE_CURRENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIPELINE_CURRENT_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _clear_pipeline_current() -> None:
    try:
        PIPELINE_CURRENT_PATH.unlink()
    except FileNotFoundError:
        pass


def _run_internal_pipeline_step(internal: str, step: dict[str, Any] | None = None) -> int:
    if internal == "pending_1_to_2_queue":
        return _export_pending_1_to_2_queue()
    if internal == "patient_spread_lifetime_export":
        return _export_patient_spread_lifetime()
    if internal == "cross_chain_research_plan":
        print(
            "cross_chain_research: R&D placeholder — no execution, no profit claims",
            flush=True,
        )
        return 0
    if internal == "time_to_mirror_sla_export":
        return _export_time_to_mirror_sla()
    if internal == "time_to_mirror_narrow_inventory":
        return _build_time_to_mirror_narrow_inventory()
    if internal == "mirror_yield_funnel_export":
        return _export_mirror_yield_funnel()
    if internal == "time_to_mirror_expand_subset":
        ns = _CURRENT_PIPELINE_ARGS
        max_t = int(getattr(ns, "max_radar_tokens", 100) or 100) if ns else 100
        return _export_time_to_mirror_expand_subset(max_tokens=max_t)
    if internal == "second_pool_transition_subset":
        return _export_second_pool_transition_subset()
    if internal == "event_stream_lane":
        return _run_event_stream_lane()
    if internal == "patient_lane_diagnostics":
        return _export_patient_lane_diagnostics()
    if internal == "mirror_selection_pass":
        return _run_mirror_selection_pass()
    if internal == "gate_recall_verify_admission":
        return _gate_recall_verify_admission()
    if internal == "streaming_batch_upstream_gate":
        return _run_streaming_batch_upstream_gate(step or {})
    if internal == "streaming_batch_manifest":
        session_id = os.environ.get(ENV_PIPELINE_SESSION_ID, "").strip()
        if not session_id:
            session_id = new_pipeline_session_id()
            os.environ[ENV_PIPELINE_SESSION_ID] = session_id
        batch_index = int((step or {}).get("streaming_batch_index", 1))
        batch_minutes = int(
            (step or {}).get(
                "streaming_batch_minutes",
                os.environ.get("ARBY_SNIPER_BATCH_MINUTES", "15"),
            )
            or 15
        )
        write_streaming_batch_manifest(
            session_id=session_id,
            batch_index=batch_index,
            batch_minutes=batch_minutes,
        )
        return 0
    print(f"ERROR: unknown internal pipeline step: {internal}", flush=True)
    return 2


def _resolve_time_to_mirror_profile(args: argparse.Namespace) -> dict[str, Any]:
    """Map hot-lane mode to bounded token/timeout budgets (minutes-scale hot path)."""
    pipeline = str(getattr(args, "pipeline", "") or "")
    if pipeline == "mirror_recall_fast":
        lane = "mirror_recall_fast"
    elif pipeline == "mirror_recall_wide":
        lane = "mirror_recall_wide"
    else:
        explicit_lane = getattr(args, "hot_lane", None)
        hot_flag = bool(getattr(args, "time_to_mirror_hot", False))
        if explicit_lane:
            lane = str(explicit_lane)
        elif hot_flag:
            lane = "hot_delta"
        else:
            lane = "warm_recall"
    profile = dict(HOT_LANE_PROFILES.get(lane, HOT_LANE_PROFILES["warm_recall"]))
    profile["lane"] = lane
    cli_max = int(getattr(args, "max_radar_tokens", 753) or 753)
    default_cli = 753
    if cli_max != default_cli:
        profile["max_radar_tokens"] = max(1, cli_max)
    skip_secondary = getattr(args, "skip_secondary", None)
    if skip_secondary is not None:
        profile["skip_secondary"] = bool(skip_secondary)
    if lane != "audit_full" and profile["max_radar_tokens"] > HOT_LANE_PROFILES[lane][
        "max_radar_tokens"
    ]:
        profile["max_radar_tokens"] = HOT_LANE_PROFILES[lane]["max_radar_tokens"]
    cli_verify = getattr(args, "verify_subset_max", None)
    if cli_verify is not None:
        if str(getattr(args, "pipeline", "") or "") == "time_to_mirror" and (
            hot_flag or lane == "hot_delta"
        ):
            profile["verify_subset_max"] = max(1, int(cli_verify))
        else:
            print(
                "WARN: --verify-subset-max ignored (only valid for -time_to_mirror --hot)",
                flush=True,
            )
    return profile


def _m81_stable_anchor_cmd(
    *,
    probe_mode: str = "audit_full",
    token_subset: str | None = None,
    duration_minutes: float | None = None,
) -> list[str]:
    cmd = _productive_rpc_cmd(
        "scripts/m8_1_stable_anchor_run.py",
        "--probe-mode",
        probe_mode,
    )
    if token_subset:
        cmd.extend(["--token-subset-file", token_subset])
    if duration_minutes is not None:
        cmd.extend(["--duration-minutes", str(duration_minutes)])
    return cmd


_resolve_streaming_step_cmd = resolve_streaming_step_cmd


def _run_streaming_batch_upstream_gate(step: dict[str, Any]) -> int:
    return run_streaming_batch_upstream_gate(step)


def _m82_cross_dex_expand_cmd(
    *,
    hot: bool = False,
    token_subset: str | None = None,
    external_hints: str | None = None,
    anchor: str | None = None,
    output: str | None = None,
) -> list[str]:
    scan_mode = "hot_path_incremental" if hot else "candidate_summary"
    cmd = [
        "scripts/m8_cross_dex_expand.py",
        "--chain",
        "base",
        "--external-hints",
        external_hints or EXTERNAL_HINTS_ROLLING,
        "--scan-mode",
        scan_mode,
    ]
    if anchor:
        cmd.extend(["--anchor", anchor])
    if output:
        cmd.extend(["--output", output])
    if hot or token_subset:
        cmd.extend(
            [
                "--token-subset-file",
                token_subset or TIME_TO_MIRROR_EXPAND_SUBSET,
            ]
        )
    return _productive_rpc_cmd(*cmd)


def _mirror_smoke_pipeline_cmd(checkpoint_path: str, *extra: str) -> list[str]:
    return _productive_rpc_cmd(
        "scripts/m8_mirror_quote_smoke.py",
        "--pipeline-mode",
        "--checkpoint-path",
        checkpoint_path,
        "--quote-workers",
        "4",
        *extra,
    )


def _gate_recall_verify_admission() -> int:
    """Downstream verify (factory/m81) only when recall produced candidates."""
    if not MIRROR_DISCOVERY_RECALL_PATH.is_file():
        print("gate_recall_verify_admission: recall artifact missing", flush=True)
        return 2
    doc = json.loads(MIRROR_DISCOVERY_RECALL_PATH.read_text(encoding="utf-8"))
    total = int(doc.get("all_dex_mirrors_total") or doc.get("mirrors_total") or 0)
    pool_exists = int(doc.get("recall_verified_pool_exists_total") or 0)
    if total <= 0:
        print(
            "gate_recall_verify_admission: no recall candidates — skip heavy verify",
            flush=True,
        )
        return 2
    print(
        f"gate_recall_verify_admission: recall={total} pool_exists={pool_exists} "
        f"subset={EXISTENCE_VERIFY_SUBSET_PATH}",
        flush=True,
    )
    return 0


def _verify_token_subset_path() -> str:
    """Prefer existence-verify queue subset over full expand universe."""
    return str(EXISTENCE_VERIFY_SUBSET_PATH)


def _export_time_to_mirror_expand_subset(*, max_tokens: int) -> int:
    from m8.discovery.time_to_mirror_lane import (
        FRESH_DELTA_SUBSET_PATH,
        TIME_TO_MIRROR_EXPAND_SUBSET_PATH,
        build_time_to_mirror_expand_subset,
    )

    return build_time_to_mirror_expand_subset(
        max_tokens=max_tokens,
        fresh_subset_path=FRESH_DELTA_SUBSET_PATH,
        output_path=TIME_TO_MIRROR_EXPAND_SUBSET_PATH,
    )


def _export_second_pool_transition_subset() -> int:
    from m8.discovery.time_to_mirror_lane import (
        SECOND_POOL_TRANSITION_SUBSET_PATH,
        build_second_pool_transition_subset,
    )

    return build_second_pool_transition_subset(output_path=SECOND_POOL_TRANSITION_SUBSET_PATH)


def _run_event_stream_lane() -> int:
    ns = _CURRENT_PIPELINE_ARGS
    max_t = 50
    max_blocks = 500
    if ns is not None:
        prof = _resolve_time_to_mirror_profile(ns)
        max_t = int(prof.get("max_radar_tokens") or max_t)
        max_blocks = int(prof.get("event_poll_max_blocks") or max_blocks)
    from m8.discovery.event_stream_lane import run_event_stream_lane

    payload = run_event_stream_lane(
        subset_path=Path(TIME_TO_MIRROR_EXPAND_SUBSET),
        max_tokens=max_t,
        max_blocks=max_blocks,
        output_path=EVENT_STREAM_LANE_ARTIFACT,
        dry_run=os.environ.get("ARBY_SKIP_RPC") == "1",
    )
    print(
        f"event_stream_lane: events={payload.get('events_emitted')} "
        f"pending={payload.get('pending_count')}",
        flush=True,
    )
    return 0


def _export_patient_lane_diagnostics() -> int:
    from m8.discovery.patient_lane_diagnostics import export_patient_lane_diagnostics

    payload = export_patient_lane_diagnostics(
        watchlist_path=WATCHLIST_PATH,
        output_path=PATIENT_LANE_DIAGNOSTIC_PATH,
    )
    print(
        f"patient_lane_diagnostics: single_venue={payload.get('single_venue_count')} "
        f"-> {PATIENT_LANE_DIAGNOSTIC_PATH}",
        flush=True,
    )
    return 0


def _run_mirror_selection_pass() -> int:
    """Hand off supported+verified recall mirrors to rolling hints (selection for narrow bridge)."""
    if not MIRROR_DISCOVERY_RECALL_PATH.is_file():
        print("mirror_selection_pass: recall artifact missing", flush=True)
        return 2
    recall = json.loads(MIRROR_DISCOVERY_RECALL_PATH.read_text(encoding="utf-8"))
    from m8.discovery.mirror_discovery_recall import (
        DEFAULT_RECALL_HINTS_PATH,
        DEFAULT_SUPPORTED_HINTS_PATH,
        load_recall_hints_checkpoint,
        run_mirror_selection_pass,
    )
    from m8.discovery.pool_hints import PoolHint, load_hints_artifact

    hints = load_recall_hints_checkpoint(DEFAULT_RECALL_HINTS_PATH)
    selection_input = DEFAULT_RECALL_HINTS_PATH
    if not hints:
        hints_doc = load_hints_artifact(str(DEFAULT_SUPPORTED_HINTS_PATH))
        hints = [PoolHint.from_dict(h) for h in hints_doc.get("hints") or []]
        selection_input = DEFAULT_SUPPORTED_HINTS_PATH
    if not hints:
        print(
            "mirror_selection_pass: no recall hints checkpoint "
            "(recall step should write data/tmp/m8_mirror_recall_hints_latest.json)",
            flush=True,
        )
        return 0
    payload = run_mirror_selection_pass(
        recall,
        hints=hints,
        selection_input_path=selection_input,
    )
    print(
        f"mirror_selection_pass: input={selection_input} "
        f"stages={payload.get('selection_stages')} "
        f"selected={payload.get('mirrors_selected')} "
        f"m9_target_ready={payload.get('m9_target_ready')}",
        flush=True,
    )
    return 0


def _export_pending_1_to_2_queue() -> int:
    from m8.discovery.time_to_mirror_lane import (
        build_pending_queue_payload,
        load_watchlist,
    )

    watchlist = load_watchlist(WATCHLIST_PATH)
    payload = build_pending_queue_payload(watchlist)
    PENDING_1_TO_2_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_1_TO_2_QUEUE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"pending_1_to_2_queue: {payload['pending_count']} tokens "
        f"(top_score={payload['tokens'][0]['priority_score'] if payload['tokens'] else 0}) "
        f"-> {PENDING_1_TO_2_QUEUE_PATH}",
        flush=True,
    )
    return 0


def _export_time_to_mirror_sla() -> int:
    from m8.discovery.time_to_mirror_lane import (
        DEFAULT_EXPANSION_PATH,
        build_time_to_mirror_sla,
    )

    payload = build_time_to_mirror_sla(
        watchlist_path=WATCHLIST_PATH,
        expansion_path=DEFAULT_EXPANSION_PATH,
        pending_path=PENDING_1_TO_2_QUEUE_PATH,
        mirror_reprobe_checkpoint_path=Path(MIRROR_QUOTE_REPROBE_CHECKPOINT_PATH),
        mirror_verify_checkpoint_path=Path(MIRROR_SECOND_POOL_VERIFY_CHECKPOINT_PATH),
    )
    TIME_TO_MIRROR_SLA_PATH.parent.mkdir(parents=True, exist_ok=True)
    TIME_TO_MIRROR_SLA_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"time_to_mirror_sla: quote_ready={payload.get('mirror_quote_ready_tokens')} "
        f"pending={payload.get('pending_count')} -> {TIME_TO_MIRROR_SLA_PATH}",
        flush=True,
    )
    return 0


def _build_time_to_mirror_narrow_inventory() -> int:
    from m8.discovery.time_to_mirror_lane import build_narrow_m9_bridge_inventory

    _payload, rc = build_narrow_m9_bridge_inventory(
        output_path=Path(M9_TTM_NARROW_BRIDGE),
    )
    print(
        f"time_to_mirror_narrow_inventory: tokens={_payload.get('quote_ready_token_count')} "
        f"routes={len(_payload.get('active_routes') or [])} exit={rc}",
        flush=True,
    )
    return rc


def _export_mirror_yield_funnel() -> int:
    from m8.discovery.time_to_mirror_lane import build_mirror_yield_funnel_artifact

    payload = build_mirror_yield_funnel_artifact()
    print(
        f"mirror_yield_funnel: fresh_long_tail_pending={payload.get('fresh_long_tail_pending')} "
        f"verify_subset_size={payload.get('verify_subset_size')} "
        f"fresh_quote_ready={payload.get('fresh_long_tail_quote_ready_tokens')} "
        f"cycles_at_floor={payload.get('cycles_at_floor')}",
        flush=True,
    )
    return 0


def _export_patient_spread_lifetime() -> int:
    shadow_path = Path(M9_PATIENT_SHADOW_ARTIFACT)
    out_path = Path("data/tmp/m9_spread_lifetime_latest.json")
    if not shadow_path.is_file():
        print(f"WARN: patient shadow artifact missing ({shadow_path})", flush=True)
        return 0
    shadow = json.loads(shadow_path.read_text(encoding="utf-8"))
    spread_block = shadow.get("spread_lifetime") or {}
    payload = {
        "schema_version": "m9_spread_lifetime_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_artifact": M9_PATIENT_SHADOW_ARTIFACT,
        "profit_claim_allowed": False,
        "spread_lifetime": spread_block,
        "summary": spread_block.get("summary") if isinstance(spread_block, dict) else {},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"patient_lane spread_lifetime exported -> {out_path}", flush=True)
    return 0


def _run_pipeline_step_subprocess(
    step: dict[str, Any],
    *,
    mode: str,
    step_index: int,
    step_total: int,
    all_step_names: list[str],
    log_fh: Any,
    timeout_s: int,
    heartbeat_stale_s: float,
) -> tuple[int, str | None]:
    name = str(step["name"])
    started_at = datetime.now(timezone.utc).isoformat()
    started_wall_ts = time.time()
    heartbeat_state = {"last": started_at}

    def _touch_current(pid: int | None, *, status: str = "running") -> None:
        _write_pipeline_current(
            {
                "mode": mode,
                "step": name,
                "pid": pid,
                "started_at": started_at,
                "last_heartbeat": heartbeat_state["last"],
                "status": status,
                "step_index": step_index,
                "step_total": step_total,
                "timeout_s": timeout_s,
                "heartbeat_stale_s": heartbeat_stale_s,
                "checkpoint_progress": _collect_checkpoint_progress(
                    all_step_names,
                    pipeline_mode=mode,
                ),
                "quiet_checkpoint_watch": list(STEP_QUIET_CHECKPOINTS.get(name, ())),
            }
        )

    internal = step.get("internal")
    if internal:
        _touch_current(os.getpid(), status="running_internal")
        rc = _run_internal_pipeline_step(str(internal), step)
        heartbeat_state["last"] = datetime.now(timezone.utc).isoformat()
        _touch_current(os.getpid(), status="finished_internal" if rc == 0 else "failed_internal")
        log_fh.write(f"<<< {name}: internal={internal} exit={rc}\n")
        log_fh.flush()
        return rc, None if rc in step["allow_exit_codes"] else f"exit={rc}"

    cmd = _resolve_streaming_step_cmd(step, list(step["cmd"]))
    env = os.environ.copy()
    base_env = dict(step.get("env") or {})
    if name in {"m9_shadow_10m", "m9_patient_shadow_10m"}:
        base_env.update(_resolve_m9_shadow_step_env())
    env.update(base_env)
    pipeline_sid = os.environ.get(ENV_PIPELINE_SESSION_ID, "").strip()
    if pipeline_sid:
        env[ENV_PIPELINE_SESSION_ID] = pipeline_sid

    pid_holder: dict[str, int | None] = {"pid": None}

    def _on_spawn(proc: subprocess.Popen) -> None:
        pid_holder["pid"] = proc.pid
        _touch_current(proc.pid)

    def _on_output(line: str) -> None:
        sys.stdout.write(line)
        log_fh.write(line)
        log_fh.flush()

    def _on_heartbeat() -> None:
        heartbeat_state["last"] = datetime.now(timezone.utc).isoformat()
        _touch_current(pid_holder["pid"])

    rc, fail_reason = run_stage_subprocess(
        cmd,
        env=env,
        timeout_s=timeout_s,
        heartbeat_stale_s=heartbeat_stale_s,
        on_output=_on_output,
        on_heartbeat=_on_heartbeat,
        has_external_activity=lambda: _checkpoint_activity_since(name, started_wall_ts),
        on_spawn=_on_spawn,
    )
    heartbeat_state["last"] = datetime.now(timezone.utc).isoformat()
    _touch_current(pid_holder["pid"], status="failed" if fail_reason else "finished")
    log_fh.write(f"<<< {name}: exit={rc}" + (f" reason={fail_reason}" if fail_reason else "") + "\n")
    log_fh.flush()
    if fail_reason:
        return rc or 1, fail_reason
    return rc, None


def build_project_pipeline_steps(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Build the canonical M8/M8.2/M8.3/M9 operation plan.

    This keeps M8/M9 orchestration centralized while leaving the legacy M4/M5
    config scanner path intact.
    """
    mode = str(getattr(args, "pipeline", "") or "")
    ttm_profile = (
        _resolve_time_to_mirror_profile(args)
        if mode in ("time_to_mirror", "mirror_recall_fast")
        else None
    )
    max_radar = str(
        int((ttm_profile or {}).get("max_radar_tokens") or getattr(args, "max_radar_tokens", 753) or 753)
    )
    streaming = bool(getattr(args, "streaming", False)) or streaming_enabled()
    streaming_final_batch_index: int | None = None
    if streaming:
        streaming_final_batch_index = len(
            resolve_streaming_batches(
                int(getattr(args, "sniper_minutes", 45) or 45),
                batch_minutes=int(getattr(args, "sniper_batch_minutes", 15) or 15),
            )
        )
    sniper_minutes = str(
        resolve_sniper_minutes(
            int(getattr(args, "sniper_minutes", 45) or 45),
            streaming=streaming,
            batch_minutes=int(getattr(args, "sniper_batch_minutes", 15) or 15),
        )
    )
    token_concurrency = str(max(1, int(getattr(args, "token_concurrency", 4) or 4)))
    skip_coingecko = bool(getattr(args, "skip_coingecko", True))
    include_shadow = not bool(getattr(args, "skip_shadow", False))

    steps: list[dict[str, Any]] = []

    def add_m8() -> None:
        total_sniper_minutes = int(getattr(args, "sniper_minutes", 45) or 45)
        batch_minutes = int(getattr(args, "sniper_batch_minutes", 15) or 15)
        if streaming:
            batches = resolve_streaming_batches(
                total_sniper_minutes,
                batch_minutes=batch_minutes,
            )
            for batch_index, batch_dur in enumerate(batches, start=1):
                sniper_cmd = _productive_rpc_cmd(
                    "-u",
                    "scripts/sniper_smoke_run.py",
                    "--chain",
                    "base",
                    "--duration-minutes",
                    str(batch_dur),
                    "--acceptance-run",
                    "--blocks-back",
                    "50",
                    "--streaming-batch-index",
                    str(batch_index),
                )
                sniper_env = {"ARBY_SNIPER_ENABLE": "1"}
                if batch_index == 1:
                    sniper_cmd.extend(
                        ["--write-checkpoint", M8_SNIPER_STREAMING_CHECKPOINT]
                    )
                else:
                    sniper_cmd.extend(
                        [
                            "--skip-self-test",
                            "--skip-preflight",
                            "--checkpoint-artifact",
                            M8_SNIPER_STREAMING_CHECKPOINT,
                        ]
                    )
                steps.append(
                    _pipeline_step(
                        f"m8_sniper_acceptance_batch_{batch_index}",
                        sniper_cmd,
                        env=sniper_env,
                        streaming_batch_index=batch_index,
                    )
                )
                steps.append(
                    _pipeline_step(
                        f"m8_streaming_batch_manifest_{batch_index}",
                        [],
                        internal="streaming_batch_manifest",
                        streaming_batch_index=batch_index,
                        streaming_batch_minutes=batch_dur,
                    )
                )
                m81_cmd = _productive_rpc_cmd("scripts/m8_1_stable_anchor_run.py")
                m81_cmd.extend(m81_streaming_cli_args(batch_index=batch_index))
                steps.append(
                    _pipeline_step(
                        f"m8_1_stable_anchor_batch_{batch_index}",
                        m81_cmd,
                        streaming_batch_index=batch_index,
                        allow_exit_codes=(0, 1),
                    )
                )
                radar_cmd = _productive_rpc_cmd(
                    "scripts/m8_radar_two_phase_refresh.py",
                    "--max-tokens",
                    max_radar,
                    "--lane-mode",
                    "fresh_first",
                    "--skip-acceptance",
                    "--token-concurrency",
                    token_concurrency,
                    "--token-subset-file",
                    STREAMING_TOKEN_SUBSET_SENTINEL,
                    "--hints-output",
                    STREAMING_M82_HINTS_SENTINEL,
                    "--radar-output",
                    STREAMING_M82_RADAR_SENTINEL,
                    "--batch-scratch-dir",
                    STREAMING_BATCH_DIR_SENTINEL,
                )
                if skip_coingecko:
                    radar_cmd.append("--skip-coingecko")
                steps.append(
                    _pipeline_step(
                        f"m8_2_radar_two_phase_batch_{batch_index}",
                        radar_cmd,
                        streaming_batch_index=batch_index,
                    )
                )
                steps.append(
                    _pipeline_step(
                        f"m8_2_cross_dex_expand_batch_{batch_index}",
                        _m82_cross_dex_expand_cmd(
                            hot=True,
                            token_subset=STREAMING_TOKEN_SUBSET_SENTINEL,
                            external_hints=STREAMING_M82_HINTS_SENTINEL,
                            anchor=STREAMING_M81_OUTPUT_SENTINEL,
                            output=STREAMING_M82_EXPANSION_SENTINEL,
                        ),
                        streaming_batch_index=batch_index,
                    )
                )
                m83_cmd = _productive_rpc_cmd(
                    "scripts/m8_3_token_metadata_registry_refresh.py",
                    "--chain",
                    "base",
                    "--task-mode",
                    "aggregated",
                    "--with-dex-workers",
                    "--dex-worker-concurrency",
                    "4",
                    "--max-onchain-probes",
                    "120",
                    "--output",
                    STREAMING_M83_REGISTRY_SENTINEL,
                )
                steps.append(
                    _pipeline_step(
                        f"m8_3_registry_refresh_batch_{batch_index}",
                        m83_cmd,
                        streaming_batch_index=batch_index,
                    )
                )
                steps.append(
                    _pipeline_step(
                        f"m8_m9_runtime_truth_gate_upstream_batch_{batch_index}",
                        [],
                        internal="streaming_batch_upstream_gate",
                        streaming_batch_index=batch_index,
                        allow_exit_codes=(0,),
                    )
                )
            return
        steps.append(
            _pipeline_step(
                "m8_sniper_acceptance",
                _productive_rpc_cmd(
                    "-u",
                    "scripts/sniper_smoke_run.py",
                    "--chain",
                    "base",
                    "--duration-minutes",
                    sniper_minutes,
                    "--acceptance-run",
                    "--blocks-back",
                    "50",
                ),
                env={"ARBY_SNIPER_ENABLE": "1"},
            )
        )
        m81_cmd = _productive_rpc_cmd("scripts/m8_1_stable_anchor_run.py")
        steps.append(
            _pipeline_step(
                "m8_1_stable_anchor",
                m81_cmd,
            )
        )

    def add_m82(
        *,
        hot_expand: bool = False,
        profile: dict[str, Any] | None = None,
        recall_output_path: Path = MIRROR_DISCOVERY_RECALL_PATH,
    ) -> None:
        prof = profile or {}
        radar_cmd = _py_cmd(
            "scripts/m8_radar_two_phase_refresh.py",
            "--max-tokens",
            max_radar,
            "--lane-mode",
            "fresh_first",
            "--skip-acceptance",
            "--token-concurrency",
            token_concurrency,
        )
        if skip_coingecko:
            radar_cmd.append("--skip-coingecko")
        if prof.get("skip_secondary"):
            radar_cmd.append("--skip-secondary")
        verify_max = prof.get("verify_subset_max")
        if verify_max:
            radar_cmd.extend(["--verify-subset-max", str(int(verify_max))])
        radar_secondary_timeout = int(
            getattr(args, "radar_secondary_provider_timeout_s", 0)
            or DEFAULT_RADAR_SECONDARY_PROVIDER_TIMEOUT_S
        )
        if radar_secondary_timeout > 0 and not prof.get("skip_secondary"):
            radar_cmd.extend(
                [
                    "--secondary-provider-timeout-s",
                    str(radar_secondary_timeout),
                    "--coingecko-provider-timeout-s",
                    str(radar_secondary_timeout),
                ]
            )
        radar_step_timeout = int(
            prof.get("radar_step_timeout_s")
            or getattr(args, "radar_step_timeout_s", 0)
            or DEFAULT_RADAR_STEP_TIMEOUT_S
        )
        mirror_max_recall = bool(prof.get("mirror_discovery_max_recall"))
        recall_only = bool(prof.get("recall_only"))
        defer_verify = bool(prof.get("defer_heavy_verify"))
        anchor_constrained = bool(prof.get("anchor_constrained"))
        run_quote_smoke = bool(prof.get("run_quote_smoke"))
        verify_subset = _verify_token_subset_path()
        recall_cmd = _py_cmd(
            "scripts/m8_mirror_discovery_recall.py",
            "--chain",
            "base",
            "--token-subset-file",
            TIME_TO_MIRROR_EXPAND_SUBSET,
            "--max-tokens",
            str(max_radar),
            "--output",
            str(recall_output_path),
            "--write-supported-hints",
        )
        if anchor_constrained:
            recall_cmd.append("--anchor-constrained")
        if run_quote_smoke:
            recall_cmd.append("--run-quote-smoke")
            qmax = int(prof.get("quote_smoke_max_candidates") or 0)
            if qmax > 0:
                recall_cmd.extend(["--quote-smoke-max-candidates", str(qmax)])
        if not bool(prof.get("use_dexscreener", True)):
            recall_cmd.append("--no-dexscreener")
        if hot_expand:
            steps.append(
                _pipeline_step(
                    "m8_time_to_mirror_pending_queue",
                    [],
                    internal="pending_1_to_2_queue",
                )
            )
            steps.append(
                _pipeline_step(
                    "m8_time_to_mirror_expand_subset",
                    [],
                    internal="time_to_mirror_expand_subset",
                )
            )
            if mirror_max_recall:
                steps.append(
                    _pipeline_step(
                        "m8_mirror_discovery_recall",
                        recall_cmd,
                        timeout_seconds=radar_step_timeout,
                    )
                )
                steps.append(
                    _pipeline_step(
                        "gate_mirror_recall",
                        _py_cmd(
                            "scripts/m9_production_refresh_gates.py",
                            "mirror_recall",
                            "--recall",
                            str(recall_output_path),
                        ),
                        allow_exit_codes=(0, 2),
                    )
                )
                recall_sla = int(prof.get("recall_sla_max_s") or 0)
                if recall_sla > 0:
                    steps.append(
                        _pipeline_step(
                            "gate_recall_sla",
                            _py_cmd(
                                "scripts/m9_production_refresh_gates.py",
                                "recall_sla",
                                "--timings",
                                str(TIME_TO_MIRROR_STEP_TIMINGS_PATH),
                                "--max-latency-s",
                                str(recall_sla),
                            ),
                            allow_exit_codes=(0, 2),
                        )
                    )
                if not recall_only:
                    steps.append(
                        _pipeline_step(
                            "m8_event_stream_lane",
                            _productive_rpc_cmd(
                                "scripts/m8_event_stream_lane.py",
                                "--chain",
                                "base",
                                "--token-subset-file",
                                TIME_TO_MIRROR_EXPAND_SUBSET,
                                "--max-tokens",
                                str(max_radar),
                                "--max-blocks",
                                str(int(prof.get("event_poll_max_blocks") or 500)),
                                "--output",
                                str(EVENT_STREAM_LANE_ARTIFACT),
                            ),
                            timeout_seconds=min(radar_step_timeout, 600),
                        )
                    )
                    steps.append(
                        _pipeline_step(
                            "gate_recall_verify_admission",
                            [],
                            internal="gate_recall_verify_admission",
                            allow_exit_codes=(0, 2),
                        )
                    )
                    onchain_scan_cmd = _productive_rpc_cmd(
                        "scripts/m8_onchain_factory_mirror_scan.py",
                        "--chain",
                        "base",
                        "--token-subset-file",
                        verify_subset,
                        "--max-tokens",
                        str(max_radar),
                    )
                    steps.append(
                        _pipeline_step(
                            "m8_onchain_factory_mirror_scan",
                            onchain_scan_cmd,
                            timeout_seconds=min(radar_step_timeout, 1200),
                            allow_exit_codes=(0, 2),
                        )
                    )
                    steps.append(
                        _pipeline_step(
                            "m8_1_stable_anchor_fresh_delta",
                            _m81_stable_anchor_cmd(
                                probe_mode="fresh_delta",
                                token_subset=verify_subset,
                                duration_minutes=prof.get("m81_duration_minutes"),
                            ),
                            allow_exit_codes=(0, 2),
                        )
                    )
                    steps.append(
                        _pipeline_step(
                            "m8_mirror_selection_pass",
                            [],
                            internal="mirror_selection_pass",
                        )
                    )
                    steps.append(
                        _pipeline_step(
                            "gate_selection_verified_fresh",
                            _py_cmd(
                                "scripts/m9_production_refresh_gates.py",
                                "selection_verified_fresh",
                                "--recall",
                                str(MIRROR_DISCOVERY_RECALL_PATH),
                            ),
                            allow_exit_codes=(0, 2),
                        )
                    )
                    steps.append(
                        _pipeline_step(
                            "m8_2_cross_dex_expand",
                            _m82_cross_dex_expand_cmd(hot=True),
                            timeout_seconds=int(prof.get("expand_step_timeout_s") or 1200),
                        )
                    )
                    verify_sla = int(prof.get("verify_sla_max_s") or 0)
                    if verify_sla > 0 and defer_verify:
                        steps.append(
                            _pipeline_step(
                                "gate_verify_sla",
                                _py_cmd(
                                    "scripts/m9_production_refresh_gates.py",
                                    "verify_sla",
                                    "--timings",
                                    str(TIME_TO_MIRROR_STEP_TIMINGS_PATH),
                                    "--max-latency-s",
                                    str(verify_sla),
                                ),
                                allow_exit_codes=(0, 2),
                            )
                        )
            else:
                steps.append(
                    _pipeline_step(
                        "m8_event_stream_lane",
                        _productive_rpc_cmd(
                            "scripts/m8_event_stream_lane.py",
                            "--chain",
                            "base",
                            "--token-subset-file",
                            TIME_TO_MIRROR_EXPAND_SUBSET,
                            "--max-tokens",
                            str(max_radar),
                            "--max-blocks",
                            str(int(prof.get("event_poll_max_blocks") or 500)),
                            "--output",
                            str(EVENT_STREAM_LANE_ARTIFACT),
                        ),
                        timeout_seconds=min(radar_step_timeout, 600),
                    )
                )
                steps.append(
                    _pipeline_step(
                        "m8_1_stable_anchor_fresh_delta",
                        _m81_stable_anchor_cmd(
                            probe_mode="fresh_delta",
                            token_subset=TIME_TO_MIRROR_EXPAND_SUBSET,
                            duration_minutes=prof.get("m81_duration_minutes"),
                        ),
                    )
                )
                onchain_scan_cmd = _productive_rpc_cmd(
                    "scripts/m8_onchain_factory_mirror_scan.py",
                    "--chain",
                    "base",
                    "--token-subset-file",
                    TIME_TO_MIRROR_EXPAND_SUBSET,
                    "--max-tokens",
                    str(max_radar),
                )
                steps.append(
                    _pipeline_step(
                        "m8_onchain_factory_mirror_scan",
                        onchain_scan_cmd,
                        timeout_seconds=min(radar_step_timeout, 1200),
                    )
                )
                enrich_radar = list(radar_cmd)
                enrich_radar.extend(
                    [
                        "--dexscreener-enrich-only",
                        "--token-subset-file",
                        TIME_TO_MIRROR_EXPAND_SUBSET,
                        "--merge-existing-hints",
                    ]
                )
                steps.append(
                    _pipeline_step(
                        "m8_2_radar_two_phase",
                        enrich_radar,
                        timeout_seconds=radar_step_timeout,
                    )
                )
        else:
            steps.append(
                _pipeline_step(
                    "m8_2_radar_two_phase",
                    radar_cmd,
                    timeout_seconds=radar_step_timeout,
                )
            )
        if not mirror_max_recall:
            steps.append(
                _pipeline_step(
                    "gate_fresh_delta_subset",
                    _py_cmd("scripts/m9_production_refresh_gates.py", "fresh_delta_subset"),
                )
            )
            expand_timeout = prof.get("expand_step_timeout_s") if prof else None
            steps.append(
                _pipeline_step(
                    "m8_2_cross_dex_expand",
                    _m82_cross_dex_expand_cmd(hot=hot_expand),
                    timeout_seconds=int(expand_timeout) if expand_timeout else None,
                )
            )
        if not bool(prof.get("recall_only")):
            steps.append(
                _pipeline_step(
                    "m8_2_acceptance_strict",
                    _py_cmd("scripts/m8_2_acceptance_report.py", "--strict"),
                )
            )

    def add_m83(*, hot: bool = False, profile: dict[str, Any] | None = None) -> None:
        prof = profile or {}
        m83_cmd = _productive_rpc_cmd(
            "scripts/m8_3_token_metadata_registry_refresh.py",
            "--chain",
            "base",
            "--task-mode",
            "aggregated",
            "--with-dex-workers",
            "--dex-worker-concurrency",
            "4",
        )
        if hot:
            m83_cmd.extend(
                [
                    "--max-onchain-probes",
                    str(int(prof.get("m83_max_onchain_probes") or 120)),
                ]
            )
        steps.append(
            _pipeline_step(
                "m8_3_registry_refresh",
                m83_cmd,
            )
        )
        steps.append(
            _pipeline_step(
                "gate_negative_cache_stats",
                _py_cmd("scripts/m9_production_refresh_gates.py", "negative_cache_stats"),
            )
        )
        steps.append(
            _pipeline_step(
                "m8_3_acceptance_strict",
                _py_cmd("scripts/m8_3_acceptance_report.py", "--strict"),
            )
        )
        steps.append(
            _pipeline_step(
                "gate_m8_3_acceptance_reached",
                _py_cmd("scripts/m9_production_refresh_gates.py", "m8_3_acceptance"),
            )
        )

    def add_m9() -> None:
        use_batched_final = streaming_final_batch_index is not None
        m83_registry = (
            STREAMING_M83_REGISTRY_SENTINEL
            if use_batched_final
            else "data/runs/_rolling/m8_3_token_metadata_registry_latest.json"
        )
        upstream_gate_cmd = [
            "scripts/m8_m9_runtime_truth_gate.py",
            "--phase",
            "upstream",
            "--output",
            "data/tmp/m8_m9_runtime_truth_gate_upstream_latest.json",
        ]
        if use_batched_final:
            upstream_gate_cmd.extend(batched_final_truth_gate_args())
        steps.append(
            _pipeline_step(
                "m8_m9_runtime_truth_gate_upstream",
                _py_cmd(*upstream_gate_cmd),
                allow_exit_codes=(0,),
                streaming_final_batch=use_batched_final,
                description=(
                    "Upstream admission: refuse M8/M8.1/M8.2/M8.3 bundle when "
                    "sniper is stub/stale or inputs come from mixed windows."
                ),
            )
        )
        steps.append(_pipeline_step("m9_curve_discovery", _productive_rpc_cmd("scripts/m9_curve_discovery.py")))
        bridge_probe_cmd = [
            "scripts/m9_bridge_build.py",
            "--graph-handoff-only",
            "--no-registry",
            "--include-expansion-duplicates-for-shadow",
            "--metadata-registry",
            m83_registry,
            "--output",
            "data/tmp/m9_bridge_curve_probe.json",
            "--no-enforce-m8-provenance",
        ]
        if use_batched_final:
            bridge_probe_cmd.extend(batched_final_bridge_args())
        steps.append(
            _pipeline_step(
                "m9_bridge_curve_probe_for_indices",
                _py_cmd(*bridge_probe_cmd),
                env={"ARBY_M9_CURVE_ADMIT_ALL": "1"},
                streaming_final_batch=use_batched_final,
            )
        )
        steps.append(
            _pipeline_step(
                "m9_discover_curve_indices",
                _productive_rpc_cmd(
                    "scripts/discover_curve_indices.py",
                    "--partial",
                    "--debug",
                    "--inventory",
                    "data/tmp/m9_bridge_curve_probe.json",
                    "--output",
                    "data/runs/_rolling/m9_curve_pool_indices_latest.json",
                ),
            )
        )
        bridge_prod_cmd = [
            "scripts/m9_bridge_build.py",
            "--metadata-registry",
            m83_registry,
            "--output",
            PRODUCTION_BRIDGE,
        ]
        if use_batched_final:
            bridge_prod_cmd.extend(batched_final_bridge_args())
        steps.append(
            _pipeline_step(
                "m9_bridge_production",
                _py_cmd(*bridge_prod_cmd),
                env={"ARBY_CURVE_POOL_INDICES": "data/runs/_rolling/m9_curve_pool_indices_latest.json"},
                streaming_final_batch=use_batched_final,
            )
        )
        bundle_gate_cmd = [
            "scripts/m8_m9_runtime_truth_gate.py",
            "--phase",
            "bundle",
            "--output",
            "data/tmp/m8_m9_runtime_truth_gate_latest.json",
            "--bridge",
            PRODUCTION_BRIDGE,
        ]
        if use_batched_final:
            bundle_gate_cmd.extend(batched_final_truth_gate_args())
        steps.append(
            _pipeline_step(
                "m8_m9_runtime_truth_gate_bundle",
                _py_cmd(*bundle_gate_cmd),
                allow_exit_codes=(0,),
                streaming_final_batch=use_batched_final,
                description=(
                    "Bundle coherence after bridge build: upstream inputs plus "
                    "production bridge must share one runtime window/session."
                ),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_enrich_depth_false_positive",
                _productive_rpc_cmd(
                    "scripts/m9_enrich_bridge_depth.py",
                    "--inventory",
                    PRODUCTION_BRIDGE,
                    "--prioritize-false-positive-reprobe",
                    "--sleep-ms",
                    "150",
                ),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_enrich_depth_broad",
                _productive_rpc_cmd(
                    "scripts/m9_enrich_bridge_depth.py",
                    "--inventory",
                    PRODUCTION_BRIDGE,
                    "--force-reprobe",
                    "--sleep-ms",
                    "150",
                ),
            )
        )
        post_depth_cmd = [
            "scripts/m8_m9_runtime_truth_gate.py",
            "--phase",
            "post_depth",
            "--output",
            "data/tmp/m8_m9_runtime_truth_gate_post_depth_latest.json",
            "--bridge",
            PRODUCTION_BRIDGE,
        ]
        if use_batched_final:
            post_depth_cmd.extend(batched_final_truth_gate_args())
        steps.append(
            _pipeline_step(
                "m8_m9_runtime_truth_gate_post_depth",
                _py_cmd(*post_depth_cmd),
                allow_exit_codes=(0,),
                streaming_final_batch=use_batched_final,
                description=(
                    "Post-depth bridge coherence: production bridge after enrichment "
                    "must remain session-bound with upstream inputs."
                ),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_prepare_effective_inventory",
                _productive_rpc_cmd(
                    "scripts/m9_prepare_effective_inventory.py",
                    "--bridge",
                    PRODUCTION_BRIDGE,
                    "--config",
                    "config/exotic_base_anchor.yaml",
                    "--chain",
                    "base",
                ),
                env=_resolve_m9_effective_inventory_materialize_env(),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_topology_diagnostic",
                _py_cmd(
                    "scripts/m9_graph_topology_diagnostic.py",
                    "--inventory",
                    _resolve_m9_effective_inventory_materialize_env()["ARBY_M9_EFFECTIVE_INVENTORY_PATH"],
                    "--cycle-lengths",
                    "2,3,4",
                ),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_capacity_diagnostic",
                _py_cmd(
                    "scripts/m9_capacity_cycle_diagnostic.py",
                    "--bridge",
                    PRODUCTION_BRIDGE,
                    "--cycle-lengths",
                    "2,3,4",
                    "--four-leg-rca",
                    "--quarantine-rca",
                    "--output",
                    CAPACITY_DIAGNOSTIC,
                ),
                env=_resolve_m9_shadow_step_env(),
                allow_exit_codes=(0, 2),
            )
        )
        steps.append(
            _pipeline_step(
                "gate_capacity_shadow",
                _py_cmd("scripts/m9_production_refresh_gates.py", "capacity_shadow", "--capacity", CAPACITY_DIAGNOSTIC),
                allow_exit_codes=(0, 2),
            )
        )
        if include_shadow:
            steps.append(
                _pipeline_step(
                    "m9_shadow_10m",
                    _productive_rpc_cmd(
                        "-u",
                        "-m",
                        "m9.graph_arb.runner",
                        "--chain",
                        "base",
                        "--config",
                        "config/exotic_base_anchor.yaml",
                        "--inventory",
                        PRODUCTION_BRIDGE,
                        "--duration-minutes",
                        "10",
                        "--productive-lane",
                        "--require-factory-verified",
                        "--require-cycles-at-floor",
                        "--capacity-diagnostic",
                        CAPACITY_DIAGNOSTIC,
                        "--quote-backend",
                        "raw_http",
                        "--quote-workers",
                        "1",
                        "--max-cycles-per-sweep",
                        "20",
                        "--artifact-path",
                        M9_SHADOW_ARTIFACT,
                    ),
                    env=_resolve_m9_shadow_step_env(),
                )
            )
        if use_batched_final:
            steps.append(
                _pipeline_step(
                    "m8_2_acceptance_final_batch",
                    _py_cmd(
                        "scripts/m8_2_acceptance_report.py",
                        "--hints",
                        STREAMING_M82_HINTS_SENTINEL,
                        "--radar",
                        STREAMING_M82_RADAR_SENTINEL,
                        "--expansion",
                        STREAMING_M82_EXPANSION_SENTINEL,
                        "--output",
                        STREAMING_M82_ACCEPTANCE_SENTINEL,
                    ),
                    streaming_final_batch=True,
                    allow_exit_codes=(0, 1),
                )
            )
        lane_acceptance_cmd = [
            "scripts/m9_lane_acceptance_report.py",
            "--bridge",
            PRODUCTION_BRIDGE,
            "--shadow",
            M9_SHADOW_ARTIFACT,
            "--rca",
            M9_RCA_ARTIFACT,
        ]
        if use_batched_final:
            lane_acceptance_cmd.extend(
                batched_final_lane_acceptance_args(skip_shadow=not include_shadow)
            )
        else:
            lane_acceptance_cmd.extend(
                [
                    "--m8-2-report",
                    "data/tmp/m8_2_acceptance_report_latest.json",
                    "--m8-3-registry",
                    "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
                ]
            )
        steps.append(
            _pipeline_step(
                "m9_lane_acceptance",
                _py_cmd(*lane_acceptance_cmd),
                streaming_final_batch=use_batched_final,
            )
        )

    def _insert_time_to_mirror_steps() -> None:
        idx = next(
            (i for i, step in enumerate(steps) if step["name"] == "m8_2_acceptance_strict"),
            None,
        )
        if idx is None:
            return
        mirror_steps = [
            _pipeline_step(
                "m8_time_to_mirror_pending_queue_post_expand",
                [],
                internal="pending_1_to_2_queue",
            ),
            _pipeline_step(
                "m8_second_pool_transition_subset",
                [],
                internal="second_pool_transition_subset",
            ),
            _pipeline_step(
                "m8_mirror_quote_reprobe",
                _mirror_smoke_pipeline_cmd(
                    MIRROR_QUOTE_REPROBE_CHECKPOINT_PATH,
                    "--force-retry",
                ),
                allow_exit_codes=(0, 2),
            ),
            _pipeline_step(
                "m8_second_pool_verify",
                _mirror_smoke_pipeline_cmd(
                    MIRROR_SECOND_POOL_VERIFY_CHECKPOINT_PATH,
                    "--token-subset-file",
                    SECOND_POOL_TRANSITION_SUBSET,
                ),
                allow_exit_codes=(0, 2),
            ),
            _pipeline_step(
                "m8_time_to_mirror_sla_export",
                [],
                internal="time_to_mirror_sla_export",
            ),
            _pipeline_step(
                "m8_patient_lane_diagnostics",
                [],
                internal="patient_lane_diagnostics",
            ),
        ]
        steps[idx:idx] = mirror_steps

    def add_m8_audit() -> None:
        """Scheduled wide audit lane — not part of time-to-mirror hot path."""
        steps.append(
            _pipeline_step(
                "m8_1_stable_anchor_audit",
                _m81_stable_anchor_cmd(probe_mode="audit_full"),
            )
        )
        steps.append(
            _pipeline_step(
                "m8_2_cross_dex_expand_audit",
                _m82_cross_dex_expand_cmd(hot=False),
            )
        )
        steps.append(
            _pipeline_step(
                "m8_2_acceptance_strict",
                _py_cmd("scripts/m8_2_acceptance_report.py", "--strict"),
            )
        )
        add_m83()

    def add_mirror_recall_fast() -> None:
        """Contour A only: on-chain/factory token-scoped recall (≤180s SLA)."""
        profile = ttm_profile or dict(HOT_LANE_PROFILES["mirror_recall_fast"])
        print(
            f"mirror_recall_fast max_radar={profile.get('max_radar_tokens')} "
            f"recall_sla_max_s={profile.get('recall_sla_max_s')}",
            flush=True,
        )
        add_m82(hot_expand=True, profile=profile)

    def add_mirror_recall_wide() -> None:
        """M8.2 wide sidecar: batched DexScreener recall over fresh_delta+pending tokens."""
        profile = ttm_profile or dict(HOT_LANE_PROFILES["mirror_recall_wide"])
        print(
            f"mirror_recall_wide max_radar={profile.get('max_radar_tokens')} "
            f"recall_sla_max_s={profile.get('recall_sla_max_s')} "
            f"use_dexscreener=True",
            flush=True,
        )
        add_m82(
            hot_expand=True,
            profile=profile,
            recall_output_path=MIRROR_RECALL_WIDE_PATH,
        )

    def add_time_to_mirror() -> None:
        """Lane A: fresh delta + top pending only (minutes-scale hot path)."""
        profile = ttm_profile or _resolve_time_to_mirror_profile(args)
        hot_expand = bool(profile.get("hot_expand", True))
        print(
            f"time_to_mirror profile={profile.get('lane')} max_radar={profile.get('max_radar_tokens')} "
            f"skip_secondary={profile.get('skip_secondary')} hot_sla_max_s={profile.get('hot_sla_max_s')}",
            flush=True,
        )
        add_m82(hot_expand=hot_expand, profile=profile)
        _insert_time_to_mirror_steps()
        add_m83(hot=hot_expand, profile=profile)
        steps.append(
            _pipeline_step(
                "m9_time_to_mirror_narrow_inventory",
                [],
                internal="time_to_mirror_narrow_inventory",
                allow_exit_codes=(0, 2),
            )
        )
        steps.append(
            _pipeline_step(
                "gate_time_to_mirror_target_universe",
                _py_cmd(
                    "scripts/m9_production_refresh_gates.py",
                    "target_narrow_universe",
                    "--bridge",
                    M9_TTM_NARROW_BRIDGE,
                ),
                allow_exit_codes=(0, 2),
            )
        )
        steps.append(
            _pipeline_step(
                "m8_mirror_yield_funnel_export",
                [],
                internal="mirror_yield_funnel_export",
            )
        )
        steps.append(
            _pipeline_step(
                "m9_time_to_mirror_depth_enrich",
                _productive_rpc_cmd(
                    "scripts/m9_enrich_bridge_depth.py",
                    "--inventory",
                    M9_TTM_NARROW_BRIDGE,
                    "--output",
                    M9_TTM_NARROW_DEPTH_BRIDGE,
                    "--force-reprobe",
                    "--sleep-ms",
                    "150",
                ),
                allow_exit_codes=(0, 2),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_time_to_mirror_capacity_diagnostic",
                _py_cmd(
                    "scripts/m9_capacity_cycle_diagnostic.py",
                    "--bridge",
                    M9_TTM_NARROW_DEPTH_BRIDGE,
                    "--cycle-lengths",
                    "2,3,4",
                    "--four-leg-rca",
                    "--quarantine-rca",
                    "--output",
                    M9_TTM_NARROW_CAPACITY_DIAGNOSTIC,
                ),
                allow_exit_codes=(0, 2),
            )
        )
        if include_shadow:
            steps.append(
                _pipeline_step(
                    "gate_time_to_mirror_narrow_shadow",
                    _py_cmd(
                        "scripts/m9_production_refresh_gates.py",
                        "narrow_shadow",
                        "--capacity",
                        M9_TTM_NARROW_CAPACITY_DIAGNOSTIC,
                        "--bridge",
                        M9_TTM_NARROW_DEPTH_BRIDGE,
                    ),
                    allow_exit_codes=(0, 2),
                )
            )
            steps.append(
                _pipeline_step(
                    "m9_time_to_mirror_narrow_shadow_10m",
                    _productive_rpc_cmd(
                        "-u",
                        "-m",
                        "m9.graph_arb.runner",
                        "--chain",
                        "base",
                        "--config",
                        "config/exotic_base_anchor.yaml",
                        "--inventory",
                        M9_TTM_NARROW_DEPTH_BRIDGE,
                        "--duration-minutes",
                        "10",
                        "--productive-lane",
                        "--require-factory-verified",
                        "--require-cycles-at-floor",
                        "--capacity-diagnostic",
                        M9_TTM_NARROW_CAPACITY_DIAGNOSTIC,
                        "--quote-backend",
                        "raw_http",
                        "--quote-workers",
                        "4",
                        "--max-cycles-per-sweep",
                        "20",
                        "--artifact-path",
                        M9_TTM_NARROW_SHADOW_ARTIFACT,
                        "--allow-spread-lifetime-without-positive-gross",
                    ),
                    allow_exit_codes=(0, 2),
                    env={
                        **patient_lane_shadow_env(),
                        "ARBY_M9_TIME_TO_MIRROR_NARROW": "1",
                    },
                )
            )
        if int(profile.get("hot_sla_max_s") or 0) > 0:
            steps.append(
                _pipeline_step(
                    "gate_time_to_mirror_hot_sla",
                    _py_cmd(
                        "scripts/m9_production_refresh_gates.py",
                        "hot_sla",
                        "--timings",
                        str(TIME_TO_MIRROR_STEP_TIMINGS_PATH),
                        "--max-latency-s",
                        str(int(profile.get("hot_sla_max_s") or TIME_TO_MIRROR_HOT_SLA_S)),
                    ),
                    allow_exit_codes=(0, 2),
                )
            )

    def add_patient_lane() -> None:
        """Lane B: thin-liquidity diagnostic shadow (no profit claim)."""
        steps.append(
            _pipeline_step(
                "m9_capacity_diagnostic",
                _py_cmd(
                    "scripts/m9_capacity_cycle_diagnostic.py",
                    "--bridge",
                    PRODUCTION_BRIDGE,
                    "--cycle-lengths",
                    "2,3,4",
                    "--four-leg-rca",
                    "--quarantine-rca",
                    "--output",
                    CAPACITY_DIAGNOSTIC,
                ),
                allow_exit_codes=(0, 2),
            )
        )
        steps.append(
            _pipeline_step(
                "gate_capacity_shadow",
                _py_cmd(
                    "scripts/m9_production_refresh_gates.py",
                    "capacity_shadow",
                    "--capacity",
                    CAPACITY_DIAGNOSTIC,
                ),
                allow_exit_codes=(0, 2),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_patient_shadow_10m",
                _productive_rpc_cmd(
                    "-u",
                    "-m",
                    "m9.graph_arb.runner",
                    "--chain",
                    "base",
                    "--config",
                    "config/exotic_base_anchor.yaml",
                    "--inventory",
                    PRODUCTION_BRIDGE,
                    "--duration-minutes",
                    "10",
                    "--productive-lane",
                    "--require-factory-verified",
                    "--require-cycles-at-floor",
                    "--capacity-diagnostic",
                    CAPACITY_DIAGNOSTIC,
                    "--quote-backend",
                    "raw_http",
                    "--quote-workers",
                    "1",
                    "--max-cycles-per-sweep",
                    "20",
                    "--artifact-path",
                    M9_PATIENT_SHADOW_ARTIFACT,
                    "--allow-spread-lifetime-without-positive-gross",
                    "--prior-shadow-artifact",
                    M9_PATIENT_SHADOW_ARTIFACT,
                ),
                env=patient_lane_shadow_env(),
            )
        )
        steps.append(
            _pipeline_step(
                "m9_patient_spread_lifetime_export",
                [],
                internal="patient_spread_lifetime_export",
            )
        )
        steps.append(
            _pipeline_step(
                "m9_lane_acceptance",
                _py_cmd(
                    "scripts/m9_lane_acceptance_report.py",
                    "--m8-2-report",
                    "data/tmp/m8_2_acceptance_report_latest.json",
                    "--m8-3-registry",
                    "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
                    "--bridge",
                    PRODUCTION_BRIDGE,
                    "--shadow",
                    M9_PATIENT_SHADOW_ARTIFACT,
                    "--rca",
                    M9_RCA_ARTIFACT,
                ),
            )
        )

    def add_cross_chain_research() -> None:
        """R&D placeholder lane — dry-run plan only, no execution or profit claims."""
        steps.append(
            _pipeline_step(
                "cross_chain_research_plan",
                [],
                internal="cross_chain_research_plan",
            )
        )

    if mode == "m8":
        add_m8()
    elif mode == "m8_2":
        add_m82()
    elif mode == "m8_3":
        add_m83()
    elif mode == "m9":
        add_m9()
    elif mode == "time_to_mirror":
        add_time_to_mirror()
    elif mode == "mirror_recall_fast":
        add_mirror_recall_fast()
    elif mode == "mirror_recall_wide":
        add_mirror_recall_wide()
    elif mode == "m8_audit":
        add_m8_audit()
    elif mode == "patient_lane":
        add_patient_lane()
    elif mode == "cross_chain_research":
        add_cross_chain_research()
    elif mode in {"m8_m9", "full"}:
        add_m8()
        if not streaming:
            add_m82()
            add_m83()
        add_m9()
    else:
        raise ValueError(f"unknown pipeline mode: {mode}")

    plan = list(steps)
    if not getattr(args, "skip_preflight", False):
        plan = _preflight_steps(
            allow_roadmap_edit=bool(getattr(args, "allow_roadmap_edit", False)),
        ) + plan
    resume_from = getattr(args, "resume_from", None)
    if resume_from:
        plan = _filter_steps_for_resume(plan, str(resume_from))
    return plan


def _write_time_to_mirror_step_timings(
    step_timings: dict[str, float],
    *,
    pipeline_t0: float,
    profile: dict[str, Any] | None = None,
    run_kind: str = "fresh_run",
) -> None:
    from m8.discovery.time_to_mirror_lane import build_time_to_mirror_latency_artifact

    executed_s = sum(float(v or 0.0) for v in step_timings.values())
    pipeline_latency_s = round(max(0.0, time.monotonic() - pipeline_t0), 2)
    if executed_s <= 0.0 or pipeline_latency_s < 5.0:
        run_kind = "cached_resume"
    if run_kind == "cached_resume" and TIME_TO_MIRROR_STEP_TIMINGS_PATH.is_file():
        try:
            prev = json.loads(TIME_TO_MIRROR_STEP_TIMINGS_PATH.read_text(encoding="utf-8"))
            prev_latency = float(prev.get("time_to_mirror_latency_s") or 0.0)
            if prev_latency >= 30.0:
                prev["last_run_kind"] = "cached_resume"
                prev["last_cached_at_utc"] = datetime.now(timezone.utc).isoformat()
                prev["step_timings_cached_s"] = step_timings
                TIME_TO_MIRROR_STEP_TIMINGS_PATH.write_text(
                    json.dumps(prev, indent=2),
                    encoding="utf-8",
                )
                return
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    prof = dict(profile or {})
    prof["run_kind"] = run_kind
    payload = build_time_to_mirror_latency_artifact(
        step_timings_s=step_timings,
        pipeline_latency_s=pipeline_latency_s,
        profile=prof,
    )
    TIME_TO_MIRROR_STEP_TIMINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TIME_TO_MIRROR_STEP_TIMINGS_PATH.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _write_pipeline_done_marker(*, fail_path: Path, done_path: Path) -> None:
    """Record successful pipeline completion; stale global fail must not coexist."""
    try:
        fail_path.unlink()
    except FileNotFoundError:
        pass
    done_path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


def _step_slo_probe_metrics(step_name: str) -> dict[str, Any]:
    if "m8_1_stable_anchor" not in step_name:
        return {}
    if not M81_PROBE_METRICS_PATH.is_file():
        return {}
    try:
        doc = json.loads(M81_PROBE_METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return {
        "rpc_wait_s": doc.get("rpc_wait_s"),
        "provider_errors": int(doc.get("provider_errors") or 0),
        "cache_hits": int(doc.get("cache_hits") or 0),
        "cache_misses": int(doc.get("cache_misses") or 0),
        "routes_per_s": doc.get("routes_per_s"),
    }


def _run_project_pipeline(args: argparse.Namespace) -> int:
    global _CURRENT_PIPELINE_ARGS
    _CURRENT_PIPELINE_ARGS = args
    if str(args.pipeline) == "cross_chain_research" and not getattr(args, "dry_run", False):
        print(
            "ERROR: cross_chain_research is R&D dry-run only; pass --dry-run",
            flush=True,
        )
        return CROSS_CHAIN_RESEARCH_BLOCKED_EXIT

    steps = build_project_pipeline_steps(args)
    step_names = [str(step["name"]) for step in steps]
    pipeline_mode = str(args.pipeline)
    pipeline_session_id = (
        os.environ.get(ENV_PIPELINE_SESSION_ID, "").strip() or new_pipeline_session_id()
    )
    os.environ[ENV_PIPELINE_SESSION_ID] = pipeline_session_id
    streaming = bool(getattr(args, "streaming", False)) or streaming_enabled()
    if streaming:
        os.environ["ARBY_PIPELINE_STREAMING"] = "1"
        os.environ["ARBY_SNIPER_BATCH_MINUTES"] = str(
            int(getattr(args, "sniper_batch_minutes", 15) or 15)
        )
        final_batches = resolve_streaming_batches(
            int(getattr(args, "sniper_minutes", 45) or 45),
            batch_minutes=int(getattr(args, "sniper_batch_minutes", 15) or 15),
        )
        os.environ[ENV_STREAMING_FINAL_BATCH_INDEX] = str(len(final_batches))
        os.environ["ARBY_PIPELINE_MODE"] = batched_m8_refresh_mode(streaming=True)
    slo_tracker = PipelineSloTracker()
    if getattr(args, "resume_from", None):
        slo_tracker.set_resume_context(str(args.resume_from))
    log_path = Path(getattr(args, "pipeline_log", "") or "data/tmp/start_pipeline_latest.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fail_path = Path("data/tmp/start_pipeline_latest.fail")
    done_path = Path("data/tmp/start_pipeline_latest.done")
    for marker in (fail_path, done_path):
        try:
            marker.unlink()
        except FileNotFoundError:
            pass

    if not getattr(args, "dry_run", False):
        cleared = _clear_stale_fail_markers(pipeline_mode, step_names)
        if cleared:
            print(f"Cleared {cleared} stale .fail marker(s) under {PIPELINE_STEP_MARKERS_DIR / pipeline_mode}")

    heartbeat_stale_s = max(
        60.0,
        float(getattr(args, "heartbeat_stale_minutes", DEFAULT_HEARTBEAT_STALE_MINUTES))
        * 60.0,
    )

    print(f"Project pipeline: {args.pipeline} steps={len(steps)} log={log_path}")
    if getattr(args, "dry_run", False):
        _print_rpc_policy_table(steps)
    force_rerun = bool(getattr(args, "force_rerun_steps", False))
    with log_path.open("a", encoding="utf-8", buffering=1) as log_fh:
        log_fh.write(f"=== start_pipeline mode={args.pipeline} ===\n")
        log_fh.write(f"pipeline_session_id={pipeline_session_id}\n")
        log_fh.flush()
        if getattr(args, "resume_from", None):
            log_fh.write(f"resume_from={args.resume_from}\n")
        if getattr(args, "allow_roadmap_edit", False):
            log_fh.write("allow_roadmap_edit=true\n")
        shadow_gate_allowed = True
        final_m82_shadow_allowed = True
        streaming_final_batch_active = int(
            os.environ.get(ENV_STREAMING_FINAL_BATCH_INDEX, "0") or "0"
        ) > 0
        narrow_shadow_allowed = True
        target_m9_allowed = (
            _target_m9_allowed_from_bridge()
            if pipeline_mode == "time_to_mirror"
            else True
        )
        selection_fresh_allowed = True
        record_ttm_timings = pipeline_mode in ("time_to_mirror", "mirror_recall_fast", "mirror_recall_wide")
        ttm_profile = (
            _resolve_time_to_mirror_profile(args) if record_ttm_timings else None
        )
        ttm_t0 = time.monotonic()
        step_timings: dict[str, float] = {}
        for step_index, step in enumerate(steps, start=1):
            name = step["name"]
            step_t0 = time.monotonic()
            queue_delay_s = slo_tracker.begin_step()
            done_marker, fail_marker = _step_marker_paths(name, pipeline_mode=pipeline_mode)
            if (
                not force_rerun
                and _should_skip_done_marker(name, done_marker, force_rerun=force_rerun)
                and not getattr(args, "dry_run", False)
            ):
                if name in {
                    "m9_time_to_mirror_depth_enrich",
                    "m9_time_to_mirror_capacity_diagnostic",
                    "m9_time_to_mirror_narrow_shadow_10m",
                    "gate_time_to_mirror_narrow_shadow",
                } and not target_m9_allowed:
                    msg = (
                        f"skip {name}: target narrow universe gate blocked "
                        "(fresh_long_tail_quote_ready=0 or NON_TARGET)\n"
                    )
                    print(msg.strip())
                    log_fh.write(msg)
                    if record_ttm_timings:
                        step_timings[name] = 0.0
                    continue
                msg = f"skip {name}: prior step marker {done_marker}\n"
                print(msg.strip())
                log_fh.write(msg)
                slo_tracker.record_skipped(name, reason="prior_marker")
                if record_ttm_timings:
                    step_timings[name] = 0.0
                continue
            if name in SELECTION_FRESH_GATED_STEPS and not selection_fresh_allowed:
                msg = (
                    f"skip {name}: selection_verified_fresh_total=0 "
                    "(cross-dex/M8.3 blocked until fresh verified mirrors)\n"
                )
                print(msg.strip())
                log_fh.write(msg)
                if record_ttm_timings:
                    step_timings[name] = 0.0
                continue
            if name in {"m9_shadow_10m", "m9_patient_shadow_10m"} and not shadow_gate_allowed:
                msg = f"skip {name}: capacity gate blocked\n"
                print(msg.strip())
                log_fh.write(msg)
                log_fh.flush()
                continue
            if (
                name in {"m9_shadow_10m", "m9_patient_shadow_10m"}
                and streaming_final_batch_active
                and not final_m82_shadow_allowed
            ):
                msg = f"skip {name}: final M8.2 acceptance blocked upstream handoff\n"
                print(msg.strip())
                log_fh.write(msg)
                log_fh.flush()
                continue
            if name == "m9_time_to_mirror_narrow_shadow_10m" and not narrow_shadow_allowed:
                msg = (
                    f"skip {name}: narrow shadow gate blocked "
                    "(cycles_total/cycles_at_floor/non_target_universe)\n"
                )
                print(msg.strip())
                log_fh.write(msg)
                continue
            if name in {
                "m9_time_to_mirror_depth_enrich",
                "m9_time_to_mirror_capacity_diagnostic",
                "m9_time_to_mirror_narrow_shadow_10m",
                "gate_time_to_mirror_narrow_shadow",
            } and not target_m9_allowed:
                msg = (
                    f"skip {name}: target narrow universe gate blocked "
                    "(fresh_long_tail_quote_ready=0 or NON_TARGET)\n"
                )
                print(msg.strip())
                log_fh.write(msg)
                if record_ttm_timings:
                    step_timings[name] = 0.0
                continue
            cmd = list(step.get("cmd") or [])
            printable = " ".join(cmd) if cmd else f"<internal:{step.get('internal')}>"
            policy = _classify_step_rpc_policy(cmd) if cmd else "internal:local_py"
            timeout_s = _resolve_step_timeout(step, args)
            print(f">>> {name}: {printable}")
            print(f"    rpc_policy: {policy}")
            print(f"    timeout_s: {timeout_s} heartbeat_stale_s: {int(heartbeat_stale_s)}")
            log_fh.write(f">>> {name}: {printable}\n")
            log_fh.write(f"    rpc_policy: {policy}\n")
            log_fh.write(
                f"    timeout_s={timeout_s} heartbeat_stale_s={int(heartbeat_stale_s)}\n"
            )
            log_fh.flush()
            if getattr(args, "dry_run", False):
                continue
            try:
                fail_marker.unlink()
            except FileNotFoundError:
                pass
            rc, fail_reason = _run_pipeline_step_subprocess(
                step,
                mode=str(args.pipeline),
                step_index=step_index,
                step_total=len(steps),
                all_step_names=step_names,
                log_fh=log_fh,
                timeout_s=timeout_s,
                heartbeat_stale_s=heartbeat_stale_s,
            )
            if name == "gate_capacity_shadow":
                shadow_gate_allowed = rc == 0
            if name == "m8_2_acceptance_final_batch" and rc in step["allow_exit_codes"]:
                final_m82_shadow_allowed = final_m82_acceptance_allows_shadow(
                    session_id=pipeline_session_id,
                )
            if name == "gate_time_to_mirror_narrow_shadow":
                narrow_shadow_allowed = rc == 0
            if name == "gate_time_to_mirror_target_universe":
                target_m9_allowed = rc == 0
            if name == "gate_selection_verified_fresh":
                selection_fresh_allowed = rc == 0
            if name == "m8_mirror_discovery_recall" and rc == 0:
                cleared = _clear_recall_downstream_markers(pipeline_mode)
                if cleared:
                    msg = (
                        f"cleared {cleared} recall-downstream marker(s) "
                        f"under {PIPELINE_STEP_MARKERS_DIR / pipeline_mode}\n"
                    )
                    print(msg.strip())
                    log_fh.write(msg)
            if rc not in step["allow_exit_codes"]:
                reason = fail_reason or f"exit={rc}"
                fail_marker.write_text(f"{reason}\n", encoding="utf-8")
                fail_path.write_text(f"{name}: {reason}\n", encoding="utf-8")
                _write_pipeline_current(
                    {
                        "mode": str(args.pipeline),
                        "step": name,
                        "pid": None,
                        "started_at": None,
                        "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                        "status": "failed",
                        "fail_reason": reason,
                        "step_index": step_index,
                        "step_total": len(steps),
                        "checkpoint_progress": _collect_checkpoint_progress(
                            step_names,
                            pipeline_mode=pipeline_mode,
                        ),
                    }
                )
                slo_tracker.mark_failed(name, reason)
                probe_metrics = _step_slo_probe_metrics(name)
                slo_tracker.end_step(
                    name,
                    step_t0,
                    queue_delay_s,
                    status="failed",
                    failure_reason=reason,
                    rpc_wait_s=probe_metrics.get("rpc_wait_s"),
                    provider_errors=int(probe_metrics.get("provider_errors") or 0),
                    cache_hits=int(probe_metrics.get("cache_hits") or 0),
                    cache_misses=int(probe_metrics.get("cache_misses") or 0),
                    routes_per_s=probe_metrics.get("routes_per_s"),
                )
                if not getattr(args, "dry_run", False):
                    slo_tracker.write(
                        session_id=pipeline_session_id,
                        pipeline_mode=pipeline_mode,
                    )
                return rc or 1
            write_done_record(
                done_marker,
                fingerprint=_pipeline_step_fingerprint(name),
            )
            if name in M83_UPSTREAM_INVALIDATING_STEPS:
                cleared_truth = _invalidate_truth_gate_markers(
                    pipeline_mode,
                    upstream=True,
                    bundle=True,
                )
                if cleared_truth:
                    log_fh.write(
                        f"invalidated {cleared_truth} truth-gate marker(s) after {name}\n"
                    )
            if name == "m9_bridge_production":
                cleared_bundle = _invalidate_truth_gate_markers(
                    pipeline_mode,
                    upstream=False,
                    bundle=True,
                )
                if cleared_bundle:
                    log_fh.write(
                        f"invalidated {cleared_bundle} bundle truth-gate marker(s) after bridge build\n"
                    )
            probe_metrics = _step_slo_probe_metrics(name)
            slo_tracker.end_step(
                name,
                step_t0,
                queue_delay_s,
                rpc_wait_s=probe_metrics.get("rpc_wait_s"),
                provider_errors=int(probe_metrics.get("provider_errors") or 0),
                cache_hits=int(probe_metrics.get("cache_hits") or 0),
                cache_misses=int(probe_metrics.get("cache_misses") or 0),
                routes_per_s=probe_metrics.get("routes_per_s"),
            )
            if record_ttm_timings:
                step_timings[name] = round(time.monotonic() - step_t0, 2)
                _write_time_to_mirror_step_timings(
                    step_timings,
                    pipeline_t0=ttm_t0,
                    profile=ttm_profile,
                    run_kind="fresh_run",
                )
        if record_ttm_timings and not getattr(args, "dry_run", False):
            executed_s = sum(float(v or 0.0) for v in step_timings.values())
            run_kind = "fresh_run" if executed_s > 0.0 else "cached_resume"
            _write_time_to_mirror_step_timings(
                step_timings,
                pipeline_t0=ttm_t0,
                profile=ttm_profile,
                run_kind=run_kind,
            )
        if not getattr(args, "dry_run", False):
            slo_tracker.write(session_id=pipeline_session_id, pipeline_mode=pipeline_mode)
        if not getattr(args, "dry_run", False):
            _write_pipeline_done_marker(fail_path=fail_path, done_path=done_path)
            _clear_pipeline_current()
    return 0



# -- main -----------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Multi-chain time-bounded online scan orchestrator"
    )
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument(
        "--config",
        help="Single config file (legacy mode, equivalent to --config-list with one entry)",
    )
    g.add_argument(
        "--config-list",
        help="Comma-separated list of config files for round-robin scanning",
    )
    pg = ap.add_mutually_exclusive_group(required=False)
    pg.add_argument(
        "--pipeline",
        choices=(
            "m8",
            "m8_2",
            "m8_3",
            "m9",
            "m8_m9",
            "full",
            "time_to_mirror",
            "mirror_recall_fast",
            "m8_audit",
            "patient_lane",
            "cross_chain_research",
        ),
        help="Run canonical project-layer pipeline instead of legacy config scan",
    )
    pg.add_argument("-m_8", "--m8", dest="pipeline", action="store_const", const="m8")
    pg.add_argument("-m_8_2", "--m8-2", dest="pipeline", action="store_const", const="m8_2")
    pg.add_argument("-m_8_3", "--m8-3", dest="pipeline", action="store_const", const="m8_3")
    pg.add_argument("-m_9", "--m9", dest="pipeline", action="store_const", const="m9")
    pg.add_argument("-m8_m9", "--m8-m9", dest="pipeline", action="store_const", const="m8_m9")
    pg.add_argument("--full-m8-m9", dest="pipeline", action="store_const", const="full")
    pg.add_argument(
        "-time_to_mirror",
        "--time-to-mirror",
        dest="pipeline",
        action="store_const",
        const="time_to_mirror",
    )
    pg.add_argument(
        "-mirror_recall_fast",
        "--mirror-recall-fast",
        dest="pipeline",
        action="store_const",
        const="mirror_recall_fast",
        help="Fast recall-only lane: pending→expand→on-chain/factory recall (≤180s SLA)",
    )
    pg.add_argument(
        "-mirror_recall_wide",
        "--mirror-recall-wide",
        dest="pipeline",
        action="store_const",
        const="mirror_recall_wide",
        help="Wide DexScreener sidecar: fresh_delta+pending→expand→batched DexScreener recall (≤300s SLA)",
    )
    pg.add_argument(
        "--patient-lane",
        "-patient_lane",
        dest="pipeline",
        action="store_const",
        const="patient_lane",
    )
    pg.add_argument(
        "--cross-chain-research",
        dest="pipeline",
        action="store_const",
        const="cross_chain_research",
        help="R&D placeholder lane (requires --dry-run)",
    )
    pg.add_argument(
        "-m8_audit",
        "--m8-audit",
        dest="pipeline",
        action="store_const",
        const="m8_audit",
        help="Scheduled wide audit lane (M8.1 audit_full + candidate_summary expansion)",
    )
    ap.add_argument("--max-radar-tokens", type=int, default=753)
    ap.add_argument(
        "--hot-lane",
        choices=tuple(HOT_LANE_PROFILES.keys()),
        default=None,
        help="time_to_mirror lane budget: hot_delta (50), warm_recall (150), mirror_recall (753 wide), mirror_recall_fast, mirror_recall_wide, audit_full (753+)",
    )
    ap.add_argument(
        "--skip-secondary",
        action="store_true",
        default=None,
        help="Skip GeckoTerminal/TheGraph secondary radar (default on hot_delta)",
    )
    ap.add_argument(
        "--no-skip-secondary",
        dest="skip_secondary",
        action="store_false",
        help="Allow secondary providers in radar (audit/wide recall)",
    )
    ap.add_argument(
        "--hot",
        dest="time_to_mirror_hot",
        action="store_true",
        default=False,
        help="Time-to-mirror hot_delta profile (≤50 tokens, skip-secondary, 15m SLA)",
    )
    ap.add_argument(
        "--verify-subset-max",
        type=int,
        default=None,
        help="Diagnostic override for scored on-chain verify cap (-time_to_mirror --hot only)",
    )
    ap.add_argument("--sniper-minutes", type=int, default=45)
    ap.add_argument(
        "--streaming",
        action="store_true",
        default=False,
        help=(
            "Batched M8 refresh (batched_m8_refresh): per-batch sniper→M8.1→M8.2→M8.3 "
            "with session-namespaced artifacts, then one M9 pass on the final batch bundle"
        ),
    )
    ap.add_argument(
        "--sniper-batch-minutes",
        type=int,
        default=15,
        help="Per-batch sniper duration when --streaming (default 15)",
    )
    ap.add_argument(
        "--token-concurrency",
        type=int,
        default=4,
        help="Concurrent token workers for M8.2 radar refresh phases",
    )
    ap.add_argument("--skip-shadow", action="store_true", default=False)
    ap.add_argument("--skip-coingecko", action="store_true", default=True)
    ap.add_argument("--with-coingecko", dest="skip_coingecko", action="store_false")
    ap.add_argument("--dry-run", action="store_true", default=False)
    ap.add_argument(
        "--allow-roadmap-edit",
        action="store_true",
        default=False,
        help="Pass --allow-roadmap-edit to check_repo_safety preflight",
    )
    ap.add_argument(
        "--skip-preflight",
        action="store_true",
        default=False,
        help="Skip repo safety / layer audit / RPC endpoint preflight",
    )
    ap.add_argument(
        "--resume-from",
        choices=tuple(RESUME_FROM_FIRST_STEP.keys()),
        default=None,
        help=(
            "Resume pipeline at m8_2, m8_2_radar, m8_onchain_factory_mirror_scan, m8_2_expand, "
            "m8_mirror_quote_reprobe, m8_second_pool_verify, m8_2_acceptance, m8_3, m9, "
            "or m9_capacity"
        ),
    )
    ap.add_argument(
        "--step-timeout-s",
        type=int,
        default=DEFAULT_STEP_TIMEOUT_S,
        help="Default hard timeout per pipeline step (seconds, 0=disable)",
    )
    ap.add_argument(
        "--radar-step-timeout-s",
        type=int,
        default=DEFAULT_RADAR_STEP_TIMEOUT_S,
        help="Hard timeout for m8_2_radar_two_phase (seconds)",
    )
    ap.add_argument(
        "--radar-secondary-provider-timeout-s",
        type=int,
        default=DEFAULT_RADAR_SECONDARY_PROVIDER_TIMEOUT_S,
        help="Per-request provider timeout for radar secondary/coingecko phases (seconds)",
    )
    ap.add_argument(
        "--heartbeat-stale-minutes",
        type=int,
        default=DEFAULT_HEARTBEAT_STALE_MINUTES,
        help="Fail a step when stdout is silent longer than this many minutes",
    )
    ap.add_argument(
        "--force-rerun-steps",
        action="store_true",
        default=False,
        help="Ignore per-step .done markers under data/tmp/start_pipeline_steps/",
    )
    ap.add_argument(
        "--pipeline-log",
        default="data/tmp/start_pipeline_latest.log",
        help="Runtime log for --pipeline/-m_* modes",
    )
    ap.add_argument("--hours", type=float, default=0, help="Time limit in hours (takes precedence over --minutes)")
    ap.add_argument("--minutes", type=int, default=120, help="Time limit in minutes (ignored if --hours set)")
    ap.add_argument("--max-runs", type=int, default=0, help="0 = unlimited within time window")
    ap.add_argument("--sleep-seconds", type=int, default=1)
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--prune-keep", type=int, default=200)
    ap.add_argument(
        "--child-timeout",
        type=int,
        default=600,
        help="Kill child process after this many seconds (0=no timeout)",
    )
    ap.add_argument(
        "--summary-file",
        default="data/runs/_rolling/long_scan_latest.json",
        help="Path to overwrite with session summary JSON (canonical rolling artifact)",
    )
    ap.add_argument(
        "--max-fail-chains",
        type=int,
        default=-1,
        help="Max chains allowed to have failures. -1=permissive (exit 0 if any PASS), "
             "0=strict (all must PASS)",
    )
    ap.add_argument(
        "--accepted-fail-chains",
        default="",
        help="Comma-separated chain names whose failures are expected/accepted "
             "(e.g. 'scroll'). These do not count toward --max-fail-chains.",
    )
    ap.add_argument(
        "--allow-partial-chains",
        action="store_true",
        default=False,
        help="Allow config-list to cover fewer chains than chains.yaml defines. "
             "Downgrades the missing-chains check from FATAL to WARNING.",
    )
    ap.add_argument(
        "--coverage-workers",
        type=int,
        default=2,
        help="Max parallel COVERAGE chain workers (default: 2). "
             "Primary NORMAL chains always run sequentially first.",
    )
    ap.add_argument(
        "--no-dashboard",
        action="store_true",
        default=False,
        help="Disable the dashboard server (dashboard is launched by default)",
    )
    ap.add_argument(
        "--dashboard",
        action="store_true",
        default=False,
        help="(deprecated, now default-on) Kept for backward compatibility",
    )
    ap.add_argument(
        "--dashboard-port",
        type=int,
        default=8099,
        help="Port for the dashboard server (default: 8099)",
    )
    ap.add_argument(
        "--keep-dashboard",
        action="store_true",
        default=False,
        help="Keep dashboard server running after scan completes (default: terminate with scan)",
    )
    ns = ap.parse_args(argv)
    if not ns.pipeline and not ns.config and not ns.config_list:
        ap.error(
            "one of --config, --config-list, --pipeline, -m_8, -m_8_2, "
            "-m_8_3, -m_9, -m8_m9, -time_to_mirror, --patient-lane, "
            "--cross-chain-research is required"
        )
    return ns


def resolve_configs(args: argparse.Namespace) -> list[str]:
    if args.config:
        return [args.config]
    return [c.strip() for c in args.config_list.split(",") if c.strip()]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.pipeline:
        dashboard_proc: subprocess.Popen | None = None
        if not args.no_dashboard:
            dashboard_proc = subprocess.Popen(
                [sys.executable, "-m", "monitoring.dashboard_server", "--port", str(args.dashboard_port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"Dashboard launched: http://127.0.0.1:{args.dashboard_port}")
        try:
            return _run_project_pipeline(args)
        finally:
            if dashboard_proc is not None:
                if args.keep_dashboard:
                    print(f"Dashboard server kept alive (PID {dashboard_proc.pid}): http://127.0.0.1:{args.dashboard_port}")
                else:
                    dashboard_proc.terminate()
                    dashboard_proc.wait(timeout=5)
                    print("Dashboard server stopped.")

    configs = resolve_configs(args)
    if not configs:
        print("ERROR: No config files specified")
        return 1

    # Co-launch dashboard server (default-on; use --no-dashboard to disable)
    dashboard_proc: subprocess.Popen | None = None
    if not args.no_dashboard:
        dashboard_proc = subprocess.Popen(
            [sys.executable, "-m", "monitoring.dashboard_server", "--port", str(args.dashboard_port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Dashboard launched: http://127.0.0.1:{args.dashboard_port}")

    try:
        return _run_scan_loop(args, configs)
    finally:
        if dashboard_proc is not None:
            if args.keep_dashboard:
                print(f"Dashboard server kept alive (PID {dashboard_proc.pid}): http://127.0.0.1:{args.dashboard_port}")
            else:
                dashboard_proc.terminate()
                dashboard_proc.wait(timeout=5)
                print("Dashboard server stopped.")


def _warn_missing_chains(config_meta: dict[str, dict[str, Any]], *, allow_partial: bool = False) -> None:
    """R24→R25→R33: Hard-fail if any chain from chains.yaml is not represented in config-list.

    Prevents silent coverage gaps where a chain is defined but has no config in the scan.
    When allow_partial=True, downgrades to WARNING for single-chain verification.
    """
    chains_yaml = Path("config") / "chains.yaml"
    if not chains_yaml.exists():
        return
    try:
        with open(chains_yaml, encoding="utf-8") as f:
            all_chains = set(yaml.safe_load(f) or {})
    except Exception:
        return
    config_chains = {meta["chain"] for meta in config_meta.values()}
    missing = sorted(all_chains - config_chains)
    if missing:
        if allow_partial:
            print(f"  WARNING: chains.yaml defines {sorted(all_chains)} but config-list covers only {sorted(config_chains)}")
            print(f"  WARNING: missing chains: {missing} (--allow-partial-chains active, continuing)")
        else:
            print(f"  FATAL: chains.yaml defines {sorted(all_chains)} but config-list covers only {sorted(config_chains)}")
            print(f"  FATAL: missing chains: {missing}")
            print("  Add configs for missing chains or remove them from chains.yaml.")
            sys.exit(1)


def _run_scan_loop(args: argparse.Namespace, configs: list[str]) -> int:

    # Pre-read config metadata
    config_meta: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        meta = read_config_meta(cfg)
        config_meta[cfg] = meta
        rolling = "YES" if is_primary_rolling_config(meta) else "no"
        print(f"  [{meta['chain']:16s}] {cfg}  run_kind={meta['run_kind']}  rolling={rolling}")

    # R24→R33: Check config-list coverage against chains.yaml
    # Auto-enable partial when single config (single-chain test/dev use case)
    _allow_partial = args.allow_partial_chains or len(configs) == 1
    _warn_missing_chains(config_meta, allow_partial=_allow_partial)

    # R28.5: Separate primary (NORMAL) and coverage configs
    primary_configs = [cfg for cfg in configs if is_primary_rolling_config(config_meta[cfg])]
    coverage_configs = [cfg for cfg in configs if not is_primary_rolling_config(config_meta[cfg])]
    coverage_workers = max(1, args.coverage_workers)
    print(f"  Primary configs: {len(primary_configs)}  Coverage configs: {len(coverage_configs)}  workers={coverage_workers}")

    # Time budget
    if args.hours > 0:
        budget_seconds = args.hours * 3600
    else:
        budget_seconds = max(1, args.minutes) * 60
    deadline = time.monotonic() + budget_seconds

    # Accepted-fail chain set
    accepted_fail_set = {
        c.strip() for c in args.accepted_fail_chains.split(",") if c.strip()
    }

    # Per-chain stats keyed by chain name
    per_chain: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        chain = config_meta[cfg]["chain"]
        if chain not in per_chain:
            per_chain[chain] = new_chain_stats()
            per_chain[chain]["config"] = cfg
            per_chain[chain]["accepted_fail"] = chain in accepted_fail_set
            per_chain[chain]["blocker_classification"] = config_meta[cfg].get("blocker_classification")
            per_chain[chain]["blocker_reason"] = config_meta[cfg].get("blocker_reason")

    total_runs = 0
    wall_start = time.monotonic()

    # R28.11: WebSocket dirty-set tracker — only re-scan chains with new blocks
    dirty_tracker: Any = None
    try:
        from strategy.infra import DirtySetTracker
        chains_yaml = Path("config") / "chains.yaml"
        _chain_ws: dict[str, str | None] = {}
        if chains_yaml.exists():
            with open(chains_yaml, encoding="utf-8") as _cyf:
                _cy = yaml.safe_load(_cyf) or {}
            for _cn, _cd in _cy.items():
                ws_eps = _cd.get("ws_endpoints") or []
                _chain_ws[_cn] = ws_eps[0] if ws_eps else None
        dirty_tracker = DirtySetTracker()
        for chain in per_chain:
            dirty_tracker.start_watching(chain, _chain_ws.get(chain))
        print(f"  DirtySet: watching {len(per_chain)} chains ({sum(1 for v in _chain_ws.values() if v)} have WSS)")
    except Exception as _ds_err:
        print(f"  DirtySet: disabled ({_ds_err})")
        dirty_tracker = None

    # R39r: Flashblocks sub-block watcher for Base structural advantage
    flashblocks_watcher: Any = None
    try:
        from chains.flashblocks import FlashblocksWatcher, get_flashblocks_ws_url
        # Only start if "base" is in our chain set
        if "base" in per_chain:
            _fb_ws = None
            chains_yaml_fb = Path("config") / "chains.yaml"
            if chains_yaml_fb.exists():
                with open(chains_yaml_fb, encoding="utf-8") as _fbf:
                    _fby = yaml.safe_load(_fbf) or {}
                _fb_ws = _fby.get("base", {}).get("flashblocks_ws_endpoint")
            # Also check per-chain config override
            base_cfg = per_chain.get("base", {}).get("config") or {}
            if isinstance(base_cfg, dict):
                _fb_ws = base_cfg.get("flashblocks_ws_endpoint") or _fb_ws
            # R39r+: Env var ARBY_FLASHBLOCKS_WS overrides config (private provider)
            _fb_ws = get_flashblocks_ws_url(_fb_ws)
            if _fb_ws:
                flashblocks_watcher = FlashblocksWatcher(ws_url=_fb_ws)
                flashblocks_watcher.start()
                print(f"  FlashblocksWatcher: started for base ({_fb_ws})")
            else:
                print("  FlashblocksWatcher: no flashblocks_ws_endpoint for base")
        else:
            print("  FlashblocksWatcher: base not in chain set, skipped")
    except Exception as _fb_err:
        print(f"  FlashblocksWatcher: disabled ({_fb_err})")
        flashblocks_watcher = None

    # R28.13 Step 7: Per-pair hot queue — load cached pairs for immediate re-quote
    pair_hot_queue: Any = None
    try:
        from strategy.infra import PairHotQueue
        pair_hot_queue = PairHotQueue()
        for chain in per_chain:
            hp_file = HOT_PAIRS_CACHE_DIR / f"hot_pairs_{chain}.json"
            if hp_file.is_file():
                with open(hp_file, encoding="utf-8") as _hpf:
                    hp_data = json.load(_hpf)
                pair_hot_queue.load_pairs_for_chain(chain, hp_data.get("pairs", []))
        pq_status = pair_hot_queue.status()
        print(f"  PairHotQueue: {pq_status['chains_loaded']} chains, {pq_status['total_pairs_loaded']} pairs loaded")
    except Exception as _pq_err:
        print(f"  PairHotQueue: disabled ({_pq_err})")
        pair_hot_queue = None

    # R28.5: Thread-safe lock for per_chain stats and stdout
    _stats_lock = threading.Lock()
    _live_lock = threading.Lock()
    _hot_snapshot_lock = threading.Lock()
    _live_events: deque[dict[str, Any]] = deque(maxlen=LIVE_STREAM_MAX_EVENTS)
    _active_runs: dict[str, dict[str, Any]] = {}

    def _append_live_event(
        event: str,
        *,
        chain: str | None = None,
        message: str | None = None,
        **extra: Any,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "event": event,
        }
        if chain:
            entry["chain"] = chain
        if message:
            entry["message"] = message
        for key, value in extra.items():
            if value is not None:
                entry[key] = value
        with _live_lock:
            _live_events.append(entry)

    def _set_active_run(
        chain: str,
        *,
        config: str,
        run_kind: str,
        scan_mode: str,
        is_coverage: bool,
        rolling: bool,
        block_number: int | None = None,
    ) -> None:
        with _live_lock:
            _active_runs[chain] = {
                "chain": chain,
                "config": config,
                "run_kind": run_kind,
                "scan_mode": scan_mode,
                "is_coverage": is_coverage,
                "rolling": rolling,
                "block_number": block_number,
                "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "_started_monotonic": time.monotonic(),
            }

    def _clear_active_run(chain: str) -> None:
        with _live_lock:
            _active_runs.pop(chain, None)

    # R28.17: Detect test-like session to protect rolling artifacts
    _is_test_session = os.environ.get("ARBY_OFFLINE", "") == "1"

    def _write_hot_snapshot() -> None:
        with _live_lock:
            live_events = list(_live_events)
            active_runs = {k: dict(v) for k, v in _active_runs.items()}
        with _hot_snapshot_lock:
            write_hot_loop_snapshot(
                per_chain,
                dirty_tracker,
                wall_start,
                args.summary_file,
                pair_hot_queue,
                live_events=live_events,
                active_runs=active_runs,
                is_test_session=_is_test_session,
                flashblocks_watcher=flashblocks_watcher,
            )

    _append_live_event(
        "session_started",
        message="Multi-chain scan session started",
        config_count=len(configs),
        coverage_workers=args.coverage_workers,
        full_sweep_interval=FULL_SWEEP_INTERVAL,
    )
    _write_hot_snapshot()

    def _run_one_chain(cfg: str, is_coverage: bool = False) -> tuple[int, Path | None, str, str]:
        """Run a single chain scan. Thread-safe for parallel coverage workers."""
        meta = config_meta[cfg]
        chain = meta["chain"]
        expected_chain_id = meta.get("chain_id")
        refresh = is_primary_rolling_config(meta)
        # R28.9: Prefix coverage worker output for log readability
        prefix = f"[{chain}]" if is_coverage else ""

        # R28.11: Hot loop — decide scan mode (full sweep vs hot re-quote)
        extra_env: dict[str, str] | None = None
        scan_mode = "full"
        with _stats_lock:
            chain_stats = per_chain[chain]
            run_count = chain_stats["_run_counter"]
            chain_stats["_run_counter"] = run_count + 1

        # Hot re-quote: skip discovery on non-full-sweep cycles if cache exists
        if run_count > 0 and run_count % FULL_SWEEP_INTERVAL != 0:
            hot_file = HOT_PAIRS_CACHE_DIR / f"hot_pairs_{chain}.json"
            if hot_file.is_file():
                extra_env = {"ARBY_HOT_PAIRS_FILE": str(hot_file)}
                scan_mode = "hot"

        # R28.12: Pass WS-observed block number to child so it skips getBlockNumber RPC
        if dirty_tracker:
            evt = dirty_tracker.drain_event(chain)
            if evt and evt.get("block_number"):
                extra_env = extra_env or {}
                extra_env["ARBY_WS_BLOCK_NUMBER"] = str(evt["block_number"])
                # R28.13 Step 7: Enqueue hot pairs for this block
                if pair_hot_queue:
                    pair_hot_queue.enqueue_chain(chain, evt["block_number"])

        block_number = None
        if extra_env:
            try:
                block_number = int(extra_env.get("ARBY_WS_BLOCK_NUMBER")) if extra_env.get("ARBY_WS_BLOCK_NUMBER") else None
            except Exception:
                block_number = None

        _set_active_run(
            chain,
            config=cfg,
            run_kind=meta["run_kind"],
            scan_mode=scan_mode,
            is_coverage=is_coverage,
            rolling=refresh,
            block_number=block_number,
        )
        _append_live_event(
            "scan_started",
            chain=chain,
            message=f"{scan_mode.upper()} scan started",
            config=cfg,
            run_kind=meta["run_kind"],
            scan_mode=scan_mode,
            is_coverage=is_coverage,
            rolling=refresh,
            block_number=block_number,
        )
        _write_hot_snapshot()

        try:
            # R28.16: Phase callback — pipe child phase events into live stream
            def _on_phase(phase_data: dict) -> None:
                evt = phase_data.get("event", "phase_unknown")
                if evt == "candidate_snapshot":
                    candidates = phase_data.get("candidates") or []
                    with _live_lock:
                        if chain in _active_runs:
                            _active_runs[chain]["verified_pairs"] = candidates[:5]
                    with _stats_lock:
                        per_chain[chain]["last_live_candidates"] = candidates[:5]
                    _append_live_event(
                        "candidate_snapshot",
                        chain=chain,
                        scan_mode=scan_mode,
                        message=f"{len(candidates)} verified pair candidates",
                        candidate_count=len(candidates),
                        verified_pairs=candidates[:5],
                    )
                    _write_hot_snapshot()
                    return
                _append_live_event(
                    f"phase:{evt}",
                    chain=chain,
                    scan_mode=scan_mode,
                    message=f"{evt.replace('_', ' ').title()}",
                    **{k: v for k, v in phase_data.items() if k != "event" and k != "chain"},
                )
                _write_hot_snapshot()

            rc, run_dir = run_gate_once(
                cfg, args.cycles, args.prune_keep, args.sleep_seconds,
                refresh_rolling=refresh,
                timeout_seconds=args.child_timeout,
                line_prefix=prefix,
                extra_env=extra_env,
                phase_callback=_on_phase,
            )

            summary = extract_run_summary(run_dir)
            gate_res = extract_gate_result(run_dir)
            scan_st = extract_scan_stats(run_dir)
            truth = extract_truth_report(run_dir)

            # R28.6: Validate scan artifact chain_id matches config chain
            # Prevents corrupted summary from runDir collisions
            if run_dir and expected_chain_id is not None:
                _validate_chain_id_match(run_dir, expected_chain_id, chain)

            cls = classify_run(rc, summary)

            with _stats_lock:
                update_chain_stats(per_chain[chain], rc, run_dir, summary, gate_res, scan_st, truth)
                # R28.11: Track scan mode for observability
                per_chain[chain]["last_scan_mode"] = scan_mode
                if scan_mode == "hot":
                    per_chain[chain]["hot_requote_count"] += 1
                    # R28.21: Track last hot re-quote timestamp
                    per_chain[chain]["last_hot_requote_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    per_chain[chain]["full_sweep_count"] += 1
                if run_dir and run_dir.exists():
                    if delete_if_empty_run_dir(run_dir):
                        pass  # cleaned up

            rt = (summary or {}).get("metrics", {}).get("roundtrip", {}) or (summary or {}).get("roundtrip_summary", {})
            _clear_active_run(chain)
            _append_live_event(
                "scan_finished",
                chain=chain,
                message=f"{scan_mode.upper()} scan finished: {cls}",
                config=cfg,
                run_kind=meta["run_kind"],
                scan_mode=scan_mode,
                is_coverage=is_coverage,
                rolling=refresh,
                result=cls,
                exit_code=rc,
                run_dir=run_dir.name if run_dir else None,
                signals=(summary or {}).get("metrics", {}).get("included_signals_count"),
                real_quote_count=rt.get("real_quote_count"),
                profitable_roundtrips=rt.get("profitable_count"),
                profit_realism_status=(summary or {}).get("metrics", {}).get("profit_realism_status"),
            )
            _write_hot_snapshot()

            return rc, run_dir, chain, cls
        except Exception as exc:
            _clear_active_run(chain)
            _append_live_event(
                "scan_error",
                chain=chain,
                message=f"{scan_mode.upper()} scan errored",
                config=cfg,
                run_kind=meta["run_kind"],
                scan_mode=scan_mode,
                is_coverage=is_coverage,
                rolling=refresh,
                error=str(exc),
            )
            _write_hot_snapshot()
            raise

    print(f"\nStarting multi-chain scan: {len(configs)} configs, budget={budget_seconds:.0f}s")

    # R28.5: Batched round — primary sequential, then coverage parallel
    while time.monotonic() < deadline:
        # R39r: Inject Flashblocks health into per_chain stats for lane summary
        if flashblocks_watcher and "base" in per_chain:
            per_chain["base"]["flashblocks_healthy"] = flashblocks_watcher.state.is_healthy

        # Phase 1: Run primary (NORMAL) configs sequentially (isolated, rolling-safe)
        # R28.12: Use pending_chains() for priority ordering (earliest-dirty first)
        if dirty_tracker:
            _pending = set(dirty_tracker.pending_chains())
            _ordered_primary = sorted(
                primary_configs,
                key=lambda c: (config_meta[c]["chain"] not in _pending, 0),
            )
        else:
            _ordered_primary = primary_configs

        for cfg in _ordered_primary:
            if time.monotonic() >= deadline:
                break
            chain = config_meta[cfg]["chain"]

            # R28.11: Skip chain if no new block since last scan (dirty-set gate)
            if dirty_tracker and not dirty_tracker.is_dirty(chain):
                continue

            total_runs += 1
            _sm = per_chain.get(chain, {}).get("last_scan_mode", "full")
            print(f"\n{'-'*60}")
            print(f"[run {total_runs}] chain={chain}  config={cfg}  rolling=YES  mode={_sm}  (PRIMARY)")

            rc, run_dir, chain_name, cls = _run_one_chain(cfg)
            _sm = per_chain.get(chain, {}).get("last_scan_mode", "full")
            print(f"[run {total_runs}] result={cls}  exit_code={rc}  mode={_sm}  run_dir={run_dir.name if run_dir else 'N/A'}")

            # R28.11: Mark chain clean after scan (wait for next block)
            if dirty_tracker:
                dirty_tracker.mark_clean(chain)

            # Live update summary for dashboard
            interim_wall = time.monotonic() - wall_start
            interim_warnings = check_guardrails(per_chain)
            interim_summary = build_summary(per_chain, interim_wall, interim_warnings)
            write_summary_file(interim_summary, args.summary_file)

            # R28.12: Write lightweight hot snapshot for fast dashboard refresh
            _write_hot_snapshot()

        # R28.13 Step 7: Per-pair micro-quote — drain dirty pairs, re-quote in-process
        if pair_hot_queue and pair_hot_queue.pending_count() > 0 and time.monotonic() < deadline:
            pending_pairs = pair_hot_queue.pending_count()
            _append_live_event(
                "micro_requote_started",
                message="In-process micro re-quote batch started",
                pending_pairs=pending_pairs,
            )
            _write_hot_snapshot()
            total_micro_quotes = _micro_requote_hot_pairs(pair_hot_queue, config_meta, per_chain, _stats_lock)
            _append_live_event(
                "micro_requote_finished",
                message="In-process micro re-quote batch finished",
                pending_pairs=pending_pairs,
                quoted_pairs=total_micro_quotes,
            )
            _write_hot_snapshot()

        if time.monotonic() >= deadline:
            break

        # Phase 2: Run coverage configs in bounded parallel pool
        if coverage_configs:
            # R28.12: Use pending_chains() for priority filtering
            if dirty_tracker:
                _pending_cov = set(dirty_tracker.pending_chains())
                batch_cfgs = [
                    cfg for cfg in coverage_configs
                    if time.monotonic() < deadline
                    and config_meta[cfg]["chain"] in _pending_cov
                ]
            else:
                batch_cfgs = [
                    cfg for cfg in coverage_configs
                    if time.monotonic() < deadline
                ]
            if batch_cfgs:
                print(f"\n{'-'*60}")
                print(f"[COVERAGE BATCH] {len(batch_cfgs)} chains, workers={coverage_workers}")
                _append_live_event(
                    "coverage_batch_started",
                    message="Coverage batch started",
                    chains=[config_meta[c]["chain"] for c in batch_cfgs],
                    workers=coverage_workers,
                )

                with ThreadPoolExecutor(max_workers=coverage_workers) as pool:
                    futures = {pool.submit(_run_one_chain, cfg, True): cfg for cfg in batch_cfgs}
                    _write_hot_snapshot()
                    for future in as_completed(futures):
                        cfg = futures[future]
                        total_runs += 1
                        try:
                            rc, run_dir, chain_name, cls = future.result()
                            print(f"[run {total_runs}] chain={chain_name}  result={cls}  exit_code={rc}  run_dir={run_dir.name if run_dir else 'N/A'}  (COVERAGE)")
                            # R28.11: Mark chain clean after coverage scan
                            if dirty_tracker:
                                dirty_tracker.mark_clean(chain_name)
                        except Exception as e:
                            print(f"[run {total_runs}] COVERAGE_ERROR: {cfg}: {e}")

                        # R28.9: Write summary after each coverage future for live dashboard
                        interim_wall = time.monotonic() - wall_start
                        interim_warnings = check_guardrails(per_chain)
                        interim_summary = build_summary(per_chain, interim_wall, interim_warnings)
                        write_summary_file(interim_summary, args.summary_file)
                        _write_hot_snapshot()

                # R28.12: Hot loop snapshot after coverage batch
                _append_live_event(
                    "coverage_batch_finished",
                    message="Coverage batch finished",
                    chains=[config_meta[c]["chain"] for c in batch_cfgs],
                    workers=coverage_workers,
                )
                _write_hot_snapshot()

        if total_runs % max(len(configs), 3) == 0:
            prune_run_dirs(args.prune_keep)

        if args.max_runs > 0 and total_runs >= args.max_runs:
            break
        if time.monotonic() >= deadline:
            break

        # R38: Event-driven sleep — use dirty_tracker.wait_for_dirty() when WS
        # is available; orchestrator wakes immediately on new block instead of
        # blind time.sleep().  Falls back to time.sleep() when tracker absent.
        if args.sleep_seconds > 0:
            if dirty_tracker:
                dirty_tracker.wait_for_dirty(timeout=args.sleep_seconds)
            else:
                time.sleep(args.sleep_seconds)

    # Final report
    # R28.11: Stop dirty-set watcher threads
    if dirty_tracker:
        dirty_tracker.stop()

    # R39r: Final Flashblocks health injection before summary
    if flashblocks_watcher and "base" in per_chain:
        per_chain["base"]["flashblocks_healthy"] = flashblocks_watcher.state.is_healthy

    wall_seconds = time.monotonic() - wall_start
    warnings = check_guardrails(per_chain)
    summary_obj = build_summary(per_chain, wall_seconds, warnings)
    print_summary(summary_obj)

    write_summary_file(summary_obj, args.summary_file)
    _append_live_event(
        "session_finished",
        message="Multi-chain scan session finished",
        total_runs=summary_obj.get("total_runs"),
        total_signals=summary_obj.get("total_included_signals"),
        total_profitable_roundtrips=summary_obj.get("total_profitable_roundtrips"),
        wall_seconds=summary_obj.get("wall_seconds"),
    )
    _write_hot_snapshot()

    # Exit semantics — accepted-fail chains don't count toward limit
    unexpected_fail_count = len(summary_obj.get("unexpected_fail_chains", []))
    has_any_pass = summary_obj["total_pass"] > 0

    if args.max_fail_chains >= 0:
        # Strict mode: exit 1 if too many unexpected chains failed
        if unexpected_fail_count > args.max_fail_chains:
            print(f"EXIT 1: {unexpected_fail_count} unexpected fail chain(s) > --max-fail-chains={args.max_fail_chains}")
            return 1
        if not has_any_pass:
            print("EXIT 1: no PASS runs at all")
            return 1
        return 0
    else:
        # Permissive (default): exit 0 if any PASS
        return 0 if has_any_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
