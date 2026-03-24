# PATH: engine/roundtrip.py
"""
Round-trip PnL simulator for M4.2.

M4.2 CONTRACT (v2.1.0):
- Canonical profit = round-trip: token_in -> token_out -> token_in
- One-leg spread = diagnostic only
- Uses QuoterV2 for both legs when available

Round-trip formula:
1. Buy leg: Start with `amount_in` of token_in, get `amount_out` of token_out
2. Sell leg: Take `amount_out`, swap back to token_in, get `amount_back`
3. Gross PnL = amount_back - amount_in (negative if loss)
4. Net PnL = Gross PnL - gas_cost

This inherently includes:
- LP fees (via quoter amount_out)
- Price impact/slippage (via quoter amount_out)
- Liquidity constraints (detected via ticks_crossed)

v3.1.0: Detailed rejection classification:
- SLIPPAGE_TOO_HIGH: slippage_bps > lp_fee_bps + gas_bps
- LP_FEES_TOO_HIGH: lp_fee_bps dominates (>50% of spread consumed)
- GAS_TOO_HIGH: gas_bps dominates (>30% of spread consumed)
- NET_PROFIT_TOO_LOW: general unprofitable (none dominates)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("engine.roundtrip")

# ---------------------------------------------------------------------------
# Canonical sweep size ladder — bounded, deterministic, session-independent.
# Wide logarithmic frontier from positive-epsilon ($1) to $10 000.
# Fixed-size doctrine removed R29: canonical truth comes from this full frontier,
# not a single probe notional. Any change requires a schema bump and test update.
# ---------------------------------------------------------------------------
CANONICAL_SWEEP_SIZES_USD: List[float] = [
    1, 2.5, 5, 10, 15, 25, 50, 75, 100, 150, 250,
    500, 750, 1000, 1500, 2500, 5000, 7500, 10000,
]


@dataclass
class RoundTripResult:
    """Result of a round-trip simulation."""
    # Input
    pair: str
    buy_dex: str
    sell_dex: str
    amount_in_wei: int
    token_in: str
    token_out: str
    
    # Leg 1 (buy): token_in -> token_out
    leg1_amount_out: int  # token_out received
    leg1_gas_estimate: Optional[int] = None
    leg1_ticks_crossed: Optional[int] = None
    leg1_success: bool = False
    
    # Leg 2 (sell): token_out -> token_in
    leg2_amount_out: int = 0  # token_in received back
    leg2_gas_estimate: Optional[int] = None
    leg2_ticks_crossed: Optional[int] = None
    leg2_success: bool = False
    leg2_is_real_quote: bool = False  # v2.1.0: True if re-quoted, False if ratio estimate
    
    # Results
    gross_pnl_wei: int = 0  # amount_back - amount_in
    gas_cost_wei: int = 0
    net_pnl_wei: int = 0
    
    # v2.8.0: USD-denominated PnL for cross-token correctness
    # When token_in != WETH, wei-based subtraction is incorrect
    gross_pnl_usd: float = 0.0
    gas_cost_usd: float = 0.0
    net_pnl_usd: float = 0.0
    
    # Quality flags
    is_profitable: bool = False
    reject_reason: Optional[str] = None
    
    # Diagnostics
    gross_pnl_bps: float = 0.0  # for comparison with one-leg
    net_pnl_bps: float = 0.0
    total_ticks: int = 0
    total_gas: int = 0
    # v2.1.0: Slippage — prefers measured from sqrtPriceAfter (see calculate_roundtrip_pnl),
    # falls back to ticks heuristic (~0.5 bps per tick in V3)
    estimated_slippage_bps: float = 0.0
    slippage_source: str = "ticks_heuristic"  # "ticks_heuristic" | "sqrtPriceAfter" | "probe"
    # v2.1.0: L1 cost source for traceability
    l1_cost_source: str = "default"  # "config" | "onchain" | "default"
    # v2.1.0-fix: L2 gas source for traceability
    gas_source: str = "quoter"  # "quoter" | "eth_estimateGas" | "default"
    
    # v2.2.0: Leg provenance for fee/pool observability
    leg1_dex: str = ""
    leg2_dex: str = ""
    leg1_pool: str = ""
    leg2_pool: str = ""
    leg1_fee: int = 0
    leg2_fee: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON output."""
        return {
            "pair": self.pair,
            "buy_dex": self.buy_dex,
            "sell_dex": self.sell_dex,
            "amount_in_wei": str(self.amount_in_wei),
            "token_in": self.token_in,
            "token_out": self.token_out,
            "leg1_amount_out": str(self.leg1_amount_out),
            "leg1_gas_estimate": self.leg1_gas_estimate,
            "leg1_ticks_crossed": self.leg1_ticks_crossed,
            "leg1_success": self.leg1_success,
            "leg2_amount_out": str(self.leg2_amount_out),
            "leg2_gas_estimate": self.leg2_gas_estimate,
            "leg2_ticks_crossed": self.leg2_ticks_crossed,
            "leg2_success": self.leg2_success,
            "leg2_is_real_quote": self.leg2_is_real_quote,
            "gross_pnl_wei": str(self.gross_pnl_wei),
            "gas_cost_wei": str(self.gas_cost_wei),
            "net_pnl_wei": str(self.net_pnl_wei),
            "is_profitable": self.is_profitable,
            "reject_reason": self.reject_reason,
            "gross_pnl_bps": round(self.gross_pnl_bps, 2),
            "net_pnl_bps": round(self.net_pnl_bps, 2),
            "total_ticks": self.total_ticks,
            "total_gas": self.total_gas,
            "estimated_slippage_bps": round(self.estimated_slippage_bps, 2),
            "slippage_source": self.slippage_source,
            "l1_cost_source": self.l1_cost_source,
            "gas_source": self.gas_source,
            # v2.2.0: Leg provenance for fee/pool observability
            "leg1_dex": self.leg1_dex,
            "leg2_dex": self.leg2_dex,
            "leg1_pool": self.leg1_pool,
            "leg2_pool": self.leg2_pool,
            "leg1_fee": self.leg1_fee,
            "leg2_fee": self.leg2_fee,
            # v2.8.0: USD-denominated PnL for cross-token correctness
            "gross_pnl_usd": round(self.gross_pnl_usd, 4),
            "gas_cost_usd": round(self.gas_cost_usd, 4),
            "net_pnl_usd": round(self.net_pnl_usd, 4),
        }


@dataclass
class RoundtripEvaluationStats:
    """
    v3.0.0: Aggregation stats from evaluate_roundtrip_candidates.
    
    Provides visibility into WHY opportunities were filtered/rejected,
    not just the results that were evaluated.
    v3.2.4: Added warnings field for L1 cost source alerts.
    """
    candidates_total: int = 0          # Total opportunities passed in
    gated_by_economics: int = 0        # Filtered by is_roundtrip_viable=False or spread_minus_required<=0
    evaluated_count: int = 0           # Actually evaluated (not gated)
    results_count: int = 0             # Results returned (may be < evaluated if errors)
    rejected_reasons: Dict[str, int] = None  # Counter of reject reasons
    warnings: List[str] = None         # v3.2.4: Warnings for data quality issues
    
    def __post_init__(self):
        if self.rejected_reasons is None:
            self.rejected_reasons = {}
        if self.warnings is None:
            self.warnings = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidates_total": self.candidates_total,
            "gated_by_economics": self.gated_by_economics,
            "evaluated_count": self.evaluated_count,
            "results_count": self.results_count,
            "rejected_reasons": dict(self.rejected_reasons),
            "warnings": list(self.warnings),
        }


def simulate_roundtrip(
    buy_quote: Dict[str, Any],
    sell_quote: Dict[str, Any],
    gas_price_wei: int = 100_000_000,  # 0.1 gwei default (Arbitrum)
    max_ticks_crossed: int = 30,  # Total for both legs
    leg2_quote_callback: Optional[callable] = None,  # v2.1.0: Optional re-quote function
    l1_cost_wei: int = 6_000_000_000_000,  # R36: L1 overhead (~$0.012 at 2000 gas * 3 gwei, post-EIP-4844)
    l1_cost_source: str = "default",  # v2.1.0: "config" | "onchain" | "default"
    gas_override: Optional[Tuple[int, int]] = None,  # v2.1.0-fix: (leg1_gas, leg2_gas) from eth_estimateGas
    eth_usd_price: float = 2000.0,  # v2.8.0: For USD gas conversion
    token_in_usd_price: Optional[float] = None,  # v2.8.0: For non-WETH token_in
    token_in_decimals: int = 18,  # v2.8.0: For wei conversion
) -> RoundTripResult:
    """
    Simulate round-trip arbitrage.
    
    v2.1.0 CONTRACT:
    - If `leg2_quote_callback` is provided, leg2 uses ACTUAL re-quote for leg1_amount_out
    - If not provided, uses ratio estimate from sell_quote (DIAGNOSTIC ONLY, upper-bound)
    - Gas cost includes L1 overhead (unified with opportunity_engine.GasConfig)
    
    v2.1.0-fix: gas_override integration
    - If `gas_override` is provided, use those values instead of quoter gas estimates
    - gas_override = (leg1_gas, leg2_gas) from eth_estimateGas
    - Sets gas_source = "eth_estimateGas" for traceability
    
    The callback signature: leg2_quote_callback(amount_in_wei: int) -> Optional[Dict]
    where the returned dict has: amount_out_wei, gas_estimate, ticks_crossed
    
    Args:
        buy_quote: Quote dict for leg 1 (token_in -> token_out) from lower-price DEX
        sell_quote: Quote dict for leg 2 (token_out -> token_in) from higher-price DEX
        gas_price_wei: L2 gas price in wei
        max_ticks_crossed: Maximum allowed ticks crossed (both legs combined)
        leg2_quote_callback: Optional callback to re-quote leg2 with actual leg1_amount_out
        l1_cost_wei: L1 data posting overhead in wei (Arbitrum/Optimism specific)  
        l1_cost_source: Source of L1 cost estimate
        gas_override: Optional (leg1_gas, leg2_gas) tuple from eth_estimateGas
        
    Returns:
        RoundTripResult with full breakdown
    """
    pair = f"{buy_quote.get('token_in', '')}/{buy_quote.get('token_out', '')}"
    
    # v2.1.0-fix: Track gas source
    gas_source = "quoter"
    
    result = RoundTripResult(
        pair=pair,
        buy_dex=buy_quote.get("dex_id", "unknown"),
        sell_dex=sell_quote.get("dex_id", "unknown"),
        amount_in_wei=buy_quote.get("amount_in_wei", 0),
        token_in=buy_quote.get("token_in", ""),
        token_out=buy_quote.get("token_out", ""),
        leg1_amount_out=0,
        l1_cost_source=l1_cost_source,  # v2.1.0: source tracking
        # v2.2.0: Leg provenance for fee/pool observability
        leg1_dex=buy_quote.get("dex_id", ""),
        leg2_dex=sell_quote.get("dex_id", ""),
        leg1_pool=buy_quote.get("pool_address", ""),
        leg2_pool=sell_quote.get("pool_address", ""),
        leg1_fee=buy_quote.get("fee", 0),
        leg2_fee=sell_quote.get("fee", 0),
    )
    
    # Leg 1: Extract from buy quote
    leg1_amount_out = buy_quote.get("amount_out_wei", 0)
    leg1_ticks = buy_quote.get("ticks_crossed") or 0
    
    # v2.1.0-fix: Use gas_override if provided (from eth_estimateGas)
    if gas_override is not None:
        leg1_gas = gas_override[0]
        gas_source = "eth_estimateGas"
    else:
        leg1_gas = buy_quote.get("gas_estimate") or 150_000
        if buy_quote.get("gas_estimate"):
            gas_source = "quoter"
        else:
            gas_source = "default"
    
    if not leg1_amount_out or leg1_amount_out <= 0:
        result.reject_reason = "LEG1_NO_AMOUNT_OUT"
        return result
    
    result.leg1_amount_out = leg1_amount_out
    result.leg1_gas_estimate = leg1_gas
    result.leg1_ticks_crossed = leg1_ticks
    result.leg1_success = True
    
    # Leg 2: Re-quote if callback provided, otherwise ratio estimate
    # v2.1.0-fix: Use gas_override[1] if provided
    if gas_override is not None:
        leg2_gas = gas_override[1]
    else:
        leg2_gas = sell_quote.get("gas_estimate") or 150_000
    leg2_ticks = sell_quote.get("ticks_crossed") or 0
    leg2_amount_out = 0
    leg2_is_real_quote = False
    
    if leg2_quote_callback:
        # v2.1.0: CANONICAL - use actual re-quote for leg2
        try:
            leg2_real_quote = leg2_quote_callback(leg1_amount_out)
            if leg2_real_quote and leg2_real_quote.get("amount_out_wei"):
                leg2_amount_out = leg2_real_quote["amount_out_wei"]
                leg2_gas = leg2_real_quote.get("gas_estimate", leg2_gas)
                leg2_ticks = leg2_real_quote.get("ticks_crossed", leg2_ticks)
                leg2_is_real_quote = True
                logger.debug("Leg2 real quote: amount_out=%d, gas=%d", leg2_amount_out, leg2_gas)
        except Exception as e:
            logger.warning("Leg2 re-quote failed: %s", e)
            leg2_is_real_quote = False
    
    if not leg2_is_real_quote:
        # DIAGNOSTIC: ratio estimate from existing sell_quote
        # This is an upper-bound estimate and NOT canonical profit
        sell_amount_in = sell_quote.get("amount_in_wei", 0)
        sell_amount_out = sell_quote.get("amount_out_wei", 0)
        
        if not sell_amount_in or not sell_amount_out or sell_amount_in <= 0:
            result.reject_reason = "LEG2_NO_QUOTE_DATA"
            return result
        
        # Estimate: scale by ratio
        ratio = Decimal(str(sell_amount_out)) / Decimal(str(sell_amount_in))
        leg2_amount_out = int(Decimal(str(leg1_amount_out)) * ratio)
        logger.debug("Leg2 ratio estimate: amount_out=%d (ratio=%s)", leg2_amount_out, ratio)
    
    result.leg2_amount_out = leg2_amount_out
    result.leg2_gas_estimate = leg2_gas
    result.leg2_ticks_crossed = leg2_ticks
    result.leg2_success = True
    result.leg2_is_real_quote = leg2_is_real_quote  # v2.1.0: Track quote method
    
    # Calculate totals
    result.total_ticks = (leg1_ticks or 0) + (leg2_ticks or 0)
    result.total_gas = (leg1_gas or 0) + (leg2_gas or 0)
    
    # Check ticks limit
    if result.total_ticks > max_ticks_crossed:
        result.reject_reason = f"TOTAL_TICKS_EXCEEDED: {result.total_ticks}>{max_ticks_crossed}"
        return result
    
    # Calculate PnL
    amount_in = result.amount_in_wei
    amount_back = result.leg2_amount_out
    
    result.gross_pnl_wei = amount_back - amount_in
    # v2.1.0: Unified gas model - L2 execution + L1 data overhead
    l2_gas_cost = result.total_gas * gas_price_wei
    result.gas_cost_wei = l2_gas_cost + l1_cost_wei
    # NOTE: net_pnl_wei mixes token-wei with ETH-wei for non-ETH tokens - 
    # use net_pnl_usd and net_pnl_bps for correct cross-token comparisons
    result.net_pnl_wei = result.gross_pnl_wei - result.gas_cost_wei
    
    # Calculate gross_pnl_bps (token-wei based, valid for same-unit comparison)
    if amount_in > 0:
        result.gross_pnl_bps = float(result.gross_pnl_wei) / float(amount_in) * 10000
    
    # v2.8.0: USD-denominated PnL for cross-token correctness
    # gas_cost is always in ETH wei, convert to USD
    result.gas_cost_usd = (result.gas_cost_wei / 1e18) * eth_usd_price
    
    # gross_pnl is in token_in wei - use token_in price if provided, else assume ETH
    effective_token_price = token_in_usd_price if token_in_usd_price else eth_usd_price
    result.gross_pnl_usd = (result.gross_pnl_wei / (10 ** token_in_decimals)) * effective_token_price
    result.net_pnl_usd = result.gross_pnl_usd - result.gas_cost_usd
    
    # v2.8.1: Calculate net_pnl_bps from USD values (fixes mixed-decimals bug)
    # net_pnl_bps = (net_pnl_usd / notional_usd) * 10000
    # This is the canonical profitability metric for cross-token comparisons
    if amount_in > 0 and effective_token_price > 0:
        notional_usd = (amount_in / (10 ** token_in_decimals)) * effective_token_price
        if notional_usd > 0:
            result.net_pnl_bps = (result.net_pnl_usd / notional_usd) * 10000
        else:
            result.net_pnl_bps = 0.0
    else:
        result.net_pnl_bps = 0.0
    
    # v2.1.0: Calculate slippage - prefer sqrtPriceAfter when available
    # Check for sqrt_price_after in quotes (from QuoterV2)
    buy_sqrt_before = buy_quote.get("sqrt_price_x96")
    buy_sqrt_after = buy_quote.get("sqrt_price_after")
    sell_sqrt_before = sell_quote.get("sqrt_price_x96") 
    sell_sqrt_after = sell_quote.get("sqrt_price_after")
    
    # Try measured slippage first
    total_measured_slippage = 0.0
    slippage_source = "ticks_heuristic"  # default
    
    if buy_sqrt_before and buy_sqrt_after:
        leg1_slippage, _ = calculate_slippage_from_sqrt_prices(buy_sqrt_before, buy_sqrt_after, is_buy=True)
        total_measured_slippage += abs(leg1_slippage)
        slippage_source = "sqrtPriceAfter"
    
    if sell_sqrt_before and sell_sqrt_after:
        leg2_slippage, _ = calculate_slippage_from_sqrt_prices(sell_sqrt_before, sell_sqrt_after, is_buy=False)
        total_measured_slippage += abs(leg2_slippage)
        slippage_source = "sqrtPriceAfter"
    
    if slippage_source == "sqrtPriceAfter" and total_measured_slippage > 0:
        result.estimated_slippage_bps = total_measured_slippage
        result.slippage_source = "sqrtPriceAfter"
    else:
        # Fallback: Heuristic ~0.5 bps per tick crossed
        result.estimated_slippage_bps = float(result.total_ticks) * 0.5
        result.slippage_source = "ticks_heuristic"
    
    # v2.8.0: Use USD-based profitability when token_in != WETH (gas units mismatch)
    # For WETH, wei-based comparison is fine; for others, use USD
    if token_in_usd_price is not None:
        # Non-WETH token_in: use USD for correctness
        result.is_profitable = result.net_pnl_usd > 0
    else:
        # WETH token_in: wei comparison is valid
        result.is_profitable = result.net_pnl_wei > 0
    
    # v2.1.0-fix: Set gas source for traceability
    result.gas_source = gas_source
    
    if not result.is_profitable:
        # v3.1.0: Detailed rejection classification
        # Calculate LP fee in bps (fee tier / 100)
        lp_fee_bps = (result.leg1_fee + result.leg2_fee) / 100.0
        
        # Calculate gas as bps of notional
        if amount_in > 0 and effective_token_price > 0:
            notional_usd = (amount_in / (10 ** token_in_decimals)) * effective_token_price
            gas_bps = (result.gas_cost_usd / notional_usd) * 10000 if notional_usd > 0 else 0
        else:
            gas_bps = 0
        
        # Classify the rejection reason
        reason = classify_rejection_reason(
            gross_pnl_bps=result.gross_pnl_bps,
            net_pnl_bps=result.net_pnl_bps,
            estimated_slippage_bps=result.estimated_slippage_bps,
            lp_fee_bps=lp_fee_bps,
            gas_bps=gas_bps,
        )
        result.reject_reason = f"{reason}: net_pnl_bps={result.net_pnl_bps:.2f}|slippage={result.estimated_slippage_bps:.1f}|lp_fee={lp_fee_bps:.1f}|gas={gas_bps:.1f}"
    
    return result


def evaluate_roundtrip_candidates(
    opportunities: list,
    buy_quotes_by_key: Dict[str, Dict],
    sell_quotes_by_key: Dict[str, Dict],
    gas_price_wei: int = 100_000_000,
    top_n: int = 5,
    leg2_quote_callback_factory: Optional[callable] = None,
    l1_cost_wei: int = 6_000_000_000_000,  # R36: L1 overhead for unified gas model (post-EIP-4844)
    l1_cost_source: str = "default",  # v2.1.0: "config" | "onchain" | "default"
    eth_usd_price: float = 2000.0,  # v2.8.0: For USD gas conversion
    token_usd_prices: Optional[Dict[str, float]] = None,  # v2.8.0: {"WBTC": 68000, "USDC": 1.0, ...}
    token_decimals: Optional[Dict[str, int]] = None,  # v2.8.0: {"WBTC": 8, "USDC": 6, ...}
) -> Tuple[list[RoundTripResult], RoundtripEvaluationStats]:
    """
    Evaluate top-N one-leg opportunities with round-trip simulation.
    
    v2.1.0 CONTRACT:
    - If `leg2_quote_callback_factory` is provided, leg2 uses ACTUAL QuoterV2 re-quote
    - Factory signature: (sell_quote: Dict) -> callable(amount_in_wei: int) -> Optional[Dict]
    - This enables CANONICAL round-trip profit (vs ratio estimate)
    
    v3.0.0 CONTRACT:
    - Returns (results, stats) tuple with aggregation visibility
    - stats.gated_by_economics: count of candidates filtered before evaluation
    - stats.rejected_reasons: Counter of reject reasons from results
    
    Args:
        opportunities: List of one-leg opportunity dicts (from opportunity_engine)
        buy_quotes_by_key: Dict mapping "dex_id:pool:fee" -> quote dict
        sell_quotes_by_key: Same for sell side
        gas_price_wei: Current gas price
        top_n: Number of candidates to evaluate
        leg2_quote_callback_factory: Optional factory to create leg2 re-quote callbacks
        
    Returns:
        Tuple of (List[RoundTripResult], RoundtripEvaluationStats)
    """
    results = []
    gated_count = 0  # v2.9.8: Count opportunities filtered by economics
    evaluated_count = 0  # v2.9.8: Count opportunities actually evaluated
    rejected_reasons: Dict[str, int] = {}  # v3.0.0: Track rejection reasons
    
    for opp in opportunities[:top_n]:
        # v2.9.8: Economics gate - skip if spread_minus_required_bps <= 0
        # This filters candidates that are mathematically unprofitable
        spread_minus_required = opp.get("spread_minus_required_bps")
        is_roundtrip_viable = opp.get("is_roundtrip_viable", False)  # v3.2.4: default False to gate unknowns
        
        if spread_minus_required is not None and spread_minus_required <= 0:
            gated_count += 1
            logger.debug(
                "Economics gate: skipping %s (spread_minus_required=%.2f bps)",
                opp.get("pair", "?"),
                spread_minus_required,
            )
            continue
        
        if not is_roundtrip_viable:
            gated_count += 1
            logger.debug(
                "Economics gate: skipping %s (is_roundtrip_viable=False)",
                opp.get("pair", "?"),
            )
            continue
        
        evaluated_count += 1
        buy_key = f"{opp.get('buy_dex')}:{opp.get('diagnostics', {}).get('buy_pool')}:{opp.get('buy_fee')}"
        sell_key = f"{opp.get('sell_dex')}:{opp.get('diagnostics', {}).get('sell_pool')}:{opp.get('sell_fee')}"
        
        buy_quote = buy_quotes_by_key.get(buy_key)
        sell_quote = sell_quotes_by_key.get(sell_key)
        
        if not buy_quote or not sell_quote:
            logger.debug("Missing quotes for roundtrip: buy=%s sell=%s", buy_key, sell_key)
            continue
        
        # v2.2.0 FIX: Correct roundtrip direction
        # For profitable arbitrage:
        # - Leg1: Sell token_in on sell_dex (HIGHER price = get MORE quote tokens)
        # - Leg2: Buy token_in on buy_dex (LOWER price = get MORE base tokens per quote)
        # So use sell_quote for leg1, buy_quote for leg2 callback
        leg2_callback = None
        if leg2_quote_callback_factory:
            try:
                leg2_callback = leg2_quote_callback_factory(buy_quote)  # v2.2.0: Use buy_quote for leg2
            except Exception as e:
                logger.debug("Leg2 callback factory failed: %s", e)
        
        # v2.2.0: Swap order - sell_quote for leg1, buy_quote for fallback leg2defensively
        # v2.8.0: Pass USD prices for cross-token correctness
        token_in = sell_quote.get("token_in", "WETH")
        token_in_price = None
        token_in_dec = 18
        if token_usd_prices and token_in in token_usd_prices:
            token_in_price = token_usd_prices[token_in]
        if token_decimals and token_in in token_decimals:
            token_in_dec = token_decimals[token_in]
        
        result = simulate_roundtrip(
            sell_quote, buy_quote, gas_price_wei,
            leg2_quote_callback=leg2_callback,
            l1_cost_wei=l1_cost_wei,
            l1_cost_source=l1_cost_source,
            eth_usd_price=eth_usd_price,
            token_in_usd_price=token_in_price,
            token_in_decimals=token_in_dec,
        )
        results.append(result)
        
        # v3.0.0: Track reject reasons
        if result.reject_reason:
            # Extract reason category (e.g., "NOT_PROFITABLE" from "NOT_PROFITABLE: net_pnl_bps=-42.15")
            reason_key = result.reject_reason.split(":")[0] if ":" in result.reject_reason else result.reject_reason
            rejected_reasons[reason_key] = rejected_reasons.get(reason_key, 0) + 1
    
    # v2.9.8: Log economics gating stats
    if gated_count > 0 or evaluated_count > 0:
        logger.info(
            "Roundtrip candidates: gated_by_economics=%d, evaluated=%d, results=%d",
            gated_count,
            evaluated_count,
            len(results),
        )
    
    # v3.0.0: Build aggregation stats
    # v3.2.4: Add warnings for L1 cost source issues
    warnings = []
    if l1_cost_source == "none":
        warnings.append("L1_COST_SOURCE_NONE: L1 cost unavailable, gas estimates may be inaccurate")
    elif l1_cost_source == "default":
        warnings.append("L1_COST_SOURCE_DEFAULT: Using fallback L1 cost, gas estimates may be inaccurate")
    
    stats = RoundtripEvaluationStats(
        candidates_total=min(len(opportunities), top_n),
        gated_by_economics=gated_count,
        evaluated_count=evaluated_count,
        results_count=len(results),
        rejected_reasons=rejected_reasons,
        warnings=warnings,
    )
    
    return results, stats


def estimate_slippage_bps(
    quote: Dict[str, Any],
    reference_price: Optional[Decimal] = None,
) -> Tuple[Decimal, str]:
    """
    v2.1.0: Estimate slippage from quoter vs reference price.
    
    Live slippage = (quoter_effective_price - reference_price) / reference_price * 10000
    
    Args:
        quote: Quote dict with 'price_exact' (quoter) and optionally 'slot0_price'
        reference_price: Optional reference price (if None, uses slot0_price from quote)
        
    Returns:
        Tuple of (slippage_bps, method_used)
        - slippage_bps: Positive = worse than reference (buying more expensive, selling cheaper)
        - method_used: "slot0" | "provided" | "none"
    """
    quoter_price = quote.get("price_exact")
    if not quoter_price:
        return Decimal("0"), "none"
    
    quoter_price = Decimal(str(quoter_price))
    
    # Determine reference price
    if reference_price:
        ref = Decimal(str(reference_price))
        method = "provided"
    else:
        slot0 = quote.get("slot0_price") or quote.get("sqrtPriceX96_slot0")
        if slot0:
            ref = Decimal(str(slot0))
            method = "slot0"
        else:
            return Decimal("0"), "none"
    
    if ref == 0:
        return Decimal("0"), method
    
    # Calculate slippage: (actual - expected) / expected * 10000
    slippage_bps = (quoter_price - ref) / ref * Decimal("10000")
    return slippage_bps, method


def probe_slippage(
    quote_small: Dict[str, Any],
    quote_target: Dict[str, Any],
) -> Tuple[Decimal, Dict[str, Any]]:
    """
    v2.1.0: Probe slippage by comparing small notional vs target notional quotes.
    
    Live slippage = (target_effective_price - small_effective_price) / small_effective_price * 10000
    
    The small quote approximates zero-impact price; target quote shows actual slippage.
    
    Args:
        quote_small: Quote for small amount (e.g., 1% of target)
        quote_target: Quote for target amount (e.g., $1000)
        
    Returns:
        Tuple of (slippage_bps, diagnostics_dict)
        - slippage_bps: Positive = worse price for target (more slippage)
        - diagnostics: {small_price, target_price, small_amount, target_amount}
    """
    small_price = quote_small.get("price_exact")
    target_price = quote_target.get("price_exact")
    
    diag = {
        "small_amount_in": quote_small.get("amount_in_wei"),
        "target_amount_in": quote_target.get("amount_in_wei"),
        "small_price": str(small_price) if small_price else None,
        "target_price": str(target_price) if target_price else None,
        "method": "probe_small_vs_target",
    }
    
    if not small_price or not target_price:
        return Decimal("0"), {**diag, "error": "missing_price"}
    
    small_p = Decimal(str(small_price))
    target_p = Decimal(str(target_price))
    
    if small_p == 0:
        return Decimal("0"), {**diag, "error": "small_price_zero"}
    
    # Slippage: how much worse is target vs small
    slippage_bps = (target_p - small_p) / small_p * Decimal("10000")
    
    diag["slippage_bps"] = float(slippage_bps)
    return slippage_bps, diag


def calculate_slippage_from_sqrt_prices(
    sqrt_price_before: Optional[int],
    sqrt_price_after: Optional[int],
    is_buy: bool = True,
) -> Tuple[float, str]:
    """
    v2.1.0: Calculate measured slippage from sqrtPriceX96 before/after.
    
    sqrtPriceX96 = sqrt(price) * 2^96
    price = (sqrtPriceX96 / 2^96)^2
    
    Slippage = (price_after - price_before) / price_before * 10000 bps
    
    For buys: positive slippage = price moved up (worse for buyer)
    For sells: positive slippage = price moved down (worse for seller)
    
    Args:
        sqrt_price_before: sqrtPriceX96 before swap (from slot0)
        sqrt_price_after: sqrtPriceX96 after swap (from quoter)
        is_buy: True if this is a buy (token_in -> token_out)
        
    Returns:
        Tuple of (slippage_bps, source)
        - slippage_bps: Signed slippage in basis points
        - source: "sqrtPriceAfter" if valid, "none" if data missing
    """
    if sqrt_price_before is None or sqrt_price_after is None:
        return 0.0, "none"
    
    if sqrt_price_before == 0:
        return 0.0, "none"
    
    try:
        # Convert to floats for calculation
        Q96 = 2 ** 96
        
        price_before = (sqrt_price_before / Q96) ** 2
        price_after = (sqrt_price_after / Q96) ** 2
        
        if price_before == 0:
            return 0.0, "none"
        
        # Calculate slippage in bps
        slippage_bps = (price_after - price_before) / price_before * 10000
        
        # For sells, slippage direction is reversed
        if not is_buy:
            slippage_bps = -slippage_bps
        
        return round(slippage_bps, 2), "sqrtPriceAfter"
        
    except Exception:
        return 0.0, "none"


def classify_rejection_reason(
    gross_pnl_bps: float,
    net_pnl_bps: float,
    estimated_slippage_bps: float,
    lp_fee_bps: float,
    gas_bps: float,
) -> str:
    """
    v3.1.0: Classify why a roundtrip is unprofitable.
    
    Given the cost breakdown, determine which factor dominates:
    - SLIPPAGE_TOO_HIGH: slippage > 50% of cost and is the largest factor
    - LP_FEES_TOO_HIGH: LP fees > 50% of cost and is the largest factor
    - GAS_TOO_HIGH: gas > 30% of cost and is significant
    - NET_PROFIT_TOO_LOW: general unprofitable (balanced costs)
    
    Args:
        gross_pnl_bps: Gross profit in bps (before gas)
        net_pnl_bps: Net profit in bps (after gas)
        estimated_slippage_bps: Estimated slippage in bps
        lp_fee_bps: LP fee in bps (leg1_fee + leg2_fee) / 100
        gas_bps: Gas cost as bps of notional
        
    Returns:
        Classification string: SLIPPAGE_TOO_HIGH, LP_FEES_TOO_HIGH, GAS_TOO_HIGH, or NET_PROFIT_TOO_LOW
    """
    # Total cost = what ate into the gross spread (or made it negative)
    total_cost_bps = abs(estimated_slippage_bps) + lp_fee_bps + gas_bps
    
    if total_cost_bps == 0:
        return "NET_PROFIT_TOO_LOW"
    
    # Calculate cost proportions
    slippage_pct = abs(estimated_slippage_bps) / total_cost_bps * 100
    lp_fee_pct = lp_fee_bps / total_cost_bps * 100
    gas_pct = gas_bps / total_cost_bps * 100
    
    # Classification logic: which cost component dominates?
    # Slippage dominates if > 40% and biggest single factor
    if slippage_pct > 40 and abs(estimated_slippage_bps) >= max(lp_fee_bps, gas_bps):
        return "SLIPPAGE_TOO_HIGH"
    
    # LP fees dominate if > 50%
    if lp_fee_pct > 50 and lp_fee_bps >= max(abs(estimated_slippage_bps), gas_bps):
        return "LP_FEES_TOO_HIGH"
    
    # Gas dominates if > 30% and significant
    if gas_pct > 30 and gas_bps >= max(abs(estimated_slippage_bps), lp_fee_bps):
        return "GAS_TOO_HIGH"
    
    # Balanced costs - general unprofitable
    return "NET_PROFIT_TOO_LOW"


# ---------------------------------------------------------------------------
# v3.3.0: Canonical dynamic size sweep — truth-probe mechanism for optimal
# notional sizing.  Uses CANONICAL_SWEEP_SIZES_USD by default.
# ---------------------------------------------------------------------------

@dataclass
class SizeSweepPoint:
    """Result of one notional step in the sweep."""
    size_usd: float
    net_pnl_bps: Optional[float] = None
    gross_pnl_bps: Optional[float] = None
    measured_slippage_bps: Optional[float] = None
    gas_bps: Optional[float] = None
    fee_bps: Optional[float] = None
    error: Optional[str] = None


@dataclass
class SizeSweepResult:
    """Aggregated result from sweeping multiple notional sizes."""
    pair: str
    buy_dex: str
    sell_dex: str
    sizes_evaluated: int = 0
    best_size_usd: Optional[float] = None
    best_net_pnl_bps: Optional[float] = None
    best_gross_pnl_bps: Optional[float] = None
    frontier_reason: str = "NO_DATA"
    gap_to_zero_bps: Optional[float] = None
    # Cost decomposition at the best point
    best_gas_bps: Optional[float] = None
    best_fee_bps: Optional[float] = None
    best_slippage_bps: Optional[float] = None
    best_total_cost_bps: Optional[float] = None
    points: Optional[List[SizeSweepPoint]] = None

    def __post_init__(self):
        if self.points is None:
            self.points = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair": self.pair,
            "buy_dex": self.buy_dex,
            "sell_dex": self.sell_dex,
            "sizes_evaluated": self.sizes_evaluated,
            "best_size_usd": self.best_size_usd,
            "best_net_pnl_bps": round(self.best_net_pnl_bps, 2) if self.best_net_pnl_bps is not None else None,
            "best_gross_pnl_bps": round(self.best_gross_pnl_bps, 2) if self.best_gross_pnl_bps is not None else None,
            "frontier_reason": self.frontier_reason,
            "gap_to_zero_bps": round(self.gap_to_zero_bps, 2) if self.gap_to_zero_bps is not None else None,
            "best_gas_bps": round(self.best_gas_bps, 2) if self.best_gas_bps is not None else None,
            "best_fee_bps": round(self.best_fee_bps, 2) if self.best_fee_bps is not None else None,
            "best_slippage_bps": round(self.best_slippage_bps, 2) if self.best_slippage_bps is not None else None,
            "best_total_cost_bps": round(self.best_total_cost_bps, 2) if self.best_total_cost_bps is not None else None,
            "points": [
                {
                    "size_usd": p.size_usd,
                    "net_pnl_bps": round(p.net_pnl_bps, 2) if p.net_pnl_bps is not None else None,
                    "gross_pnl_bps": round(p.gross_pnl_bps, 2) if p.gross_pnl_bps is not None else None,
                    "measured_slippage_bps": round(p.measured_slippage_bps, 2) if p.measured_slippage_bps is not None else None,
                    "gas_bps": round(p.gas_bps, 2) if p.gas_bps is not None else None,
                    "fee_bps": round(p.fee_bps, 2) if p.fee_bps is not None else None,
                    "error": p.error,
                }
                for p in (self.points or [])
            ],
        }


def sweep_roundtrip_sizes(
    buy_quote_base: Dict[str, Any],
    sell_quote_base: Dict[str, Any],
    requote_leg1,
    requote_leg2,
    sizes_usd: Optional[List[float]] = None,
    token_in_usd_price: float = 0.0,
    token_in_decimals: int = 18,
    gas_price_wei: int = 100_000_000,
    l1_cost_wei: int = 6_000_000_000_000,  # R36: Post-EIP-4844 default
    l1_cost_source: str = "default",
    eth_usd_price: float = 2000.0,
) -> SizeSweepResult:
    """Sweep multiple notional sizes for a single opportunity route.

    This is the **canonical truth-probe mechanism** for finding the optimal
    notional size.  By default ``sizes_usd`` falls back to
    ``CANONICAL_SWEEP_SIZES_USD`` so the ladder is bounded, deterministic,
    and identical across sessions.

    For each size, re-quotes both legs via *requote_leg1* / *requote_leg2*
    and runs ``simulate_roundtrip`` to find the best net_pnl_bps.
    """
    if sizes_usd is None:
        sizes_usd = list(CANONICAL_SWEEP_SIZES_USD)
    pair = f"{buy_quote_base.get('token_in', '')}/{buy_quote_base.get('token_out', '')}"
    result = SizeSweepResult(
        pair=pair,
        buy_dex=buy_quote_base.get("dex_id", ""),
        sell_dex=sell_quote_base.get("dex_id", ""),
    )

    if token_in_usd_price <= 0:
        result.frontier_reason = "TOKEN_PRICE_ZERO"
        return result

    best_net: Optional[float] = None

    for size_usd in sizes_usd:
        # Convert USD → token_in wei
        amount_in_wei = int(
            (Decimal(str(size_usd)) / Decimal(str(token_in_usd_price)))
            * (Decimal(10) ** token_in_decimals)
        )
        if amount_in_wei <= 0:
            result.points.append(SizeSweepPoint(size_usd=size_usd, error="AMOUNT_ZERO"))
            continue

        # Re-quote leg1 at this size
        try:
            leg1_q = requote_leg1(amount_in_wei)
        except Exception as e:
            logger.warning("Sweep leg1 requote failed at $%s: %s", size_usd, e)
            result.points.append(SizeSweepPoint(size_usd=size_usd, error="LEG1_QUOTE_FAIL"))
            continue
        if not leg1_q or not leg1_q.get("amount_out_wei"):
            result.points.append(SizeSweepPoint(size_usd=size_usd, error="LEG1_QUOTE_FAIL"))
            continue

        leg1_amount_out = leg1_q["amount_out_wei"]

        # Re-quote leg2 using leg1's actual output as input
        try:
            leg2_q = requote_leg2(leg1_amount_out)
        except Exception as e:
            logger.warning("Sweep leg2 requote failed at $%s: %s", size_usd, e)
            result.points.append(SizeSweepPoint(size_usd=size_usd, error="LEG2_QUOTE_FAIL"))
            continue
        if not leg2_q or not leg2_q.get("amount_out_wei"):
            result.points.append(SizeSweepPoint(size_usd=size_usd, error="LEG2_QUOTE_FAIL"))
            continue

        # Build synthetic quote dicts for simulate_roundtrip
        synth_buy = {
            **buy_quote_base,
            "amount_in_wei": amount_in_wei,
            "amount_out_wei": leg1_q["amount_out_wei"],
            "gas_estimate": leg1_q.get("gas_estimate", 150_000),
            "ticks_crossed": leg1_q.get("ticks_crossed", 0),
            "sqrt_price_x96": leg1_q.get("sqrt_price_x96") or buy_quote_base.get("sqrt_price_x96"),
            "sqrt_price_after": leg1_q.get("sqrt_price_after"),
        }
        synth_sell = {
            **sell_quote_base,
            "amount_in_wei": leg1_amount_out,
            "amount_out_wei": leg2_q["amount_out_wei"],
            "gas_estimate": leg2_q.get("gas_estimate", 150_000),
            "ticks_crossed": leg2_q.get("ticks_crossed", 0),
            "sqrt_price_x96": leg2_q.get("sqrt_price_x96") or sell_quote_base.get("sqrt_price_x96"),
            "sqrt_price_after": leg2_q.get("sqrt_price_after"),
        }

        # Capture leg2_q for lambda closure
        _leg2_out = leg2_q["amount_out_wei"]
        _leg2_gas = leg2_q.get("gas_estimate", 150_000)
        _leg2_ticks = leg2_q.get("ticks_crossed", 0)

        rt = simulate_roundtrip(
            buy_quote=synth_buy,
            sell_quote=synth_sell,
            gas_price_wei=gas_price_wei,
            l1_cost_wei=l1_cost_wei,
            l1_cost_source=l1_cost_source,
            eth_usd_price=eth_usd_price,
            token_in_usd_price=token_in_usd_price,
            token_in_decimals=token_in_decimals,
            leg2_quote_callback=lambda _amt, _out=_leg2_out, _gas=_leg2_gas, _tc=_leg2_ticks: {
                "amount_out_wei": _out,
                "gas_estimate": _gas,
                "ticks_crossed": _tc,
            },
        )

        # Gas as bps of notional
        gas_bps_val = (rt.gas_cost_usd / size_usd) * 10000 if size_usd > 0 else 0
        # LP fee as bps (fee tier is in ppm: 3000 = 30 bps)
        fee_bps_val = (rt.leg1_fee + rt.leg2_fee) / 100.0

        # R39i: Degenerate result guard — gross PnL exactly zero AND slippage
        # exactly zero signals a broken re-quote (output == input, no price
        # impact measured).  Real routes always have non-zero spread or slippage.
        is_degenerate = (
            rt.gross_pnl_bps == 0.0
            and rt.estimated_slippage_bps == 0.0
        )

        if is_degenerate:
            result.points.append(
                SizeSweepPoint(size_usd=size_usd, error="DEGENERATE_ZERO")
            )
            continue

        point = SizeSweepPoint(
            size_usd=size_usd,
            net_pnl_bps=rt.net_pnl_bps,
            gross_pnl_bps=rt.gross_pnl_bps,
            measured_slippage_bps=rt.estimated_slippage_bps,
            gas_bps=gas_bps_val,
            fee_bps=fee_bps_val,
        )
        result.points.append(point)

        if best_net is None or rt.net_pnl_bps > best_net:
            best_net = rt.net_pnl_bps
            result.best_size_usd = size_usd
            result.best_net_pnl_bps = rt.net_pnl_bps
            result.best_gross_pnl_bps = rt.gross_pnl_bps
            result.best_gas_bps = gas_bps_val
            result.best_fee_bps = fee_bps_val
            result.best_slippage_bps = rt.estimated_slippage_bps
            result.best_total_cost_bps = gas_bps_val + fee_bps_val + rt.estimated_slippage_bps

    result.sizes_evaluated = len([p for p in result.points if p.error is None])

    # R39i: Slippage quality gate — if the best point has unmeasured slippage
    # (ticks_heuristic fallback with ticks=0 → 0.0 bps), do not promote to
    # BREAKEVEN/PROFITABLE.  Real routes always incur some slippage.
    slippage_unmeasured = (
        result.best_slippage_bps is not None
        and result.best_slippage_bps == 0.0
    )

    if result.best_net_pnl_bps is not None and result.best_net_pnl_bps > 0:
        if slippage_unmeasured:
            result.frontier_reason = "SUSPECT_ZERO_SLIPPAGE"
            result.gap_to_zero_bps = 0.0
        else:
            result.frontier_reason = "PROFITABLE"
            result.gap_to_zero_bps = 0.0
    elif result.best_net_pnl_bps is not None and result.best_net_pnl_bps == 0.0:
        if slippage_unmeasured:
            result.frontier_reason = "SUSPECT_ZERO_SLIPPAGE"
            result.gap_to_zero_bps = 0.0
        else:
            result.frontier_reason = "BREAKEVEN_FRONTIER"
            result.gap_to_zero_bps = 0.0
    elif result.best_net_pnl_bps is not None:
        result.frontier_reason = "BEST_NEG"
        result.gap_to_zero_bps = abs(result.best_net_pnl_bps)
    elif result.sizes_evaluated == 0:
        result.frontier_reason = "ALL_FAILED"

    return result
