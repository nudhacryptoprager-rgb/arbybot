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

    def __init__(self, stale_threshold_blocks: int = 10) -> None:
        # {pair_key: [PoolRegistryEntry, ...]}
        self._pools: Dict[str, List[PoolRegistryEntry]] = {}
        # {pair_key} — set of pairs already queried (even if no pools found)
        self._queried: Set[str] = set()
        # M7.A.5.38: Configurable staleness threshold for state refresh.
        # Default 10 blocks (~2.5s). Persistent cold registries use higher
        # values (e.g., 200) to avoid per-event refresh in diagnostic lane.
        self.stale_threshold_blocks = stale_threshold_blocks
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
            # Refresh state if stale (> stale_threshold_blocks old)
            if existing and existing[0].last_block and (block_num - existing[0].last_block) > self.stale_threshold_blocks:
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

        # E1.22: ve33 raw multicall queries (batched alongside V3)
        _ve33_raw_calls: List[Tuple] = []   # (target, allowFailure, calldata)
        _ve33_meta: List[Tuple] = []        # (dex_name, stable_flag)

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
                self._preload_v2_pair(
                    dex_name, factory, token_a, token_b,
                    rpc_url, block_num, key,
                )
            elif adapter_type in ("ve33",):
                # E1.22: Batch ve33 getPool(tokenA, tokenB, stable) queries
                # into raw multicall instead of individual eth_call.
                # Selector: 0x79bc57d5 = getPool(address,address,bool)
                from web3 import Web3 as _W3
                _cs_factory = _W3.to_checksum_address(factory)
                for _stable in (False, True):
                    _cd = bytes.fromhex("79bc57d5")
                    _cd += _W3.to_bytes(hexstr=token_a).rjust(32, b"\x00")
                    _cd += _W3.to_bytes(hexstr=token_b).rjust(32, b"\x00")
                    _cd += (1 if _stable else 0).to_bytes(32, "big")
                    _ve33_raw_calls.append((_cs_factory, True, _cd))
                    _ve33_meta.append((dex_name, _stable))

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

        # E1.22: Execute ve33 factory queries via raw multicall batch
        if _ve33_raw_calls:
            try:
                _ve33_results = batcher._execute_multicall(_ve33_raw_calls)
                _ZERO_ADDR = "0x" + "0" * 40
                _ve33_pool_addrs: List[Optional[str]] = []
                _ve33_pool_meta: List[Tuple] = []
                if _ve33_results:
                    from web3 import Web3 as _W3
                    for idx, (success, data) in enumerate(_ve33_results):
                        if success and len(data) >= 32:
                            addr = "0x" + data[-20:].hex()
                            if addr != _ZERO_ADDR:
                                _ve33_pool_addrs.append(_W3.to_checksum_address(addr))
                                _ve33_pool_meta.append(_ve33_meta[idx])
                # Batch getReserves() for discovered ve33 pools
                if _ve33_pool_addrs:
                    _RESERVES_SELECTOR = bytes.fromhex("0902f1ac")
                    _reserves_calls = [
                        (pa, True, _RESERVES_SELECTOR) for pa in _ve33_pool_addrs
                    ]
                    _reserves_results = batcher._execute_multicall(_reserves_calls)
                    for idx, pa in enumerate(_ve33_pool_addrs):
                        dex_name, _stable = _ve33_pool_meta[idx]
                        reserve0 = reserve1 = 0
                        if _reserves_results and idx < len(_reserves_results):
                            _rsuc, _rdata = _reserves_results[idx]
                            if _rsuc and len(_rdata) >= 64:
                                reserve0 = int.from_bytes(_rdata[0:32], "big")
                                reserve1 = int.from_bytes(_rdata[32:64], "big")
                        entry = PoolRegistryEntry(
                            address=pa.lower(),
                            dex=dex_name,
                            adapter_type="ve33",
                            fee=1 if _stable else 0,  # E1.24: 0=volatile, 1=stable (for pricing fee model)
                            token_a=token_a,
                            token_b=token_b,
                            liquidity=reserve0 + reserve1 if (reserve0 > 0 or reserve1 > 0) else 0,
                            sqrt_price_x96=reserve0,
                            tick=reserve1,
                            last_block=block_num,
                        )
                        entries.append(entry)
                        self.pools_discovered += 1
                        if entry.is_active():
                            self.pools_active += 1
            except Exception as exc:
                logger.debug("ve33 batch factory query failed: %s", str(exc)[:100])

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
            from core.rpc_rate_limiter import rpc_throttle

            # E1.19a: 10s timeout prevents hanging on slow/429'd RPC
            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))

            # getPair(address,address) = 0xe6a43905
            calldata = bytes.fromhex(_SELECTOR_GET_PAIR)
            calldata += Web3.to_bytes(hexstr=token_a).rjust(32, b"\x00")
            calldata += Web3.to_bytes(hexstr=token_b).rjust(32, b"\x00")

            rpc_throttle.acquire()
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
            rpc_throttle.acquire()
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

    def _preload_ve33_pair(
        self,
        dex_name: str,
        factory: str,
        token_a: str,
        token_b: str,
        rpc_url: str,
        block_num: int,
        pair_key: str,
    ) -> None:
        """Query a ve33/Solidly-style factory.getPool(tokenA, tokenB, stable) and read getReserves() for state.

        Queries both stable=false (volatile) and stable=true pools.
        """
        try:
            from web3 import Web3
            from core.rpc_rate_limiter import rpc_throttle

            w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))

            for stable in (False, True):
                # getPool(address,address,bool) = 0x79bc57d5
                calldata = bytes.fromhex("79bc57d5")
                calldata += Web3.to_bytes(hexstr=token_a).rjust(32, b"\x00")
                calldata += Web3.to_bytes(hexstr=token_b).rjust(32, b"\x00")
                calldata += (1 if stable else 0).to_bytes(32, "big")

                rpc_throttle.acquire()
                result = w3.eth.call(
                    {"to": Web3.to_checksum_address(factory), "data": "0x" + calldata.hex()},
                    block_num,
                )
                if len(result) < 32:
                    continue
                pair_addr = "0x" + result[-20:].hex()
                if pair_addr == "0x" + "0" * 40:
                    continue

                # Read getReserves() = 0x0902f1ac
                rpc_throttle.acquire()
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
                    adapter_type="ve33",
                    fee=0,  # ve33 pools use dynamic fees, not fixed tiers
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
            logger.debug("ve33 getPool failed for %s/%s: %s", dex_name, pair_key[:20], str(exc)[:80])

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
                from core.rpc_rate_limiter import rpc_throttle
                # E1.19a: 10s timeout
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                for e in v2_entries:
                    rpc_throttle.acquire()
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

    def register_ptt_pools(
        self,
        ptt: Dict[str, Tuple],
        rpc_url: str,
        block_num: int,
    ) -> int:
        """E1.25: Directly register PTT pools that factory discovery missed.

        For each PTT entry (pool_addr → [t0, t1, fee]), check if the pool
        is already in the registry for its pair.  If not, inject it as a
        PoolRegistryEntry and batch-read its on-chain state.

        This covers pools from unconfigured factories (Algebra dynamic-fee,
        BaseSwap, etc.) that ``preload_pair`` cannot discover via factory
        queries.

        Returns number of newly registered pools.
        """
        # Identify PTT pools missing from registry
        missing: List[Tuple[str, str, str, int]] = []  # (pool_addr, t0, t1, fee)
        for pa, triple in ptt.items():
            if len(triple) != 3:
                continue
            t0, t1, fee = triple
            if not t0 or not t1:
                continue
            key = _pair_key(t0, t1)
            existing = self._pools.get(key, [])
            pa_lower = pa.lower()
            if any(e.address == pa_lower for e in existing):
                continue  # Already registered
            missing.append((pa_lower, t0, t1, fee if isinstance(fee, int) else 0))

        if not missing:
            return 0

        # Batch-read state for all missing pools via multicall.
        # Try slot0() for V3-style, getReserves() for V2-style.
        # Use a heuristic: fee > 10 → V3-style (slot0), fee <= 10 → V2-style (getReserves).
        try:
            from core.multicall import get_multicall_batcher
            batcher = get_multicall_batcher(rpc_url, block_num)
        except Exception:
            return 0

        # Read full pool data in batch (handles both V3 slot0 and V2 reserves)
        all_addrs = [m[0] for m in missing]
        state_map: Dict[str, Optional[Dict[str, Any]]] = {}
        try:
            state_map = batcher.batch_full_pool_data(all_addrs)
        except Exception:
            pass

        # For pools where slot0 returned nothing, try getReserves batch
        _need_reserves: List[Tuple[int, str]] = []
        for idx, (pa, t0, t1, fee) in enumerate(missing):
            if pa not in state_map or state_map[pa] is None:
                _need_reserves.append((idx, pa))

        reserves_map: Dict[str, Tuple[int, int]] = {}
        if _need_reserves:
            try:
                _RESERVES_SEL = bytes.fromhex("0902f1ac")
                _calls = [(pa, True, _RESERVES_SEL) for _, pa in _need_reserves]
                _results = batcher._execute_multicall(_calls)
                if _results:
                    for i, (_, pa) in enumerate(_need_reserves):
                        if i < len(_results):
                            success, data = _results[i]
                            if success and len(data) >= 64:
                                r0 = int.from_bytes(data[0:32], "big")
                                r1 = int.from_bytes(data[32:64], "big")
                                reserves_map[pa] = (r0, r1)
            except Exception:
                pass

        # E1.26: Fee → DEX mapping for router resolution.
        # Maps PTT pool fees to configured DEX names so execution_gate
        # can look up the correct router via get_dex_config(chain, dex_name).
        _STANDARD_V3_FEES = {100, 500, 3000, 10000}
        _PCS_FEES = {2500}  # PancakeSwap unique tier

        # E1.26: Batch-read factory() from V3-style pools to determine which
        # configured DEX they belong to.  V3 pools expose factory() → address.
        _FACTORY_SEL = bytes.fromhex("c45a0155")  # factory() selector
        _factory_map: Dict[str, str] = {}  # pool_addr → factory_addr
        _v3_pools = [(pa, fee) for pa, t0, t1, fee in missing if fee > 10]
        if _v3_pools:
            try:
                _fact_calls = [(pa, True, _FACTORY_SEL) for pa, _ in _v3_pools]
                _fact_results = batcher._execute_multicall(_fact_calls)
                if _fact_results:
                    for i, (pa, _) in enumerate(_v3_pools):
                        if i < len(_fact_results):
                            success, data = _fact_results[i]
                            if success and len(data) >= 32:
                                addr = "0x" + data[12:32].hex()
                                _factory_map[pa] = addr.lower()
            except Exception:
                pass

        # Map known factories to DEX names (from config/dexes.yaml)
        _FACTORY_TO_DEX = {
            "0x33128a8fc17869897dce68ed026d694621f6fdfd": "uniswap_v3",
            "0xc35dadb65012ec5796536bd9864ed8773abc74c4": "sushiswap_v3",
            "0x0bfbcf9fa4f9c56b0f40a671ad40e0805a091865": "pancakeswap_v3",
            "0x420dd381b31aef6683db6b902084cb0ffece40da": "aerodrome",
        }

        registered = 0
        for pa, t0, t1, fee in missing:
            key = _pair_key(t0, t1)
            state = state_map.get(pa)
            reserves = reserves_map.get(pa)

            # Determine adapter type AND dex name from fee heuristic
            if fee <= 1:
                # ve33 (Aerodrome): fee 0=volatile, 1=stable
                dex_name = "aerodrome"
                adapter = "ve33"
                r0 = reserves[0] if reserves else 0
                r1 = reserves[1] if reserves else 0
                liq = r0 + r1 if (r0 > 0 or r1 > 0) else 0
                entry = PoolRegistryEntry(
                    address=pa, dex=dex_name, adapter_type=adapter,
                    fee=fee, token_a=t0, token_b=t1,
                    liquidity=liq, sqrt_price_x96=r0, tick=r1,
                    last_block=block_num,
                )
            elif 1 < fee <= 10:
                # V2-style (fee 3 etc.)
                dex_name = "ptt_direct"
                adapter = "uniswap_v2"
                r0 = reserves[0] if reserves else 0
                r1 = reserves[1] if reserves else 0
                liq = r0 + r1 if (r0 > 0 or r1 > 0) else 0
                entry = PoolRegistryEntry(
                    address=pa, dex=dex_name, adapter_type=adapter,
                    fee=fee, token_a=t0, token_b=t1,
                    liquidity=liq, sqrt_price_x96=r0, tick=r1,
                    last_block=block_num,
                )
            else:
                # V3-style: map to configured DEX by factory match or fee tier
                _pool_factory = _factory_map.get(pa, "")
                _matched_dex = _FACTORY_TO_DEX.get(_pool_factory, "")
                if _matched_dex:
                    # Factory matched — use the correct DEX
                    dex_name = _matched_dex
                    adapter = "ve33" if _matched_dex == "aerodrome" else "uniswap_v3"
                elif fee in _PCS_FEES:
                    dex_name = "pancakeswap_v3"
                    adapter = "uniswap_v3"
                elif fee in _STANDARD_V3_FEES:
                    dex_name = "uniswap_v3"
                    adapter = "uniswap_v3"
                else:
                    # Non-standard fees (2700, 10305, 586, etc.) → Algebra/dynamic
                    dex_name = "ptt_direct"
                    adapter = "algebra"
                liq = state.get("liquidity", 0) if state else 0
                sqp = state.get("sqrt_price_x96", 0) if state else 0
                tick = state.get("tick", 0) if state else 0
                # If V3 slot0 failed, try reserves as fallback
                if liq == 0 and sqp == 0 and reserves:
                    r0, r1 = reserves
                    liq = r0 + r1 if (r0 > 0 or r1 > 0) else 0
                    sqp = r0
                    tick = r1
                    if not _matched_dex:
                        adapter = "algebra"  # V3 slot0 failed + no factory → likely non-V3
                        dex_name = "ptt_direct"
                entry = PoolRegistryEntry(
                    address=pa, dex=dex_name, adapter_type=adapter,
                    fee=fee, token_a=t0, token_b=t1,
                    liquidity=liq, sqrt_price_x96=sqp, tick=tick,
                    last_block=block_num,
                )

            self._pools.setdefault(key, []).append(entry)
            self._queried.add(key)
            self.pools_discovered += 1
            if entry.is_active():
                self.pools_active += 1
            registered += 1

        if registered > 0:
            # E1.26: Log factory matching stats
            _factory_matched = sum(1 for pa, _, _, f in missing if pa in _factory_map and _FACTORY_TO_DEX.get(_factory_map.get(pa, ""), ""))
            _dex_dist: Dict[str, int] = {}
            for pa, t0, t1, fee in missing:
                for e in self._pools.get(_pair_key(t0, t1), []):
                    if e.address == pa:
                        _dex_dist[e.dex] = _dex_dist.get(e.dex, 0) + 1
            logger.info(
                "PTT direct register: %d/%d pools (active=%d, factory_matched=%d, dex_dist=%s)",
                registered, len(missing),
                sum(1 for pa, t0, t1, fee in missing
                    if any(e.address == pa and e.is_active()
                           for e in self._pools.get(_pair_key(t0, t1), []))),
                _factory_matched,
                _dex_dist,
            )
        return registered
