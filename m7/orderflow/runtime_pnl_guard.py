"""E1.58 fix step #6: Runtime PnL guard / max-loss kill-switch.

Tracks the cumulative simulated net PnL across rolling windows and
flips ``kill_switch_active=True`` when the cumulative loss exceeds
``ARBY_MAX_LOSS_WEI``.  This module is purely advisory at the rollup
level — it never aborts the live process.  The kill-switch flag is
consumed by the execution gate and submission paths, which already
default to refusing real submits.

Public contract:

  * ``DEFAULT_MAX_LOSS_WEI`` — module-level constant (1_000_000_000 wei
    by default — extremely conservative for an offline paper-signing
    soak).  Override via ``ARBY_MAX_LOSS_WEI`` env var.
  * ``apply_runtime_pnl_guard(rollup, *, window_pnl_wei) -> dict`` —
    mutates ``rollup`` in-place and also returns it.  Adds keys:
        * ``runtime_pnl_cumulative_wei`` (int)
        * ``runtime_pnl_window_count`` (int)
        * ``kill_switch_active`` (bool)
        * ``runtime_pnl_max_loss_wei`` (int) — currently configured threshold
        * ``runtime_pnl_blocker`` (str|None) — "MAX_LOSS_EXCEEDED" or None
  * ``reset_runtime_pnl(rollup) -> dict`` — resets cumulative PnL and
    clears the kill-switch flag.  Triggered when ``ARBY_PNL_GUARD_RESET=1``.

Reasonable defaults make this safe to enable in offline soaks: when
the cumulative simulated PnL stays positive (or trivially negative),
the rollup is a strict superset of the existing schema.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


# Conservative default: 1 gwei equivalent in wei terms (i.e. 1e9).
# In real deployments this should be set to a meaningful loss budget.
DEFAULT_MAX_LOSS_WEI: int = 1_000_000_000


def _max_loss_wei() -> int:
    raw = os.environ.get("ARBY_MAX_LOSS_WEI")
    if raw is None or not raw.strip():
        return DEFAULT_MAX_LOSS_WEI
    try:
        v = int(raw.strip())
        if v < 0:
            return DEFAULT_MAX_LOSS_WEI
        return v
    except (TypeError, ValueError):
        return DEFAULT_MAX_LOSS_WEI


def _reset_requested() -> bool:
    return os.environ.get("ARBY_PNL_GUARD_RESET", "0").strip() == "1"


def reset_runtime_pnl(rollup: Dict[str, Any]) -> Dict[str, Any]:
    """Clear cumulative PnL state and the kill-switch flag.

    Called explicitly when the operator wants a fresh PnL window
    (e.g. after deploying a fix or rotating wallets).  The function
    also clears ``runtime_pnl_blocker``.
    """
    rollup["runtime_pnl_cumulative_wei"] = 0
    rollup["runtime_pnl_window_count"] = 0
    rollup["kill_switch_active"] = False
    rollup["runtime_pnl_blocker"] = None
    rollup["runtime_pnl_reset_requested"] = True
    return rollup


def apply_runtime_pnl_guard(
    rollup: Dict[str, Any],
    *,
    window_pnl_wei: Optional[int],
) -> Dict[str, Any]:
    """Update cumulative PnL and flip kill-switch on excess loss.

    ``window_pnl_wei`` is the simulated net PnL produced in the current
    rollup window (positive == profit, negative == loss).  ``None`` is
    treated as zero (no signal in this window).

    The function is idempotent w.r.t. an already-active kill-switch:
    once flipped, ``kill_switch_active`` stays True until either an
    explicit reset or a recovery (cumulative PnL climbs back above
    the negative threshold).
    """
    if _reset_requested():
        return reset_runtime_pnl(rollup)

    pnl = 0
    if window_pnl_wei is not None:
        try:
            pnl = int(window_pnl_wei)
        except (TypeError, ValueError):
            pnl = 0

    cumulative = int(rollup.get("runtime_pnl_cumulative_wei", 0) or 0) + pnl
    window_count = int(rollup.get("runtime_pnl_window_count", 0) or 0) + 1

    threshold = _max_loss_wei()
    rollup["runtime_pnl_cumulative_wei"] = cumulative
    rollup["runtime_pnl_window_count"] = window_count
    rollup["runtime_pnl_max_loss_wei"] = threshold

    # Kill-switch trips when cumulative PnL is below -threshold.
    if cumulative < -threshold:
        rollup["kill_switch_active"] = True
        rollup["runtime_pnl_blocker"] = "MAX_LOSS_EXCEEDED"
    else:
        # Recovery: clear the flag *only* if not already set by another guard.
        # We honor any external True (e.g. profile sets kill_switch_active=true
        # by default in offline paper soaks) — only clear if we set it.
        if rollup.get("runtime_pnl_blocker") == "MAX_LOSS_EXCEEDED":
            rollup["kill_switch_active"] = False
            rollup["runtime_pnl_blocker"] = None

    return rollup
