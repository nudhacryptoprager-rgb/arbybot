"""
M7 orderflow token resolution, pool-address resolution, enrichment,
and pool-state extraction.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from m7.shared.constants import _DEFAULT_FEE_TIERS

logger = logging.getLogger("m7.orderflow.resolve")

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

    batcher = get_multicall_batcher(rpc_url, block_num)
    info = batcher.batch_token_info([pool_address])
    pool_info = info.get(pool_address)
    if pool_info is None:
        return None

    token0_addr, token1_addr, fee = pool_info

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
    """Resolve V3 pool addresses via batched factory.getPool() multicall.

    Returns {dex_name: [{"address": addr, "fee": fee, "liquidity": int|None}, ...]}.
    One multicall for getPool + one for liquidity.
    """
    from core.multicall import get_multicall_batcher

    batcher = get_multicall_batcher(rpc_url, block_num)

    # Build getPool queries for all V3 factories × fee tiers
    queries: List[tuple] = []  # (factory, tokenA, tokenB, fee)
    query_meta: List[tuple] = []  # (dex_name, fee)
    for dex_name, cfg in dex_configs.items():
        adapter_type = cfg.get("adapter_type", "")
        factory = cfg.get("factory", "")
        if not factory:
            continue
        if adapter_type not in ("uniswap_v3", "algebra"):
            continue
        fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
        for fee in fee_tiers[:2]:  # Top 2 fee tiers only
            queries.append((factory, token_a, token_b, fee))
            query_meta.append((dex_name, fee))

    if not queries:
        return {}

    pool_addrs = batcher.batch_get_pool(queries)

    # M7.A.5.12: Use batch_full_pool_data as canonical pool state source
    # (unifies coverage scan and local-sim truth — single RPC extraction)
    valid_addrs = [a for a in pool_addrs if a is not None]
    full_state_map: Dict[str, Optional[Dict[str, Any]]] = {}
    if valid_addrs:
        full_state_map = batcher.batch_full_pool_data(valid_addrs)

    # Build result grouped by dex
    result: Dict[str, List[Dict[str, Any]]] = {}
    for i, addr in enumerate(pool_addrs):
        dex_name, fee = query_meta[i]
        pool_state = full_state_map.get(addr) if addr else None
        entry = {
            "address": addr,
            "fee": fee,
            "liquidity": pool_state.get("liquidity") if pool_state else None,
            "pool_state": pool_state,  # M7.A.5.12: full state for reuse
        }
        result.setdefault(dex_name, []).append(entry)

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

    try:
        batcher = get_multicall_batcher(rpc_url, block_num)
        symbols = batcher.batch_symbol(token_addrs)
        decimals_map = batcher.batch_decimals(token_addrs)
        for addr in token_addrs:
            sym = symbols.get(addr)
            dec = decimals_map.get(addr)
            result[addr.lower()] = {
                "enriched": sym is not None,
                "symbol": sym,
                "decimals": dec,
                "source": "onchain",
            }
    except Exception as exc:
        logger.debug("enrich_tokens_batch failed: %s", str(exc)[:100])
        for addr in token_addrs:
            result[addr.lower()] = {
                "enriched": False, "symbol": None, "decimals": None, "source": "onchain",
            }

    return result



def extract_pool_state_for_sim(
    pool_addresses: List[str],
    rpc_url: str,
    block_num: int,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Extract V3 pool state (sqrtPriceX96, tick, liquidity) for local simulation.

    Uses existing MulticallBatcher.batch_full_pool_data() to read slot0 + liquidity
    in one multicall. This is the state-preparation step for future local pricing.

    Returns {pool_addr: {sqrt_price_x96, tick, liquidity} or None}.
    """
    if not pool_addresses:
        return {}

    try:
        from core.multicall import get_multicall_batcher
        batcher = get_multicall_batcher(rpc_url, block_num)
        return batcher.batch_full_pool_data(pool_addresses)
    except Exception as exc:
        logger.debug("extract_pool_state_for_sim failed: %s", str(exc)[:100])
        return {addr: None for addr in pool_addresses}



def _get_pool_addresses_for_dexes(
    dex_configs: Dict[str, Any],
    token_in_addr: str,
    token_out_addr: str,
) -> List[str]:
    """Legacy shim — returns empty. Actual resolution now uses
    _resolve_pool_addresses_multicall() in the 2-stage pipeline.
    """
    return []

