# PATH: strategy/spreads.py
"""
Spread signal computation logic.

Extracted from run_scan_real.py for modularity.
Contains functions for computing spread signals from quotes.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from m4.policy import Thresholds

logger = logging.getLogger("strategy.spreads")


def is_suspect_spread_value(spread_bps: float) -> bool:
    """Check if spread_bps exceeds the SUSPECT threshold (300 bps).
    
    Suspect spreads are likely due to low-liquidity pools and may not
    represent real arbitrage opportunities.
    
    Args:
        spread_bps: Spread in basis points
        
    Returns:
        True if spread > SUSPECT_SPREAD_BPS (300)
    """
    return abs(spread_bps) > Thresholds.SUSPECT_SPREAD_BPS


def is_excluded_spread_value(spread_bps: float) -> bool:
    """Check if spread_bps exceeds the EXCLUDE threshold (500 bps).
    
    Excluded spreads are so high they are almost certainly not real arb
    opportunities. These signals are excluded from DoD metrics.
    
    Args:
        spread_bps: Spread in basis points
        
    Returns:
        True if spread > SUSPECT_SPREAD_BPS_HARD (500)
    """
    return abs(spread_bps) > Thresholds.SUSPECT_SPREAD_BPS_HARD


def compute_spread_signals(
    quotes_sample: List[Dict[str, Any]],
    config: Dict[str, Any],
    current_block: int,
    rejected_quotes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compute spread signals from quotes.
    
    v2.2.0: When truth_mode_m42=true, diagnostic-only quotes (slot0)
    are excluded from spread computation.
    
    Args:
        quotes_sample: List of quote dicts
        config: Configuration dict
        current_block: Current block number
        rejected_quotes: List to append rejected quotes to
        
    Returns:
        List of spread signal dicts
    """
    spread_signals: List[Dict[str, Any]] = []
    spread_threshold_bps = config.get("min_spread_bps", config.get("spread_threshold_bps", 0))
    max_spread_bps_sanity = config.get("max_spread_bps_sanity", 10000)
    truth_mode = config.get("truth_mode_m42", False)
    
    # v2.2.0: Filter out diagnostic-only quotes when truth_mode=true
    executable_quotes = quotes_sample
    diagnostic_count = 0
    if truth_mode:
        executable_quotes = []
        for q in quotes_sample:
            if q.get("is_diagnostic_only", False):
                diagnostic_count += 1
            else:
                executable_quotes.append(q)
        
        if diagnostic_count > 0:
            logger.info("truth_mode_m42: excluded %d diagnostic-only (slot0) quotes from spread evaluation",
                       diagnostic_count)
    
    logger.info("Starting spread signal computation: %d quotes (%d diagnostic excluded), threshold=%s bps", 
                len(executable_quotes), diagnostic_count, spread_threshold_bps)
    
    try:
        # Group quotes by pair
        quotes_by_pair: Dict[str, List[Dict[str, Any]]] = {}
        for q in executable_quotes:
            pair_key = f"{q.get('token_in')}/{q.get('token_out')}"
            if pair_key not in quotes_by_pair:
                quotes_by_pair[pair_key] = []
            quotes_by_pair[pair_key].append(q)
        
        logger.info("Grouped quotes: %s", {k: len(v) for k, v in quotes_by_pair.items()})
        
        for pair, quotes_for_pair in quotes_by_pair.items():
            if len(quotes_for_pair) < 2:
                continue
            
            # v2.5.2: _compute_pair_spread returns a LIST of signals (0-2)
            # This enables dual cross-DEX routes for diversity
            signals = _compute_pair_spread(
                pair, quotes_for_pair, config, current_block,
                spread_threshold_bps, max_spread_bps_sanity, rejected_quotes
            )
            spread_signals.extend(signals)
        
        logger.info("Computed %d spread signals (threshold: %d bps)", 
                    len(spread_signals), spread_threshold_bps)
    except Exception as e:
        logger.warning("Failed to compute spread signals: %s", e)
    
    return spread_signals


def _get_price(q: Dict[str, Any]) -> Decimal:
    """Get price from quote, preferring price_exact."""
    if q.get("price_exact"):
        return Decimal(str(q.get("price_exact")))
    return Decimal(str(q.get("price") or "0"))



def _compute_pair_spread(
    pair: str,
    quotes_for_pair: List[Dict[str, Any]],
    config: Dict[str, Any],
    current_block: int,
    spread_threshold_bps: int,
    max_spread_bps_sanity: int,
    rejected_quotes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Compute spread signals for a single pair.
    
    v2.5.2: ALWAYS prefer cross-DEX combinations. Returns a LIST of signals.
    When emit_dual_routes=true (default), emits BOTH cross-DEX directions
    if both are net-positive, enabling unique_routes_cross_dex >= 2.
    
    Returns:
        List of spread signal dicts (0-2 signals per pair)
    """
    signals = []
    emit_dual_routes = config.get("emit_dual_routes", True)  # Default: emit both directions
    
    # v2.5.2: ALWAYS try cross-DEX first (not just when require_cross_dex=True)
    all_cross_dex = _find_all_cross_dex_spreads(quotes_for_pair, config, spread_threshold_bps)
    
    if all_cross_dex:
        for result in all_cross_dex:
            best_buy, best_sell, buy_price, sell_price = result
            spread_bps_decimal = (sell_price - buy_price) / buy_price * Decimal("10000")
            
            # Check sanity
            if abs(spread_bps_decimal) > max_spread_bps_sanity:
                continue
            
            # Check pool addresses
            buy_pool = best_buy.get("pool_address")
            sell_pool = best_sell.get("pool_address")
            if not buy_pool or not sell_pool:
                continue
            
            spread_bps = int(spread_bps_decimal)
            route = f"{best_buy.get('dex_id')}->{best_sell.get('dex_id')}"
            logger.info(
                "Spread calc (CROSS-DEX %s): %s buy=%s@%s sell=%s@%s spread_bps=%s",
                route, pair, buy_price, best_buy.get("dex_id"), 
                sell_price, best_sell.get("dex_id"), spread_bps_decimal
            )
            
            signal = _build_spread_signal(
                pair, best_buy, best_sell, buy_price, sell_price,
                spread_bps_decimal, spread_bps, config, current_block
            )
            signals.append(signal)
            
            # If not emitting dual routes, stop after first cross-DEX signal
            if not emit_dual_routes:
                break
        
        # If we got any cross-DEX signals, return them (don't fall back to same-DEX)
        if signals:
            return signals
    
    # Fallback: standard logic (min/max regardless of DEX) - only if no cross-DEX found
    sorted_by_price = sorted(quotes_for_pair, key=_get_price)
    best_buy = sorted_by_price[0]
    best_sell = sorted_by_price[-1]
    
    buy_price = _get_price(best_buy)
    sell_price = _get_price(best_sell)
    
    if buy_price <= 0 or sell_price <= 0:
        return []
    
    # Verify pool addresses
    buy_pool = best_buy.get("pool_address")
    sell_pool = best_sell.get("pool_address")
    if not buy_pool or not sell_pool:
        logger.warning("INVALID_SPREAD: %s - missing pool address", pair)
        return []
    
    # Calculate spread in bps
    spread_bps_decimal = (sell_price - buy_price) / buy_price * Decimal("10000")
    spread_bps = int(spread_bps_decimal)
    
    # Price outlier detection
    if abs(spread_bps_decimal) > max_spread_bps_sanity:
        logger.error("PRICE_OUTLIER: %s spread=%s bps exceeds sanity limit %s", 
                     pair, spread_bps_decimal, max_spread_bps_sanity)
        rejected_quotes.append({
            "pair": pair,
            "buy_dex": best_buy.get("dex_id"),
            "sell_dex": best_sell.get("dex_id"),
            "reason": "PRICE_OUTLIER",
            "gate_passed": False,
            "spread_bps": float(spread_bps_decimal),
            "max_allowed_bps": max_spread_bps_sanity,
            "error": f"Spread {spread_bps_decimal} bps exceeds sanity limit",
        })
        return []
    
    logger.info(
        "Spread calc (FALLBACK): %s buy=%s sell=%s spread_bps=%s threshold=%s",
        pair, buy_price, sell_price, spread_bps_decimal, spread_threshold_bps
    )
    
    # Only record if spread exceeds threshold
    if abs(spread_bps_decimal) < spread_threshold_bps:
        return []
    
    signal = _build_spread_signal(
        pair, best_buy, best_sell, buy_price, sell_price,
        spread_bps_decimal, spread_bps, config, current_block
    )
    return [signal]


def _find_all_cross_dex_spreads(
    quotes_for_pair: List[Dict[str, Any]],
    config: Dict[str, Any],
    spread_threshold_bps: int,
) -> List[Tuple[Dict[str, Any], Dict[str, Any], Decimal, Decimal]]:
    """
    Find ALL profitable cross-DEX spread combinations.
    
    v2.5.2: Returns a list of (best_buy, best_sell, buy_price, sell_price) tuples
    for BOTH directions (A->B and B->A) when both are profitable.
    This enables unique_routes_cross_dex >= 2 in rolling metrics.
    
    Returns:
        List of tuples, each representing a profitable cross-DEX spread
    """
    # Group quotes by DEX
    quotes_by_dex: Dict[str, List[Dict[str, Any]]] = {}
    for q in quotes_for_pair:
        dex_id = q.get("dex_id", "unknown")
        if dex_id not in quotes_by_dex:
            quotes_by_dex[dex_id] = []
        quotes_by_dex[dex_id].append(q)
    
    # Need at least 2 different DEXes for cross-DEX
    dex_ids = list(quotes_by_dex.keys())
    if len(dex_ids) < 2:
        return []
    
    results = []
    seen_routes = set()
    
    # Find all profitable cross-DEX combinations (both directions)
    for buy_dex in dex_ids:
        for sell_dex in dex_ids:
            if buy_dex == sell_dex:
                continue
            
            route = f"{buy_dex}->{sell_dex}"
            if route in seen_routes:
                continue
            
            # Find min price in buy_dex (where we buy)
            buy_quotes = quotes_by_dex[buy_dex]
            buy_quote = min(buy_quotes, key=_get_price)
            buy_price = _get_price(buy_quote)
            
            # Find max price in sell_dex (where we sell)
            sell_quotes = quotes_by_dex[sell_dex]
            sell_quote = max(sell_quotes, key=_get_price)
            sell_price = _get_price(sell_quote)
            
            if buy_price <= 0 or sell_price <= 0:
                continue
            
            # Check pool addresses
            if not buy_quote.get("pool_address") or not sell_quote.get("pool_address"):
                continue
            
            # Calculate spread
            spread = (sell_price - buy_price) / buy_price * Decimal("10000")
            
            # Only include if spread is positive and above threshold
            if spread >= spread_threshold_bps:
                results.append((buy_quote, sell_quote, buy_price, sell_price))
                seen_routes.add(route)
    
    # Sort by spread (highest first)
    results.sort(key=lambda r: (r[3] - r[2]) / r[2], reverse=True)
    
    return results
    
    best_result = None
    best_spread = Decimal("-999999")
    
    # Find best cross-DEX combination
    for buy_dex in dex_ids:
        for sell_dex in dex_ids:
            if buy_dex == sell_dex:
                continue
            
            # Find min price in buy_dex (where we buy)
            buy_quotes = quotes_by_dex[buy_dex]
            buy_quote = min(buy_quotes, key=_get_price)
            buy_price = _get_price(buy_quote)
            
            # Find max price in sell_dex (where we sell)
            sell_quotes = quotes_by_dex[sell_dex]
            sell_quote = max(sell_quotes, key=_get_price)
            sell_price = _get_price(sell_quote)
            
            if buy_price <= 0 or sell_price <= 0:
                continue
            
            # Check pool addresses
            if not buy_quote.get("pool_address") or not sell_quote.get("pool_address"):
                continue
            
            # Calculate spread
            spread = (sell_price - buy_price) / buy_price * Decimal("10000")
            
            if spread > best_spread:
                best_spread = spread
                best_result = (buy_quote, sell_quote, buy_price, sell_price)
    
    return best_result


def _build_spread_signal(
    pair: str,
    best_buy: Dict[str, Any],
    best_sell: Dict[str, Any],
    buy_price: Decimal,
    sell_price: Decimal,
    spread_bps_decimal: Decimal,
    spread_bps: int,
    config: Dict[str, Any],
    current_block: int,
) -> Dict[str, Any]:
    """Build spread signal dict with PnL estimates."""
    # Paper cost estimates
    paper_size_usd = Decimal(str(config.get("paper_size_usd", 1000)))
    size_source = "config" if "paper_size_usd" in config else "default"
    
    gross_pnl_usdc = float(paper_size_usd * spread_bps_decimal / Decimal(10000))
    
    gas_usd_estimate = float(config.get("gas_usd_estimate", 0.10))
    gas_source = "config" if "gas_usd_estimate" in config else "default"
    
    slippage_bps = Decimal(str(config.get("paper_slippage_bps", 0)))
    slippage_source = "config" if "paper_slippage_bps" in config else "default"
    slippage_usd_estimate = float(paper_size_usd * slippage_bps / Decimal(10000))
    
    net_pnl_usdc_estimate = gross_pnl_usdc - gas_usd_estimate - slippage_usd_estimate
    
    # Confidence reasons
    confidence_reasons = []
    if abs(spread_bps) < 5:
        confidence_reasons.append("micro_spread")
    if not config.get("execution_enabled", False):
        confidence_reasons.append("execution_disabled")
    confidence_reasons.append("paper_cost_model")
    
    # v2.0.3: Suspect spread detection (unrealistic arb due to low liquidity)
    # Spreads > 300 bps are often illusions from low-liquidity pools
    suspect_spread_bps = config.get("suspect_spread_bps", 300)
    suspect_spread_hard = config.get("suspect_spread_bps_hard", 500)
    is_suspect_spread = abs(spread_bps_decimal) > suspect_spread_bps
    is_excluded_spread = abs(spread_bps_decimal) > suspect_spread_hard
    
    if is_excluded_spread:
        confidence_reasons.append("SUSPECT_SPREAD_EXCLUDED")
    elif is_suspect_spread:
        confidence_reasons.append("SUSPECT_SPREAD")
    
    # v2.1.0: Quote source tracking for truth_mode_m42
    buy_quote_source = best_buy.get("quote_source", "unknown")
    sell_quote_source = best_sell.get("quote_source", "unknown")
    buy_dex = best_buy.get("dex_id", "unknown")
    sell_dex = best_sell.get("dex_id", "unknown")
    is_mixed_source = buy_quote_source != sell_quote_source
    is_slot0_only = buy_quote_source == "slot0" or sell_quote_source == "slot0"
    is_quoter_v2_both = buy_quote_source == "quoter_v2" and sell_quote_source == "quoter_v2"
    
    # v2.2.0: LP fee tracking for roundtrip estimation
    # Fee tier: 500 = 0.05% = 5 bps, 3000 = 0.30% = 30 bps, 100 = 0.01% = 1 bps
    buy_fee = best_buy.get("fee", 3000)  # default to 3000 if not specified
    sell_fee = best_sell.get("fee", 3000)
    lp_fee_bps_roundtrip = float(buy_fee + sell_fee) / 100  # roundtrip touches both pools
    lp_fee_usdc_est = float(paper_size_usd) * lp_fee_bps_roundtrip / 10000
    
    # v2.2.0: Updated net estimate includes LP fees (more realistic for roundtrip)
    net_pnl_after_lp_fee_usdc = net_pnl_usdc_estimate - lp_fee_usdc_est
    
    # v2.5.0: Same-dex detection (fee-tier arb within same DEX)
    is_same_dex = buy_dex == sell_dex
    is_same_dex_excluded = is_same_dex and config.get("require_cross_dex", False)
    if is_same_dex:
        confidence_reasons.append("SAME_DEX_FEE_TIER")
    if is_same_dex_excluded:
        confidence_reasons.append("SAME_DEX_EXCLUDED")
    
    # v2.1.0: Mark slot0/mixed-source as diagnostic only when truth_mode_m42=true
    is_diagnostic_only = (
        config.get("truth_mode_m42", False) and 
        (is_slot0_only or is_mixed_source)
    )
    if is_slot0_only:
        confidence_reasons.append("SLOT0_DIAGNOSTIC")
    if is_mixed_source:
        confidence_reasons.append("MIXED_SOURCE_DIAGNOSTIC")
    
    spread_bps_ui_display = int(spread_bps_decimal)
    
    net_negative_reason = None
    if net_pnl_usdc_estimate < 0:
        if float(spread_bps_decimal) < 1.0:
            net_negative_reason = "micro_spread_net_negative_due_to_gas"
        else:
            net_negative_reason = "costs_exceed_gross"
    
    tokens = pair.split("/")
    token_in = tokens[0] if len(tokens) > 0 else ""
    token_out = tokens[1] if len(tokens) > 1 else ""
    
    return {
        "pair": pair,
        "buy_dex": best_buy.get("dex_id"),
        "sell_dex": best_sell.get("dex_id"),
        "buy_price": str(round(buy_price, 6)),
        "sell_price": str(round(sell_price, 6)),
        "buy_pool": best_buy.get("pool_address"),
        "sell_pool": best_sell.get("pool_address"),
        # v2.2.0: Buy/sell fee tiers for LP fee estimation
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
        "price_direction": "quote_out_per_1_base_in",
        "price_note": f"1 {token_in} = X {token_out}",
        "spread_bps_exact": round(float(spread_bps_decimal), 4),
        "spread_bps_ui": spread_bps_ui_display,
        "spread_pct": round(float(spread_bps_decimal) / 100, 6),
        "spread_frac": str(round(spread_bps_decimal / Decimal(10000), 10)),
        "block_number": current_block,
        "is_gross_positive": bool(spread_bps_decimal > 0),
        "size_usd": float(paper_size_usd),
        "size_source": size_source,
        "gross_pnl_usdc_est": round(gross_pnl_usdc, 4),
        "gas_usd_estimate": gas_usd_estimate,
        "gas_source": gas_source,
        "slippage_bps": float(slippage_bps),
        "slippage_usd_estimate": round(slippage_usd_estimate, 4),
        "slippage_source": slippage_source,
        "net_pnl_usdc_est": round(net_pnl_usdc_estimate, 4),
        "is_net_positive_est": net_pnl_usdc_estimate > 0,
        # v2.2.0: LP fee estimation for roundtrip-aware filtering
        "lp_fee_bps_roundtrip": round(lp_fee_bps_roundtrip, 2),
        "lp_fee_usdc_est": round(lp_fee_usdc_est, 4),
        "net_pnl_after_lp_fee_usdc": round(net_pnl_after_lp_fee_usdc, 4),
        "is_net_positive_after_lp_fee": net_pnl_after_lp_fee_usdc > 0,
        "net_negative_reason": net_negative_reason,
        # v2.0.3: Suspect spread flags (unrealistic arb detection)
        "is_suspect_spread": is_suspect_spread,
        "is_excluded_spread": is_excluded_spread or is_same_dex_excluded,  # v2.5.0: also exclude same-dex when require_cross_dex
        "suspect_spread_threshold_bps": suspect_spread_bps,
        # v2.5.0: Same-dex detection (potential fee-tier arb)
        "is_same_dex": is_same_dex,
        "is_same_dex_excluded": is_same_dex_excluded,
        "buy_dex_id": buy_dex,
        "sell_dex_id": sell_dex,
        # v2.1.0: Quote source tracking for truth_mode_m42
        "buy_quote_source": buy_quote_source,
        "sell_quote_source": sell_quote_source,
        "is_quoter_v2_both": is_quoter_v2_both,
        "is_slot0_only": is_slot0_only,
        "is_mixed_source": is_mixed_source,
        "is_diagnostic_only": is_diagnostic_only,
        # Confidence downgrades if suspect or same-dex-excluded
        "confidence": "suspect" if (is_excluded_spread or is_same_dex_excluded) else (
            "low" if not config.get("execution_enabled", False) or is_suspect_spread else (
                "high" if abs(spread_bps) >= 20 else "medium" if abs(spread_bps) >= 10 else "low"
            )
        ),
        "confidence_reasons": confidence_reasons,
    }
