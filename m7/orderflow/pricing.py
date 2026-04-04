"""
M7 orderflow pricing: classification, estimation, simple live scoring,
gas decomposition, and size sweep.

The heavy parallel scoring pipeline lives in scoring_parallel.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    CHAINLINK_DECIMALS,
    CHAINLINK_FEEDS_ARBITRUM,
    CHAINLINK_LATEST_ROUND_SELECTOR,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    MIN_EVENT_SIZE_USD,
    SIGNIFICANT_IMPACT_BPS,
    REJECT_EVENT_TOO_SMALL,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_QUOTE_FAILURE,
    REJECT_STALE_POSITIVE,
    M7A4_CHAIN,
    _DEFAULT_FEE_TIERS,
    _FALLBACK_ETH_PRICE_USD,
    _REF_MIN_WEI_18,
    _REF_MAX_WEI_18,
)
from m7.orderflow.contracts import BackrunResult, OrderflowEvent

logger = logging.getLogger("m7.orderflow.pricing")

def _normalized_bounds(
    token_decimals: int,
    default_18_min: int = _REF_MIN_WEI_18,
    default_18_max: int = _REF_MAX_WEI_18,
) -> tuple:
    """Return (min_wei, max_wei) adjusted for token decimals.

    For 18-decimal tokens this returns the original bounds unchanged.
    For 6-decimal tokens (USDC/USDT) the bounds shrink by 10**12 so
    that the notional range stays comparable in human-readable units
    (0.001 .. 1.0 of the token).
    """
    if token_decimals is None or token_decimals == 18:
        return (default_18_min, default_18_max)
    ratio = 10 ** max(0, 18 - token_decimals)
    mn = max(1, default_18_min // ratio)
    mx = max(1, default_18_max // ratio)
    return (mn, mx)


# M7.A.5.9: Gas denomination conversion
_FALLBACK_ETH_PRICE_USD = 3500.0  # conservative fallback when oracle unavailable



def _gas_cost_in_token_wei(
    gas_cost_eth_wei: int,
    token_decimals: Optional[int],
    token_price_usd: Optional[float] = None,
    eth_price_usd: Optional[float] = None,
) -> int:
    """Convert gas cost from ETH wei to the backrun token's raw units.

    Gas is always paid in ETH.  For the bps formula
    ``(net_pnl / amount_in) * 10000`` to be meaningful, gas must be
    expressed in the **same denomination** as the backrun token.

    * 18-decimal token with no explicit USD price → assumed ETH; returns
      ``gas_cost_eth_wei`` unchanged.
    * Otherwise: convert via ``gas_eth * eth_usd / tok_usd * 10^dec / 10^18``.
      Falls back to ``_FALLBACK_ETH_PRICE_USD`` and ``$1`` for stablecoins.
    """
    dec = token_decimals if token_decimals is not None else 18
    if dec == 18 and token_price_usd is None:
        return gas_cost_eth_wei  # assume ETH-denominated token
    _eth = eth_price_usd if eth_price_usd and eth_price_usd > 0 else _FALLBACK_ETH_PRICE_USD
    _tok = token_price_usd if token_price_usd and token_price_usd > 0 else 1.0
    # gas_token_wei = gas_cost_eth_wei / 10^18 * eth_usd / tok_usd * 10^dec
    gas_token_wei = int(gas_cost_eth_wei * _eth * (10 ** dec) / (_tok * 10 ** 18))
    return max(1, gas_token_wei)


# Canonical chain for M7.A.4/M7.A.5 (same as M7.A: arbitrum_one)
M7A4_CHAIN = "arbitrum_one"

# Uniswap V3 Swap event topic (shared across V3 forks)
SWAP_EVENT_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

# Default number of recent blocks to scan for live events
DEFAULT_LIVE_BLOCKS = 5


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

    # M7.A.5.9: Infer token_in decimals from symbol for size normalization
    _backrun_token_in_sym = event.token_out  # backrun buys what user sold
    _live_dec: Optional[int] = None
    if _backrun_token_in_sym.upper() in ("USDC", "USDT", "USDC.e", "USDT.e"):
        _live_dec = 6
    elif _backrun_token_in_sym.upper() in ("WBTC",):
        _live_dec = 8
    _live_min, _live_max = _normalized_bounds(_live_dec if _live_dec is not None else 18)
    backrun_size_wei = max(_live_min, min(_live_max, backrun_size_wei))

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

    # M7.A.5.9: Convert gas to backrun token denomination
    _gas_eth_wei = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)
    gas_cost_wei = _gas_cost_in_token_wei(_gas_eth_wei, _live_dec)

    # Compute measured net from best quotes
    if best_buy_amount is not None and best_sell_amount is not None:
        # Gross = what we get selling minus what we spend buying
        # We buy token_out with backrun_size_wei of token_in → get best_buy_amount
        # We sell best_buy_amount of token_out → get best_sell_amount of token_in
        # Net = best_sell_amount - backrun_size_wei (in token_in units)
        gross_wei = best_sell_amount - backrun_size_wei
        net_wei = gross_wei - gas_cost_wei
        net_bps = (net_wei / backrun_size_wei) * 10000 if backrun_size_wei > 0 else 0.0

        # M7.A.5.10: Stale-gate — positive but stale quotes are not executable
        if net_bps > 0 and block_lag <= 2:
            route_viable = True
            reject_reason = None
        elif net_bps > 0:
            route_viable = False
            reject_reason = REJECT_STALE_POSITIVE
        else:
            route_viable = False
            reject_reason = REJECT_GAS_EXCEEDS_GROSS

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
    token_in_decimals: Optional[int] = None,
    gas_cost_token_wei: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Run a bounded size sweep (3-5 sizes) around a base notional.

    Returns list of dicts with: size_wei, gross_pnl_wei, gas_cost_wei,
    net_pnl_wei, net_bps, buy_venue, sell_venue.
    """
    from strategy.quote_rpc import read_quoter_v2, QUOTER_RATE_LIMITED

    # Build 5-point ladder: 0.2x, 0.5x, 1x, 2x, 5x of base
    multipliers = [0.2, 0.5, 1.0, 2.0, 5.0]
    # M7.A.5.9: decimal-aware bounds
    MIN_WEI, MAX_WEI = _normalized_bounds(token_in_decimals if token_in_decimals is not None else 18)
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
        _sweep_gas = gas_cost_token_wei if gas_cost_token_wei is not None else int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)
        net_wei = gross_wei - _sweep_gas
        net_bps = (net_wei / size_wei) * 10000 if size_wei > 0 else 0.0

        results.append({
            "size_wei": size_wei,
            "gross_pnl_wei": gross_wei,
            "gas_cost_wei": _sweep_gas,
            "net_pnl_wei": net_wei,
            "net_bps": round(net_bps, 4),
            "buy_venue": best_buy_venue,
            "sell_venue": best_sell_venue,
        })

    return results



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


# M7.A.5.37: Module-level cache for oracle sanity results.
# Oracle is "sanity guardrail, not execution truth" — cached results are
# acceptable if queried within 50 blocks (~100s on Arbitrum). This drops
# oracle_ms from ~104ms to 0ms for repeated token pairs.
_oracle_cache: Dict[str, tuple] = {}  # key → (block_num, result_dict)
_ORACLE_CACHE_STALE_BLOCKS = 50


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

    # M7.A.5.37: Check cache before RPC
    _cache_key = f"{token_in_symbol or ''}|{token_out_symbol or ''}"
    _cached = _oracle_cache.get(_cache_key)
    if _cached is not None:
        _cached_block, _cached_result = _cached
        if abs(block_num - _cached_block) <= _ORACLE_CACHE_STALE_BLOCKS:
            return dict(_cached_result)  # return copy

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

        MAX_STALENESS_SECONDS = 3600
        if result["oracle_staleness_seconds"] and result["oracle_staleness_seconds"] > MAX_STALENESS_SECONDS:
            result["oracle_guard_triggered"] = True

    except Exception as exc:
        logger.debug("check_oracle_sanity failed: %s", str(exc)[:100])

    # M7.A.5.37: Store in cache
    _oracle_cache[_cache_key] = (block_num, dict(result))

    return result

