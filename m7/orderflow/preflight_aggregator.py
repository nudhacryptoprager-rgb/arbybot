"""E1.59 step #8: aggregator for ``run_preflight`` outcomes.

The E1.58 ``m7.orderflow.preflight`` module returns a list of blocker
reasons per candidate. This thin aggregator collects those across the
lifetime of a process so the rollup writer can surface:

  * total candidates that ran preflight,
  * total that passed (no blockers),
  * total blocked,
  * counts per blocker reason prefix (``PREFLIGHT_*``),
  * recent blocker samples (capped, with router/owner/token context).

Default OFF — gated by the same ``ARBY_EXECUTION_PREFLIGHT=1`` flag the
preflight module respects, so when the operator has not opted in this
aggregator stays a no-op.

Public API:
  * ``record(blockers, *, router, token_in, owner, amount_wei, candidate_id)``
  * ``snapshot()`` -> dict
  * ``reset()``
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Optional


def is_enabled() -> bool:
    return os.environ.get("ARBY_EXECUTION_PREFLIGHT", "0") == "1"


_STATS = {
    "candidates_total": 0,
    "passed_total": 0,
    "blocked_total": 0,
}
_REASON_COUNTS: Dict[str, int] = {}
_RECENT_BLOCKERS: List[Dict[str, Any]] = []
_RECENT_CAP = 30


def _reason_prefix(reason: str) -> str:
    """Normalize ``PREFLIGHT_BALANCE_INSUFFICIENT:5<10`` -> ``PREFLIGHT_BALANCE_INSUFFICIENT``."""
    if not reason:
        return "PREFLIGHT_UNKNOWN"
    return reason.split(":", 1)[0]


def record(
    blockers: Iterable[str],
    *,
    router: Optional[str] = None,
    token_in: Optional[str] = None,
    owner: Optional[str] = None,
    amount_wei: Optional[int] = None,
    candidate_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Record one preflight outcome.

    Returns a small summary dict (always — even when feature flag OFF)::

        {"blocked": bool, "blocker_count": int, "passed": bool}
    """
    blockers_list = list(blockers or [])
    out = {
        "blocked": bool(blockers_list),
        "blocker_count": len(blockers_list),
        "passed": not blockers_list,
    }
    if not is_enabled():
        return out
    _STATS["candidates_total"] += 1
    if blockers_list:
        _STATS["blocked_total"] += 1
        for r in blockers_list:
            prefix = _reason_prefix(r)
            _REASON_COUNTS[prefix] = _REASON_COUNTS.get(prefix, 0) + 1
        if len(_RECENT_BLOCKERS) >= _RECENT_CAP:
            _RECENT_BLOCKERS.pop(0)
        _RECENT_BLOCKERS.append(
            {
                "candidate_id": candidate_id,
                "router": router,
                "token_in": token_in,
                "owner": owner,
                "amount_wei": amount_wei,
                "blockers": blockers_list,
            }
        )
    else:
        _STATS["passed_total"] += 1
    return out


def snapshot() -> Dict[str, Any]:
    return {
        "candidates_total": _STATS["candidates_total"],
        "passed_total": _STATS["passed_total"],
        "blocked_total": _STATS["blocked_total"],
        "reason_counts": dict(_REASON_COUNTS),
        "recent_blockers": list(_RECENT_BLOCKERS),
    }


def reset() -> None:
    for k in ("candidates_total", "passed_total", "blocked_total"):
        _STATS[k] = 0
    _REASON_COUNTS.clear()
    _RECENT_BLOCKERS.clear()


reset_for_tests = reset


__all__ = ["is_enabled", "record", "reset", "reset_for_tests", "snapshot"]
