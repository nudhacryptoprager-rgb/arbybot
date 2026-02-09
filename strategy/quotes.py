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
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.pairs import load_pairs, get_pool_address, PairConfig
from strategy.compat import QuoteCompat

logger = logging.getLogger("strategy.quotes")


def read_slot0_v3(pool_address: str, rpc_url: Optional[str], block_num: int) -> Tuple[Optional[int], Optional[int]]:
    """
    Read slot0() from a Uniswap V3 pool contract.
    
    Args:
        pool_address: Pool contract address
        rpc_url: RPC URL to use
        block_num: Block number to query at
        
    Returns:
        (tick, sqrtPriceX96) or (None, None) on failure
    """
    if not pool_address or not rpc_url:
        return None, None
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
        
        if token_in_addr and token_out_addr:
            token_in_is_token0 = token_in_addr.lower() < token_out_addr.lower()
            
            if token_in_is_token0:
                decimals_diff = Decimal(10 ** (decimals_in - decimals_out))
                return raw_price * decimals_diff
            else:
                decimals_diff = Decimal(10 ** (decimals_in - decimals_out))
                return (Decimal(1) / raw_price) * decimals_diff
        else:
            decimals_diff = Decimal(10 ** (decimals_in - decimals_out))
            return raw_price * decimals_diff
    except Exception as e:
        logger.warning("Price calculation failed: %s", e)
        return None


def collect_quotes(
    config: Dict[str, Any],
    current_block: int,
    rpc_latency: int = 0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Collect quotes from DEX pools.
    
    Args:
        config: Configuration dict
        current_block: Current block number
        rpc_latency: RPC latency in ms
        
    Returns:
        (quotes_sample, rejected_quotes, counts)
    """
    quotes_sample: List[Dict[str, Any]] = []
    rejected_quotes: List[Dict[str, Any]] = []
    
    counts = {
        "pool_missing": 0,
        "v3_slot0_failed": 0,
        "price_calc_failed": 0,
        "no_onchain_price": 0,
    }
    
    dexes_list = config.get("dexes") or []
    pools_cfg = config.get("pools", {}) or {}
    token_addresses = config.get("tokens", {}) or {}
    
    # Load pairs from config
    chain_key = config.get("chain", "arbitrum_one")
    pairs_list = load_pairs(chain_key, config, use_intent=False)
    
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
    
    for pair_cfg in pairs_list:
        token_pair_tag = pair_cfg.pair_tag
        token_in = pair_cfg.token_in
        token_out = pair_cfg.token_out
        decimals_in = pair_cfg.token_in_decimals
        decimals_out = pair_cfg.token_out_decimals
        
        # Get anchor price for this pair
        anchor_price = tokens_anchor_price.get(token_pair_tag)
        if not anchor_price:
            reversed_tag = f"{token_out}_{token_in}"
            anchor_price = tokens_anchor_price.get(reversed_tag)
            if anchor_price:
                anchor_price = 1.0 / anchor_price
        
        for dex in dexes_list:
            pool_addr = get_pool_address(config, dex, token_pair_tag)
            if not pool_addr:
                for k, v in pools_cfg.items():
                    if dex in k and token_pair_tag in k:
                        if v and v != "0x0000000000000000000000000000000000000000":
                            pool_addr = v
                            break
            
            if not pool_addr:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "reason": "POOL_MISSING",
                    "gate_passed": False,
                    "error": f"No pool address configured for {dex}_{token_pair_tag}",
                })
                counts["pool_missing"] += 1
                logger.warning("POOL_MISSING: %s %s/%s", dex, token_in, token_out)
                continue
            
            # Read slot0 for v3 pools
            tick_val, sqrt_price_val = None, None
            if "v3" in dex.lower():
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
                            "pool_address": pool_addr,
                            "reason": "V3_SLOT0_FAILED",
                            "gate_passed": False,
                            "error": f"Failed to read slot0 from pool {pool_addr}",
                        })
                        counts["v3_slot0_failed"] += 1
                        logger.warning("V3_SLOT0_FAILED: %s %s/%s", dex, token_in, token_out)
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
                        "pool_address": pool_addr,
                        "reason": "PRICE_CALC_FAILED",
                        "gate_passed": False,
                        "error": "Failed to calculate price from sqrtPriceX96",
                    })
                    counts["price_calc_failed"] += 1
                    continue
                
                price_str = str(round(price_exact, 6))
                amount_out_human_val = price_exact
                amount_out_wei_val = int(amount_out_human_val * (10 ** decimals_out))
                amount_out_human_str = str(round(amount_out_human_val, 6))
            else:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "pool_address": pool_addr,
                    "reason": "NO_ONCHAIN_PRICE",
                    "gate_passed": False,
                    "error": "No on-chain price available",
                })
                counts["no_onchain_price"] += 1
                continue
            
            # Build quote
            q = QuoteCompat(
                dex_id=dex,
                pool_address=pool_addr,
                token_in=token_in,
                token_out=token_out,
                fee=3000,
                amount_in_wei=10 ** decimals_in,
                amount_out_wei=amount_out_wei_val,
                amount_in_human="1",
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
            quotes_sample.append(q_dict)
    
    return quotes_sample, rejected_quotes, counts
