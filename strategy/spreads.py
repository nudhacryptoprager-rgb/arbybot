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
            
            signal = _compute_pair_spread(
                pair, quotes_for_pair, config, current_block,
                spread_threshold_bps, max_spread_bps_sanity, rejected_quotes
            )
            if signal:
                spread_signals.append(signal)
        
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
) -> Dict[str, Any] | None:
    """
    Compute spread signal for a single pair.
    
    Returns:
        Spread signal dict or None if no valid spread found
    """
    sorted_by_price = sorted(quotes_for_pair, key=_get_price)
    best_buy = sorted_by_price[0]
    best_sell = sorted_by_price[-1]
    
    buy_price = _get_price(best_buy)
    sell_price = _get_price(best_sell)
    
    if buy_price <= 0 or sell_price <= 0:
        return None
    
    # Verify pool addresses
    buy_pool = best_buy.get("pool_address")
    sell_pool = best_sell.get("pool_address")
    if not buy_pool or not sell_pool:
        logger.warning("INVALID_SPREAD: %s - missing pool address", pair)
        return None
    
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
        return None
    
    logger.info(
        "Spread calc: %s buy=%s sell=%s spread_bps=%s threshold=%s",
        pair, buy_price, sell_price, spread_bps_decimal, spread_threshold_bps
    )
    
    # Only record if spread exceeds threshold
    if abs(spread_bps_decimal) < spread_threshold_bps:
        return None
    
    return _build_spread_signal(
        pair, best_buy, best_sell, buy_price, sell_price,
        spread_bps_decimal, spread_bps, config, current_block
    )


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
    is_mixed_source = buy_quote_source != sell_quote_source
    is_slot0_only = buy_quote_source == "slot0" or sell_quote_source == "slot0"
    is_quoter_v2_both = buy_quote_source == "quoter_v2" and sell_quote_source == "quoter_v2"
    
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
        "net_negative_reason": net_negative_reason,
        # v2.0.3: Suspect spread flags (unrealistic arb detection)
        "is_suspect_spread": is_suspect_spread,
        "is_excluded_spread": is_excluded_spread,
        "suspect_spread_threshold_bps": suspect_spread_bps,
        # v2.1.0: Quote source tracking for truth_mode_m42
        "buy_quote_source": buy_quote_source,
        "sell_quote_source": sell_quote_source,
        "is_quoter_v2_both": is_quoter_v2_both,
        "is_slot0_only": is_slot0_only,
        "is_mixed_source": is_mixed_source,
        "is_diagnostic_only": is_diagnostic_only,
        # Confidence downgrades if suspect
        "confidence": "suspect" if is_excluded_spread else (
            "low" if not config.get("execution_enabled", False) or is_suspect_spread else (
                "high" if abs(spread_bps) >= 20 else "medium" if abs(spread_bps) >= 10 else "low"
            )
        ),
        "confidence_reasons": confidence_reasons,
    }
