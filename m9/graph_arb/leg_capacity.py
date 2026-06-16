"""Universal leg capacity + continuity contract for all adapter families.

Principle A — Continuity-invariant:
  For leg_index > 0, amount_in MUST equal the previous leg's amount_out.
  Never silently re-cap a propagated amount to a probe/smoke size.

Principle B — Depth/capacity contract:
  When propagated amount exceeds a pool's known capacity, reject honestly with
  LEG_AMOUNT_EXCEEDS_POOL_CAPACITY instead of quoting at the wrong size.

Principle C — Bidirectional probe requirement:
  Routes probed in only one swap direction are marked ONE_DIRECTION_ONLY and
  cannot be used as inter-cycle return legs without an explicit probe for that
  token_in direction.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

REJECT_LEG_AMOUNT_EXCEEDS_POOL_CAPACITY = "LEG_AMOUNT_EXCEEDS_POOL_CAPACITY"
REJECT_ONE_DIRECTION_ONLY = "ONE_DIRECTION_ONLY"
REJECT_NO_DIRECTION_PROBE = "NO_ACTIVE_LIQUIDITY_FOR_TOKEN_IN"

# Instrumentation rejects — NOT market-negative signals.
CAPACITY_INSTRUMENTATION_REJECTS = frozenset(
    {
        REJECT_LEG_AMOUNT_EXCEEDS_POOL_CAPACITY,
        REJECT_ONE_DIRECTION_ONLY,
        REJECT_NO_DIRECTION_PROBE,
    }
)


def _edge_token_in_lc(edge: Any) -> str:
    return str(getattr(edge, "token_in_addr", "") or "").lower()


def maverick_max_quoteable_raw(edge: Any) -> Optional[int]:
    max_raw = getattr(edge, "maverick_max_quoteable_amount_raw", None)
    if max_raw is not None:
        try:
            v = int(max_raw)
            return v if v > 0 else None
        except (TypeError, ValueError):
            pass
    by_tin = getattr(edge, "maverick_probe_by_token_in", None)
    token_in = _edge_token_in_lc(edge)
    if isinstance(by_tin, dict) and token_in in by_tin:
        row = by_tin[token_in] or {}
        try:
            v = int(row.get("maverick_max_quoteable_amount_raw") or 0)
            return v if v > 0 else None
        except (TypeError, ValueError):
            pass
    return None


def maverick_has_direction_probe(edge: Any, token_in: Optional[str] = None) -> bool:
    tin = (token_in or _edge_token_in_lc(edge)).lower()
    by_tin = getattr(edge, "maverick_probe_by_token_in", None)
    if isinstance(by_tin, dict) and tin in by_tin:
        return True
    probe_tin = getattr(edge, "maverick_pool_lane_token_in", None)
    if probe_tin and str(probe_tin).lower() == tin:
        return bool(getattr(edge, "maverick_pool_lane_probe_amount", None))
    return False


def maverick_probe_direction_count(edge: Any) -> int:
    by_tin = getattr(edge, "maverick_probe_by_token_in", None)
    if isinstance(by_tin, dict) and by_tin:
        return len(by_tin)
    if getattr(edge, "maverick_pool_lane_token_in", None):
        return 1
    return 0


def route_probe_direction_status(route: dict) -> str:
    """Return BIDIRECTIONAL, ONE_DIRECTION_ONLY, or NO_PROBE."""
    adapter = str(route.get("adapter_type") or route.get("dex_id") or "").lower()
    if adapter == "maverick_v2":
        by_tin = route.get("maverick_probe_by_token_in")
        if isinstance(by_tin, dict):
            n = len(by_tin)
            if n >= 2:
                return "BIDIRECTIONAL"
            if n == 1:
                return "ONE_DIRECTION_ONLY"
        if route.get("maverick_pool_lane_token_in"):
            return "ONE_DIRECTION_ONLY"
        return "NO_PROBE"
    # Generic: both token0 and token1 must have depth or quote smoke for full cycle use.
    return "UNKNOWN"


def balancer_max_in_raw(edge: Any, amount_in: int) -> Optional[int]:
    from m9.graph_arb.productive_distinct_quote import balancer_cap_amount_in

    adapter = str(getattr(edge, "adapter_type", "") or "")
    if adapter not in ("balancer_stable", "balancer_weighted", "balancer_vault"):
        return None
    assets = getattr(edge, "balancer_assets", None)
    balances = getattr(edge, "balancer_balances", None)
    token_in = getattr(edge, "token_in_addr", None)
    if not assets or not balances or not token_in:
        return None
    capped = balancer_cap_amount_in(
        int(amount_in),
        str(token_in).lower(),
        assets=list(assets),
        balances=list(balances),
    )
    if capped < int(amount_in):
        return capped
    return None


def pool_capacity_overflow_reason(
    edge: Any,
    amount_in: int,
    *,
    leg_index: int = 0,
) -> Optional[str]:
    """Return reject reason when *amount_in* exceeds known pool capacity."""
    if amount_in <= 0:
        return None
    adapter = str(getattr(edge, "adapter_type", "") or "")

    if adapter == "maverick_v2":
        if leg_index > 0 and not maverick_has_direction_probe(edge):
            return REJECT_ONE_DIRECTION_ONLY if maverick_probe_direction_count(edge) == 1 else REJECT_NO_DIRECTION_PROBE
        max_raw = maverick_max_quoteable_raw(edge)
        if max_raw is not None and int(amount_in) > int(max_raw):
            return REJECT_LEG_AMOUNT_EXCEEDS_POOL_CAPACITY
        return None

    if adapter in ("balancer_stable", "balancer_weighted", "balancer_vault"):
        if leg_index == 0:
            return None
        cap = balancer_max_in_raw(edge, int(amount_in))
        if cap is not None and int(amount_in) > int(cap):
            return REJECT_LEG_AMOUNT_EXCEEDS_POOL_CAPACITY
        return None

    return None


def resolve_leg_amount_in(
    edge: Any,
    amount_in: int,
    *,
    leg_index: int = 0,
    size_usd: Optional[float] = None,
) -> Tuple[int, Optional[str]]:
    """Resolve the amount to quote for one cycle leg under the continuity contract.

    Returns (resolved_amount_in, reject_reason).  When reject_reason is set the
    caller must NOT issue an RPC quote — the cycle cannot be evaluated honestly
    at this propagated size.
    """
    amount = max(int(amount_in), 0)
    adapter = str(getattr(edge, "adapter_type", "") or "")

    # Principle C — direction probe must exist for this token_in on inter-cycle legs.
    if leg_index > 0 and adapter == "maverick_v2":
        if not maverick_has_direction_probe(edge):
            n = maverick_probe_direction_count(edge)
            if n == 1:
                return amount, REJECT_ONE_DIRECTION_ONLY
            return amount, REJECT_NO_DIRECTION_PROBE

    # Principle A — never cap propagated amounts on leg > 0.
    if leg_index > 0:
        overflow = pool_capacity_overflow_reason(edge, amount, leg_index=leg_index)
        if overflow:
            return amount, overflow
        return max(amount, 1), None

    # Leg 0 — family-specific bootstrap/cap is allowed (cycle entry sizing).
    if adapter == "maverick_v2":
        from m9.graph_arb.productive_distinct_quote import maverick_cycle_amount_in

        resolved = maverick_cycle_amount_in(
            amount,
            pool_lane_probe_amount=getattr(edge, "maverick_pool_lane_probe_amount", None),
            min_quoteable=getattr(edge, "maverick_min_quoteable_amount_raw", None),
            max_quoteable=getattr(edge, "maverick_max_quoteable_amount_raw", None),
            leg_index=0,
            size_usd=size_usd,
            token_in_decimals=getattr(edge, "token_in_decimals", None),
        )
        return max(resolved, 1), None

    if adapter in ("balancer_stable", "balancer_weighted", "balancer_vault"):
        assets = getattr(edge, "balancer_assets", None)
        balances = getattr(edge, "balancer_balances", None)
        token_in = getattr(edge, "token_in_addr", None)
        if assets and balances and token_in:
            from m9.graph_arb.productive_distinct_quote import balancer_cap_amount_in

            return balancer_cap_amount_in(
                amount,
                str(token_in).lower(),
                assets=list(assets),
                balances=list(balances),
            ), None

    return amount, None


def cap_leg_amount_in_for_edge(
    edge: Any,
    amount_in: int,
    *,
    leg_index: int = 0,
    size_usd: Optional[float] = None,
) -> int:
    """Backward-compatible cap helper — returns amount only (no reject).

    Prefer ``resolve_leg_amount_in`` in new code paths.  This wrapper preserves
    leg-0 bootstrap behaviour and the continuity-invariant for leg > 0.
    """
    resolved, _reject = resolve_leg_amount_in(
        edge, amount_in, leg_index=leg_index, size_usd=size_usd
    )
    return resolved


def is_instrumentation_reject(reject_reason: Optional[str]) -> bool:
    return (reject_reason or "") in CAPACITY_INSTRUMENTATION_REJECTS
