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
from collections import deque
import json
import subprocess
import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import re

import yaml

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility (existing tests import from start)
# ---------------------------------------------------------------------------
from strategy.run_artifact_extract import (  # noqa: F401
    extract_run_summary,
    extract_gate_result,
    extract_scan_stats,
    extract_truth_report,
    validate_chain_id_match as _validate_chain_id_match,
    delete_if_empty_run_dir,
    prune_run_dirs,
    CI_M5_DIR_RE,
)
from strategy.chain_stats import (  # noqa: F401
    classify_run,
    new_chain_stats,
    _compute_blocker_evidence,
    update_chain_stats,
    check_guardrails,
    SANE_ROUNDTRIP_PNL_BPS_MAX,
    SANE_ROUNDTRIP_PNL_BPS_MIN,
)
from strategy.long_scan_summary import (  # noqa: F401
    _roundtrip_accounting_is_sane,
    classify_chain_profit_state,
    _compute_median,
    build_summary,
    _compute_truth_path_alignment,
    _compute_per_chain_drift_summary,
    _compute_universe_split,
    _compute_kpi_separation,
    _compute_profit_truth_summary,
    _compute_frontier_ranking,
)
from strategy.rolling_outputs import (  # noqa: F401
    print_summary,
    write_summary_file,
    _micro_requote_hot_pairs,
    write_hot_loop_snapshot,
    _serialize_live_stream,
    HOT_LOOP_LATEST,
    FULL_SWEEP_INTERVAL,
    LIVE_STREAM_MAX_EVENTS,
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
M9_SHADOW_ARTIFACT = "data/tmp/m9_graph_handoff_quote_validation_10m.json"
M9_PATIENT_SHADOW_ARTIFACT = "data/tmp/m9_patient_lane_shadow_10m.json"
M9_RCA_ARTIFACT = "data/tmp/m9_quote_lane_rca_graph_handoff_latest.json"
PIPELINE_STEP_MARKERS_DIR = Path("data/tmp/start_pipeline_steps")
RESUME_FROM_FIRST_STEP: dict[str, str] = {
    "m8_2": "m8_2_radar_two_phase",
    "m8_3": "m8_3_registry_refresh",
    "m9": "m9_curve_discovery",
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


def _step_marker_paths(step_name: str) -> tuple[Path, Path]:
    PIPELINE_STEP_MARKERS_DIR.mkdir(parents=True, exist_ok=True)
    return (
        PIPELINE_STEP_MARKERS_DIR / f"{step_name}.done",
        PIPELINE_STEP_MARKERS_DIR / f"{step_name}.fail",
    )


def _classify_step_rpc_policy(cmd: list[str]) -> str:
    joined = " ".join(cmd)
    if "bootstrap_productive_rpc_env.py" in joined:
        return "productive_rpc:alchemy_primary+dRPC_secondary"
    if "m8_radar_two_phase_refresh.py" in joined:
        return "direct:DexScreener/async+multicall (no bootstrap)"
    if joined.endswith("check_rpc_endpoints.py") or "check_rpc_endpoints.py --chain" in joined:
        return "preflight:HTTP+WS archive probe"
    return "direct:local_py"


def _preflight_steps() -> list[dict[str, Any]]:
    return [
        _pipeline_step("preflight_repo_safety", _py_cmd("scripts/check_repo_safety.py")),
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
        print(f"  - {step['name']}: {policy}{ws_note}")


def _pipeline_step(
    name: str,
    cmd: Iterable[str],
    *,
    allow_exit_codes: tuple[int, ...] = (0,),
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "cmd": list(cmd),
        "allow_exit_codes": allow_exit_codes,
        "env": dict(env or {}),
    }


def build_project_pipeline_steps(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Build the canonical M8/M8.2/M8.3/M9 operation plan.

    This keeps M8/M9 orchestration centralized while leaving the legacy M4/M5
    config scanner path intact.
    """
    mode = str(getattr(args, "pipeline", "") or "")
    max_radar = str(int(getattr(args, "max_radar_tokens", 753) or 753))
    sniper_minutes = str(int(getattr(args, "sniper_minutes", 45) or 45))
    skip_coingecko = bool(getattr(args, "skip_coingecko", True))
    include_shadow = not bool(getattr(args, "skip_shadow", False))

    steps: list[dict[str, Any]] = []

    def add_m8() -> None:
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
        steps.append(
            _pipeline_step(
                "m8_1_stable_anchor",
                _productive_rpc_cmd("scripts/m8_1_stable_anchor_run.py"),
            )
        )

    def add_m82() -> None:
        radar_cmd = _py_cmd(
            "scripts/m8_radar_two_phase_refresh.py",
            "--max-tokens",
            max_radar,
            "--lane-mode",
            "fresh_first",
            "--skip-acceptance",
        )
        if skip_coingecko:
            radar_cmd.append("--skip-coingecko")
        steps.append(_pipeline_step("m8_2_radar_two_phase", radar_cmd))
        steps.append(
            _pipeline_step(
                "gate_fresh_delta_subset",
                _py_cmd("scripts/m9_production_refresh_gates.py", "fresh_delta_subset"),
            )
        )
        steps.append(
            _pipeline_step(
                "m8_2_cross_dex_expand",
                _py_cmd("scripts/m8_cross_dex_expand.py", "--chain", "base"),
            )
        )
        steps.append(
            _pipeline_step(
                "m8_2_acceptance_strict",
                _py_cmd("scripts/m8_2_acceptance_report.py", "--strict"),
            )
        )

    def add_m83() -> None:
        steps.append(
            _pipeline_step(
                "m8_3_registry_refresh",
                _productive_rpc_cmd(
                    "scripts/m8_3_token_metadata_registry_refresh.py",
                    "--chain",
                    "base",
                    "--task-mode",
                    "aggregated",
                    "--with-dex-workers",
                ),
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
        steps.append(_pipeline_step("m9_curve_discovery", _productive_rpc_cmd("scripts/m9_curve_discovery.py")))
        steps.append(
            _pipeline_step(
                "m9_bridge_curve_probe_for_indices",
                _py_cmd(
                    "scripts/m9_bridge_build.py",
                    "--graph-handoff-only",
                    "--no-registry",
                    "--include-expansion-duplicates-for-shadow",
                    "--metadata-registry",
                    "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
                    "--output",
                    "data/tmp/m9_bridge_curve_probe.json",
                    "--no-enforce-m8-provenance",
                ),
                env={"ARBY_M9_CURVE_ADMIT_ALL": "1"},
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
        steps.append(
            _pipeline_step(
                "m9_bridge_production",
                _py_cmd(
                    "scripts/m9_bridge_build.py",
                    "--metadata-registry",
                    "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
                    "--output",
                    PRODUCTION_BRIDGE,
                    "--no-enforce-m8-provenance",
                ),
                env={"ARBY_CURVE_POOL_INDICES": "data/runs/_rolling/m9_curve_pool_indices_latest.json"},
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
        steps.append(
            _pipeline_step(
                "m9_topology_diagnostic",
                _py_cmd("scripts/m9_graph_topology_diagnostic.py", "--inventory", PRODUCTION_BRIDGE, "--cycle-lengths", "2,3,4"),
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
                    env={"ARBY_M9_CYCLE_LENGTHS": "2,3,4"},
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
                    M9_SHADOW_ARTIFACT,
                    "--rca",
                    M9_RCA_ARTIFACT,
                ),
            )
        )

    def add_time_to_mirror() -> None:
        """Lane A: fresh radar → mirror verify → M8.3 metadata for handoff candidates."""
        add_m82()
        add_m83()

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
                ),
                env={
                    "ARBY_M9_CYCLE_LENGTHS": "2,3,4",
                    "ARBY_M9_ECONOMICS_PROFILE": "diagnostic_near_econ",
                    "ARBY_M9_PATIENT_LANE": "1",
                    "ARBY_BRIDGE_ARTIFACT_MODE": "exploration_debug",
                },
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
    elif mode == "patient_lane":
        add_patient_lane()
    elif mode in {"m8_m9", "full"}:
        add_m8()
        add_m82()
        add_m83()
        add_m9()
    else:
        raise ValueError(f"unknown pipeline mode: {mode}")

    plan = list(steps)
    if not getattr(args, "skip_preflight", False):
        plan = _preflight_steps() + plan
    resume_from = getattr(args, "resume_from", None)
    if resume_from:
        plan = _filter_steps_for_resume(plan, str(resume_from))
    return plan


def _run_project_pipeline(args: argparse.Namespace) -> int:
    steps = build_project_pipeline_steps(args)
    log_path = Path(getattr(args, "pipeline_log", "") or "data/tmp/start_pipeline_latest.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fail_path = Path("data/tmp/start_pipeline_latest.fail")
    done_path = Path("data/tmp/start_pipeline_latest.done")
    for marker in (fail_path, done_path):
        try:
            marker.unlink()
        except FileNotFoundError:
            pass

    print(f"Project pipeline: {args.pipeline} steps={len(steps)} log={log_path}")
    if getattr(args, "dry_run", False):
        _print_rpc_policy_table(steps)
    force_rerun = bool(getattr(args, "force_rerun_steps", False))
    with log_path.open("a", encoding="utf-8") as log_fh:
        log_fh.write(f"=== start_pipeline mode={args.pipeline} ===\n")
        if getattr(args, "resume_from", None):
            log_fh.write(f"resume_from={args.resume_from}\n")
        shadow_gate_allowed = True
        for step in steps:
            name = step["name"]
            done_marker, fail_marker = _step_marker_paths(name)
            if (
                not force_rerun
                and done_marker.exists()
                and not getattr(args, "dry_run", False)
            ):
                msg = f"skip {name}: prior step marker {done_marker}\n"
                print(msg.strip())
                log_fh.write(msg)
                continue
            if name in {"m9_shadow_10m", "m9_patient_shadow_10m"} and not shadow_gate_allowed:
                msg = f"skip {name}: capacity gate blocked\n"
                print(msg.strip())
                log_fh.write(msg)
                continue
            cmd = list(step["cmd"])
            printable = " ".join(cmd)
            policy = _classify_step_rpc_policy(cmd)
            print(f">>> {name}: {printable}")
            print(f"    rpc_policy: {policy}")
            log_fh.write(f">>> {name}: {printable}\n")
            log_fh.write(f"    rpc_policy: {policy}\n")
            if getattr(args, "dry_run", False):
                continue
            try:
                fail_marker.unlink()
            except FileNotFoundError:
                pass
            env = os.environ.copy()
            env.update(step.get("env") or {})
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                log_fh.write(line)
            rc = proc.wait()
            log_fh.write(f"<<< {name}: exit={rc}\n")
            if name == "gate_capacity_shadow":
                shadow_gate_allowed = rc == 0
            if rc not in step["allow_exit_codes"]:
                fail_marker.write_text(f"exit={rc}\n", encoding="utf-8")
                fail_path.write_text(f"{name}: exit={rc}\n", encoding="utf-8")
                return rc or 1
            done_marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
        if not getattr(args, "dry_run", False):
            done_path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
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
            "patient_lane",
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
        "--patient-lane",
        "-patient_lane",
        dest="pipeline",
        action="store_const",
        const="patient_lane",
    )
    ap.add_argument("--max-radar-tokens", type=int, default=753)
    ap.add_argument("--sniper-minutes", type=int, default=45)
    ap.add_argument("--skip-shadow", action="store_true", default=False)
    ap.add_argument("--skip-coingecko", action="store_true", default=True)
    ap.add_argument("--with-coingecko", dest="skip_coingecko", action="store_false")
    ap.add_argument("--dry-run", action="store_true", default=False)
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
        help="Resume pipeline at m8_2, m8_3, or m9 anchor step",
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
            "-m_8_3, -m_9, -m8_m9, -time_to_mirror, --patient-lane is required"
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
            print(f"  Add configs for missing chains or remove them from chains.yaml.")
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
    empty_deleted = 0
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
