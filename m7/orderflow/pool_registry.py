"""
M7.A.5.21: Factory-driven persistent pool registry.

Preloads pool addresses from on-chain factory contracts (V2 getPair, V3 getPool,
Algebra poolByPair) so that low-lag events can skip expensive per-event coverage
scans.  The registry is session-scoped: it persists across events within a single
ws-live replay window but is not saved to disk.

Factory selectors:
  - V3 getPool(address,address,uint24) = 0x1698ee82
  - V2 getPair(address,address)        = 0xe6a43905
  - Algebra poolByPair(address,address) = 0xe6a43905  (same as V2)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("m7.orderflow.pool_registry")

# Factory selectors
_SELECTOR_GET_POOL = "1698ee82"   # V3: getPool(address,address,uint24)
_SELECTOR_GET_PAIR = "e6a43905"   # V2/Algebra: getPair(address,address)


def _pair_key(token_a: str, token_b: str) -> str:
    """Canonical pair key: sorted lowercase addresses joined by '/'."""
    a, b = token_a.lower(), token_b.lower()
    return f"{min(a, b)}/{max(a, b)}"


class PoolRegistryEntry:
    """A single pool discovered via factory queries."""

    __slots__ = (
        "address", "dex", "adapter_type", "fee", "token_a", "token_b",
        "liquidity", "sqrt_price_x96", "tick", "last_block",
    )

    def __init__(
        self,
        address: str,
        dex: str,
        adapter_type: str,
        fee: int,
        token_a: str,
        token_b: str,
        liquidity: Optional[int] = None,
        sqrt_price_x96: Optional[int] = None,
        tick: Optional[int] = None,
        last_block: Optional[int] = None,
    ):
        self.address = address.lower()
        self.dex = dex
        self.adapter_type = adapter_type
        self.fee = fee
        self.token_a = token_a.lower()
        self.token_b = token_b.lower()
        self.liquidity = liquidity
        self.sqrt_price_x96 = sqrt_price_x96
        self.tick = tick
        self.last_block = last_block

    def is_active(self) -> bool:
        """Active = has known positive liquidity."""
        return self.liquidity is not None and self.liquidity > 0

    def to_candidate_pool(self) -> Dict[str, Any]:
        """Convert to the candidate_pool dict format used by coverage/scoring."""
        return {
            "address": self.address,
            "dex": self.dex,
            "fee": self.fee,
            "liquidity": self.liquidity,
            "activity_source": "factory_registry",
            "activity_drop_reason": None if self.is_active() else "liquidity_zero",
        }

    def to_pool_state(self) -> Optional[Dict[str, Any]]:
        """Convert to local_sim pool_state dict if full state is available."""
        if self.sqrt_price_x96 and self.sqrt_price_x96 > 0 and self.liquidity is not None:
            return {
                "sqrt_price_x96": self.sqrt_price_x96,
                "tick": self.tick,
                "liquidity": self.liquidity,
            }
        return None


class PoolRegistry:
    """Session-scoped persistent pool registry.

    Discovered pools persist across events.  Call ``preload_pair()`` to
    factory-discover pools for a token pair.  Call ``lookup_pair()`` to
    retrieve cached entries without RPC.

    Thread-safety: NOT thread-safe.  Intended for single-threaded scoring loop.
    """

    def __init__(self) -> None:
        # {pair_key: [PoolRegistryEntry, ...]}
        self._pools: Dict[str, List[PoolRegistryEntry]] = {}
        # {pair_key} — set of pairs already queried (even if no pools found)
        self._queried: Set[str] = set()
        # Stats
        self.preload_calls = 0
        self.cache_hits = 0
        self.pools_discovered = 0
        self.pools_active = 0

    def is_pair_known(self, token_a: str, token_b: str) -> bool:
        """Return True if this pair has already been queried."""
        return _pair_key(token_a, token_b) in self._queried

    def lookup_pair(self, token_a: str, token_b: str) -> List[PoolRegistryEntry]:
        """Return cached entries for a pair (empty list if not queried or no pools)."""
        key = _pair_key(token_a, token_b)
        if key in self._queried:
            self.cache_hits += 1
        return self._pools.get(key, [])

    def preload_pair(
        self,
        token_a: str,
        token_b: str,
        dex_configs: Dict[str, Any],
        rpc_url: str,
        block_num: int,
    ) -> List[PoolRegistryEntry]:
        """Query factories for all pools of `token_a/token_b` and cache results.

        Uses batch_get_pool + batch_full_pool_data in one multicall round.
        Returns the discovered entries (also cached for future lookup).
        """
        key = _pair_key(token_a, token_b)

        # If already queried at this or later block, return cached
        if key in self._queried:
            existing = self._pools.get(key, [])
            # Refresh state if stale (> 10 blocks old)
            if existing and existing[0].last_block and (block_num - existing[0].last_block) > 10:
                return self._refresh_state(key, rpc_url, block_num)
            self.cache_hits += 1
            return existing

        self.preload_calls += 1
        self._queried.add(key)

        from core.multicall import get_multicall_batcher
        batcher = get_multicall_batcher(rpc_url, block_num)

        # Build factory queries
        queries: List[Tuple] = []         # (factory, tokenA, tokenB, fee)
        query_meta: List[Tuple] = []      # (dex_name, adapter_type, fee)

        for dex_name, cfg in dex_configs.items():
            adapter_type = cfg.get("adapter_type", "")
            factory = cfg.get("factory", "")
            if not factory:
                continue

            if adapter_type in ("uniswap_v3",):
                fee_tiers = cfg.get("fee_tiers", [500, 3000, 100, 10000])
                for fee in fee_tiers:  # Query ALL tiers, not just top 2
                    queries.append((factory, token_a, token_b, fee))
                    query_meta.append((dex_name, adapter_type, fee))
            elif adapter_type in ("algebra",):
                # Algebra: use getPair-style query with fee=0 (dynamic fee)
                queries.append((factory, token_a, token_b, 0))
                query_meta.append((dex_name, adapter_type, 0))
            elif adapter_type in ("uniswap_v2",):
                # V2: getPair query — use batch_get_pool with fee=0
                # (The multicall batcher encodes getPool, but for V2 we
                #  need a different approach — direct eth_call)
                self._preload_v2_pair(
                    dex_name, factory, token_a, token_b,
                    rpc_url, block_num, key,
                )

        # Execute V3/Algebra queries via batch_get_pool
        entries: List[PoolRegistryEntry] = []
        if queries:
            try:
                pool_addrs = batcher.batch_get_pool(queries)
                valid_addrs = [a for a in pool_addrs if a is not None]

                # Batch-read full state for discovered pools
                full_state_map: Dict[str, Optional[Dict[str, Any]]] = {}
                if valid_addrs:
                    full_state_map = batcher.batch_full_pool_data(valid_addrs)

                for i, addr in enumerate(pool_addrs):
                    if addr is None:
                        continue
                    dex_name, adapter_type, fee = query_meta[i]
                    state = full_state_map.get(addr)

                    entry = PoolRegistryEntry(
                        address=addr,
                        dex=dex_name,
                        adapter_type=adapter_type,
                        fee=fee,
                        token_a=token_a,
                        token_b=token_b,
                        liquidity=state.get("liquidity") if state else None,
                        sqrt_price_x96=state.get("sqrt_price_x96") if state else None,
                        tick=state.get("tick") if state else None,
                        last_block=block_num,
                    )
                    entries.append(entry)
                    self.pools_discovered += 1
                    if entry.is_active():
                        self.pools_active += 1
            except Exception as exc:
                logger.debug("preload_pair factory query failed: %s", str(exc)[:100])

        # Merge with any V2 entries already added
        existing_v2 = self._pools.get(key, [])
        all_entries = existing_v2 + entries
        self._pools[key] = all_entries
        return all_entries

    def _preload_v2_pair(
        self,
        dex_name: str,
        factory: str,
        token_a: str,
        token_b: str,
        rpc_url: str,
        block_num: int,
        pair_key: str,
    ) -> None:
        """Query a V2 factory.getPair() and read getReserves() for state."""
        try:
            from web3 import Web3

            w3 = Web3(Web3.HTTPProvider(rpc_url))

            # getPair(address,address) = 0xe6a43905
            calldata = bytes.fromhex(_SELECTOR_GET_PAIR)
            calldata += Web3.to_bytes(hexstr=token_a).rjust(32, b"\x00")
            calldata += Web3.to_bytes(hexstr=token_b).rjust(32, b"\x00")

            result = w3.eth.call(
                {"to": Web3.to_checksum_address(factory), "data": "0x" + calldata.hex()},
                block_num,
            )
            if len(result) < 32:
                return
            pair_addr = "0x" + result[-20:].hex()
            if pair_addr == "0x" + "0" * 40:
                return

            # Read getReserves() = 0x0902f1ac
            reserves_data = w3.eth.call(
                {"to": Web3.to_checksum_address(pair_addr), "data": "0x0902f1ac"},
                block_num,
            )
            reserve0 = reserve1 = 0
            if len(reserves_data) >= 64:
                reserve0 = int.from_bytes(reserves_data[0:32], "big")
                reserve1 = int.from_bytes(reserves_data[32:64], "big")

            entry = PoolRegistryEntry(
                address=pair_addr,
                dex=dex_name,
                adapter_type="uniswap_v2",
                fee=3,  # 0.3% as per V2 standard (fee_numerator=997/1000)
                token_a=token_a,
                token_b=token_b,
                liquidity=reserve0 + reserve1 if (reserve0 > 0 or reserve1 > 0) else 0,
                sqrt_price_x96=reserve0,  # Store reserve0 in sqrt_price field
                tick=reserve1,            # Store reserve1 in tick field (V2 reuse)
                last_block=block_num,
            )
            self._pools.setdefault(pair_key, []).append(entry)
            self.pools_discovered += 1
            if entry.is_active():
                self.pools_active += 1
        except Exception as exc:
            logger.debug("V2 getPair failed for %s/%s: %s", dex_name, pair_key[:20], str(exc)[:80])

    def _refresh_state(
        self,
        pair_key: str,
        rpc_url: str,
        block_num: int,
    ) -> List[PoolRegistryEntry]:
        """Refresh pool state for already-discovered pools (stale > 10 blocks)."""
        entries = self._pools.get(pair_key, [])
        if not entries:
            return entries

        # Separate V3-style and V2-style entries
        v3_entries = [e for e in entries if e.adapter_type != "uniswap_v2"]
        v2_entries = [e for e in entries if e.adapter_type == "uniswap_v2"]

        if v3_entries:
            try:
                from core.multicall import get_multicall_batcher
                batcher = get_multicall_batcher(rpc_url, block_num)
                addrs = [e.address for e in v3_entries]
                fresh_state = batcher.batch_full_pool_data(addrs)
                for e in v3_entries:
                    state = fresh_state.get(e.address)
                    if state:
                        e.liquidity = state.get("liquidity", 0)
                        e.sqrt_price_x96 = state.get("sqrt_price_x96", 0)
                        e.tick = state.get("tick", 0)
                    e.last_block = block_num
            except Exception as exc:
                logger.debug("refresh V3 state failed: %s", str(exc)[:80])

        if v2_entries:
            try:
                from web3 import Web3
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                for e in v2_entries:
                    reserves_data = w3.eth.call(
                        {"to": Web3.to_checksum_address(e.address), "data": "0x0902f1ac"},
                        block_num,
                    )
                    if len(reserves_data) >= 64:
                        r0 = int.from_bytes(reserves_data[0:32], "big")
                        r1 = int.from_bytes(reserves_data[32:64], "big")
                        e.sqrt_price_x96 = r0  # reserve0
                        e.tick = r1              # reserve1
                        e.liquidity = r0 + r1 if (r0 > 0 or r1 > 0) else 0
                    e.last_block = block_num
            except Exception as exc:
                logger.debug("refresh V2 state failed: %s", str(exc)[:80])

        return entries

    def get_stats(self) -> Dict[str, Any]:
        """Return registry usage statistics."""
        return {
            "preload_calls": self.preload_calls,
            "cache_hits": self.cache_hits,
            "pairs_known": len(self._queried),
            "pools_discovered": self.pools_discovered,
            "pools_active": self.pools_active,
        }
