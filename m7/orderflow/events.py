"""
M7 orderflow event building, fetching, normalization, and loading.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    EVENT_TYPE_SWAP,
    M7A4_CHAIN,
    MIN_EVENT_SIZE_USD,
    SWAP_EVENT_TOPIC,
    DEFAULT_LIVE_BLOCKS,
)
from m7.orderflow.contracts import OrderflowEvent

logger = logging.getLogger("m7.orderflow.events")

def build_fixture_events() -> List[OrderflowEvent]:
    """Generate canonical fixture events for offline replay scoring.

    These represent realistic orderflow patterns on arbitrum_one
    that would be visible in MEV-Share or block event streams.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        # 1. Medium USDC→WETH swap on Uniswap V3 (common retail flow)
        OrderflowEvent(
            event_id="fixture_swap_usdc_weth_medium",
            event_type=EVENT_TYPE_SWAP,
            chain=M7A4_CHAIN,
            block_number=446900000,
            tx_hash="0x" + "a1" * 32,
            token_in="USDC",
            token_out="WETH",
            amount_in_wei=5000 * 10**6,  # 5000 USDC
            amount_out_wei=1_400_000_000_000_000,  # ~1.4 WETH
            dex="uniswap_v3",
            pool_address="0x" + "b2" * 20,
            fee_tier=500,
            estimated_size_usd=5000.0,
            estimated_impact_bps=3.0,
            timestamp=ts,
        ),
        # 2. Large WETH→USDC swap on Camelot V3 (institutional exit)
        OrderflowEvent(
            event_id="fixture_swap_weth_usdc_large",
            event_type=EVENT_TYPE_SWAP,
            chain=M7A4_CHAIN,
            block_number=446900001,
            tx_hash="0x" + "c3" * 32,
            token_in="WETH",
            token_out="USDC",
            amount_in_wei=10 * 10**18,  # 10 WETH
            amount_out_wei=35000 * 10**6,  # ~35000 USDC
            dex="camelot_v3",
            pool_address="0x" + "d4" * 20,
            fee_tier=3000,
            estimated_size_usd=35000.0,
            estimated_impact_bps=15.0,
            timestamp=ts,
        ),
        # 3. Small ARB→USDC swap on PancakeSwap V3 (retail churn)
        OrderflowEvent(
            event_id="fixture_swap_arb_usdc_small",
            event_type=EVENT_TYPE_SWAP,
            chain=M7A4_CHAIN,
            block_number=446900002,
            tx_hash="0x" + "e5" * 32,
            token_in="ARB",
            token_out="USDC",
            amount_in_wei=500 * 10**18,  # 500 ARB
            amount_out_wei=250 * 10**6,  # ~250 USDC
            dex="pancakeswap_v3",
            pool_address="0x" + "f6" * 20,
            fee_tier=500,
            estimated_size_usd=250.0,
            estimated_impact_bps=2.0,
            timestamp=ts,
        ),
        # 4. Very large WBTC→USDC swap (whale movement)
        OrderflowEvent(
            event_id="fixture_swap_wbtc_usdc_whale",
            event_type=EVENT_TYPE_SWAP,
            chain=M7A4_CHAIN,
            block_number=446900003,
            tx_hash="0x" + "a7" * 32,
            token_in="WBTC",
            token_out="USDC",
            amount_in_wei=2 * 10**8,  # 2 WBTC
            amount_out_wei=190000 * 10**6,  # ~190000 USDC
            dex="uniswap_v3",
            pool_address="0x" + "b8" * 20,
            fee_tier=3000,
            estimated_size_usd=190000.0,
            estimated_impact_bps=25.0,
            timestamp=ts,
        ),
        # 5. USDT→USDC stablecoin rebalance (low impact, high volume)
        OrderflowEvent(
            event_id="fixture_swap_usdt_usdc_stable",
            event_type=EVENT_TYPE_SWAP,
            chain=M7A4_CHAIN,
            block_number=446900004,
            tx_hash="0x" + "c9" * 32,
            token_in="USDT",
            token_out="USDC",
            amount_in_wei=50000 * 10**6,  # 50000 USDT
            amount_out_wei=49990 * 10**6,  # ~49990 USDC
            dex="uniswap_v3",
            pool_address="0x" + "da" * 20,
            fee_tier=100,
            estimated_size_usd=50000.0,
            estimated_impact_bps=0.5,
            timestamp=ts,
        ),
    ]



def fetch_recent_swap_events(
    rpc_url: str,
    blocks_back: int = DEFAULT_LIVE_BLOCKS,
    chunk_size: int = 10,
) -> list:
    """Fetch raw Swap event logs from recent blocks on-chain.

    Returns raw Web3 LogEntry objects. Caller normalizes them.
    Chunks requests into chunk_size-block windows to respect RPC tier limits
    (e.g. Alchemy free tier allows max 10 blocks per eth_getLogs).
    """
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    current_block = w3.eth.block_number
    from_block = max(current_block - blocks_back, 0)

    logger.info(
        "Fetching Swap events from block %d to %d (%d blocks, chunk_size=%d)",
        from_block,
        current_block,
        blocks_back,
        chunk_size,
        extra={"context": {"from_block": from_block, "to_block": current_block, "chunk_size": chunk_size}},
    )

    all_logs = []
    chunk_start = from_block
    while chunk_start <= current_block:
        chunk_end = min(chunk_start + chunk_size - 1, current_block)
        logs = w3.eth.get_logs({
            "fromBlock": chunk_start,
            "toBlock": chunk_end,
            "topics": [SWAP_EVENT_TOPIC],
        })
        all_logs.extend(logs)
        chunk_start = chunk_end + 1

    logger.info(
        "Fetched %d raw Swap logs",
        len(all_logs),
        extra={"context": {"count": len(all_logs), "blocks": blocks_back}},
    )
    return list(all_logs), current_block



def normalize_swap_log(
    log: Any,
    addr_to_symbol: Dict[str, str],
    token_addresses: Dict[str, str],
    dex_configs: Dict[str, Any],
    event_index: int = 0,
) -> Optional[OrderflowEvent]:
    """Normalize a raw V3 Swap log into an OrderflowEvent.

    Decodes the Swap(address,address,int256,int256,uint160,uint128,int24) event.
    Attempts to identify the pool's token pair and originating DEX.

    Returns None if the log cannot be fully normalized (unknown tokens etc).
    """
    try:
        pool_address = log["address"].lower() if hasattr(log["address"], "lower") else log["address"]
        tx_hash = log["transactionHash"].hex() if hasattr(log["transactionHash"], "hex") else str(log["transactionHash"])
        block_number = log["blockNumber"]

        # Decode Swap event data: int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick
        data = log["data"]
        if hasattr(data, "hex"):
            data_hex = data.hex()
        else:
            data_hex = data if isinstance(data, str) else str(data)
        if data_hex.startswith("0x"):
            data_hex = data_hex[2:]

        # Each field is 32 bytes (64 hex chars)
        if len(data_hex) < 320:  # Need at least 5 x 64 = 320 hex chars
            return None

        def _decode_int256(hex_str: str) -> int:
            val = int(hex_str, 16)
            if val >= (1 << 255):
                val -= (1 << 256)
            return val

        amount0 = _decode_int256(data_hex[0:64])
        amount1 = _decode_int256(data_hex[64:128])
        # sqrtPriceX96, liquidity, tick available but not needed for event normalization

        # Determine swap direction from amounts:
        # Positive amount = token flowing INTO the pool (user pays)
        # Negative amount = token flowing OUT of the pool (user receives)
        # We need to know token0 and token1 for this pool — we don't have that from logs alone,
        # so we'll try to match against known token pairs.

        # For now, use absolute values and mark direction
        abs_amount0 = abs(amount0)
        abs_amount1 = abs(amount1)

        # We can't definitively identify token0/token1 from the log without
        # querying the pool contract. Instead, use a heuristic:
        # The token with the positive amount is token_in (user sent it),
        # the token with the negative amount is token_out (user received it).
        if amount0 > 0 and amount1 < 0:
            amount_in_raw = abs_amount0
            amount_out_raw = abs_amount1
            direction = "token0_in"
        elif amount1 > 0 and amount0 < 0:
            amount_in_raw = abs_amount1
            amount_out_raw = abs_amount0
            direction = "token1_in"
        else:
            # Both same sign — unusual, skip
            return None

        # Estimate USD size (rough: assume ~1 USD per 1e6 for stables, ~3500 per 1e18 for ETH)
        # This is a rough filter — exact pricing not needed for event classification
        estimated_size_usd = max(amount_in_raw / 1e6, amount_in_raw / 1e18 * 3500)

        # Skip tiny events
        if estimated_size_usd < MIN_EVENT_SIZE_USD * 0.1:
            return None

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Try to identify source DEX from pool address (best-effort)
        # We don't have a pool→factory mapping without on-chain calls,
        # so mark as "unknown_v3" — the DEX identity doesn't affect quoting
        source_dex = "unknown_v3"

        event_id = f"live_swap_{block_number}_{event_index}"

        return OrderflowEvent(
            event_id=event_id,
            event_type=EVENT_TYPE_SWAP,
            chain=M7A4_CHAIN,
            block_number=block_number,
            tx_hash=tx_hash,
            token_in=direction,  # Placeholder — resolved later or left as direction tag
            token_out="token0" if direction == "token1_in" else "token1",
            amount_in_wei=amount_in_raw,
            amount_out_wei=amount_out_raw,
            dex=source_dex,
            pool_address=pool_address,
            fee_tier=0,  # Unknown from log alone
            estimated_size_usd=estimated_size_usd,
            estimated_impact_bps=max(1.0, min(50.0, estimated_size_usd / 10000)),  # Rough estimate
            timestamp=ts,
        )
    except Exception as exc:
        logger.debug("Failed to normalize swap log: %s", str(exc)[:120])
        return None



def load_events_from_file(path: str) -> List[OrderflowEvent]:
    """Load orderflow events from a JSON file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Event file not found: {path}")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    events_raw = data if isinstance(data, list) else data.get("events", [])
    events = []
    for raw in events_raw:
        events.append(OrderflowEvent(**raw))
    return events

