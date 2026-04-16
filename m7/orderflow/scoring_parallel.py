"""
M7 orderflow parallel scoring pipeline (score_backrun_live_parallel).

This is the main 3-stage pipeline: pair resolve + coverage scan + quote.
Extracted from the monolith due to size (~787 lines).
"""
from __future__ import annotations

import logging
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
    _pool_token_cache,
)
from m7.orderflow.coverage import (
    admit_event_tokens,
    counter_venue_coverage_scan,
)
from m7.orderflow.pricing import check_oracle_sanity
from m7.orderflow.v3_math import attempt_local_pricing

from m7.shared.constants import (
    HOT_BUDGET_TOTAL_MS,
    HOT_BUDGET_REGISTRY_LOOKUP_MS,
    HOT_BUDGET_POOL_STATE_READ_MS,
    HOT_BUDGET_LOCAL_MATH_MS,
    HOT_BUDGET_PROFIT_GUARD_MS,
)

logger = logging.getLogger("m7.orderflow.scoring_parallel")

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
        oracle_result = check_oracle_sanity(in_sym, out_sym, rpc_url, current_block)
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
        # Well-known stablecoin heuristic (symbol-based)
        _in_sym = _ats.get(token_in_addr.lower(), "")
        if _in_sym.upper() in ("USDC", "USDT", "USDC.e", "USDT.e"):
            _token_in_dec = 6
        elif _in_sym.upper() in ("WBTC",):
            _token_in_dec = 8
    _norm_source = "decimal_only" if _token_in_dec is not None else "fallback_18"
    _effective_dec = _token_in_dec if _token_in_dec is not None else 18
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

    if _local_result is not None:
        # Local pricing produced a result — use it, skip remote quoter
        local_pricing_used = True
        best_buy_amount = _local_result["buy_amount"]
        best_sell_amount = _local_result["sell_amount"]
        best_buy_venue = _local_result.get("buy_dex", _local_result["buy_venue"])
        best_sell_venue = _local_result.get("sell_dex", _local_result["sell_venue"])
        venues_quoted = _local_result["pools_succeeded"]
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
            _eth_orc = check_oracle_sanity("WETH", None, rpc_url, current_block)
            _eth_price_usd = _eth_orc.get("token_in_oracle_usd")
        except Exception:
            pass
    gas_cost_wei = _gas_cost_in_token_wei(
        _gas_eth_wei, _effective_dec,
        token_price_usd=_tok_price_usd,
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
        sweep_results = None
        best_sweep_net = None
        best_sweep_size = None
        if _scoring_path != "registry_direct":
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

        return BackrunResult(
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
        )

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
    if _in_sym in ("USDC", "USDT", "USDC.E", "USDT.E"):
        _effective_dec = 6
    elif _in_sym in ("WBTC",):
        _effective_dec = 8
    else:
        _effective_dec = 18
    low, high = _normalized_bounds(_effective_dec)
    # Dynamic min: ensure trade can cover gas at >= 1 bps net
    _dyn_min = get_min_profitable_size_wei(chain, _effective_dec)
    low = max(low, _dyn_min)
    backrun_size_wei = max(event.amount_in_wei // 10, 1)
    backrun_size_wei = max(low, min(high, backrun_size_wei))

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

    buy_amount = pricing_result["buy_amount"]
    sell_amount = pricing_result["sell_amount"]

    # ── N5: Accumulate dynamic_anchors sample (fast path) ──────────────
    # Fire-and-forget; mirrors the hook in score_backrun_live_parallel.
    try:
        from strategy.dynamic_anchors import record_m7_anchor_sample
        _out_sym_fast = _ats.get(token_out_addr.lower(), "").upper()
        # Fallback: reverse-lookup in token_addresses (symbol -> address map).
        if not _in_sym or not _out_sym_fast:
            _rev = {v.lower(): k.upper() for k, v in (token_addresses or {}).items() if v}
            if not _in_sym:
                _in_sym = _rev.get(token_in_addr.lower(), "")
            if not _out_sym_fast:
                _out_sym_fast = _rev.get(token_out_addr.lower(), "")
        _out_dec_fast = get_cached_decimals(token_out_addr)
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
    if block_lag == 0:
        same_state_class = "same_block"
    elif block_lag <= 2:
        same_state_class = "next_block"
    else:
        same_state_class = "stale"

    actual_pair = None
    tin_sym = _ats.get(token_in_addr.lower(), token_in_addr[:10] if token_in_addr else "??")
    tout_sym = _ats.get(token_out_addr.lower(), token_out_addr[:10] if token_out_addr else "??")
    actual_pair = f"{tin_sym}/{tout_sym}"

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
        local_pricing_attempted=True,
        local_pricing_used=True,
        registry_pools_found=len(entries),
        registry_pools_active=len(active_entries),
        gas_floor_exceeded=(net_bps <= 0),
        gas_floor_bps=gas_bps,
        scoring_path="registry_fast",
        profit_guard_passed=_profit_guard_passed,
    )
    if _guard_reject_reason is not None:
        setattr(result, "guard_reject_reason", _guard_reject_reason)
    return result

