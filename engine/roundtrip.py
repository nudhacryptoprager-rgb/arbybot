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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("engine.roundtrip")


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
    
    # Quality flags
    is_profitable: bool = False
    reject_reason: Optional[str] = None
    
    # Diagnostics
    gross_pnl_bps: float = 0.0  # for comparison with one-leg
    net_pnl_bps: float = 0.0
    total_ticks: int = 0
    total_gas: int = 0
    # v2.1.0: Slippage estimate from ticks (heuristic: ~0.5 bps per tick in V3)
    # TODO v2.2.0: Replace with measured slippage from sqrtPriceAfter (QuoterV2 output)
    #   - sqrtPriceAfter = price AFTER swap, gives exact slippage vs sqrtPriceBefore
    #   - requires adapter changes to expose sqrtPriceAfter in quote dict
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
        }


def simulate_roundtrip(
    buy_quote: Dict[str, Any],
    sell_quote: Dict[str, Any],
    gas_price_wei: int = 100_000_000,  # 0.1 gwei default (Arbitrum)
    max_ticks_crossed: int = 30,  # Total for both legs
    leg2_quote_callback: Optional[callable] = None,  # v2.1.0: Optional re-quote function
    l1_cost_wei: int = 60_000_000_000_000,  # v2.1.0: L1 overhead (~$0.12 at 2000 gas * 30 gwei)
    l1_cost_source: str = "default",  # v2.1.0: "config" | "onchain" | "default"
    gas_override: Optional[Tuple[int, int]] = None,  # v2.1.0-fix: (leg1_gas, leg2_gas) from eth_estimateGas
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
    result.net_pnl_wei = result.gross_pnl_wei - result.gas_cost_wei
    
    # Calculate bps for comparison
    if amount_in > 0:
        result.gross_pnl_bps = float(result.gross_pnl_wei) / float(amount_in) * 10000
        result.net_pnl_bps = float(result.net_pnl_wei) / float(amount_in) * 10000
    
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
    
    result.is_profitable = result.net_pnl_wei > 0
    
    # v2.1.0-fix: Set gas source for traceability
    result.gas_source = gas_source
    
    if not result.is_profitable:
        result.reject_reason = f"NOT_PROFITABLE: net_pnl_bps={result.net_pnl_bps:.2f}"
    
    return result


def evaluate_roundtrip_candidates(
    opportunities: list,
    buy_quotes_by_key: Dict[str, Dict],
    sell_quotes_by_key: Dict[str, Dict],
    gas_price_wei: int = 100_000_000,
    top_n: int = 5,
    leg2_quote_callback_factory: Optional[callable] = None,
    l1_cost_wei: int = 60_000_000_000_000,  # v2.1.0: L1 overhead for unified gas model
    l1_cost_source: str = "default",  # v2.1.0: "config" | "onchain" | "default"
) -> list[RoundTripResult]:
    """
    Evaluate top-N one-leg opportunities with round-trip simulation.
    
    v2.1.0 CONTRACT:
    - If `leg2_quote_callback_factory` is provided, leg2 uses ACTUAL QuoterV2 re-quote
    - Factory signature: (sell_quote: Dict) -> callable(amount_in_wei: int) -> Optional[Dict]
    - This enables CANONICAL round-trip profit (vs ratio estimate)
    
    Args:
        opportunities: List of one-leg opportunity dicts (from opportunity_engine)
        buy_quotes_by_key: Dict mapping "dex_id:pool:fee" -> quote dict
        sell_quotes_by_key: Same for sell side
        gas_price_wei: Current gas price
        top_n: Number of candidates to evaluate
        leg2_quote_callback_factory: Optional factory to create leg2 re-quote callbacks
        
    Returns:
        List of RoundTripResult for top candidates
    """
    results = []
    
    for opp in opportunities[:top_n]:
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
        result = simulate_roundtrip(sell_quote, buy_quote, gas_price_wei, leg2_quote_callback=leg2_callback, l1_cost_wei=l1_cost_wei, l1_cost_source=l1_cost_source)
        results.append(result)
    
    return results


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
