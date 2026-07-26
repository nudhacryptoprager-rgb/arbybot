"""Terminal runner paths — capacity mismatch and effective inventory prep failure."""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

EXIT_CAPACITY_UNIVERSE_MISMATCH = 7
EXIT_EFFECTIVE_INVENTORY_PREP_FAILED = 8
BLOCKER_EFFECTIVE_INVENTORY_PREP_FAILED = "EFFECTIVE_INVENTORY_PREP_FAILED"

__all__ = [
    "BLOCKER_EFFECTIVE_INVENTORY_PREP_FAILED",
    "EXIT_CAPACITY_UNIVERSE_MISMATCH",
    "EXIT_EFFECTIVE_INVENTORY_PREP_FAILED",
    "validate_capacity_universe_or_exit",
    "write_capacity_universe_mismatch_artifact",
    "write_effective_inventory_prep_failed_artifact",
]


def write_capacity_universe_mismatch_artifact(
    *,
    args: argparse.Namespace,
    log: Any,
    run_timestamp: str,
    started_at: float,
    inventory_path: str,
    capacity_scope: Dict[str, Any],
    capacity_doc: Dict[str, Any],
    runner_contract: Dict[str, Any],
    mismatches: List[str],
    process_id: int,
    duration_minutes: float,
) -> None:
    """Emit canonical shadow artifact when capacity universe contract mismatches runner."""
    from core.pipeline_provenance import apply_pipeline_provenance
    from m9.graph_arb.artifacts import build_artifact, write_artifact
    from m9.graph_arb.models import GraphTopology
    from m9.graph_arb.universe_contract import BLOCKER_CAPACITY_UNIVERSE_MISMATCH

    artifact_path = getattr(
        args, "artifact_path", "data/runs/_rolling/m9_graph_latest.json"
    )
    empty_topology = GraphTopology(
        token_count=0,
        edge_count=0,
        route_count=0,
        hub_tokens=[],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    cap_contract = (capacity_doc or {}).get("universe_contract") or {}
    artifact = build_artifact(
        chain=args.chain,
        duration_minutes=duration_minutes,
        cycle_results=[],
        topology=empty_topology,
        sizes_usd=tuple(getattr(args, "sizes_usd", None) or (100.0,)),
        run_timestamp=run_timestamp,
        started_at_mono=started_at,
        elapsed_s=time.monotonic() - started_at,
        sweeps_completed=0,
        process_id=process_id,
        python_executable=sys.executable,
        venv_active=bool(os.environ.get("VIRTUAL_ENV")),
        cycles_found_topology=0,
        inventory_path=inventory_path,
        config_path=args.config,
        capacity_scope={
            **capacity_scope,
            "universe_mismatch_keys": list(mismatches),
            "capacity_universe_contract": cap_contract,
        },
        scan_scope={
            "shadow_lane_blocker": BLOCKER_CAPACITY_UNIVERSE_MISMATCH,
            "universe_mismatch_keys": list(mismatches),
        },
    )
    artifact["runner_outcome"] = BLOCKER_CAPACITY_UNIVERSE_MISMATCH
    artifact["shadow_lane_blocker"] = BLOCKER_CAPACITY_UNIVERSE_MISMATCH
    artifact["universe_mismatch_keys"] = list(mismatches)
    artifact["capacity_universe_contract"] = cap_contract
    provenance_out = apply_pipeline_provenance(artifact, run_timestamp=run_timestamp)
    artifact.update(provenance_out)
    artifact["universe_contract"] = dict(runner_contract)
    write_artifact(artifact, artifact_path)
    log.info(
        "Wrote capacity universe mismatch artifact: mismatches=%s path=%s",
        mismatches,
        artifact_path,
    )


def validate_capacity_universe_or_exit(
    *,
    args: argparse.Namespace,
    log: Any,
    cap_path_str: str,
    cap_doc: Dict[str, Any],
    capacity_scope: Dict[str, Any],
    inventory_path: str,
    cycle_lengths: tuple[int, ...],
    active_profile: str,
    run_timestamp: str,
    started_at: float,
    process_id: int,
    duration_minutes: float,
) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    from m9.graph_arb.universe_contract import (
        build_runner_admission_graph_fingerprint,
        build_universe_contract,
        resolve_session_id,
        validate_capacity_for_runner,
    )

    pool_lane = "productive" if getattr(args, "productive_lane", False) else "discovery"
    require_fv = bool(getattr(args, "require_factory_verified", False))
    graph_fp = build_runner_admission_graph_fingerprint(
        inventory_path=inventory_path,
        config_path=args.config,
        lane=pool_lane,
        require_factory_verified=require_fv,
    )
    runner_contract = build_universe_contract(
        inventory_path=inventory_path,
        config_path=args.config,
        lane=pool_lane,
        require_factory_verified=require_fv,
        cycle_lengths=cycle_lengths,
        active_economics_profile=active_profile,
        session_id=resolve_session_id(getattr(args, "session_id", None)),
        graph_fingerprint=graph_fp,
    )
    capacity_scope["universe_contract"] = runner_contract
    ok, mismatches = validate_capacity_for_runner(
        cap_doc,
        runner_contract,
        require_session_binding=True,
    )
    if ok:
        return runner_contract, None
    log.error(
        "CAPACITY_UNIVERSE_MISMATCH: mismatches=%s path=%s effective_inventory=%s",
        mismatches,
        cap_path_str,
        inventory_path,
    )
    write_capacity_universe_mismatch_artifact(
        args=args,
        log=log,
        run_timestamp=run_timestamp,
        started_at=started_at,
        inventory_path=inventory_path,
        capacity_scope=capacity_scope,
        capacity_doc=cap_doc,
        runner_contract=runner_contract,
        mismatches=mismatches,
        process_id=process_id,
        duration_minutes=duration_minutes,
    )
    return runner_contract, EXIT_CAPACITY_UNIVERSE_MISMATCH


def write_effective_inventory_prep_failed_artifact(
    *,
    args: argparse.Namespace,
    log: Any,
    run_timestamp: str,
    started_at: float,
    inventory_path: str,
    failure_reason: str,
    process_id: int,
    duration_minutes: float,
) -> None:
    from m9.graph_arb.artifacts import build_artifact, write_artifact
    from m9.graph_arb.models import GraphTopology
    from m9.graph_arb.runner_provenance import stamp_runner_completion_provenance
    from m9.graph_arb.universe_contract import resolve_session_id

    artifact_path = getattr(
        args, "artifact_path", "data/runs/_rolling/m9_graph_latest.json"
    )
    empty_topology = GraphTopology(
        token_count=0,
        edge_count=0,
        route_count=0,
        hub_tokens=[],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )
    artifact = build_artifact(
        chain=args.chain,
        duration_minutes=duration_minutes,
        cycle_results=[],
        topology=empty_topology,
        sizes_usd=tuple(getattr(args, "sizes_usd", None) or (100.0,)),
        run_timestamp=run_timestamp,
        started_at_mono=started_at,
        elapsed_s=time.monotonic() - started_at,
        sweeps_completed=0,
        process_id=process_id,
        python_executable=sys.executable,
        venv_active=bool(os.environ.get("VIRTUAL_ENV")),
        inventory_path=inventory_path,
        config_path=args.config,
        scan_scope={
            "shadow_lane_blocker": BLOCKER_EFFECTIVE_INVENTORY_PREP_FAILED,
            "effective_inventory_prep_failure": failure_reason,
        },
    )
    artifact["runner_outcome"] = BLOCKER_EFFECTIVE_INVENTORY_PREP_FAILED
    artifact["shadow_lane_blocker"] = BLOCKER_EFFECTIVE_INVENTORY_PREP_FAILED
    artifact["effective_inventory_prep_failure"] = failure_reason
    stamp_runner_completion_provenance(
        artifact,
        run_timestamp=run_timestamp,
        universe_contract=None,
        inventory_path=inventory_path,
        session_id=resolve_session_id(getattr(args, "session_id", None)),
    )
    write_artifact(artifact, artifact_path)
    log.error(
        "Effective inventory preparation failed: %s (path=%s)",
        failure_reason,
        inventory_path,
    )
