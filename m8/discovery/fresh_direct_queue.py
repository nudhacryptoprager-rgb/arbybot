"""Fresh-direct cohort state queue (M8 discovery → M9 quote handoff)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Mapping, Optional

__all__ = [
    "FreshDirectState",
    "FreshDirectQueue",
    "build_fresh_direct_queue_snapshot",
    "max_snapshot_state",
    "transition_fresh_direct_state",
]


class FreshDirectState(str, Enum):
    DISCOVERED = "discovered"
    ANCHOR_VALID = "anchor_valid"
    MIRROR_PENDING = "mirror_pending"
    MIRROR_VERIFIED = "mirror_verified"
    METADATA_READY = "metadata_ready"
    GRAPH_CYCLE = "graph_cycle"
    QUOTED = "quoted"
    REJECTED = "rejected"


_STATE_ORDER = (
    FreshDirectState.DISCOVERED,
    FreshDirectState.ANCHOR_VALID,
    FreshDirectState.MIRROR_PENDING,
    FreshDirectState.MIRROR_VERIFIED,
    FreshDirectState.METADATA_READY,
    FreshDirectState.GRAPH_CYCLE,
    FreshDirectState.QUOTED,
)

_STATE_RANK = {state: idx for idx, state in enumerate(_STATE_ORDER)}

_ALLOWED_TRANSITIONS: Dict[FreshDirectState, frozenset[FreshDirectState]] = {
    FreshDirectState.DISCOVERED: frozenset(
        {FreshDirectState.ANCHOR_VALID, FreshDirectState.REJECTED}
    ),
    FreshDirectState.ANCHOR_VALID: frozenset(
        {
            FreshDirectState.MIRROR_PENDING,
            FreshDirectState.METADATA_READY,
            FreshDirectState.REJECTED,
        }
    ),
    FreshDirectState.MIRROR_PENDING: frozenset(
        {FreshDirectState.MIRROR_VERIFIED, FreshDirectState.REJECTED}
    ),
    FreshDirectState.MIRROR_VERIFIED: frozenset(
        {FreshDirectState.METADATA_READY, FreshDirectState.REJECTED}
    ),
    FreshDirectState.METADATA_READY: frozenset(
        {FreshDirectState.GRAPH_CYCLE, FreshDirectState.REJECTED}
    ),
    FreshDirectState.GRAPH_CYCLE: frozenset(
        {FreshDirectState.QUOTED, FreshDirectState.REJECTED}
    ),
    FreshDirectState.QUOTED: frozenset(),
    FreshDirectState.REJECTED: frozenset(),
}


def max_snapshot_state(*states: FreshDirectState) -> FreshDirectState:
    """Deterministic max state for route snapshots — order-independent."""
    if not states:
        return FreshDirectState.DISCOVERED
    non_rejected = [s for s in states if s != FreshDirectState.REJECTED]
    if not non_rejected:
        return FreshDirectState.REJECTED
    return max(non_rejected, key=lambda s: _STATE_RANK.get(s, -1))


def transition_fresh_direct_state(
    current: FreshDirectState,
    target: FreshDirectState,
) -> FreshDirectState:
    if current == target:
        return target
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if target in allowed:
        return target
    try:
        cur_idx = _STATE_ORDER.index(current)
        tgt_idx = _STATE_ORDER.index(target)
    except ValueError:
        raise ValueError(
            f"invalid fresh-direct transition {current.value} -> {target.value}"
        ) from None
    if tgt_idx <= cur_idx:
        raise ValueError(
            f"invalid fresh-direct transition {current.value} -> {target.value}"
        )
    state = current
    for step in _STATE_ORDER[cur_idx + 1 : tgt_idx + 1]:
        state = transition_fresh_direct_state(state, step)
    return state


def _derive_route_state(route: Mapping[str, Any]) -> FreshDirectState:
    if route.get("m8_3_preflight_applied"):
        return FreshDirectState.METADATA_READY
    if route.get("mirror_of"):
        return FreshDirectState.MIRROR_VERIFIED
    if route.get("verified_mirror") is False:
        return FreshDirectState.MIRROR_PENDING
    if route.get("factory_verified"):
        return FreshDirectState.ANCHOR_VALID
    return FreshDirectState.DISCOVERED


class FreshDirectQueue:
    """In-memory cohort queue keyed by pool address."""

    def __init__(self) -> None:
        self._rows: Dict[str, Dict[str, Any]] = {}

    def assign_from_route_snapshot(
        self,
        pool_address: str,
        *,
        state: FreshDirectState,
        route_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Advance cohort state for explicit live queue updates."""
        key = str(pool_address or "").lower()
        row = dict(self._rows.get(key) or {})
        prev_raw = row.get("state")
        prev = (
            FreshDirectState(prev_raw)
            if prev_raw in FreshDirectState._value2member_map_
            else FreshDirectState.DISCOVERED
        )
        row["pool_address"] = key
        row["state"] = transition_fresh_direct_state(prev, state).value
        if route_id:
            row["route_id"] = route_id
        if reason:
            row["reason"] = reason
        self._rows[key] = row
        return row

    def set_snapshot_state(
        self,
        pool_address: str,
        *,
        state: FreshDirectState,
        route_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Set pool state from aggregated snapshot (no transition replay)."""
        key = str(pool_address or "").lower()
        row = dict(self._rows.get(key) or {})
        prev_raw = row.get("state")
        prev = (
            FreshDirectState(prev_raw)
            if prev_raw in FreshDirectState._value2member_map_
            else None
        )
        merged = max_snapshot_state(*(s for s in (prev, state) if s is not None))
        row["pool_address"] = key
        row["state"] = merged.value
        if route_id:
            row["route_id"] = route_id
        self._rows[key] = row
        return row

    def snapshot(self) -> Dict[str, Any]:
        by_state: Dict[str, int] = {s.value: 0 for s in FreshDirectState}
        for row in self._rows.values():
            by_state[str(row.get("state") or FreshDirectState.DISCOVERED.value)] += 1
        return {
            "total_pools": len(self._rows),
            "by_state": by_state,
            "rows": list(self._rows.values()),
        }


def _route_is_fresh_direct(route: Mapping[str, Any]) -> bool:
    return str(route.get("source") or "") == "m8_sniper"


def build_fresh_direct_queue_snapshot(
    *,
    bridge: Optional[Mapping[str, Any]] = None,
    shadow: Optional[Mapping[str, Any]] = None,
    registry: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Derive cohort queue counters from bridge/shadow/registry artifacts."""
    routes = [
        r
        for r in ((bridge or {}).get("active_routes") or [])
        if _route_is_fresh_direct(r)
    ]
    pool_states: Dict[str, list[FreshDirectState]] = {}
    pool_route_ids: Dict[str, str] = {}
    for route in routes:
        pool = str(route.get("pool_address") or "").lower()
        if not pool:
            continue
        pool_states.setdefault(pool, []).append(_derive_route_state(route))
        rid = str(route.get("route_id") or "").strip()
        if rid:
            pool_route_ids[pool] = rid

    queue = FreshDirectQueue()
    for pool, states in pool_states.items():
        queue.set_snapshot_state(
            pool,
            state=max_snapshot_state(*states),
            route_id=pool_route_ids.get(pool),
        )

    snap = queue.snapshot()
    snap["tokens"] = len(
        {
            str(route.get(tok) or "").lower()
            for route in routes
            for tok in ("token0", "token1")
            if route.get(tok)
        }
    )
    snap["pools"] = len(
        {str(r.get("pool_address") or "").lower() for r in routes if r.get("pool_address")}
    )
    snap["routes"] = len(routes)
    snap["mirrors"] = sum(1 for r in routes if r.get("mirror_of") or r.get("verified_mirror"))
    snap["cycles_found"] = int(
        (shadow or {}).get("m8_direct_cycles_found")
        or (shadow or {}).get("cycles_with_direct_sniper_pool")
        or 0
    )
    snap["cycles_quoteable"] = int((shadow or {}).get("m8_direct_cycles_quoteable") or 0)
    snap["registry_tokens"] = len((registry or {}).get("tokens") or [])
    return snap
