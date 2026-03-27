"""
Low-level quote RPC helpers extracted from strategy.quotes.

This module owns:
- shared Web3 / executor caches
- multicall prefetch caches
- raw pool / quoter readers

High-level quote orchestration remains in strategy.quotes.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("strategy.quotes")


# =============================================================================
# SHARED WEB3 PROVIDER CACHE
# =============================================================================

_shared_w3_cache: Dict[str, Any] = {}


def _get_shared_w3(rpc_url: str, timeout: int = 10) -> Any:
    """Get or create a shared Web3 instance for an RPC URL."""
    if rpc_url in _shared_w3_cache:
        return _shared_w3_cache[rpc_url]
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout}))
        _shared_w3_cache[rpc_url] = w3
        return w3
    except Exception:
        return None


def clear_shared_w3_cache() -> None:
    """Clear the shared Web3 provider cache (for testing)."""
    _shared_w3_cache.clear()


_QUOTE_CONCURRENCY = 8


# =============================================================================
# R39o: PER-CYCLE 429 QUARANTINE
# =============================================================================
# After a (rpc_url, quoter_address) pair receives a 429, quarantine it for the
# rest of the cycle so subsequent calls go straight to fallback RPCs.

_cycle_quarantine: set = set()  # Set[Tuple[str, str]]

# R39p: Cycle-level primary rotation counter.
# Each reset_cycle_quarantine() bumps this so the next cycle uses a
# different endpoint as primary, spreading rate-limit surface evenly.
_cycle_rotation_counter: int = 0


def reset_cycle_quarantine() -> int:
    """Reset the per-cycle 429 quarantine. Call at the start of each scan cycle.
    Returns the number of entries cleared."""
    global _cycle_rotation_counter
    n = len(_cycle_quarantine)
    _cycle_quarantine.clear()
    _cycle_rotation_counter += 1
    return n


def get_cycle_rotation_counter() -> int:
    """Return current rotation counter for RPC primary rotation."""
    return _cycle_rotation_counter


# =============================================================================
# QUOTE EXECUTOR + MULTICALL CACHES
# =============================================================================

_shared_quote_executor: Any = None
_SHARED_QUOTE_CONCURRENCY = 16

_multicall_slot0_cache: Dict[str, Optional[Tuple[int, int]]] = {}
_multicall_liquidity_cache: Dict[str, Optional[int]] = {}
_multicall_token_info_cache: Dict[str, Optional[Tuple[str, str, int]]] = {}
_multicall_decimals_cache: Dict[str, Optional[int]] = {}


def _get_shared_quote_executor() -> Any:
    """Get or create the shared quote ThreadPoolExecutor."""
    global _shared_quote_executor
    if _shared_quote_executor is None:
        from concurrent.futures import ThreadPoolExecutor as _TPE

        _shared_quote_executor = _TPE(max_workers=_SHARED_QUOTE_CONCURRENCY)
    return _shared_quote_executor


def prefetch_slot0_multicall(
    pool_addresses: List[str], rpc_url: str, block_num: int
) -> Dict[str, Optional[Tuple[int, int]]]:
    """
    Prefetch slot0, liquidity, and token_info data for multiple pools using multicall.
    """
    global _multicall_slot0_cache
    global _multicall_liquidity_cache
    global _multicall_token_info_cache

    if not pool_addresses or not rpc_url:
        return {}

    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return {addr: None for addr in pool_addresses}

    try:
        from core.multicall import get_multicall_batcher

        batcher = get_multicall_batcher(rpc_url, block_num)
        results = batcher.batch_slot0(pool_addresses)
        liquidity_results = batcher.batch_liquidity(pool_addresses)
        token_info_results = batcher.batch_token_info(pool_addresses)

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

        output: Dict[str, Optional[Tuple[int, int]]] = {}
        for addr, data in results.items():
            if data is not None:
                sqrt_price, tick, _ = data
                output[addr.lower()] = (tick, sqrt_price)
            else:
                output[addr.lower()] = None

        _multicall_slot0_cache.update(output)
        _multicall_liquidity_cache.update(
            {k.lower(): v for k, v in liquidity_results.items()}
        )
        _multicall_token_info_cache.update(
            {k.lower(): v for k, v in token_info_results.items()}
        )
        _multicall_decimals_cache.update(
            {k.lower(): v for k, v in decimals_results.items()}
        )

        success_count = sum(1 for v in output.values() if v is not None)
        liq_count = sum(1 for v in liquidity_results.values() if v is not None)
        token_count = sum(1 for v in token_info_results.values() if v is not None)
        decimals_count = sum(1 for v in decimals_results.values() if v is not None)
        logger.info(
            "Multicall prefetch: %d pools, %d tokens, success: slot0=%d, liquidity=%d, token_info=%d, decimals=%d",
            len(pool_addresses),
            len(unique_tokens),
            success_count,
            liq_count,
            token_count,
            decimals_count,
        )
        return output
    except Exception as e:
        logger.debug("Multicall prefetch failed: %s", e)
        return {addr: None for addr in pool_addresses}


def get_cached_liquidity(pool_address: str) -> Optional[int]:
    """Get liquidity from multicall cache if available."""
    return _multicall_liquidity_cache.get(pool_address.lower())


def get_cached_slot0(pool_address: str) -> Optional[Tuple[int, int]]:
    """Get slot0 (tick, sqrt_price_x96) from multicall cache if available."""
    return _multicall_slot0_cache.get(pool_address.lower())


def get_cached_token_info(pool_address: str) -> Optional[Tuple[str, str, int]]:
    """Get token_info (token0, token1, fee) from multicall cache if available."""
    return _multicall_token_info_cache.get(pool_address.lower())


def get_cached_decimals(token_address: str) -> Optional[int]:
    """Get decimals from multicall cache if available."""
    return _multicall_decimals_cache.get(token_address.lower())


def clear_multicall_cache() -> None:
    """Clear the multicall prefetch cache (for testing)."""
    _multicall_slot0_cache.clear()
    _multicall_liquidity_cache.clear()
    _multicall_token_info_cache.clear()
    _multicall_decimals_cache.clear()


def read_slot0_v3(
    pool_address: str, rpc_url: Optional[str], block_num: int
) -> Tuple[Optional[int], Optional[int]]:
    """Read slot0() from a Uniswap V3 pool contract."""
    if not pool_address or not rpc_url:
        return None, None

    cache_key = pool_address.lower()
    if cache_key in _multicall_slot0_cache:
        cached = _multicall_slot0_cache[cache_key]
        if cached is not None:
            logger.debug("slot0() from multicall cache for %s", pool_address)
            return cached

    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None, None

    try:
        from web3 import Web3
    except ImportError:
        logger.debug("slot0() skipped: web3 not installed")
        return None, None

    try:
        abi_path = (
            Path(__file__).parent.parent / "dex" / "abi" / "uniswap_v3_pool.json"
        )
        if not abi_path.exists():
            logger.debug("slot0() skipped: ABI not found at %s", abi_path)
            return None, None

        abi = json.loads(abi_path.read_text(encoding="utf8"))
        w3 = _get_shared_w3(rpc_url, timeout=5)
        if w3 is None:
            return None, None
        pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=abi)
        slot0 = pool.functions.slot0().call(block_identifier=block_num)

        sqrt_price_x96 = int(slot0[0])
        tick = int(slot0[1])
        logger.debug(
            "slot0() success for %s: tick=%s, sqrtPriceX96=%s",
            pool_address,
            tick,
            sqrt_price_x96,
        )
        return tick, sqrt_price_x96
    except Exception as e:
        logger.debug("slot0() read failed for %s: %s", pool_address, e)
        return None, None


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect HTTP 429 / rate-limit errors from RPC responses."""
    msg = str(exc).lower()
    return "429" in msg or "too many requests" in msg or "rate limit" in msg


# Sentinel returned when quoter_v2 fails due to RPC rate limiting.
# Callers should NOT count this as a genuine quoter failure.
QUOTER_RATE_LIMITED: Dict[str, Any] = {"_rate_limited": True}


def read_quoter_v2(
    quoter_address: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int,
    rpc_url: Optional[str],
    block_num: Union[int, str],  # int block number or "latest"/"pending"
    fallback_rpc_urls: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Get executable quote from QuoterV2 contract.

    R39n: On 429 rate-limit, tries fallback_rpc_urls before returning
    QUOTER_RATE_LIMITED sentinel. This prevents slot0 contamination
    on alpha pairs when the primary RPC is rate-limited.
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

    # Build ordered list of RPCs to try: primary first, then fallbacks
    # R39o: skip URLs already quarantined this cycle for this quoter
    urls_to_try = []
    for _u in [rpc_url] + (fallback_rpc_urls or []):
        if _u and _u not in urls_to_try:
            if (_u, quoter_address) in _cycle_quarantine:
                logger.debug("QuoterV2 skip quarantined RPC %s for quoter %s", _u[:40], quoter_address[:10])
                continue
            urls_to_try.append(_u)

    # R39o: All RPCs quarantined for this quoter → immediate rate-limited sentinel
    if not urls_to_try:
        logger.debug("QuoterV2 all RPCs quarantined for quoter %s", quoter_address[:10])
        return QUOTER_RATE_LIMITED

    from dex.adapters.uniswap_v3 import (
        decode_quote_response,
        encode_quote_exact_input_single,
    )

    call_data = encode_quote_exact_input_single(
        token_in=token_in,
        token_out=token_out,
        amount_in=amount_in,
        fee=fee,
    )

    last_error = None
    for url in urls_to_try:
        try:
            w3 = _get_shared_w3(url)
            if w3 is None:
                continue
            result_hex = w3.eth.call(
                {"to": Web3.to_checksum_address(quoter_address), "data": call_data},
                block_identifier=block_num,
            ).hex()

            amount_out, sqrt_price_after, ticks_crossed, gas_estimate = (
                decode_quote_response(result_hex)
            )

            logger.debug(
                "QuoterV2 success: %s -> %s, amountOut=%d, ticks=%d, gas=%d",
                token_in[:10],
                token_out[:10],
                amount_out,
                ticks_crossed,
                gas_estimate,
            )

            return {
                "amount_out": amount_out,
                "sqrt_price_after": sqrt_price_after,
                "ticks_crossed": ticks_crossed,
                "gas_estimate": gas_estimate,
            }
        except Exception as e:
            if _is_rate_limit_error(e):
                logger.info("QuoterV2 rate-limited (429) on %s: %s", url[:40], e)
                _cycle_quarantine.add((url, quoter_address))  # R39o: quarantine this pair
                last_error = e
                continue  # R39n: try next RPC
            logger.debug("QuoterV2 failed on %s: %s", url[:40], e)
            return None

    # All RPCs rate-limited
    if last_error is not None:
        logger.info("QuoterV2 rate-limited on all %d RPCs", len(urls_to_try))
        return QUOTER_RATE_LIMITED
    return None
