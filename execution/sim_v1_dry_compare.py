"""E1.59 step #4: feature-gated ``eth_simulateV1`` backend with dry compare.

Reviewer 3h-soak finding: heavy ``rpc_fork`` simulation is the bottleneck
(``cold_immediate_sim_revert_total=248`` PROD, plus HTTP 408 samples). Base's
``eth_simulateV1`` is much faster but its accuracy versus a forked-state
simulator must be measured before swapping.

This module is a *dry-compare* harness: callers run both backends per
candidate and we record agreement/divergence statistics. Acceptance is
explicit (operator decision) — we never auto-promote ``eth_simulateV1`` to
canonical without recorded evidence.

Default OFF — opt-in via ``ARBY_SIM_V1_DRY_COMPARE=1``.

Public API:
  * ``compare_results(rpc_fork_result, sim_v1_result, *, candidate_id)`` ->
    SimCompareSample
  * ``stats()`` -> aggregate dict (samples_total, agree, disagree by reason)
  * ``reset_stats()``

Reference:
  https://docs.base.org/base-chain/api-reference/flashblocks-api/eth_simulateV1
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("execution.sim_v1_dry_compare")


def is_enabled() -> bool:
    return os.environ.get("ARBY_SIM_V1_DRY_COMPARE", "0") == "1"


@dataclass
class SimResult:
    """Common outcome shape for both rpc_fork and sim_v1."""
    success: bool
    revert_reason: Optional[str] = None
    profit_bps: Optional[float] = None
    gas_used: Optional[int] = None


@dataclass
class SimCompareSample:
    candidate_id: str
    rpc_fork: SimResult
    sim_v1: SimResult
    agree_success: bool
    agree_revert_reason: bool
    bps_delta: Optional[float] = None  # rpc_fork.profit_bps - sim_v1.profit_bps


_STATS = {
    "samples_total": 0,
    "agree_success_count": 0,
    "disagree_success_count": 0,
    "agree_revert_reason_count": 0,
    "disagree_revert_reason_count": 0,
    "rpc_fork_only_success": 0,
    "sim_v1_only_success": 0,
    "bps_delta_abs_sum": 0.0,
    "bps_delta_samples": 0,
    "bps_delta_max_abs": 0.0,
}
_RECENT_DISAGREE: List[Dict[str, Any]] = []
_RECENT_DISAGREE_CAP = 30


def reset_stats() -> None:
    for k in (
        "samples_total",
        "agree_success_count",
        "disagree_success_count",
        "agree_revert_reason_count",
        "disagree_revert_reason_count",
        "rpc_fork_only_success",
        "sim_v1_only_success",
        "bps_delta_samples",
    ):
        _STATS[k] = 0
    _STATS["bps_delta_abs_sum"] = 0.0
    _STATS["bps_delta_max_abs"] = 0.0
    _RECENT_DISAGREE.clear()


def compare_results(
    rpc_fork_result: SimResult,
    sim_v1_result: SimResult,
    *,
    candidate_id: str,
) -> SimCompareSample:
    """Compare two simulation backends and record agreement statistics.

    No-op (returns sample but does not record) when the feature flag is
    disabled, so callers can stay backend-agnostic.
    """
    rf = rpc_fork_result
    sv = sim_v1_result
    agree_success = bool(rf.success) == bool(sv.success)

    def _norm_reason(r: Optional[str]) -> Optional[str]:
        if not r:
            return None
        # Take up to the first 2 colon-separated segments so
        # "REVERT:STF:0xabc" and "REVERT:STF:0xdef" match while
        # "REVERT:STF" and "REVERT:OUT_OF_GAS" don't.
        parts = r.split(":")
        return ":".join(parts[:2]) if parts else r

    rf_reason = _norm_reason(rf.revert_reason)
    sv_reason = _norm_reason(sv.revert_reason)
    agree_reason = rf_reason == sv_reason

    bps_delta: Optional[float] = None
    if rf.profit_bps is not None and sv.profit_bps is not None:
        bps_delta = float(rf.profit_bps) - float(sv.profit_bps)

    sample = SimCompareSample(
        candidate_id=candidate_id,
        rpc_fork=rf,
        sim_v1=sv,
        agree_success=agree_success,
        agree_revert_reason=agree_reason,
        bps_delta=bps_delta,
    )

    if not is_enabled():
        return sample

    _STATS["samples_total"] += 1
    if agree_success:
        _STATS["agree_success_count"] += 1
    else:
        _STATS["disagree_success_count"] += 1
        if rf.success and not sv.success:
            _STATS["rpc_fork_only_success"] += 1
        elif sv.success and not rf.success:
            _STATS["sim_v1_only_success"] += 1
    if agree_reason:
        _STATS["agree_revert_reason_count"] += 1
    else:
        _STATS["disagree_revert_reason_count"] += 1

    if bps_delta is not None:
        abs_d = abs(bps_delta)
        _STATS["bps_delta_abs_sum"] += abs_d
        _STATS["bps_delta_samples"] += 1
        if abs_d > _STATS["bps_delta_max_abs"]:
            _STATS["bps_delta_max_abs"] = abs_d

    if not agree_success or not agree_reason:
        if len(_RECENT_DISAGREE) >= _RECENT_DISAGREE_CAP:
            _RECENT_DISAGREE.pop(0)
        _RECENT_DISAGREE.append(
            {
                "candidate_id": candidate_id,
                "rpc_fork_success": rf.success,
                "sim_v1_success": sv.success,
                "rpc_fork_revert": rf.revert_reason,
                "sim_v1_revert": sv.revert_reason,
                "bps_delta": bps_delta,
            }
        )

    return sample


def stats() -> dict:
    """Return aggregate compare stats plus mean abs bps delta."""
    out = dict(_STATS)
    if out["bps_delta_samples"] > 0:
        out["bps_delta_abs_mean"] = round(
            out["bps_delta_abs_sum"] / out["bps_delta_samples"], 4
        )
    else:
        out["bps_delta_abs_mean"] = None
    out["recent_disagree_samples"] = list(_RECENT_DISAGREE)
    # Step 7: explicit pending/latest sim state mode fields so reviewer
    # can confirm which chain-state each backend targets.
    # rpc_fork uses flashblocks pending-state when ARBY_FLASHBLOCKS_SIM=1,
    # otherwise it forks at the latest committed block.
    _flashblocks = os.environ.get("ARBY_FLASHBLOCKS_SIM", "0") == "1"
    out["rpc_fork_state_mode"] = "pending" if _flashblocks else "latest"
    out["sim_v1_state_mode"] = "pending"   # eth_simulateV1 always targets the pending block
    return out


__all__ = [
    "SimResult",
    "SimCompareSample",
    "compare_results",
    "is_enabled",
    "reset_stats",
    "stats",
]
