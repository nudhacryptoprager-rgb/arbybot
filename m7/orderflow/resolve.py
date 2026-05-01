"""
M7 orderflow token resolution, pool-address resolution, enrichment,
and pool-state extraction.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from m7.shared.constants import _DEFAULT_FEE_TIERS

logger = logging.getLogger("m7.orderflow.resolve")

# M7.A.5.37: Module-level cache for pool→(token0, token1, fee) resolution.
# Pool tokens are immutable contract properties — safe to cache forever.
# Cache is process-scoped: persists across iterations in the same Python process.
_pool_token_cache: Dict[str, tuple] = {}

# M7.A.5.38: Module-level cache for ERC-20 enrichment (symbol + decimals).
# ERC-20 symbol/decimals are immutable contract properties — safe to cache forever.
_enrichment_cache: Dict[str, dict] = {}  # addr_lower → {enriched, symbol, decimals, source}

# soak16 P0.1: Persistent disk-backed cache so resolved pool-token mapping
# survives supervisor restarts (root cause of DISC `session_fast_path_scored=0`
# regressions seen in soak14/soak15). The cache file is opt-out via
# ARBY_PERSISTENT_POOL_CACHE=0 and stored in the rolling artifacts directory.
_PERSISTENT_CACHE_PATH = Path("data/runs/_rolling/_pool_token_cache.json")
_PERSISTENT_CACHE_LOCK = threading.Lock()
_PERSISTENT_CACHE_LOADED = False


def _persistent_cache_enabled() -> bool:
    return os.environ.get("ARBY_PERSISTENT_POOL_CACHE", "1").strip() == "1"


def load_persistent_pool_token_cache() -> int:
    """Load `_pool_token_cache` from disk on process start.

    Returns the number of entries loaded. Idempotent: subsequent calls are
    no-ops once loaded.
    """
    global _PERSISTENT_CACHE_LOADED
    if _PERSISTENT_CACHE_LOADED:
        return len(_pool_token_cache)
    if not _persistent_cache_enabled():
        _PERSISTENT_CACHE_LOADED = True
        return 0
    try:
        if not _PERSISTENT_CACHE_PATH.exists():
            _PERSISTENT_CACHE_LOADED = True
            return 0
        with _PERSISTENT_CACHE_LOCK:
            data = json.loads(_PERSISTENT_CACHE_PATH.read_text(encoding="utf-8"))
            entries = data.get("entries") or {}
            loaded = 0
            for pa, triple in entries.items():
                if not isinstance(triple, (list, tuple)) or len(triple) != 3:
                    continue
                t0, t1, fee = triple
                try:
                    fee_int = int(fee) if fee is not None else 0
                except (TypeError, ValueError):
                    continue
                if not (isinstance(t0, str) and isinstance(t1, str)):
                    continue
                _pool_token_cache.setdefault(pa.lower(), (t0.lower(), t1.lower(), fee_int))
                loaded += 1
            _PERSISTENT_CACHE_LOADED = True
            logger.info(
                "persistent pool-token cache loaded: %d entries from %s",
                loaded, _PERSISTENT_CACHE_PATH,
            )
            return loaded
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("persistent pool-token cache load failed: %s", exc)
        _PERSISTENT_CACHE_LOADED = True
        return 0


def save_persistent_pool_token_cache() -> int:
    """Persist current `_pool_token_cache` to disk atomically.

    Returns the number of entries written. Bounded to the in-memory cache.
    """
    if not _persistent_cache_enabled():
        return 0
    try:
        with _PERSISTENT_CACHE_LOCK:
            entries = {}
            for k, v in _pool_token_cache.items():
                if not isinstance(v, (list, tuple)) or len(v) != 3:
                    continue
                t0, t1, fee = v
                try:
                    fee_int = int(fee) if fee is not None else 0
                except (TypeError, ValueError):
                    continue
                entries[str(k).lower()] = [str(t0).lower(), str(t1).lower(), fee_int]
            payload = {"version": 1, "entries": entries, "count": len(entries)}
            _PERSISTENT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _PERSISTENT_CACHE_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            os.replace(tmp, _PERSISTENT_CACHE_PATH)
            return len(entries)
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("persistent pool-token cache save failed: %s", exc)
        return 0


# Auto-load at import time so consumers (loop_runner, scoring) see cached
# entries before the first event arrives.
try:
    load_persistent_pool_token_cache()
except Exception:  # pragma: no cover
    pass

def _build_address_to_symbol(token_addresses: Dict[str, str]) -> Dict[str, str]:
    """Build reverse lookup: checksummed address → symbol."""
    result: Dict[str, str] = {}
    for sym, addr in token_addresses.items():
        result[addr.lower()] = sym
    return result



def _get_v3_factory_addresses(dex_configs: Dict[str, Any]) -> Dict[str, str]:
    """Extract factory addresses from dex configs.

    Returns: {factory_address_lower: dex_name}
    """
    result: Dict[str, str] = {}
    for dex_name, cfg in dex_configs.items():
        adapter_type = cfg.get("adapter_type", "")
        if adapter_type in ("uniswap_v3", "algebra"):
            factory = cfg.get("factory", "")
            if factory:
                result[factory.lower()] = dex_name
    return result



def _resolve_event_tokens(
    pool_address: str,
    swap_direction: str,
    rpc_url: str,
    block_num: int,
    addr_to_symbol: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """Resolve actual token0/token1 from a V3 pool contract via multicall.

    Args:
        pool_address: The pool contract address from the Swap log.
        swap_direction: "token0_in" or "token1_in" from normalize_swap_log().
        rpc_url: HTTP RPC URL.
        block_num: Block number for the multicall.
        addr_to_symbol: Reverse lookup {address_lower: symbol}.

    Returns:
        Dict with keys: token_in_symbol, token_out_symbol, token_in_addr,
        token_out_addr, fee, pool_address. Or None if resolution fails.
    """
    from core.multicall import get_multicall_batcher

    if not pool_address:
        return None

    # M7.A.5.37: Check module-level cache first (immutable pool data)
    _cache_key = pool_address.lower()
    cached = _pool_token_cache.get(_cache_key)
    if cached is not None:
        token0_addr, token1_addr, fee = cached
    else:
        batcher = get_multicall_batcher(rpc_url, block_num)
        info = batcher.batch_token_info([pool_address])
        pool_info = info.get(pool_address)
        if pool_info is None:
            return None

        token0_addr, token1_addr, fee = pool_info
        # Cache immutable pool data
        _pool_token_cache[_cache_key] = (token0_addr, token1_addr, fee)

    # Map direction to actual addresses
    if swap_direction == "token0_in":
        token_in_addr = token0_addr
        token_out_addr = token1_addr
    elif swap_direction == "token1_in":
        token_in_addr = token1_addr
        token_out_addr = token0_addr
    else:
        return None

    # Map addresses to symbols (best-effort)
    token_in_sym = addr_to_symbol.get(token_in_addr.lower(), token_in_addr[:10])
    token_out_sym = addr_to_symbol.get(token_out_addr.lower(), token_out_addr[:10])

    return {
        "token_in_symbol": token_in_sym,
        "token_out_symbol": token_out_sym,
        "token_in_addr": token_in_addr,
        "token_out_addr": token_out_addr,
        "fee": fee,
        "pool_address": pool_address,
    }




def _resolve_pool_addresses_multicall(
    dex_configs: Dict[str, Any],
    token_a: str,
    token_b: str,
    rpc_url: str,
    block_num: int,
) -> Dict[str, List[Dict[str, Any]]]:
    """Resolve V3 + ve33 pool addresses via batched factory multicall.

    Returns {dex_name: [{"address": addr, "fee": fee, "liquidity": int|None}, ...]}.
    One multicall for getPool + one for liquidity/state.
    """
    from core.multicall import get_multicall_batcher

    batcher = get_multicall_batcher(rpc_url, block_num)

    # Build getPool queries for all V3 factories × fee tiers
    queries: List[tuple] = []  # (factory, tokenA, tokenB, fee)
    query_meta: List[tuple] = []  # (dex_name, fee)

    # E1.22: ve33 raw multicall queries (batched alongside V3)
    _ve33_raw_calls: List[tuple] = []   # (target, allowFailure, calldata)
    _ve33_meta: List[tuple] = []        # (dex_name, stable_flag)

    for dex_name, cfg in dex_configs.items():
        adapter_type = cfg.get("adapter_type", "")
        factory = cfg.get("factory", "")
        if not factory:
            continue
        if adapter_type in ("uniswap_v3", "algebra"):
            fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
            for fee in fee_tiers:  # Query all configured tiers (batched in one multicall)
                queries.append((factory, token_a, token_b, fee))
                query_meta.append((dex_name, fee))
        elif adapter_type in ("ve33",):
            # E1.22: Batch ve33 getPool(tokenA, tokenB, stable) queries
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

    result: Dict[str, List[Dict[str, Any]]] = {}

    # Execute V3/Algebra queries
    if queries:
        pool_addrs = batcher.batch_get_pool(queries)

        # M7.A.5.12: Use batch_full_pool_data as canonical pool state source
        valid_addrs = [a for a in pool_addrs if a is not None]
        full_state_map: Dict[str, Optional[Dict[str, Any]]] = {}
        if valid_addrs:
            full_state_map = batcher.batch_full_pool_data(valid_addrs)

        for i, addr in enumerate(pool_addrs):
            dex_name, fee = query_meta[i]
            pool_state = full_state_map.get(addr) if addr else None
            entry = {
                "address": addr,
                "fee": fee,
                "liquidity": pool_state.get("liquidity") if pool_state else None,
                "pool_state": pool_state,
            }
            result.setdefault(dex_name, []).append(entry)

    # E1.22: Execute ve33 factory queries via raw multicall batch
    if _ve33_raw_calls:
        try:
            _ve33_results = batcher._execute_multicall(_ve33_raw_calls)
            _ZERO_ADDR = "0x" + "0" * 40
            _ve33_pool_addrs: List[str] = []
            _ve33_pool_dex: List[tuple] = []
            if _ve33_results:
                from web3 import Web3 as _W3b
                for idx, (success, data) in enumerate(_ve33_results):
                    if success and len(data) >= 32:
                        addr = "0x" + data[-20:].hex()
                        if addr != _ZERO_ADDR:
                            _ve33_pool_addrs.append(_W3b.to_checksum_address(addr))
                            _ve33_pool_dex.append(_ve33_meta[idx])
            # Batch getReserves() for discovered ve33 pools
            if _ve33_pool_addrs:
                _RESERVES_SELECTOR = bytes.fromhex("0902f1ac")
                _reserves_calls = [
                    (pa, True, _RESERVES_SELECTOR) for pa in _ve33_pool_addrs
                ]
                _reserves_results = batcher._execute_multicall(_reserves_calls)
                for idx, pa in enumerate(_ve33_pool_addrs):
                    dex_name, _stable = _ve33_pool_dex[idx]
                    reserve0 = reserve1 = 0
                    if _reserves_results and idx < len(_reserves_results):
                        _rsuc, _rdata = _reserves_results[idx]
                        if _rsuc and len(_rdata) >= 64:
                            reserve0 = int.from_bytes(_rdata[0:32], "big")
                            reserve1 = int.from_bytes(_rdata[32:64], "big")
                    liq = reserve0 + reserve1 if (reserve0 > 0 or reserve1 > 0) else 0
                    entry = {
                        "address": pa,
                        "fee": 1 if _stable else 0,  # E1.24: 0=volatile, 1=stable
                        "liquidity": liq,
                        "pool_state": {"liquidity": liq, "sqrt_price_x96": reserve0, "tick": reserve1},
                    }
                    result.setdefault(dex_name, []).append(entry)
        except Exception as exc:
            logger.debug("ve33 resolve batch failed: %s", str(exc)[:80])

    return result



def enrich_unknown_token(
    token_addr: str,
    rpc_url: str,
    block_num: int,
) -> Dict[str, Any]:
    """Read ERC-20 symbol() and decimals() on-chain via multicall.

    Returns dict with:
        enriched: bool
        symbol: str or None
        decimals: int or None
        source: "onchain"
    """
    from core.multicall import get_multicall_batcher

    try:
        batcher = get_multicall_batcher(rpc_url, block_num)
        symbols = batcher.batch_symbol([token_addr])
        decimals = batcher.batch_decimals([token_addr])
        sym = symbols.get(token_addr)
        dec = decimals.get(token_addr)
        return {
            "enriched": sym is not None,
            "symbol": sym,
            "decimals": dec,
            "source": "onchain",
        }
    except Exception as exc:
        logger.debug("enrich_unknown_token failed for %s: %s", token_addr[:10], str(exc)[:80])
        return {"enriched": False, "symbol": None, "decimals": None, "source": "onchain"}



def enrich_tokens_batch(
    token_addrs: List[str],
    rpc_url: str,
    block_num: int,
) -> Dict[str, Dict[str, Any]]:
    """Batch-enrich multiple unknown token addresses in one multicall.

    Returns {addr_lower: {enriched, symbol, decimals, source}}.
    """
    from core.multicall import get_multicall_batcher

    result: Dict[str, Dict[str, Any]] = {}
    if not token_addrs:
        return result

    # M7.A.5.38: Check module-level cache first (immutable ERC-20 data)
    uncached_addrs = []
    for addr in token_addrs:
        _ck = addr.lower()
        cached = _enrichment_cache.get(_ck)
        if cached is not None:
            result[_ck] = dict(cached)
        else:
            uncached_addrs.append(addr)

    if not uncached_addrs:
        return result

    try:
        batcher = get_multicall_batcher(rpc_url, block_num)
        symbols = batcher.batch_symbol(uncached_addrs)
        decimals_map = batcher.batch_decimals(uncached_addrs)
        for addr in uncached_addrs:
            sym = symbols.get(addr)
            dec = decimals_map.get(addr)
            entry = {
                "enriched": sym is not None,
                "symbol": sym,
                "decimals": dec,
                "source": "onchain",
            }
            _ck = addr.lower()
            result[_ck] = entry
            # Cache only successfully enriched tokens (immutable data)
            if sym is not None:
                _enrichment_cache[_ck] = dict(entry)
    except Exception as exc:
        logger.debug("enrich_tokens_batch failed: %s", str(exc)[:100])
        for addr in uncached_addrs:
            result[addr.lower()] = {
                "enriched": False, "symbol": None, "decimals": None, "source": "onchain",
            }

    return result



def extract_pool_state_for_sim(
    pool_addresses: List[str],
    rpc_url: str,
    block_num: int,
    *,
    chain: Optional[str] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Extract V3 pool state (sqrtPriceX96, tick, liquidity) for local simulation.

    E1.51 slice-3b: when ``ARBY_REGISTRY_FIRST_POOL_STATE=1`` AND ``chain``
    is provided, the local ``PoolPriceStateRegistry`` is consulted FIRST.
    Pools missing from the registry fall back to
    ``MulticallBatcher.batch_full_pool_data`` (the legacy path).

    Default behaviour (env unset / chain=None) is unchanged: full multicall.

    Returns {pool_addr: {sqrt_price_x96, tick, liquidity} or None}.
    """
    if not pool_addresses:
        return {}

    # Slice-3b: registry-first lookup, opt-in via env until canary green.
    use_registry = (
        chain is not None
        and os.environ.get("ARBY_REGISTRY_FIRST_POOL_STATE", "0") in ("1", "true", "True")
    )
    result: Dict[str, Optional[Dict[str, Any]]] = {}
    cold_pools: List[str] = list(pool_addresses)

    if use_registry:
        try:
            from m7.orderflow.pool_price_state import get_registry as _ps_get_registry
            reg = _ps_get_registry()
            cold_pools = []
            for addr in pool_addresses:
                st = reg.get(chain, addr)
                if st is not None:
                    result[addr.lower()] = {
                        "sqrt_price_x96": st.sqrt_price_x96,
                        "tick": st.tick,
                        "liquidity": st.liquidity,
                        "source": "local_registry",
                    }
                else:
                    cold_pools.append(addr)
        except Exception as exc:
            logger.debug("registry-first lookup failed, falling back: %s", str(exc)[:100])
            cold_pools = list(pool_addresses)
            result = {}

    if not cold_pools:
        return result

    try:
        from core.multicall import get_multicall_batcher
        batcher = get_multicall_batcher(rpc_url, block_num)
        rpc_state = batcher.batch_full_pool_data(cold_pools)
    except Exception as exc:
        logger.debug("extract_pool_state_for_sim failed: %s", str(exc)[:100])
        for addr in cold_pools:
            result.setdefault(addr.lower(), None)
        return result

    for addr, st in rpc_state.items():
        result[addr.lower() if isinstance(addr, str) else addr] = st
    return result



def _get_pool_addresses_for_dexes(
    dex_configs: Dict[str, Any],
    token_in_addr: str,
    token_out_addr: str,
) -> List[str]:
    """Legacy shim — returns empty. Actual resolution now uses
    _resolve_pool_addresses_multicall() in the 2-stage pipeline.
    """
    return []


def get_cached_decimals(token_addr: str) -> Optional[int]:
    """Return cached decimals for a token address, or None if not cached.

    Reads from the module-level _enrichment_cache (immutable ERC-20 data).
    """
    cached = _enrichment_cache.get(token_addr.lower())
    if cached is not None:
        return cached.get("decimals")
    return None


def get_cached_symbol(token_addr: str) -> Optional[str]:
    """Return cached symbol for a token address, or None if not cached.

    Reads from the module-level _enrichment_cache. Used by N5 anchor
    recording when addr_to_symbol lacks an entry for the event's token.
    """
    cached = _enrichment_cache.get(token_addr.lower())
    if cached is not None:
        sym = cached.get("symbol")
        if sym:
            return str(sym)
    return None


def batch_pre_resolve_pools(
    pool_addresses: List[str],
    rpc_url: str,
    block_num: int,
    addr_to_symbol: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """Batch-resolve pool tokens and enrich in one pass. Fills module caches.

    M7.A.5.40: Moves per-event resolve+enrichment RPC calls into a single
    batch call before scoring, so that individual scoring calls hit caches.

    For each pool:
      1. Check _pool_token_cache — skip if already known.
      2. Batch-resolve token0/token1/fee via multicall for uncached pools.
      3. Batch-enrich all discovered token addresses (symbol + decimals).

    Returns: {pool_addr_lower: {token0, token1, fee, token_in_sym, token_out_sym}
              or None if resolution failed}.
    Populates _pool_token_cache and _enrichment_cache as side effects.
    """
    if not pool_addresses:
        return {}

    result: Dict[str, Dict[str, Any]] = {}

    # 1. Separate cached vs uncached pools
    uncached_pools: List[str] = []
    for pa in pool_addresses:
        key = pa.lower()
        if key in _pool_token_cache:
            token0, token1, fee = _pool_token_cache[key]
            result[key] = {"token0": token0, "token1": token1, "fee": fee}
        else:
            uncached_pools.append(pa)

    # 2. Batch-resolve uncached pools via multicall
    if uncached_pools:
        try:
            from core.multicall import get_multicall_batcher
            batcher = get_multicall_batcher(rpc_url, block_num)
            batch_info = batcher.batch_token_info(uncached_pools)
            for pa in uncached_pools:
                info = batch_info.get(pa)
                if info is not None:
                    token0, token1, fee = info
                    key = pa.lower()
                    _pool_token_cache[key] = (token0, token1, fee)
                    result[key] = {"token0": token0, "token1": token1, "fee": fee}
        except Exception as exc:
            logger.debug("batch_pre_resolve_pools resolve failed: %s", str(exc)[:100])

    # 3. Collect all unique token addresses for enrichment
    all_token_addrs: List[str] = []
    seen: set = set()
    for info in result.values():
        for tk in (info["token0"], info["token1"]):
            tk_lower = tk.lower()
            if tk_lower not in seen and tk_lower not in _enrichment_cache:
                # Only enrich tokens not already in addr_to_symbol
                if tk_lower not in addr_to_symbol:
                    all_token_addrs.append(tk)
                    seen.add(tk_lower)

    # 4. Batch-enrich unknown tokens
    if all_token_addrs:
        try:
            enriched = enrich_tokens_batch(all_token_addrs, rpc_url, block_num)
            for addr_lower, info in enriched.items():
                if info.get("enriched") and info.get("symbol"):
                    addr_to_symbol[addr_lower] = info["symbol"]
        except Exception as exc:
            logger.debug("batch_pre_resolve_pools enrich failed: %s", str(exc)[:100])

    return result

