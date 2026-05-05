"""E1.59 step #9: 1-wei canary dry-run rehearsal aggregator.

Reviewer 3h-soak finding: ``runtime_pnl_guard`` and ``canary_submitter``
exist as scaffolds but are never exercised in soak telemetry. This module
wires them together so an operator can run a *rehearsal* during a
paper-signing soak:

  1. Preflight checks (already aggregated by ``preflight_aggregator``).
  2. ``submit_canary`` in dry_run mode returns a synthetic tx_hash.
  3. ``apply_runtime_pnl_guard`` is invoked with a synthetic
     ``window_pnl_wei`` so the guard's kill-switch logic is exercised.

The aggregator records each rehearsal outcome and exposes a snapshot
suitable for the rollup writer. NO real signing or submission happens —
we explicitly forbid that until the operator opts into live execution.

Default OFF — opt-in via ``ARBY_CANARY_REHEARSAL=1``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from execution.canary_submitter import submit_canary
from m7.orderflow.runtime_pnl_guard import apply_runtime_pnl_guard


def is_enabled() -> bool:
    return os.environ.get("ARBY_CANARY_REHEARSAL", "0") == "1"


_STATS = {
    "rehearsals_total": 0,
    "canary_dry_run_submitted": 0,
    "canary_rejected": 0,
    "pnl_guard_kill_switch_trips": 0,
    "pnl_guard_passes": 0,
}
_RECENT: List[Dict[str, Any]] = []
_RECENT_CAP = 20


def reset() -> None:
    for k in _STATS:
        _STATS[k] = 0
    _RECENT.clear()


reset_for_tests = reset


def rehearse(
    *,
    owner: str,
    chain: str,
    rollup: Dict[str, Any],
    window_pnl_wei: int = 0,
    amount_wei: int = 1,
    candidate_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one paper rehearsal: canary dry-run + pnl-guard apply.

    Args:
      owner / chain / amount_wei: forwarded to ``submit_canary`` (dry_run=True).
      rollup: a dict the pnl-guard mutates in place — pass a copy if
        the caller wants the original to remain untouched.
      window_pnl_wei: synthetic PnL delta to feed the guard.

    Returns a dict::

        {
          "ok": bool,
          "canary": {...},
          "pnl_guard": {...},  # subset of guard fields
          "candidate_id": ...,
        }

    When the feature flag is OFF, the helpers are still invoked (so
    callers can use this synchronously) but no aggregation is recorded.
    """
    canary = submit_canary(
        w3=None,
        owner=owner,
        chain=chain,
        amount_wei=amount_wei,
        dry_run=True,
    )
    apply_runtime_pnl_guard(rollup, window_pnl_wei=window_pnl_wei)
    pnl_guard_summary = {
        "kill_switch_active": bool(rollup.get("kill_switch_active", False)),
        "runtime_pnl_cumulative_wei": int(rollup.get("runtime_pnl_cumulative_wei", 0) or 0),
        "runtime_pnl_blocker": rollup.get("runtime_pnl_blocker"),
    }
    out = {
        "ok": canary.get("status") == "dry_run_submitted"
        and not pnl_guard_summary["kill_switch_active"],
        "canary": canary,
        "pnl_guard": pnl_guard_summary,
        "candidate_id": candidate_id,
    }
    if not is_enabled():
        return out
    _STATS["rehearsals_total"] += 1
    if canary.get("status") == "dry_run_submitted":
        _STATS["canary_dry_run_submitted"] += 1
    else:
        _STATS["canary_rejected"] += 1
    if pnl_guard_summary["kill_switch_active"]:
        _STATS["pnl_guard_kill_switch_trips"] += 1
    else:
        _STATS["pnl_guard_passes"] += 1
    if len(_RECENT) >= _RECENT_CAP:
        _RECENT.pop(0)
    _RECENT.append(out)
    return out


def snapshot() -> Dict[str, Any]:
    return {
        "rehearsals_total": _STATS["rehearsals_total"],
        "canary_dry_run_submitted": _STATS["canary_dry_run_submitted"],
        "canary_rejected": _STATS["canary_rejected"],
        "pnl_guard_kill_switch_trips": _STATS["pnl_guard_kill_switch_trips"],
        "pnl_guard_passes": _STATS["pnl_guard_passes"],
        "recent_rehearsals": list(_RECENT),
    }


__all__ = [
    "is_enabled",
    "rehearse",
    "reset",
    "reset_for_tests",
    "snapshot",
]
