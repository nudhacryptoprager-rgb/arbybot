# PATH: strategy/quotes.py
"""
Quote collection logic for scan jobs.

Extracted from run_scan_real.py for modularity.
Contains functions for fetching quotes from DEX pools.
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Dict, List, Optional, Tuple

from config.pairs import load_pairs, get_pool_address, is_pool_disabled, PairConfig
from config import get_token_address  # v3.2.17: core_tokens.yaml fallback
from strategy.compat import QuoteCompat
from strategy.quarantine import get_quarantine_manager
from strategy.dynamic_anchors import get_anchor_manager
from strategy.runtime_disabled import (
    is_runtime_disabled,
    auto_disable_pool,
    record_quote_success,
)

# v2.0.4: Import canonical pool_key builder
from core.pool_keys import make_pool_key


# =============================================================================
# CASE-INSENSITIVE LOOKUP HELPERS (v3.2.24+)
# =============================================================================

def lookup_anchor_price_ci(
    anchor_dict: Dict[str, float],
    pair_tag: str,
) -> Optional[float]:
    """
    Case-insensitive lookup for tokens_anchor_price.
    
    v3.2.24: Fixes wstETH/WSTETH case mismatch issue where config uses
    'wstETH_WETH' but runtime may generate 'WSTETH_WETH'.
    
    Args:
        anchor_dict: The tokens_anchor_price dict from config
        pair_tag: Pair tag to lookup (e.g., "WSTETH_WETH")
        
    Returns:
        Anchor price if found, None otherwise
    """
    # Direct lookup first (fast path)
    if pair_tag in anchor_dict:
        return anchor_dict[pair_tag]
    
    # Case-insensitive lookup
    pair_upper = pair_tag.upper()
    for key, value in anchor_dict.items():
        if key.upper() == pair_upper:
            return value
    
    return None


def lookup_token_usd_price_ci(
    usd_dict: Dict[str, float],
    symbol: str,
    default: Optional[float] = None,
) -> Optional[float]:
    """
    Case-insensitive lookup for tokens_usd_price.
    
    v3.2.25: Fixes wstETH/WSTETH case mismatch issue where config uses
    'wstETH' but runtime may generate 'WSTETH'.
    
    Args:
        usd_dict: The tokens_usd_price dict from config
        symbol: Token symbol to lookup (e.g., "WSTETH")
        default: Default value if not found
        
    Returns:
        USD price if found, else default
    """
    # Direct lookup first (fast path)
    if symbol in usd_dict:
        return usd_dict[symbol]
    
    # Case-insensitive lookup
    symbol_upper = symbol.upper()
    for key, value in usd_dict.items():
        if key.upper() == symbol_upper:
            return value
    
    return default


# =============================================================================
# TOKEN ADDRESS RESOLUTION (v3.2.17)
# =============================================================================

def resolve_token_address(
    symbol: str,
    pair_cfg: Optional[PairConfig],
    config_tokens: Dict[str, str],
    chain_key: str,
    is_token_in: bool = True,
) -> str:
    """
    Resolve token address with fallback chain: pair_cfg -> config.tokens -> core_tokens.yaml.
    
    v3.2.17: Intent-driven discovery sets pair_cfg.token_in_address / token_out_address.
    This function ensures those addresses are used first, with graceful fallbacks.
    
    Args:
        symbol: Token symbol (e.g., 'WETH')
        pair_cfg: PairConfig object (may have token_in_address/token_out_address)
        config_tokens: config.get("tokens", {}) from YAML
        chain_key: Chain identifier for core_tokens.yaml lookup
        is_token_in: True for token_in, False for token_out
        
    Returns:
        Token address or empty string if not found
    """
    # Priority 1: pair_cfg from discovery_runtime (intent-driven)
    if pair_cfg is not None:
        addr = pair_cfg.token_in_address if is_token_in else pair_cfg.token_out_address
        if addr:
            return addr
    
    # Priority 2: config["tokens"] from YAML
    addr = config_tokens.get(symbol, "")
    if addr:
        return addr
    
    # Priority 3: core_tokens.yaml canonical addresses
    addr = get_token_address(chain_key, symbol)
    if addr:
        return addr
    
    return ""

logger = logging.getLogger("strategy.quotes")

from strategy.quote_rpc import (
    _get_shared_w3,
    _get_shared_quote_executor,
    clear_multicall_cache,
    clear_shared_w3_cache,
    get_cached_liquidity,
    get_cached_slot0,
    prefetch_slot0_multicall,
    read_quoter_v2,
    read_slot0_v3,
)
from strategy.quote_adapters import (
    read_algebra_quoter,
    read_ve33_amount_out,
    synthesize_sqrt_price_from_anchor,
    calculate_price_from_sqrt,
)
from strategy.quote_policy import (
    get_runtime_filter_switches as _get_runtime_filter_switches,
    apply_price_sanity_gate,
)
from strategy.quote_metrics import (
    init_quote_counts,
    init_quoter_matrix,
    finalize_quote_counts,
)


# =============================================================================
# USD-NOTIONAL SIZING (M4.2)
# =============================================================================

# Default USD prices for common tokens (for sizing, not profit calc)
DEFAULT_TOKEN_USD_PRICES = {
    "WETH": 2000.0,
    "ETH": 2000.0,
    "WBTC": 34000.0,
    "USDC": 1.0,
    "USDT": 1.0,
    "DAI": 1.0,
    "ARB": 0.70,
    "LINK": 11.0,
    "GMX": 24.0,
    "wstETH": 2300.0,
    "UNI": 6.0,
    "AAVE": 100.0,
    "GNS": 1.50,
    "PENDLE": 1.30,
    "RETH": 2400.0,
    "rETH": 2400.0,
    "TBTC": 68000.0,
    "tBTC": 68000.0,
    "EZETH": 2050.0,
    "ezETH": 2050.0,
    "STONE": 2100.0,
    "weETH": 2100.0,
    "mETH": 2100.0,
    # R28.22: Per-chain NO_USD_PRICE fixes
    "GRAIL": 1.50,
    "MAGIC": 0.30,
    "RDNT": 0.01,
    "HOLD": 0.003,
    "BRETT": 0.05,
    "cbBTC": 68000.0,
    "CBBTC": 68000.0,
    "DEGEN": 0.005,
    "TOSHI": 0.0003,
    "FRAX": 1.0,
    "LUSD": 1.0,
    "USDE": 1.0,
    "JOE": 0.25,
    "DPX": 5.0,
    "WMNT": 0.50,
    "ZK": 0.10,
    "SCR": 0.50,
    "AERO": 0.50,
    "cbETH": 2200.0,
}


# =============================================================================
# R32: QUOTER_V2 SKIP CACHE — skip quoter_v2 for pools with repeated failures
# =============================================================================
# Pools where quoter_v2 consistently fails (low/dust liquidity) waste RPC calls
# and inflate QUOTER_V2_FAILED counts.  After QUOTER_V2_SKIP_THRESHOLD consecutive
# failures the quoter call is bypassed and the pool goes directly to slot0 diagnostic.
# The cache entry expires after QUOTER_V2_SKIP_TTL_SECONDS so the quoter is retried
# periodically in case liquidity improves.

import time as _time

_quoter_v2_fail_counts: Dict[str, int] = {}        # pool_key → consecutive fail count
_quoter_v2_skip_since: Dict[str, float] = {}        # pool_key → timestamp when skip started

QUOTER_V2_SKIP_THRESHOLD = 3      # skip after this many consecutive failures
QUOTER_V2_SKIP_TTL_SECONDS = 600  # 10 min: retry quoter_v2 to detect liquidity recovery


def _should_skip_quoter_v2(pool_key: str) -> bool:
    """Return True if quoter_v2 should be skipped for this pool (repeated failures)."""
    cnt = _quoter_v2_fail_counts.get(pool_key, 0)
    if cnt < QUOTER_V2_SKIP_THRESHOLD:
        return False
    since = _quoter_v2_skip_since.get(pool_key, 0.0)
    if _time.time() - since > QUOTER_V2_SKIP_TTL_SECONDS:
        # TTL expired — reset and allow retry
        _quoter_v2_fail_counts.pop(pool_key, None)
        _quoter_v2_skip_since.pop(pool_key, None)
        return False
    return True


def _record_quoter_v2_failure(pool_key: str) -> None:
    """Track a quoter_v2 failure for skip-cache purposes."""
    prev = _quoter_v2_fail_counts.get(pool_key, 0)
    _quoter_v2_fail_counts[pool_key] = prev + 1
    if prev + 1 >= QUOTER_V2_SKIP_THRESHOLD and pool_key not in _quoter_v2_skip_since:
        _quoter_v2_skip_since[pool_key] = _time.time()


def _record_quoter_v2_success(pool_key: str) -> None:
    """Reset skip-cache on quoter_v2 success (liquidity recovered)."""
    _quoter_v2_fail_counts.pop(pool_key, None)
    _quoter_v2_skip_since.pop(pool_key, None)


def calculate_amount_in_wei(
    token_symbol: str,
    decimals: int,
    target_usd_notional: float,
    tokens_usd_price: Optional[Dict[str, float]] = None,
) -> int:
    """
    Calculate amount_in_wei for a given USD notional target.
    
    M4.2 CONTRACT:
    - All quotes use consistent USD notional (e.g., $1000)
    - This makes profit metrics comparable across pairs
    
    Args:
        token_symbol: Input token symbol (e.g., "WETH")
        decimals: Token decimals
        target_usd_notional: Target USD value (e.g., 1000.0)
        tokens_usd_price: Optional price overrides
        
    Returns:
        Amount in wei (int)
    """
    # Merge config prices with defaults
    prices = dict(DEFAULT_TOKEN_USD_PRICES)
    if tokens_usd_price:
        prices.update(tokens_usd_price)
    
    # Get token USD price
    # v3.2.33: Use case-insensitive lookup (WEETH/weETH, WSTETH/wstETH)
    token_price = lookup_token_usd_price_ci(prices, token_symbol, default=1.0)
    
    # v2.2.3: Warn if using default fallback price (not from config)
    # v3.2.33: Use case-insensitive check for this warning too
    if tokens_usd_price and lookup_token_usd_price_ci(tokens_usd_price, token_symbol) is None:
        if token_symbol in DEFAULT_TOKEN_USD_PRICES:
            logger.warning("USD_PRICE_FALLBACK_USED: %s using default $%.2f (not in config)", 
                          token_symbol, token_price)
    
    if token_price <= 0:
        logger.warning("Invalid token price for %s: %s, using $1", token_symbol, token_price)
        token_price = 1.0
    
    # Calculate token amount for target USD notional
    token_amount = target_usd_notional / token_price
    
    # Convert to wei
    amount_in_wei = int(token_amount * (10 ** decimals))
    
    logger.debug(
        "USD-notional sizing: %s $%.0f -> %.6f tokens -> %d wei",
        token_symbol, target_usd_notional, token_amount, amount_in_wei
    )
    
    return amount_in_wei


def collect_quotes(
    config: Dict[str, Any],
    current_block: int,
    rpc_latency: int = 0,
    pairs_list: Optional[List[PairConfig]] = None,  # v2.6.0: Allow passing pre-resolved pairs
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Collect quotes from DEX pools.
    
    Args:
        config: Configuration dict
        current_block: Current block number
        rpc_latency: RPC latency in ms
        pairs_list: Optional pre-resolved pairs (for discovery_runtime mode)
        
    Returns:
        (quotes_sample, rejected_quotes, counts)
    """
    quotes_sample: List[Dict[str, Any]] = []
    rejected_quotes: List[Dict[str, Any]] = []
    
    counts = init_quote_counts()
    quoter_matrix = init_quoter_matrix()
    
    # v2.3.0: Track failed pool addresses for actionable diagnostics
    failed_pool_addresses: List[Dict[str, str]] = []
    
    # v2.3.1: Track pool_missing_keys for observability (what pools were skipped)
    pool_missing_keys: List[str] = []
    
    # v3.2.7: Strict chain_key contract - 'unknown' if missing (warning issued in run_scan_real)
    chain_key = config.get("chain", "unknown")
    
    # v3.2.12: Guardrail - log WARN if chain_key is 'unknown' (misconfig protection)
    if chain_key == "unknown":
        logger.warning(
            "CHAIN_KEY_UNKNOWN: config missing 'chain' field - persistence will use legacy paths. "
            "For proper chain-scoped caching, set 'chain' in config (e.g., 'arbitrum_one', 'linea')."
        )
    
    # v3.2.11: Get chain-scoped managers to prevent cross-chain cache pollution
    # Get quarantine manager for runtime auto-quarantine
    qm = get_quarantine_manager(chain_key=chain_key)
    runtime_filter_switches = _get_runtime_filter_switches(config)
    quarantine_enabled = runtime_filter_switches["quarantine_enabled"]
    runtime_disabled_enabled = runtime_filter_switches["runtime_disabled_enabled"]
    if not quarantine_enabled or not runtime_disabled_enabled:
        logger.warning(
            "RUNTIME_FILTER_SWITCHES: quarantine_enabled=%s runtime_disabled_enabled=%s",
            quarantine_enabled,
            runtime_disabled_enabled,
        )
    
    # Get dynamic anchor manager
    am = get_anchor_manager(chain_key=chain_key)
    
    # v3.2.11: Get runtime disabled manager with chain scope
    from strategy.runtime_disabled import get_runtime_disabled_manager
    get_runtime_disabled_manager(chain_key=chain_key)  # Initialize chain-scoped singleton
    
    dexes_list = config.get("dexes") or []
    pools_cfg = config.get("pools", {}) or {}
    token_addresses = config.get("tokens", {}) or {}
    if pairs_list is None:
        # v2.3.1 FIX: Respect universe_source from config
        universe_source = config.get("universe_source", "config")
        use_intent = (universe_source == "intent")
        force_intent = (universe_source in ("intent_verified", "intent_forced"))
        pairs_list = load_pairs(chain_key, config, use_intent=use_intent, force_intent=force_intent)
    
    if not pairs_list:
        from config.pairs import get_pair_info
        fallback_pair = get_pair_info(chain_key, "WETH", "USDC")
        if fallback_pair:
            pairs_list = [fallback_pair]
    
    logger.info("Scanning %d pairs: %s", len(pairs_list), [p.display_name for p in pairs_list])
    
    # RPC URL for slot0 reads
    # v3.2.32: Config rpc_endpoints take priority over env (multi-chain safety)
    rpc_url = (config.get("rpc_endpoints") or [None])[0] or os.environ.get("ARBY_RPC_HTTP_PRIMARY")
    skip_rpc = os.environ.get("ARBY_SKIP_RPC") == "1"
    tokens_anchor_price = config.get("tokens_anchor_price") or {}
    
    # v2.2.0: Multicall prefetch for slot0 batching (Roadmap M5_0 requirement)
    use_multicall = config.get("use_multicall", True)  # Default ON for v2.2.0
    if use_multicall and rpc_url and not skip_rpc:
        # Collect all pool addresses that will be queried
        all_pool_addrs: List[str] = []
        for pair_cfg in pairs_list:
            # v2.6.0: Use pre-resolved pool_addresses if available (discovery_runtime)
            if pair_cfg.pool_addresses:
                all_pool_addrs.extend(pair_cfg.pool_addresses)
            else:
                # Fall back to config lookup
                token_pair_tag = pair_cfg.pair_tag
                fee_tiers = pair_cfg.fee_tiers or [500, 3000]
                for dex in dexes_list:
                    from dex.registry import get_dex_config
                    dex_cfg = get_dex_config(chain_key, dex)
                    adapter_type = dex_cfg.adapter_type if dex_cfg else None
                    
                    if adapter_type == "algebra":
                        effective_fees = [0]
                    else:
                        effective_fees = fee_tiers
                    
                    for fee in effective_fees:
                        pool_addr = get_pool_address(config, dex, token_pair_tag, fee_tier=fee)
                        if pool_addr:
                            all_pool_addrs.append(pool_addr)
        
        # Unique pool addresses
        unique_pools = list(set(all_pool_addrs))
        if unique_pools:
            logger.info("Multicall prefetch: %d unique pools", len(unique_pools))
            clear_multicall_cache()  # Clear cache before prefetch
            prefetch_slot0_multicall(unique_pools, rpc_url, current_block)
            # R28.5: Expose multicall stats for performance observability
            try:
                from core.multicall import get_multicall_batcher
                _mc_batcher = get_multicall_batcher(rpc_url, current_block)
                counts["multicall_stats"] = _mc_batcher.get_stats()
            except Exception:
                pass
    
    # M4.2: USD-notional sizing
    # R29: discovery_probe_size_usd is the canonical key for quote-stage sizing.
    # Falls back to target_usd_notional (legacy) for backward compatibility.
    # This is a discovery probe — NOT the execution truth size.
    target_usd_notional = config.get(
        "discovery_probe_size_usd",
        config.get("target_usd_notional", 1000.0),
    )
    tokens_usd_price = config.get("tokens_usd_price") or {}
    use_usd_notional = config.get("use_usd_notional", True)  # Default ON for M4.2

    # R28.13 Step 8: Cross-pair parallel quoter prefetch
    # Phase A: Build work items for ALL pairs and submit ALL quoter futures at once.
    # Phase B: Resolve all futures in bulk (cross-pair parallelism).
    # Phase C: Process pairs sequentially using pre-resolved results.
    _global_prefetch_futures: Dict[str, Any] = {}
    _global_prefetch_results: Dict[str, Any] = {}
    _pair_work_data: list[tuple[Any, list, Any, Any, Any, Any, Optional[str]]] = []
    # ^^ (pair_cfg, pool_work_items, anchor_price, anchor_source, amount_in_wei_pf, pf_tin, pf_tout)

    _pf_exec = _get_shared_quote_executor()

    for pair_cfg in pairs_list:
        token_pair_tag = pair_cfg.pair_tag
        token_in = pair_cfg.token_in
        token_out = pair_cfg.token_out
        decimals_in = pair_cfg.token_in_decimals
        decimals_out = pair_cfg.token_out_decimals

        # Viability filter (same as inner loop)
        if use_usd_notional:
            merged_prices = dict(DEFAULT_TOKEN_USD_PRICES)
            merged_prices.update(tokens_usd_price)
            token_in_price = lookup_token_usd_price_ci(merged_prices, token_in)
            if token_in_price is None or token_in_price <= 0:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": "_pre_routing",
                    "fee": 0,
                    "reason": "NO_USD_PRICE",
                    "gate_passed": False,
                    "error": f"Token {token_in} has no USD price in config or defaults (use_usd_notional=true)",
                })
                counts["no_usd_price"] = counts.get("no_usd_price", 0) + 1
                logger.warning("NO_USD_PRICE: %s pair %s/%s skipped (add %s to tokens_usd_price)",
                              "VIABILITY_FILTER", token_in, token_out, token_in)
                continue

        # Anchor price
        yaml_anchor = lookup_anchor_price_ci(tokens_anchor_price, token_pair_tag)
        if not yaml_anchor:
            reversed_tag = f"{token_out}_{token_in}"
            yaml_anchor = lookup_anchor_price_ci(tokens_anchor_price, reversed_tag)
            if yaml_anchor:
                yaml_anchor = 1.0 / yaml_anchor
        pair_tag_display = f"{token_in}/{token_out}"
        anchor_price, anchor_source = am.get_anchor(pair_tag_display, yaml_anchor)

        # Build pool work items (same logic as before)
        fee_tiers = pair_cfg.fee_tiers or [500, 3000]
        chain_name = config.get("chain", "arbitrum_one")
        from dex.registry import get_dex_config
        pool_work_items: list = []

        if pair_cfg.pool_info:
            for pi in pair_cfg.pool_info:
                pi_dex = pi["dex"]
                pi_fee = pi["fee"]
                pi_addr = pi["address"]
                pi_dex_cfg = get_dex_config(chain_name, pi_dex)
                pi_adapter = pi_dex_cfg.adapter_type if pi_dex_cfg else None
                pool_key = make_pool_key(pi_dex, token_pair_tag, pi_fee)
                disabled_info = is_pool_disabled(config, pi_dex, token_pair_tag, pi_fee)
                if disabled_info:
                    counts["pool_disabled"] += 1
                    continue
                runtime_info = is_runtime_disabled(pool_key) if runtime_disabled_enabled else None
                if runtime_info and not runtime_info.get("expired", False):
                    counts["runtime_disabled"] += 1
                    continue
                pool_work_items.append((pi_dex, pi_fee, pi_addr, pi_dex_cfg, pi_adapter, pool_key))
        else:
            for dex in dexes_list:
                dex_cfg = get_dex_config(chain_name, dex)
                adapter_type = dex_cfg.adapter_type if dex_cfg else None
                if adapter_type == "algebra":
                    effective_fee_tiers = [0]
                else:
                    effective_fee_tiers = fee_tiers
                for fee_tier in effective_fee_tiers:
                    pool_key = make_pool_key(dex, token_pair_tag, fee_tier)
                    # v2.6.1 FIX: Check disabled_pools BEFORE pool lookup
                    disabled_info = is_pool_disabled(config, dex, token_pair_tag, fee_tier)
                    if disabled_info:
                        counts["pool_disabled"] += 1
                        logger.debug("POOL_DISABLED (config): %s %s/%s fee=%d",
                                   dex, token_in, token_out, fee_tier)
                        continue
                    runtime_info = is_runtime_disabled(pool_key) if runtime_disabled_enabled else None
                    if runtime_info and not runtime_info.get("expired", False):
                        counts["runtime_disabled"] += 1
                        continue
                    pool_addr = get_pool_address(config, dex, token_pair_tag, fee_tier=fee_tier)
                    if pool_addr:
                        pool_work_items.append((dex, fee_tier, pool_addr, dex_cfg, adapter_type, pool_key))
                    else:
                        counts["pool_missing"] += 1
                        pool_missing_keys.append(pool_key)
                        logger.debug("POOL_SKIP: %s %s/%s fee=%d - not in config (key=%s)",
                                    dex, token_in, token_out, fee_tier, pool_key)

        # Submit quoter futures for this pair's pools (NO blocking yet)
        _pf_tin = None
        _pf_tout = None
        if pool_work_items and rpc_url and not skip_rpc:
            _pf_tin = resolve_token_address(token_in, pair_cfg, token_addresses, chain_name, is_token_in=True)
            _pf_tout = resolve_token_address(token_out, pair_cfg, token_addresses, chain_name, is_token_in=False)
            if use_usd_notional:
                _pf_amt = calculate_amount_in_wei(token_in, decimals_in, target_usd_notional, tokens_usd_price)
            else:
                _pf_amt = 10 ** decimals_in
            _pf_use_q = config.get("use_quoter_v2", False)

            for _d, _f, _a, _dc, _at, _pk in pool_work_items:
                if _pk in _global_prefetch_futures:
                    continue  # already submitted
                if _at == "ve33":
                    _global_prefetch_futures[_pk] = _pf_exec.submit(
                        read_ve33_amount_out,
                        pool_address=_a, token_in=_pf_tin,
                        amount_in=_pf_amt, rpc_url=rpc_url, block_num=current_block,
                    )
                elif (_at == "algebra" or _pf_use_q) and _dc:
                    # R32: Skip quoter_v2 prefetch for pools with repeated failures
                    if _at == "uniswap_v3" and _should_skip_quoter_v2(_pk):
                        continue
                    _qa = _dc.get_quoter_address()
                    if _qa:
                        if _at == "uniswap_v3":
                            _global_prefetch_futures[_pk] = _pf_exec.submit(
                                read_quoter_v2,
                                _qa, _pf_tin, _pf_tout,
                                _pf_amt, _f, rpc_url, current_block,
                            )
                        elif _at == "algebra":
                            _global_prefetch_futures[_pk] = _pf_exec.submit(
                                read_algebra_quoter,
                                _qa, _pf_tin, _pf_tout,
                                _pf_amt, rpc_url, current_block,
                            )

        _pair_work_data.append((pair_cfg, pool_work_items, anchor_price, anchor_source))

    # Phase B: Resolve ALL quoter futures at once (cross-pair parallelism)
    for _pk, _fut in _global_prefetch_futures.items():
        try:
            _global_prefetch_results[_pk] = _fut.result(timeout=15)
        except Exception as _e:
            _global_prefetch_results[_pk] = None
            logger.debug("PREFETCH_FAIL: %s error=%s", _pk, _e)

    if _global_prefetch_futures:
        logger.info(
            "Cross-pair prefetch: %d futures submitted, %d resolved",
            len(_global_prefetch_futures),
            sum(1 for v in _global_prefetch_results.values() if v is not None),
        )

    # Phase C: Process pairs sequentially using pre-resolved prefetch results
    for pair_cfg, pool_work_items, anchor_price, anchor_source in _pair_work_data:
        token_pair_tag = pair_cfg.pair_tag
        token_in = pair_cfg.token_in
        token_out = pair_cfg.token_out
        decimals_in = pair_cfg.token_in_decimals
        decimals_out = pair_cfg.token_out_decimals

        fee_tiers = pair_cfg.fee_tiers or [500, 3000]
        chain_name = config.get("chain", "arbitrum_one")

        # Use global prefetch results for this pair
        _prefetch_results = {
            pk: _global_prefetch_results.get(pk)
            for _, _, _, _, _, pk in pool_work_items
            if pk in _global_prefetch_results
        }

        for dex, fee_tier, pool_addr, dex_cfg, adapter_type, pool_key in pool_work_items:
            # v2.1.0-fix: Check disabled_pools FIRST (before pool lookup)
            disabled_info = is_pool_disabled(config, dex, token_pair_tag, fee_tier)
            if disabled_info:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "reason": "POOL_DISABLED",
                    "gate_passed": False,
                    "error": f"Pool disabled: {disabled_info.get('reason', 'DISABLED')} - {disabled_info.get('detail', '')}",
                    "disabled_info": disabled_info,
                })
                counts["pool_disabled"] += 1
                logger.info("POOL_DISABLED: %s %s/%s fee=%d reason=%s", 
                           dex, token_in, token_out, fee_tier, disabled_info.get('reason', 'DISABLED'))
                continue
            
            # v2.1.0-fix: Check runtime quarantine (auto-quarantine for failing pools)
            pair_tag = f"{token_in}/{token_out}"
            if quarantine_enabled and qm.is_quarantined(dex, pair_tag, fee_tier):
                remaining = qm.get_quarantine_remaining(dex, pair_tag, fee_tier)
                rejected_quotes.append({
                    "pair": pair_tag,
                    "dex_id": dex,
                    "fee": fee_tier,
                    "reason": "QUARANTINED",
                    "gate_passed": False,
                    "error": f"Pool quarantined (remaining: {remaining:.0f}s)",
                })
                counts["quarantined"] += 1
                logger.info("QUARANTINED: %s %s fee=%d (remaining: %.0fs)", 
                           dex, pair_tag, fee_tier, remaining)
                continue
            
            # v3.2.0: Check prefetched liquidity for LIQUIDITY_ZERO auto-disable
            cached_liq = get_cached_liquidity(pool_addr)
            if cached_liq is not None and cached_liq == 0:
                if runtime_disabled_enabled:
                    auto_disable_pool(pool_key, "LIQUIDITY_ZERO",
                                     {"pool_address": pool_addr, "liquidity": 0})
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "pool_address": pool_addr,
                    "reason": "LIQUIDITY_ZERO",
                    "gate_passed": False,
                    "error": "Pool has zero liquidity (prefetch check)",
                })
                counts["liquidity_zero"] = counts.get("liquidity_zero", 0) + 1
                logger.info("LIQUIDITY_ZERO: %s (auto-disabled)", pool_key)
                continue
            
            # M4.2: Calculate amount_in_wei using USD-notional sizing
            if use_usd_notional:
                amount_in_wei = calculate_amount_in_wei(
                    token_in, decimals_in, target_usd_notional, tokens_usd_price
                )
            else:
                amount_in_wei = 10 ** decimals_in  # Legacy: 1 token
            
            # Resolve token addresses once (used by all adapter types)
            token_in_addr = resolve_token_address(token_in, pair_cfg, token_addresses, chain_name, is_token_in=True)
            token_out_addr = resolve_token_address(token_out, pair_cfg, token_addresses, chain_name, is_token_in=False)
            
            # M4.2 FIX: Use adapter_type for branching (reuse from outer loop)
            is_v3_dex = adapter_type in ("uniswap_v3", "algebra")
            is_algebra = adapter_type == "algebra"
            is_ve33 = adapter_type == "ve33"
            
            # ve33 executable quote path (Aerodrome/Velodrome)
            if is_ve33:
                # R28.4: Use prefetched result if available
                if pool_key in _prefetch_results:
                    amount_out_wei_val = _prefetch_results[pool_key]
                else:
                    amount_out_wei_val = read_ve33_amount_out(
                        pool_address=pool_addr,
                        token_in=token_in_addr,
                        amount_in=amount_in_wei,
                        rpc_url=rpc_url,
                        block_num=current_block,
                    )
                if amount_out_wei_val is None or amount_out_wei_val <= 0:
                    rejected_quotes.append({
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "VE33_QUOTE_FAILED",
                        "gate_passed": False,
                        "error": "pool.getAmountOut() failed or returned zero",
                    })
                    counts["ve33_quote_failed"] += 1
                    failed_pool_addresses.append({
                        "pool_address": pool_addr,
                        "dex_id": dex,
                        "pair": f"{token_in}/{token_out}",
                        "fee": fee_tier,
                        "reason": "VE33_QUOTE_FAILED",
                    })
                    if quarantine_enabled:
                        qm.record_failure(
                            dex,
                            f"{token_in}/{token_out}",
                            fee_tier,
                            "QUOTE_REVERT",
                            details={"pool_address": pool_addr, "error": "getAmountOut_failed"},
                        )
                    continue
                
                amount_out_human_val = float(Decimal(amount_out_wei_val) / Decimal(10 ** decimals_out))
                amount_out_human_str = str(round(amount_out_human_val, 6))
                amount_in_human_str = str(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
                
                amount_in_tokens = float(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
                price_exact = (
                    Decimal(str(amount_out_human_val)) / Decimal(str(amount_in_tokens))
                    if amount_in_tokens > 0
                    else Decimal(0)
                )
                price_str = str(round(float(price_exact), 6))
                
                # PRICE_SANITY gate (ve33 path — consolidated via quote_policy)
                _ps_reject = apply_price_sanity_gate(
                    price_exact=price_exact, anchor_price=anchor_price,
                    anchor_source="tokens_anchor_price",
                    pair_tag=f"{token_in}/{token_out}", dex=dex,
                    fee_tier=fee_tier, pool_addr=pool_addr, config=config,
                    amount_in_wei=amount_in_wei,
                    target_usd_notional=target_usd_notional if use_usd_notional else None,
                )
                if _ps_reject is not None:
                    rejected_quotes.append(_ps_reject)
                    counts["quotes_rejected"] = counts.get("quotes_rejected", 0) + 1
                    counts["price_sanity_failed"] = counts.get("price_sanity_failed", 0) + 1
                    if quarantine_enabled:
                        qm.record_failure(
                            dex, f"{token_in}/{token_out}", fee_tier,
                            "PRICE_SANITY_FAILED",
                            details={"pool_address": pool_addr,
                                     "deviation_bps": _ps_reject.get("deviation_bps"),
                                     "anchor_price": str(anchor_price),
                                     "price_exact": str(price_exact)},
                        )
                    if runtime_disabled_enabled:
                        auto_disable_pool(
                            pool_key, "PRICE_SANITY_FAILED",
                            {"pool_address": pool_addr,
                             "deviation_bps": _ps_reject.get("deviation_bps")},
                        )
                    continue
                
                q = QuoteCompat(
                    dex_id=dex,
                    pool_address=pool_addr,
                    token_in=token_in,
                    token_out=token_out,
                    fee=fee_tier,
                    amount_in_wei=amount_in_wei,
                    amount_out_wei=amount_out_wei_val,
                    amount_in_human=amount_in_human_str,
                    amount_out_human=amount_out_human_str,
                    price=price_str,
                    latency_ms=rpc_latency or 10,
                    block_number=current_block,
                    rpc_success=True,
                    gate_passed=True,
                    tick=None,
                    sqrt_price_x96=None,
                )
                q_dict = q.__dict__
                q_dict["price_exact"] = str(price_exact)
                q_dict["usd_notional"] = target_usd_notional if use_usd_notional else None
                q_dict["notional_usd_target"] = target_usd_notional if use_usd_notional else None
                
                token_out_price = lookup_token_usd_price_ci(tokens_usd_price, token_out) or DEFAULT_TOKEN_USD_PRICES.get(token_out, 1.0)
                notional_usd_actual = round(amount_out_human_val * token_out_price, 2)
                q_dict["notional_usd_actual"] = notional_usd_actual
                
                if use_usd_notional and target_usd_notional > 0 and notional_usd_actual > 0:
                    drift_pct = abs(notional_usd_actual - target_usd_notional) / target_usd_notional * 100
                    q_dict["notional_drift_pct"] = round(drift_pct, 2)
                    if drift_pct > 10.0:
                        logger.warning(
                            "NOTIONAL_DRIFT: %s/%s %s target=$%.0f actual=$%.2f drift=%.1f%%",
                            token_in, token_out, dex, target_usd_notional, notional_usd_actual, drift_pct
                        )
                
                q_dict["quote_source"] = "ve33_getAmountOut"
                q_dict["gas_estimate"] = None
                q_dict["ticks_crossed"] = None
                q_dict["anchor_source"] = anchor_source
                q_dict["sqrt_price_after"] = None
                q_dict["is_diagnostic_only"] = False
                
                quotes_sample.append(q_dict)
                counts["quotes_fetched"] += 1
                if quarantine_enabled:
                    qm.record_success(dex, f"{token_in}/{token_out}", fee_tier)
                if runtime_disabled_enabled:
                    record_quote_success(pool_key)
                if price_exact is not None and float(price_exact) > 0:
                    am.record_quote(f"{token_in}/{token_out}", float(price_exact), dex, fee_tier, current_block)
                continue
            
            # v3.2.20: Per-DEX quoter mode decision
            # - Algebra DEXes ALWAYS need quoter (slot0 ABI incompatible)
            # - UniswapV3 uses quoter_v2 when config flag is set
            use_quoter_global = config.get("use_quoter_v2", False)
            use_quoter_for_dex = is_algebra or use_quoter_global
            quoter_result = None
            _quoter_v2_was_skipped = False
            
            if use_quoter_for_dex and dex_cfg:
                quoter_addr = dex_cfg.get_quoter_address()
                if quoter_addr:
                    if adapter_type == "uniswap_v3":
                        # R32: Skip quoter_v2 for pools with repeated failures
                        if _should_skip_quoter_v2(pool_key):
                            counts["quoter_v2_skipped"] = counts.get("quoter_v2_skipped", 0) + 1
                            _quoter_v2_was_skipped = True
                        elif pool_key in _prefetch_results:
                            quoter_result = _prefetch_results[pool_key]
                        else:
                            quoter_result = read_quoter_v2(
                                quoter_addr, token_in_addr, token_out_addr,
                                amount_in_wei, fee_tier, rpc_url, current_block
                            )
                    elif adapter_type == "algebra":
                        # R28.4: Use prefetched result if available
                        if pool_key in _prefetch_results:
                            quoter_result = _prefetch_results[pool_key]
                        else:
                            quoter_result = read_algebra_quoter(
                                quoter_addr, token_in_addr, token_out_addr,
                                amount_in_wei, rpc_url, current_block
                            )
            
            # M4.2 FIX: If quoter_result is successful, we DON'T need slot0 at all
            # quoter_result gives executable amount_out, price derived from amount_out/amount_in
            # v2.8.0: But we DO want sqrt_price_x96 for slippage measurement (before-price)
            tick_val, sqrt_price_val = None, None
            quoter_success = quoter_result and quoter_result.get("amount_out", 0) > 0
            
            # R29: Track per-DEX quoter success/failure for quoter_matrix artifact
            if use_quoter_for_dex and dex_cfg and dex_cfg.get_quoter_address():
                mx_key = f"{dex}:{fee_tier}"
                if mx_key not in quoter_matrix:
                    quoter_matrix[mx_key] = {"dex": dex, "fee": fee_tier, "attempted": 0, "quoter_success": 0, "slot0_fallback": 0, "diagnostic_only": 0}
                quoter_matrix[mx_key]["attempted"] += 1
                if quoter_success:
                    quoter_matrix[mx_key]["quoter_success"] += 1
            
            # v2.8.0: Try to get sqrt_price_x96 from multicall cache for slippage measurement
            # This is the "before" price - quoter gives us "after" price via sqrt_price_after
            cached_slot0 = get_cached_slot0(pool_addr)
            if cached_slot0:
                tick_val, sqrt_price_val = cached_slot0
            
            # Path A: quoter canonical - skip slot0 for v3/algebra when quoter succeeds
            if quoter_success:
                # Use quoter data directly - no slot0 needed
                amount_out_wei_val = quoter_result["amount_out"]
                amount_out_human_val = float(Decimal(amount_out_wei_val) / Decimal(10 ** decimals_out))
                amount_out_human_str = str(round(amount_out_human_val, 6))
                amount_in_human_str = str(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
                # Price from quoter amounts
                amount_in_tokens = float(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
                price_exact = Decimal(str(amount_out_human_val)) / Decimal(str(amount_in_tokens)) if amount_in_tokens > 0 else Decimal(0)
                price_str = str(round(float(price_exact), 6))
                quote_source = "quoter_v2"
                gas_estimate = quoter_result.get("gas_estimate")
                ticks_crossed = quoter_result.get("ticks_crossed")
                
                # v2.0.9: SUSPECT_LIQUIDITY gate - reject high-impact quotes early
                # v3.2.58: Config-level overrides for per-chain tuning
                from core.constants import QUOTER_MAX_TICKS_CROSSED, QUOTER_MAX_GAS_ESTIMATE
                max_ticks = config.get("quoter_max_ticks_crossed", QUOTER_MAX_TICKS_CROSSED)
                max_gas = config.get("quoter_max_gas_estimate", QUOTER_MAX_GAS_ESTIMATE)
                suspect_liquidity_reason = None
                if ticks_crossed is not None and ticks_crossed > max_ticks:
                    suspect_liquidity_reason = f"ticks_crossed={ticks_crossed}>{max_ticks}"
                elif gas_estimate is not None and gas_estimate > max_gas:
                    suspect_liquidity_reason = f"gas_estimate={gas_estimate}>{max_gas}"
                
                if suspect_liquidity_reason:
                    rejected_quotes.append({
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "SUSPECT_LIQUIDITY",
                        "gate_passed": False,
                        "error": suspect_liquidity_reason,
                        "ticks_crossed": ticks_crossed,
                        "gas_estimate": gas_estimate,
                    })
                    counts["quotes_rejected"] = counts.get("quotes_rejected", 0) + 1
                    counts["suspect_liquidity"] = counts.get("suspect_liquidity", 0) + 1
                    logger.debug("SUSPECT_LIQUIDITY: %s %s/%s fee=%d: %s", 
                                dex, token_in, token_out, fee_tier, suspect_liquidity_reason)
                    # v2.4.0: Record failure for auto-quarantine
                    if quarantine_enabled:
                        qm.record_failure(dex, f"{token_in}/{token_out}", fee_tier, "SUSPECT_LIQUIDITY",
                                         details={"pool_address": pool_addr, "error": suspect_liquidity_reason})
                    if runtime_disabled_enabled:
                        auto_disable_pool(pool_key, "SUSPECT_LIQUIDITY", 
                                         {"pool_address": pool_addr, "error": suspect_liquidity_reason})
                    continue  # Skip this quote
                
                # PRICE_SANITY gate (quoter path — consolidated via quote_policy)
                _ps_reject = apply_price_sanity_gate(
                    price_exact=price_exact, anchor_price=anchor_price,
                    anchor_source="tokens_anchor_price",
                    pair_tag=f"{token_in}/{token_out}", dex=dex,
                    fee_tier=fee_tier, pool_addr=pool_addr, config=config,
                    amount_in_wei=amount_in_wei,
                    target_usd_notional=target_usd_notional if use_usd_notional else None,
                )
                if _ps_reject is not None:
                    rejected_quotes.append(_ps_reject)
                    counts["quotes_rejected"] = counts.get("quotes_rejected", 0) + 1
                    counts["price_sanity_failed"] = counts.get("price_sanity_failed", 0) + 1
                    if quarantine_enabled:
                        qm.record_failure(dex, f"{token_in}/{token_out}", fee_tier, "PRICE_SANITY_FAILED",
                                         details={"pool_address": pool_addr,
                                                  "deviation_bps": _ps_reject.get("deviation_bps"),
                                                  "anchor_price": str(anchor_price),
                                                  "price_exact": str(price_exact)})
                    if runtime_disabled_enabled:
                        auto_disable_pool(pool_key, "PRICE_SANITY_FAILED",
                                         {"pool_address": pool_addr,
                                          "deviation_bps": _ps_reject.get("deviation_bps")})
                    continue  # Skip this quote
                
                # Build quote directly from quoter data
                q = QuoteCompat(
                    dex_id=dex,
                    pool_address=pool_addr,
                    token_in=token_in,
                    token_out=token_out,
                    fee=fee_tier,
                    amount_in_wei=amount_in_wei,
                    amount_out_wei=amount_out_wei_val,
                    amount_in_human=amount_in_human_str,
                    amount_out_human=amount_out_human_str,
                    price=price_str,
                    latency_ms=rpc_latency or 10,
                    block_number=current_block,
                    rpc_success=True,
                    gate_passed=True,
                    tick=tick_val,  # v2.8.0: From multicall cache for slippage measurement
                    sqrt_price_x96=sqrt_price_val,  # v2.8.0: From multicall cache (before price)
                )
                q_dict = q.__dict__
                q_dict["price_exact"] = str(price_exact)
                q_dict["usd_notional"] = target_usd_notional if use_usd_notional else None
                
                # v2.1.0: Enhanced USD-notional tracking (Step 7)
                q_dict["notional_usd_target"] = target_usd_notional if use_usd_notional else None
                # v3.2.25: Case-insensitive USD price lookup
                token_out_price = lookup_token_usd_price_ci(tokens_usd_price, token_out) or DEFAULT_TOKEN_USD_PRICES.get(token_out, 1.0)
                notional_usd_actual = round(amount_out_human_val * token_out_price, 2)
                q_dict["notional_usd_actual"] = notional_usd_actual
                
                # NOTIONAL_DRIFT logging
                if use_usd_notional and target_usd_notional > 0 and notional_usd_actual > 0:
                    drift_pct = abs(notional_usd_actual - target_usd_notional) / target_usd_notional * 100
                    q_dict["notional_drift_pct"] = round(drift_pct, 2)
                    if drift_pct > 10.0:
                        logger.warning(
                            "NOTIONAL_DRIFT: %s/%s %s target=$%.0f actual=$%.2f drift=%.1f%%",
                            token_in, token_out, dex, target_usd_notional, notional_usd_actual, drift_pct
                        )
                
                q_dict["quote_source"] = quote_source
                q_dict["gas_estimate"] = gas_estimate
                q_dict["ticks_crossed"] = ticks_crossed
                q_dict["anchor_source"] = anchor_source  # v2.2.0: track dynamic vs yaml
                # v2.1.0: Add sqrt_price_after for measured slippage calculation
                q_dict["sqrt_price_after"] = quoter_result.get("sqrt_price_after") if quoter_result else None
                # v2.2.0 Fix Step 5: quoter_v2 quotes are executable, not diagnostic
                q_dict["is_diagnostic_only"] = False
                quotes_sample.append(q_dict)
                counts["quotes_fetched"] += 1
                # Record success to reset quarantine failure counter
                if quarantine_enabled:
                    qm.record_success(dex, f"{token_in}/{token_out}", fee_tier)
                if runtime_disabled_enabled:
                    record_quote_success(pool_key)
                # R32: Reset quoter_v2 skip cache on success (liquidity recovered)
                _record_quoter_v2_success(pool_key)
                # v2.2.0: Record valid quote for dynamic anchor calculation
                if price_exact is not None and float(price_exact) > 0:
                    am.record_quote(f"{token_in}/{token_out}", float(price_exact), dex, fee_tier, current_block)
                logger.debug("QuoterV2 canonical: %s %s/%s fee=%d amount_out=%s", 
                            dex, token_in, token_out, fee_tier, amount_out_wei_val)
                continue  # Skip slot0 path entirely
            
            # M4.2 FIX: Algebra DEXes require quoter - slot0() ABI is incompatible
            # v3.2.20: Quoter is now auto-enabled for Algebra, so this means quoter call failed
            # R28.25: Track as ALGEBRA_QUOTER_FAILED (not NEEDS_QUOTER) for clarity.
            # Algebra pools use globalState() not slot0(), so V3 slot0 fallback won't work.
            # These are genuine filter losses — visible in filter_funnel artifact.
            if is_algebra and not quoter_success:
                quoter_addr = dex_cfg.get_quoter_address() if dex_cfg else None
                reject_error = (
                    f"Algebra quoter call failed (quoter={quoter_addr[:16] + '...' if quoter_addr else 'NONE'})"
                    if quoter_addr else
                    "Algebra DEX has no quoter address in dexes.yaml"
                )
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "pool_address": pool_addr,
                    "reason": "ALGEBRA_NEEDS_QUOTER",
                    "gate_passed": False,
                    "error": reject_error,
                    "quoter_configured": bool(quoter_addr),
                    "quoter_result": quoter_result,
                })
                counts["algebra_needs_quoter"] = counts.get("algebra_needs_quoter", 0) + 1
                logger.info("ALGEBRA_QUOTER_FAILED: %s %s/%s fee=%d: %s", 
                           dex, token_in, token_out, fee_tier, reject_error)
                continue
            
            # R29: Emit QUOTER_V2_FAILED reject for non-algebra V3 DEXes when quoter
            # was attempted but failed. This is INFORMATIONAL — we still fall through
            # to slot0 path below. Makes quoter failures visible in reject_histogram.
            # R32: Don't emit QUOTER_V2_FAILED when quoter was intentionally skipped
            if use_quoter_for_dex and not quoter_success and is_v3_dex and not is_algebra and not _quoter_v2_was_skipped:
                quoter_addr = dex_cfg.get_quoter_address() if dex_cfg else None
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "pool_address": pool_addr,
                    "reason": "QUOTER_V2_FAILED",
                    "gate_passed": False,
                    "error": f"QuoterV2 failed, falling back to slot0 diagnostic (quoter={quoter_addr[:16] + '...' if quoter_addr else 'NONE'})",
                    "quoter_configured": bool(quoter_addr),
                    "quoter_result": quoter_result,
                    "fallback": "slot0_diagnostic",
                })
                counts["quoter_v2_failed"] = counts.get("quoter_v2_failed", 0) + 1
                mx_key = f"{dex}:{fee_tier}"
                if mx_key in quoter_matrix:
                    quoter_matrix[mx_key]["slot0_fallback"] += 1
                logger.info("QUOTER_V2_FAILED: %s %s/%s fee=%d pool=%s → slot0 fallback",
                           dex, token_in, token_out, fee_tier, pool_addr)
                # R32: Track failure for skip cache (skip quoter_v2 after repeated failures)
                _record_quoter_v2_failure(pool_key)
                # Do NOT continue — fall through to slot0 path below
            
            # Path B: slot0 fallback — DIAGNOSTIC CHANNEL only (R28)
            # slot0 reads are NOT executable quotes; they provide price reference
            # when QuoterV2 is unavailable. Gated as is_diagnostic_only=True
            # when truth_mode_m42=true (see line ~1693).
            if is_v3_dex and not is_algebra:
                # R28.18: Secondary liquidity check for slot0 path.
                cached_liq_slot0 = get_cached_liquidity(pool_addr)
                if cached_liq_slot0 is not None and cached_liq_slot0 == 0:
                    if runtime_disabled_enabled:
                        auto_disable_pool(pool_key, "LIQUIDITY_ZERO",
                                         {"pool_address": pool_addr, "liquidity": 0, "path": "slot0"})
                    rejected_quotes.append({
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "LIQUIDITY_ZERO",
                        "gate_passed": False,
                        "error": "Pool has zero liquidity (slot0 path check)",
                    })
                    counts["liquidity_zero"] = counts.get("liquidity_zero", 0) + 1
                    logger.info("LIQUIDITY_ZERO (slot0): %s (auto-disabled)", pool_key)
                    continue

                tick_val, sqrt_price_val = read_slot0_v3(pool_addr, rpc_url, current_block)
                
                if tick_val is None or sqrt_price_val is None:
                    if skip_rpc and anchor_price is not None:
                        tick_val, sqrt_price_val = synthesize_sqrt_price_from_anchor(
                            anchor_price, decimals_in, decimals_out
                        )
                    else:
                        rejected_quotes.append({
                            "pair": f"{token_in}/{token_out}",
                            "dex_id": dex,
                            "fee": fee_tier,
                            "pool_address": pool_addr,
                            "reason": "V3_SLOT0_FAILED",
                            "gate_passed": False,
                            "error": f"Failed to read slot0 from pool {pool_addr}",
                            # M4.2: Add diagnostic - was quoter attempted?
                            "quoter_attempted": use_quoter_global and dex_cfg is not None,
                        })
                        counts["v3_slot0_failed"] += 1
                        # v2.3.0: Track failed pool address for actionable diagnostics
                        failed_pool_addresses.append({
                            "pool_address": pool_addr,
                            "dex_id": dex,
                            "pair": f"{token_in}/{token_out}",
                            "fee": fee_tier,
                            "reason": "V3_SLOT0_FAILED",
                        })
                        logger.warning("V3_SLOT0_FAILED: %s %s/%s fee=%d pool=%s (quoter_attempted=%s)", 
                                      dex, token_in, token_out, fee_tier, pool_addr, use_quoter_global)
                        # Record failure for auto-quarantine
                        if quarantine_enabled:
                            qm.record_failure(dex, f"{token_in}/{token_out}", fee_tier, "QUOTE_REVERT",
                                            details={"pool_address": pool_addr, "error": "slot0_failed"})
                        continue
            
            # Calculate price from sqrtPriceX96
            if sqrt_price_val is not None and sqrt_price_val > 0:
                # v3.2.17: Use resolve_token_address with fallback chain
                token_in_addr = resolve_token_address(token_in, pair_cfg, token_addresses, chain_name, is_token_in=True)
                token_out_addr = resolve_token_address(token_out, pair_cfg, token_addresses, chain_name, is_token_in=False)
                price_exact = calculate_price_from_sqrt(
                    sqrt_price_val, token_in_addr, token_out_addr, decimals_in, decimals_out
                )
                
                if price_exact is None:
                    rejected_quotes.append({
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "PRICE_CALC_FAILED",
                        "gate_passed": False,
                        "error": "Failed to calculate price from sqrtPriceX96",
                    })
                    counts["price_calc_failed"] += 1
                    continue
                
                # v2.1.0-fix: Use localcontext to avoid InvalidOperation trap on round()
                # Some Decimal values (extreme precision) can trigger trap
                try:
                    with localcontext() as ctx:
                        ctx.traps[InvalidOperation] = False
                        price_str = str(round(price_exact, 6))
                except Exception:
                    price_str = str(price_exact)[:20]  # Fallback to truncation
                # M4.2 FIX: amount_out must scale with amount_in_wei (USD-notional)
                # For slot0: price_exact = amount_out per 1 token_in
                # amount_out = price_exact * (amount_in_wei / 10^decimals_in)
                # amount_out_wei = amount_out * 10^decimals_out
                price_exact_dec = Decimal(str(price_exact)) if not isinstance(price_exact, Decimal) else price_exact
                amount_in_tokens = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
                amount_out_human_dec = price_exact_dec * amount_in_tokens
                amount_out_wei_val = int(price_exact_dec * Decimal(amount_in_wei) * Decimal(10 ** decimals_out) / Decimal(10 ** decimals_in))
                try:
                    amount_out_human_str = str(round(float(amount_out_human_dec), 6))
                except (OverflowError, ValueError):
                    amount_out_human_str = "0.0"
                
                # v2.0.8: Enhanced QUOTE_ZERO_OUT gate with diagnostics
                # Detect: zero output, micro-liquidity, token0/token1 mismatch
                # token_in_addr / token_out_addr already looked up above
                token_in_is_token0 = (
                    token_in_addr.lower() < token_out_addr.lower()
                    if token_in_addr and token_out_addr else None
                )
                
                # Micro-price threshold: 1e-18 is suspiciously small
                is_micro_price = price_exact is not None and price_exact < 1e-18
                
                if amount_out_wei_val <= 0 or is_micro_price:
                    # Build diagnostic payload
                    diag = {
                        "pair": f"{token_in}/{token_out}",
                        "dex_id": dex,
                        "fee": fee_tier,
                        "pool_address": pool_addr,
                        "reason": "QUOTE_ZERO_OUT",
                        "gate_passed": False,
                        "error": f"amount_out_wei={amount_out_wei_val} <= 0" if amount_out_wei_val <= 0 else f"micro_price={price_exact}",
                        "price_exact": str(price_exact) if price_exact else None,
                        # v2.0.8: Enhanced diagnostics
                        "diag_token_in_is_token0": token_in_is_token0,
                        "diag_sqrt_price_x96": str(sqrt_price_val) if sqrt_price_val else None,
                        "diag_tick": tick_val,
                        "diag_decimals": f"{decimals_in}/{decimals_out}",
                    }
                    
                    # Detect potential token0/token1 mismatch
                    if is_micro_price and price_exact < 1e-20:
                        diag["diag_suspect"] = "TOKEN_ORDER_MISMATCH_OR_UNINITIALIZED"
                    
                    rejected_quotes.append(diag)
                    counts["quote_zero_out"] = counts.get("quote_zero_out", 0) + 1
                    logger.warning(
                        "QUOTE_ZERO_OUT: %s %s/%s fee=%d price=%s token_in_is_token0=%s",
                        dex, token_in, token_out, fee_tier, price_exact, token_in_is_token0
                    )
                    continue
            else:
                rejected_quotes.append({
                    "pair": f"{token_in}/{token_out}",
                    "dex_id": dex,
                    "fee": fee_tier,
                    "pool_address": pool_addr,
                    "reason": "NO_ONCHAIN_PRICE",
                    "gate_passed": False,
                    "error": "No on-chain price available",
                })
                counts["no_onchain_price"] += 1
                continue
            
            # Build quote with actual fee_tier (v2.0.7: no more hardcoded fee=3000)
            # M4.2: Use USD-notional sizing for amount_in_wei
            amount_in_human_str = str(Decimal(amount_in_wei) / Decimal(10 ** decimals_in))
            
            # PRICE_SANITY gate (slot0 path — consolidated via quote_policy)
            _ps_reject = apply_price_sanity_gate(
                price_exact=price_exact, anchor_price=anchor_price,
                anchor_source=anchor_source,
                pair_tag=f"{token_in}/{token_out}", dex=dex,
                fee_tier=fee_tier, pool_addr=pool_addr, config=config,
                quote_source="slot0", tick_val=tick_val,
            )
            if _ps_reject is not None:
                rejected_quotes.append(_ps_reject)
                counts["quotes_rejected"] = counts.get("quotes_rejected", 0) + 1
                counts["price_sanity_failed"] = counts.get("price_sanity_failed", 0) + 1
                continue
            
            # M4.2: This path is only reached via slot0 (quoter success continues early above)
            quote_source = "slot0"
            gas_estimate = None
            ticks_crossed = None
            
            q = QuoteCompat(
                dex_id=dex,
                pool_address=pool_addr,
                token_in=token_in,
                token_out=token_out,
                fee=fee_tier,  # v2.0.7: actual fee tier from config
                amount_in_wei=amount_in_wei,  # M4.2: USD-notional sizing
                amount_out_wei=amount_out_wei_val,
                amount_in_human=amount_in_human_str,
                amount_out_human=amount_out_human_str,
                price=price_str,
                latency_ms=rpc_latency or 10,
                block_number=current_block,
                rpc_success=True,
                gate_passed=True,
                tick=tick_val,
                sqrt_price_x96=sqrt_price_val,
            )
            q_dict = q.__dict__
            if price_exact is not None:
                q_dict["price_exact"] = str(price_exact)
            
            # M4.2: Add USD-notional metadata
            q_dict["usd_notional"] = target_usd_notional if use_usd_notional else None
            
            # v2.1.0: Enhanced USD-notional tracking (Step 7)
            # notional_usd_target: what we asked for
            # notional_usd_actual: what we got (amount_out * token_out_price)
            q_dict["notional_usd_target"] = target_usd_notional if use_usd_notional else None
            
            # v3.2.25: Case-insensitive USD price lookup
            token_out_price = lookup_token_usd_price_ci(tokens_usd_price, token_out) or DEFAULT_TOKEN_USD_PRICES.get(token_out, 1.0)
            amount_out_val = float(amount_out_human_str) if amount_out_human_str else 0.0
            notional_usd_actual = round(amount_out_val * token_out_price, 2)
            q_dict["notional_usd_actual"] = notional_usd_actual
            
            # NOTIONAL_DRIFT: log when target vs actual differs significantly (>10%)
            if use_usd_notional and target_usd_notional > 0 and notional_usd_actual > 0:
                drift_pct = abs(notional_usd_actual - target_usd_notional) / target_usd_notional * 100
                q_dict["notional_drift_pct"] = round(drift_pct, 2)
                if drift_pct > 10.0:
                    logger.warning(
                        "NOTIONAL_DRIFT: %s/%s %s target=$%.0f actual=$%.2f drift=%.1f%%",
                        token_in, token_out, dex, target_usd_notional, notional_usd_actual, drift_pct
                    )
            
            # M4.2: Quote source and quoter diagnostics (canonical now)
            q_dict["quote_source"] = quote_source
            q_dict["gas_estimate"] = gas_estimate
            q_dict["ticks_crossed"] = ticks_crossed
            q_dict["anchor_source"] = anchor_source  # v2.2.0: track dynamic vs yaml
            
            # v2.2.0 Fix Step 5: truth_mode_m42 behavior
            # When truth_mode_m42=true, slot0-only quotes are diagnostic only
            # These should be excluded from opportunity evaluation
            truth_mode = config.get("truth_mode_m42", False)
            if truth_mode and quote_source == "slot0":
                q_dict["is_diagnostic_only"] = True
                q_dict["diagnostic_reason"] = "SLOT0_DIAGNOSTIC"
                # R29: Track in quoter_matrix
                mx_key = f"{dex}:{fee_tier}"
                if mx_key in quoter_matrix:
                    quoter_matrix[mx_key]["diagnostic_only"] += 1
                logger.debug(
                    "SLOT0_DIAGNOSTIC: %s %s/%s (truth_mode requires quoter for executable quotes)",
                    dex, token_in, token_out
                )
            else:
                q_dict["is_diagnostic_only"] = False
            
            quotes_sample.append(q_dict)
            counts["quotes_fetched"] = counts.get("quotes_fetched", 0) + 1
            # Record success to reset quarantine failure counter
            if quarantine_enabled:
                qm.record_success(dex, f"{token_in}/{token_out}", fee_tier)
            # v2.2.0: Record valid quote for dynamic anchor calculation
            if price_exact is not None and float(price_exact) > 0:
                am.record_quote(f"{token_in}/{token_out}", float(price_exact), dex, fee_tier, current_block)
    
    finalize_quote_counts(counts, failed_pool_addresses, pool_missing_keys, quoter_matrix)
    
    return quotes_sample, rejected_quotes, counts
