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
REJECT_QUOTE_FAILURE = "QUOTE_FAILURE"  # legacy — kept for backward compat
REJECT_INSUFFICIENT_IMPACT = "INSUFFICIENT_IMPACT"
REJECT_TOKEN_PAIR_UNRESOLVED = "TOKEN_PAIR_UNRESOLVED"
# M7.A.5.6: Split QUOTE_FAILURE into granular sub-reasons
REJECT_NO_COUNTER_POOL = "NO_COUNTER_POOL"  # resolved pair has no counter-venue pool
REJECT_TOKEN_NOT_ADMITTED = "TOKEN_NOT_ADMITTED"  # event token outside any known universe
REJECT_UNSUPPORTED_ADAPTER = "UNSUPPORTED_ADAPTER"  # no adapter can quote this pair
REJECT_RPC_QUOTE_FAIL = "RPC_QUOTE_FAIL"  # quoter call failed (RPC/timeout)
REJECT_PAIR_RESOLVED_UNTRADEABLE = "PAIR_RESOLVED_BUT_UNTRADEABLE"  # pair resolved, coverage checked, no viable route

ALL_REJECT_REASONS = frozenset({
    REJECT_NO_COUNTER_VENUE,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_EVENT_TOO_SMALL,
    REJECT_SAME_BLOCK_IMPOSSIBLE,
    REJECT_QUOTE_FAILURE,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    REJECT_NO_COUNTER_POOL,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
})

# ---------------------------------------------------------------------------
# M7.A.5.7: Admission source tracking
# ---------------------------------------------------------------------------
ADMISSION_CANONICAL = "canonical_core"
ADMISSION_ADDR_TO_SYMBOL = "addr_to_symbol"
ADMISSION_SUBGRAPH_VERIFIED = "subgraph_seeded_verified"
ADMISSION_REJECTED = "rejected_unverified"
ALL_ADMISSION_SOURCES = frozenset({
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_SUBGRAPH_VERIFIED,
    ADMISSION_REJECTED,
})

# ---------------------------------------------------------------------------
# M7.A.5.7: Chainlink price feed addresses on Arbitrum One (USD, 8 decimals)
# ---------------------------------------------------------------------------
CHAINLINK_FEEDS_ARBITRUM: Dict[str, str] = {
    "WETH": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
    "WBTC": "0x6ce185860a4963106506C203335A2910413708e9",
    "USDT": "0x3f3f5dF88dC9F13eac63DF89EC16ef6e7E25DdE7",
    "USDC": "0x50834F3163758fcC1Df9973b6e91f0F0F0434aD3",
    "ARB": "0xb2A824043730FE05F3DA2efaFa1CBbe83fa548D6",
    "LINK": "0x86E53CF1B870786351Da77A57575e79CB55812CB",
    "DAI": "0xc5C8E77B397E531B8EC06BFb0048328B30E9eCfB",
    "UNI": "0x9C917083fDb403ab5ADbEC26Ee294f6EcAda7Fee",
    "GMX": "0xDB98056FecFff59D032aB628337A4887110df3dB",
    "PENDLE": "0x66853E19d73c0F9301fe99c324C1ba0bb3f51b01",
}
CHAINLINK_LATEST_ROUND_SELECTOR = "0xfeaf968c"  # latestRoundData()
CHAINLINK_DECIMALS = 8  # USD feeds return 8-decimal answer

# ---------------------------------------------------------------------------
# M7.A.5.8: Subgraph-backed coverage seed endpoints (The Graph, Arbitrum One)
# ---------------------------------------------------------------------------
# These are public subgraph endpoints for supported DEX families on Arbitrum.
# Used ONLY as token-symbol seed (not as price truth or execution source).
SUBGRAPH_ENDPOINTS_ARBITRUM: Dict[str, str] = {
    "uniswap_v3": "https://gateway.thegraph.com/api/subgraphs/id/5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
    "sushiswap_v3": "https://gateway.thegraph.com/api/subgraphs/id/B2o157JTLbHpqy2MFga4HPrv46RTGiB3FWBQk6SwNkrR",
}
# Cap on tokens seeded from subgraph (bounded discovery)
SUBGRAPH_SEED_TOKEN_CAP = 50
# Timeout for subgraph HTTP requests
SUBGRAPH_TIMEOUT_SECONDS = 10

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
    # M7.A.5.4 two-stage pruning fields (None for non-ws and offline modes)
    quote_calls_attempted: Optional[int] = None
    quote_calls_after_pruning: Optional[int] = None
    prune_reason_histogram: Optional[Dict[str, int]] = None
    pipeline_stage_latency_ms: Optional[Dict[str, float]] = None
    # M7.A.5.5 actual-pair resolution fields
    pair_resolved: bool = False  # True if token0/token1 resolved from pool contract
    actual_pair: Optional[str] = None  # e.g. "WETH/USDC" — None if unresolved
    size_source: Optional[str] = None  # "event_proportional" | "fixed_fallback"
    # M7.A.5.6 coverage scan + size sweep fields
    coverage_result: Optional[Dict[str, Any]] = None  # counter_venue_coverage_scan() output
    size_sweep_results: Optional[List[Dict[str, Any]]] = None  # bounded size sweep ladder
    best_sweep_net_bps: Optional[float] = None  # best net across sweep sizes
    best_sweep_size_wei: Optional[int] = None  # size that produced best_sweep_net_bps
    token_admitted: Optional[bool] = None  # True if event tokens in admitted universe
    # M7.A.5.7 coverage enrichment + oracle guard + local-sim fields
    admission_source: Optional[str] = None  # canonical_core | addr_to_symbol | subgraph_seeded_verified | rejected_unverified
    oracle_guard: Optional[Dict[str, Any]] = None  # Chainlink sanity check result
    local_sim_state: Optional[Dict[str, Any]] = None  # V3 pool state for future local pricing
    # M7.A.5.8 gas decomposition + subgraph seed fields
    l2_gas_bps: Optional[float] = None  # L2 execution gas cost in bps
    l1_data_bps: Optional[float] = None  # L1 data posting cost in bps
    total_gas_bps: Optional[float] = None  # l2_gas_bps + l1_data_bps
    subgraph_seed_used: Optional[bool] = None  # Whether subgraph seed contributed to admission


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
# M7.A.5.5: Actual-pair token resolution from pool contracts
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# M7.A.5.3: Parallel live scoring with multicall-assisted venue pruning
# ---------------------------------------------------------------------------

_DEFAULT_FEE_TIERS = [500, 3000, 10000]


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

    # Collect non-None addresses for liquidity check
    valid_addrs = [a for a in pool_addrs if a is not None]
    liq_map: Dict[str, Optional[int]] = {}
    if valid_addrs:
        liq_map = batcher.batch_liquidity(valid_addrs)

    # Build result grouped by dex
    result: Dict[str, List[Dict[str, Any]]] = {}
    for i, addr in enumerate(pool_addrs):
        dex_name, fee = query_meta[i]
        entry = {
            "address": addr,
            "fee": fee,
            "liquidity": liq_map.get(addr) if addr else None,
        }
        result.setdefault(dex_name, []).append(entry)

    return result


# ---------------------------------------------------------------------------
# M7.A.5.6: Event-token admission + coverage scan + size sweep
# ---------------------------------------------------------------------------


def admit_event_tokens(
    token_in_addr: str,
    token_out_addr: str,
    addr_to_symbol: Dict[str, str],
    canonical_token_addrs: Dict[str, str],
) -> Dict[str, Any]:
    """Check whether event tokens are admissible for quoting.

    A token is 'admitted' if its address maps to a known symbol in
    canonical_token_addrs OR in addr_to_symbol.  This allows temporary
    admission of tokens resolved from pool contracts even if they are
    not in the canonical narrow universe.

    M7.A.5.7: Returns admission_source to disambiguate how tokens were admitted.

    Returns dict with:
        admitted: bool
        token_in_symbol: str or None
        token_out_symbol: str or None
        token_in_known: bool   # in canonical universe
        token_out_known: bool
        blocker_reason: str or None
        admission_source: str  # canonical_core | addr_to_symbol | subgraph_seeded_verified | rejected_unverified
    """
    reverse_canonical = {v.lower(): k for k, v in canonical_token_addrs.items() if v}
    in_sym = addr_to_symbol.get(token_in_addr.lower()) or reverse_canonical.get(token_in_addr.lower())
    out_sym = addr_to_symbol.get(token_out_addr.lower()) or reverse_canonical.get(token_out_addr.lower())
    in_known = token_in_addr.lower() in reverse_canonical
    out_known = token_out_addr.lower() in reverse_canonical

    # Admitted if we have ANY symbol mapping (even truncated addr fallback is NOT admitted)
    in_admitted = in_sym is not None and len(in_sym) > 10  # truncated addrs are <=10
    out_admitted = out_sym is not None and len(out_sym) > 10
    # But canonical tokens are always admitted regardless of symbol length
    if in_known:
        in_admitted = True
    if out_known:
        out_admitted = True
    # Also admit if addr_to_symbol returned a real symbol (not a truncated address)
    if in_sym and not in_sym.startswith("0x"):
        in_admitted = True
    if out_sym and not out_sym.startswith("0x"):
        out_admitted = True

    admitted = in_admitted and out_admitted
    blocker = None
    if not in_admitted and not out_admitted:
        blocker = "both_tokens_unknown"
    elif not in_admitted:
        blocker = "token_in_unknown"
    elif not out_admitted:
        blocker = "token_out_unknown"

    # M7.A.5.7: Determine admission source
    if not admitted:
        admission_source = ADMISSION_REJECTED
    elif in_known and out_known:
        admission_source = ADMISSION_CANONICAL
    elif in_known or out_known:
        # One canonical, one from addr_to_symbol mapping
        admission_source = ADMISSION_ADDR_TO_SYMBOL
    else:
        # Both from addr_to_symbol (e.g. subgraph-seeded tokens verified on-chain)
        admission_source = ADMISSION_ADDR_TO_SYMBOL

    return {
        "admitted": admitted,
        "token_in_symbol": in_sym,
        "token_out_symbol": out_sym,
        "token_in_known": in_known,
        "token_out_known": out_known,
        "blocker_reason": blocker,
        "admission_source": admission_source,
    }


def counter_venue_coverage_scan(
    token_in_addr: str,
    token_out_addr: str,
    dex_configs: Dict[str, Any],
    rpc_url: str,
    block_num: int,
) -> Dict[str, Any]:
    """Scan counter-venue coverage for a resolved token pair.

    Uses multicall to check which DEXes have deployed pools with liquidity
    for the given pair.

    Returns machine-readable truth block:
        known_pools: int         # pools found via factory.getPool
        known_dexes: list[str]   # DEX names with at least one live pool
        buy_venues: int          # venues with quoter that could quote buy
        sell_venues: int         # venues with quoter that could quote sell
        coverage_complete: bool  # at least 1 buy + 1 sell venue
        coverage_blocker_reason: str or None
    """
    pool_map = _resolve_pool_addresses_multicall(
        dex_configs, token_in_addr, token_out_addr, rpc_url, block_num,
    )

    known_pools = 0
    known_dexes: List[str] = []
    buy_venues = 0
    sell_venues = 0

    for dex_name, pools in pool_map.items():
        dex_has_pool = False
        for p in pools:
            if p["address"] is not None:
                liq = p["liquidity"]
                if liq is None or liq > 0:
                    known_pools += 1
                    dex_has_pool = True
        if dex_has_pool:
            known_dexes.append(dex_name)

    # Check which have quoter for buy/sell
    for dex_name in known_dexes:
        cfg = dex_configs.get(dex_name, {})
        quoter = cfg.get("quoter_v2") or cfg.get("quoter")
        if quoter:
            buy_venues += 1
            sell_venues += 1  # same quoter can do both directions

    coverage_complete = buy_venues >= 1 and sell_venues >= 1
    blocker = None
    if known_pools == 0:
        blocker = "no_pools_found"
    elif buy_venues == 0 and sell_venues == 0:
        blocker = "no_quoter_for_live_pools"
    elif buy_venues == 0:
        blocker = "no_buy_venue"
    elif sell_venues == 0:
        blocker = "no_sell_venue"

    return {
        "known_pools": known_pools,
        "known_dexes": known_dexes,
        "buy_venues": buy_venues,
        "sell_venues": sell_venues,
        "coverage_complete": coverage_complete,
        "coverage_blocker_reason": blocker,
    }


# ---------------------------------------------------------------------------
# M7.A.5.7: On-chain token enrichment
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# M7.A.5.7: Chainlink oracle sanity guard
# ---------------------------------------------------------------------------

def check_oracle_sanity(
    token_in_symbol: Optional[str],
    token_out_symbol: Optional[str],
    rpc_url: str,
    block_num: int,
) -> Dict[str, Any]:
    """Check Chainlink price feeds as sanity guardrail (not execution truth).

    Returns dict with:
        oracle_price_available: bool
        token_in_oracle_usd: float or None
        token_out_oracle_usd: float or None
        oracle_deviation_bps: float or None  (cross-check between tokens)
        oracle_guard_triggered: bool
        oracle_staleness_seconds: int or None
    """
    import time as _time

    result: Dict[str, Any] = {
        "oracle_price_available": False,
        "token_in_oracle_usd": None,
        "token_out_oracle_usd": None,
        "oracle_deviation_bps": None,
        "oracle_guard_triggered": False,
        "oracle_staleness_seconds": None,
    }

    feed_in = CHAINLINK_FEEDS_ARBITRUM.get(token_in_symbol or "") if token_in_symbol else None
    feed_out = CHAINLINK_FEEDS_ARBITRUM.get(token_out_symbol or "") if token_out_symbol else None

    if not feed_in and not feed_out:
        return result

    try:
        from core.multicall import get_multicall_batcher
        from web3 import Web3

        batcher = get_multicall_batcher(rpc_url, block_num)
        calls = []
        feed_addrs = []
        if feed_in:
            feed_addrs.append(("in", feed_in))
            calls.append((
                Web3.to_checksum_address(feed_in),
                True,
                bytes.fromhex(CHAINLINK_LATEST_ROUND_SELECTOR[2:]),
            ))
        if feed_out:
            feed_addrs.append(("out", feed_out))
            calls.append((
                Web3.to_checksum_address(feed_out),
                True,
                bytes.fromhex(CHAINLINK_LATEST_ROUND_SELECTOR[2:]),
            ))

        multicall_results = batcher._execute_multicall(calls)
        if multicall_results is None:
            return result

        now_ts = int(_time.time())
        prices: Dict[str, float] = {}
        staleness: Dict[str, int] = {}
        for i, (side, _feed_addr) in enumerate(feed_addrs):
            success, data = multicall_results[i]
            if success and len(data) >= 160:
                # latestRoundData returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
                answer = int.from_bytes(data[32:64], "big", signed=True)
                updated_at = int.from_bytes(data[96:128], "big")
                price_usd = answer / (10 ** CHAINLINK_DECIMALS)
                if price_usd > 0:
                    prices[side] = price_usd
                    staleness[side] = max(0, now_ts - updated_at)

        if "in" in prices:
            result["token_in_oracle_usd"] = round(prices["in"], 6)
        if "out" in prices:
            result["token_out_oracle_usd"] = round(prices["out"], 6)

        result["oracle_price_available"] = bool(prices)

        if staleness:
            result["oracle_staleness_seconds"] = max(staleness.values())

        # Cross-check: if both prices available, compute implied exchange rate deviation
        # The oracle guard triggers if staleness > 1 hour (feeds stale)
        MAX_STALENESS_SECONDS = 3600
        if result["oracle_staleness_seconds"] and result["oracle_staleness_seconds"] > MAX_STALENESS_SECONDS:
            result["oracle_guard_triggered"] = True

    except Exception as exc:
        logger.debug("check_oracle_sanity failed: %s", str(exc)[:100])

    return result


# ---------------------------------------------------------------------------
# M7.A.5.7: Local-sim pool state extraction
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# M7.A.5.8: Subgraph-backed bounded coverage seed
# ---------------------------------------------------------------------------

def seed_tokens_from_subgraph(
    existing_addr_to_symbol: Dict[str, str],
    rpc_url: str,
    block_num: int,
    chain: str = "arbitrum_one",
) -> Dict[str, Any]:
    """Seed addr_to_symbol with top tokens from supported DEX subgraphs.

    Queries The Graph for the top tokens (by tx count) from Uniswap V3 and
    SushiSwap V3 subgraphs on Arbitrum. For each new token found, verifies
    symbol + decimals on-chain via multicall before adding to addr_to_symbol.

    This is a bounded coverage enrichment — NOT a price oracle.

    Args:
        existing_addr_to_symbol: Current addr→symbol mapping (will be mutated)
        rpc_url: HTTP RPC URL for on-chain verification
        block_num: Block number for multicall context
        chain: Chain key (only arbitrum_one supported)

    Returns dict with:
        tokens_discovered: int (from subgraph queries)
        tokens_new: int (not already in addr_to_symbol)
        tokens_verified: int (verified on-chain and added)
        tokens_failed_verification: int
        sources_queried: list[str]
        errors: list[str]
    """
    import urllib.request
    import urllib.error

    stats: Dict[str, Any] = {
        "tokens_discovered": 0,
        "tokens_new": 0,
        "tokens_verified": 0,
        "tokens_failed_verification": 0,
        "sources_queried": [],
        "errors": [],
    }

    if chain != "arbitrum_one":
        stats["errors"].append(f"subgraph seed not supported for chain: {chain}")
        return stats

    # GraphQL query: top tokens by txCount (bounded)
    query = """
    {
      tokens(first: %d, orderBy: txCount, orderDirection: desc) {
        id
        symbol
        decimals
      }
    }
    """ % SUBGRAPH_SEED_TOKEN_CAP

    candidate_tokens: Dict[str, str] = {}  # addr_lower → symbol

    for dex_name, endpoint in SUBGRAPH_ENDPOINTS_ARBITRUM.items():
        try:
            payload = json.dumps({"query": query}).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=SUBGRAPH_TIMEOUT_SECONDS) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            tokens_data = body.get("data", {}).get("tokens", [])
            stats["sources_queried"].append(dex_name)
            for t in tokens_data:
                addr = t.get("id", "").lower()
                sym = t.get("symbol", "")
                if addr and sym and len(sym) <= 20 and not sym.startswith("0x"):
                    candidate_tokens[addr] = sym
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            stats["errors"].append(f"{dex_name}: {str(exc)[:80]}")
        except Exception as exc:
            stats["errors"].append(f"{dex_name}: {str(exc)[:80]}")

    stats["tokens_discovered"] = len(candidate_tokens)

    # Filter to tokens not already known
    new_tokens = {
        addr: sym for addr, sym in candidate_tokens.items()
        if addr not in existing_addr_to_symbol
    }
    stats["tokens_new"] = len(new_tokens)

    if not new_tokens:
        return stats

    # Verify on-chain via multicall (symbol + decimals)
    addrs_to_verify = list(new_tokens.keys())[:SUBGRAPH_SEED_TOKEN_CAP]
    try:
        verified = enrich_tokens_batch(addrs_to_verify, rpc_url, block_num)
        for addr, info in verified.items():
            if info["enriched"] and info["symbol"]:
                existing_addr_to_symbol[addr] = info["symbol"]
                stats["tokens_verified"] += 1
            else:
                stats["tokens_failed_verification"] += 1
    except Exception as exc:
        stats["errors"].append(f"verification: {str(exc)[:80]}")
        stats["tokens_failed_verification"] = len(addrs_to_verify)

    return stats


def estimate_gas_decomposition_bps(
    amount_in_wei: int,
    gas_cost_wei: int,
) -> Dict[str, float]:
    """Decompose gas cost into L2 execution and L1 data posting components.

    On Arbitrum, total gas cost ≈ L2 execution (~20%) + L1 data (~80%).
    Uses Arbitrum canonical split ratio from Nitro whitepaper.

    Returns:
        l2_gas_bps: L2 execution gas in bps of amount_in
        l1_data_bps: L1 data posting gas in bps of amount_in
        total_gas_bps: Total gas cost in bps of amount_in
    """
    if amount_in_wei <= 0 or gas_cost_wei <= 0:
        return {"l2_gas_bps": 0.0, "l1_data_bps": 0.0, "total_gas_bps": 0.0}

    total_bps = gas_cost_wei / amount_in_wei * 10000
    # Arbitrum Nitro: L1 data posting dominates (~80% of gas cost for typical txs)
    L1_DATA_RATIO = 0.80
    l1_bps = round(total_bps * L1_DATA_RATIO, 4)
    l2_bps = round(total_bps * (1 - L1_DATA_RATIO), 4)
    return {
        "l2_gas_bps": l2_bps,
        "l1_data_bps": l1_bps,
        "total_gas_bps": round(total_bps, 4),
    }


def _run_size_sweep(
    event: OrderflowEvent,
    rpc_url: str,
    token_in_addr: str,
    token_out_addr: str,
    quotable_dexes: list,
    base_size_wei: int,
    fallback_rpc_urls: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Run a bounded size sweep (3-5 sizes) around a base notional.

    Returns list of dicts with: size_wei, gross_pnl_wei, gas_cost_wei,
    net_pnl_wei, net_bps, buy_venue, sell_venue.
    """
    from strategy.quote_rpc import read_quoter_v2, QUOTER_RATE_LIMITED

    # Build 5-point ladder: 0.2x, 0.5x, 1x, 2x, 5x of base
    multipliers = [0.2, 0.5, 1.0, 2.0, 5.0]
    MIN_WEI = 10**15   # 0.001 ETH
    MAX_WEI = 10**18   # 1.0 ETH
    sizes = []
    for m in multipliers:
        s = int(base_size_wei * m)
        s = max(MIN_WEI, min(MAX_WEI, s))
        sizes.append(s)
    # Deduplicate (e.g. if clamped to same min/max)
    sizes = sorted(set(sizes))

    results: List[Dict[str, Any]] = []

    for size_wei in sizes:
        # Quick single-pass: best buy then best sell
        best_buy_amt = None
        best_buy_venue = None
        for dex_name, cfg, quoter_addr in quotable_dexes:
            fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
            for fee in fee_tiers[:2]:
                try:
                    res = read_quoter_v2(
                        quoter_address=quoter_addr,
                        token_in=token_in_addr,
                        token_out=token_out_addr,
                        amount_in=size_wei,
                        fee=fee,
                        rpc_url=rpc_url,
                        block_num="latest",
                        fallback_rpc_urls=fallback_rpc_urls,
                    )
                    if res and res is not QUOTER_RATE_LIMITED:
                        amt = res.get("amount_out", 0)
                        if amt > 0 and (best_buy_amt is None or amt > best_buy_amt):
                            best_buy_amt = amt
                            best_buy_venue = dex_name
                except Exception:
                    pass

        if best_buy_amt is None:
            results.append({
                "size_wei": size_wei,
                "gross_pnl_wei": 0,
                "gas_cost_wei": 0,
                "net_pnl_wei": 0,
                "net_bps": 0.0,
                "buy_venue": None,
                "sell_venue": None,
            })
            continue

        best_sell_amt = None
        best_sell_venue = None
        for dex_name, cfg, quoter_addr in quotable_dexes:
            fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
            for fee in fee_tiers[:2]:
                try:
                    res = read_quoter_v2(
                        quoter_address=quoter_addr,
                        token_in=token_out_addr,
                        token_out=token_in_addr,
                        amount_in=best_buy_amt,
                        fee=fee,
                        rpc_url=rpc_url,
                        block_num="latest",
                        fallback_rpc_urls=fallback_rpc_urls,
                    )
                    if res and res is not QUOTER_RATE_LIMITED:
                        amt = res.get("amount_out", 0)
                        if amt > 0 and (best_sell_amt is None or amt > best_sell_amt):
                            best_sell_amt = amt
                            best_sell_venue = dex_name
                except Exception:
                    pass

        if best_sell_amt is None:
            results.append({
                "size_wei": size_wei,
                "gross_pnl_wei": 0,
                "gas_cost_wei": 0,
                "net_pnl_wei": 0,
                "net_bps": 0.0,
                "buy_venue": best_buy_venue,
                "sell_venue": None,
            })
            continue

        gross_wei = best_sell_amt - size_wei
        gas_cost_wei = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)
        net_wei = gross_wei - gas_cost_wei
        net_bps = (net_wei / size_wei) * 10000 if size_wei > 0 else 0.0

        results.append({
            "size_wei": size_wei,
            "gross_pnl_wei": gross_wei,
            "gas_cost_wei": gas_cost_wei,
            "net_pnl_wei": net_wei,
            "net_bps": round(net_bps, 4),
            "buy_venue": best_buy_venue,
            "sell_venue": best_sell_venue,
        })

    return results


def _get_pool_addresses_for_dexes(
    dex_configs: Dict[str, Any],
    token_in_addr: str,
    token_out_addr: str,
) -> List[str]:
    """Legacy shim — returns empty. Actual resolution now uses
    _resolve_pool_addresses_multicall() in the 2-stage pipeline.
    """
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
    addr_to_symbol: Optional[Dict[str, str]] = None,
    subgraph_seeded_addrs: Optional[set] = None,
) -> BackrunResult:
    """Score a backrun using 3-stage pipeline: pair resolve + coverage scan + quote.

    M7.A.5.6: Adds event-token admission, counter-venue coverage scan,
    bounded size sweep, and split reject reasons.

    Stage A (cheap): Resolve pool tokens + admission check + coverage scan.
    Stage B (multicall): batch factory.getPool() + liquidity() via multicall.
        Prune venues with no pool or zero liquidity.
    Stage C (confirmatory): read_quoter_v2() only for shortlisted venues,
        with bounded size sweep (3-5 sizes).
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from strategy.quote_rpc import read_quoter_v2, QUOTER_RATE_LIMITED

    pipeline_start = time.monotonic()
    backrun_dir = classify_event_backrun_type(event)

    quote_started_block = current_block

    # Common early-exit builder for rejected results
    def _reject(reason, pr=False, ap=None, ss=None, cov=None, adm=None,
                adm_src=None, orc=None, lss=None, sg_seed=None,
                extra_latency=None):
        return BackrunResult(
            event_id=event.event_id,
            event_source="live",
            event_type=event.event_type,
            post_trade_state_used="live",
            backrun_direction=backrun_dir,
            reject_reason=reason,
            event_block=event.block_number,
            quote_block=current_block,
            block_lag=current_block - event.block_number,
            ws_provider=ws_provider,
            event_detected_at_block=event_detected_at_block,
            quote_started_block=quote_started_block,
            quote_finished_block=current_block,
            quote_pipeline_latency_ms=round(
                (time.monotonic() - pipeline_start) * 1000, 2
            ),
            latency_budget_ms=block_time_ms,
            pair_resolved=pr,
            actual_pair=ap,
            size_source=ss,
            coverage_result=cov,
            token_admitted=adm,
            admission_source=adm_src,
            oracle_guard=orc,
            local_sim_state=lss,
            subgraph_seed_used=sg_seed,
        )

    # ── Stage A: Actual-pair token resolution ───────────────────────────
    pair_resolved = False
    actual_pair: Optional[str] = None
    size_source = "event_proportional"

    token_in_addr = token_addresses.get(event.token_out, "")
    token_out_addr = token_addresses.get(event.token_in, "")
    use_common_pairs = not token_in_addr or not token_out_addr

    if use_common_pairs and event.pool_address and addr_to_symbol is not None:
        resolved = _resolve_event_tokens(
            pool_address=event.pool_address,
            swap_direction=event.token_in,
            rpc_url=rpc_url,
            block_num=current_block,
            addr_to_symbol=addr_to_symbol,
        )
        if resolved:
            token_in_addr = resolved["token_in_addr"]
            token_out_addr = resolved["token_out_addr"]
            pair_resolved = True
            actual_pair = f"{resolved['token_in_symbol']}/{resolved['token_out_symbol']}"
            use_common_pairs = False

    if use_common_pairs:
        return _reject(REJECT_TOKEN_PAIR_UNRESOLVED)

    # ── M7.A.5.7: On-chain enrichment for unknown tokens ───────────────
    # Before admission: if a token is not in addr_to_symbol, try reading
    # its ERC-20 symbol/decimals on-chain. If successful, inject into
    # addr_to_symbol so the admission check can use it.
    enrichment_applied = False
    _ats = addr_to_symbol or {}
    unknown_addrs = []
    if token_in_addr and token_in_addr.lower() not in _ats:
        unknown_addrs.append(token_in_addr)
    if token_out_addr and token_out_addr.lower() not in _ats:
        unknown_addrs.append(token_out_addr)
    if unknown_addrs:
        try:
            enriched = enrich_tokens_batch(unknown_addrs, rpc_url, current_block)
            for addr, info in enriched.items():
                if info["enriched"] and info["symbol"]:
                    _ats[addr] = info["symbol"]
                    enrichment_applied = True
        except Exception:
            pass  # enrichment is best-effort

    # ── M7.A.5.6: Event-token admission check ──────────────────────────
    admission = admit_event_tokens(
        token_in_addr, token_out_addr,
        _ats, token_addresses,
    )
    # M7.A.5.7: Override admission_source if enrichment was used
    adm_source = admission.get("admission_source", ADMISSION_REJECTED)
    if enrichment_applied and admission["admitted"] and adm_source == ADMISSION_ADDR_TO_SYMBOL:
        adm_source = ADMISSION_SUBGRAPH_VERIFIED  # on-chain verified enrichment

    # M7.A.5.8: Track whether subgraph seed contributed to admission
    _sg_addrs = subgraph_seeded_addrs or set()
    sg_seed = bool(
        _sg_addrs
        and (token_in_addr.lower() in _sg_addrs or token_out_addr.lower() in _sg_addrs)
        and admission["admitted"]
    )

    if not admission["admitted"]:
        return _reject(
            REJECT_TOKEN_NOT_ADMITTED,
            pr=pair_resolved, ap=actual_pair, adm=False,
            adm_src=ADMISSION_REJECTED, sg_seed=False,
        )

    # ── M7.A.5.7: Oracle sanity guard ──────────────────────────────────
    oracle_result = None
    try:
        in_sym = admission.get("token_in_symbol")
        out_sym = admission.get("token_out_symbol")
        oracle_result = check_oracle_sanity(in_sym, out_sym, rpc_url, current_block)
    except Exception:
        pass  # oracle guard is best-effort

    # ── M7.A.5.6: Counter-venue coverage scan ──────────────────────────
    try:
        coverage = counter_venue_coverage_scan(
            token_in_addr, token_out_addr,
            dex_configs, rpc_url, current_block,
        )
    except Exception:
        coverage = {
            "known_pools": 0, "known_dexes": [], "buy_venues": 0,
            "sell_venues": 0, "coverage_complete": False,
            "coverage_blocker_reason": "scan_error",
        }

    if not coverage["coverage_complete"]:
        reason = REJECT_NO_COUNTER_POOL
        if coverage["coverage_blocker_reason"] == "no_quoter_for_live_pools":
            reason = REJECT_UNSUPPORTED_ADAPTER
        return _reject(
            reason,
            pr=pair_resolved, ap=actual_pair, adm=True,
            adm_src=adm_source, orc=oracle_result,
            cov=coverage, sg_seed=sg_seed,
        )

    # ── M7.A.5.7: Local-sim pool state extraction ──────────────────────
    local_sim = None
    try:
        pool_addrs_for_sim = []
        if coverage.get("known_dexes"):
            # Get pool addresses from the coverage scan results
            pool_map = _resolve_pool_addresses_multicall(
                dex_configs, token_in_addr, token_out_addr, rpc_url, current_block,
            )
            for dex_name, pools in pool_map.items():
                for p in pools:
                    if p["address"] is not None:
                        pool_addrs_for_sim.append(p["address"])
        if pool_addrs_for_sim:
            raw_states = extract_pool_state_for_sim(pool_addrs_for_sim, rpc_url, current_block)
            # Summarize: how many pools have valid state
            valid_states = {k: v for k, v in raw_states.items() if v is not None}
            local_sim = {
                "pools_queried": len(pool_addrs_for_sim),
                "pools_with_state": len(valid_states),
                "pool_states": {k: v for k, v in list(valid_states.items())[:3]},  # cap to 3
            }
    except Exception:
        pass  # local-sim state is best-effort

    # ── Bounded size logic ──────────────────────────────────────────────
    MIN_BACKRUN_WEI = 10**15   # 0.001 ETH
    MAX_BACKRUN_WEI = 10**18   # 1.0 ETH
    backrun_size_wei = max(event.amount_in_wei // 10, 1)
    backrun_size_wei = max(MIN_BACKRUN_WEI, min(MAX_BACKRUN_WEI, backrun_size_wei))
    if backrun_size_wei != max(event.amount_in_wei // 10, 1):
        size_source = "bounded"

    # DEXes that have quoter_v2
    quotable_dexes = []
    for dex_name, cfg in dex_configs.items():
        quoter = cfg.get("quoter_v2") or cfg.get("quoter")
        if quoter:
            quotable_dexes.append((dex_name, cfg, quoter))

    # Total quote calls that would be attempted without pruning
    total_quote_calls = 0
    for _dn, cfg, _q in quotable_dexes:
        fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
        total_quote_calls += len(fee_tiers[:2]) * 2  # buy + sell pass

    # ── Stage A: Multicall-based venue pruning ──────────────────────────
    stage_a_start = time.monotonic()
    venues_pruned = 0
    prune_reasons: Dict[str, int] = {}

    try:
        pool_map = _resolve_pool_addresses_multicall(
            dex_configs, token_in_addr, token_out_addr, rpc_url, current_block,
        )
        if pool_map:
            active_dexes = []
            for dex_name, cfg, quoter in quotable_dexes:
                pools_for_dex = pool_map.get(dex_name, [])
                if not pools_for_dex:
                    # No factory entry — keep (may be algebra/non-standard)
                    active_dexes.append((dex_name, cfg, quoter))
                    continue
                # Check if any pool exists and has liquidity
                has_live_pool = False
                for p in pools_for_dex:
                    if p["address"] is None:
                        prune_reasons["NO_POOL"] = prune_reasons.get("NO_POOL", 0) + 1
                        continue
                    liq = p["liquidity"]
                    if liq is not None and liq == 0:
                        prune_reasons["ZERO_LIQUIDITY"] = prune_reasons.get("ZERO_LIQUIDITY", 0) + 1
                        continue
                    has_live_pool = True
                if has_live_pool:
                    active_dexes.append((dex_name, cfg, quoter))
                else:
                    venues_pruned += 1
            quotable_dexes = active_dexes
    except Exception as exc:
        logger.debug("Stage A multicall pruning skipped: %s", str(exc)[:100])

    stage_a_ms = round((time.monotonic() - stage_a_start) * 1000, 2)

    # Compute post-pruning quote calls
    quote_calls_after = 0
    for _dn, cfg, _q in quotable_dexes:
        fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
        quote_calls_after += len(fee_tiers[:2]) * 2  # buy + sell

    # ── Stage B: Confirmatory QuoterV2 quotes ───────────────────────────
    stage_b_start = time.monotonic()
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

    stage_b_ms = round((time.monotonic() - stage_b_start) * 1000, 2)
    pipeline_end = time.monotonic()
    pipeline_ms = round((pipeline_end - pipeline_start) * 1000, 2)

    stage_latency = {"stage_a_ms": stage_a_ms, "stage_b_ms": stage_b_ms}

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

        # Build candidate_path with actual symbols if pair resolved
        if pair_resolved and actual_pair:
            parts = actual_pair.split("/")
            cand_path = [parts[1], parts[0], parts[1]] if len(parts) == 2 else [event.token_out, event.token_in, event.token_out]
        else:
            cand_path = [event.token_out, event.token_in, event.token_out]

        # ── M7.A.5.6: Bounded size sweep ───────────────────────────────
        sweep_results = None
        best_sweep_net = None
        best_sweep_size = None
        try:
            sweep_results = _run_size_sweep(
                event, rpc_url, token_in_addr, token_out_addr,
                quotable_dexes, backrun_size_wei, fallback_rpc_urls,
            )
            if sweep_results:
                viable_sweeps = [s for s in sweep_results if s["net_bps"] != 0.0]
                if viable_sweeps:
                    best_s = max(viable_sweeps, key=lambda s: s["net_bps"])
                    best_sweep_net = best_s["net_bps"]
                    best_sweep_size = best_s["size_wei"]
        except Exception:
            pass  # sweep is best-effort, don't block scoring

        # M7.A.5.8: Gas decomposition
        gas_decomp = estimate_gas_decomposition_bps(backrun_size_wei, gas_cost_wei)

        return BackrunResult(
            event_id=event.event_id,
            event_source="live",
            event_type=event.event_type,
            post_trade_state_used="live",
            backrun_direction=backrun_dir,
            best_buy_venue=best_buy_venue,
            best_sell_venue=best_sell_venue,
            candidate_path=cand_path,
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
            quote_calls_attempted=total_quote_calls,
            quote_calls_after_pruning=quote_calls_after,
            prune_reason_histogram=prune_reasons if prune_reasons else None,
            pipeline_stage_latency_ms=stage_latency,
            pair_resolved=pair_resolved,
            actual_pair=actual_pair,
            size_source=size_source,
            coverage_result=coverage,
            size_sweep_results=sweep_results,
            best_sweep_net_bps=best_sweep_net,
            best_sweep_size_wei=best_sweep_size,
            token_admitted=True,
            admission_source=adm_source,
            oracle_guard=oracle_result,
            local_sim_state=local_sim,
            l2_gas_bps=gas_decomp["l2_gas_bps"],
            l1_data_bps=gas_decomp["l1_data_bps"],
            total_gas_bps=gas_decomp["total_gas_bps"],
            subgraph_seed_used=sg_seed,
        )

    # M7.A.5.6: Split QUOTE_FAILURE — distinguish RPC failure from no-route
    fail_reason = REJECT_RPC_QUOTE_FAIL if venues_quoted == 0 else REJECT_PAIR_RESOLVED_UNTRADEABLE
    return BackrunResult(
        event_id=event.event_id,
        event_source="live",
        event_type=event.event_type,
        post_trade_state_used="live",
        backrun_direction=backrun_dir,
        reject_reason=fail_reason,
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
        quote_calls_attempted=total_quote_calls,
        quote_calls_after_pruning=quote_calls_after,
        prune_reason_histogram=prune_reasons if prune_reasons else None,
        pipeline_stage_latency_ms=stage_latency,
        pair_resolved=pair_resolved,
        actual_pair=actual_pair,
        size_source=size_source,
        coverage_result=coverage,
        token_admitted=True,
        admission_source=adm_source,
        oracle_guard=oracle_result,
        local_sim_state=local_sim,
        subgraph_seed_used=sg_seed,
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

        # M7.A.5.8: Subgraph-backed bounded coverage seed
        # Seed addr_to_symbol with top tokens from DEX subgraphs
        # before scoring loop — purely coverage expansion, not price truth
        pre_seed_count = len(addr_to_symbol)
        subgraph_seed_stats = {"tokens_discovered": 0, "tokens_new": 0,
                               "tokens_verified": 0, "sources_queried": [], "errors": []}
        subgraph_seeded_addrs: set = set()
        try:
            from web3 import Web3
            w3_seed = Web3(Web3.HTTPProvider(rpc_url))
            seed_block = w3_seed.eth.block_number
            subgraph_seed_stats = seed_tokens_from_subgraph(
                addr_to_symbol, rpc_url, seed_block, chain=args.chain,
            )
            # Track which addresses were added by subgraph seed
            post_seed_count = len(addr_to_symbol)
            if post_seed_count > pre_seed_count:
                # Identify newly added addresses
                canonical_addrs = set(_build_address_to_symbol(token_addresses).keys())
                subgraph_seeded_addrs = set(addr_to_symbol.keys()) - canonical_addrs
            logger.info(
                "Subgraph seed: discovered=%d new=%d verified=%d sources=%s",
                subgraph_seed_stats["tokens_discovered"],
                subgraph_seed_stats["tokens_new"],
                subgraph_seed_stats["tokens_verified"],
                subgraph_seed_stats["sources_queried"],
            )
        except Exception as exc:
            logger.debug("Subgraph seed failed (best-effort): %s", str(exc)[:100])
            subgraph_seed_stats["errors"].append(f"seed_init: {str(exc)[:80]}")

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
                        addr_to_symbol=addr_to_symbol,
                        subgraph_seeded_addrs=subgraph_seeded_addrs,
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
        artifact["m7a56_hypothesis"] = (
            "same-chain backrun on arbitrum_one may become measurable only after "
            "pair-resolved counter-venue coverage is expanded for actual live-event "
            "tokens; no expansion outside current DEX domain"
        )
        artifact["m7a57_hypothesis"] = (
            "same-chain backrun on arbitrum_one may become measurable once "
            "pair-resolved live-event tokens are admitted through bounded discovery "
            "coverage (on-chain ERC-20 enrichment + oracle sanity rails), "
            "without leaving the current DEX domain"
        )
        artifact["m7a58_hypothesis"] = (
            "bounded coverage enrichment (The Graph subgraph seed) materially raises "
            "live admission and counter-venue coverage for pair-resolved Arbitrum "
            "event tokens within the same-chain DEX domain"
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
            # M7.A.5.4: Two-stage pruning metrics
            calls_attempted = [r.quote_calls_attempted for r in live_results if r.quote_calls_attempted is not None]
            calls_after = [r.quote_calls_after_pruning for r in live_results if r.quote_calls_after_pruning is not None]
            if calls_attempted:
                artifact["live_state_metrics"]["mean_quote_calls_attempted"] = round(
                    sum(calls_attempted) / len(calls_attempted), 2
                )
            if calls_after:
                artifact["live_state_metrics"]["mean_quote_calls_after_pruning"] = round(
                    sum(calls_after) / len(calls_after), 2
                )
            # Aggregate prune_reason_histogram across all events
            agg_prune: Dict[str, int] = {}
            for r in live_results:
                if r.prune_reason_histogram:
                    for reason, cnt in r.prune_reason_histogram.items():
                        agg_prune[reason] = agg_prune.get(reason, 0) + cnt
            if agg_prune:
                artifact["live_state_metrics"]["prune_reason_histogram"] = agg_prune
            # Aggregate stage latency
            stage_a_times = [r.pipeline_stage_latency_ms["stage_a_ms"] for r in live_results if r.pipeline_stage_latency_ms]
            stage_b_times = [r.pipeline_stage_latency_ms["stage_b_ms"] for r in live_results if r.pipeline_stage_latency_ms]
            if stage_a_times:
                artifact["live_state_metrics"]["mean_stage_a_ms"] = round(sum(stage_a_times) / len(stage_a_times), 2)
            if stage_b_times:
                artifact["live_state_metrics"]["mean_stage_b_ms"] = round(sum(stage_b_times) / len(stage_b_times), 2)
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
                "mean_quote_calls_after_pruning": (
                    round(
                        sum(r.quote_calls_after_pruning or 0 for r in low_lag)
                        / len(low_lag), 2
                    ) if low_lag else None
                ),
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

            # M7.A.5.5: Pair resolution metrics
            resolved_results = [r for r in live_results if r.pair_resolved]
            unresolved_results = [r for r in live_results if not r.pair_resolved]
            resolved_net = [r.best_live_net_bps for r in resolved_results if r.best_live_net_bps is not None]
            unresolved_net = [r.best_live_net_bps for r in unresolved_results if r.best_live_net_bps is not None]
            actual_pairs_seen = list(set(r.actual_pair for r in resolved_results if r.actual_pair))
            size_sources = {}
            for r in live_results:
                src = r.size_source or "unknown"
                size_sources[src] = size_sources.get(src, 0) + 1
            artifact["pair_resolution_metrics"] = {
                "events_pair_resolved": len(resolved_results),
                "events_pair_unresolved": len(unresolved_results),
                "pair_resolution_rate": round(
                    len(resolved_results) / len(live_results), 4
                ) if live_results else 0.0,
                "actual_pairs_seen": actual_pairs_seen,
                "resolved_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
                "resolved_mean_net_bps": (
                    round(sum(resolved_net) / len(resolved_net), 4)
                    if resolved_net else None
                ),
                "size_source_histogram": size_sources,
            }

            # M7.A.5.5: M4 vs M7 economics comparison block
            # Use amounts from resolved events to compute decomposed costs
            resolved_with_amounts = [r for r in resolved_results if r.amount_in_wei > 0]
            if resolved_with_amounts:
                mean_amount_wei = sum(r.amount_in_wei for r in resolved_with_amounts) // len(resolved_with_amounts)
                mean_gross_bps = round(
                    sum(
                        (r.gross_pnl_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                        for r in resolved_with_amounts
                    ) / len(resolved_with_amounts), 4
                )
                mean_gas_bps = round(
                    sum(
                        (r.gas_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                        for r in resolved_with_amounts
                    ) / len(resolved_with_amounts), 4
                )
            else:
                mean_amount_wei = 0
                mean_gross_bps = None
                mean_gas_bps = None

            artifact["m4_m7_comparison"] = {
                "m4_best_net_bps": -3.5062,
                "m4_frontier_pair": "WBTC/USDC",
                "m4_size_usd": 50,
                "m4_gas_bps": 2.01,
                "m7_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
                "m7_mean_gross_bps": mean_gross_bps,
                "m7_mean_gas_bps": mean_gas_bps,
                "m7_mean_size_wei": mean_amount_wei,
                "m7_latency_class": "stale" if not low_lag else "low_lag",
                "m7_pair_resolved_count": len(resolved_results),
                "note": "M4 uses pair-specific dynamic sweep; M7 uses event-driven replay with actual-pair resolution",
            }

            # ── M7.A.5.6: Coverage scan metrics ────────────────────────
            admitted_results = [r for r in live_results if r.token_admitted is True]
            not_admitted = [r for r in live_results if r.token_admitted is False]
            coverage_complete_results = [
                r for r in live_results
                if r.coverage_result and r.coverage_result.get("coverage_complete")
            ]
            coverage_blocker_hist: Dict[str, int] = {}
            for r in live_results:
                if r.coverage_result and r.coverage_result.get("coverage_blocker_reason"):
                    reason = r.coverage_result["coverage_blocker_reason"]
                    coverage_blocker_hist[reason] = coverage_blocker_hist.get(reason, 0) + 1

            artifact["coverage_scan_metrics"] = {
                "events_admitted": len(admitted_results),
                "events_not_admitted": len(not_admitted),
                "events_coverage_complete": len(coverage_complete_results),
                "coverage_blocker_histogram": coverage_blocker_hist,
                "admission_rate": round(
                    len(admitted_results) / len(live_results), 4
                ) if live_results else 0.0,
            }

            # ── M7.A.5.6: Size sweep metrics ───────────────────────────
            sweep_events = [r for r in live_results if r.size_sweep_results]
            all_sweep_nets = []
            for r in sweep_events:
                for s in (r.size_sweep_results or []):
                    if s.get("net_bps", 0) != 0.0:
                        all_sweep_nets.append(s["net_bps"])
            events_with_sweep_best = [r for r in live_results if r.best_sweep_net_bps is not None]

            artifact["size_sweep_metrics"] = {
                "events_with_sweep": len(sweep_events),
                "sweep_net_bps_all": all_sweep_nets,
                "best_sweep_net_bps": round(max(all_sweep_nets), 4) if all_sweep_nets else None,
                "mean_sweep_net_bps": (
                    round(sum(all_sweep_nets) / len(all_sweep_nets), 4)
                    if all_sweep_nets else None
                ),
                "events_with_positive_sweep": sum(1 for n in all_sweep_nets if n > 0),
            }

            # ── M7.A.5.6: m4_m7_comparison_v2 block ────────────────────
            # Decomposed economics comparison with coverage truth
            v2_resolved_with_amounts = [r for r in resolved_results if r.amount_in_wei > 0]
            v2_gross_bps = None
            v2_gas_bps = None
            v2_fee_bps = None
            v2_size_usd = None
            if v2_resolved_with_amounts:
                v2_gross_bps = round(
                    sum(
                        (r.gross_pnl_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                        for r in v2_resolved_with_amounts
                    ) / len(v2_resolved_with_amounts), 4
                )
                v2_gas_bps = round(
                    sum(
                        (r.gas_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                        for r in v2_resolved_with_amounts
                    ) / len(v2_resolved_with_amounts), 4
                )
                v2_fee_bps = round(
                    sum(
                        (r.fee_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                        for r in v2_resolved_with_amounts
                    ) / len(v2_resolved_with_amounts), 4
                )
                # Rough USD estimate: assume 1 ETH ≈ $3000
                v2_size_usd = round(
                    sum(r.amount_in_wei for r in v2_resolved_with_amounts)
                    / len(v2_resolved_with_amounts) / 10**18 * 3000, 2
                )

            artifact["m4_m7_comparison_v2"] = {
                "m4_best_net_bps": -3.5062,
                "m4_gross_pre_cost_bps": 36.35,
                "m4_gas_bps": 2.01,
                "m4_fee_bps": 31.0,
                "m4_slippage_bps": 6.85,
                "m4_size_usd": 50,
                "m4_pair": "WBTC/USDC",
                "m7_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
                "m7_gross_pre_cost_bps": v2_gross_bps,
                "m7_gas_bps": v2_gas_bps,
                "m7_fee_bps": v2_fee_bps,
                "m7_slippage_bps": None,  # not decomposed yet
                "m7_size_usd": v2_size_usd,
                "m7_pair_resolved": True,
                "m7_coverage_complete_count": len(coverage_complete_results),
                "m7_latency_class": "stale" if not low_lag else "low_lag",
                "m7_best_sweep_net_bps": (
                    round(max(all_sweep_nets), 4) if all_sweep_nets else None
                ),
                "note": (
                    "M4 has mature pair-specific dynamic sweep; "
                    "M7 now has pair-resolved coverage + bounded event-size evaluation"
                ),
            }

            # ── M7.A.5.6: Granular reject histogram ────────────────────
            granular_hist: Dict[str, int] = {}
            for r in live_results:
                if r.reject_reason:
                    granular_hist[r.reject_reason] = granular_hist.get(r.reject_reason, 0) + 1
            artifact["reject_histogram_v2"] = granular_hist

            # ── M7.A.5.7: Enrichment metrics ───────────────────────────
            adm_source_hist: Dict[str, int] = {}
            for r in live_results:
                src = r.admission_source or "unknown"
                adm_source_hist[src] = adm_source_hist.get(src, 0) + 1
            enriched_count = sum(
                1 for r in live_results
                if r.admission_source == ADMISSION_SUBGRAPH_VERIFIED
            )
            artifact["enrichment_metrics"] = {
                "admission_source_histogram": adm_source_hist,
                "events_enriched_onchain": enriched_count,
                "enrichment_admission_rate": round(
                    enriched_count / len(live_results), 4
                ) if live_results else 0.0,
                "total_admitted": sum(
                    1 for r in live_results if r.token_admitted is True
                ),
                "total_rejected": sum(
                    1 for r in live_results if r.token_admitted is False
                ),
            }

            # ── M7.A.5.7: Oracle guard metrics ─────────────────────────
            events_with_oracle = [
                r for r in live_results
                if r.oracle_guard and r.oracle_guard.get("oracle_price_available")
            ]
            guard_triggered = [
                r for r in live_results
                if r.oracle_guard and r.oracle_guard.get("oracle_guard_triggered")
            ]
            artifact["oracle_guard_metrics"] = {
                "events_with_oracle_price": len(events_with_oracle),
                "oracle_coverage_rate": round(
                    len(events_with_oracle) / len(live_results), 4
                ) if live_results else 0.0,
                "guard_triggered_count": len(guard_triggered),
                "oracle_feeds_available": list(CHAINLINK_FEEDS_ARBITRUM.keys()),
            }

            # ── M7.A.5.7: Local-sim readiness metrics ──────────────────
            events_with_sim = [
                r for r in live_results
                if r.local_sim_state and r.local_sim_state.get("pools_with_state", 0) > 0
            ]
            total_pools_queried = sum(
                r.local_sim_state.get("pools_queried", 0)
                for r in live_results if r.local_sim_state
            )
            total_pools_with_state = sum(
                r.local_sim_state.get("pools_with_state", 0)
                for r in live_results if r.local_sim_state
            )
            artifact["local_sim_readiness"] = {
                "events_with_pool_state": len(events_with_sim),
                "sim_readiness_rate": round(
                    len(events_with_sim) / len(live_results), 4
                ) if live_results else 0.0,
                "total_pools_queried": total_pools_queried,
                "total_pools_with_state": total_pools_with_state,
                "note": "State captured for future local-sim pricing path (sqrtPriceX96 + tick + liquidity)",
            }

            # ── M7.A.5.8: Oracle summary extended ──────────────────────
            oracle_price_avail = sum(
                1 for r in live_results
                if r.oracle_guard and r.oracle_guard.get("oracle_price_available")
            )
            oracle_guard_trig = sum(
                1 for r in live_results
                if r.oracle_guard and r.oracle_guard.get("oracle_guard_triggered")
            )
            oracle_staleness_vals = [
                r.oracle_guard.get("oracle_staleness_seconds", 0)
                for r in live_results
                if r.oracle_guard and r.oracle_guard.get("oracle_staleness_seconds") is not None
            ]
            events_blocked_oracle = sum(
                1 for r in live_results
                if r.reject_reason and "ORACLE" in (r.reject_reason or "").upper()
            )
            artifact["oracle_summary_extended"] = {
                "oracle_price_available_rate": round(
                    oracle_price_avail / len(live_results), 4
                ) if live_results else 0.0,
                "oracle_guard_triggered_rate": round(
                    oracle_guard_trig / len(live_results), 4
                ) if live_results else 0.0,
                "oracle_staleness_max_seconds": (
                    max(oracle_staleness_vals) if oracle_staleness_vals else None
                ),
                "events_blocked_by_oracle": events_blocked_oracle,
            }

            # ── M7.A.5.8: Gas decomposition metrics ────────────────────
            events_with_gas = [
                r for r in live_results
                if r.total_gas_bps is not None
            ]
            artifact["gas_decomposition_metrics"] = {
                "events_with_gas_decomp": len(events_with_gas),
                "mean_l2_gas_bps": round(
                    sum(r.l2_gas_bps or 0 for r in events_with_gas)
                    / len(events_with_gas), 4
                ) if events_with_gas else None,
                "mean_l1_data_bps": round(
                    sum(r.l1_data_bps or 0 for r in events_with_gas)
                    / len(events_with_gas), 4
                ) if events_with_gas else None,
                "mean_total_gas_bps": round(
                    sum(r.total_gas_bps or 0 for r in events_with_gas)
                    / len(events_with_gas), 4
                ) if events_with_gas else None,
            }

            # ── M7.A.5.8: Subgraph seed stats ──────────────────────────
            sg_used_count = sum(
                1 for r in live_results
                if r.subgraph_seed_used is True
            )
            artifact["subgraph_seed_stats"] = {
                "tokens_discovered": subgraph_seed_stats.get("tokens_discovered", 0),
                "tokens_new": subgraph_seed_stats.get("tokens_new", 0),
                "tokens_verified": subgraph_seed_stats.get("tokens_verified", 0),
                "sources_queried": subgraph_seed_stats.get("sources_queried", []),
                "errors": subgraph_seed_stats.get("errors", []),
                "addr_to_symbol_size_before": pre_seed_count,
                "addr_to_symbol_size_after": len(addr_to_symbol),
                "subgraph_seeded_events_admitted": sg_used_count,
                "subgraph_seeded_admission_rate": round(
                    sg_used_count / len(live_results), 4
                ) if live_results else 0.0,
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
