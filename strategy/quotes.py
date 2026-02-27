# PATH: strategy/quotes.py
"""
Quote collection logic for scan jobs.

Extracted from run_scan_real.py for modularity.
Contains functions for fetching quotes from DEX pools.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.pairs import load_pairs, get_pool_address, is_pool_disabled, PairConfig
from strategy.compat import QuoteCompat
from strategy.quarantine import get_quarantine_manager
from strategy.dynamic_anchors import get_anchor_manager

logger = logging.getLogger("strategy.quotes")

# =============================================================================
# MULTICALL PREFETCH CACHE (v2.2.0)
# =============================================================================

# Module-level cache for multicall prefetch results
_multicall_slot0_cache: Dict[str, Optional[Tuple[int, int]]] = {}
_multicall_liquidity_cache: Dict[str, Optional[int]] = {}  # v2.2.0 Fix Step 6: Add liquidity cache
_multicall_token_info_cache: Dict[str, Optional[Tuple[str, str, int]]] = {}  # v2.2.0 Fix Step 6: Add token_info cache
_multicall_decimals_cache: Dict[str, Optional[int]] = {}  # v2.2.0 Fix Step 5: Add decimals cache


def prefetch_slot0_multicall(
    pool_addresses: List[str], rpc_url: str, block_num: int
) -> Dict[str, Optional[Tuple[int, int]]]:
    """
    Prefetch slot0, liquidity, and token_info data for multiple pools using multicall.
    
    v2.2.0: Roadmap M5_0 requires multicall batching per cycle.
    This reduces RPC calls from N to 1 for N pools.
    
    v2.2.0 Fix Step 6: Also batch liquidity() calls.
    v2.2.1 Fix Step 6: Also batch token_info() calls (token0, token1, fee).
    
    Args:
        pool_addresses: List of pool addresses to fetch
        rpc_url: RPC URL
        block_num: Block number
        
    Returns:
        Dict mapping pool_address -> (tick, sqrt_price_x96) or None
    """
    global _multicall_slot0_cache, _multicall_liquidity_cache, _multicall_token_info_cache
    
    if not pool_addresses or not rpc_url:
        return {}
    
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return {addr: None for addr in pool_addresses}
    
    try:
        from core.multicall import get_multicall_batcher
        
        batcher = get_multicall_batcher(rpc_url, block_num)
        
        # Batch slot0 calls
        results = batcher.batch_slot0(pool_addresses)
        
        # v2.2.0 Fix Step 6: Also batch liquidity calls
        liquidity_results = batcher.batch_liquidity(pool_addresses)
        
        # v2.2.0 Fix Step 6: Also batch token_info calls (token0, token1, fee)
        token_info_results = batcher.batch_token_info(pool_addresses)
        
        # v2.2.0 Fix Step 5: Batch decimals for unique tokens from token_info
        unique_tokens: set[str] = set()
        for info in token_info_results.values():
            if info is not None:
                token0, token1, _ = info
                if token0:
                    unique_tokens.add(token0.lower())
                if token1:
                    unique_tokens.add(token1.lower())
        
        decimals_results: Dict[str, Optional[int]] = {}
        if unique_tokens:
            decimals_results = batcher.batch_decimals(list(unique_tokens))
        
        # Convert from (sqrt, tick, liq) to (tick, sqrt)
        output = {}
        for addr, data in results.items():
            if data is not None:
                sqrt_price, tick, _ = data
                output[addr.lower()] = (tick, sqrt_price)
            else:
                output[addr.lower()] = None
        
        # Update caches
        _multicall_slot0_cache.update(output)
        _multicall_liquidity_cache.update({k.lower(): v for k, v in liquidity_results.items()})
        _multicall_token_info_cache.update({k.lower(): v for k, v in token_info_results.items()})
        _multicall_decimals_cache.update({k.lower(): v for k, v in decimals_results.items()})
        
        success_count = sum(1 for v in output.values() if v is not None)
        liq_count = sum(1 for v in liquidity_results.values() if v is not None)
        token_count = sum(1 for v in token_info_results.values() if v is not None)
        decimals_count = sum(1 for v in decimals_results.values() if v is not None)
        logger.info("Multicall prefetch: %d pools, %d tokens, success: slot0=%d, liquidity=%d, token_info=%d, decimals=%d", 
                   len(pool_addresses), len(unique_tokens), success_count, liq_count, token_count, decimals_count)
        return output
    except Exception as e:
        logger.debug("Multicall prefetch failed: %s", e)
        return {addr: None for addr in pool_addresses}


def get_cached_liquidity(pool_address: str) -> Optional[int]:
    """Get liquidity from multicall cache if available."""
    return _multicall_liquidity_cache.get(pool_address.lower())


def get_cached_token_info(pool_address: str) -> Optional[Tuple[str, str, int]]:
    """Get token_info (token0, token1, fee) from multicall cache if available."""
    return _multicall_token_info_cache.get(pool_address.lower())


def get_cached_decimals(token_address: str) -> Optional[int]:
    """Get decimals from multicall cache if available."""
    return _multicall_decimals_cache.get(token_address.lower())


def clear_multicall_cache() -> None:
    """Clear the multicall prefetch cache (for testing)."""
    global _multicall_slot0_cache, _multicall_liquidity_cache, _multicall_token_info_cache, _multicall_decimals_cache
    _multicall_slot0_cache.clear()
    _multicall_liquidity_cache.clear()  # v2.2.0 Fix Step 6
    _multicall_token_info_cache.clear()  # v2.2.0 Fix Step 6
    _multicall_decimals_cache.clear()  # v2.2.0 Fix Step 5


def read_slot0_v3(pool_address: str, rpc_url: Optional[str], block_num: int) -> Tuple[Optional[int], Optional[int]]:
    """
    Read slot0() from a Uniswap V3 pool contract.
    
    v2.2.0: Checks multicall cache first if prefetch was done.
    
    Args:
        pool_address: Pool contract address
        rpc_url: RPC URL to use
        block_num: Block number to query at
        
    Returns:
        (tick, sqrtPriceX96) or (None, None) on failure
    """
    if not pool_address or not rpc_url:
        return None, None
    
    # v2.2.0: Check multicall cache first
    cache_key = pool_address.lower()
    if cache_key in _multicall_slot0_cache:
        cached = _multicall_slot0_cache[cache_key]
        if cached is not None:
            logger.debug("slot0() from multicall cache for %s", pool_address)
            return cached  # (tick, sqrt_price_x96)
        # None in cache means multicall tried and failed - fall through to direct read
    
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None, None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.debug("slot0() skipped: web3 not installed")
        return None, None
    
    try:
        abi_path = Path(__file__).parent.parent / "dex" / "abi" / "uniswap_v3_pool.json"
        if not abi_path.exists():
            logger.debug("slot0() skipped: ABI not found at %s", abi_path)
            return None, None
        
        abi = json.loads(abi_path.read_text(encoding="utf8"))
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=abi)
        slot0 = pool.functions.slot0().call(block_identifier=block_num)
        
        sqrt_price_x96 = int(slot0[0])
        tick = int(slot0[1])
        logger.debug("slot0() success for %s: tick=%s, sqrtPriceX96=%s", pool_address, tick, sqrt_price_x96)
        return tick, sqrt_price_x96
    except Exception as e:
        logger.debug("slot0() read failed for %s: %s", pool_address, e)
        return None, None


# =============================================================================
# USD-NOTIONAL SIZING (M4.2)
# =============================================================================

# Default USD prices for common tokens (for sizing, not profit calc)
DEFAULT_TOKEN_USD_PRICES = {
    "WETH": 2000.0,
    "ETH": 2000.0,
    "WBTC": 34000.0,
    "USDC": 1.0,
    "USDT": 1.0,
    "DAI": 1.0,
    "ARB": 0.70,
    "LINK": 11.0,
    "GMX": 24.0,
    "wstETH": 2300.0,
    "UNI": 6.0,
    "AAVE": 100.0,
}


def calculate_amount_in_wei(
    token_symbol: str,
    decimals: int,
    target_usd_notional: float,
    tokens_usd_price: Optional[Dict[str, float]] = None,
) -> int:
    """
    Calculate amount_in_wei for a given USD notional target.
    
    M4.2 CONTRACT:
    - All quotes use consistent USD notional (e.g., $1000)
    - This makes profit metrics comparable across pairs
    
    Args:
        token_symbol: Input token symbol (e.g., "WETH")
        decimals: Token decimals
        target_usd_notional: Target USD value (e.g., 1000.0)
        tokens_usd_price: Optional price overrides
        
    Returns:
        Amount in wei (int)
    """
    # Merge config prices with defaults
    prices = dict(DEFAULT_TOKEN_USD_PRICES)
    if tokens_usd_price:
        prices.update(tokens_usd_price)
    
    # Get token USD price
    token_price = prices.get(token_symbol, 1.0)  # Default $1 if unknown
    
    # v2.2.3: Warn if using default fallback price (not from config)
    if tokens_usd_price and token_symbol not in tokens_usd_price:
        if token_symbol in DEFAULT_TOKEN_USD_PRICES:
            logger.warning("USD_PRICE_FALLBACK_USED: %s using default $%.2f (not in config)", 
                          token_symbol, token_price)
    
    if token_price <= 0:
        logger.warning("Invalid token price for %s: %s, using $1", token_symbol, token_price)
        token_price = 1.0
    
    # Calculate token amount for target USD notional
    token_amount = target_usd_notional / token_price
    
    # Convert to wei
    amount_in_wei = int(token_amount * (10 ** decimals))
    
    logger.debug(
        "USD-notional sizing: %s $%.0f -> %.6f tokens -> %d wei",
        token_symbol, target_usd_notional, token_amount, amount_in_wei
    )
    
    return amount_in_wei


# =============================================================================
# QUOTER V2 - Executable quotes (M4.2)
# =============================================================================

def read_quoter_v2(
    quoter_address: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int,
    rpc_url: Optional[str],
    block_num: int,
) -> Optional[Dict[str, Any]]:
    """
    Get executable quote from QuoterV2 contract.
    
    M4.2 CONTRACT:
    - Returns actual amountOut (not spot price)
    - Returns gas_estimate and ticks_crossed
    - Can detect low liquidity (high ticks/gas)
    
    Args:
        quoter_address: QuoterV2 contract address
        token_in: Input token address
        token_out: Output token address
        amount_in: Input amount in wei
        fee: Fee tier
        rpc_url: RPC URL
        block_num: Block number
        
    Returns:
        Dict with: amount_out, sqrt_price_after, ticks_crossed, gas_estimate
        None on failure
    """
    if not quoter_address or not rpc_url:
        return None
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.debug("QuoterV2 skipped: web3 not installed")
        return None
    
    try:
        # Encode quoteExactInputSingle call
        from dex.adapters.uniswap_v3 import (
            encode_quote_exact_input_single,
            decode_quote_response,
        )
        
        call_data = encode_quote_exact_input_single(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            fee=fee,
        )
        
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        result_hex = w3.eth.call(
            {"to": Web3.to_checksum_address(quoter_address), "data": call_data},
            block_identifier=block_num,
        ).hex()
        
        amount_out, sqrt_price_after, ticks_crossed, gas_estimate = decode_quote_response(result_hex)
        
        logger.debug(
            "QuoterV2 success: %s -> %s, amountOut=%d, ticks=%d, gas=%d",
            token_in[:10], token_out[:10], amount_out, ticks_crossed, gas_estimate
        )
        
        return {
            "amount_out": amount_out,
            "sqrt_price_after": sqrt_price_after,
            "ticks_crossed": ticks_crossed,
            "gas_estimate": gas_estimate,
        }
    except Exception as e:
        logger.debug("QuoterV2 failed: %s", e)
        return None


def read_algebra_quoter(
    quoter_address: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    rpc_url: Optional[str],
    block_num: int,
) -> Optional[Dict[str, Any]]:
    """
    Get executable quote from Algebra (Camelot) quoter contract.
    
    Algebra quoter uses different signature than UniswapV3 QuoterV2:
    - No fee parameter (Algebra has dynamic fees)
    - Different return values
    
    Args:
        quoter_address: Algebra quoter contract address
        token_in: Input token address
        token_out: Output token address
        amount_in: Input amount in wei
        rpc_url: RPC URL
        block_num: Block number
        
    Returns:
        Dict with: amount_out, gas_estimate
        None on failure
    """
    if not quoter_address or not rpc_url:
        return None
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.debug("Algebra quoter skipped: web3 not installed")
        return None
    
    try:
        # Algebra quoteExactInputSingle(address tokenIn, address tokenOut, uint256 amountIn, uint160 limitSqrtPrice)
        # Returns (uint256 amountOut, uint16 fee)
        # Selector: 0x2d58eb1d
        SELECTOR = "0x2d58eb1d"
        
        token_in_padded = token_in[2:].lower().zfill(64)
        token_out_padded = token_out[2:].lower().zfill(64)
        amount_in_hex = hex(amount_in)[2:].zfill(64)
        sqrt_price_limit = hex(0)[2:].zfill(64)  # 0 = no limit
        
        call_data = f"{SELECTOR}{token_in_padded}{token_out_padded}{amount_in_hex}{sqrt_price_limit}"
        
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        result_hex = w3.eth.call(
            {"to": Web3.to_checksum_address(quoter_address), "data": call_data},
            block_identifier=block_num,
        ).hex()
        
        if not result_hex or result_hex == "0x":
            logger.debug("Algebra quoter empty response")
            return None
        
        data = result_hex[2:] if result_hex.startswith("0x") else result_hex
        if len(data) < 64:
            logger.debug("Algebra quoter response too short: %d", len(data))
            return None
        
        amount_out = int(data[0:64], 16)
        # dynamic_fee = int(data[64:128], 16) if len(data) >= 128 else None
        
        logger.debug(
            "Algebra quoter success: %s -> %s, amountOut=%d",
            token_in[:10], token_out[:10], amount_out
        )
        
        return {
            "amount_out": amount_out,
            "sqrt_price_after": None,  # Algebra doesn't return this
            "ticks_crossed": None,
            "gas_estimate": 200_000,  # Conservative estimate for Algebra
        }
    except Exception as e:
        logger.debug("Algebra quoter failed: %s", e)
        return None


def synthesize_sqrt_price_from_anchor(
    anchor_price: float,
    decimals_in: int,
    decimals_out: int,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Synthesize sqrtPriceX96 from anchor price for test mode.
    
    Args:
        anchor_price: Anchor price to use
        decimals_in: Decimals of token_in
        decimals_out: Decimals of token_out
        
    Returns:
        (tick, sqrtPriceX96) or (None, None) on failure
    """
    from math import sqrt
    try:
        decimals_diff_pow = 10 ** (decimals_in - decimals_out)
        raw_price = anchor_price / decimals_diff_pow
        sqrt_price_val = int(sqrt(raw_price) * (2 ** 96))
        tick_val = 0  # Placeholder for test mode
        return tick_val, sqrt_price_val
    except Exception as e:
        logger.warning("Failed to synthesize sqrtPriceX96 from anchor: %s", e)
        return None, None


def calculate_price_from_sqrt(
    sqrt_price_val: int,
    token_in_addr: str,
    token_out_addr: str,
    decimals_in: int,
    decimals_out: int,
) -> Optional[Decimal]:
    """
    Calculate price from sqrtPriceX96.
    
    v2.1.0-fix: Use Decimal exponentiation to avoid overflow with high-decimal 
    difference pairs (e.g., WBTC(8) / WETH(18) = -10 decimals diff).
    Previously used `10 ** (decimals_in - decimals_out)` which could overflow
    to float for large negative exponents.
    
    Args:
        sqrt_price_val: sqrtPriceX96 value
        token_in_addr: Address of token_in
        token_out_addr: Address of token_out
        decimals_in: Decimals of token_in
        decimals_out: Decimals of token_out
        
    Returns:
        Price as Decimal or None on failure
    """
    if sqrt_price_val is None or sqrt_price_val <= 0:
        return None
    
    try:
        sqrt_ratio = Decimal(sqrt_price_val) / Decimal(2 ** 96)
        raw_price = sqrt_ratio * sqrt_ratio
        
        # v2.1.0-fix: Use Decimal(10) ** exp to avoid float overflow for large
        # negative exponents (e.g., WBTC/WETH has decimals_in=8, decimals_out=18)
        decimals_exp = decimals_in - decimals_out
        decimals_diff = Decimal(10) ** decimals_exp
        
        if token_in_addr and token_out_addr:
            token_in_is_token0 = token_in_addr.lower() < token_out_addr.lower()
            
            if token_in_is_token0:
                return raw_price * decimals_diff
            else:
                return (Decimal(1) / raw_price) * decimals_diff
        else:
            return raw_price * decimals_diff
    except Exception as e:
        logger.warning("Price calculation failed: %s", e)
        return None


def collect_quotes(
    config: Dict[str, Any],
    current_block: int,
    rpc_latency: int = 0,
    pairs_list: Optional[List[PairConfig]] = None,  # v2.6.0: Allow passing pre-resolved pairs
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Collect quotes from DEX pools.
    
    Args:
        config: Configuration dict
        current_block: Current block number
        rpc_latency: RPC latency in ms
        pairs_list: Optional pre-resolved pairs (for discovery_runtime mode)
        
    Returns:
        (quotes_sample, rejected_quotes, counts)
    """
    quotes_sample: List[Dict[str, Any]] = []
    rejected_quotes: List[Dict[str, Any]] = []
    
    counts = {
        "quotes_fetched": 0,
        "pool_missing": 0,
        "pool_disabled": 0,
        "quarantined": 0,
        "v3_slot0_failed": 0,
        "price_calc_failed": 0,
        "no_onchain_price": 0,
        "algebra_needs_quoter": 0,
    }
    
    # v2.3.0: Track failed pool addresses for actionable diagnostics
    failed_pool_addresses: List[Dict[str, str]] = []
    
    # v2.3.1: Track pool_missing_keys for observability (what pools were skipped)
    pool_missing_keys: List[str] = []
    
    # Get quarantine manager for runtime auto-quarantine
    qm = get_quarantine_manager()
    
    # Get dynamic anchor manager
    am = get_anchor_manager()
    
    dexes_list = config.get("dexes") or []
    pools_cfg = config.get("pools", {}) or {}
    token_addresses = config.get("tokens", {}) or {}
    
    # Load pairs from config or use pre-resolved pairs
    # v2.6.0: Allow passing pre-resolved pairs for discovery_runtime mode
    chain_key = config.get("chain", "arbitrum_one")
    if pairs_list is None:
        # v2.3.1 FIX: Respect universe_source from config
        universe_source = config.get("universe_source", "config")
        use_intent = (universe_source == "intent")
        force_intent = (universe_source in ("intent_verified", "intent_forced"))
        pairs_list = load_pairs(chain_key, config, use_intent=use_intent, force_intent=force_intent)
    
    if not pairs_list:
        from config.pairs import get_pair_info
        fallback_pair = get_pair_info(chain_key, "WETH", "USDC")
        if fallback_pair:
            pairs_list = [fallback_pair]
    
    logger.info("Scanning %d pairs: %s", len(pairs_list), [p.display_name for p in pairs_list])
    
    # RPC URL for slot0 reads
    rpc_url = os.environ.get("ARBY_RPC_HTTP_PRIMARY") or (config.get("rpc_endpoints") or [None])[0]
    skip_rpc = os.environ.get("ARBY_SKIP_RPC") == "1"
    tokens_anchor_price = config.get("tokens_anchor_price") or {}
    
    # v2.2.0: Multicall prefetch for slot0 batching (Roadmap M5_0 requirement)
    use_multicall = config.get("use_multicall", True)  # Default ON for v2.2.0
    if use_multicall and rpc_url and not skip_rpc:
        # Collect all pool addresses that will be queried
        all_pool_addrs: List[str] = []
        for pair_cfg in pairs_list:
            # v2.6.0: Use pre-resolved pool_addresses if available (discovery_runtime)
            if pair_cfg.pool_addresses:
                all_pool_addrs.extend(pair_cfg.pool_addresses)
            else:
                # Fall back to config lookup
                token_pair_tag = pair_cfg.pair_tag
                fee_tiers = pair_cfg.fee_tiers or [500, 3000]
                for dex in dexes_list:
                    from dex.registry import get_dex_config
                    dex_cfg = get_dex_config(chain_key, dex)
                    adapter_type = dex_cfg.adapter_type if dex_cfg else None
                    
                    if adapter_type == "algebra":
                        effective_fees = [0]
                    else:
                        effective_fees = fee_tiers
                    
                    for fee in effective_fees:
                        pool_addr = get_pool_address(config, dex, token_pair_tag, fee_tier=fee)
                        if pool_addr:
                            all_pool_addrs.append(pool_addr)
        
        # Unique pool addresses
        unique_pools = list(set(all_pool_addrs))
        if unique_pools:
            logger.info("Multicall prefetch: %d unique pools", len(unique_pools))
            clear_multicall_cache()  # Clear cache before prefetch
            prefetch_slot0_multicall(unique_pools, rpc_url, current_block)
    
    # M4.2: USD-notional sizing
    target_usd_notional = config.get("target_usd_notional", 1000.0)
    tokens_usd_price = config.get("tokens_usd_price") or {}
    use_usd_notional = config.get("use_usd_notional", True)  # Default ON for M4.2
    
    for pair_cfg in pairs_list:
        token_pair_tag = pair_cfg.pair_tag
        token_in = pair_cfg.token_in
        token_out = pair_cfg.token_out
        decimals_in = pair_cfg.token_in_decimals
        decimals_out = pair_cfg.token_out_decimals
        
        # Get anchor price for this pair (v2.2.0: prefer dynamic over YAML)
        yaml_anchor = tokens_anchor_price.get(token_pair_tag)
        if not yaml_anchor:
            reversed_tag = f"{token_out}_{token_in}"
            yaml_anchor = tokens_anchor_price.get(reversed_tag)
            if yaml_anchor:
                yaml_anchor = 1.0 / yaml_anchor
        
        # Dynamic anchor with YAML fallback
        pair_tag_display = f"{token_in}/{token_out}"
        anchor_price, anchor_source = am.get_anchor(pair_tag_display, yaml_anchor)
        
        # v2.0.7: Iterate over fee_tiers from pair config
        fee_tiers = pair_cfg.fee_tiers or [500, 3000]
        chain_name = config.get("chain", "arbitrum_one")
        
        # v2.4.0: Build pool work items from either pool_info (discovery_runtime) or dex/fee iteration (config)
        from dex.registry import get_dex_config
        pool_work_items = []
        
        if pair_cfg.pool_info:
            # discovery_runtime mode: use pre-resolved pools with exact (dex, fee, address)
            for pi in pair_cfg.pool_info:
                pi_dex = pi["dex"]
                pi_fee = pi["fee"]
                pi_addr = pi["address"]
                pi_dex_cfg = get_dex_config(chain_name, pi_dex)
                pi_adapter = pi_dex_cfg.adapter_type if pi_dex_cfg else None
                pool_work_items.append((pi_dex, pi_fee, pi_addr, pi_dex_cfg, pi_adapter))
        else:
            # config mode: iterate over dexes and fee_tiers, lookup pool addresses
            for dex in dexes_list:
                dex_cfg = get_dex_config(chain_name, dex)
                adapter_type = dex_cfg.adapter_type if dex_cfg else None
                
                # M4.2 FIX: Algebra DEXes use dynamic fees, use fee=0 for pool lookup
                if adapter_type == "algebra":
                    effective_fee_tiers = [0]  # Dynamic fee - lookup with fee=0
                else:
                    effective_fee_tiers = fee_tiers
                
                for fee_tier in effective_fee_tiers:
                    # v2.6.1 FIX: Check disabled_pools BEFORE pool lookup
                    # If pool is explicitly disabled, count as POOL_DISABLED not POOL_MISSING
                    disabled_info = is_pool_disabled(config, dex, token_pair_tag, fee_tier)
                    if disabled_info:
                        counts["pool_disabled"] += 1
                        logger.debug("POOL_DISABLED (config): %s %s/%s fee=%d reason=%s", 
                                   dex, token_in, token_out, fee_tier, disabled_info.get('reason', 'DISABLED'))
                        continue
                    
                    pool_addr = get_pool_address(config, dex, token_pair_tag, fee_tier=fee_tier)
                    if pool_addr:
                        pool_work_items.append((dex, fee_tier, pool_addr, dex_cfg, adapter_type))
                    else:
                        # v2.3.0: Silent skip (not reject) for unconfigured pools
                        counts["pool_missing"] += 1
                        pool_key = f"{dex}_{token_pair_tag}_{fee_tier}"
                        pool_missing_keys.append(pool_key)
                        logger.debug("POOL_SKIP: %s %s/%s fee=%d - not in config (key=%s)", 
                                    dex, token_in, token_out, fee_tier, pool_key)
        
        for dex, fee_tier, pool_addr, dex_cfg, adapter_type in pool_work_items:
            # v2.1.0-fix: Check disabled_pools FIRST (before pool lookup)
            disabled_info = is_pool_disabled(config, dex, token_pair_tag, fee_tier)
            if disabled_info:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "reason": "POOL_DISABLED",
                    "gate_passed": False,
                    "error": f"Pool disabled: {disabled_info.get('reason', 'DISABLED')} - {disabled_info.get('detail', '')}",
                    "disabled_info": disabled_info,
                })
                counts["pool_disabled"] += 1
                logger.info("POOL_DISABLED: %s %s/%s fee=%d reason=%s", 
                           dex, token_in, token_out, fee_tier, disabled_info.get('reason', 'DISABLED'))
                continue
            
            # v2.1.0-fix: Check runtime quarantine (auto-quarantine for failing pools)
            pair_tag = f"{token_in}/{token_out}"
            if qm.is_quarantined(dex, pair_tag, fee_tier):
                remaining = qm.get_quarantine_remaining(dex, pair_tag, fee_tier)
                rejected_quotes.append({
                    "pair": pair_tag,
                    "dex_id": dex,
                    "fee": fee_tier,
                    "reason": "QUARANTINED",
                    "gate_passed": False,
                    "error": f"Pool quarantined (remaining: {remaining:.0f}s)",
                })
                counts["quarantined"] += 1
                logger.info("QUARANTINED: %s %s fee=%d (remaining: %.0fs)", 
                           dex, pair_tag, fee_tier, remaining)
                continue
            
            # TODO(M4.2): Replace slot0 with QuoterV2 for executable quotes
            # See dex/adapters/uniswap_v3.py UniswapV3Adapter
            # Quoter addresses in config/dexes.yaml: quoter_v2
            # This would give: amountOut, ticksCrossed, gasEstimate
            
            # M4.2 Preview: Try QuoterV2 if configured (optional feature flag)
            use_quoter_v2 = config.get("use_quoter_v2", False)
            quoter_result = None
            
            # M4.2: Calculate amount_in_wei using USD-notional sizing
            if use_usd_notional:
                amount_in_wei = calculate_amount_in_wei(
                    token_in, decimals_in, target_usd_notional, tokens_usd_price
                )
            else:
                amount_in_wei = 10 ** decimals_in  # Legacy: 1 token
            
            # M4.2 FIX: Use adapter_type for branching (reuse from outer loop)
            is_v3_dex = adapter_type in ("uniswap_v3", "algebra")
            is_algebra = adapter_type == "algebra"
            
            if use_quoter_v2 and dex_cfg:
                quoter_addr = dex_cfg.get_quoter_address()
                if quoter_addr:
                    token_in_addr = token_addresses.get(token_in, "")
                    token_out_addr = token_addresses.get(token_out, "")
                    
                    if adapter_type == "uniswap_v3":
                        # UniswapV3 QuoterV2
                        quoter_result = read_quoter_v2(
                            quoter_addr, token_in_addr, token_out_addr,
                            amount_in_wei, fee_tier, rpc_url, current_block
                        )
                    elif adapter_type == "algebra":
                        # Algebra quoter (Camelot) - use fee=0 for dynamic fees
                        quoter_result = read_algebra_quoter(
                            quoter_addr, token_in_addr, token_out_addr,
                            amount_in_wei, rpc_url, current_block
                        )
            
            # M4.2 FIX: If quoter_result is successful, we DON'T need slot0 at all
            # quoter_result gives executable amount_out, price derived from amount_out/amount_in
            # v2.8.0: But we DO want sqrt_price_x96 for slippage measurement (before-price)
            tick_val, sqrt_price_val = None, None
            quoter_success = quoter_result and quoter_result.get("amount_out", 0) > 0
            
            # v2.8.0: Try to get sqrt_price_x96 from multicall cache for slippage measurement
            # This is the "before" price - quoter gives us "after" price via sqrt_price_after
            cached_slot0 = _multicall_slot0_cache.get(pool_addr.lower())
            if cached_slot0:
                tick_val, sqrt_price_val = cached_slot0
            
            # Path A: quoter canonical - skip slot0 for v3/algebra when quoter succeeds
            if quoter_success:
                # Use quoter data directly - no slot0 needed
                amount_out_wei_val = quoter_result["amount_out"]
                amount_out_human_val = float(Decimal(amount_out_wei_val) / Decimal(10 ** decimals_out))
                amount_out_human_str = str(round(amount_out_human_val, 6))
                amount_in_human_str = str(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
                # Price from quoter amounts
                amount_in_tokens = float(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
                price_exact = Decimal(str(amount_out_human_val)) / Decimal(str(amount_in_tokens)) if amount_in_tokens > 0 else Decimal(0)
                price_str = str(round(float(price_exact), 6))
                quote_source = "quoter_v2"
                gas_estimate = quoter_result.get("gas_estimate")
                ticks_crossed = quoter_result.get("ticks_crossed")
                
                # v2.0.9: SUSPECT_LIQUIDITY gate - reject high-impact quotes early
                from core.constants import QUOTER_MAX_TICKS_CROSSED, QUOTER_MAX_GAS_ESTIMATE
                suspect_liquidity_reason = None
                if ticks_crossed is not None and ticks_crossed > QUOTER_MAX_TICKS_CROSSED:
                    suspect_liquidity_reason = f"ticks_crossed={ticks_crossed}>{QUOTER_MAX_TICKS_CROSSED}"
                elif gas_estimate is not None and gas_estimate > QUOTER_MAX_GAS_ESTIMATE:
                    suspect_liquidity_reason = f"gas_estimate={gas_estimate}>{QUOTER_MAX_GAS_ESTIMATE}"
                
                if suspect_liquidity_reason:
                    rejected_quotes.append({
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "SUSPECT_LIQUIDITY",
                        "gate_passed": False,
                        "error": suspect_liquidity_reason,
                        "ticks_crossed": ticks_crossed,
                        "gas_estimate": gas_estimate,
                    })
                    counts["quotes_rejected"] = counts.get("quotes_rejected", 0) + 1
                    counts["suspect_liquidity"] = counts.get("suspect_liquidity", 0) + 1
                    logger.debug("SUSPECT_LIQUIDITY: %s %s/%s fee=%d: %s", 
                                dex, token_in, token_out, fee_tier, suspect_liquidity_reason)
                    # v2.4.0: Record failure for auto-quarantine
                    qm.record_failure(dex, f"{token_in}/{token_out}", fee_tier, "SUSPECT_LIQUIDITY",
                                     details={"pool_address": pool_addr, "error": suspect_liquidity_reason})
                    continue  # Skip this quote
                
                # v2.1.0: PRICE_SANITY gate (per-quote)
                price_sanity_enabled = config.get("price_sanity_enabled", True)
                price_sanity_max_bps = config.get("price_sanity_max_deviation_bps", 5000)
                if price_sanity_enabled and anchor_price:
                    from decimal import Decimal as _Decimal
                    from core.validators import check_price_sanity
                    sanity_passed, sanity_dev_bps, sanity_err, sanity_diag = check_price_sanity(
                        price=_Decimal(str(price_exact)),
                        anchor_price=_Decimal(str(anchor_price)),
                        pair=f"{token_in}/{token_out}",
                        dex_id=dex,
                        fee_tier=fee_tier,
                        max_deviation_bps=price_sanity_max_bps,
                        anchor_source="tokens_anchor_price",
                        pool_address=pool_addr,
                    )
                    if not sanity_passed:
                        # v2.1.0 Step 8: Enhanced price_sanity reject logging
                        try:
                            ratio = float(price_exact) / float(anchor_price) if anchor_price else 0.0
                        except (TypeError, ZeroDivisionError):
                            ratio = 0.0
                        
                        rejected_quotes.append({
                            "pair": f"{token_in}/{token_out}",
                            "dex_id": dex,
                            "fee": fee_tier,
                            "pool_address": pool_addr,
                            "reason": "PRICE_SANITY_FAILED",  # v2.1.0: Match ErrorCode canonical
                            "gate_passed": False,
                            "error": sanity_err,
                            "deviation_bps": sanity_dev_bps,
                            "anchor_price": str(anchor_price),
                            "price_exact": str(price_exact),
                            # v2.1.0 Step 8: Enhanced diagnostics
                            "price_ratio": round(ratio, 4),
                            "anchor_source": anchor_source,  # v2.2.0: dynamic or yaml_fallback
                            "amount_in_wei": amount_in_wei,
                            "notional_usd_target": target_usd_notional if use_usd_notional else None,
                            "diagnostics": sanity_diag,
                        })
                        counts["quotes_rejected"] = counts.get("quotes_rejected", 0) + 1
                        counts["price_sanity_failed"] = counts.get("price_sanity_failed", 0) + 1
                        # v2.2.2: Record failure for auto-quarantine (same as SUSPECT_LIQUIDITY)
                        qm.record_failure(dex, f"{token_in}/{token_out}", fee_tier, "PRICE_SANITY_FAILED",
                                         details={"pool_address": pool_addr, "deviation_bps": sanity_dev_bps,
                                                  "anchor_price": str(anchor_price), "price_exact": str(price_exact)})
                        # v2.1.0: Log at INFO level for visibility of price sanity failures
                        logger.info(
                            "PRICE_SANITY_FAILED: %s %s/%s fee=%d dev=%d bps anchor=%s observed=%s ratio=%.4f",
                            dex, token_in, token_out, fee_tier, sanity_dev_bps,
                            str(anchor_price)[:12], str(price_exact)[:12], ratio
                        )
                        continue  # Skip this quote
                
                # Build quote directly from quoter data
                q = QuoteCompat(
                    dex_id=dex,
                    pool_address=pool_addr,
                    token_in=token_in,
                    token_out=token_out,
                    fee=fee_tier,
                    amount_in_wei=amount_in_wei,
                    amount_out_wei=amount_out_wei_val,
                    amount_in_human=amount_in_human_str,
                    amount_out_human=amount_out_human_str,
                    price=price_str,
                    latency_ms=rpc_latency or 10,
                    block_number=current_block,
                    rpc_success=True,
                    gate_passed=True,
                    tick=tick_val,  # v2.8.0: From multicall cache for slippage measurement
                    sqrt_price_x96=sqrt_price_val,  # v2.8.0: From multicall cache (before price)
                )
                q_dict = q.__dict__
                q_dict["price_exact"] = str(price_exact)
                q_dict["usd_notional"] = target_usd_notional if use_usd_notional else None
                
                # v2.1.0: Enhanced USD-notional tracking (Step 7)
                q_dict["notional_usd_target"] = target_usd_notional if use_usd_notional else None
                token_out_price = tokens_usd_price.get(token_out) or DEFAULT_TOKEN_USD_PRICES.get(token_out, 1.0)
                notional_usd_actual = round(amount_out_human_val * token_out_price, 2)
                q_dict["notional_usd_actual"] = notional_usd_actual
                
                # NOTIONAL_DRIFT logging
                if use_usd_notional and target_usd_notional > 0 and notional_usd_actual > 0:
                    drift_pct = abs(notional_usd_actual - target_usd_notional) / target_usd_notional * 100
                    q_dict["notional_drift_pct"] = round(drift_pct, 2)
                    if drift_pct > 10.0:
                        logger.warning(
                            "NOTIONAL_DRIFT: %s/%s %s target=$%.0f actual=$%.2f drift=%.1f%%",
                            token_in, token_out, dex, target_usd_notional, notional_usd_actual, drift_pct
                        )
                
                q_dict["quote_source"] = quote_source
                q_dict["gas_estimate"] = gas_estimate
                q_dict["ticks_crossed"] = ticks_crossed
                q_dict["anchor_source"] = anchor_source  # v2.2.0: track dynamic vs yaml
                # v2.1.0: Add sqrt_price_after for measured slippage calculation
                q_dict["sqrt_price_after"] = quoter_result.get("sqrt_price_after") if quoter_result else None
                # v2.2.0 Fix Step 5: quoter_v2 quotes are executable, not diagnostic
                q_dict["is_diagnostic_only"] = False
                quotes_sample.append(q_dict)
                counts["quotes_fetched"] += 1
                # Record success to reset quarantine failure counter
                qm.record_success(dex, f"{token_in}/{token_out}", fee_tier)
                # v2.2.0: Record valid quote for dynamic anchor calculation
                if price_exact is not None and float(price_exact) > 0:
                    am.record_quote(f"{token_in}/{token_out}", float(price_exact), dex, fee_tier, current_block)
                logger.debug("QuoterV2 canonical: %s %s/%s fee=%d amount_out=%s", 
                            dex, token_in, token_out, fee_tier, amount_out_wei_val)
                continue  # Skip slot0 path entirely
            
            # M4.2 FIX: Algebra DEXes require quoter - slot0() ABI is incompatible
            if is_algebra and not quoter_success:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "pool_address": pool_addr,
                    "reason": "ALGEBRA_NEEDS_QUOTER",
                    "gate_passed": False,
                    "error": "Algebra/Camelot DEX requires use_quoter_v2=true (slot0 ABI incompatible)",
                    "use_quoter_v2": use_quoter_v2,
                })
                counts["algebra_needs_quoter"] = counts.get("algebra_needs_quoter", 0) + 1
                logger.warning("ALGEBRA_NEEDS_QUOTER: %s %s/%s fee=%d (enable use_quoter_v2)", 
                              dex, token_in, token_out, fee_tier)
                continue
            
            # Path B: slot0 fallback - only for uniswap_v3 when no quoter
            if is_v3_dex and not is_algebra:
                tick_val, sqrt_price_val = read_slot0_v3(pool_addr, rpc_url, current_block)
                
                if tick_val is None or sqrt_price_val is None:
                    if skip_rpc and anchor_price is not None:
                        tick_val, sqrt_price_val = synthesize_sqrt_price_from_anchor(
                            anchor_price, decimals_in, decimals_out
                        )
                    else:
                        rejected_quotes.append({
                            "pair": f"{token_in}/{token_out}",
                            "dex_id": dex,
                            "fee": fee_tier,
                            "pool_address": pool_addr,
                            "reason": "V3_SLOT0_FAILED",
                            "gate_passed": False,
                            "error": f"Failed to read slot0 from pool {pool_addr}",
                            # M4.2: Add diagnostic - was quoter attempted?
                            "quoter_attempted": use_quoter_v2 and dex_cfg is not None,
                        })
                        counts["v3_slot0_failed"] += 1
                        # v2.3.0: Track failed pool address for actionable diagnostics
                        failed_pool_addresses.append({
                            "pool_address": pool_addr,
                            "dex_id": dex,
                            "pair": f"{token_in}/{token_out}",
                            "fee": fee_tier,
                            "reason": "V3_SLOT0_FAILED",
                        })
                        logger.warning("V3_SLOT0_FAILED: %s %s/%s fee=%d pool=%s (quoter_attempted=%s)", 
                                      dex, token_in, token_out, fee_tier, pool_addr, use_quoter_v2)
                        # Record failure for auto-quarantine
                        qm.record_failure(dex, f"{token_in}/{token_out}", fee_tier, "QUOTE_REVERT",
                                        details={"pool_address": pool_addr, "error": "slot0_failed"})
                        continue
            
            # Calculate price from sqrtPriceX96
            if sqrt_price_val is not None and sqrt_price_val > 0:
                token_in_addr = token_addresses.get(token_in, "")
                token_out_addr = token_addresses.get(token_out, "")
                price_exact = calculate_price_from_sqrt(
                    sqrt_price_val, token_in_addr, token_out_addr, decimals_in, decimals_out
                )
                
                if price_exact is None:
                    rejected_quotes.append({
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "PRICE_CALC_FAILED",
                        "gate_passed": False,
                        "error": "Failed to calculate price from sqrtPriceX96",
                    })
                    counts["price_calc_failed"] += 1
                    continue
                
                # v2.1.0-fix: Use localcontext to avoid InvalidOperation trap on round()
                # Some Decimal values (extreme precision) can trigger trap
                try:
                    with localcontext() as ctx:
                        ctx.traps[InvalidOperation] = False
                        price_str = str(round(price_exact, 6))
                except Exception:
                    price_str = str(price_exact)[:20]  # Fallback to truncation
                # M4.2 FIX: amount_out must scale with amount_in_wei (USD-notional)
                # For slot0: price_exact = amount_out per 1 token_in
                # amount_out = price_exact * (amount_in_wei / 10^decimals_in)
                # amount_out_wei = amount_out * 10^decimals_out
                price_exact_dec = Decimal(str(price_exact)) if not isinstance(price_exact, Decimal) else price_exact
                amount_in_tokens = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
                amount_out_human_dec = price_exact_dec * amount_in_tokens
                amount_out_wei_val = int(price_exact_dec * Decimal(amount_in_wei) * Decimal(10 ** decimals_out) / Decimal(10 ** decimals_in))
                try:
                    amount_out_human_str = str(round(float(amount_out_human_dec), 6))
                except (OverflowError, ValueError):
                    amount_out_human_str = "0.0"
                
                # v2.0.8: Enhanced QUOTE_ZERO_OUT gate with diagnostics
                # Detect: zero output, micro-liquidity, token0/token1 mismatch
                # token_in_addr / token_out_addr already looked up above
                token_in_is_token0 = (
                    token_in_addr.lower() < token_out_addr.lower()
                    if token_in_addr and token_out_addr else None
                )
                
                # Micro-price threshold: 1e-18 is suspiciously small
                is_micro_price = price_exact is not None and price_exact < 1e-18
                
                if amount_out_wei_val <= 0 or is_micro_price:
                    # Build diagnostic payload
                    diag = {
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "QUOTE_ZERO_OUT",
                        "gate_passed": False,
                        "error": f"amount_out_wei={amount_out_wei_val} <= 0" if amount_out_wei_val <= 0 else f"micro_price={price_exact}",
                        "price_exact": str(price_exact) if price_exact else None,
                        # v2.0.8: Enhanced diagnostics
                        "diag_token_in_is_token0": token_in_is_token0,
                        "diag_sqrt_price_x96": str(sqrt_price_val) if sqrt_price_val else None,
                        "diag_tick": tick_val,
                        "diag_decimals": f"{decimals_in}/{decimals_out}",
                    }
                    
                    # Detect potential token0/token1 mismatch
                    if is_micro_price and price_exact < 1e-20:
                        diag["diag_suspect"] = "TOKEN_ORDER_MISMATCH_OR_UNINITIALIZED"
                    
                    rejected_quotes.append(diag)
                    counts["quote_zero_out"] = counts.get("quote_zero_out", 0) + 1
                    logger.warning(
                        "QUOTE_ZERO_OUT: %s %s/%s fee=%d price=%s token_in_is_token0=%s",
                        dex, token_in, token_out, fee_tier, price_exact, token_in_is_token0
                    )
                    continue
            else:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "pool_address": pool_addr,
                    "reason": "NO_ONCHAIN_PRICE",
                    "gate_passed": False,
                    "error": "No on-chain price available",
                })
                counts["no_onchain_price"] += 1
                continue
            
            # Build quote with actual fee_tier (v2.0.7: no more hardcoded fee=3000)
            # M4.2: Use USD-notional sizing for amount_in_wei
            amount_in_human_str = str(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
            
            # v2.1.0-fix: PRICE_SANITY gate for slot0 path (parity with quoter path)
            # Issue #3: slot0 quotes were bypassing PRICE_SANITY check, allowing outliers
            price_sanity_enabled = config.get("price_sanity_enabled", True)
            price_sanity_max_bps = config.get("price_sanity_max_deviation_bps", 5000)
            # Note: tokens_anchor_price uses underscore format (WBTC_WETH), not slash
            slot0_anchor_price = tokens_anchor_price.get(f"{token_in}_{token_out}")
            if not slot0_anchor_price:
                reversed_tag = f"{token_out}_{token_in}"
                slot0_anchor_price = tokens_anchor_price.get(reversed_tag)
                if slot0_anchor_price:
                    slot0_anchor_price = 1.0 / slot0_anchor_price
            if price_sanity_enabled and slot0_anchor_price and price_exact is not None:
                from core.validators import check_price_sanity
                sanity_passed, sanity_dev_bps, sanity_err, sanity_diag = check_price_sanity(
                    price=Decimal(str(price_exact)),
                    anchor_price=Decimal(str(slot0_anchor_price)),
                    pair=f"{token_in}/{token_out}",
                    dex_id=dex,
                    fee_tier=fee_tier,
                    max_deviation_bps=price_sanity_max_bps,
                    anchor_source="tokens_anchor_price",
                    pool_address=pool_addr,
                )
                if not sanity_passed:
                    try:
                        ratio = float(price_exact) / float(slot0_anchor_price) if slot0_anchor_price else 0.0
                    except (TypeError, ZeroDivisionError, OverflowError):
                        ratio = 0.0
                    
                    rejected_quotes.append({
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "PRICE_SANITY_FAILED",
                        "gate_passed": False,
                        "error": sanity_err,
                        "deviation_bps": sanity_dev_bps,
                        "anchor_price": str(slot0_anchor_price),
                        "price_exact": str(price_exact),
                        "price_ratio": round(ratio, 4) if abs(ratio) < 1e20 else None,
                        "anchor_source": "tokens_anchor_price",
                        "quote_source": "slot0",
                        "tick": tick_val,
                        "diagnostics": sanity_diag,
                    })
                    counts["quotes_rejected"] = counts.get("quotes_rejected", 0) + 1
                    counts["price_sanity_failed"] = counts.get("price_sanity_failed", 0) + 1
                    logger.info(
                        "PRICE_SANITY_FAILED (slot0): %s %s/%s fee=%d dev=%d bps anchor=%s observed=%s",
                        dex, token_in, token_out, fee_tier, sanity_dev_bps,
                        str(slot0_anchor_price)[:12], str(price_exact)[:20]
                    )
                    continue
            
            # M4.2: This path is only reached via slot0 (quoter success continues early above)
            quote_source = "slot0"
            gas_estimate = None
            ticks_crossed = None
            
            q = QuoteCompat(
                dex_id=dex,
                pool_address=pool_addr,
                token_in=token_in,
                token_out=token_out,
                fee=fee_tier,  # v2.0.7: actual fee tier from config
                amount_in_wei=amount_in_wei,  # M4.2: USD-notional sizing
                amount_out_wei=amount_out_wei_val,
                amount_in_human=amount_in_human_str,
                amount_out_human=amount_out_human_str,
                price=price_str,
                latency_ms=rpc_latency or 10,
                block_number=current_block,
                rpc_success=True,
                gate_passed=True,
                tick=tick_val,
                sqrt_price_x96=sqrt_price_val,
            )
            q_dict = q.__dict__
            if price_exact is not None:
                q_dict["price_exact"] = str(price_exact)
            
            # M4.2: Add USD-notional metadata
            q_dict["usd_notional"] = target_usd_notional if use_usd_notional else None
            
            # v2.1.0: Enhanced USD-notional tracking (Step 7)
            # notional_usd_target: what we asked for
            # notional_usd_actual: what we got (amount_out * token_out_price)
            q_dict["notional_usd_target"] = target_usd_notional if use_usd_notional else None
            
            # Calculate actual USD value of amount_out
            token_out_price = tokens_usd_price.get(token_out) or DEFAULT_TOKEN_USD_PRICES.get(token_out, 1.0)
            amount_out_val = float(amount_out_human_str) if amount_out_human_str else 0.0
            notional_usd_actual = round(amount_out_val * token_out_price, 2)
            q_dict["notional_usd_actual"] = notional_usd_actual
            
            # NOTIONAL_DRIFT: log when target vs actual differs significantly (>10%)
            if use_usd_notional and target_usd_notional > 0 and notional_usd_actual > 0:
                drift_pct = abs(notional_usd_actual - target_usd_notional) / target_usd_notional * 100
                q_dict["notional_drift_pct"] = round(drift_pct, 2)
                if drift_pct > 10.0:
                    logger.warning(
                        "NOTIONAL_DRIFT: %s/%s %s target=$%.0f actual=$%.2f drift=%.1f%%",
                        token_in, token_out, dex, target_usd_notional, notional_usd_actual, drift_pct
                    )
            
            # M4.2: Quote source and quoter diagnostics (canonical now)
            q_dict["quote_source"] = quote_source
            q_dict["gas_estimate"] = gas_estimate
            q_dict["ticks_crossed"] = ticks_crossed
            q_dict["anchor_source"] = anchor_source  # v2.2.0: track dynamic vs yaml
            
            # v2.2.0 Fix Step 5: truth_mode_m42 behavior
            # When truth_mode_m42=true, slot0-only quotes are diagnostic only
            # These should be excluded from opportunity evaluation
            truth_mode = config.get("truth_mode_m42", False)
            if truth_mode and quote_source == "slot0":
                q_dict["is_diagnostic_only"] = True
                q_dict["diagnostic_reason"] = "SLOT0_DIAGNOSTIC"
                logger.debug(
                    "SLOT0_DIAGNOSTIC: %s %s/%s (truth_mode requires quoter for executable quotes)",
                    dex, token_in, token_out
                )
            else:
                q_dict["is_diagnostic_only"] = False
            
            quotes_sample.append(q_dict)
            counts["quotes_fetched"] = counts.get("quotes_fetched", 0) + 1
            # Record success to reset quarantine failure counter
            qm.record_success(dex, f"{token_in}/{token_out}", fee_tier)
            # v2.2.0: Record valid quote for dynamic anchor calculation
            if price_exact is not None and float(price_exact) > 0:
                am.record_quote(f"{token_in}/{token_out}", float(price_exact), dex, fee_tier, current_block)
    
    # v2.3.0: Add failed pool addresses to counts for artifact generation
    counts["failed_pool_addresses"] = failed_pool_addresses
    
    # v2.3.1: Add pool_missing_keys for observability (what pools were skipped)
    # Limit to top 20 to avoid huge artifacts
    counts["pool_missing_keys"] = pool_missing_keys[:20]
    counts["pool_missing_keys_total"] = len(pool_missing_keys)
    
    return quotes_sample, rejected_quotes, counts
