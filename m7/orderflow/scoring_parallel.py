"""
M7 orderflow parallel scoring pipeline (score_backrun_live_parallel).

This is the main 3-stage pipeline: pair resolve + coverage scan + quote.
Extracted from the monolith due to size (~787 lines).
"""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    REJECT_EVENT_TOO_SMALL,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_QUOTE_FAILURE,
    REJECT_STALE_POSITIVE,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    REJECT_NO_COUNTER_POOL,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
    REJECT_ZERO_LIQUIDITY,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_GAS_FLOOR_EXCEEDED,
    REJECT_PRICING_ANOMALY,
    REJECT_USD_BASIS_MISSING,
    REJECT_MIN_PROFIT_USD_NOT_MET,
    REJECT_DEPTH_MATH_INVALID,
    ALL_REJECT_REASONS,
    UNSCORED_REJECTS,
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_REJECTED,
    ADMISSION_SUBGRAPH_VERIFIED,
    CHAINLINK_FEEDS_ARBITRUM,
    GAS_FLOOR_BPS_ARBITRUM,
    _DEFAULT_FEE_TIERS,
    _FALLBACK_ETH_PRICE_USD,
    M7A4_CHAIN,
    estimate_gas_cost,
    get_gas_floor_bps,
    get_gas_price_gwei,
    get_min_profitable_size_wei,
)
from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.pricing import (
    classify_event_backrun_type,
    _normalized_bounds,
    _gas_cost_in_token_wei,
    estimate_gas_decomposition_bps,
)
from m7.orderflow.resolve import (
    _resolve_event_tokens,
    _resolve_pool_addresses_multicall,
    enrich_tokens_batch,
    get_cached_decimals,
    get_cached_symbol,
    _pool_token_cache,
)
from m7.orderflow.coverage import (
    admit_event_tokens,
    counter_venue_coverage_scan,
)
from m7.orderflow.pricing import check_oracle_sanity
from m7.orderflow.v3_math import attempt_local_pricing, compute_v3_sqrt_price_after, attempt_split_pricing

from m7.shared.constants import (
    HOT_BUDGET_TOTAL_MS,
    HOT_BUDGET_REGISTRY_LOOKUP_MS,
    HOT_BUDGET_POOL_STATE_READ_MS,
    HOT_BUDGET_LOCAL_MATH_MS,
    HOT_BUDGET_PROFIT_GUARD_MS,
    get_chain_stale_blocks,
)

logger = logging.getLogger("m7.orderflow.scoring_parallel")

# ── E1.63/E1.64 module-level counters (thread-safe, reset per session) ────────
import threading as _threading
_e163_lock = _threading.Lock()
_e163_split_route_attempted: int = 0
_e163_split_route_win: int = 0
_e163_depth_guard_attempted: int = 0
_e163_price_impact_populated: int = 0
# E1.64 additional counters
_e164_depth_guard_rejected: int = 0   # guard triggered (price_impact > max_bps)
_e164_depth_math_invalid: int = 0     # compute_v3_sqrt_price_after gave absurd result
_e164_usd_basis_missing: int = 0      # net_bps>0 but no USD truth available
_e164_min_profit_rejected: int = 0    # expected_profit_usd < ARBY_MIN_EXPECTED_PROFIT_USD


def get_e163_session_counters() -> dict:
    """Return a snapshot of E1.63/E1.64 cumulative counters (never raises)."""
    try:
        with _e163_lock:
            return {
                "split_route_attempted_total": _e163_split_route_attempted,
                "split_route_win_total": _e163_split_route_win,
                "depth_guard_attempted_total": _e163_depth_guard_attempted,
                "price_impact_populated_total": _e163_price_impact_populated,
                # E1.64
                "depth_guard_rejected_total": _e164_depth_guard_rejected,
                "depth_math_invalid_total": _e164_depth_math_invalid,
                "usd_basis_missing_total": _e164_usd_basis_missing,
                "min_profit_rejected_total": _e164_min_profit_rejected,
            }
    except Exception:
        return {
            "split_route_attempted_total": 0,
            "split_route_win_total": 0,
            "depth_guard_attempted_total": 0,
            "price_impact_populated_total": 0,
            "depth_guard_rejected_total": 0,
            "depth_math_invalid_total": 0,
            "usd_basis_missing_total": 0,
            "min_profit_rejected_total": 0,
        }


def reset_e163_session_counters() -> None:
    """Reset E1.63/E1.64 counters — call at session boundary if needed (never raises)."""
    global _e163_split_route_attempted, _e163_split_route_win
    global _e163_depth_guard_attempted, _e163_price_impact_populated
    global _e164_depth_guard_rejected, _e164_depth_math_invalid
    global _e164_usd_basis_missing, _e164_min_profit_rejected
    try:
        with _e163_lock:
            _e163_split_route_attempted = 0
            _e163_split_route_win = 0
            _e163_depth_guard_attempted = 0
            _e163_price_impact_populated = 0
            _e164_depth_guard_rejected = 0
            _e164_depth_math_invalid = 0
            _e164_usd_basis_missing = 0
            _e164_min_profit_rejected = 0
    except Exception:
        pass
# ─────────────────────────────────────────────────────────────────────────────

_USD_STABLE_SYMBOLS = {"USDC", "USDT", "USDC.E", "USDT.E", "USDBC", "DAI", "PYUSD", "FRAX"}
_ETH_USD_SYMBOLS = {"WETH", "ETH"}
# E1.65 fix step 4/7: stable-coin-specific decimal overrides.
# get_cached_decimals() returns None on cache miss → falls back to 18 by default,
# causing a 10^12 underestimate for 6-decimal stables (USDC/USDT etc.) and
# rounding size_usd to 0.0.  This map provides the correct decimal count
# for known stablecoins so _quote_implied_size_usd() is correct even on cache miss.
_STABLE_DEC_OVERRIDE: dict = {
    "USDC": 6, "USDT": 6, "USDC.E": 6, "USDT.E": 6,
    "USDBC": 6, "PYUSD": 6,
    "DAI": 18, "FRAX": 18,
}


def _usd_basis_source(
    symbol_in: Optional[str],
    symbol_out: Optional[str],
    size_usd: Optional[float],
) -> Optional[str]:
    """Return a canonical string describing how size_usd was derived.

    E1.65: Used to populate BackrunResult.usd_basis_source for reviewer
    diagnosis and cold_immediate_sim routing.
    """
    if size_usd is None or size_usd <= 0:
        return None
    in_sym = (symbol_in or "").upper()
    out_sym = (symbol_out or "").upper()
    if in_sym in _USD_STABLE_SYMBOLS:
        return "token_in_stable"
    if in_sym in _ETH_USD_SYMBOLS:
        return "token_in_weth"
    if out_sym in _USD_STABLE_SYMBOLS:
        return "token_out_stable_fallback"
    if out_sym in _ETH_USD_SYMBOLS:
        return "token_out_weth_fallback"
    return None


def _quote_implied_size_usd(
    *,
    amount_in_wei: int,
    decimals_in: Optional[int],
    symbol_in: Optional[str],
    amount_out_wei: Optional[int],
    decimals_out: Optional[int],
    symbol_out: Optional[str],
    eth_price_usd: Optional[float],
) -> Optional[float]:
    """Estimate notional USD only from this candidate's quote and live anchors.

    Step 3 (E1.62): Added token_out USD fallback for meme/unknown tokens.
    When token_in is unknown (e.g. B3, FUN), use amount_out in the known
    output token (USDC/WETH) as the USD basis.  This unblocks rescale for
    B3/USDC where token_in=B3 has no oracle but token_out=USDC is always known.
    """
    in_sym = (symbol_in or "").upper()
    out_sym = (symbol_out or "").upper()
    dec_in = decimals_in if decimals_in is not None else 18
    dec_out = decimals_out if decimals_out is not None else 18

    # Primary path: token_in is known
    if in_sym in _USD_STABLE_SYMBOLS:
        return round(amount_in_wei / (10 ** dec_in), 6)
    if in_sym in _ETH_USD_SYMBOLS and eth_price_usd and eth_price_usd > 0:
        return round(amount_in_wei / (10 ** dec_in) * float(eth_price_usd), 6)

    if amount_out_wei is None or amount_out_wei <= 0:
        return None

    # Secondary path: token_out is known (covers meme/unknown token_in)
    if out_sym in _USD_STABLE_SYMBOLS:
        # E1.65 fix step 4/7: use symbol-aware decimal override to guard against
        # cache miss (decimals_out=None → dec_out=18 → 10^12 underestimate → 0.0).
        # Check original decimals_out param, not derived dec_out (always 18 on miss).
        _dec_out_stable = decimals_out if decimals_out is not None else _STABLE_DEC_OVERRIDE.get(out_sym, 6)
        return round(amount_out_wei / (10 ** _dec_out_stable), 6)
    if out_sym in _ETH_USD_SYMBOLS and eth_price_usd and eth_price_usd > 0:
        return round(amount_out_wei / (10 ** dec_out) * float(eth_price_usd), 6)

    # E1.69 reviewer fix step 7: USD-basis fallback for production tokens
    # without a stable/WETH leg (AERO, VIRTUAL, CBBTC, ...).  Opt-in via
    # ARBY_USD_BASIS_FALLBACK_ENABLE=1 so default behaviour is unchanged.
    if os.getenv("ARBY_USD_BASIS_FALLBACK_ENABLE", "0") == "1":
        try:
            from m7.orderflow.usd_basis_fallback import fallback_usd_for_amount
            _fb = fallback_usd_for_amount(
                symbol=in_sym, amount_wei=int(amount_in_wei), decimals=decimals_in
            )
            if _fb is not None and _fb > 0:
                return _fb
            _fb_out = fallback_usd_for_amount(
                symbol=out_sym, amount_wei=int(amount_out_wei), decimals=decimals_out
            )
            if _fb_out is not None and _fb_out > 0:
                return _fb_out
        except Exception:
            pass

    return None


def _read_positive_float_env(name: str, default: float = 0.0) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def _roundtrip_gross_wei(amount_in_wei: int, sell_amount_wei: int) -> int:
    """Return roundtrip gross PnL in token_in units.

    ``attempt_local_pricing`` returns buy_amount in token_out units and
    sell_amount in token_in units.  Profit math must therefore compare
    sell_amount to the original amount_in, never buy_amount to sell_amount.
    """
    return int(sell_amount_wei) - int(amount_in_wei)


def _roundtrip_net_bps_from_sell(amount_in_wei: int, sell_amount_wei: int) -> float:
    """Return roundtrip net bps before gas, measured in token_in units."""
    amount_in = int(amount_in_wei)
    if amount_in <= 0:
        return 0.0
    return (_roundtrip_gross_wei(amount_in, int(sell_amount_wei)) * 10000.0) / amount_in


def _usd_target_rescaled_size_wei(
    *,
    amount_in_wei: int,
    current_size_usd: Optional[float],
    target_usd: Optional[float] = None,
    max_scale: Optional[float] = None,
    max_size_wei: Optional[int] = None,
) -> Optional[int]:
    """Return a larger test size when a dynamic USD basis is far too small.

    This is deliberately opt-in via ``ARBY_TARGET_TRADE_USD``. The legacy
    decimal-normalized bounds cap 18-decimal inputs at 1 whole token, which is
    reasonable for WETH but pathological for low-price ERC20s. This helper only
    scales when a live quote/oracle-derived USD basis exists.
    """
    if amount_in_wei <= 0 or current_size_usd is None or current_size_usd <= 0:
        return None
    target = (
        float(target_usd)
        if target_usd is not None
        else _read_positive_float_env("ARBY_TARGET_TRADE_USD", 0.0)
    )
    if target <= 0 or current_size_usd >= target:
        return None
    scale = target / float(current_size_usd)
    if scale <= 1:
        return None
    max_scale_val = (
        float(max_scale)
        if max_scale is not None
        else _read_positive_float_env("ARBY_TARGET_TRADE_MAX_SCALE", 100000.0)
    )
    if max_scale_val > 0:
        scale = min(scale, max_scale_val)
    new_size = int(amount_in_wei * scale)
    max_size_val = max_size_wei
    if max_size_val is None:
        try:
            max_size_val = int(os.getenv("ARBY_TARGET_TRADE_MAX_WEI", "0") or "0")
        except (TypeError, ValueError):
            max_size_val = 0
    if max_size_val and max_size_val > 0:
        new_size = min(new_size, max_size_val)
    if new_size <= amount_in_wei:
        return None
    return new_size


# E1.62 step 2: size frontier — USD ladder instead of single target.
# ENV: ARBY_SIZE_FRONTIER_USD (comma-separated, default "0.1,0.25,0.5,1,2,5,10,25,50")
_DEFAULT_SIZE_FRONTIER_USD = "0.1,0.25,0.5,1,2,5,10,25,50"


def _usd_frontier_sizes_wei(
    *,
    amount_in_wei: int,
    current_size_usd: Optional[float],
    token_in_decimals: int = 18,
    max_scale: Optional[float] = None,
) -> List[int]:
    """Return sorted list of wei sizes corresponding to the USD frontier ladder.

    Step 2 (E1.62): instead of rescaling to a single $10 target, probe a
    range of USD notionals so the caller can pick the size that maximises
    expected_profit_usd (absolute edge) rather than net_bps (relative edge).

    Only returns sizes strictly larger than ``amount_in_wei``; the original
    size is always kept in the calling sweep so it is not duplicated here.
    Returns empty list when the USD basis is unavailable, unless
    ``ARBY_FRONTIER_FORCE_PROBE=1`` is set, in which case the function
    treats the missing basis as $1 and emits wei multipliers anyway.
    """
    if amount_in_wei <= 0:
        return []
    if current_size_usd is None or current_size_usd <= 0:
        if os.getenv("ARBY_FRONTIER_FORCE_PROBE", "0") == "1":
            current_size_usd = 1.0
        else:
            return []

    _env_frontier = os.getenv("ARBY_SIZE_FRONTIER_USD", "").strip()
    try:
        frontier_usd = [
            float(x) for x in (_env_frontier or _DEFAULT_SIZE_FRONTIER_USD).split(",")
            if x.strip()
        ]
    except Exception:
        frontier_usd = [0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0]

    max_scale_val = (
        float(max_scale)
        if max_scale is not None
        else _read_positive_float_env("ARBY_TARGET_TRADE_MAX_SCALE", 100000.0)
    )

    sizes: List[int] = []
    for target_usd in frontier_usd:
        if current_size_usd >= target_usd:
            continue  # current size already covers this tier
        scale = target_usd / current_size_usd
        if scale <= 1:
            continue
        if max_scale_val > 0:
            scale = min(scale, max_scale_val)
        s = int(amount_in_wei * scale)
        if s > amount_in_wei:
            sizes.append(s)

    return sorted(set(sizes))


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
    pool_registry: Any = None,
    chain: str = "base",
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
                extra_latency=None, pct=None, psrp=None):
        # M7.A.5.11: Assign same_state_class for early rejects based on block_lag
        _lag = current_block - event.block_number
        if _lag == 0:
            _ssc = "same_block"
        elif _lag <= 2:
            _ssc = "next_block"
        else:
            _ssc = "stale"
        return BackrunResult(
            event_id=event.event_id,
            event_source="live",
            event_type=event.event_type,
            post_trade_state_used="live",
            backrun_direction=backrun_dir,
            reject_reason=reason,
            event_block=event.block_number,
            quote_block=current_block,
            block_lag=_lag,
            same_state_class=_ssc,
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
            pool_contract_truth=pct,
            pool_state_read_path=psrp,
        )

    # ── Stage A: Actual-pair token resolution ───────────────────────────
    pair_resolved = False
    actual_pair: Optional[str] = None
    size_source = "event_proportional"

    token_in_addr = token_addresses.get(event.token_out, "")
    token_out_addr = token_addresses.get(event.token_in, "")
    use_common_pairs = not token_in_addr or not token_out_addr

    _pair_unresolved_detail: Optional[str] = None
    _pool_truth: Optional[Dict[str, Any]] = None
    _pool_read_path: Optional[str] = None
    # M7.A.5.30: Time the token-resolve phase (previously unaccounted)
    _resolve_start = time.monotonic()
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
            _pool_read_path = "v3_multicall"
        else:
            # M7.A.5.16: Probe individual pool selectors for fine-grained failure truth
            _pair_unresolved_detail = "pool_read_failed"
            try:
                from web3 import Web3
                from core.rpc_rate_limiter import rpc_throttle
                _w3 = Web3(Web3.HTTPProvider(rpc_url))
                _pool_cs = _w3.to_checksum_address(event.pool_address)
                # Check if pool has code
                rpc_throttle.acquire()
                _code = _w3.eth.get_code(_pool_cs, current_block)
                _code_present = len(_code) > 0
                if not _code_present:
                    _pair_unresolved_detail = "POOL_CODE_EMPTY"
                    _pool_truth = {
                        "pool_address": event.pool_address,
                        "code_present": False,
                        "token0_ok": False,
                        "token1_ok": False,
                        "slot0_ok": False,
                        "liquidity_ok": False,
                        "dex_family_guess": "no_code",
                    }
                else:
                    # Probe individual selectors
                    _t0_ok, _t1_ok, _s0_ok, _liq_ok = False, False, False, False
                    _t0_raw, _t1_raw = b"", b""
                    try:
                        rpc_throttle.acquire()
                        _t0_raw = _w3.eth.call({"to": _pool_cs, "data": "0x0dfe1681"}, current_block)
                        _t0_ok = len(_t0_raw) >= 32
                    except Exception:
                        pass
                    try:
                        rpc_throttle.acquire()
                        _t1_raw = _w3.eth.call({"to": _pool_cs, "data": "0xd21220a7"}, current_block)
                        _t1_ok = len(_t1_raw) >= 32
                    except Exception:
                        pass
                    try:
                        rpc_throttle.acquire()
                        _s0_raw = _w3.eth.call({"to": _pool_cs, "data": "0x3850c7bd"}, current_block)
                        _s0_ok = len(_s0_raw) >= 32
                    except Exception:
                        pass
                    try:
                        rpc_throttle.acquire()
                        _liq_raw = _w3.eth.call({"to": _pool_cs, "data": "0x1a686502"}, current_block)
                        _liq_ok = len(_liq_raw) >= 32
                    except Exception:
                        pass

                    # Determine dex_family_guess
                    if _t0_ok and _t1_ok and _s0_ok:
                        _dex_guess = "uniswap_v3_like"
                    elif _t0_ok and _t1_ok and not _s0_ok:
                        _dex_guess = "uniswap_v2_like"
                    elif _t0_ok or _t1_ok:
                        _dex_guess = "partial_erc20_pool"
                    else:
                        _dex_guess = "unknown"

                    _pool_truth = {
                        "pool_address": event.pool_address,
                        "code_present": True,
                        "token0_ok": _t0_ok,
                        "token1_ok": _t1_ok,
                        "slot0_ok": _s0_ok,
                        "liquidity_ok": _liq_ok,
                        "dex_family_guess": _dex_guess,
                    }

                    # Determine fine-grained failure cause
                    if not _t0_ok:
                        _pair_unresolved_detail = "POOL_TOKEN0_REVERT"
                    elif not _t1_ok:
                        _pair_unresolved_detail = "POOL_TOKEN1_REVERT"
                    elif not _s0_ok:
                        _pair_unresolved_detail = "POOL_SLOT0_REVERT"
                    elif not _liq_ok:
                        _pair_unresolved_detail = "POOL_LIQUIDITY_REVERT"
                    # else: all selectors worked but multicall batch still failed —
                    # keep "pool_read_failed" (batch assembly issue)

                    # If token0 + token1 readable, try enrichment + resolve
                    if _t0_ok and _t1_ok:
                        _t0 = "0x" + _t0_raw[-20:].hex()
                        _t1 = "0x" + _t1_raw[-20:].hex()
                        _enr = enrich_tokens_batch([_t0, _t1], rpc_url, current_block)
                        for _ea, _ei in _enr.items():
                            if _ei.get("enriched") and _ei.get("symbol"):
                                addr_to_symbol[_ea.lower()] = _ei["symbol"]

                        # M7.A.5.17: V2 direct resolve — bypass batch_token_info (fee() reverts)
                        if _dex_guess == "uniswap_v2_like":
                            _t0_sym = addr_to_symbol.get(_t0.lower(), _t0[:10])
                            _t1_sym = addr_to_symbol.get(_t1.lower(), _t1[:10])
                            if event.token_in == "token0_in":
                                token_in_addr = _t0
                                token_out_addr = _t1
                                _tin_sym, _tout_sym = _t0_sym, _t1_sym
                            else:
                                token_in_addr = _t1
                                token_out_addr = _t0
                                _tin_sym, _tout_sym = _t1_sym, _t0_sym
                            pair_resolved = True
                            actual_pair = f"{_tin_sym}/{_tout_sym}"
                            use_common_pairs = False
                            _pair_unresolved_detail = None
                            _pool_read_path = "v2_getReserves"
                            # Probe getReserves for pool state truth
                            _reserves_ok = False
                            _r0, _r1 = 0, 0
                            try:
                                rpc_throttle.acquire()
                                _res_raw = _w3.eth.call(
                                    {"to": _pool_cs, "data": "0x0902f1ac"}, current_block
                                )
                                if len(_res_raw) >= 64:
                                    _r0 = int.from_bytes(_res_raw[0:32], "big")
                                    _r1 = int.from_bytes(_res_raw[32:64], "big")
                                    _reserves_ok = _r0 > 0 or _r1 > 0
                            except Exception:
                                pass
                            _pool_truth["reserve0"] = _r0
                            _pool_truth["reserve1"] = _r1
                            _pool_truth["reserves_ok"] = _reserves_ok
                            _pool_truth["v2_resolved"] = True
                        else:
                            # V3-like or partial: retry via multicall
                            resolved2 = _resolve_event_tokens(
                                pool_address=event.pool_address,
                                swap_direction=event.token_in,
                                rpc_url=rpc_url,
                                block_num=current_block,
                                addr_to_symbol=addr_to_symbol,
                            )
                            if resolved2:
                                token_in_addr = resolved2["token_in_addr"]
                                token_out_addr = resolved2["token_out_addr"]
                                pair_resolved = True
                                actual_pair = f"{resolved2['token_in_symbol']}/{resolved2['token_out_symbol']}"
                                use_common_pairs = False
                                _pair_unresolved_detail = None
                                _pool_truth = None  # resolved; truth no longer needed
                                _pool_read_path = "v3_multicall"
            except Exception:
                pass  # fallback is best-effort
    elif use_common_pairs:
        if not event.pool_address:
            _pair_unresolved_detail = "no_pool_address"
        elif addr_to_symbol is None:
            _pair_unresolved_detail = "no_symbol_map"

    if use_common_pairs:
        r = _reject(REJECT_TOKEN_PAIR_UNRESOLVED, pct=_pool_truth, psrp=_pool_read_path)
        r.pair_unresolved_detail = _pair_unresolved_detail
        return r
    _resolve_ms = round((time.monotonic() - _resolve_start) * 1000, 2)

    # ── M7.A.5.7: On-chain enrichment for unknown tokens ───────────────
    # Before admission: if a token is not in addr_to_symbol, try reading
    # its ERC-20 symbol/decimals on-chain. If successful, inject into
    # addr_to_symbol so the admission check can use it.
    _enrichment_start = time.monotonic()
    enrichment_applied = False
    _ats = addr_to_symbol or {}
    _addr_to_dec: Dict[str, int] = {}  # M7.A.5.9: decimals cache
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
                if info.get("decimals") is not None:
                    _addr_to_dec[addr] = info["decimals"]
        except Exception:
            pass  # enrichment is best-effort
    _enrichment_ms = round((time.monotonic() - _enrichment_start) * 1000, 2)

    # ── M7.A.5.6: Event-token admission check ──────────────────────────
    _admission_start = time.monotonic()
    admission = admit_event_tokens(
        token_in_addr, token_out_addr,
        _ats, token_addresses,
    )
    # M7.A.5.10: Fix admission provenance — compute sg_seed first, then decide source
    _admission_ms = round((time.monotonic() - _admission_start) * 1000, 2)
    adm_source = admission.get("admission_source", ADMISSION_REJECTED)
    _sg_addrs = subgraph_seeded_addrs or set()
    sg_seed = bool(
        _sg_addrs
        and (token_in_addr.lower() in _sg_addrs or token_out_addr.lower() in _sg_addrs)
        and admission["admitted"]
    )
    if enrichment_applied and admission["admitted"] and adm_source == ADMISSION_ADDR_TO_SYMBOL:
        if sg_seed:
            adm_source = ADMISSION_SUBGRAPH_VERIFIED
        else:
            adm_source = ADMISSION_ONCHAIN_ENRICHED

    if not admission["admitted"]:
        return _reject(
            REJECT_TOKEN_NOT_ADMITTED,
            pr=pair_resolved, ap=actual_pair, adm=False,
            adm_src=ADMISSION_REJECTED, sg_seed=False,
            pct=_pool_truth, psrp=_pool_read_path,
        )

    # ── M7.A.5.7: Oracle sanity guard ──────────────────────────────────
    _oracle_start = time.monotonic()
    oracle_result = None
    try:
        in_sym = admission.get("token_in_symbol")
        out_sym = admission.get("token_out_symbol")
        oracle_result = check_oracle_sanity(in_sym, out_sym, rpc_url, current_block, chain=chain)
    except Exception:
        pass  # oracle guard is best-effort
    _oracle_ms = round((time.monotonic() - _oracle_start) * 1000, 2)

    # ── M7.A.5.21: Registry preload for this pair ────────────────────────
    _registry_start = time.monotonic()
    _registry_entries: list = []
    _registry_pools_found: Optional[int] = None
    _registry_pools_active: Optional[int] = None
    if pool_registry is not None:
        try:
            _reg_results = pool_registry.preload_pair(
                token_in_addr, token_out_addr,
                dex_configs, rpc_url, current_block,
            )
            _registry_entries = _reg_results
            _registry_pools_found = len(_reg_results)
            _registry_pools_active = sum(1 for e in _reg_results if e.is_active())
        except Exception as _reg_exc:
            logger.debug("Registry preload failed: %s", str(_reg_exc)[:80])
    _registry_preload_ms = round((time.monotonic() - _registry_start) * 1000, 2)

    # ── M7.A.5.23: Low-lag registry-direct scoring fast path ────────────
    # For low-lag events (preliminary_lag <= 2) with active registry pools,
    # build synthetic coverage and local_sim directly from registry entries.
    # This bypasses the RPC-heavy coverage scan and allows V2 pools (which
    # lack quoter_v2) to be priced via adapter-specific local math.
    _scoring_path = None
    _preliminary_lag = current_block - event.block_number
    _is_low_lag = _preliminary_lag <= 2
    if _is_low_lag and _registry_pools_active and _registry_pools_active > 0:
        _active_entries = [e for e in _registry_entries if e.is_active()]
        _reg_pool_states: Dict[str, Any] = {}
        for _re in _active_entries:
            _ps = _re.to_pool_state()
            if _ps is not None:
                _reg_pool_states[_re.address] = _ps
        if _reg_pool_states:
            _reg_cand_pools = [e.to_candidate_pool() for e in _active_entries]
            _reg_dexes = list(set(e.dex for e in _active_entries))
            coverage = {
                "known_pools_total": _registry_pools_found,
                "active_pools_total": _registry_pools_active,
                "inactive_pool_count": (_registry_pools_found or 0) - (_registry_pools_active or 0),
                "known_pools": _registry_pools_found,
                "known_dexes": _reg_dexes,
                "active_dexes": _reg_dexes,
                "buy_venues": len(_active_entries),
                "sell_venues": len(_active_entries),
                "active_buy_venues": len(_reg_dexes),
                "active_sell_venues": len(_reg_dexes),
                "coverage_complete": True,
                "coverage_blocker_reason": None,
                "candidate_pools": _reg_cand_pools,
            }
            cand_pools = _reg_cand_pools
            local_sim = {
                "pools_queried": len(_reg_cand_pools),
                "pools_with_state": len(_reg_pool_states),
                "pool_states": dict(list(_reg_pool_states.items())[:3]),
            }
            _scoring_path = "registry_direct"
            logger.debug(
                "M7.A.5.23 low-lag fast path: registry_direct "
                "(lag=%d, active_pools=%d, pool_states=%d)",
                _preliminary_lag, _registry_pools_active, len(_reg_pool_states),
            )

    # M7.A.5.24: Instant reject for low-lag events with zero active pools
    if _is_low_lag and _registry_pools_active is not None and _registry_pools_active == 0:
        return _reject(
            REJECT_ALL_POOLS_TRULY_INACTIVE,
            pr=pair_resolved, ap=actual_pair, adm=True,
            adm_src=adm_source, orc=oracle_result,
            cov=None, sg_seed=sg_seed,
            pct=_pool_truth, psrp=_pool_read_path,
        )

    if _scoring_path is None:
        # ── M7.A.5.6: Counter-venue coverage scan ──────────────────────────
        try:
            coverage = counter_venue_coverage_scan(
                token_in_addr, token_out_addr,
                dex_configs, rpc_url, current_block,
                pool_registry=pool_registry,
            )
        except Exception:
            coverage = {
                "known_pools_total": 0, "active_pools_total": 0, "inactive_pool_count": 0,
                "known_pools": 0, "known_dexes": [], "active_dexes": [],
                "buy_venues": 0, "sell_venues": 0,
                "active_buy_venues": 0, "active_sell_venues": 0,
                "coverage_complete": False,
                "coverage_blocker_reason": "scan_error",
                "candidate_pools": [],
            }

        if not coverage["coverage_complete"]:
            # M7.A.5.11: Granular reject based on coverage blocker
            blocker = coverage.get("coverage_blocker_reason", "")
            if blocker == "no_pools_found":
                reason = REJECT_NO_COUNTER_POOL
            elif blocker == "all_pools_zero_liquidity":
                # M7.A.5.12: Coverage itself says all zero → truly inactive
                reason = REJECT_ALL_POOLS_TRULY_INACTIVE
            elif blocker in ("no_quoter_for_active_pools", "no_quoter_for_live_pools"):
                reason = REJECT_UNSUPPORTED_ADAPTER
            elif blocker == "scan_error":
                reason = REJECT_NO_COUNTER_POOL
            elif blocker == "local_sim_all_zero_liquidity":
                reason = REJECT_COVERAGE_LOCAL_MISMATCH
            else:
                reason = REJECT_NO_ACTIVE_COUNTER_POOL
            return _reject(
                reason,
                pr=pair_resolved, ap=actual_pair, adm=True,
                adm_src=adm_source, orc=oracle_result,
                cov=coverage, sg_seed=sg_seed,
                pct=_pool_truth, psrp=_pool_read_path,
            )

        # ── M7.A.5.12: Build local-sim from coverage canonical state ───────
        # Reuse pool_state from coverage scan (same batch_full_pool_data extraction)
        # to avoid a second RPC call and guarantee state consistency.
        local_sim = None
        cand_pools = coverage.get("candidate_pools", [])
        if cand_pools:
            _pool_states = {}
            for cp in cand_pools:
                addr = cp.get("address")
                liq = cp.get("liquidity")
                if addr and liq is not None:
                    _pool_states[addr] = {
                        "sqrt_price_x96": None,  # filled below if available
                        "tick": None,
                        "liquidity": liq,
                    }
            # Try to get full state from the same multicall data
            try:
                pool_map = _resolve_pool_addresses_multicall(
                    dex_configs, token_in_addr, token_out_addr, rpc_url, current_block,
                )
                for dex_name, pools in pool_map.items():
                    for p in pools:
                        if p["address"] and p.get("pool_state"):
                            _pool_states[p["address"]] = p["pool_state"]
            except Exception:
                pass  # fallback to liquidity-only state from candidate_pools
            # E1.63 step 7: supplement pool states from pool_price_state registry
            # (populated by WS Swap events + HTTP feed). This makes price-impact and
            # split routing available even when multicall fails for a pool.
            try:
                from m7.orderflow.pool_price_state import get_registry as _get_pps_reg
                _pps_reg = _get_pps_reg()
                _chain_for_pps = chain if chain else "base"
                for _pa_k, _ps_v in _pool_states.items():
                    if _ps_v.get("sqrt_price_x96") is None:
                        _cached_v3 = _pps_reg.get(_chain_for_pps, _pa_k)
                        if _cached_v3 is not None and _cached_v3.sqrt_price_x96:
                            _pool_states[_pa_k]["sqrt_price_x96"] = _cached_v3.sqrt_price_x96
                            _pool_states[_pa_k]["tick"] = _cached_v3.tick
                            if _pool_states[_pa_k].get("liquidity") is None:
                                _pool_states[_pa_k]["liquidity"] = _cached_v3.liquidity
            except Exception:
                pass
            if _pool_states:
                local_sim = {
                    "pools_queried": len(cand_pools),
                    "pools_with_state": len(_pool_states),
                    "pool_states": dict(list(_pool_states.items())[:3]),  # cap to 3
                }

        # ── M7.A.5.12: Zero-liquidity reject gate with consistency check ──
        if local_sim and local_sim.get("pool_states"):
            _all_zero_liq = all(
                ps.get("liquidity", 1) == 0
                for ps in local_sim["pool_states"].values()
                if ps is not None
            )
            if _all_zero_liq:
                # M7.A.5.12: Split based on coverage/local-sim agreement
                _cov_active = coverage.get("active_pools_total", 0)
                if _cov_active > 0:
                    # Coverage said active but canonical state shows all zero
                    # → patch coverage for invariant correctness
                    coverage["active_pools_total"] = 0
                    coverage["inactive_pool_count"] = coverage.get("known_pools_total", 0)
                    coverage["active_dexes"] = []
                    coverage["active_buy_venues"] = 0
                    coverage["active_sell_venues"] = 0
                    coverage["coverage_complete"] = False
                    coverage["coverage_blocker_reason"] = "local_sim_all_zero_liquidity"
                    _reject_reason = REJECT_COVERAGE_LOCAL_MISMATCH
                else:
                    _reject_reason = REJECT_ALL_POOLS_TRULY_INACTIVE
                return _reject(
                    _reject_reason,
                    pr=pair_resolved, ap=actual_pair, adm=True,
                    adm_src=adm_source, orc=oracle_result,
                    cov=coverage, lss=local_sim, sg_seed=sg_seed,
                    pct=_pool_truth, psrp=_pool_read_path,
                )

    # ── M7.A.5.9: Decimal-aware bounded size logic ────────────────────
    # Resolve token_in decimals: enrichment cache → well-known defaults → 18
    _token_in_dec: Optional[int] = _addr_to_dec.get(token_in_addr.lower())
    if _token_in_dec is None:
        # M7.A.5.40: Check module-level enrichment cache (populated by batch
        # pre-resolve or prior enrichment calls). This fixes size_valid_for_token
        # being false when per-event enrichment was skipped due to cache hit.
        _token_in_dec = get_cached_decimals(token_in_addr)
    if _token_in_dec is None:
        # Well-known stablecoin/wrapped-asset heuristic (symbol-based).
        # Reviewer post-soak19 fix #5: extended symbol list (DAI/WETH/cbBTC/
        # cbETH/wstETH/PYUSD/USDbC) so MISSING_SIZE_METADATA upstream coverage
        # improves before reaching execution_gate.
        _in_sym = _ats.get(token_in_addr.lower(), "")
        _sym_upper = _in_sym.upper()
        if _sym_upper in ("USDC", "USDT", "USDC.E", "USDT.E", "USDBC", "PYUSD"):
            _token_in_dec = 6
        elif _sym_upper in ("WBTC", "CBBTC", "TBTC"):
            _token_in_dec = 8
        elif _sym_upper in ("WETH", "ETH", "DAI", "CBETH", "WSTETH", "RETH", "FRAX"):
            _token_in_dec = 18
    # Reviewer post-soak19 fix #5: final EVM-default fallback so
    # ``token_in_decimals`` is always populated downstream. Recorded with an
    # explicit source so observability stays honest about inference quality.
    if _token_in_dec is not None:
        _norm_source = "decimal_only"
    else:
        _token_in_dec = 18
        _norm_source = "default_18_inferred"
    _effective_dec = _token_in_dec
    MIN_BACKRUN_WEI, MAX_BACKRUN_WEI = _normalized_bounds(_effective_dec)
    MIN_BACKRUN_WEI = max(MIN_BACKRUN_WEI, get_min_profitable_size_wei(chain, _effective_dec))

    backrun_size_wei = max(event.amount_in_wei // 10, 1)
    backrun_size_wei = max(MIN_BACKRUN_WEI, min(MAX_BACKRUN_WEI, backrun_size_wei))
    if backrun_size_wei != max(event.amount_in_wei // 10, 1):
        size_source = "dynamic_bounded"

    # M7.A.5.9: Compute USD estimate if oracle price available
    _size_usd: Optional[float] = None
    if oracle_result and oracle_result.get("token_in_oracle_usd"):
        _price = oracle_result["token_in_oracle_usd"]
        _size_usd = round(backrun_size_wei / (10 ** _effective_dec) * _price, 2)
    # Reviewer post-soak19 fix #5: stablecoin USD coarse fallback so candidates
    # with a recognised stable token still arrive at the gate with a non-null
    # ``size_usd_estimate`` even when oracle is silent. Non-stables stay None.
    if _size_usd is None:
        _in_sym_us = _ats.get(token_in_addr.lower(), "").upper()
        if _in_sym_us in ("USDC", "USDT", "USDC.E", "USDT.E", "USDBC", "DAI", "PYUSD", "FRAX"):
            try:
                _size_usd = round(backrun_size_wei / (10 ** _effective_dec) * 1.0, 2)
            except Exception:
                _size_usd = None

    # ── M7.A.5.21: Gas-floor prefilter ──────────────────────────────────
    _gas_floor_exceeded = False
    _gas_floor_bps: Optional[float] = None
    if _size_usd is not None and _size_usd > 0:
        # Chain-aware gas cost in USD: gas_eth_wei * eth_price / 1e18
        _gas_eth_wei_est = int(DEFAULT_BACKRUN_GAS * get_gas_price_gwei(chain) * 1e9)
        _est_eth_price: Optional[float] = None
        if oracle_result:
            _in_sym = _ats.get(token_in_addr.lower(), "")
            _out_sym = _ats.get(token_out_addr.lower(), "")
            if _in_sym.upper() in ("WETH", "ETH"):
                _est_eth_price = oracle_result.get("token_in_oracle_usd")
            elif _out_sym.upper() in ("WETH", "ETH"):
                _est_eth_price = oracle_result.get("token_out_oracle_usd")
        if _est_eth_price is None:
            # N1 (E5 follow-up): prefer LIVE resolver (no stale table) over
            # the 3500.0 constant. allow_default_fallback=False ensures we
            # only override _FALLBACK_ETH_PRICE_USD when a dynamic_anchors or
            # config source actually has WETH; otherwise the old behavior is
            # preserved byte-for-byte.
            try:
                from strategy.quotes import resolve_token_usd_price
                _resolved = resolve_token_usd_price(
                    "WETH", chain=chain, allow_default_fallback=False,
                )
                if _resolved is not None and _resolved > 0:
                    _est_eth_price = float(_resolved)
            except Exception:
                pass
        if _est_eth_price is None:
            _est_eth_price = _FALLBACK_ETH_PRICE_USD
        _gas_usd = _gas_eth_wei_est * _est_eth_price / 1e18
        _gas_floor_bps = round(_gas_usd / _size_usd * 10000, 2) if _size_usd > 0 else None
        if _gas_floor_bps is not None and _gas_floor_bps > get_gas_floor_bps(chain):
            _gas_floor_exceeded = True

    # ── M7.A.5.22: Gas-floor operational filter for stale events ────────
    # If event is already stale (block_lag > 2) AND gas floor exceeded,
    # skip further scoring — this event cannot be executable and gas will
    # dominate any theoretical net. Saves RPC budget for low-lag events.
    _preliminary_lag = current_block - event.block_number
    if _gas_floor_exceeded and _preliminary_lag > 2:
        r = _reject(
            REJECT_GAS_FLOOR_EXCEEDED,
            pr=pair_resolved, ap=actual_pair, adm=True,
            adm_src=adm_source, orc=oracle_result,
            cov=coverage, sg_seed=sg_seed,
            pct=_pool_truth, psrp=_pool_read_path,
        )
        r.registry_pools_found = _registry_pools_found
        r.registry_pools_active = _registry_pools_active
        r.gas_floor_exceeded = True
        r.gas_floor_bps = _gas_floor_bps
        r.scoring_path = _scoring_path
        return r

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

    # ── M7.A.5.24: Skip Stage A multicall for registry_direct fast path ─
    # Registry already discovered pools; multicall pruning is redundant.
    stage_a_start = time.monotonic()
    venues_pruned = 0
    prune_reasons: Dict[str, int] = {}
    quote_calls_after = 0

    if _scoring_path == "registry_direct":
        # Skip Stage A entirely — registry pools are the truth
        stage_a_ms = 0.0
        quote_calls_after = 0
    else:
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
        for _dn, cfg, _q in quotable_dexes:
            fee_tiers = cfg.get("fee_tiers", _DEFAULT_FEE_TIERS)
            quote_calls_after += len(fee_tiers[:2]) * 2  # buy + sell

    # ── M7.A.5.20: Local-state-first pricing attempt ───────────────────
    local_pricing_attempted = False
    local_pricing_used = False
    local_pricing_failure_reason = None
    local_pricing_ms = None
    _local_result = None

    if local_sim and local_sim.get("pool_states"):
        _lp_start = time.monotonic()
        local_pricing_attempted = True
        try:
            _local_result = attempt_local_pricing(
                candidate_pools=cand_pools,
                local_sim_states=local_sim["pool_states"],
                token_in_addr=token_in_addr,
                token_out_addr=token_out_addr,
                backrun_size_wei=backrun_size_wei,
                registry_entries=_registry_entries if _registry_entries else None,
            )
            if _local_result is None:
                local_pricing_failure_reason = "no_pools_priced"
        except Exception as _lp_exc:
            local_pricing_failure_reason = f"error:{type(_lp_exc).__name__}"
        local_pricing_ms = round((time.monotonic() - _lp_start) * 1000, 2)

    # ── M7.A.5.27: Wall-clock mid-pipeline abort for executable lane ────
    # Replace expensive RPC block check with deterministic wall-clock budget.
    # If elapsed time exceeds block_time_ms, the event has almost certainly
    # become stale — abort remaining heavy work (Stage B, sweep) to save budget.
    _mid_pipeline_aborted = False
    _budget_ms = block_time_ms or 250.0
    _elapsed_ms = (time.monotonic() - pipeline_start) * 1000
    if _is_low_lag and _elapsed_ms > _budget_ms:
        _mid_pipeline_aborted = True
        _mid_pipeline_ms = round(_elapsed_ms, 2)
        _mid_stage_latency = {
            "stage_a_ms": stage_a_ms if isinstance(stage_a_ms, float) else 0.0,
            "stage_b_ms": 0.0,
            "mid_pipeline_abort": True,
            "mid_pipeline_budget_exceeded_ms": round(_elapsed_ms, 2),
            "resolve_ms": _resolve_ms,
            "enrichment_ms": _enrichment_ms,
            "admission_ms": _admission_ms,
            "oracle_ms": _oracle_ms,
            "registry_preload_ms": _registry_preload_ms,
        }
        if local_pricing_ms is not None:
            _mid_stage_latency["local_pricing_ms"] = local_pricing_ms
            _mid_stage_latency["local_pricing_used"] = _local_result is not None
        # If local pricing produced amounts, compute net for diagnostic
        if _local_result is not None:
            if _size_usd is None:
                _mid_eth_price_usd: Optional[float] = None
                if oracle_result:
                    if (in_sym or "").upper() in _ETH_USD_SYMBOLS:
                        _mid_eth_price_usd = oracle_result.get("token_in_oracle_usd")
                    elif (out_sym or "").upper() in _ETH_USD_SYMBOLS:
                        _mid_eth_price_usd = oracle_result.get("token_out_oracle_usd")
                _mid_out_dec_usd = get_cached_decimals(token_out_addr)
                _size_usd = _quote_implied_size_usd(
                    amount_in_wei=int(backrun_size_wei),
                    decimals_in=_effective_dec,
                    symbol_in=in_sym or _ats.get(token_in_addr.lower(), ""),
                    amount_out_wei=int(_local_result.get("buy_amount") or 0),
                    decimals_out=_mid_out_dec_usd,
                    symbol_out=out_sym or _ats.get(token_out_addr.lower(), ""),
                    eth_price_usd=_mid_eth_price_usd,
                )
            _mid_buy = _local_result["buy_amount"]
            _mid_sell = _local_result["sell_amount"]
            _mid_gross = _mid_sell - backrun_size_wei
            _mid_gas_eth_wei = int(DEFAULT_BACKRUN_GAS * get_gas_price_gwei(chain) * 1e9)
            _mid_gas_cost = _gas_cost_in_token_wei(
                _mid_gas_eth_wei, _effective_dec,
                token_price_usd=_tok_price_usd if '_tok_price_usd' in dir() else None,
                eth_price_usd=_eth_price_usd if '_eth_price_usd' in dir() else None,
            )
            _mid_net = _mid_gross - _mid_gas_cost
            _mid_net_bps = (_mid_net / backrun_size_wei) * 10000 if backrun_size_wei > 0 else 0.0
            _mid_gas_decomp = estimate_gas_decomposition_bps(backrun_size_wei, _mid_gas_cost)
            _PRICING_ANOMALY_BPS_MID = 10000
            if abs(_mid_net_bps) > _PRICING_ANOMALY_BPS_MID:
                _mid_reject = REJECT_PRICING_ANOMALY
            elif _mid_net_bps > 0:
                _mid_reject = REJECT_STALE_POSITIVE
            else:
                _mid_reject = REJECT_GAS_EXCEEDS_GROSS
            return BackrunResult(
                event_id=event.event_id,
                event_source="live",
                event_type=event.event_type,
                post_trade_state_used="live",
                backrun_direction=backrun_dir,
                best_buy_venue=_local_result.get("buy_dex", _local_result["buy_venue"]),
                best_sell_venue=_local_result.get("sell_dex", _local_result["sell_venue"]),
                best_buy_fee=_local_result.get("buy_fee", 0),
                best_sell_fee=_local_result.get("sell_fee", 0),
                amount_in_wei=backrun_size_wei,
                gross_pnl_wei=_mid_gross,
                gas_cost_wei=_mid_gas_cost,
                fee_cost_wei=0,
                net_pnl_wei=_mid_net,
                best_backrun_net_bps=round(_mid_net_bps, 4),
                same_block_possible=False,
                route_viable=False,
                reject_reason=_mid_reject,
                event_block=event.block_number,
                quote_block=current_block,
                block_lag=current_block - event.block_number,
                same_state_class="stale",
                counter_venue_count=_local_result["pools_succeeded"],
                best_live_net_bps=round(_mid_net_bps, 4),
                ws_provider=ws_provider,
                event_detected_at_block=event_detected_at_block,
                quote_started_block=quote_started_block,
                quote_finished_block=current_block,
                quote_pipeline_latency_ms=_mid_pipeline_ms,
                venues_pruned_by_multicall=0,
                latency_budget_ms=block_time_ms,
                quote_calls_attempted=0,
                quote_calls_after_pruning=0,
                pipeline_stage_latency_ms=_mid_stage_latency,
                pair_resolved=pair_resolved,
                actual_pair=actual_pair,
                backrun_token_in_address=token_in_addr,
                backrun_token_out_address=token_out_addr,
                size_source=size_source,
                coverage_result=coverage,
                token_admitted=True,
                admission_source=adm_source,
                oracle_guard=oracle_result,
                local_sim_state=local_sim,
                l2_gas_bps=_mid_gas_decomp["l2_gas_bps"],
                l1_data_bps=_mid_gas_decomp["l1_data_bps"],
                total_gas_bps=_mid_gas_decomp["total_gas_bps"],
                subgraph_seed_used=sg_seed,
                token_in_decimals=_token_in_dec,
                size_normalization_source=_norm_source,
                size_usd_estimate=_size_usd,
                size_valid_for_token=(_token_in_dec is not None),
                pool_contract_truth=_pool_truth,
                pool_state_read_path=_pool_read_path,
                local_pricing_attempted=local_pricing_attempted,
                local_pricing_used=True,
                local_pricing_failure_reason=None,
                registry_pools_found=_registry_pools_found,
                registry_pools_active=_registry_pools_active,
                adapter_type_used=_local_result.get("pricing_path"),
                gas_floor_exceeded=_gas_floor_exceeded,
                gas_floor_bps=_gas_floor_bps,
                pricing_path=_local_result.get("pricing_path"),
                scoring_path=_scoring_path,
            )
        # No local result — just reject as budget exceeded
        return _reject(
            REJECT_GAS_EXCEEDS_GROSS,
            pr=pair_resolved, ap=actual_pair, adm=True,
            adm_src=adm_source, orc=oracle_result,
            cov=coverage, lss=local_sim, sg_seed=sg_seed,
            pct=_pool_truth, psrp=_pool_read_path,
        )

    # ── Stage B: Confirmatory QuoterV2 quotes ───────────────────────────
    # M7.A.5.20: Skip remote quoter if local pricing succeeded (fast path)
    stage_b_start = time.monotonic()
    best_buy_amount = None
    best_buy_venue = None
    best_sell_amount = None
    best_sell_venue = None
    venues_quoted = 0
    _buy_fail_info: list = []  # M7.A.5.19: capture quote failure provenance
    _price_impact_bps_computed: Optional[float] = None  # E1.63 step 8

    if _local_result is not None:
        # Local pricing produced a result — use it, skip remote quoter
        local_pricing_used = True
        best_buy_amount = _local_result["buy_amount"]
        best_sell_amount = _local_result["sell_amount"]
        best_buy_venue = _local_result.get("buy_dex", _local_result["buy_venue"])
        best_sell_venue = _local_result.get("sell_dex", _local_result["sell_venue"])
        venues_quoted = _local_result["pools_succeeded"]
        _local_eth_price_usd: Optional[float] = None
        if oracle_result:
            if (in_sym or "").upper() in _ETH_USD_SYMBOLS:
                _local_eth_price_usd = oracle_result.get("token_in_oracle_usd")
            elif (out_sym or "").upper() in _ETH_USD_SYMBOLS:
                _local_eth_price_usd = oracle_result.get("token_out_oracle_usd")
        # E1.73: when oracle is silent, allow constant ETH price fallback so
        # frontier-sweep candidates with WETH on either leg can be USD-sized.
        # Mirrors the hot fast-path behaviour and keeps slow path consistent.
        if _local_eth_price_usd is None and (
            (in_sym or "").upper() in _ETH_USD_SYMBOLS
            or (out_sym or "").upper() in _ETH_USD_SYMBOLS
            or (_ats.get(token_in_addr.lower(), "").upper() in _ETH_USD_SYMBOLS)
            or (_ats.get(token_out_addr.lower(), "").upper() in _ETH_USD_SYMBOLS)
        ):
            try:
                from m7.shared.constants import _FALLBACK_ETH_PRICE_USD
                _local_eth_price_usd = float(_FALLBACK_ETH_PRICE_USD)
            except Exception:
                _local_eth_price_usd = None
        if _size_usd is None:
            _out_dec_local_usd = get_cached_decimals(token_out_addr)
            _size_usd = _quote_implied_size_usd(
                amount_in_wei=int(backrun_size_wei),
                decimals_in=_effective_dec,
                symbol_in=in_sym or _ats.get(token_in_addr.lower(), ""),
                amount_out_wei=int(best_buy_amount) if best_buy_amount else None,
                decimals_out=_out_dec_local_usd,
                symbol_out=out_sym or _ats.get(token_out_addr.lower(), ""),
                eth_price_usd=_local_eth_price_usd,
            )
        # E1.62 step 2: sweep a USD frontier to find the max-profit size.
        # Falls back to single _usd_target_rescaled_size_wei when frontier is disabled.
        _frontier_sizes = _usd_frontier_sizes_wei(
            amount_in_wei=int(backrun_size_wei),
            current_size_usd=_size_usd,
        )
        if not _frontier_sizes:
            # Legacy single-target rescale (backward compat / when no USD basis)
            _single = _usd_target_rescaled_size_wei(
                amount_in_wei=int(backrun_size_wei),
                current_size_usd=_size_usd,
            )
            _frontier_sizes = [_single] if _single is not None else []

        # Pick the size from the frontier that maximises expected_profit_usd.
        # expected_profit_usd = size_usd * net_bps / 10_000
        # We approximate: for each candidate size, compute a price-implication
        # by calling attempt_local_pricing, then pick best absolute edge.
        _best_size_wei = None
        _best_result = None
        _best_profit_usd: float = -1.0
        _best_is_split = False  # E1.63 step 7: tracks if split routing won
        _split_route_enable = os.getenv("ARBY_SPLIT_ROUTE_ENABLE", "0") == "1"  # E1.63 step 7
        # E1.64-3: depth curve — capture (size_usd, price_impact_bps, net_bps,
        # expected_profit_usd) per probed size so reviewer can verify where the
        # pool starts to be liquidity-bound.  Attached to result via setattr
        # for runtime telemetry; not part of the persisted contract.
        _depth_curve: List[Dict[str, Any]] = []
        for _candidate_size_wei in _frontier_sizes:
            try:
                _cand_result = attempt_local_pricing(
                    candidate_pools=cand_pools,
                    local_sim_states=local_sim["pool_states"],
                    token_in_addr=token_in_addr,
                    token_out_addr=token_out_addr,
                    backrun_size_wei=_candidate_size_wei,
                    registry_entries=_registry_entries if _registry_entries else None,
                )
            except Exception:
                continue
            if _cand_result is None:
                continue
            # Compute net_bps for this size
            _cb = _cand_result.get("buy_amount")
            _cs = _cand_result.get("sell_amount")
            if not (_cb and _cs and _cs > 0):
                continue
            _cand_net_bps = _roundtrip_net_bps_from_sell(
                int(_candidate_size_wei), int(_cs)
            )
            # Compute size_usd for candidate
            _cand_size_usd = _quote_implied_size_usd(
                amount_in_wei=int(_candidate_size_wei),
                decimals_in=_effective_dec,
                symbol_in=in_sym or _ats.get(token_in_addr.lower(), ""),
                amount_out_wei=int(_cb) if _cb else None,
                decimals_out=get_cached_decimals(token_out_addr),
                symbol_out=out_sym or _ats.get(token_out_addr.lower(), ""),
                eth_price_usd=_local_eth_price_usd,
            )
            if _cand_size_usd is None or _cand_size_usd <= 0:
                # Frontier hit token without USD basis — skip, keep original size
                continue
            _cand_profit_usd = _cand_size_usd * _cand_net_bps / 10_000.0
            # E1.64-3: capture depth-curve point (single-route, pre-split).
            # price_impact_bps is computed below the frontier loop for the
            # winning size; here we expose net_bps + size_usd which is enough
            # to plot expected_profit(size) and detect cliff behaviour.
            try:
                _depth_curve.append({
                    "size_wei": int(_candidate_size_wei),
                    "size_usd": round(float(_cand_size_usd), 6),
                    "net_bps": round(float(_cand_net_bps), 3),
                    "expected_profit_usd": round(float(_cand_profit_usd), 6),
                })
            except Exception:
                pass
            _cand_is_split = False
            # E1.63 step 7: optionally try 50/50 split routing at this size
            if _split_route_enable:
                # Track that split routing was attempted for this candidate
                global _e163_split_route_attempted
                try:
                    with _e163_lock:
                        _e163_split_route_attempted += 1
                except Exception:
                    pass
                try:
                    _sr = attempt_split_pricing(
                        candidate_pools=cand_pools,
                        local_sim_states=local_sim["pool_states"],
                        token_in_addr=token_in_addr,
                        token_out_addr=token_out_addr,
                        backrun_size_wei=_candidate_size_wei,
                        registry_entries=_registry_entries if _registry_entries else None,
                    )
                    if _sr is not None:
                        _srb = _sr.get("buy_amount")
                        _srs = _sr.get("sell_amount")
                        if _srb and _srs and int(_srs) > 0:
                            _sr_net = _roundtrip_net_bps_from_sell(
                                int(_candidate_size_wei), int(_srs)
                            )
                            _sr_usd = _quote_implied_size_usd(
                                amount_in_wei=int(_candidate_size_wei),
                                decimals_in=_effective_dec,
                                symbol_in=in_sym or _ats.get(token_in_addr.lower(), ""),
                                amount_out_wei=int(_srb),
                                decimals_out=get_cached_decimals(token_out_addr),
                                symbol_out=out_sym or _ats.get(token_out_addr.lower(), ""),
                                eth_price_usd=_local_eth_price_usd,
                            )
                            if _sr_usd and _sr_usd > 0:
                                _sr_profit = _sr_usd * _sr_net / 10_000.0
                                if _sr_profit > _cand_profit_usd:
                                    _cand_result = _sr
                                    _cand_profit_usd = _sr_profit
                                    _cand_is_split = True
                                    # Track split win
                                    global _e163_split_route_win
                                    try:
                                        with _e163_lock:
                                            _e163_split_route_win += 1
                                    except Exception:
                                        pass
                except Exception:
                    pass  # split is best-effort
            if _cand_profit_usd > _best_profit_usd:
                _best_profit_usd = _cand_profit_usd
                _best_size_wei = _candidate_size_wei
                _best_result = _cand_result
                _best_is_split = _cand_is_split

        if _best_result is not None and _best_size_wei is not None:
            backrun_size_wei = _best_size_wei
            _local_result = _best_result
            best_buy_amount = _local_result["buy_amount"]
            best_sell_amount = _local_result["sell_amount"]
            best_buy_venue = _local_result.get("buy_dex", _local_result["buy_venue"])
            best_sell_venue = _local_result.get("sell_dex", _local_result["sell_venue"])
            venues_quoted = _local_result["pools_succeeded"]
            size_source = "usd_frontier_split" if _best_is_split else "usd_frontier_rescaled"
            _out_dec_target_usd = get_cached_decimals(token_out_addr)
            _target_usd = _quote_implied_size_usd(
                amount_in_wei=int(backrun_size_wei),
                decimals_in=_effective_dec,
                symbol_in=in_sym or _ats.get(token_in_addr.lower(), ""),
                amount_out_wei=int(best_buy_amount) if best_buy_amount else None,
                decimals_out=_out_dec_target_usd,
                symbol_out=out_sym or _ats.get(token_out_addr.lower(), ""),
                eth_price_usd=_local_eth_price_usd,
            )
            if _target_usd is not None:
                _size_usd = _target_usd
        # E1.63 step 8: depth guard — compute price_impact_bps from best buy pool state.
        # Uses sqrtPriceAfter vs sqrtPriceBefore from local V3 math (no extra RPC).
        # price = sqrtP^2 → price_impact = |1 - (sqrtAfter/sqrtBefore)^2| * 10_000.
        # ENV: ARBY_PRICE_IMPACT_MAX_BPS (default 1000 = 10%): when exceeded,
        # sets liquidity_depth_usd=0 to signal thin pool to cold_immediate_sim.
        if _local_result is not None and local_sim and local_sim.get("pool_states"):
            _pi_pool = _local_result.get("buy_venue")
            _pi_fee = _local_result.get("buy_fee") or 3000
            if _pi_pool:
                _pi_state = local_sim["pool_states"].get(_pi_pool)
                if _pi_state:
                    _pi_sp_before = _pi_state.get("sqrt_price_x96") or 0
                    _pi_liq = _pi_state.get("liquidity") or 0
                    if _pi_sp_before > 0 and _pi_liq > 0:
                        # Track depth guard attempted
                        global _e163_depth_guard_attempted
                        try:
                            with _e163_lock:
                                _e163_depth_guard_attempted += 1
                        except Exception:
                            pass
                        try:
                            _pi_sp_after = compute_v3_sqrt_price_after(
                                sqrt_price_x96=int(_pi_sp_before),
                                liquidity=int(_pi_liq),
                                amount_in=int(backrun_size_wei),
                                fee_pips=int(_pi_fee),
                                zero_for_one=(token_in_addr.lower() < token_out_addr.lower()),
                            )
                            if _pi_sp_after is not None:
                                _pi_ratio = (_pi_sp_after / _pi_sp_before) ** 2
                                _price_impact_bps_computed = round(
                                    abs(1.0 - _pi_ratio) * 10_000.0, 2
                                )
                                # Track price_impact_bps populated
                                global _e163_price_impact_populated
                                try:
                                    with _e163_lock:
                                        _e163_price_impact_populated += 1
                                except Exception:
                                    pass
                        except Exception:
                            pass  # price impact is best-effort
        # ── N5: Accumulate dynamic_anchors sample from live pool state ──
        # Fire-and-forget; never fail the hot path if recording has issues.
        try:
            from strategy.dynamic_anchors import record_m7_anchor_sample
            _out_dec = get_cached_decimals(token_out_addr)
            record_m7_anchor_sample(
                chain_key=chain,
                symbol_in=in_sym,
                symbol_out=out_sym,
                amount_in_wei=int(backrun_size_wei),
                amount_out_wei=int(best_buy_amount) if best_buy_amount else 0,
                decimals_in=_token_in_dec,
                decimals_out=_out_dec,
                dex_id=str(_local_result.get("buy_dex") or "unknown"),
                fee_tier=int(_local_result.get("buy_fee") or 0),
                block=int(event.block_number or 0),
            )
        except Exception:
            pass
    else:
        # Remote quoter path (slow, confirmatory)
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
                        return ("ok", dex_name, amt)
                return ("fail", dex_name, "zero_or_rate_limited")
            except Exception as exc:
                return ("fail", dex_name, type(exc).__name__)

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
                    if result is not None and result[0] == "ok":
                        _, dex_name, amt = result
                        venues_quoted += 1
                        if best_buy_amount is None or amt > best_buy_amount:
                            best_buy_amount = amt
                            best_buy_venue = dex_name
                    elif result is not None and result[0] == "fail":
                        _buy_fail_info.append((result[1], result[2]))

        # Parallel sell pass: sell best_buy_amount back
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

    # N5: Accumulate dynamic_anchors sample from remote quoter path too.
    # Same rationale as the local_pricing branch above — fire-and-forget.
    if (
        _local_result is None
        and best_buy_amount is not None
        and best_buy_amount > 0
        and in_sym
        and out_sym
    ):
        try:
            from strategy.dynamic_anchors import record_m7_anchor_sample
            _out_dec = get_cached_decimals(token_out_addr)
            record_m7_anchor_sample(
                chain_key=chain,
                symbol_in=in_sym,
                symbol_out=out_sym,
                amount_in_wei=int(backrun_size_wei),
                amount_out_wei=int(best_buy_amount),
                decimals_in=_token_in_dec,
                decimals_out=_out_dec,
                dex_id=str(best_buy_venue or "quoter_v2"),
                fee_tier=0,
                block=int(event.block_number or 0),
            )
        except Exception:
            pass

    stage_b_ms = round((time.monotonic() - stage_b_start) * 1000, 2)
    pipeline_end = time.monotonic()
    pipeline_ms = round((pipeline_end - pipeline_start) * 1000, 2)

    stage_latency = {"stage_a_ms": stage_a_ms, "stage_b_ms": stage_b_ms}

    # M7.A.5.30: Full pipeline stage breakdown
    stage_latency["resolve_ms"] = _resolve_ms
    stage_latency["enrichment_ms"] = _enrichment_ms
    stage_latency["admission_ms"] = _admission_ms
    stage_latency["oracle_ms"] = _oracle_ms
    stage_latency["registry_preload_ms"] = _registry_preload_ms

    # M7.A.5.20: Inject local pricing latency
    if local_pricing_ms is not None:
        stage_latency["local_pricing_ms"] = local_pricing_ms
        stage_latency["local_pricing_used"] = local_pricing_used

    # M7.A.5.19: Inject quote_fail provenance when all buy quotes failed
    if venues_quoted == 0 and _buy_fail_info:
        _fail_venues = sorted(set(v for v, _ in _buy_fail_info))
        _fail_excs = sorted(set(e for _, e in _buy_fail_info))
        stage_latency["quote_fail_stage"] = "buy"
        stage_latency["quote_fail_venue"] = ",".join(_fail_venues)
        stage_latency["quote_fail_exception_short"] = ",".join(_fail_excs)

    # Get current block after quoting for lag measurement
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        rpc_throttle.acquire()
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

    # ── M7.A.5.9: Gas denomination conversion ──────────────────────────
    # Gas is paid in ETH; convert to backrun token denomination for bps.
    _gas_eth_wei = int(DEFAULT_BACKRUN_GAS * get_gas_price_gwei(chain) * 1e9)
    _eth_price_usd: Optional[float] = None
    _tok_price_usd: Optional[float] = None
    if oracle_result:
        _tok_price_usd = oracle_result.get("token_in_oracle_usd")
        # Check if either scored token is WETH to reuse its price
        if in_sym and in_sym.upper() in ("WETH", "ETH"):
            _eth_price_usd = oracle_result.get("token_in_oracle_usd")
        elif out_sym and out_sym.upper() in ("WETH", "ETH"):
            _eth_price_usd = oracle_result.get("token_out_oracle_usd")
    # Separate WETH oracle call if not already available
    if _eth_price_usd is None:
        try:
            _eth_orc = check_oracle_sanity("WETH", None, rpc_url, current_block, chain=chain)
            _eth_price_usd = _eth_orc.get("token_in_oracle_usd")
        except Exception:
            pass
    gas_cost_wei = _gas_cost_in_token_wei(
        _gas_eth_wei, _effective_dec,
        token_price_usd=_tok_price_usd,
        eth_price_usd=_eth_price_usd,
    )
    if _size_usd is None and best_buy_amount is not None:
        _out_dec_for_usd = get_cached_decimals(token_out_addr)
        _size_usd = _quote_implied_size_usd(
            amount_in_wei=int(backrun_size_wei),
            decimals_in=_effective_dec,
            symbol_in=in_sym or _ats.get(token_in_addr.lower(), ""),
            amount_out_wei=int(best_buy_amount),
            decimals_out=_out_dec_for_usd,
            symbol_out=out_sym or _ats.get(token_out_addr.lower(), ""),
            eth_price_usd=_eth_price_usd,
        )

    if best_buy_amount is not None and best_sell_amount is not None:
        gross_wei = best_sell_amount - backrun_size_wei
        net_wei = gross_wei - gas_cost_wei
        net_bps = (net_wei / backrun_size_wei) * 10000 if backrun_size_wei > 0 else 0.0

        # M7.A.5.25: Pricing anomaly gate — absurd net_bps from thin-liquidity local pricing
        # 10000 bps = 100% return, anything above is almost certainly a pricing artifact
        _PRICING_ANOMALY_BPS = 10000
        if abs(net_bps) > _PRICING_ANOMALY_BPS:
            route_viable = False
            reject_reason = REJECT_PRICING_ANOMALY
        # M7.A.5.10: Stale-gate — positive but stale quotes are not executable
        elif net_bps > 0 and block_lag <= 2:
            route_viable = True
            reject_reason = None
        elif net_bps > 0:
            route_viable = False
            reject_reason = REJECT_STALE_POSITIVE
        else:
            route_viable = False
            reject_reason = REJECT_GAS_EXCEEDS_GROSS

        # Build candidate_path with actual symbols if pair resolved
        if pair_resolved and actual_pair:
            parts = actual_pair.split("/")
            cand_path = [parts[1], parts[0], parts[1]] if len(parts) == 2 else [event.token_out, event.token_in, event.token_out]
        else:
            cand_path = [event.token_out, event.token_in, event.token_out]

        # ── M7.A.5.6: Bounded size sweep ───────────────────────────────
        # M7.A.5.24: Skip size sweep for registry_direct fast path
        # (minimal scoring: registry → local pricing → economics → done)
        # Reviewer post-soak19 fix #6: ARBY_HOT_SWEEP_ENABLE=1 lifts the gate
        # so registry_direct events also run a bounded sweep, populating
        # ``size_sweep_metrics.events_with_sweep > 0`` for acceptance evidence.
        # E1.62 step 4: sweep enabled for registry_direct by default to fix
        # cold/proof lane missing sweep; only hot fast-path respects sweep-disable.
        # Hot fast-path is identified by scoring_path == "registry_direct" AND
        # the caller context is the hot-lane (not bridged from cold_immediate_sim).
        # We approximate this by checking ARBY_HOT_SWEEP_ENABLE vs. hot_mode env.
        _hot_sweep_enable = os.getenv("ARBY_HOT_SWEEP_ENABLE", "0") == "1"
        _is_hot_fast_path = (
            _scoring_path == "registry_direct"
            and os.getenv("ARBY_COLD_IMMEDIATE_SIM", "0") != "1"
        )
        _sweep_allowed = (not _is_hot_fast_path) or _hot_sweep_enable
        sweep_results = None
        best_sweep_net = None
        best_sweep_size = None
        if _sweep_allowed:
            try:
                sweep_results = _run_size_sweep(
                    event, rpc_url, token_in_addr, token_out_addr,
                    quotable_dexes, backrun_size_wei, chain, fallback_rpc_urls,
                    token_in_decimals=_token_in_dec,
                    gas_cost_token_wei=gas_cost_wei,
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

        _slow_result = BackrunResult(
            event_id=event.event_id,
            event_source="live",
            event_type=event.event_type,
            post_trade_state_used="live",
            backrun_direction=backrun_dir,
            best_buy_venue=best_buy_venue,
            best_sell_venue=best_sell_venue,
            best_buy_fee=_local_result.get("buy_fee", 0) if _local_result else None,
            best_sell_fee=_local_result.get("sell_fee", 0) if _local_result else None,
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
            backrun_token_in_address=token_in_addr,
            backrun_token_out_address=token_out_addr,
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
            token_in_decimals=_token_in_dec,
            size_normalization_source=_norm_source,
            size_usd_estimate=_size_usd,
            size_valid_for_token=(_token_in_dec is not None),
            pool_contract_truth=_pool_truth,
            pool_state_read_path=_pool_read_path,
            local_pricing_attempted=local_pricing_attempted,
            local_pricing_used=local_pricing_used,
            local_pricing_failure_reason=local_pricing_failure_reason,
            registry_pools_found=_registry_pools_found,
            registry_pools_active=_registry_pools_active,
            adapter_type_used=_local_result.get("pricing_path") if _local_result else None,
            gas_floor_exceeded=_gas_floor_exceeded,
            gas_floor_bps=_gas_floor_bps,
            pricing_path=_local_result.get("pricing_path") if _local_result else None,
            scoring_path=_scoring_path,
            # E1.62 step 1: populate observability fields for cold_immediate_sim ranking
            expected_profit_usd=(
                round(_size_usd * net_bps / 10_000.0, 6)
                if (_size_usd and _size_usd > 0 and "net_bps" in dir())
                else None
            ),
            amount_in_optimal_usd=_size_usd,
            price_impact_bps=_price_impact_bps_computed,
            # E1.65: best trade amounts for USD basis fallback in bridge/cold lane
            best_buy_amount_wei=int(best_buy_amount) if best_buy_amount else None,
            best_sell_amount_wei=int(best_sell_amount) if best_sell_amount else None,
            usd_basis_source=_usd_basis_source(
                in_sym or _ats.get(token_in_addr.lower(), ""),
                out_sym or _ats.get(token_out_addr.lower(), ""),
                _size_usd,
            ),
        )
        # E1.64-3: attach depth curve via setattr (runtime telemetry; not in
        # the persisted BackrunResult schema).  Consumers (hot rollup, bridge
        # writer) can pick it up via getattr.
        try:
            if _depth_curve:
                setattr(_slow_result, "depth_curve", list(_depth_curve))
        except Exception:
            pass
        return _slow_result

    # M7.A.5.6: Split QUOTE_FAILURE — distinguish RPC failure from no-route
    fail_reason = REJECT_RPC_QUOTE_FAIL if venues_quoted == 0 else REJECT_PAIR_RESOLVED_UNTRADEABLE
    result = BackrunResult(
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
        pool_contract_truth=_pool_truth,
        pool_state_read_path=_pool_read_path,
        local_pricing_attempted=local_pricing_attempted,
        local_pricing_used=local_pricing_used,
        local_pricing_failure_reason=local_pricing_failure_reason,
        registry_pools_found=_registry_pools_found,
        registry_pools_active=_registry_pools_active,
        gas_floor_exceeded=_gas_floor_exceeded,
        gas_floor_bps=_gas_floor_bps,
        scoring_path=_scoring_path,
    )


# ---------------------------------------------------------------------------
# M7.A.5.36: Fast scoring path — preloaded registry, zero discovery
# Per-stage hard budget abort: any stage exceeding its budget → return None.
# ---------------------------------------------------------------------------

def score_backrun_fast(
    event: OrderflowEvent,
    pool_registry: Any,
    token_addresses: Dict[str, str],
    current_block: int,
    *,
    event_detected_at_block: Optional[int] = None,
    block_time_ms: Optional[float] = None,
    addr_to_symbol: Optional[Dict[str, str]] = None,
    chain: str = "arbitrum_one",
    l1_fee_bps: Optional[float] = None,
) -> Optional[BackrunResult]:
    """Score a backrun using pre-warmed registry only. Zero RPC in hot path.

    This is the fast path for the hot lane. It assumes:
    - Pool registry already has preloaded pairs
    - Pool state is cached in registry entries
    - No token enrichment, no subgraph, no oracle check
    - Single-size local math only

    Returns BackrunResult or None if pair not in registry / no state.
    Total budget: HOT_BUDGET_TOTAL_MS (250ms hard abort).

    M7.A.5.33: Adds per-stage timing (registry_lookup_ms, pool_state_ms,
    local_math_ms, profit_guard_ms, tx_build_ms) and integrated profit_guard.
    """
    import time

    pipeline_start = time.monotonic()
    backrun_dir = classify_event_backrun_type(event)

    # Fast pair resolution from addr_to_symbol (O(1) lookup, no RPC)
    if not addr_to_symbol or not event.pool_address:
        return None

    _ats = addr_to_symbol

    # M7.A.5.41: Resolve actual token addresses from _pool_token_cache.
    # event.token_in / event.token_out contain direction tags ("token0_in",
    # "token1_in", "token0", "token1") — NOT symbol names. The cold lane
    # populates _pool_token_cache with immutable pool→(token0, token1, fee)
    # mappings. Use pool_address + direction to resolve actual addresses.
    _cache_key = event.pool_address.lower()
    _cached_pool = _pool_token_cache.get(_cache_key)
    if _cached_pool is None:
        return None  # Pool not yet seen by cold lane — skip

    _token0_addr, _token1_addr, _pool_fee = _cached_pool
    _direction = event.token_in  # "token0_in" or "token1_in"
    if _direction == "token0_in":
        token_in_addr = _token0_addr   # victim's in (consistent with cold path)
        token_out_addr = _token1_addr  # victim's out
    elif _direction == "token1_in":
        token_in_addr = _token1_addr
        token_out_addr = _token0_addr
    else:
        return None  # Unknown direction tag

    if not token_in_addr or not token_out_addr:
        return None

    # ── Stage 1: Registry lookup (O(1) cache hit) ──────────────────────
    _reg_start = time.monotonic()
    entries = pool_registry.lookup_pair(token_in_addr, token_out_addr)
    if not entries:
        # M7.E1.47/P0: Direct (in, out) miss. Probe for triangular candidates
        # via intent-token graph. If at least one X exists s.t. registry has
        # active (in, X) AND (X, out), surface the count + first sample as a
        # detection signal (real triangle scoring is a follow-up iteration).
        _tri_intermediates: list = []
        try:
            _tri_intermediates = pool_registry.find_triangular_intermediates(
                token_in_addr, token_out_addr, max_results=4
            )
        except Exception:
            _tri_intermediates = []
        if _tri_intermediates:
            _tri_count = len(_tri_intermediates)
            _tri_first = _tri_intermediates[0]
            _lag_t = current_block - event.block_number
            if _lag_t == 0:
                _ssc_t = "same_block"
            elif _lag_t <= 2:
                _ssc_t = "next_block"
            else:
                _ssc_t = "stale"
            return BackrunResult(
                event_id=event.event_id,
                event_source="live",
                event_type=event.event_type,
                post_trade_state_used="live",
                backrun_direction="skip",
                reject_reason=f"TRIANGULAR_CANDIDATE_DEFERRED:{_tri_count}",
                event_block=event.block_number,
                quote_block=current_block,
                block_lag=_lag_t,
                same_state_class=_ssc_t,
                event_detected_at_block=event_detected_at_block,
                actual_pair=f"{token_in_addr[:10]}/{token_out_addr[:10]}",
                scoring_path="triangular_pending",
                backrun_token_in_address=token_in_addr,
                backrun_token_out_address=token_out_addr,
                size_normalization_source=f"triangular_via:{_tri_first}",
            )
        return None

    active_entries = [e for e in entries if e.is_active()]
    if not active_entries:
        return None
    _registry_lookup_ms = round((time.monotonic() - _reg_start) * 1000, 2)

    # M7.A.5.36: per-stage hard abort
    if _registry_lookup_ms > HOT_BUDGET_REGISTRY_LOOKUP_MS:
        return None

    # ── Stage 2: Build candidate pools + state from cached entries ─────
    _state_start = time.monotonic()
    candidate_pools = []
    local_sim_states = {}
    for entry in active_entries:
        cp = entry.to_candidate_pool()
        candidate_pools.append(cp)
        ps = entry.to_pool_state()
        if ps:
            local_sim_states[entry.address] = ps

    if not local_sim_states:
        return None
    _pool_state_ms = round((time.monotonic() - _state_start) * 1000, 2)

    # M7.A.5.36: per-stage hard abort
    if _pool_state_ms > HOT_BUDGET_POOL_STATE_READ_MS:
        return None

    # Backrun size from event — decimal-aware bounded size
    # M7.A.5.41: Resolve actual symbol from addr_to_symbol for decimal detection
    _in_sym = _ats.get(token_in_addr.lower(), "").upper()
    # post-1h-soak P0 fix: expanded heuristic list mirrors scoring_parallel slow
    # path; CBBTC/TBTC/USDBC/PYUSD were missing causing 6/8-dec tokens to use
    # 18-dec bounds. Also try enrichment cache for completely unknown addresses.
    if _in_sym in ("USDC", "USDT", "USDC.E", "USDT.E", "USDBC", "PYUSD"):
        _effective_dec = 6
    elif _in_sym in ("WBTC", "CBBTC", "TBTC"):
        _effective_dec = 8
    elif _in_sym in ("WETH", "ETH", "DAI", "CBETH", "WSTETH", "RETH", "FRAX"):
        _effective_dec = 18
    else:
        # Try enrichment cache populated by cold lane; fall back to EVM default.
        _cached_dec_fast = get_cached_decimals(token_in_addr)
        _effective_dec = _cached_dec_fast if _cached_dec_fast is not None else 18
    low, high = _normalized_bounds(_effective_dec)
    # Dynamic min: ensure trade can cover gas at >= 1 bps net
    _dyn_min = get_min_profitable_size_wei(chain, _effective_dec)
    low = max(low, _dyn_min)
    backrun_size_wei = max(event.amount_in_wei // 10, 1)
    backrun_size_wei = max(low, min(high, backrun_size_wei))

    # E1.71: hot fast-path size escalation — when ARBY_HOT_FAST_ESCALATE_USD>0,
    # probe at production-grade notional from the start instead of event-derived
    # sub-$1 sizes.  Heuristic uses known stable/ETH token_in with optional
    # fallback table.  Falls back silently to original size if no USD basis.
    try:
        _esc_target_usd = float(os.getenv("ARBY_HOT_FAST_ESCALATE_USD", "0") or "0")
    except (TypeError, ValueError):
        _esc_target_usd = 0.0
    if _esc_target_usd > 0.0:
        _esc_price_usd: Optional[float] = None
        if _in_sym in _USD_STABLE_SYMBOLS:
            _esc_price_usd = 1.0
        elif _in_sym in _ETH_USD_SYMBOLS:
            try:
                from m7.shared.constants import _FALLBACK_ETH_PRICE_USD
                _esc_price_usd = float(_FALLBACK_ETH_PRICE_USD)
            except Exception:
                _esc_price_usd = None
        else:
            # Optional fallback table (E1.69 step 7)
            if os.getenv("ARBY_USD_BASIS_FALLBACK_ENABLE", "0") == "1":
                try:
                    from m7.orderflow.usd_basis_fallback import load_fallback_table
                    _esc_tbl = load_fallback_table()
                    _esc_price_usd = _esc_tbl.get(_in_sym)
                except Exception:
                    _esc_price_usd = None
        if _esc_price_usd and _esc_price_usd > 0:
            try:
                _esc_target_wei = int((_esc_target_usd / _esc_price_usd) * (10 ** _effective_dec))
                if _esc_target_wei > backrun_size_wei:
                    backrun_size_wei = max(low, min(high, _esc_target_wei))
            except (TypeError, ValueError, OverflowError):
                pass

    if backrun_size_wei <= 0:
        return None

    # ── Stage 3: Local pricing — the actual computation ────────────────
    _math_start = time.monotonic()
    pricing_result = attempt_local_pricing(
        candidate_pools=candidate_pools,
        local_sim_states=local_sim_states,
        token_in_addr=token_in_addr,
        token_out_addr=token_out_addr,
        backrun_size_wei=backrun_size_wei,
        registry_entries=active_entries,
    )
    _local_math_ms = round((time.monotonic() - _math_start) * 1000, 2)

    # M7.A.5.36: per-stage hard abort
    if _local_math_ms > HOT_BUDGET_LOCAL_MATH_MS:
        return None

    pipeline_ms = round((time.monotonic() - pipeline_start) * 1000, 2)

    # Hard abort if over budget
    if pipeline_ms > HOT_BUDGET_TOTAL_MS:
        return None

    if pricing_result is None:
        return None

    # E1.71: post-pricing size escalation (token_out anchor).
    # If we still don't have token_in price but token_out is WETH/stable, use
    # the buy_amount/in_amount ratio as a price quote: token_in_per_unit_out,
    # then derive wei target for ARBY_HOT_FAST_ESCALATE_USD and re-price.
    if _esc_target_usd > 0.0:
        try:
            _out_sym_esc = _ats.get(token_out_addr.lower(), "").upper()
            if not _out_sym_esc:
                _cs = get_cached_symbol(token_out_addr)
                if _cs:
                    _out_sym_esc = _cs.upper()
            _out_dec_esc = get_cached_decimals(token_out_addr)
            if _out_dec_esc is None:
                if _out_sym_esc in ("USDC", "USDT", "USDC.E", "USDT.E", "USDBC", "PYUSD"):
                    _out_dec_esc = 6
                elif _out_sym_esc in ("WBTC", "CBBTC", "TBTC"):
                    _out_dec_esc = 8
                else:
                    _out_dec_esc = 18
            _out_price_usd: Optional[float] = None
            if _out_sym_esc in _USD_STABLE_SYMBOLS:
                _out_price_usd = 1.0
            elif _out_sym_esc in _ETH_USD_SYMBOLS:
                try:
                    from m7.shared.constants import _FALLBACK_ETH_PRICE_USD
                    _out_price_usd = float(_FALLBACK_ETH_PRICE_USD)
                except Exception:
                    _out_price_usd = None
            elif os.getenv("ARBY_USD_BASIS_FALLBACK_ENABLE", "0") == "1":
                try:
                    from m7.orderflow.usd_basis_fallback import load_fallback_table
                    _out_price_usd = (load_fallback_table() or {}).get(_out_sym_esc)
                except Exception:
                    _out_price_usd = None
            _buy_amt_esc = pricing_result.get("buy_amount") if pricing_result else None
            if (_out_price_usd and _out_price_usd > 0
                    and _buy_amt_esc and int(_buy_amt_esc) > 0):
                # current size USD via token_out: amount_out / 10**dec_out * out_price
                _cur_usd = (int(_buy_amt_esc) / (10 ** _out_dec_esc)) * float(_out_price_usd)
                if _cur_usd and _cur_usd > 0 and _cur_usd < _esc_target_usd:
                    _scale = _esc_target_usd / _cur_usd
                    _new_wei = int(backrun_size_wei * _scale)
                    _new_wei = max(low, min(high, _new_wei))
                    if _new_wei > backrun_size_wei:
                        _re_pricing = attempt_local_pricing(
                            candidate_pools=candidate_pools,
                            local_sim_states=local_sim_states,
                            token_in_addr=token_in_addr,
                            token_out_addr=token_out_addr,
                            backrun_size_wei=_new_wei,
                            registry_entries=active_entries,
                        )
                        if _re_pricing is not None:
                            pricing_result = _re_pricing
                            backrun_size_wei = _new_wei
        except Exception:
            pass

    # E1.63 fast-path split routing: try 50/50 split across top-2 V3 pools.
    # Pure local math — zero-RPC, same pool states already loaded above.
    # Increments shared E1.63 session counters so the hot lane contributes to
    # the soak validation metric (split_route_attempted_total > 0).
    _split_route_enable_fast = os.getenv("ARBY_SPLIT_ROUTE_ENABLE", "0") == "1"
    if _split_route_enable_fast and local_sim_states:
        try:
            global _e163_split_route_attempted, _e163_split_route_win
            with _e163_lock:
                _e163_split_route_attempted += 1
            _sr_fast = attempt_split_pricing(
                candidate_pools=candidate_pools,
                local_sim_states=local_sim_states,
                token_in_addr=token_in_addr,
                token_out_addr=token_out_addr,
                backrun_size_wei=backrun_size_wei,
                registry_entries=active_entries if active_entries else None,
            )
            if _sr_fast is not None:
                _srb = _sr_fast.get("buy_amount")
                _srs = _sr_fast.get("sell_amount")
                if _srb and _srs and int(_srs) > 0:
                    # E1.67: buy_amount is token_out, sell_amount is token_in.
                    # Split-route wins must compare token_in roundtrip PnL:
                    # sell_amount - original amount_in.
                    _sr_gross_wei = _roundtrip_gross_wei(
                        int(backrun_size_wei), int(_srs)
                    )
                    _pr_sell = int(pricing_result.get("sell_amount") or 0)
                    _pr_gross_wei = (
                        _roundtrip_gross_wei(int(backrun_size_wei), _pr_sell)
                        if _pr_sell > 0 else -1
                    )
                    if _sr_gross_wei > _pr_gross_wei:
                        pricing_result = _sr_fast
                        with _e163_lock:
                            _e163_split_route_win += 1
        except Exception:
            pass  # split is best-effort; never fail the fast path

    buy_amount = pricing_result["buy_amount"]
    sell_amount = pricing_result["sell_amount"]

    # E1.64: depth guard in fast path — compute price_impact_bps from best buy
    # pool's local V3 state (zero-RPC, same pool states already loaded above).
    _price_impact_bps_fast: Optional[float] = None
    _depth_math_invalid_fast: bool = False
    _depth_guard_rejected_fast: bool = False
    if local_sim_states:
        try:
            import math as _math_mod
            _pi_venue = pricing_result.get("buy_venue")
            if _pi_venue:
                _pi_state = local_sim_states.get(_pi_venue)
                if _pi_state:
                    _pi_sp = int(_pi_state.get("sqrt_price_x96") or 0)
                    _pi_liq = int(_pi_state.get("liquidity") or 0)
                    _pi_fee = int(pricing_result.get("buy_fee") or 3000)
                    if _pi_sp > 0 and _pi_liq > 0:
                        global _e163_depth_guard_attempted
                        with _e163_lock:
                            _e163_depth_guard_attempted += 1
                        _zero_for_one = token_in_addr.lower() < token_out_addr.lower()
                        _pi_sp_after = compute_v3_sqrt_price_after(
                            sqrt_price_x96=_pi_sp,
                            liquidity=_pi_liq,
                            amount_in=int(backrun_size_wei),
                            fee_pips=_pi_fee,
                            zero_for_one=_zero_for_one,
                        )
                        if _pi_sp_after is not None:
                            _pi_ratio = (_pi_sp_after / _pi_sp) ** 2
                            _pi_bps_raw = abs(1.0 - _pi_ratio) * 10_000.0
                            if not _math_mod.isfinite(_pi_bps_raw) or _pi_bps_raw > 1_000_000:
                                _depth_math_invalid_fast = True
                                global _e164_depth_math_invalid
                                with _e163_lock:
                                    _e164_depth_math_invalid += 1
                            else:
                                _price_impact_bps_fast = round(_pi_bps_raw, 2)
                                global _e163_price_impact_populated
                                with _e163_lock:
                                    _e163_price_impact_populated += 1
                                _max_pi_fast = int(
                                    os.getenv("ARBY_PRICE_IMPACT_MAX_BPS", "1000")
                                )
                                if _price_impact_bps_fast > _max_pi_fast:
                                    _depth_guard_rejected_fast = True
                                    global _e164_depth_guard_rejected
                                    with _e163_lock:
                                        _e164_depth_guard_rejected += 1
        except Exception:
            pass  # depth guard is best-effort; never fail the fast path

    # ── N5: Accumulate dynamic_anchors sample (fast path) ──────────────
    # Fire-and-forget; mirrors the hook in score_backrun_live_parallel.
    try:
        from strategy.dynamic_anchors import record_m7_anchor_sample
        _out_sym_fast = _ats.get(token_out_addr.lower(), "").upper()
        # Fallback 1: reverse-lookup in token_addresses (symbol -> address map).
        if not _in_sym or not _out_sym_fast:
            _rev = {v.lower(): k.upper() for k, v in (token_addresses or {}).items() if v}
            if not _in_sym:
                _in_sym = _rev.get(token_in_addr.lower(), "")
            if not _out_sym_fast:
                _out_sym_fast = _rev.get(token_out_addr.lower(), "")
        # Fallback 2: enrichment cache populated by cold lane multicall.
        if not _in_sym:
            _cs = get_cached_symbol(token_in_addr)
            if _cs:
                _in_sym = _cs.upper()
        if not _out_sym_fast:
            _cs = get_cached_symbol(token_out_addr)
            if _cs:
                _out_sym_fast = _cs.upper()
        # Fallback 3: short hex tag for unknown tokens (still records the pair,
        # so we build an anchor key per-address).
        if not _in_sym:
            _in_sym = f"0x{token_in_addr.lower().replace('0x','')[:8]}"
        if not _out_sym_fast:
            _out_sym_fast = f"0x{token_out_addr.lower().replace('0x','')[:8]}"

        # Decimals_out: cached first, else heuristic from symbol, else EVM default.
        _out_dec_fast = get_cached_decimals(token_out_addr)
        if _out_dec_fast is None:
            if _out_sym_fast in ("USDC", "USDT", "USDC.E", "USDT.E", "USDBC"):
                _out_dec_fast = 6
            elif _out_sym_fast in ("WBTC", "CBBTC"):
                _out_dec_fast = 8
            else:
                _out_dec_fast = 18

        logger.info(
            "N5 hook(fast): chain=%s %s/%s in_wei=%d out_wei=%s dec_in=%s dec_out=%s",
            chain, _in_sym, _out_sym_fast, int(backrun_size_wei),
            buy_amount, _effective_dec, _out_dec_fast,
        )
        record_m7_anchor_sample(
            chain_key=chain,
            symbol_in=_in_sym,
            symbol_out=_out_sym_fast,
            amount_in_wei=int(backrun_size_wei),
            amount_out_wei=int(buy_amount) if buy_amount else 0,
            decimals_in=_effective_dec,
            decimals_out=_out_dec_fast,
            dex_id=str(pricing_result.get("buy_dex") or "unknown"),
            fee_tier=int(pricing_result.get("buy_fee") or 0),
            block=int(event.block_number or 0),
        )
    except Exception as _n5_exc:
        logger.warning("N5 hook(fast) exception: %s", _n5_exc)

    # Economics
    gross_wei = sell_amount - backrun_size_wei

    if backrun_size_wei > 0:
        gross_bps = (gross_wei / backrun_size_wei) * 10000
        # Unified gas estimation — chain-aware, consistent with profit_guard
        gas_bps, gas_cost_wei = estimate_gas_cost(
            chain, backrun_size_wei, l1_fee_bps=(l1_fee_bps or 0.0),
        )
        net_bps = gross_bps - gas_bps
        net_wei = gross_wei - gas_cost_wei
    else:
        return None

    # M7.A.5.34: PRICING_ANOMALY hard-exclude in fast path
    _PRICING_ANOMALY_BPS_FAST = 10000
    _reject_reason = None
    _route_viable = (net_bps > 0 and net_wei > 0)
    if abs(net_bps) > _PRICING_ANOMALY_BPS_FAST:
        _reject_reason = REJECT_PRICING_ANOMALY
        _route_viable = False

    # ── Stage 4: Profit guard (local sim) ──────────────────────────────
    _guard_start = time.monotonic()
    _profit_guard_passed = None
    _guard_reject_reason = None
    if _route_viable and net_bps > 0 and net_wei > 0:
        from m7.orderflow.profit_guard import check_profit_guard
        _guard = check_profit_guard(
            buy_amount_wei=backrun_size_wei,
            sell_amount_wei=sell_amount,
            backrun_size_wei=backrun_size_wei,
            pipeline_latency_ms=pipeline_ms,
            chain=chain,
            l1_fee_bps=(l1_fee_bps or 0.0),
            pre_computed_gas_bps=gas_bps,
            pre_computed_gas_cost_wei=gas_cost_wei,
        )
        _profit_guard_passed = _guard.passed
        _guard_reject_reason = _guard.reject_reason
    _profit_guard_ms = round((time.monotonic() - _guard_start) * 1000, 2)

    # M7.A.5.36: per-stage hard abort
    if _profit_guard_ms > HOT_BUDGET_PROFIT_GUARD_MS:
        return None

    # ── Stage 5: Execution-readiness timing (3 sub-stages) ────────────
    # M7.A.5.34: Split into tx_build / calldata / sign_or_bundle_prep
    _tx_build_start = time.monotonic()
    # Sub-stage 5a: Transaction build decision
    _tx_build_ms = round((time.monotonic() - _tx_build_start) * 1000, 2)

    _calldata_start = time.monotonic()
    # Sub-stage 5b: Calldata encoding (placeholder — future ABI encode)
    _calldata_ms = round((time.monotonic() - _calldata_start) * 1000, 2)

    _sign_start = time.monotonic()
    # Sub-stage 5c: Sign or bundle preparation (placeholder — future signing)
    _sign_or_bundle_prep_ms = round((time.monotonic() - _sign_start) * 1000, 2)

    pipeline_ms = round((time.monotonic() - pipeline_start) * 1000, 2)

    # Final budget check
    if pipeline_ms > HOT_BUDGET_TOTAL_MS:
        return None

    block_lag = current_block - event.block_number
    _stale_threshold = get_chain_stale_blocks(chain)
    if block_lag == 0:
        same_state_class = "same_block"
    elif block_lag <= _stale_threshold:
        same_state_class = "next_block"
    else:
        same_state_class = "stale"

    actual_pair = None
    tin_sym = _ats.get(token_in_addr.lower(), token_in_addr[:10] if token_in_addr else "??")
    tout_sym = _ats.get(token_out_addr.lower(), token_out_addr[:10] if token_out_addr else "??")
    actual_pair = f"{tin_sym}/{tout_sym}"

    # E1.64: USD basis — expand beyond stablecoin inputs to cover WETH and
    # dynamic-anchor fallback so expected_profit_usd is populated more often.
    _in_sym_upper_fast = tin_sym.upper()
    _out_sym_upper_fast = tout_sym.upper()
    _size_usd_fast: Optional[float] = None
    if _in_sym_upper_fast in _USD_STABLE_SYMBOLS:
        try:
            _size_usd_fast = round(backrun_size_wei / (10 ** _effective_dec) * 1.0, 2)
        except Exception:
            _size_usd_fast = None
    elif _in_sym_upper_fast in _ETH_USD_SYMBOLS:
        try:
            _eth_px_fast = _get_eth_price_usd(chain) if "_get_eth_price_usd" in dir() else None
            if not _eth_px_fast:
                # fallback to module-level constant
                from m7.shared.constants import _FALLBACK_ETH_PRICE_USD
                _eth_px_fast = _FALLBACK_ETH_PRICE_USD
            if _eth_px_fast and _eth_px_fast > 0:
                _size_usd_fast = round(backrun_size_wei / 1e18 * float(_eth_px_fast), 4)
        except Exception:
            _size_usd_fast = None
    else:
        # Best-effort: try token_out if it is a stable (receive-side basis).
        try:
            _out_dec_fast: Optional[int] = None
            if _out_sym_upper_fast in ("USDC", "USDT", "USDC.E", "USDT.E", "USDBC"):
                _out_dec_fast = 6
            elif _out_sym_upper_fast in ("DAI", "PYUSD", "FRAX"):
                _out_dec_fast = 18
            if _out_dec_fast is not None and buy_amount and buy_amount > 0:
                _size_usd_fast = round(buy_amount / (10 ** _out_dec_fast), 4)
            elif _out_sym_upper_fast in _ETH_USD_SYMBOLS and buy_amount and buy_amount > 0:
                # E1.71: token_out=WETH branch — use ETH price for USD basis.
                from m7.shared.constants import _FALLBACK_ETH_PRICE_USD
                _eth_px_o = float(_FALLBACK_ETH_PRICE_USD)
                if _eth_px_o > 0:
                    _size_usd_fast = round(buy_amount / 1e18 * _eth_px_o, 4)
            elif os.getenv("ARBY_USD_BASIS_FALLBACK_ENABLE", "0") == "1" and buy_amount and buy_amount > 0:
                # Fallback table on token_out as last resort
                from m7.orderflow.usd_basis_fallback import load_fallback_table
                _tbl_o = load_fallback_table() or {}
                _px_o = _tbl_o.get(_out_sym_upper_fast)
                _od = get_cached_decimals(token_out_addr) or 18
                if _px_o and _px_o > 0:
                    _size_usd_fast = round(buy_amount / (10 ** _od) * float(_px_o), 4)
        except Exception:
            _size_usd_fast = None

    # E1.64: compute expected_profit_usd from size_usd * net_bps.
    _expected_profit_usd_fast: Optional[float] = None
    if _size_usd_fast and _size_usd_fast > 0 and net_bps > 0:
        _expected_profit_usd_fast = round(_size_usd_fast * net_bps / 10_000.0, 6)

    # E1.64: USD_BASIS_MISSING gate — only active when net_bps > 0.
    # Counts opportunities we *cannot* rank in USD terms.
    if _route_viable and net_bps > 0 and _expected_profit_usd_fast is None:
        global _e164_usd_basis_missing
        with _e163_lock:
            _e164_usd_basis_missing += 1

    # E1.64: ARBY_MIN_EXPECTED_PROFIT_USD gate.
    _min_profit_usd_gate = float(os.getenv("ARBY_MIN_EXPECTED_PROFIT_USD", "0.0") or "0.0")
    if _min_profit_usd_gate > 0.0 and _route_viable:
        if _expected_profit_usd_fast is None:
            # USD basis unavailable — treat as not meeting the gate.
            _route_viable = False
            _reject_reason = _reject_reason or REJECT_USD_BASIS_MISSING
            global _e164_min_profit_rejected
            with _e163_lock:
                _e164_min_profit_rejected += 1
        elif _expected_profit_usd_fast < _min_profit_usd_gate:
            _route_viable = False
            _reject_reason = _reject_reason or REJECT_MIN_PROFIT_USD_NOT_MET
            with _e163_lock:
                _e164_min_profit_rejected += 1

    return BackrunResult(
        event_id=event.event_id,
        event_source="live",
        event_type=event.event_type,
        post_trade_state_used="live",
        backrun_direction=backrun_dir,
        best_buy_venue=pricing_result.get("buy_dex", pricing_result.get("buy_venue")),
        best_sell_venue=pricing_result.get("sell_dex", pricing_result.get("sell_venue")),
        best_buy_fee=pricing_result.get("buy_fee", 0),
        best_sell_fee=pricing_result.get("sell_fee", 0),
        amount_in_wei=backrun_size_wei,
        gross_pnl_wei=gross_wei,
        gas_cost_wei=gas_cost_wei,
        net_pnl_wei=net_wei,
        best_backrun_net_bps=round(net_bps, 4),
        route_viable=_route_viable,
        reject_reason=_reject_reason if _reject_reason else (None if _route_viable else REJECT_GAS_EXCEEDS_GROSS),
        event_block=event.block_number,
        quote_block=current_block,
        block_lag=block_lag,
        same_state_class=same_state_class,
        event_detected_at_block=event_detected_at_block,
        quote_started_block=current_block,
        quote_finished_block=current_block,
        quote_pipeline_latency_ms=pipeline_ms,
        latency_budget_ms=block_time_ms,
        pipeline_stage_latency_ms={
            "registry_lookup_ms": _registry_lookup_ms,
            "pool_state_ms": _pool_state_ms,
            "local_math_ms": _local_math_ms,
            "profit_guard_ms": _profit_guard_ms,
            "tx_build_ms": _tx_build_ms,
            "calldata_ms": _calldata_ms,
            "sign_or_bundle_prep_ms": _sign_or_bundle_prep_ms,
        },
        pair_resolved=True,
        actual_pair=actual_pair,
        backrun_token_in_address=token_in_addr,
        backrun_token_out_address=token_out_addr,
        size_source="dynamic_bounded",
        size_valid_for_token=True,
        token_in_decimals=_effective_dec,
        size_normalization_source=("heuristic" if _in_sym else "default_18_inferred"),
        size_usd_estimate=_size_usd_fast,
        local_pricing_attempted=True,
        local_pricing_used=True,
        registry_pools_found=len(entries),
        registry_pools_active=len(active_entries),
        gas_floor_exceeded=(net_bps <= 0),
        gas_floor_bps=gas_bps,
        scoring_path="registry_fast",
        profit_guard_passed=_profit_guard_passed,
        # E1.64: new observability fields
        expected_profit_usd=_expected_profit_usd_fast,
        price_impact_bps=_price_impact_bps_fast,
        amount_in_optimal_usd=_size_usd_fast,
    )

