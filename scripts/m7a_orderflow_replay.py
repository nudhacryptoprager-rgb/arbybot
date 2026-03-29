#!/usr/bin/env python3
"""
M7.A.5 — Live block-event backrun replay on arbitrum_one.

Hypothesis: block_event_backrun on arbitrum_one may produce viable measured edge
when replay uses real block events and post-event live quotes instead of
offline estimated state.

This script implements a read-only event-driven replay pipeline:
  event → post-trade state delta → best backrun venue → measured net

Modes:
  --offline             Score backrun opportunities from built-in fixture events
  --replay <file>       Score from imported event samples (JSON)
  --online              Score fixture events using live RPC quotes at current block
  --live-blocks N       M7.A.5: Fetch real Swap events from last N blocks, score with live quotes
  --ws-live             M7.A.5.3: WebSocket newHeads subscription + parallel scoring
  --intent-scout        Read-only feasibility assessment of orderflow surfaces

Usage:
    python scripts/m7a_orderflow_replay.py --offline --output data/tmp/m7a_orderflow_offline.json
    python scripts/m7a_orderflow_replay.py --replay data/tmp/events.json --output data/tmp/m7a_replay.json
    python scripts/m7a_orderflow_replay.py --intent-scout --output data/tmp/m7a_intent_scout.json
    python scripts/m7a_orderflow_replay.py --online --output data/tmp/m7a_orderflow_online.json
    python scripts/m7a_orderflow_replay.py --live-blocks 5 --output data/tmp/m7a_live_blocks.json
    python scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 10 --output data/tmp/m7a_ws_live.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Supported event types for the replay pipeline
EVENT_TYPE_SWAP = "swap"
EVENT_TYPE_LARGE_TRANSFER = "large_transfer"
EVENT_TYPE_POOL_REBALANCE = "pool_rebalance"
ALL_EVENT_TYPES = frozenset({EVENT_TYPE_SWAP, EVENT_TYPE_LARGE_TRANSFER, EVENT_TYPE_POOL_REBALANCE})

# Backrun direction labels
BACKRUN_BUY_DEPRESSED = "buy_depressed_token"
BACKRUN_SELL_APPRECIATED = "sell_appreciated_token"
BACKRUN_TRIANGULAR = "triangular_post_event"

# Reject reason codes
REJECT_NO_COUNTER_VENUE = "NO_COUNTER_VENUE"
REJECT_GAS_EXCEEDS_GROSS = "GAS_EXCEEDS_GROSS"
REJECT_SLIPPAGE_EXCEEDS_GROSS = "SLIPPAGE_EXCEEDS_GROSS"
REJECT_EVENT_TOO_SMALL = "EVENT_TOO_SMALL"
REJECT_SAME_BLOCK_IMPOSSIBLE = "SAME_BLOCK_IMPOSSIBLE"
REJECT_QUOTE_FAILURE = "QUOTE_FAILURE"
REJECT_INSUFFICIENT_IMPACT = "INSUFFICIENT_IMPACT"

ALL_REJECT_REASONS = frozenset({
    REJECT_NO_COUNTER_VENUE,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_EVENT_TOO_SMALL,
    REJECT_SAME_BLOCK_IMPOSSIBLE,
    REJECT_QUOTE_FAILURE,
    REJECT_INSUFFICIENT_IMPACT,
})

# Intent/auction surface types
SURFACE_MEV_SHARE_BACKRUN = "mev_share_backrun"
SURFACE_UNISWAPX_FILLER = "uniswapx_filler"
SURFACE_COW_SOLVER = "cow_solver"
SURFACE_BLOCK_BACKRUN = "block_event_backrun"

ALL_SURFACES = frozenset({
    SURFACE_MEV_SHARE_BACKRUN,
    SURFACE_UNISWAPX_FILLER,
    SURFACE_COW_SOLVER,
    SURFACE_BLOCK_BACKRUN,
})

# Thresholds for event classification
MIN_EVENT_SIZE_USD = 100.0  # Below this, gas dominates — skip
SIGNIFICANT_IMPACT_BPS = 5.0  # Minimum price impact to consider backrunnable
DEFAULT_BACKRUN_GAS = 200_000  # Two-swap backrun gas estimate
DEFAULT_GAS_PRICE_GWEI = 0.1  # Arbitrum typical

# Canonical chain for M7.A.4/M7.A.5 (same as M7.A: arbitrum_one)
M7A4_CHAIN = "arbitrum_one"

# Uniswap V3 Swap event topic (shared across V3 forks)
SWAP_EVENT_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

# Default number of recent blocks to scan for live events
DEFAULT_LIVE_BLOCKS = 5

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class OrderflowEvent:
    """A single orderflow event suitable for backrun replay."""

    event_id: str
    event_type: str  # One of ALL_EVENT_TYPES
    chain: str
    block_number: int
    tx_hash: str  # Real or synthetic
    token_in: str  # Symbol (e.g. "USDC")
    token_out: str  # Symbol (e.g. "WETH")
    amount_in_wei: int
    amount_out_wei: int
    dex: str  # Source DEX where event occurred
    pool_address: str
    fee_tier: int
    estimated_size_usd: float
    estimated_impact_bps: float  # Estimated price impact of user trade
    timestamp: str  # ISO-8601

    def __post_init__(self):
        if self.event_type not in ALL_EVENT_TYPES:
            raise ValueError(f"Unknown event_type: {self.event_type!r}")


@dataclass
class BackrunResult:
    """Result of scoring a backrun opportunity from an event."""

    event_id: str
    event_source: str  # "fixture" | "imported" | "live"
    event_type: str
    post_trade_state_used: str  # "estimated" | "simulated" | "quoted" | "live"
    backrun_direction: str  # Direction of backrun
    best_buy_venue: Optional[str] = None
    best_sell_venue: Optional[str] = None
    candidate_path: Optional[List[str]] = None  # e.g. ["WETH", "USDC", "WETH"]
    amount_in_wei: int = 0
    gross_pnl_wei: int = 0
    gas_cost_wei: int = 0
    fee_cost_wei: int = 0
    net_pnl_wei: int = 0
    best_backrun_net_bps: float = 0.0
    same_block_possible: bool = False
    route_viable: bool = False
    reject_reason: Optional[str] = None
    # M7.A.5 live replay fields (None for offline/fixture results)
    event_block: Optional[int] = None
    quote_block: Optional[int] = None
    block_lag: Optional[int] = None  # quote_block - event_block
    same_state_class: Optional[str] = None  # "same_block" | "next_block" | "stale"
    counter_venue_count: int = 0
    best_live_net_bps: Optional[float] = None  # Net bps from live quotes
    # M7.A.5.3 ws-live fields (None for non-ws modes)
    ws_provider: Optional[str] = None  # "alchemy" | "public" | "unknown"
    event_detected_at_block: Optional[int] = None  # Block when newHead triggered
    quote_started_block: Optional[int] = None
    quote_finished_block: Optional[int] = None
    quote_pipeline_latency_ms: Optional[float] = None
    venues_pruned_by_multicall: int = 0
    # M7.A.5.3.1 latency budget fields (None for non-ws modes)
    latency_budget_ms: Optional[float] = None  # chain block_time_ms budget


@dataclass
class IntentSurfaceAssessment:
    """Read-only feasibility assessment of an orderflow surface."""

    surface_type: str  # One of ALL_SURFACES
    chain: str
    description: str
    # Feasibility dimensions
    orderflow_accessible: bool  # Can we read the orderflow?
    execution_model: str  # "backrun_bundle" | "filler_rfq" | "solver_batch" | "direct_arb"
    requires_private_inventory: bool
    requires_onchain_execution: bool
    latency_class: str  # "sub_block" | "single_block" | "multi_block"
    capital_requirement_class: str  # "zero" | "low" | "medium" | "high"
    # Repo readiness
    quote_infra_ready: bool  # Can existing adapters quote this surface?
    simulation_possible: bool  # Can we simulate without execution?
    current_repo_gap: str  # What's missing to score this surface
    # Assessment
    feasibility_score: str  # "high" | "medium" | "low" | "not_feasible"
    key_advantage: str
    key_risk: str


# ---------------------------------------------------------------------------
# Fixture events (offline mode)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------

def classify_event_backrun_type(event: OrderflowEvent) -> str:
    """Classify what kind of backrun opportunity an event creates.

    Returns one of the BACKRUN_* direction constants.
    """
    # A swap pushes token_out price up and token_in price down
    # Backrun buys the depressed token (token_in) on cheap venue,
    # sells on the impacted pool where price is now worse for sellers
    if event.estimated_impact_bps >= SIGNIFICANT_IMPACT_BPS:
        return BACKRUN_BUY_DEPRESSED
    # Low impact events: check if triangular path exists
    return BACKRUN_SELL_APPRECIATED


def classify_event_viability(event: OrderflowEvent) -> Optional[str]:
    """Pre-classify whether an event is viable for backrun scoring.

    Returns a reject reason string if not viable, None if viable.
    """
    if event.estimated_size_usd < MIN_EVENT_SIZE_USD:
        return REJECT_EVENT_TOO_SMALL
    if event.estimated_impact_bps < 0.1:
        return REJECT_INSUFFICIENT_IMPACT
    return None


# ---------------------------------------------------------------------------
# Backrun scoring (offline estimation)
# ---------------------------------------------------------------------------

def estimate_backrun_gross_bps(event: OrderflowEvent) -> float:
    """Estimate theoretical gross backrun profit in bps.

    Offline estimation based on event characteristics:
    - Price impact creates a temporary dislocation
    - Backrunner captures a fraction of the impact by arbing across venues
    - Capture rate depends on venue diversity and competition

    This is a bounded theoretical estimate, not a simulation.
    """
    impact = event.estimated_impact_bps
    # Theoretical capture: backrunner can capture up to ~50% of impact
    # in a competitive environment (multiple searchers, fast inclusion)
    # In practice, competition and gas erode most of this
    CAPTURE_RATE = 0.3  # 30% of impact as gross (optimistic for solo searcher)
    COMPETITION_DECAY = 0.5  # 50% lost to competition
    return impact * CAPTURE_RATE * (1.0 - COMPETITION_DECAY)


def estimate_gas_cost_bps(event: OrderflowEvent) -> float:
    """Estimate gas cost in bps for a two-swap backrun on Arbitrum."""
    gas_cost_eth = DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e-9
    gas_cost_usd = gas_cost_eth * 3500  # ETH price estimate
    if event.estimated_size_usd <= 0:
        return 10000.0  # Infinite gas overhead
    return (gas_cost_usd / event.estimated_size_usd) * 10000


def estimate_fee_cost_bps(event: OrderflowEvent) -> float:
    """Estimate protocol fee cost for backrun legs."""
    # Two-leg backrun: buy on venue A, sell on venue B
    # Each leg has a protocol fee tier; use typical Arbitrum tiers
    leg1_fee_bps = event.fee_tier / 10000 if event.fee_tier else 5.0
    leg2_fee_bps = 5.0  # Assume 500 fee tier (5 bps) for counter-venue
    return leg1_fee_bps + leg2_fee_bps


def score_backrun_offline(event: OrderflowEvent) -> BackrunResult:
    """Score a single event's backrun opportunity in offline mode.

    Uses theoretical estimation based on event characteristics.
    No RPC calls, no state forking — bounded feasibility estimate only.
    """
    # Pre-viability check
    reject = classify_event_viability(event)
    if reject is not None:
        return BackrunResult(
            event_id=event.event_id,
            event_source="fixture",
            event_type=event.event_type,
            post_trade_state_used="estimated",
            backrun_direction=classify_event_backrun_type(event),
            reject_reason=reject,
        )

    backrun_dir = classify_event_backrun_type(event)
    gross_bps = estimate_backrun_gross_bps(event)
    gas_bps = estimate_gas_cost_bps(event)
    fee_bps = estimate_fee_cost_bps(event)
    net_bps = gross_bps - gas_bps - fee_bps

    # Determine viability
    reject_reason = None
    route_viable = True
    if gas_bps > gross_bps:
        reject_reason = REJECT_GAS_EXCEEDS_GROSS
        route_viable = False
    elif fee_bps > gross_bps:
        reject_reason = REJECT_SLIPPAGE_EXCEEDS_GROSS
        route_viable = False
    elif net_bps < 0:
        # Net negative but for a different reason
        route_viable = False

    # Estimate wei amounts from bps (proportional to event size)
    amount_in = event.amount_in_wei
    gross_wei = int(amount_in * gross_bps / 10000) if amount_in > 0 else 0
    gas_wei = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)
    fee_wei = int(amount_in * fee_bps / 10000) if amount_in > 0 else 0
    net_wei = gross_wei - gas_wei - fee_wei

    # Build candidate path
    candidate_path = [event.token_out, event.token_in, event.token_out]

    return BackrunResult(
        event_id=event.event_id,
        event_source="fixture",
        event_type=event.event_type,
        post_trade_state_used="estimated",
        backrun_direction=backrun_dir,
        best_buy_venue=event.dex,  # Same venue (impacted)
        best_sell_venue="counter_venue",  # Theoretical counter-venue
        candidate_path=candidate_path,
        amount_in_wei=amount_in,
        gross_pnl_wei=gross_wei,
        gas_cost_wei=gas_wei,
        fee_cost_wei=fee_wei,
        net_pnl_wei=net_wei,
        best_backrun_net_bps=round(net_bps, 4),
        same_block_possible=event.chain == M7A4_CHAIN,  # Arbitrum 250ms blocks
        route_viable=route_viable,
        reject_reason=reject_reason,
    )


# ---------------------------------------------------------------------------
# M7.A.5: Live block-event fetching and normalization
# ---------------------------------------------------------------------------

# V3 fee tiers to try when pool fee is unknown
_DEFAULT_FEE_TIERS = [500, 3000, 100, 10000]


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


# ---------------------------------------------------------------------------
# M7.A.5: Live backrun scoring using read_quoter_v2 (sync)
# ---------------------------------------------------------------------------

def score_backrun_live(
    event: OrderflowEvent,
    rpc_url: str,
    dex_configs: Dict[str, Any],
    token_addresses: Dict[str, str],
    current_block: int,
    fallback_rpc_urls: Optional[List[str]] = None,
) -> BackrunResult:
    """Score a backrun opportunity using live QuoterV2 RPC quotes.

    M7.A.5: Uses read_quoter_v2() from strategy/quote_rpc.py for
    sync measured quotes at the current block (post-event state).
    Replaces the broken M7.A.4 score_backrun_online which used
    incorrect adapter constructors.

    Quotes each known V3 DEX with quoter_v2, finds best buy/sell,
    computes measured net spread.
    """
    from strategy.quote_rpc import read_quoter_v2, QUOTER_RATE_LIMITED

    backrun_dir = classify_event_backrun_type(event)

    # Backrun size: ~10% of the original event
    backrun_size_wei = max(event.amount_in_wei // 10, 1)

    # We need real token addresses for quoting
    # For live-fetched events, token_in/token_out may be direction tags
    # Try to resolve actual token addresses
    token_in_addr = token_addresses.get(event.token_out, "")
    token_out_addr = token_addresses.get(event.token_in, "")

    # If we can't resolve tokens (live events without token identification),
    # fall back to quoting common pairs
    use_common_pairs = not token_in_addr or not token_out_addr

    # Track best quotes across venues
    best_buy_amount = None  # Best amount_out when buying the depressed token
    best_buy_venue = None
    best_sell_amount = None  # Best amount_out when selling
    best_sell_venue = None
    venues_quoted = 0
    quote_block = current_block

    # DEXes that have quoter_v2 (V3 forks)
    quotable_dexes = []
    for dex_name, cfg in dex_configs.items():
        quoter = cfg.get("quoter_v2") or cfg.get("quoter")
        if quoter:
            quotable_dexes.append((dex_name, cfg, quoter))

    if use_common_pairs:
        # For live events where we don't know the exact tokens,
        # try the most common pair: WETH/USDC
        weth_addr = token_addresses.get("WETH", "")
        usdc_addr = token_addresses.get("USDC", "")
        if not weth_addr or not usdc_addr:
            return BackrunResult(
                event_id=event.event_id,
                event_source="live",
                event_type=event.event_type,
                post_trade_state_used="live",
                backrun_direction=backrun_dir,
                reject_reason=REJECT_QUOTE_FAILURE,
                event_block=event.block_number,
                quote_block=quote_block,
                block_lag=quote_block - event.block_number,
            )
        # Use WETH→USDC as representative quote
        token_in_addr = weth_addr
        token_out_addr = usdc_addr
        backrun_size_wei = 10**16  # 0.01 ETH — small test size

    # Pass 1: Find best buy across all venues/fees
    for dex_name, cfg, quoter_addr in quotable_dexes:
        fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
        for fee in fee_tiers[:2]:  # Limit to 2 fee tiers to conserve RPC calls
            try:
                buy_result = read_quoter_v2(
                    quoter_address=quoter_addr,
                    token_in=token_in_addr,
                    token_out=token_out_addr,
                    amount_in=backrun_size_wei,
                    fee=fee,
                    rpc_url=rpc_url,
                    block_num="latest",
                    fallback_rpc_urls=fallback_rpc_urls,
                )
                if buy_result and buy_result is not QUOTER_RATE_LIMITED:
                    amt_out = buy_result.get("amount_out", 0)
                    if amt_out > 0:
                        venues_quoted += 1
                        if best_buy_amount is None or amt_out > best_buy_amount:
                            best_buy_amount = amt_out
                            best_buy_venue = dex_name
            except Exception as exc:
                logger.debug(
                    "Live buy quote failed for %s fee=%d: %s",
                    dex_name,
                    fee,
                    str(exc)[:100],
                    extra={"context": {"dex": dex_name, "event_id": event.event_id}},
                )
                continue

    # Pass 2: Sell the buy output back — use best_buy_amount as input
    if best_buy_amount is not None:
        for dex_name, cfg, quoter_addr in quotable_dexes:
            fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
            for fee in fee_tiers[:2]:
                try:
                    sell_result = read_quoter_v2(
                        quoter_address=quoter_addr,
                        token_in=token_out_addr,
                        token_out=token_in_addr,
                        amount_in=best_buy_amount,
                        fee=fee,
                        rpc_url=rpc_url,
                        block_num="latest",
                        fallback_rpc_urls=fallback_rpc_urls,
                    )
                    if sell_result and sell_result is not QUOTER_RATE_LIMITED:
                        amt_out = sell_result.get("amount_out", 0)
                        if amt_out > 0:
                            if best_sell_amount is None or amt_out > best_sell_amount:
                                best_sell_amount = amt_out
                                best_sell_venue = dex_name
                except Exception as exc:
                    logger.debug(
                        "Live sell quote failed for %s fee=%d: %s",
                        dex_name,
                        fee,
                        str(exc)[:100],
                        extra={"context": {"dex": dex_name, "event_id": event.event_id}},
                    )
                    continue

    # Compute block lag and state classification
    block_lag = quote_block - event.block_number
    if block_lag == 0:
        same_state_class = "same_block"
    elif block_lag <= 2:
        same_state_class = "next_block"
    else:
        same_state_class = "stale"

    # Compute measured net from best quotes
    if best_buy_amount is not None and best_sell_amount is not None:
        # Gross = what we get selling minus what we spend buying
        # We buy token_out with backrun_size_wei of token_in → get best_buy_amount
        # We sell best_buy_amount of token_out → get best_sell_amount of token_in
        # Net = best_sell_amount - backrun_size_wei (in token_in units)
        gross_wei = best_sell_amount - backrun_size_wei
        gas_cost_wei = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)
        net_wei = gross_wei - gas_cost_wei
        net_bps = (net_wei / backrun_size_wei) * 10000 if backrun_size_wei > 0 else 0.0

        route_viable = net_bps > 0
        reject_reason = None if route_viable else REJECT_GAS_EXCEEDS_GROSS

        return BackrunResult(
            event_id=event.event_id,
            event_source="live",
            event_type=event.event_type,
            post_trade_state_used="live",
            backrun_direction=backrun_dir,
            best_buy_venue=best_buy_venue,
            best_sell_venue=best_sell_venue,
            candidate_path=[event.token_out, event.token_in, event.token_out],
            amount_in_wei=backrun_size_wei,
            gross_pnl_wei=gross_wei,
            gas_cost_wei=gas_cost_wei,
            fee_cost_wei=0,  # Already in quote spread
            net_pnl_wei=net_wei,
            best_backrun_net_bps=round(net_bps, 4),
            same_block_possible=(block_lag == 0),
            route_viable=route_viable,
            reject_reason=reject_reason,
            event_block=event.block_number,
            quote_block=quote_block,
            block_lag=block_lag,
            same_state_class=same_state_class,
            counter_venue_count=venues_quoted,
            best_live_net_bps=round(net_bps, 4),
        )

    return BackrunResult(
        event_id=event.event_id,
        event_source="live",
        event_type=event.event_type,
        post_trade_state_used="live",
        backrun_direction=backrun_dir,
        reject_reason=REJECT_QUOTE_FAILURE,
        event_block=event.block_number,
        quote_block=quote_block,
        block_lag=block_lag,
        same_state_class=same_state_class,
        counter_venue_count=venues_quoted,
    )


# ---------------------------------------------------------------------------
# M7.A.5.3: Parallel live scoring with multicall-assisted venue pruning
# ---------------------------------------------------------------------------

def _get_pool_addresses_for_dexes(
    dex_configs: Dict[str, Any],
    token_in_addr: str,
    token_out_addr: str,
) -> List[str]:
    """Collect known pool addresses from dex configs for multicall prefetch.

    Best-effort: returns addresses that might exist based on V3 factory patterns.
    For proper prefetch, callers should use the pool registry or discovery module.
    """
    # For now return empty — multicall prefetch will use addresses from factory resolution
    # This is intentionally minimal; the prefetch adds value when pool addresses are known
    return []


def score_backrun_live_parallel(
    event: OrderflowEvent,
    rpc_url: str,
    dex_configs: Dict[str, Any],
    token_addresses: Dict[str, str],
    current_block: int,
    ws_provider: Optional[str] = None,
    event_detected_at_block: Optional[int] = None,
    fallback_rpc_urls: Optional[List[str]] = None,
    block_time_ms: Optional[float] = None,
) -> BackrunResult:
    """Score a backrun using parallel QuoterV2 RPC quotes with multicall prefetch.

    M7.A.5.3: Uses ThreadPoolExecutor for parallel buy/sell fanout and
    multicall-assisted venue pruning to reduce pipeline latency.

    Key differences from score_backrun_live:
    - Parallel buy quotes across venues (ThreadPoolExecutor)
    - Multicall prefetch for venue prefiltering (prune dead liquidity)
    - Latency tracking fields (pipeline_ms, detected_at_block, etc.)
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from strategy.quote_rpc import read_quoter_v2, QUOTER_RATE_LIMITED

    pipeline_start = time.monotonic()
    backrun_dir = classify_event_backrun_type(event)

    # Backrun size: ~10% of the original event
    backrun_size_wei = max(event.amount_in_wei // 10, 1)

    token_in_addr = token_addresses.get(event.token_out, "")
    token_out_addr = token_addresses.get(event.token_in, "")
    use_common_pairs = not token_in_addr or not token_out_addr

    quote_started_block = current_block

    # DEXes that have quoter_v2
    quotable_dexes = []
    for dex_name, cfg in dex_configs.items():
        quoter = cfg.get("quoter_v2") or cfg.get("quoter")
        if quoter:
            quotable_dexes.append((dex_name, cfg, quoter))

    if use_common_pairs:
        weth_addr = token_addresses.get("WETH", "")
        usdc_addr = token_addresses.get("USDC", "")
        if not weth_addr or not usdc_addr:
            return BackrunResult(
                event_id=event.event_id,
                event_source="live",
                event_type=event.event_type,
                post_trade_state_used="live",
                backrun_direction=backrun_dir,
                reject_reason=REJECT_QUOTE_FAILURE,
                event_block=event.block_number,
                quote_block=current_block,
                block_lag=current_block - event.block_number,
                ws_provider=ws_provider,
                event_detected_at_block=event_detected_at_block,
                quote_started_block=quote_started_block,
                quote_finished_block=current_block,
                quote_pipeline_latency_ms=round((time.monotonic() - pipeline_start) * 1000, 2),
                latency_budget_ms=block_time_ms,
            )
        token_in_addr = weth_addr
        token_out_addr = usdc_addr
        backrun_size_wei = 10**16  # 0.01 ETH

    # Multicall-assisted venue pruning (best-effort)
    venues_pruned = 0
    try:
        from strategy.quote_rpc import (
            prefetch_slot0_multicall,
            get_cached_liquidity,
        )
        # Collect pool addresses if any are known
        pool_addrs = _get_pool_addresses_for_dexes(dex_configs, token_in_addr, token_out_addr)
        if pool_addrs:
            prefetch_slot0_multicall(pool_addrs, rpc_url, current_block)
            # Prune venues with zero liquidity
            orig_count = len(quotable_dexes)
            active_dexes = []
            for dex_name, cfg, quoter in quotable_dexes:
                # Check if any known pool for this dex has liquidity
                pools_for_dex = [a for a in pool_addrs if a in cfg.get("_known_pools", [])]
                if pools_for_dex:
                    has_liq = any(
                        (get_cached_liquidity(p) or 0) > 0 for p in pools_for_dex
                    )
                    if not has_liq:
                        venues_pruned += 1
                        continue
                active_dexes.append((dex_name, cfg, quoter))
            quotable_dexes = active_dexes
    except Exception as exc:
        logger.debug("Multicall prefetch skipped: %s", str(exc)[:100])

    # Parallel buy pass: fan out across all venues × fee tiers
    best_buy_amount = None
    best_buy_venue = None
    venues_quoted = 0

    def _try_buy(dex_name: str, quoter_addr: str, fee: int):
        try:
            result = read_quoter_v2(
                quoter_address=quoter_addr,
                token_in=token_in_addr,
                token_out=token_out_addr,
                amount_in=backrun_size_wei,
                fee=fee,
                rpc_url=rpc_url,
                block_num="latest",
                fallback_rpc_urls=fallback_rpc_urls,
            )
            if result and result is not QUOTER_RATE_LIMITED:
                amt = result.get("amount_out", 0)
                if amt > 0:
                    return (dex_name, amt)
        except Exception:
            pass
        return None

    buy_jobs = []
    for dex_name, cfg, quoter_addr in quotable_dexes:
        fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
        for fee in fee_tiers[:2]:
            buy_jobs.append((dex_name, quoter_addr, fee))

    # Use ThreadPoolExecutor for parallel buy quotes
    if buy_jobs:
        with ThreadPoolExecutor(max_workers=min(len(buy_jobs), 6)) as executor:
            futures = {
                executor.submit(_try_buy, dn, qa, f): (dn, f)
                for dn, qa, f in buy_jobs
            }
            for future in as_completed(futures):
                result = future.result()
                if result is not None:
                    dex_name, amt = result
                    venues_quoted += 1
                    if best_buy_amount is None or amt > best_buy_amount:
                        best_buy_amount = amt
                        best_buy_venue = dex_name

    # Parallel sell pass: sell best_buy_amount back
    best_sell_amount = None
    best_sell_venue = None

    if best_buy_amount is not None:
        def _try_sell(dex_name: str, quoter_addr: str, fee: int):
            try:
                result = read_quoter_v2(
                    quoter_address=quoter_addr,
                    token_in=token_out_addr,
                    token_out=token_in_addr,
                    amount_in=best_buy_amount,
                    fee=fee,
                    rpc_url=rpc_url,
                    block_num="latest",
                    fallback_rpc_urls=fallback_rpc_urls,
                )
                if result and result is not QUOTER_RATE_LIMITED:
                    amt = result.get("amount_out", 0)
                    if amt > 0:
                        return (dex_name, amt)
            except Exception:
                pass
            return None

        sell_jobs = []
        for dex_name, cfg, quoter_addr in quotable_dexes:
            fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
            for fee in fee_tiers[:2]:
                sell_jobs.append((dex_name, quoter_addr, fee))

        if sell_jobs:
            with ThreadPoolExecutor(max_workers=min(len(sell_jobs), 6)) as executor:
                futures = {
                    executor.submit(_try_sell, dn, qa, f): (dn, f)
                    for dn, qa, f in sell_jobs
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result is not None:
                        dex_name, amt = result
                        if best_sell_amount is None or amt > best_sell_amount:
                            best_sell_amount = amt
                            best_sell_venue = dex_name

    pipeline_end = time.monotonic()
    pipeline_ms = round((pipeline_end - pipeline_start) * 1000, 2)

    # Get current block after quoting for lag measurement
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        quote_finished_block = w3.eth.block_number
    except Exception:
        quote_finished_block = current_block

    # Compute block lag and state classification
    block_lag = quote_finished_block - event.block_number
    if block_lag == 0:
        same_state_class = "same_block"
    elif block_lag <= 2:
        same_state_class = "next_block"
    else:
        same_state_class = "stale"

    if best_buy_amount is not None and best_sell_amount is not None:
        gross_wei = best_sell_amount - backrun_size_wei
        gas_cost_wei = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)
        net_wei = gross_wei - gas_cost_wei
        net_bps = (net_wei / backrun_size_wei) * 10000 if backrun_size_wei > 0 else 0.0

        route_viable = net_bps > 0
        reject_reason = None if route_viable else REJECT_GAS_EXCEEDS_GROSS

        return BackrunResult(
            event_id=event.event_id,
            event_source="live",
            event_type=event.event_type,
            post_trade_state_used="live",
            backrun_direction=backrun_dir,
            best_buy_venue=best_buy_venue,
            best_sell_venue=best_sell_venue,
            candidate_path=[event.token_out, event.token_in, event.token_out],
            amount_in_wei=backrun_size_wei,
            gross_pnl_wei=gross_wei,
            gas_cost_wei=gas_cost_wei,
            fee_cost_wei=0,
            net_pnl_wei=net_wei,
            best_backrun_net_bps=round(net_bps, 4),
            same_block_possible=(block_lag == 0),
            route_viable=route_viable,
            reject_reason=reject_reason,
            event_block=event.block_number,
            quote_block=quote_finished_block,
            block_lag=block_lag,
            same_state_class=same_state_class,
            counter_venue_count=venues_quoted,
            best_live_net_bps=round(net_bps, 4),
            ws_provider=ws_provider,
            event_detected_at_block=event_detected_at_block,
            quote_started_block=quote_started_block,
            quote_finished_block=quote_finished_block,
            quote_pipeline_latency_ms=pipeline_ms,
            venues_pruned_by_multicall=venues_pruned,
            latency_budget_ms=block_time_ms,
        )

    return BackrunResult(
        event_id=event.event_id,
        event_source="live",
        event_type=event.event_type,
        post_trade_state_used="live",
        backrun_direction=backrun_dir,
        reject_reason=REJECT_QUOTE_FAILURE,
        event_block=event.block_number,
        quote_block=quote_finished_block,
        block_lag=block_lag,
        same_state_class=same_state_class,
        counter_venue_count=venues_quoted,
        ws_provider=ws_provider,
        event_detected_at_block=event_detected_at_block,
        quote_started_block=quote_started_block,
        quote_finished_block=quote_finished_block,
        quote_pipeline_latency_ms=pipeline_ms,
        venues_pruned_by_multicall=venues_pruned,
        latency_budget_ms=block_time_ms,
    )


# ---------------------------------------------------------------------------
# Legacy online scoring (fixture events + live quotes) — kept for backward compat
# ---------------------------------------------------------------------------

def score_backrun_online(
    event: OrderflowEvent,
    rpc_url: str,
    dex_configs: Dict[str, Any],
    token_addresses: Dict[str, str],
) -> BackrunResult:
    """Score a backrun using live QuoterV2 quotes (fixture events).

    Legacy wrapper around score_backrun_live for --online mode
    which uses fixture events instead of live block events.
    """
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    current_block = w3.eth.block_number

    result = score_backrun_live(
        event=event,
        rpc_url=rpc_url,
        dex_configs=dex_configs,
        token_addresses=token_addresses,
        current_block=current_block,
    )
    # Mark as fixture-sourced for backward compatibility
    result.event_source = "fixture"
    result.post_trade_state_used = "quoted"
    return result


# ---------------------------------------------------------------------------
# Intent / auction surface scout
# ---------------------------------------------------------------------------

def build_intent_surface_assessments() -> List[IntentSurfaceAssessment]:
    """Build read-only feasibility assessments for orderflow surfaces.

    This is a structured classification, not execution or integration.
    """
    return [
        IntentSurfaceAssessment(
            surface_type=SURFACE_MEV_SHARE_BACKRUN,
            chain="ethereum_mainnet",
            description=(
                "Flashbots MEV-Share: users share tx hints via MEV-Share Node; "
                "searchers submit backrun bundles. Node simulates, forwards "
                "successful bundles to builders with user refund conditions."
            ),
            orderflow_accessible=True,
            execution_model="backrun_bundle",
            requires_private_inventory=False,
            requires_onchain_execution=True,
            latency_class="sub_block",
            capital_requirement_class="medium",
            quote_infra_ready=False,
            simulation_possible=True,
            current_repo_gap=(
                "No MEV-Share event stream client. No bundle submission. "
                "No trace_callMany for post-trade simulation. "
                "Repo adapters are Arbitrum-focused, not Ethereum mainnet."
            ),
            feasibility_score="medium",
            key_advantage=(
                "Orderflow-driven: edge from reacting to user trades, "
                "not static pool state. Permissionless for searchers."
            ),
            key_risk=(
                "Ethereum mainnet gas costs 100-1000x Arbitrum. "
                "High competition from professional searchers. "
                "Requires archive node with trace API."
            ),
        ),
        IntentSurfaceAssessment(
            surface_type=SURFACE_UNISWAPX_FILLER,
            chain="arbitrum_one",
            description=(
                "UniswapX Dutch auctions: users sign intent orders with "
                "decay curves. Fillers compete to fill at best price. "
                "Can use on-chain liquidity AND private inventory."
            ),
            orderflow_accessible=True,
            execution_model="filler_rfq",
            requires_private_inventory=False,  # Can use on-chain only
            requires_onchain_execution=True,
            latency_class="single_block",
            capital_requirement_class="high",
            quote_infra_ready=True,  # Existing adapters can quote Arb venues
            simulation_possible=True,
            current_repo_gap=(
                "No UniswapX order stream client. No filler contract. "
                "No Dutch auction decay modeling. No Permit2 signing. "
                "Quote infra exists but no order-to-fill pipeline."
            ),
            feasibility_score="medium",
            key_advantage=(
                "Already on arbitrum_one where repo infrastructure lives. "
                "Existing quote adapters can score fill profitability. "
                "Access to private + public liquidity."
            ),
            key_risk=(
                "Filler competition from professional MMs with private inventory. "
                "Capital-intensive: must hold tokens to fill. "
                "UniswapX API key required."
            ),
        ),
        IntentSurfaceAssessment(
            surface_type=SURFACE_COW_SOLVER,
            chain="ethereum_mainnet",
            description=(
                "CoW Protocol batch auction: orders batched into settlements. "
                "Solvers compete to find best execution (including CoWs — "
                "coincidence of wants). Flash-loan-backed settlement possible."
            ),
            orderflow_accessible=True,
            execution_model="solver_batch",
            requires_private_inventory=False,  # Flash loans available
            requires_onchain_execution=True,
            latency_class="multi_block",
            capital_requirement_class="low",  # Flash loans reduce capital needs
            quote_infra_ready=False,
            simulation_possible=True,
            current_repo_gap=(
                "No CoW orderbook API client. No solver framework. "
                "No batch auction optimizer. No flash-loan router. "
                "Repo is single-trade focused, not batch."
            ),
            feasibility_score="low",
            key_advantage=(
                "Flash-loan-backed: low capital requirement. "
                "Batch auctions create unique opportunity shapes "
                "(CoWs, surplus extraction). Permissionless solver entry."
            ),
            key_risk=(
                "Ethereum mainnet gas. Complex solver optimization needed. "
                "Mature solver competition (Gnosis solvers). "
                "Batch settlement delay reduces alpha decay advantage."
            ),
        ),
        IntentSurfaceAssessment(
            surface_type=SURFACE_BLOCK_BACKRUN,
            chain=M7A4_CHAIN,
            description=(
                "Monitor Arbitrum block events (large swaps, rebalances) "
                "and score backrun opportunities using existing adapter "
                "infrastructure. Post-block analysis, not pre-block insertion."
            ),
            orderflow_accessible=True,
            execution_model="direct_arb",
            requires_private_inventory=False,
            requires_onchain_execution=True,
            latency_class="single_block",
            capital_requirement_class="low",
            quote_infra_ready=True,
            simulation_possible=True,
            current_repo_gap=(
                "No block event parser (swap log decoder). "
                "No post-trade state delta estimator. "
                "Existing DirtySetWatcher tracks new blocks but "
                "doesn't parse individual swap events."
            ),
            feasibility_score="high",
            key_advantage=(
                "Reuses existing Arbitrum adapter infrastructure. "
                "Low gas cost. Post-event quoting is simple extension "
                "of current measured scoring."
            ),
            key_risk=(
                "Post-block analysis misses same-block opportunities. "
                "Arbitrum sequencer ordering limits backrun placement. "
                "Still bounded by venue diversity (M7.A evidence)."
            ),
        ),
    ]


def build_intent_scout_summary(
    assessments: List[IntentSurfaceAssessment],
) -> Dict[str, Any]:
    """Build machine-readable summary of intent surface scout."""
    by_feasibility: Dict[str, List[str]] = {}
    for a in assessments:
        by_feasibility.setdefault(a.feasibility_score, []).append(a.surface_type)

    return {
        "scout_type": "intent_auction_surface",
        "chain_focus": M7A4_CHAIN,
        "surfaces_assessed": len(assessments),
        "by_feasibility": by_feasibility,
        "best_near_term": SURFACE_BLOCK_BACKRUN,
        "best_near_term_reason": (
            "Reuses existing arbitrum_one adapter infrastructure. "
            "Requires only block event parsing + post-event quoting. "
            "No new chain, no new capital, no new protocol integration."
        ),
        "assessments": [asdict(a) for a in assessments],
    }


# ---------------------------------------------------------------------------
# Replay pipeline (imported events)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Artifact builders
# ---------------------------------------------------------------------------

def build_replay_summary(
    events: List[OrderflowEvent],
    results: List[BackrunResult],
    mode: str,
) -> Dict[str, Any]:
    """Build machine-readable artifact from replay results."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    viable_count = sum(1 for r in results if r.route_viable)
    positive_net_count = sum(1 for r in results if r.best_backrun_net_bps > 0)
    all_net_bps = [r.best_backrun_net_bps for r in results]
    viable_net_bps = [r.best_backrun_net_bps for r in results if r.route_viable]

    # Reject reason histogram
    reject_counts: Dict[str, int] = {}
    for r in results:
        if r.reject_reason:
            reject_counts[r.reject_reason] = reject_counts.get(r.reject_reason, 0) + 1

    return {
        "m7a4_hypothesis": "orderflow_driven_backrun_replay",
        "mode": mode,
        "timestamp": ts,
        "chain": M7A4_CHAIN,
        "events_count": len(events),
        "results_count": len(results),
        "viable_count": viable_count,
        "positive_net_count": positive_net_count,
        "best_net_bps": round(max(all_net_bps), 4) if all_net_bps else None,
        "worst_net_bps": round(min(all_net_bps), 4) if all_net_bps else None,
        "mean_net_bps": round(sum(all_net_bps) / len(all_net_bps), 4) if all_net_bps else None,
        "viable_best_net_bps": round(max(viable_net_bps), 4) if viable_net_bps else None,
        "reject_histogram": reject_counts,
        "results": [asdict(r) for r in results],
        "two_leg_baseline_net_bps": -3.5062,
        "m7a_triangular_best_net_bps": -14.16,
        "beats_two_leg_baseline": positive_net_count > 0,
        "beats_triangular_baseline": (
            max(all_net_bps) > -14.16 if all_net_bps else False
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="M7.A.5 — Orderflow-driven replay with live block events",
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--offline",
        action="store_true",
        help="Score backrun opportunities from built-in fixture events",
    )
    mode_group.add_argument(
        "--replay",
        type=str,
        metavar="FILE",
        help="Score from imported event samples (JSON)",
    )
    mode_group.add_argument(
        "--online",
        action="store_true",
        help="Score fixture events using live RPC quotes at current block",
    )
    mode_group.add_argument(
        "--live-blocks",
        type=int,
        metavar="N",
        default=None,
        help="M7.A.5: Fetch real Swap events from last N blocks and score with live quotes",
    )
    mode_group.add_argument(
        "--intent-scout",
        action="store_true",
        help="Read-only feasibility assessment of orderflow surfaces",
    )
    mode_group.add_argument(
        "--ws-live",
        action="store_true",
        help="M7.A.5.3: WebSocket-triggered same-block/next-block replay with parallel scoring",
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON path (default: stdout)",
    )
    parser.add_argument(
        "--chain",
        type=str,
        default=M7A4_CHAIN,
        help=f"Chain to analyze (default: {M7A4_CHAIN})",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=20,
        help="Maximum number of live events to score (default: 20, limits RPC calls)",
    )
    parser.add_argument(
        "--ws-blocks",
        type=int,
        default=10,
        help="M7.A.5.3: Number of newHeads to process in ws-live mode (default: 10)",
    )
    parser.add_argument(
        "--ws-timeout",
        type=int,
        default=120,
        help="M7.A.5.3: Timeout in seconds for ws-live subscription (default: 120)",
    )

    return parser.parse_args()


def main():
    args = parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.intent_scout:
        logger.info("Running intent/auction surface scout")
        assessments = build_intent_surface_assessments()
        artifact = build_intent_scout_summary(assessments)
        artifact["timestamp"] = ts
    elif args.offline:
        logger.info("Running offline backrun replay with fixture events")
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
    elif args.replay:
        logger.info("Running replay from imported events: %s", args.replay)
        events = load_events_from_file(args.replay)
        results = [score_backrun_offline(e) for e in events]
        for r in results:
            r.event_source = "imported"
        artifact = build_replay_summary(events, results, mode="replay")
    elif args.online:
        logger.info("Running online backrun scoring with live quotes")
        from config import load_dexes, get_all_token_addresses
        from core.rpc_urls import get_rpc_url

        rpc_url = get_rpc_url(args.chain)
        all_dexes = load_dexes()
        dex_configs = all_dexes.get(args.chain, {})
        token_addresses = get_all_token_addresses(args.chain)

        events = build_fixture_events()
        results = [
            score_backrun_online(e, rpc_url, dex_configs, token_addresses)
            for e in events
        ]
        artifact = build_replay_summary(events, results, mode="online")
    elif args.live_blocks is not None:
        # M7.A.5: Live block-event backrun replay
        logger.info(
            "Running M7.A.5 live block-event replay (%d blocks)",
            args.live_blocks,
        )
        import os
        from urllib.parse import urlparse

        from config import load_dexes, get_all_token_addresses
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID

        chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, rpc_provider, rpc_diag = resolve_rpc_http(
            chain_id=chain_id,
            network=args.chain,
            env=dict(os.environ),
        )
        if not rpc_url:
            raise SystemExit(f"No RPC URL found for chain: {args.chain}")
        rpc_host = urlparse(rpc_url).netloc
        logger.info(
            "RPC resolved: provider=%s source=%s host=%s",
            rpc_provider,
            rpc_diag.get("source", "unknown"),
            rpc_host,
            extra={"context": {"rpc_provider": rpc_provider, "rpc_host": rpc_host}},
        )

        all_dexes = load_dexes()
        dex_configs = all_dexes.get(args.chain, {})
        token_addresses = get_all_token_addresses(args.chain)
        addr_to_symbol = _build_address_to_symbol(token_addresses)

        # Fetch real Swap events from chain
        raw_logs, current_block = fetch_recent_swap_events(
            rpc_url=rpc_url,
            blocks_back=args.live_blocks,
        )

        # Normalize logs into OrderflowEvents
        events = []
        for i, log in enumerate(raw_logs):
            ev = normalize_swap_log(
                log=log,
                addr_to_symbol=addr_to_symbol,
                token_addresses=token_addresses,
                dex_configs=dex_configs,
                event_index=i,
            )
            if ev is not None:
                events.append(ev)

        logger.info(
            "Normalized %d events from %d raw logs",
            len(events),
            len(raw_logs),
            extra={"context": {"normalized": len(events), "raw": len(raw_logs)}},
        )

        # Limit events to conserve RPC calls
        if len(events) > args.max_events:
            # Take largest events by estimated_size_usd
            events.sort(key=lambda e: e.estimated_size_usd, reverse=True)
            events = events[:args.max_events]
            logger.info("Truncated to %d largest events", len(events))

        # Score each event with live QuoterV2 quotes
        results = []
        for ev in events:
            r = score_backrun_live(
                event=ev,
                rpc_url=rpc_url,
                dex_configs=dex_configs,
                token_addresses=token_addresses,
                current_block=current_block,
            )
            results.append(r)

        artifact = build_replay_summary(events, results, mode="live_blocks")
        # Add M7.A.5 specific fields
        artifact["m7a5_hypothesis"] = (
            "block_event_backrun on arbitrum_one may produce viable measured edge "
            "when replay uses real block events and post-event live quotes"
        )
        artifact["live_blocks_scanned"] = args.live_blocks
        artifact["raw_logs_count"] = len(raw_logs)
        artifact["normalized_events_count"] = len(events)
        artifact["current_block"] = current_block
        # M7.A.5.2: Provider provenance (machine-readable)
        artifact["rpc_provider"] = rpc_provider
        artifact["rpc_source"] = rpc_diag.get("source", "unknown")
        artifact["resolved_rpc_host"] = rpc_host
        artifact["fallback_used"] = rpc_diag.get("source") == "public_fallback"
        # Live replay state metrics
        live_results = [r for r in results if r.event_block is not None]
        if live_results:
            artifact["live_state_metrics"] = {
                "events_with_block_data": len(live_results),
                "mean_block_lag": round(
                    sum(r.block_lag or 0 for r in live_results) / len(live_results), 2
                ),
                "same_block_count": sum(
                    1 for r in live_results if r.same_state_class == "same_block"
                ),
                "next_block_count": sum(
                    1 for r in live_results if r.same_state_class == "next_block"
                ),
                "stale_count": sum(
                    1 for r in live_results if r.same_state_class == "stale"
                ),
                "venues_quoted_max": max(r.counter_venue_count for r in live_results),
                "venues_quoted_mean": round(
                    sum(r.counter_venue_count for r in live_results) / len(live_results), 2
                ),
            }
            live_net = [r.best_live_net_bps for r in live_results if r.best_live_net_bps is not None]
            if live_net:
                artifact["live_state_metrics"]["best_live_net_bps"] = round(max(live_net), 4)
                artifact["live_state_metrics"]["worst_live_net_bps"] = round(min(live_net), 4)
                artifact["live_state_metrics"]["mean_live_net_bps"] = round(
                    sum(live_net) / len(live_net), 4
                )
            # M7.A.5.2: Low-lag subset metrics (same_block + next_block only)
            low_lag = [
                r for r in live_results
                if r.same_state_class in ("same_block", "next_block")
            ]
            low_lag_net = [
                r.best_live_net_bps for r in low_lag
                if r.best_live_net_bps is not None
            ]
            artifact["live_state_metrics"]["events_scored_low_lag"] = len(low_lag)
            artifact["live_state_metrics"]["best_live_net_bps_low_lag"] = (
                round(max(low_lag_net), 4) if low_lag_net else None
            )
    elif args.ws_live:
        # M7.A.5.3: WebSocket-triggered same-block/next-block replay
        logger.info(
            "Running M7.A.5.3 ws-live replay (ws_blocks=%d, ws_timeout=%ds)",
            args.ws_blocks,
            args.ws_timeout,
        )
        import os
        import time
        from urllib.parse import urlparse

        from config import load_dexes, get_all_token_addresses
        from core.rpc_urls import resolve_rpc_http, resolve_rpc_ws, _CHAIN_KEY_TO_ID

        chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())

        # Resolve HTTP RPC for quoting
        rpc_url, rpc_provider, rpc_diag = resolve_rpc_http(
            chain_id=chain_id,
            network=args.chain,
            env=dict(os.environ),
        )
        if not rpc_url:
            raise SystemExit(f"No HTTP RPC URL found for chain: {args.chain}")
        rpc_host = urlparse(rpc_url).netloc

        # Resolve WebSocket for newHeads subscription
        ws_url, ws_provider, ws_diag = resolve_rpc_ws(
            chain_id=chain_id,
            network=args.chain,
            env=dict(os.environ),
        )
        if not ws_url:
            raise SystemExit(
                f"No WebSocket RPC URL found for chain: {args.chain}. "
                "Set ALCHEMY_API_KEY or ALCHEMY_RPC_WS in .env"
            )
        ws_host = urlparse(ws_url).netloc

        logger.info(
            "RPC resolved: http=%s ws=%s ws_provider=%s",
            rpc_host,
            ws_host,
            ws_provider,
            extra={"context": {
                "rpc_provider": rpc_provider,
                "ws_provider": ws_provider,
                "rpc_host": rpc_host,
                "ws_host": ws_host,
            }},
        )

        all_dexes = load_dexes()
        dex_configs = all_dexes.get(args.chain, {})
        token_addresses = get_all_token_addresses(args.chain)
        addr_to_symbol = _build_address_to_symbol(token_addresses)

        # Load block_time_ms from chains.yaml for latency budget
        from config import load_chains
        chain_cfg = load_chains().get(args.chain, {})
        block_time_ms = chain_cfg.get("block_time_ms", 250)

        # Subscribe to newHeads via WebSocket and process blocks
        import websocket as ws_mod

        all_events = []
        all_results = []
        blocks_processed = 0
        raw_logs_total = 0
        ws_start_time = time.monotonic()

        try:
            ws_conn = ws_mod.create_connection(ws_url, timeout=10)
            # Subscribe to newHeads
            sub_msg = json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_subscribe",
                "params": ["newHeads"],
            })
            ws_conn.send(sub_msg)
            sub_response = ws_conn.recv()
            sub_data = json.loads(sub_response)
            sub_id = sub_data.get("result")
            if not sub_id:
                raise RuntimeError(f"WebSocket subscription failed: {sub_data}")
            logger.info(
                "WebSocket newHeads subscribed: sub_id=%s",
                sub_id,
                extra={"context": {"ws_url": ws_host, "sub_id": sub_id}},
            )

            ws_conn.settimeout(args.ws_timeout)

            while blocks_processed < args.ws_blocks:
                elapsed = time.monotonic() - ws_start_time
                if elapsed > args.ws_timeout:
                    logger.info("ws-live timeout reached (%ds)", args.ws_timeout)
                    break

                try:
                    msg = ws_conn.recv()
                except Exception:
                    logger.info("WebSocket recv timeout or error after %d blocks", blocks_processed)
                    break

                data = json.loads(msg)
                params = data.get("params", {})
                result = params.get("result", {})
                block_hex = result.get("number")
                if not block_hex:
                    continue  # Not a newHead notification

                detected_block = int(block_hex, 16)
                blocks_processed += 1
                logger.info(
                    "newHead #%d: block=%d (processed %d/%d)",
                    detected_block,
                    detected_block,
                    blocks_processed,
                    args.ws_blocks,
                    extra={"context": {"block": detected_block}},
                )

                # Fetch swap logs for THIS block only (single-block window)
                from web3 import Web3
                w3 = Web3(Web3.HTTPProvider(rpc_url))
                try:
                    logs = w3.eth.get_logs({
                        "fromBlock": detected_block,
                        "toBlock": detected_block,
                        "topics": [SWAP_EVENT_TOPIC],
                    })
                except Exception as exc:
                    logger.debug(
                        "Failed to fetch logs for block %d: %s",
                        detected_block,
                        str(exc)[:100],
                    )
                    continue

                raw_logs_total += len(logs)
                if not logs:
                    continue

                # Normalize logs
                block_events = []
                for i, log_entry in enumerate(logs):
                    ev = normalize_swap_log(
                        log=log_entry,
                        addr_to_symbol=addr_to_symbol,
                        token_addresses=token_addresses,
                        dex_configs=dex_configs,
                        event_index=i,
                    )
                    if ev is not None:
                        block_events.append(ev)

                if not block_events:
                    continue

                # Sort by size, take up to max_events per block
                block_events.sort(key=lambda e: e.estimated_size_usd, reverse=True)
                events_to_score = block_events[:max(1, args.max_events // args.ws_blocks)]

                # Score with parallel pipeline
                current_block = detected_block
                for ev in events_to_score:
                    r = score_backrun_live_parallel(
                        event=ev,
                        rpc_url=rpc_url,
                        dex_configs=dex_configs,
                        token_addresses=token_addresses,
                        current_block=current_block,
                        ws_provider=ws_provider,
                        event_detected_at_block=detected_block,
                        fallback_rpc_urls=None,
                        block_time_ms=block_time_ms,
                    )
                    all_results.append(r)
                    all_events.append(ev)

                    if len(all_results) >= args.max_events:
                        break

                if len(all_results) >= args.max_events:
                    logger.info("max_events reached (%d), stopping", args.max_events)
                    break

        except Exception as exc:
            logger.warning(
                "WebSocket error: %s (scored %d events from %d blocks)",
                str(exc)[:200],
                len(all_results),
                blocks_processed,
            )
        finally:
            try:
                ws_conn.close()
            except Exception:
                pass

        ws_elapsed = time.monotonic() - ws_start_time

        # Build artifact
        artifact = build_replay_summary(all_events, all_results, mode="ws_live")
        artifact["m7a53_hypothesis"] = (
            "block_event_backrun on arbitrum_one may only be fairly testable "
            "with websocket-triggered same-block/next-block replay"
        )
        artifact["ws_live_config"] = {
            "ws_blocks_requested": args.ws_blocks,
            "ws_timeout_seconds": args.ws_timeout,
            "max_events": args.max_events,
        }
        artifact["ws_live_stats"] = {
            "blocks_processed": blocks_processed,
            "raw_logs_total": raw_logs_total,
            "normalized_events": len(all_events),
            "events_scored": len(all_results),
            "ws_elapsed_seconds": round(ws_elapsed, 2),
        }
        # Provider provenance
        artifact["rpc_provider"] = rpc_provider
        artifact["rpc_source"] = rpc_diag.get("source", "unknown")
        artifact["resolved_rpc_host"] = rpc_host
        artifact["ws_provider"] = ws_provider
        artifact["ws_source"] = ws_diag.get("source", "unknown")
        artifact["resolved_ws_host"] = ws_host
        artifact["fallback_used"] = rpc_diag.get("source") == "public_fallback"

        # Live state metrics
        live_results = [r for r in all_results if r.event_block is not None]
        if live_results:
            artifact["live_state_metrics"] = {
                "events_with_block_data": len(live_results),
                "mean_block_lag": round(
                    sum(r.block_lag or 0 for r in live_results) / len(live_results), 2
                ),
                "same_block_count": sum(
                    1 for r in live_results if r.same_state_class == "same_block"
                ),
                "next_block_count": sum(
                    1 for r in live_results if r.same_state_class == "next_block"
                ),
                "stale_count": sum(
                    1 for r in live_results if r.same_state_class == "stale"
                ),
                "venues_quoted_max": max(r.counter_venue_count for r in live_results) if live_results else 0,
                "venues_quoted_mean": round(
                    sum(r.counter_venue_count for r in live_results) / len(live_results), 2
                ),
                "mean_pipeline_latency_ms": round(
                    sum(r.quote_pipeline_latency_ms or 0 for r in live_results) / len(live_results), 2
                ),
                "total_venues_pruned_by_multicall": sum(
                    r.venues_pruned_by_multicall for r in live_results
                ),
            }
            live_net = [r.best_live_net_bps for r in live_results if r.best_live_net_bps is not None]
            if live_net:
                artifact["live_state_metrics"]["best_live_net_bps"] = round(max(live_net), 4)
                artifact["live_state_metrics"]["worst_live_net_bps"] = round(min(live_net), 4)
                artifact["live_state_metrics"]["mean_live_net_bps"] = round(
                    sum(live_net) / len(live_net), 4
                )
            # Low-lag subset metrics (ws-specific: should have more than polling)
            low_lag = [
                r for r in live_results
                if r.same_state_class in ("same_block", "next_block")
            ]
            low_lag_net = [
                r.best_live_net_bps for r in low_lag
                if r.best_live_net_bps is not None
            ]
            artifact["live_state_metrics"]["events_scored_low_lag_ws"] = len(low_lag)
            artifact["live_state_metrics"]["best_live_net_bps_low_lag_ws"] = (
                round(max(low_lag_net), 4) if low_lag_net else None
            )
            artifact["live_state_metrics"]["events_scored_low_lag"] = len(low_lag)
            artifact["live_state_metrics"]["best_live_net_bps_low_lag"] = (
                round(max(low_lag_net), 4) if low_lag_net else None
            )

            # M7.A.5.3.1 — Latency budget metrics (relative to chain block_time_ms)
            pipeline_latencies = [
                r.quote_pipeline_latency_ms for r in live_results
                if r.quote_pipeline_latency_ms is not None
            ]
            budget_hits = [
                lat for lat in pipeline_latencies if lat < block_time_ms
            ]
            artifact["live_state_metrics"]["latency_budget_ms"] = block_time_ms
            artifact["live_state_metrics"]["latency_budget_hit_rate"] = (
                round(len(budget_hits) / len(pipeline_latencies), 4)
                if pipeline_latencies else 0.0
            )
            artifact["live_state_metrics"]["sub_block_capable"] = len(budget_hits) > 0

            # M7.A.5.3.1 — Separate low-lag vs stale summaries
            stale = [
                r for r in live_results
                if r.same_state_class == "stale"
            ]
            stale_net = [
                r.best_live_net_bps for r in stale
                if r.best_live_net_bps is not None
            ]
            artifact["ws_low_lag_summary"] = {
                "count": len(low_lag),
                "best_net_bps": round(max(low_lag_net), 4) if low_lag_net else None,
                "worst_net_bps": round(min(low_lag_net), 4) if low_lag_net else None,
                "mean_net_bps": (
                    round(sum(low_lag_net) / len(low_lag_net), 4)
                    if low_lag_net else None
                ),
                "same_block_count": sum(
                    1 for r in low_lag if r.same_state_class == "same_block"
                ),
                "next_block_count": sum(
                    1 for r in low_lag if r.same_state_class == "next_block"
                ),
                "mean_pipeline_latency_ms": (
                    round(
                        sum(r.quote_pipeline_latency_ms or 0 for r in low_lag)
                        / len(low_lag), 2
                    ) if low_lag else None
                ),
                "viable_count": sum(1 for r in low_lag if r.route_viable),
            }
            artifact["ws_stale_summary"] = {
                "count": len(stale),
                "best_net_bps": round(max(stale_net), 4) if stale_net else None,
                "worst_net_bps": round(min(stale_net), 4) if stale_net else None,
                "mean_net_bps": (
                    round(sum(stale_net) / len(stale_net), 4)
                    if stale_net else None
                ),
                "mean_block_lag": (
                    round(
                        sum(r.block_lag or 0 for r in stale) / len(stale), 2
                    ) if stale else None
                ),
                "mean_pipeline_latency_ms": (
                    round(
                        sum(r.quote_pipeline_latency_ms or 0 for r in stale)
                        / len(stale), 2
                    ) if stale else None
                ),
                "viable_count": sum(1 for r in stale if r.route_viable),
            }
    else:
        parser_err = "No mode specified"
        raise SystemExit(parser_err)

    output_json = json.dumps(artifact, indent=2, default=str)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        logger.info("Artifact written to %s", out_path)
    else:
        print(output_json)

    # Summary log
    if "results_count" in artifact:
        logger.info(
            "Replay complete: %d events, %d viable, best_net=%.4f bps",
            artifact["events_count"],
            artifact["viable_count"],
            artifact.get("best_net_bps") or 0.0,
            extra={"context": {
                "mode": artifact.get("mode"),
                "viable": artifact["viable_count"],
                "best_net_bps": artifact.get("best_net_bps"),
            }},
        )
    else:
        logger.info(
            "Scout complete: %d surfaces assessed, best_near_term=%s",
            artifact.get("surfaces_assessed", 0),
            artifact.get("best_near_term", "none"),
        )


if __name__ == "__main__":
    main()
