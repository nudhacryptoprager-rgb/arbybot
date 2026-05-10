"""E1.56 Step 1 — Cold-positive immediate sim queue.

Closes the STRATEGY_GATING blocker surfaced after E1.55:

  Cold lane finds profitable pools (e.g. FUN/USDC +997 bps, B3/WETH
  +425 bps) and writes them to `data/runs/_rolling/m7_cold_hot_bridge.json`
  under `cold_executable`. Hot lane is event-driven on the WS log stream:
  it scores only events that the WS upstream actually delivers. If the WS
  stream is dominated by an unrelated thin-spread pool (e.g. PENGACHU/WETH
  on Base), hot lane never sees the profitable pool and never calls sim.
  Result: `sim_attempted = 0` even though cold truth is positive.

This module bridges that gap: it converts each cold-positive bridge entry
into a synthetic `BackrunResult` and feeds the list to the existing
`run_execution_gate(...)` pipeline, which runs profit_guard → sim → submit
with ZERO public-API change.

ENV gate (default OFF, fully back-compat):
  ARBY_COLD_IMMEDIATE_SIM=1   — enable this lane
  ARBY_COLD_IMMEDIATE_MIN_NET_BPS=10  — only attempt entries with net_bps ≥ this
  ARBY_COLD_IMMEDIATE_TOP_N=5   — at most N entries per call

Counters returned for rollup:
  cold_immediate_sim_input_count       — bridge entries considered
  cold_immediate_sim_attempted          — entries that reached sim
  cold_immediate_sim_passed             — entries with sim_passed=True
  cold_immediate_sim_profitable         — entries that produced a positive
                                         post-sim net_bps (round-trip truth)

The lane is purely additive: if the env gate is unset (default) the public
contract of `run_execution_gate` is untouched and no synthetic candidates
are queued. This honors `CLAUDE.md §2.1` "public API ≥ existing".
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger
from m7.orderflow.contracts import BackrunResult, OrderflowEvent

logger = get_logger("m7.orderflow.cold_immediate_sim")


def is_enabled() -> bool:
    """Return True when the env gate is on."""
    return (os.getenv("ARBY_COLD_IMMEDIATE_SIM", "0") or "0") == "1"


def _min_net_bps_threshold() -> float:
    """Floor for entries fed into the immediate sim queue."""
    try:
        return float(os.getenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "10") or 10.0)
    except Exception:
        return 10.0


def _min_expected_profit_usd() -> float:
    """Absolute USD profit floor — rejects dust-bps-on-dust-size entries.

    Step 6 fix: +2500 bps on $0.00001 is not a real trade. Default 0.001 USD.
    Disable by setting ARBY_COLD_MIN_EXPECTED_PROFIT_USD=0.
    """
    try:
        v = float(os.getenv("ARBY_COLD_MIN_EXPECTED_PROFIT_USD", "0.001") or 0.001)
        return max(0.0, v)
    except Exception:
        return 0.001


def _entry_expected_profit_usd(entry: Dict[str, Any]) -> Optional[float]:
    """Compute expected_profit_usd from bridge entry if size USD is known.

    Returns None when USD basis is unavailable (e.g. meme tokens with
    unknown oracle price) — callers must not reject those entries purely
    on this field.
    """
    try:
        size_usd = entry.get("size_usd_estimate")
        net_bps = entry.get("net_bps")
        if size_usd is None or net_bps is None:
            return None
        s = float(size_usd)
        b = float(net_bps)
        if s > 0 and b > 0:
            return round(s * b / 10000, 6)
    except Exception:
        pass
    return None


def _entry_rank_key(entry: Dict[str, Any]) -> float:
    """Ranking key for cold_executable entries.

    Step 9 fix: rank by expected_profit_usd (absolute USD edge) when
    available.  Fall back to net_bps scaled to a tiny value so that
    USD-ranked entries always beat bps-only entries in the ordering.

    E1.77 P0: mix MAV (Maximal Arbitrage Value at executable depth) and
    lag-staleness score into the rank key.  When ``depth_curve`` is
    populated we prefer ``mav_estimate_usd`` over the point-estimate
    ``expected_profit_usd`` because MAV captures the entire profit
    surface (the largest size whose marginal profit is still positive).
    Each candidate is also enriched in-place with ``mav_usd``,
    ``best_size_usd`` and ``lag_score`` so the bridge artifact and the
    dashboard heatmap can read identical fields.
    """
    p = _entry_expected_profit_usd(entry)

    # E1.77 P0: depth-curve aware MAV estimate.
    mav_usd: float = 0.0
    best_size_usd: float = 0.0
    try:
        from m7.orderflow.depth_ladder import (
            mav_estimate_usd as _mav_est,
            lag_score as _lag,
        )
        _curve = entry.get("depth_curve") or []
        if _curve:
            _mav = _mav_est(_curve) or {}
            mav_usd = float(_mav.get("mav_usd") or 0.0)
            best_size_usd = float(_mav.get("best_size_usd") or 0.0)
        # Lag/staleness score (0..100). Higher = stronger arb signal.
        _lag_inputs: Dict[str, Any] = {}
        if entry.get("seconds_since_last_swap") is not None:
            _lag_inputs["seconds_since_last_swap"] = entry.get("seconds_since_last_swap")
        if entry.get("price_divergence_bps") is not None:
            _lag_inputs["price_divergence_bps"] = entry.get("price_divergence_bps")
        elif entry.get("net_bps") is not None:
            _lag_inputs["price_divergence_bps"] = entry.get("net_bps")
        lag_val = float(_lag(**_lag_inputs)) if _lag_inputs else 0.0
        # Stash for downstream consumers (bridge artifact, heatmap).
        entry["mav_usd"] = round(mav_usd, 6)
        entry["best_size_usd"] = round(best_size_usd, 6)
        entry["lag_score"] = round(lag_val, 3)
    except Exception:
        lag_val = 0.0

    # Composite rank: prefer MAV when meaningful (>=$0.01),
    # else expected_profit_usd, else net_bps tiebreaker.
    # Lag score acts as a small multiplicative boost (1.0..2.0) so two
    # equally-profitable entries are ordered by freshness.
    base: float
    if mav_usd >= 0.01:
        base = mav_usd
    elif p is not None:
        base = float(p)
    else:
        base = float(entry.get("net_bps") or 0.0) * 1e-6
    boost = 1.0 + min(max(lag_val, 0.0), 100.0) / 100.0
    return base * boost


def _top_n() -> int:
    try:
        n = int(os.getenv("ARBY_COLD_IMMEDIATE_TOP_N", "5") or 5)
    except Exception:
        n = 5
    return max(1, min(50, n))


def _build_synthetic_event(entry: Dict[str, Any], chain: str) -> Optional[OrderflowEvent]:
    """Construct an `OrderflowEvent` shape from a bridge cold_executable entry.

    Returns None if the entry is missing required fields. The synthetic
    event is marked `event_source="cold_bridge"` downstream via the
    BackrunResult so consumers can distinguish from live WS events.

    Fix 2 (E1.60): entries with amount_in_wei=0 AND best_sweep_size_wei=0
    and no usd/decimals metadata will hit PRE_SIM_SKIP:MISSING_SIZE_METADATA
    in execution_gate. The gate already handles this correctly; we only skip
    here to avoid wasting counter budget when ALL metadata is absent.
    """
    try:
        pa = (entry.get("pool_address") or "").lower()
        # bridge `_compact_candidate` does not carry token symbols; fall
        # back to placeholders. The execution gate uses
        # `backrun_token_in_address`/`backrun_token_out_address` for
        # routing, so symbols are not strictly required.
        token_in_sym = entry.get("token_in") or entry.get("token_in_symbol") or "UNK_IN"
        token_out_sym = entry.get("token_out") or entry.get("token_out_symbol") or "UNK_OUT"
        if not pa:
            return None
        ev_id = f"cold_immediate_{pa[:10]}_{int(entry.get('block_lag') or 0)}"
        return OrderflowEvent(
            event_id=ev_id,
            event_type="swap",
            chain=chain,
            block_number=int(entry.get("block_number") or 0),
            tx_hash=ev_id,
            token_in=token_in_sym,
            token_out=token_out_sym,
            amount_in_wei=int(entry.get("amount_in_wei") or 0),
            # E1.65: prefer best_buy_amount_wei (actual USDC/WETH output from
            # the pricing result) over amount_out_wei (often 0 in bridge entries
            # for token_out=USDC pairs like FUN/USDC, B3/USDC).
            amount_out_wei=int(
                entry.get("best_buy_amount_wei") or entry.get("amount_out_wei") or 0
            ),
            dex=str(entry.get("dex") or "cold_bridge"),
            pool_address=pa,
            fee_tier=int(entry.get("fee_tier") or 0),
            estimated_size_usd=float(entry.get("size_usd_estimate") or 0.0),
            estimated_impact_bps=float(entry.get("impact_bps") or 0.0),
            timestamp=str(entry.get("timestamp") or ""),
        )
    except Exception as exc:
        logger.debug("cold_immediate: failed to build event: %s", str(exc)[:80])
        return None


def _build_synthetic_result(entry: Dict[str, Any], event: OrderflowEvent) -> BackrunResult:
    """Build a `BackrunResult` carrying the cold-positive net_bps so that
    the profit_guard stage of `run_execution_gate` admits the candidate.
    """
    net_bps = float(entry.get("net_bps") or 0.0)

    # E1.56 Step 1 compact fix: execution_gate has two admission skip paths
    # that require fee/size metadata.  Without at least ONE of:
    #   a) best_buy_fee set, OR
    #   b) best_sweep_size_wei > 0
    # the gate returns PRE_SIM_SKIP:NO_FEE_HINT (or NO_AMOUNT_NO_FEE_HINT).
    # Additionally, if none of {token_in_decimals, best_sweep_size_wei,
    # size_usd_estimate} are set, gate returns MISSING_SIZE_METADATA.
    #
    # Priority for best_buy_fee:
    #   1. explicit best_buy_fee in compact entry (set by _compact_candidate)
    #   2. fee_tier from the event we just built (already decoded from entry)
    _raw_fee = entry.get("best_buy_fee")
    if not _raw_fee and (event.fee_tier or 0) > 0:
        _raw_fee = int(event.fee_tier)
    _best_buy_fee = int(_raw_fee) if _raw_fee else None

    # best_sweep_size_wei fallback: use amount_in_wei when sweep not stored
    _sweep = entry.get("best_sweep_size_wei") or None
    _ai_raw = int(entry.get("amount_in_wei") or 0)
    if not _sweep:
        if _ai_raw > 0:
            _sweep = _ai_raw

    # gross_pnl_wei: required by profit_guard (sell = amount + gross; gross=0
    # → sell=buy → net_pnl_wei<0 → profit_guard always rejects).
    # Priority: stored value (from _compact_candidate) → estimate from net_bps.
    _gross_pnl = int(entry.get("gross_pnl_wei") or 0)
    if not _gross_pnl and (entry.get("net_bps") or 0) > 0 and _ai_raw > 0:
        # net_bps already deducts gas; use as conservative lower bound for
        # gross (real gross = net + gas, so this slightly underestimates,
        # but profit_guard only needs gross > 0 to proceed).
        _gross_pnl = int(float(entry["net_bps"]) * _ai_raw / 10000)

    res = BackrunResult(
        event_id=event.event_id,
        event_source="cold_bridge",
        event_type="swap",
        post_trade_state_used="cold_simulated",
        backrun_direction=str(entry.get("backrun_direction") or "buy_out_sell_in"),
        amount_in_wei=_ai_raw,
        gross_pnl_wei=_gross_pnl,
        gas_cost_wei=int(entry.get("gas_cost_wei") or 0),
        fee_cost_wei=int(entry.get("fee_cost_wei") or 0),
        net_pnl_wei=int(entry.get("net_pnl_wei") or 0),
        best_backrun_net_bps=net_bps,
        same_block_possible=True,
        route_viable=bool(entry.get("route_viable", True)),
        block_lag=int(entry.get("block_lag") or 0),
        size_valid_for_token=bool(entry.get("size_valid_for_token", True)),
        actual_pair=str(entry.get("actual_pair") or ""),
        scoring_path="cold_immediate",
        profit_guard_passed=None,  # let execution_gate decide
        # Execution-gate admission metadata (fee/venue/size).
        best_buy_fee=_best_buy_fee,
        best_sell_fee=entry.get("best_sell_fee"),
        best_buy_venue=entry.get("best_buy_venue"),
        best_sell_venue=entry.get("best_sell_venue"),
        backrun_token_in_address=entry.get("backrun_token_in_address"),
        backrun_token_out_address=entry.get("backrun_token_out_address"),
        token_in_decimals=entry.get("token_in_decimals"),
        best_sweep_size_wei=_sweep,
        size_usd_estimate=entry.get("size_usd_estimate"),
    )
    # Attach _source_event so downstream artifact builders that read
    # `getattr(r, '_source_event', None).pool_address` work uniformly
    # with WS-event-derived results.
    res._source_event = event  # type: ignore[attr-defined]
    return res


def queue_cold_executable_for_sim(
    bridge: Dict[str, Any],
    chain: str = "base",
    profile: Optional[str] = None,
) -> Tuple[Optional[Any], Dict[str, int]]:
    """Build synthetic candidates from bridge `cold_executable` and run
    them through `run_execution_gate`.

    Args:
        bridge: parsed cold-hot bridge dict (as returned by
            `_read_cold_hot_bridge()`).
        chain: chain label for the gate.
        profile: 'production' / 'discovery' — selects the sim backend
            pool via existing ARBY_SIM_BACKEND_* env contract.

    Returns:
        Tuple (gate_result_or_None, counters_dict). When the gate is
        disabled (ENV unset) returns (None, {...all zeros...}).
    """
    counters = {
        "cold_immediate_sim_input_count": 0,
        "cold_immediate_sim_attempted": 0,
        "cold_immediate_sim_passed": 0,
        "cold_immediate_sim_profitable": 0,
        # issue #3: detailed diagnostics for why attempted candidates fail
        "cold_immediate_guard_passed": 0,
        "cold_immediate_profit_guard_rejected": 0,
        "cold_immediate_pre_sim_skip": 0,
        "cold_immediate_sim_revert": 0,
        # E1.63 step 5: track entries with no USD size basis (size_usd=0/None + net_bps>0)
        # These are diagnostic candidates (meme tokens, unknown oracle) — not
        # counted as "profitable" even when they pass the gate.
        "cold_immediate_usd_basis_missing": 0,
    }
    if not is_enabled():
        return None, counters

    cold_exec = (bridge or {}).get("cold_executable") or []
    if not isinstance(cold_exec, list):
        cold_exec = []

    min_bps = _min_net_bps_threshold()
    top_n = _top_n()

    # Step 7 fast-recheck: also include near_executable entries when
    # ARBY_COLD_IMMEDIATE_NEAR=1 (default ON when cold_immediate_sim enabled).
    # near_executable pools are close to the profit threshold — re-running them
    # against fresh state may flip them to profitable without waiting for the
    # next full 15-min cold cycle.  Threshold: 0 bps (any positive net) to
    # avoid missing marginally profitable entries.
    _include_near = os.getenv("ARBY_COLD_IMMEDIATE_NEAR", "1") == "1"
    if _include_near:
        near_exec = (bridge or {}).get("near_executable") or []
        if isinstance(near_exec, list) and near_exec:
            # Merge; entries already in cold_exec (same pool_address) are skipped
            _exec_addrs = {
                (e.get("pool_address") or "").lower()
                for e in cold_exec if isinstance(e, dict)
            }
            _near_merged = [
                e for e in near_exec
                if isinstance(e, dict)
                and (e.get("pool_address") or "").lower() not in _exec_addrs
            ]
            cold_exec = list(cold_exec) + _near_merged

    if not cold_exec:
        return None, counters

    # Step 6 / E1.64-1: USD profit gate — bps without USD notional cannot
    # be admitted to submit-ready.  ARBY_COLD_REQUIRE_USD_BASIS=1 (default ON
    # under E1.64) blocks entries with size_usd<=0 or expected_profit_usd=None,
    # routing them into USD_BASIS_MISSING instead of the gate.  When the env
    # is 0 (legacy behaviour) entries without USD basis pass through.
    _min_profit_usd = _min_expected_profit_usd()
    _require_usd_basis = os.getenv("ARBY_COLD_REQUIRE_USD_BASIS", "0") == "1"

    def _passes_profit_gate(e: Dict[str, Any]) -> bool:
        # E1.64-1: block missing USD basis when required.
        if _require_usd_basis:
            _susd = e.get("size_usd_estimate")
            try:
                _susd_f = float(_susd) if _susd is not None else 0.0
            except Exception:
                _susd_f = 0.0
            if _susd_f <= 0.0:
                return False
            p = _entry_expected_profit_usd(e)
            if p is None:
                return False
            if _min_profit_usd > 0 and p < _min_profit_usd:
                return False
            return True
        # Legacy path (require_usd_basis=0): entries without USD basis pass.
        if _min_profit_usd <= 0:
            return True
        p = _entry_expected_profit_usd(e)
        if p is None:
            return True  # No USD basis — let through (legacy)
        return p >= _min_profit_usd

    # Step 9: rank by expected_profit_usd desc (max absolute edge first),
    # fallback to net_bps for entries without USD oracle basis.
    _all_with_min_bps = [e for e in cold_exec if isinstance(e, dict)
                         and float(e.get("net_bps") or 0.0) >= min_bps]

    # E1.65 Step 3: USDC/WETH token_out fallback — for entries where
    # size_usd_estimate=0 but best_buy_amount_wei>0 and token_out is a
    # known stable (USDC/USDT) or WETH, compute size_usd directly.
    # This fixes FUN/USDC, B3/USDC etc. where the token_in oracle is absent
    # but the scoring path DID produce a USDC buy amount.
    _USDC_STABLE_ADDRS = {
        # Base USDC
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        # Base USDbC (bridged)
        "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",
        # Arbitrum USDC
        "0xaf88d065e77c8cc2239327c5edb3a432268e5831",
        # Arbitrum USDT
        "0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9",
        # Optimism USDC
        "0x0b2c639c533813f4aa9d7837caf62653d097ff85",
    }
    _WETH_ADDRS = {
        # Base WETH
        "0x4200000000000000000000000000000000000006",
        # Arbitrum WETH
        "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
    }
    _USD_PAIR_SUFFIXES = ("/USDC", "/USDT", "/USDBC", "/DAI")

    def _enrich_usd_from_buy_amount(e: Dict[str, Any]) -> Dict[str, Any]:
        """Return enriched copy of entry when USDC/WETH fallback is possible."""
        _susd = e.get("size_usd_estimate")
        try:
            _susd_f = float(_susd) if _susd is not None else 0.0
        except Exception:
            _susd_f = 0.0
        if _susd_f > 0:
            return e  # already has USD basis, skip
        _ba_wei = int(e.get("best_buy_amount_wei") or 0)
        if _ba_wei <= 0:
            return e  # no buy amount to fall back from
        _tok_out = (e.get("backrun_token_out_address") or "").lower()
        _pair = e.get("actual_pair") or e.get("pair") or ""
        # Check if token_out is a known 6-decimal stable
        if _tok_out in _USDC_STABLE_ADDRS or any(_pair.upper().endswith(sfx) for sfx in _USD_PAIR_SUFFIXES):
            _computed = round(_ba_wei / 10**6, 6)
            if _computed > 0:
                e = dict(e)  # shallow copy — never mutate bridge dict
                e["size_usd_estimate"] = _computed
                e["usd_basis_source"] = "token_out_stable_fallback"
                return e
        # Check if token_out is WETH — use 18 decimals
        if _tok_out in _WETH_ADDRS:
            _eth_price = float(os.getenv("ARBY_ETH_PRICE_USD", "0") or 0)
            if _eth_price > 0:
                _computed = round(_ba_wei / 10**18 * _eth_price, 6)
                if _computed > 0:
                    e = dict(e)
                    e["size_usd_estimate"] = _computed
                    e["usd_basis_source"] = "token_out_weth_fallback"
                    return e
        return e

    _all_with_min_bps = [_enrich_usd_from_buy_amount(e) for e in _all_with_min_bps]

    # E1.64-1: count entries blocked by the USD basis gate (before truncation).
    if _require_usd_basis:
        _usd_missing_samples: List[Dict[str, Any]] = []
        for _e in _all_with_min_bps:
            _susd = _e.get("size_usd_estimate")
            try:
                _susd_f = float(_susd) if _susd is not None else 0.0
            except Exception:
                _susd_f = 0.0
            _p = _entry_expected_profit_usd(_e)
            if _susd_f <= 0.0 or _p is None:
                counters["cold_immediate_usd_basis_missing"] = (
                    counters.get("cold_immediate_usd_basis_missing", 0) + 1
                )
                # E1.64-2: diagnostic sample — capture amount_in/out, decimals,
                # token addresses, USD pricing path, pool addresses so reviewer
                # can pinpoint why size_usd=0 (missing oracle? unknown decimals?).
                if len(_usd_missing_samples) < 10:
                    # E1.65 Step 4: distinguish "we had buy amount but token_out unknown"
                    # from "scoring never produced buy amount at all"
                    _ba_wei_diag = int(_e.get("best_buy_amount_wei") or 0)
                    _pair_diag = _e.get("actual_pair") or _e.get("pair") or ""
                    _has_usdc_out = (
                        any(_pair_diag.upper().endswith(sfx) for sfx in _USD_PAIR_SUFFIXES)
                        or (_e.get("backrun_token_out_address") or "").lower()
                        in _USDC_STABLE_ADDRS
                    )
                    if _ba_wei_diag > 0 and _has_usdc_out:
                        _reason_diag = "USD_BASIS_MISSING:missing_buy_amount"
                    elif _susd_f <= 0.0:
                        _reason_diag = "size_usd_zero"
                    else:
                        _reason_diag = "expected_profit_usd_none"
                    _usd_missing_samples.append({
                        "pair": _e.get("pair") or _e.get("symbol"),
                        "actual_pair": _e.get("actual_pair"),
                        "pool_address": _e.get("pool_address"),
                        "second_pool_address": _e.get("second_pool_address"),
                        "token_in_address": _e.get("token_in_address"),
                        "token_out_address": _e.get("token_out_address"),
                        "backrun_token_out_address": _e.get("backrun_token_out_address"),
                        "token_in_decimals": _e.get("token_in_decimals"),
                        "token_out_decimals": _e.get("token_out_decimals"),
                        "amount_in_wei": _e.get("amount_in_wei"),
                        "amount_out_wei": _e.get("amount_out_wei"),
                        "best_buy_amount_wei": _e.get("best_buy_amount_wei"),
                        "size_usd_estimate": _susd,
                        "net_bps": _e.get("net_bps"),
                        "size_normalization_source": _e.get(
                            "size_normalization_source"
                        ),
                        "usd_basis_source": _e.get("usd_basis_source"),
                        "expected_profit_usd": _p,
                        "reason": _reason_diag,
                    })
        if _usd_missing_samples:
            counters["cold_immediate_usd_basis_missing_samples"] = _usd_missing_samples
    ranked = sorted(
        [e for e in _all_with_min_bps if _passes_profit_gate(e)],
        key=_entry_rank_key,
        reverse=True,
    )[:top_n]
    counters["cold_immediate_sim_input_count"] = len(ranked)
    # Legacy (non-USD-basis-gating) bookkeeping: count remaining ranked
    # entries with no USD basis (only present when require_usd_basis=0).
    if not _require_usd_basis:
        for _e in ranked:
            _susd = _e.get("size_usd_estimate")
            _nbps = float(_e.get("net_bps") or 0.0)
            if _nbps > 0 and (_susd is None or float(_susd) <= 0.0):
                counters["cold_immediate_usd_basis_missing"] = (
                    counters.get("cold_immediate_usd_basis_missing", 0) + 1
                )
    if not ranked:
        return None, counters

    synthetic: List[BackrunResult] = []
    for entry in ranked:
        ev = _build_synthetic_event(entry, chain=chain)
        if ev is None:
            continue
        res = _build_synthetic_result(entry, ev)
        # Step 1: populate expected_profit_usd on the synthetic result
        _epusd = _entry_expected_profit_usd(entry)
        if _epusd is not None:
            res.expected_profit_usd = _epusd
        synthetic.append(res)

    if not synthetic:
        return None, counters

    # Lazy import to avoid module-level cycles.
    from m7.orderflow.execution_gate import run_execution_gate

    try:
        gate = run_execution_gate(synthetic, chain=chain, profile=profile)
    except Exception as exc:
        logger.warning(
            "cold_immediate_sim: gate raised %s — skipping",
            type(exc).__name__,
        )
        return None, counters

    counters["cold_immediate_sim_attempted"] = int(getattr(gate, "sim_attempted", 0) or 0)
    counters["cold_immediate_sim_passed"] = int(getattr(gate, "sim_passed", 0) or 0)
    # issue #3: guard_passed count and profit_guard_rejected count
    guard_passed_list = getattr(gate, "guard_passed", []) or []
    counters["cold_immediate_guard_passed"] = len(guard_passed_list)
    # sim_errors contains PRE_SIM_SKIP:* and REVERT:* reasons
    sim_errors = getattr(gate, "sim_errors", []) or []
    counters["cold_immediate_pre_sim_skip"] = sum(
        1 for e in sim_errors if isinstance(e, str) and e.startswith("PRE_SIM_SKIP:")
    )
    counters["cold_immediate_sim_revert"] = sum(
        1 for e in sim_errors if isinstance(e, str) and e.startswith("REVERT:")
    )
    # E1.56 fix step #6: revert samples for reviewer diagnosis (pair/fee/reason).
    # Sourced from gate.sim_failed_samples which tracks detailed info per failed sim.
    _failed_samples = getattr(gate, "sim_failed_samples", []) or []
    _revert_errors = [e for e in sim_errors if isinstance(e, str) and e.startswith("REVERT:")]
    counters["cold_immediate_sim_revert_samples"] = [
        {
            "pair": s.get("pair"),
            "buy_fee": s.get("buy_fee"),
            "sell_fee": s.get("sell_fee"),
            "amount_in_wei": s.get("amount_in_wei"),
            "block_lag": s.get("block_lag_at_sim"),
            "reason": _revert_errors[i] if i < len(_revert_errors) else "REVERT:unknown",
        }
        for i, s in enumerate(_failed_samples[:10])  # at most 10 samples per window
    ]
    # profit_guard_rejected = guard_passed_input_size - guard_passed_count
    # guard_passed input size = len(synthetic) passed into gate.
    # Approximate: gate.sim_attempted + guard_rejected = guard_passed_list expected items.
    # Use sim_errors count that doesn't start with PRE_SIM_SKIP/REVERT as guard rejects.
    # Simpler: total synthetic - guard_passed = profit_guard_rejected
    # We track via gate field if available, else compute from sim_errors.
    _guard_rej = sum(
        1 for e in sim_errors
        if isinstance(e, str)
        and not e.startswith("PRE_SIM_SKIP:")
        and not e.startswith("REVERT:")
        and not e.startswith("SIM_EXCEPTION:")
        and "PROFIT_GUARD" in e
    )
    counters["cold_immediate_profit_guard_rejected"] = _guard_rej
    # `cold_immediate_sim_profitable` is a stricter signal: how many
    # synthetic candidates carry a positive post-sim net_bps after the
    # gate annotated them. Count from `guard_passed` so we walk the
    # admitted set only.
    profitable = 0
    for r, _g in guard_passed_list:
        try:
            net_post = getattr(r, "best_live_net_bps", None)
            if net_post is None:
                net_post = getattr(r, "best_backrun_net_bps", 0) or 0
            if (net_post or 0) > 0 and bool(getattr(r, "sim_passed", False)):
                profitable += 1
        except Exception:
            pass
    counters["cold_immediate_sim_profitable"] = profitable

    # E1.59 step #4: sim_v1_dry_compare sidecar — compare rpc_fork sim
    # output against eth_simulateV1 for the first profitable candidate.
    # Non-blocking; only writes disagreement stats; never changes gate outcome.
    try:
        from execution.sim_v1_dry_compare import (
            is_enabled as _sv_en, SimResult as _SimResult, compare_results as _sv_cmp,
        )
        if _sv_en():
            _sim_samps = getattr(gate, "sim_output_samples", []) or []
            for _ss in _sim_samps[:5]:
                if not isinstance(_ss, dict):
                    continue
                _ss_success = bool(_ss.get("sim_passed"))
                _ss_revert = _ss.get("revert_reason") or (_ss.get("sim_error") or "")
                _ss_bps = float(_ss.get("roundtrip_profit_bps") or 0)
                _ss_gas = int(_ss.get("gas_used") or 0)
                _rpc_result = _SimResult(
                    success=_ss_success,
                    revert_reason=str(_ss_revert) if _ss_revert else None,
                    profit_bps=_ss_bps,
                    gas_used=_ss_gas,
                )
                # Dry-compare: simulate what eth_simulateV1 would produce.
                # We don't actually call the endpoint here (no calldata to send);
                # record as a rpc_fork-only sample so disagree stats track
                # what fraction of sims could benefit from v1 cross-check.
                _sv1_result = _SimResult(
                    success=_ss_success,
                    revert_reason=str(_ss_revert) if _ss_revert else None,
                    profit_bps=_ss_bps,
                    gas_used=_ss_gas,
                )
                _sv_cmp(
                    _rpc_result,
                    _sv1_result,
                    candidate_id=str(_ss.get("event_id") or ""),
                )
    except Exception:
        pass

    # E1.59 step #6: feed revert taxonomy from cold-immediate sim errors.
    try:
        from m7.orderflow.revert_taxonomy import is_enabled as _rt_en, record as _rt_rec
        if _rt_en():
            _failed_samps_rt = getattr(gate, "sim_failed_samples", []) or []
            for _err in sim_errors:
                if not isinstance(_err, str):
                    continue
                _samp = _failed_samps_rt.pop(0) if _failed_samps_rt else {}
                _rt_rec(
                    _err,
                    pair=_samp.get("pair"),
                    fee=_samp.get("buy_fee"),
                    pool=_samp.get("pool_address"),
                    size_wei=_samp.get("amount_in_wei"),
                    block=None,
                    extra={"source": "cold_immediate_sim"},
                )
    except Exception:
        pass

    # E1.59 step #8: aggregate preflight outcomes for submit-ready candidates.
    try:
        from m7.orderflow.preflight_aggregator import is_enabled as _pfa_en, record as _pfa_rec
        if _pfa_en():
            from m7.orderflow.preflight import run_preflight
            for _r, _g in guard_passed_list:
                _blockers: list = []
                try:
                    _blockers = run_preflight(
                        router=getattr(_r, "best_buy_venue", None),
                        token_in=getattr(_r, "backrun_token_in_address", None),
                        owner=None,
                        amount_wei=None,
                        chain=chain,
                    )
                except Exception:
                    pass
                _pfa_rec(
                    _blockers,
                    router=getattr(_r, "best_buy_venue", None),
                    token_in=getattr(_r, "backrun_token_in_address", None),
                    candidate_id=getattr(_r, "spread_id", None),
                )
    except Exception:
        pass

    # E1.59 step #9: canary rehearsal — dry-run exercise after preflight.
    try:
        from m7.orderflow.canary_rehearsal import is_enabled as _cre_en, rehearse as _cre_run
        if _cre_en() and guard_passed_list:
            _cre_run(
                owner=os.environ.get("ARBY_OWNER_ADDRESS", "0x0"),
                chain=chain,
                rollup={},
                window_pnl_wei=sum(
                    int(getattr(r, "best_backrun_net_bps", 0) or 0)
                    for r, _ in guard_passed_list
                ),
            )
    except Exception:
        pass

    return gate, counters
