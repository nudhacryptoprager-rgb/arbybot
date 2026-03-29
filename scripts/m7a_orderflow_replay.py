#!/usr/bin/env python3
"""
M7.A.4 — Orderflow-driven replay and intent/auction surface scout.

Hypothesis: Edge may emerge from external orderflow events, auction dynamics,
or private-inventory/filler surfaces rather than from static AMM state alone.

This script implements a read-only event-driven replay pipeline:
  event → post-trade state delta → best backrun venue → measured net

Modes:
  --offline           Score backrun opportunities from built-in fixture events
  --replay <file>     Score from imported event samples (JSON)
  --intent-scout      Read-only feasibility assessment of orderflow surfaces

Usage:
    python scripts/m7a_orderflow_replay.py --offline --output data/tmp/m7a_orderflow_offline.json
    python scripts/m7a_orderflow_replay.py --replay data/tmp/events.json --output data/tmp/m7a_replay.json
    python scripts/m7a_orderflow_replay.py --intent-scout --output data/tmp/m7a_intent_scout.json
    python scripts/m7a_orderflow_replay.py --online --output data/tmp/m7a_orderflow_online.json
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

# Canonical chain for M7.A.4 (same as M7.A: arbitrum_one)
M7A4_CHAIN = "arbitrum_one"

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
    post_trade_state_used: str  # "estimated" | "simulated" | "quoted"
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
# Online backrun scoring (live quotes at current block)
# ---------------------------------------------------------------------------

def score_backrun_online(
    event: OrderflowEvent,
    rpc_url: str,
    dex_configs: Dict[str, Any],
    token_addresses: Dict[str, str],
) -> BackrunResult:
    """Score a backrun opportunity using live RPC quotes.

    Quotes the backrun path at the current block to estimate
    real post-trade venue spreads. Requires RPC access.
    """
    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    current_block = w3.eth.block_number

    # The backrun buys the depressed token on the cheapest alternative venue
    # and sells on the impacted venue (or the most expensive alternative)
    backrun_dir = classify_event_backrun_type(event)

    # For a swap token_in → token_out on source DEX:
    # Backrun: buy token_in on cheapest venue, sell token_in on source venue
    # (the source venue now has more token_in than before → token_in is cheaper there)

    # Quote on source venue (impacted)
    best_buy_quote = None
    best_buy_venue = None
    best_sell_quote = None
    best_sell_venue = None

    # Use a reasonable backrun size: tied to ~10% of event impact
    backrun_size_wei = max(event.amount_in_wei // 10, 1)

    # Try quoting across known DEXes on the chain
    known_dexes = ["uniswap_v3", "camelot_v3", "pancakeswap_v3", "sushiswap_v3"]

    for dex_name in known_dexes:
        try:
            dex_cfg = dex_configs.get(dex_name, {})
            if not dex_cfg:
                continue
            quoter_addr = dex_cfg.get("quoter_v2") or dex_cfg.get("quoter")
            factory_addr = dex_cfg.get("factory")
            if not quoter_addr or not factory_addr:
                continue

            adapter_type = dex_cfg.get("adapter_type", "uniswap_v3")
            token_in_addr = token_addresses.get(event.token_out, "")
            token_out_addr = token_addresses.get(event.token_in, "")
            if not token_in_addr or not token_out_addr:
                continue

            # Dynamic adapter import
            if adapter_type in ("uniswap_v3", "camelot_v3", "pancakeswap_v3", "sushiswap_v3"):
                from dex.adapters.uniswap_v3 import UniswapV3Adapter
                adapter = UniswapV3Adapter(
                    rpc_url=rpc_url,
                    chain_id=42161,  # arbitrum
                    quoter_address=quoter_addr,
                    factory_address=factory_addr,
                )
            else:
                continue

            fee_tier = event.fee_tier or 500
            quote_result = adapter.quote(
                token_in=token_in_addr,
                token_out=token_out_addr,
                amount_in=backrun_size_wei,
                fee=fee_tier,
            )
            if quote_result and quote_result.amount_out > 0:
                if best_buy_quote is None or quote_result.amount_out > best_buy_quote:
                    best_buy_quote = quote_result.amount_out
                    best_buy_venue = dex_name

        except Exception as exc:
            logger.debug(
                "Quote failed for %s: %s",
                dex_name,
                str(exc)[:100],
                extra={"context": {"dex": dex_name, "event_id": event.event_id}},
            )
            continue

    # Also quote the sell side: token_in → token_out (reverse direction)
    for dex_name in known_dexes:
        try:
            dex_cfg = dex_configs.get(dex_name, {})
            if not dex_cfg:
                continue
            quoter_addr = dex_cfg.get("quoter_v2") or dex_cfg.get("quoter")
            factory_addr = dex_cfg.get("factory")
            if not quoter_addr or not factory_addr:
                continue

            token_in_addr = token_addresses.get(event.token_in, "")
            token_out_addr = token_addresses.get(event.token_out, "")
            if not token_in_addr or not token_out_addr:
                continue

            from dex.adapters.uniswap_v3 import UniswapV3Adapter
            adapter = UniswapV3Adapter(
                rpc_url=rpc_url,
                chain_id=42161,
                quoter_address=quoter_addr,
                factory_address=factory_addr,
            )

            fee_tier = event.fee_tier or 500
            quote_result = adapter.quote(
                token_in=token_in_addr,
                token_out=token_out_addr,
                amount_in=backrun_size_wei,
                fee=fee_tier,
            )
            if quote_result and quote_result.amount_out > 0:
                if best_sell_quote is None or quote_result.amount_out > best_sell_quote:
                    best_sell_quote = quote_result.amount_out
                    best_sell_venue = dex_name

        except Exception as exc:
            logger.debug(
                "Sell quote failed for %s: %s",
                dex_name,
                str(exc)[:100],
                extra={"context": {"dex": dex_name, "event_id": event.event_id}},
            )
            continue

    # Compute gross from venue spread
    if best_buy_quote is not None and best_sell_quote is not None:
        gross_wei = best_sell_quote - backrun_size_wei
        gas_cost_wei = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)
        net_wei = gross_wei - gas_cost_wei
        net_bps = (net_wei / backrun_size_wei) * 10000 if backrun_size_wei > 0 else 0.0

        route_viable = net_bps > 0
        reject_reason = None if route_viable else REJECT_GAS_EXCEEDS_GROSS

        return BackrunResult(
            event_id=event.event_id,
            event_source="live",
            event_type=event.event_type,
            post_trade_state_used="quoted",
            backrun_direction=backrun_dir,
            best_buy_venue=best_buy_venue,
            best_sell_venue=best_sell_venue,
            candidate_path=[event.token_out, event.token_in, event.token_out],
            amount_in_wei=backrun_size_wei,
            gross_pnl_wei=gross_wei,
            gas_cost_wei=gas_cost_wei,
            fee_cost_wei=0,  # Already in quote
            net_pnl_wei=net_wei,
            best_backrun_net_bps=round(net_bps, 4),
            same_block_possible=True,
            route_viable=route_viable,
            reject_reason=reject_reason,
        )

    return BackrunResult(
        event_id=event.event_id,
        event_source="live",
        event_type=event.event_type,
        post_trade_state_used="quoted",
        backrun_direction=backrun_dir,
        reject_reason=REJECT_QUOTE_FAILURE,
    )


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
        description="M7.A.4 — Orderflow-driven replay and intent/auction scout",
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
        "--intent-scout",
        action="store_true",
        help="Read-only feasibility assessment of orderflow surfaces",
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
        dex_configs = load_dexes(args.chain)
        token_addresses = get_all_token_addresses(args.chain)

        events = build_fixture_events()
        results = [
            score_backrun_online(e, rpc_url, dex_configs, token_addresses)
            for e in events
        ]
        artifact = build_replay_summary(events, results, mode="online")
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
