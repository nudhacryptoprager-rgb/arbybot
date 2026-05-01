"""M7.E1.51 slice-1: local V3 pool price state derived from Swap logs.

Goal: avoid ``eth_call slot0`` per pool by harvesting ``sqrtPriceX96``,
``tick`` and ``liquidity`` directly from the V3 ``Swap`` event payload that
the indexer already receives via ``eth_subscribe logs`` /
``getLogs``.

This module is **purely additive** and does not modify the public
``OrderflowEvent`` contract. It can be wired to the hot lane in a later
slice without touching the existing fast-path/profit-guard code.

Schema notes
------------
V3 Swap event::

    Swap(address sender, address recipient, int256 amount0, int256 amount1,
         uint160 sqrtPriceX96, uint128 liquidity, int24 tick)

Non-indexed payload (``log["data"]``) layout (5 x 32 bytes):

    [  0:64  )  amount0       (int256)
    [ 64:128 )  amount1       (int256)
    [128:192 )  sqrtPriceX96  (uint160 right-padded in 32B word)
    [192:256 )  liquidity     (uint128 right-padded in 32B word)
    [256:320 )  tick          (int24 right-padded in 32B word)

This matches the parser in ``m7/orderflow/events.py`` which already
validates the ``len(data_hex) >= 320`` invariant.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# uint160 max — sqrtPriceX96 is uint160 but stored in a 32B word (high 12B = 0)
_UINT160_MASK = (1 << 160) - 1
# uint128 max — liquidity is uint128 in a 32B word (high 16B = 0)
_UINT128_MASK = (1 << 128) - 1
# uint112 max — V2 reserves
_UINT112_MASK = (1 << 112) - 1


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class V3PoolState:
    """Snapshot of a Uniswap V3 / Aerodrome Slipstream pool right after a Swap."""

    pool_address: str
    sqrt_price_x96: int
    tick: int
    liquidity: int
    block_number: int
    log_index: int
    chain: str
    captured_at: str  # ISO-8601 UTC

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # ints can grow huge — keep as native int; JSON encoder will widen
        return d


@dataclass(frozen=True)
class V2PoolState:
    """Snapshot of a Uniswap V2 / Aerodrome v2 / Velodrome ve33 pool right after a Sync."""

    pool_address: str
    reserve0: int  # uint112
    reserve1: int  # uint112
    block_number: int
    log_index: int
    chain: str
    captured_at: str  # ISO-8601 UTC

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

def _decode_int256(hex_str: str) -> int:
    val = int(hex_str, 16)
    if val >= (1 << 255):
        val -= (1 << 256)
    return val


def _decode_int24(hex_str: str) -> int:
    """Decode a 32B word containing a signed int24 (right-aligned, sign-extended)."""
    val = int(hex_str, 16)
    # Stored as int256 with sign-extension to full 32B — same path as int256.
    if val >= (1 << 255):
        val -= (1 << 256)
    return val


def decode_v3_swap_log_state(
    log: Any,
    chain: str,
) -> Optional[V3PoolState]:
    """Decode a raw V3 Swap log into a :class:`V3PoolState`.

    Returns ``None`` if the log payload is malformed. Never raises.
    """
    try:
        addr = log["address"]
        pool_address = addr.lower() if hasattr(addr, "lower") else str(addr).lower()
        block_number = int(log["blockNumber"])
        log_index_raw = log.get("logIndex", 0)
        log_index = int(log_index_raw) if log_index_raw is not None else 0

        data = log["data"]
        if hasattr(data, "hex"):
            data_hex = data.hex()
        else:
            data_hex = data if isinstance(data, str) else str(data)
        if data_hex.startswith("0x"):
            data_hex = data_hex[2:]

        if len(data_hex) < 320:
            return None

        # amounts are not stored here — slice-1 only persists post-trade state
        sqrt_price_raw = int(data_hex[128:192], 16) & _UINT160_MASK
        liquidity_raw = int(data_hex[192:256], 16) & _UINT128_MASK
        tick = _decode_int24(data_hex[256:320])

        # sqrtPriceX96 == 0 is a malformed/empty word — reject
        if sqrt_price_raw == 0:
            return None

        captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return V3PoolState(
            pool_address=pool_address,
            sqrt_price_x96=sqrt_price_raw,
            tick=tick,
            liquidity=liquidity_raw,
            block_number=block_number,
            log_index=log_index,
            chain=chain,
            captured_at=captured_at,
        )
    except Exception:
        return None


def decode_v2_sync_log_state(
    log: Any,
    chain: str,
) -> Optional[V2PoolState]:
    """Decode a raw V2 ``Sync(uint112,uint112)`` log into :class:`V2PoolState`.

    V2 ``Sync`` event payload (non-indexed, 2 x 32 bytes):

        [  0:64  )  reserve0  (uint112 right-padded in 32B word)
        [ 64:128 )  reserve1  (uint112 right-padded in 32B word)

    Returns ``None`` on malformed payload. Never raises.
    """
    try:
        addr = log["address"]
        pool_address = addr.lower() if hasattr(addr, "lower") else str(addr).lower()
        block_number = int(log["blockNumber"])
        log_index_raw = log.get("logIndex", 0)
        log_index = int(log_index_raw) if log_index_raw is not None else 0

        data = log["data"]
        if hasattr(data, "hex"):
            data_hex = data.hex()
        else:
            data_hex = data if isinstance(data, str) else str(data)
        if data_hex.startswith("0x"):
            data_hex = data_hex[2:]

        if len(data_hex) < 128:
            return None

        reserve0 = int(data_hex[0:64], 16) & _UINT112_MASK
        reserve1 = int(data_hex[64:128], 16) & _UINT112_MASK

        # Both-zero reserves are not a useful pricing signal — reject.
        if reserve0 == 0 and reserve1 == 0:
            return None

        captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return V2PoolState(
            pool_address=pool_address,
            reserve0=reserve0,
            reserve1=reserve1,
            block_number=block_number,
            log_index=log_index,
            chain=chain,
            captured_at=captured_at,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class PoolPriceStateRegistry:
    """Thread-safe per-chain pool price state cache.

    Holds two parallel sub-stores per chain — one for V3 (``sqrtPriceX96``+tick+
    liquidity) and one for V2 (``reserve0``/``reserve1``). Both use the same
    latest-write-wins by ``(block_number, log_index)`` invariant; older logs
    that arrive out of order are silently dropped (counted in
    ``stale_drops_total``).
    """

    def __init__(self) -> None:
        self._lock = RLock()
        # chain -> pool_addr -> V3PoolState
        self._state: Dict[str, Dict[str, V3PoolState]] = {}
        # chain -> pool_addr -> V2PoolState
        self._v2_state: Dict[str, Dict[str, V2PoolState]] = {}
        self._counters: Dict[str, int] = {
            "updates_total": 0,
            "decode_errors_total": 0,
            "stale_drops_total": 0,
            "v2_updates_total": 0,
            "v2_decode_errors_total": 0,
            "v2_stale_drops_total": 0,
        }

    # -- decode + store one log --------------------------------------------
    def update_from_v3_log(self, chain: str, log: Any) -> bool:
        decoded = decode_v3_swap_log_state(log, chain)
        if decoded is None:
            with self._lock:
                self._counters["decode_errors_total"] += 1
            return False
        return self._store(decoded)

    def update_from_v2_log(self, chain: str, log: Any) -> bool:
        decoded = decode_v2_sync_log_state(log, chain)
        if decoded is None:
            with self._lock:
                self._counters["v2_decode_errors_total"] += 1
            return False
        return self._store_v2(decoded)

    def store_state(self, state: V3PoolState) -> bool:
        return self._store(state)

    def store_v2_state(self, state: V2PoolState) -> bool:
        return self._store_v2(state)

    def _store_v2(self, state: V2PoolState) -> bool:
        with self._lock:
            chain_map = self._v2_state.setdefault(state.chain, {})
            existing = chain_map.get(state.pool_address)
            if existing is not None:
                if (state.block_number, state.log_index) <= (
                    existing.block_number,
                    existing.log_index,
                ):
                    self._counters["v2_stale_drops_total"] += 1
                    return False
            chain_map[state.pool_address] = state
            self._counters["v2_updates_total"] += 1
            return True

    def _store(self, state: V3PoolState) -> bool:
        with self._lock:
            chain_map = self._state.setdefault(state.chain, {})
            existing = chain_map.get(state.pool_address)
            if existing is not None:
                # latest-write-wins by (block_number, log_index)
                if (state.block_number, state.log_index) <= (
                    existing.block_number,
                    existing.log_index,
                ):
                    self._counters["stale_drops_total"] += 1
                    return False
            chain_map[state.pool_address] = state
            self._counters["updates_total"] += 1
            return True

    # -- read --------------------------------------------------------------
    def get(self, chain: str, pool_address: str) -> Optional[V3PoolState]:
        with self._lock:
            chain_map = self._state.get(chain)
            if chain_map is None:
                return None
            return chain_map.get(pool_address.lower())

    def get_v2(self, chain: str, pool_address: str) -> Optional[V2PoolState]:
        with self._lock:
            chain_map = self._v2_state.get(chain)
            if chain_map is None:
                return None
            return chain_map.get(pool_address.lower())

    def pools_tracked(self, chain: Optional[str] = None) -> int:
        with self._lock:
            if chain is None:
                return sum(len(m) for m in self._state.values()) + sum(
                    len(m) for m in self._v2_state.values()
                )
            v3 = len(self._state.get(chain) or {})
            v2 = len(self._v2_state.get(chain) or {})
            return v3 + v2

    def counters(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)

    # -- snapshot for rolling artifact -------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            chains_summary: Dict[str, Dict[str, Any]] = {}
            all_chains = set(self._state.keys()) | set(self._v2_state.keys())
            for chain in all_chains:
                v3_map = self._state.get(chain) or {}
                v2_map = self._v2_state.get(chain) or {}
                latest_v3 = max((s.block_number for s in v3_map.values()), default=0)
                latest_v2 = max((s.block_number for s in v2_map.values()), default=0)
                chains_summary[chain] = {
                    "pools_tracked": len(v3_map) + len(v2_map),
                    "v3_pools_tracked": len(v3_map),
                    "v2_pools_tracked": len(v2_map),
                    "latest_block": max(latest_v3, latest_v2),
                }
            total_v3 = sum(len(m) for m in self._state.values())
            total_v2 = sum(len(m) for m in self._v2_state.values())
            return {
                "schema_version": "m7.e1.51.slice2.pool_price_state.v2",
                "captured_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "counters": dict(self._counters),
                "chains": chains_summary,
                "total_pools_tracked": total_v3 + total_v2,
                "total_v3_pools_tracked": total_v3,
                "total_v2_pools_tracked": total_v2,
            }

    # -- testing helper ----------------------------------------------------
    def reset(self) -> None:
        with self._lock:
            self._state.clear()
            self._v2_state.clear()
            for k in self._counters:
                self._counters[k] = 0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry_singleton: Optional[PoolPriceStateRegistry] = None
_registry_singleton_lock = RLock()


def get_registry() -> PoolPriceStateRegistry:
    """Return the process-wide registry singleton.

    The singleton is the canonical hot-lane integration point added in
    later slices. It is safe to call from multiple coroutines/threads.
    """
    global _registry_singleton
    with _registry_singleton_lock:
        if _registry_singleton is None:
            _registry_singleton = PoolPriceStateRegistry()
        return _registry_singleton


def reset_registry_for_tests() -> None:
    """Reset the singleton — tests only."""
    global _registry_singleton
    with _registry_singleton_lock:
        _registry_singleton = None


# ---------------------------------------------------------------------------
# Hot-lane sink (slice-3)
# ---------------------------------------------------------------------------

def feed_raw_logs(chain: str, logs) -> Dict[str, int]:
    """Passive sink for raw WS logs. Never raises.

    Dispatches each log to the appropriate decoder based on payload size:
      - >= 320 hex chars -> V3 Swap
      - >= 128 hex chars -> V2 Sync
      - otherwise        -> skipped

    Returns a small dict of per-call counters useful for canary metrics::

        {"v3_updates": int, "v2_updates": int, "skipped": int}
    """
    counters = {"v3_updates": 0, "v2_updates": 0, "skipped": 0}
    if not logs:
        return counters
    try:
        reg = get_registry()
    except Exception:
        return counters
    for lg in logs:
        try:
            data_hex = lg.get("data") if isinstance(lg, dict) else None
            if not data_hex:
                counters["skipped"] += 1
                continue
            payload = data_hex[2:] if data_hex.startswith("0x") else data_hex
            n = len(payload)
            if n >= 320:
                if reg.update_from_v3_log(chain, lg):
                    counters["v3_updates"] += 1
                else:
                    counters["skipped"] += 1
            elif n >= 128:
                if reg.update_from_v2_log(chain, lg):
                    counters["v2_updates"] += 1
                else:
                    counters["skipped"] += 1
            else:
                counters["skipped"] += 1
        except Exception:
            counters["skipped"] += 1
    return counters


__all__ = [
    "V3PoolState",
    "V2PoolState",
    "decode_v3_swap_log_state",
    "decode_v2_sync_log_state",
    "PoolPriceStateRegistry",
    "feed_raw_logs",
    "get_registry",
    "reset_registry_for_tests",
]
