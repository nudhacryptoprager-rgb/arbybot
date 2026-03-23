# PATH: strategy/quote_adapters.py
"""
Adapter-specific quote readers extracted from strategy.quotes.

This module owns:
- Algebra (Camelot/Lynex) quoter reader
- ve33 (Aerodrome/Velodrome) getAmountOut reader
- sqrtPriceX96 → price math
- Anchor-based sqrtPrice synthesis (test mode)

All functions are pure I/O helpers with no policy/gating logic.
High-level quote orchestration remains in strategy.quotes.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from strategy.quote_rpc import _get_shared_w3

logger = logging.getLogger("strategy.quotes")


# =============================================================================
# ALGEBRA QUOTER (Camelot / Lynex)
# =============================================================================

def read_algebra_quoter(
    quoter_address: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    rpc_url: Optional[str],
    block_num: int,
) -> Optional[Dict[str, Any]]:
    """
    Get executable quote from Algebra (Camelot/Lynex) quoter contract.
    
    Algebra quoter uses different signature than UniswapV3 QuoterV2:
    - No fee parameter (Algebra has dynamic fees)
    - Different return values
    
    Supports two Algebra quoter styles:
    1. quoteExactInputSingle(address,address,uint256,uint160) - Camelot style
    2. quoteExactInput(bytes path, uint256 amountIn) - Lynex style
    
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
    
    w3 = _get_shared_w3(rpc_url, timeout=5)  # 5s timeout matches QuoterV2
    if w3 is None:
        return None
    
    # Try Style 1: quoteExactInputSingle(address,address,uint256,uint160) - Camelot
    style1_error = None
    try:
        SELECTOR_SINGLE = "0x2d58eb1d"
        
        token_in_padded = token_in[2:].lower().zfill(64)
        token_out_padded = token_out[2:].lower().zfill(64)
        amount_in_hex = hex(amount_in)[2:].zfill(64)
        sqrt_price_limit = hex(0)[2:].zfill(64)  # 0 = no limit
        
        call_data = f"{SELECTOR_SINGLE}{token_in_padded}{token_out_padded}{amount_in_hex}{sqrt_price_limit}"
        
        result_hex = w3.eth.call(
            {"to": Web3.to_checksum_address(quoter_address), "data": call_data},
            block_identifier=block_num,
        ).hex()
        
        if result_hex and result_hex != "0x" and len(result_hex) >= 66:
            data = result_hex[2:] if result_hex.startswith("0x") else result_hex
            amount_out = int(data[0:64], 16)
            if amount_out > 0:
                logger.debug(
                    "Algebra quoter (single) success: %s -> %s, amountOut=%d",
                    token_in[:10], token_out[:10], amount_out
                )
                return {
                    "amount_out": amount_out,
                    "sqrt_price_after": None,
                    "ticks_crossed": None,
                    "gas_estimate": 200_000,
                }
            else:
                style1_error = "amountOut=0 (zero liquidity)"
        else:
            style1_error = f"empty_response (len={len(result_hex) if result_hex else 0})"
    except Exception as e:
        style1_error = str(e)[:120]
        logger.debug("Algebra quoter (single) failed: %s", e)
    
    # Try Style 2: quoteExactInput(bytes path, uint256 amountIn) - Lynex
    style2_error = None
    try:
        from eth_abi import encode
        
        # Algebra path: 20 bytes tokenIn + 20 bytes tokenOut (no fee)
        path = bytes.fromhex(token_in[2:]) + bytes.fromhex(token_out[2:])
        params = encode(['bytes', 'uint256'], [path, amount_in])
        call_data = "0xcdca1753" + params.hex()
        
        result_hex = w3.eth.call(
            {"to": Web3.to_checksum_address(quoter_address), "data": call_data},
            block_identifier=block_num,
        ).hex()
        
        if result_hex and result_hex != "0x" and len(result_hex) >= 66:
            data = result_hex[2:] if result_hex.startswith("0x") else result_hex
            amount_out = int(data[0:64], 16)
            if amount_out > 0:
                logger.debug(
                    "Algebra quoter (path) success: %s -> %s, amountOut=%d",
                    token_in[:10], token_out[:10], amount_out
                )
                return {
                    "amount_out": amount_out,
                    "sqrt_price_after": None,
                    "ticks_crossed": None,
                    "gas_estimate": 200_000,
                }
            else:
                style2_error = "amountOut=0 (zero liquidity)"
        else:
            style2_error = f"empty_response (len={len(result_hex) if result_hex else 0})"
    except Exception as e:
        style2_error = str(e)[:120]
        logger.debug("Algebra quoter (path) failed: %s", e)
    
    # R28.27: Enhanced diagnostic — capture WHY both styles failed
    logger.info(
        "ALGEBRA_QUOTER_DIAG: %s/%s quoter=%s style1=%s style2=%s",
        token_in[:10], token_out[:10], quoter_address[:16],
        style1_error or "not_attempted", style2_error or "not_attempted",
    )
    return None


# =============================================================================
# VE33 (Aerodrome / Velodrome / Solidly)
# =============================================================================

def read_ve33_amount_out(
    pool_address: str,
    token_in: str,
    amount_in: int,
    rpc_url: Optional[str],
    block_num: int,
) -> Optional[int]:
    """
    Get executable quote from ve33 / Solidly-style pool via getAmountOut().
    
    Aerodrome/Velodrome-style pools expose:
      getAmountOut(uint256 amountIn, address tokenIn) -> uint256 amountOut
    """
    if not pool_address or not token_in or not rpc_url:
        return None
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.debug("ve33 quote skipped: web3 not installed")
        return None
    
    try:
        w3 = _get_shared_w3(rpc_url)
        if w3 is None:
            return None
        pool = w3.eth.contract(
            address=Web3.to_checksum_address(pool_address),
            abi=[
                {
                    "inputs": [
                        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                        {"internalType": "address", "name": "tokenIn", "type": "address"},
                    ],
                    "name": "getAmountOut",
                    "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                }
            ],
        )
        
        amount_out = pool.functions.getAmountOut(
            amount_in,
            Web3.to_checksum_address(token_in),
        ).call(block_identifier=block_num)
        
        if amount_out is None:
            return None
        amount_out_int = int(amount_out)
        return amount_out_int if amount_out_int > 0 else None
        
    except Exception as e:
        # R28.27: Enhanced diagnostic for ve33 failures (same pattern as ALGEBRA_QUOTER_DIAG)
        logger.info(
            "VE33_QUOTE_DIAG: pool=%s token_in=%s amount_in=%d error=%s",
            pool_address[:16], token_in[:10], amount_in, str(e)[:120],
        )
        return None


# =============================================================================
# SYNCSWAP (zkSync / Scroll / Linea)
# =============================================================================

def read_syncswap_amount_out(
    pool_address: str,
    token_in: str,
    amount_in: int,
    rpc_url: Optional[str],
    block_num: int,
) -> Optional[int]:
    """
    Get executable quote from SyncSwap pool via getAmountOut().

    SyncSwap Classic/Stable pools expose:
      getAmountOut(address tokenIn, uint256 amountIn, address sender) -> uint256 amountOut
    """
    if not pool_address or not token_in or not rpc_url:
        return None
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None

    try:
        from web3 import Web3
    except ImportError:
        logger.debug("syncswap quote skipped: web3 not installed")
        return None

    try:
        w3 = _get_shared_w3(rpc_url)
        if w3 is None:
            return None
        pool = w3.eth.contract(
            address=Web3.to_checksum_address(pool_address),
            abi=[
                {
                    "inputs": [
                        {"internalType": "address", "name": "tokenIn", "type": "address"},
                        {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                        {"internalType": "address", "name": "sender", "type": "address"},
                    ],
                    "name": "getAmountOut",
                    "outputs": [{"internalType": "uint256", "name": "amountOut", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function",
                }
            ],
        )

        amount_out = pool.functions.getAmountOut(
            Web3.to_checksum_address(token_in),
            amount_in,
            Web3.to_checksum_address("0x0000000000000000000000000000000000000000"),
        ).call(block_identifier=block_num)

        if amount_out is None:
            return None
        amount_out_int = int(amount_out)
        return amount_out_int if amount_out_int > 0 else None

    except Exception as e:
        logger.info(
            "SYNCSWAP_QUOTE_DIAG: pool=%s token_in=%s amount_in=%d error=%s",
            pool_address[:16], token_in[:10], amount_in, str(e)[:120],
        )
        return None


# =============================================================================
# IZISWAP (iZUMi Finance — Discretized Concentrated Liquidity)
# =============================================================================

def read_iziswap_amount_out(
    quoter_address: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int,
    rpc_url: Optional[str],
    block_num: int,
) -> Optional[Dict[str, Any]]:
    """
    Get executable quote from iZiSwap via Quoter.swapAmount().

    iZiSwap Quoter exposes:
      swapAmount(uint128 amount, address tokenX, address tokenY, uint24 fee, bool sellXEarnY)
      -> (uint256 acquire, int24 pointAfterX)

    We pass sellXEarnY = (tokenIn < tokenOut by address) since iZiSwap
    defines tokenX < tokenY and sellXEarnY = selling tokenX.
    """
    if not quoter_address or not token_in or not token_out or not rpc_url:
        return None
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None

    try:
        from web3 import Web3
    except ImportError:
        logger.debug("iziswap quote skipped: web3 not installed")
        return None

    try:
        w3 = _get_shared_w3(rpc_url)
        if w3 is None:
            return None

        quoter = w3.eth.contract(
            address=Web3.to_checksum_address(quoter_address),
            abi=[
                {
                    "inputs": [
                        {"internalType": "uint128", "name": "amount", "type": "uint128"},
                        {"internalType": "address", "name": "tokenX", "type": "address"},
                        {"internalType": "address", "name": "tokenY", "type": "address"},
                        {"internalType": "uint24", "name": "fee", "type": "uint24"},
                        {"internalType": "bool", "name": "sellXEarnY", "type": "bool"},
                    ],
                    "name": "swapAmount",
                    "outputs": [
                        {"internalType": "uint256", "name": "acquire", "type": "uint256"},
                        {"internalType": "int24", "name": "pointAfter", "type": "int24"},
                    ],
                    "stateMutability": "nonpayable",
                    "type": "function",
                }
            ],
        )

        # iZiSwap convention: tokenX < tokenY (sorted by address)
        token_in_lower = token_in.lower()
        token_out_lower = token_out.lower()
        sell_x_earn_y = token_in_lower < token_out_lower

        # Clamp amount to uint128 max
        max_uint128 = (1 << 128) - 1
        clamped_amount = min(amount_in, max_uint128)

        acquire, point_after = quoter.functions.swapAmount(
            clamped_amount,
            Web3.to_checksum_address(min(token_in, token_out, key=str.lower)),
            Web3.to_checksum_address(max(token_in, token_out, key=str.lower)),
            fee,
            sell_x_earn_y,
        ).call(block_identifier=block_num)

        if acquire is None or int(acquire) <= 0:
            return None

        return {
            "amount_out": int(acquire),
            "point_after": int(point_after),
        }

    except Exception as e:
        logger.info(
            "IZISWAP_QUOTE_DIAG: quoter=%s token_in=%s token_out=%s fee=%s amount_in=%d error=%s",
            quoter_address[:16], token_in[:10], token_out[:10], fee, amount_in, str(e)[:120],
        )
        return None


# =============================================================================
# PRICE MATH (sqrtPriceX96 → price)
# =============================================================================

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
