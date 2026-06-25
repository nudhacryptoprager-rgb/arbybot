"""M8.3 durable negative cache for non-economics ERC20 probe outcomes."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Set

from m8.metadata.registry import (
    ERROR_ERC20_DECIMALS_REVERT,
    ERROR_NO_CODE,
    ERROR_NON_ERC20,
    ERROR_PROBE_CAP_EXHAUSTED,
)

NEGATIVE_CACHE_SCHEMA = "m8_3_token_negative_cache_v1"
DEFAULT_NEGATIVE_CACHE_TTL_S = 48.0 * 3600.0

NEGATIVE_ERROR_CODES = frozenset(
    {
        ERROR_NON_ERC20,
        ERROR_NO_CODE,
        ERROR_ERC20_DECIMALS_REVERT,
        ERROR_PROBE_CAP_EXHAUSTED,
    }
)


def is_negative_cache_eligible(error_code: Optional[str]) -> bool:
    return str(error_code or "") in NEGATIVE_ERROR_CODES


def negative_cache_key(
    chain: str,
    address: str,
    *,
    code_hash: Optional[str] = None,
    code_length: Optional[int] = None,
) -> str:
    """Cache key: chain + token_address + code_hash (code_length fallback)."""
    addr = str(address or "").lower()
    if code_hash:
        ch = str(code_hash).lower()
    elif code_length is not None:
        ch = f"len:{int(code_length)}"
    else:
        ch = "none"
    return f"{chain.lower()}:{addr}:{ch}"


def collect_cycle_scope_token_addresses(
    bridge: Optional[Dict[str, Any]],
    *,
    capacity: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    """Token addresses on routes in cycle / econ-capacity scope (negative-cache bypass)."""
    from m8.metadata.registry import _route_scope_ids

    scopes = _route_scope_ids(bridge, capacity=capacity)
    route_ids = set(scopes.get("cycle_participating_routes") or set()) | set(
        scopes.get("econ_capacity_routes") or set()
    )
    if not route_ids:
        return set()
    addrs: Set[str] = set()
    inv = bridge or {}
    for route in list(inv.get("active_routes") or []) + list(
        inv.get("exploration_routes") or []
    ):
        rid = str(route.get("route_id") or "")
        if route_ids and rid not in route_ids:
            continue
        for key in ("token0_addr", "token1_addr"):
            raw = str(route.get(key) or "").lower()
            if raw.startswith("0x") and len(raw) == 42:
                addrs.add(raw)
    return addrs


class TokenNegativeCache:
    """TTL negative cache persisted inside the M8.3 registry artifact."""

    def __init__(
        self,
        *,
        ttl_s: float = DEFAULT_NEGATIVE_CACHE_TTL_S,
        entries: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.ttl_s = float(ttl_s)
        self._entries: Dict[str, Dict[str, Any]] = dict(entries or {})
        self.hits = 0
        self.misses = 0
        self.bypass_count = 0

    @classmethod
    def load_from_registry(
        cls,
        prior_registry: Optional[Dict[str, Any]],
        *,
        ttl_s: float = DEFAULT_NEGATIVE_CACHE_TTL_S,
    ) -> "TokenNegativeCache":
        block = (prior_registry or {}).get("negative_cache") or {}
        entries = dict(block.get("entries") or {})
        ttl = float(block.get("ttl_s") or ttl_s)
        return cls(ttl_s=ttl, entries=entries)

    def should_bypass(
        self,
        address: str,
        cycle_scope_addrs: Optional[Set[str]] = None,
    ) -> bool:
        if not cycle_scope_addrs:
            return False
        if str(address or "").lower() in cycle_scope_addrs:
            self.bypass_count += 1
            return True
        return False

    def get(
        self,
        chain: str,
        address: str,
        *,
        code_hash: Optional[str] = None,
        code_length: Optional[int] = None,
        now_ts: Optional[float] = None,
    ) -> Optional[str]:
        now = float(now_ts if now_ts is not None else time.time())
        keys = [negative_cache_key(chain, address, code_hash=code_hash, code_length=code_length)]
        if code_hash is None and code_length is None:
            prefix = f"{chain.lower()}:{str(address or '').lower()}:"
            keys.extend(k for k in self._entries if k.startswith(prefix))
        seen: set[str] = set()
        for key in keys:
            if key in seen:
                continue
            seen.add(key)
            row = self._entries.get(key)
            if not row:
                continue
            cached_at = float(row.get("cached_at_epoch_s") or 0.0)
            if now - cached_at > self.ttl_s:
                del self._entries[key]
                continue
            self.hits += 1
            return str(row.get("error_code") or "")
        self.misses += 1
        return None

    def put(
        self,
        chain: str,
        address: str,
        error_code: str,
        *,
        code_hash: Optional[str] = None,
        code_length: Optional[int] = None,
        now_ts: Optional[float] = None,
    ) -> None:
        if not is_negative_cache_eligible(error_code):
            return
        key = negative_cache_key(
            chain,
            address,
            code_hash=code_hash,
            code_length=code_length,
        )
        now = float(now_ts if now_ts is not None else time.time())
        self._entries[key] = {
            "chain": chain.lower(),
            "address": str(address or "").lower(),
            "error_code": str(error_code),
            "code_hash": code_hash,
            "code_length": code_length,
            "cached_at_epoch_s": now,
        }

    def to_registry_block(self) -> Dict[str, Any]:
        return {
            "schema_version": NEGATIVE_CACHE_SCHEMA,
            "ttl_s": self.ttl_s,
            "entries": self._entries,
            "stats": {
                "hits": self.hits,
                "misses": self.misses,
                "bypass_count": self.bypass_count,
                "entry_count": len(self._entries),
            },
        }
