"""Artifact builder and writer for M9 graph-arb scanner."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from m9.graph_arb.models import CycleQuoteResult, GraphTopology

SCHEMA_FAMILY = "m9_graph_arb"
SCHEMA_REVISION = "m9.1"
ROLLING_PATH = "data/runs/_rolling/m9_graph_latest.json"

# Economics gate statuses
_ECON_BLOCKED_NO_CYCLES = "BLOCKED_NO_CYCLES"
_ECON_BLOCKED_QSR = "BLOCKED_QSR"
_ECON_NEAR_MISS = "NEAR_MISS"
_ECON_BLOCKED_NO_POSITIVE_GROSS = "BLOCKED_NO_POSITIVE_GROSS"
_ECON_PASS = "PASS"


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_cycle_summary(qr: CycleQuoteResult) -> Dict[str, Any]:
    cycle = qr.cycle
    return {
        "cycle_id": cycle.cycle_id,
        "length": cycle.length,
        "token_path": cycle.token_path,
        "start_token": cycle.start_token_sym,
        "total_fee_bps": round(cycle.total_fee_bps, 4),
        "min_factory_class": cycle.min_factory_class,
        "size_usd": qr.size_usd,
        "amount_in": qr.amount_in,
        "amount_out": qr.amount_out,
        "gross_bps": round(qr.gross_bps, 4),
        "status": qr.status,
        "reject_reason": qr.reject_reason,
        "elapsed_s": round(qr.elapsed_s, 3),
    }


def build_artifact(
    chain: str,
    duration_minutes: float,
    cycle_results: List[CycleQuoteResult],
    topology: GraphTopology,
    sizes_usd: "tuple[float, ...]",
    run_timestamp: str,
    started_at_mono: float,
    elapsed_s: float,
    execution_mode: str = "shadow",
    gas_mode: str = "static",
    inventory_path: str = "",
    config_path: str = "",
    sweeps_completed: int = 0,
    scan_scope: str = "graph_arb",
    process_id: Optional[int] = None,
    python_executable: Optional[str] = None,
    venv_active: bool = False,
) -> Dict[str, Any]:
    """Build the canonical M9 rolling artifact dict."""

    cycles_found = len(cycle_results)
    cycles_positive_gross = sum(
        1 for qr in cycle_results if qr.gross_bps > 0
    )
    cycles_router_sim_eligible = sum(
        1 for qr in cycle_results
        if qr.gross_bps > 0 and qr.status == "POSITIVE_GROSS"
    )
    best_cycle_net_bps: Optional[float] = None
    if cycle_results:
        best = max(cycle_results, key=lambda qr: qr.gross_bps)
        best_cycle_net_bps = round(best.gross_bps, 4)

    # QSR: quote success rate
    quoted = [qr for qr in cycle_results if qr.status not in ("ZERO_AMOUNT_IN",)]
    qsr = (
        sum(1 for qr in quoted if qr.status not in ("QUOTE_FAILED", "CYCLE_QUOTE_TIMEOUT"))
        / len(quoted)
        if quoted
        else 0.0
    )

    # Economics gate
    if cycles_found == 0:
        econ_status = _ECON_BLOCKED_NO_CYCLES
    elif qsr < 0.5:
        econ_status = _ECON_BLOCKED_QSR
    elif cycles_positive_gross == 0:
        econ_status = _ECON_BLOCKED_NO_POSITIVE_GROSS
    elif best_cycle_net_bps is not None and 0 < best_cycle_net_bps < 5:
        econ_status = _ECON_NEAR_MISS
    else:
        econ_status = _ECON_PASS

    gate_acceptance = econ_status == _ECON_PASS

    # Build top cycles summary (up to 10 best)
    top_cycles = sorted(cycle_results, key=lambda qr: -qr.gross_bps)[:10]

    return {
        "schema_family": SCHEMA_FAMILY,
        "schema_revision": SCHEMA_REVISION,
        "run_timestamp": run_timestamp,
        "chain": chain,
        "execution_mode": execution_mode,
        "gas_mode": gas_mode,
        "scan_scope": scan_scope,
        "inventory_path": inventory_path,
        "config_path": config_path,
        "process_id": process_id,
        "python_executable": python_executable,
        "venv_active": venv_active,
        "sweeps_completed": sweeps_completed,
        "duration_minutes": duration_minutes,
        "duration_fulfilled": elapsed_s >= duration_minutes * 60 * 0.9,
        "elapsed_s": round(elapsed_s, 1),
        "sizes_usd": list(sizes_usd),
        "topology": {
            "token_count": topology.token_count,
            "edge_count": topology.edge_count,
            "route_count": topology.route_count,
            "hub_tokens": topology.hub_tokens,
            "dead_end_tokens": topology.dead_end_tokens[:10],
        },
        "cycles_found": cycles_found,
        "cycles_positive_gross": cycles_positive_gross,
        "cycles_router_sim_eligible": cycles_router_sim_eligible,
        "best_cycle_net_bps": best_cycle_net_bps,
        "qsr": round(qsr, 4),
        "economics_gate_status": econ_status,
        "gate_acceptance": gate_acceptance,
        "top_cycles": [_build_cycle_summary(qr) for qr in top_cycles],
    }


def write_artifact(artifact: Dict[str, Any], artifact_path: str = ROLLING_PATH) -> None:
    """Write artifact atomically to artifact_path (via .tmp rename)."""
    path = os.path.abspath(artifact_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)
    os.replace(tmp_path, path)
