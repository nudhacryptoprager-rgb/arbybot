"""
M7 orderflow artifact builders: offline scoring, intent surface
assessments, and the main replay summary aggregator.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    ALL_BLOCKER_TAGS,
    ALL_SURFACES,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_COMPLETION_LATENCY,
    BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    GAS_FLOOR_BPS_ARBITRUM,
    M7A4_CHAIN,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_PRICING_ANOMALY,
    REJECT_GAS_FLOOR_EXCEEDED,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_NO_COUNTER_POOL,
    REJECT_NO_COUNTER_VENUE,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_STALE_POSITIVE,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    SURFACE_BLOCK_BACKRUN,
    SURFACE_COW_SOLVER,
    SURFACE_MEV_SHARE_BACKRUN,
    SURFACE_UNISWAPX_FILLER,
    UNSCORED_REJECTS,
)
from m7.orderflow.contracts import (
    BackrunResult,
    IntentSurfaceAssessment,
    OrderflowEvent,
)
from m7.orderflow.pricing import (
    classify_event_backrun_type,
    classify_event_viability,
    estimate_backrun_gross_bps,
    estimate_fee_cost_bps,
    estimate_gas_cost_bps,
)

logger = logging.getLogger("m7.orderflow.artifacts")

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



def _build_adapter_histogram(results: List[BackrunResult]) -> Dict[str, int]:
    """Build histogram of adapter_type_used across results."""
    hist: Dict[str, int] = {}
    for r in results:
        at = r.adapter_type_used or "none"
        hist[at] = hist.get(at, 0) + 1
    return hist


def _build_pricing_path_histogram(results: List[BackrunResult]) -> Dict[str, int]:
    """Build histogram of pricing_path across results."""
    hist: Dict[str, int] = {}
    for r in results:
        pp = r.pricing_path or "none"
        hist[pp] = hist.get(pp, 0) + 1
    return hist


def _build_latency_breakdown(results: List[BackrunResult]) -> Dict[str, Any]:
    """M7.A.5.30: Aggregate per-stage latency across all results with timing data."""
    _STAGE_KEYS = (
        "resolve_ms", "enrichment_ms", "admission_ms",
        "oracle_ms", "registry_preload_ms", "local_pricing_ms",
    )
    accum: Dict[str, list] = {k: [] for k in _STAGE_KEYS}
    total_pipeline: list = []

    for r in results:
        psl = r.pipeline_stage_latency_ms
        if not isinstance(psl, dict):
            continue
        for k in _STAGE_KEYS:
            v = psl.get(k)
            if isinstance(v, (int, float)):
                accum[k].append(v)
        qpl = r.quote_pipeline_latency_ms
        if isinstance(qpl, (int, float)):
            total_pipeline.append(qpl)

    def _stats(vals):
        if not vals:
            return None
        return {
            "mean": round(sum(vals) / len(vals), 2),
            "max": round(max(vals), 2),
            "count": len(vals),
        }

    breakdown = {k: _stats(v) for k, v in accum.items()}
    breakdown["total_pipeline"] = _stats(total_pipeline)
    # Compute unaccounted = total_pipeline - sum(stages) per result
    unaccounted = []
    for r in results:
        psl = r.pipeline_stage_latency_ms
        if not isinstance(psl, dict):
            continue
        qpl = r.quote_pipeline_latency_ms
        if not isinstance(qpl, (int, float)):
            continue
        staged = sum(psl.get(k, 0) for k in _STAGE_KEYS if isinstance(psl.get(k), (int, float)))
        unaccounted.append(round(qpl - staged, 2))
    breakdown["unaccounted"] = _stats(unaccounted)
    return breakdown


def build_replay_summary(
    events: List[OrderflowEvent],
    results: List[BackrunResult],
    mode: str,
    compact: bool = False,
) -> Dict[str, Any]:
    """Build machine-readable artifact from replay results.

    M7.A.5.46: When compact=True (operational path), skips the expensive
    full results serialization and heavy debug arrays. The rolling/dashboard
    surface only needs aggregate metrics and compact candidate rows.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    viable_count = sum(1 for r in results if r.route_viable)
    positive_net_count = sum(1 for r in results if r.best_backrun_net_bps > 0)

    # M7.A.5.10/5.11/5.12: Unscored reject reasons — results that never got economic scoring
    _UNSCORED_REJECTS = UNSCORED_REJECTS  # alias for local readability

    # Scored results = those that went through economic scoring (even if rejected)
    scored_results = [r for r in results if r.reject_reason not in _UNSCORED_REJECTS]
    scored_net_bps = [r.best_backrun_net_bps for r in scored_results]
    all_net_bps = [r.best_backrun_net_bps for r in results]
    viable_net_bps = [r.best_backrun_net_bps for r in results if r.route_viable]

    # M7.A.5.27: Anomaly-clean scored results — exclude PRICING_ANOMALY from headlines
    # PRICING_ANOMALY (|net_bps| > 10000) is an artifact of thin-liquidity local pricing,
    # not a real signal. Headlines must not be inflated by these values.
    _ANOMALY_REJECTS = frozenset({REJECT_PRICING_ANOMALY})
    scored_results_clean = [
        r for r in scored_results if r.reject_reason not in _ANOMALY_REJECTS
    ]
    scored_net_bps_clean = [r.best_backrun_net_bps for r in scored_results_clean]

    # M7.A.5.10: Split summary fields
    # "any" = includes stale-positive results; "executable" = only viable (fresh + positive)
    # M7.A.5.13: Fix block_lag=0 falsy trap — use explicit None check
    def _lag(r): return r.block_lag if r.block_lag is not None else 999

    # M7.A.5.25: Detection-time lag — how many blocks between event and detection.
    # This is the TRUE low-lag signal; _lag(r) includes scoring latency.
    def _detection_lag(r):
        if r.event_detected_at_block is not None and r.event_block is not None:
            return r.event_detected_at_block - r.event_block
        return 999

    # M7.A.5.28: Unified stale classifier — a result is stale if EITHER:
    #   (a) final block_lag > 2, OR
    #   (b) same_state_class == "stale" (set by mid-pipeline wall-clock abort even
    #       when block_lag may still be ≤ 2 at abort time), OR
    #   (c) reject_reason == REJECT_STALE_POSITIVE
    # This fixes the contract bug where reject_histogram["STALE_POSITIVE"] > 0
    # but stale_positive_count == 0 because mid-pipeline abort events had low block_lag.
    def _is_stale(r):
        if _lag(r) > 2:
            return True
        if getattr(r, "same_state_class", None) == "stale":
            return True
        if getattr(r, "reject_reason", None) == REJECT_STALE_POSITIVE:
            return True
        return False

    positive_net_count_any = sum(1 for r in results if r.best_backrun_net_bps > 0)
    # M7.A.5.25: Use detection-time lag for "low_lag" classification
    positive_net_count_low_lag = sum(
        1 for r in results
        if r.best_backrun_net_bps > 0 and _detection_lag(r) <= 2
    )
    # M7.A.5.28: stale_positive_count uses unified stale classifier
    stale_positive_count = sum(
        1 for r in results
        if r.best_backrun_net_bps > 0 and _is_stale(r)
    )
    # M7.A.5.35: stale_positive_count_clean uses the same filter as
    # best_net_bps_stale_clean (clean + size_valid) to avoid the contract
    # mismatch where stale_positive_count > 0 but stale_clean best is negative.
    # This is computed later after _stale_scored_clean_valid is available.
    best_net_bps_any = round(max(scored_net_bps), 4) if scored_net_bps else None
    best_net_bps_executable = round(max(viable_net_bps), 4) if viable_net_bps else None

    # M7.A.5.27: Anomaly-clean positive counts (exclude PRICING_ANOMALY)
    positive_net_count_clean = sum(
        1 for r in scored_results_clean if r.best_backrun_net_bps > 0
    )
    positive_net_count_low_lag_clean = sum(
        1 for r in scored_results_clean
        if r.best_backrun_net_bps > 0 and _detection_lag(r) <= 2
    )
    best_net_bps_clean = (
        round(max(scored_net_bps_clean), 4) if scored_net_bps_clean else None
    )

    # M7.A.5.13: Stale vs low-lag scored split
    # M7.A.5.25: "detected" uses detection-time lag; "scored" = economically evaluated
    #            from the detection-low-lag set
    _scored_set = frozenset(id(r) for r in scored_results)
    _low_lag_all = [r for r in results if _detection_lag(r) <= 2]
    _low_lag_scored = [r for r in _low_lag_all if id(r) in _scored_set]
    # M7.A.5.28: Use unified stale classifier (block_lag OR same_state_class OR reject_reason)
    _stale_all = [r for r in results if _is_stale(r)]
    _stale_scored = [r for r in _stale_all if id(r) in _scored_set]
    _low_lag_scored_net = [r.best_backrun_net_bps for r in _low_lag_scored]
    _stale_scored_net = [r.best_backrun_net_bps for r in _stale_scored]
    events_detected_low_lag = len(_low_lag_all)
    events_scored_low_lag = len(_low_lag_scored)
    best_net_bps_stale = round(max(_stale_scored_net), 4) if _stale_scored_net else None
    best_net_bps_low_lag_scored = round(max(_low_lag_scored_net), 4) if _low_lag_scored_net else None
    mean_net_bps_stale = (
        round(sum(_stale_scored_net) / len(_stale_scored_net), 4)
        if _stale_scored_net else None
    )
    mean_net_bps_low_lag_scored = (
        round(sum(_low_lag_scored_net) / len(_low_lag_scored_net), 4)
        if _low_lag_scored_net else None
    )

    # M7.A.5.27: Anomaly-clean stale scored — exclude PRICING_ANOMALY from stale KPIs
    _clean_set = frozenset(id(r) for r in scored_results_clean)
    _stale_scored_clean = [r for r in _stale_scored if id(r) in _clean_set]
    _stale_scored_clean_net = [r.best_backrun_net_bps for r in _stale_scored_clean]
    # Also require size_valid for stale_clean to be meaningful
    _stale_scored_clean_valid = [
        r for r in _stale_scored_clean if r.size_valid_for_token
    ]
    _stale_scored_clean_valid_net = [r.best_backrun_net_bps for r in _stale_scored_clean_valid]
    best_net_bps_stale_clean = (
        round(max(_stale_scored_clean_valid_net), 4)
        if _stale_scored_clean_valid_net else None
    )
    # M7.A.5.35: stale_positive_count_clean — same filter as best_net_bps_stale_clean
    stale_positive_count_clean = sum(
        1 for v in _stale_scored_clean_valid_net if v > 0
    )
    # M7.A.5.13: Machine-readable stale/low-lag comparison block
    _TWO_LEG_BASELINE = -3.5062
    stale_scored_count = len(_stale_scored)
    low_lag_scored_count = len(_low_lag_scored)
    low_lag_positive_count = sum(1 for v in _low_lag_scored_net if v > 0)
    stale_positive_count_scored = sum(1 for v in _stale_scored_net if v > 0)
    beats_m4_baseline_stale = (
        max(_stale_scored_net) > _TWO_LEG_BASELINE if _stale_scored_net else False
    )
    beats_m4_baseline_low_lag = (
        max(_low_lag_scored_net) > _TWO_LEG_BASELINE if _low_lag_scored_net else False
    )

    # M7.A.5.10: Size-validity subset
    size_valid_count = sum(1 for r in results if r.size_valid_for_token)
    size_fallback_count = sum(1 for r in results if r.size_valid_for_token is False)

    # Reject reason histogram
    reject_counts: Dict[str, int] = {}
    for r in results:
        if r.reject_reason:
            reject_counts[r.reject_reason] = reject_counts.get(r.reject_reason, 0) + 1

    # M7.A.5.14: Low-lag reject decomposition histogram (block_lag <= 2 only)
    low_lag_reject_counts: Dict[str, int] = {}
    for r in _low_lag_all:
        if r.reject_reason:
            low_lag_reject_counts[r.reject_reason] = (
                low_lag_reject_counts.get(r.reject_reason, 0) + 1
            )

    # M7.A.5.14: Low-lag pipeline stage rates
    _ll_n = len(_low_lag_all)
    _ll_pair_resolved = sum(
        1 for r in _low_lag_all
        if r.reject_reason not in (REJECT_TOKEN_PAIR_UNRESOLVED,)
    )
    _ll_counter_covered = sum(
        1 for r in _low_lag_all
        if r.reject_reason not in (
            REJECT_TOKEN_PAIR_UNRESOLVED, REJECT_NO_COUNTER_POOL,
            REJECT_NO_COUNTER_VENUE,
        )
    )
    _ll_pre_econ_rejected = sum(
        1 for r in _low_lag_all if r.reject_reason in _UNSCORED_REJECTS
    )
    low_lag_pair_resolution_rate = round(_ll_pair_resolved / _ll_n, 4) if _ll_n else None
    low_lag_counter_coverage_rate = round(_ll_counter_covered / _ll_n, 4) if _ll_n else None
    low_lag_scored_results_rate = round(len(_low_lag_scored) / _ll_n, 4) if _ll_n else None
    low_lag_pre_econ_reject_rate = round(_ll_pre_econ_rejected / _ll_n, 4) if _ll_n else None

    # M7.A.5.15: Low-lag debug rows — per-event diagnostic for block_lag <= 2
    low_lag_debug_rows = []
    for r in _low_lag_all:
        _cov = r.coverage_result or {}
        # M7.A.5.19: Extract quote_fail provenance from pipeline_stage_latency_ms
        _psl = r.pipeline_stage_latency_ms or {}
        _qf_stage = None
        _qf_venue = None
        _qf_exc = None
        if r.reject_reason == REJECT_RPC_QUOTE_FAIL:
            _qf_stage = _psl.get("quote_fail_stage")
            _qf_venue = _psl.get("quote_fail_venue")
            _qf_exc = _psl.get("quote_fail_exception_short")
        low_lag_debug_rows.append({
            "event_id": r.event_id,
            "block_lag": r.block_lag,
            "reject_reason": r.reject_reason,
            "pair_resolved": r.pair_resolved,
            "actual_pair": r.actual_pair,
            "pair_unresolved_detail": r.pair_unresolved_detail,
            "token_admitted": r.token_admitted,
            "admission_source": r.admission_source,
            "known_pools": _cov.get("known_pools_total", _cov.get("known_pools", 0)),
            "active_pools": _cov.get("active_pools_total", 0),
            "counter_venue_count": r.counter_venue_count,
            # M7.A.5.16: pool contract truth (None unless TOKEN_PAIR_UNRESOLVED with pool_address)
            "pool_contract_truth": r.pool_contract_truth,
            # M7.A.5.17: which adapter path read pool state
            "pool_state_read_path": r.pool_state_read_path,
            # M7.A.5.19: RPC_QUOTE_FAIL provenance
            "quote_fail_stage": _qf_stage,
            "quote_fail_venue": _qf_venue,
            "quote_fail_exception_short": _qf_exc,
        })

    # M7.A.5.15: Low-lag coverage truth metrics (aggregated from _low_lag_all)
    _ll_cov_results = [r for r in _low_lag_all if r.coverage_result is not None]
    _ll_known_pools = sum(
        (r.coverage_result or {}).get("known_pools_total",
            (r.coverage_result or {}).get("known_pools", 0))
        for r in _ll_cov_results
    )
    _ll_active_pools = sum(
        (r.coverage_result or {}).get("active_pools_total", 0)
        for r in _ll_cov_results
    )
    _ll_active_buy = sum(
        (r.coverage_result or {}).get("active_buy_venues", 0)
        for r in _ll_cov_results
    )
    _ll_active_sell = sum(
        (r.coverage_result or {}).get("active_sell_venues", 0)
        for r in _ll_cov_results
    )
    _ll_no_counter = sum(
        1 for r in _low_lag_all
        if r.reject_reason in (REJECT_NO_COUNTER_POOL, REJECT_NO_COUNTER_VENUE)
    )
    _ll_inactive = sum(
        1 for r in _low_lag_all
        if r.reject_reason in (
            REJECT_ALL_POOLS_TRULY_INACTIVE, REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_COVERAGE_LOCAL_MISMATCH,
        )
    )
    # M7.A.5.19: Count low-lag RPC_QUOTE_FAIL separately
    _ll_rpc_quote_fail = sum(
        1 for r in _low_lag_all
        if r.reject_reason == REJECT_RPC_QUOTE_FAIL
    )
    low_lag_no_counter_pool_rate = round(_ll_no_counter / _ll_n, 4) if _ll_n else None
    low_lag_inactive_pool_rate = round(_ll_inactive / _ll_n, 4) if _ll_n else None

    # M7.A.5.16: Low-lag pool-class truth aggregated metrics
    _ll_unsupported_pool = sum(
        1 for r in _low_lag_all
        if r.pair_unresolved_detail in (
            "POOL_CODE_EMPTY", "POOL_TOKEN0_REVERT", "POOL_TOKEN1_REVERT",
            "POOL_SLOT0_REVERT", "POOL_LIQUIDITY_REVERT", "pool_read_failed",
        )
    )
    _ll_known_untradeable = sum(
        1 for r in _low_lag_all
        if r.pair_resolved and r.reject_reason in _UNSCORED_REJECTS
    )
    low_lag_unsupported_pool_rate = round(_ll_unsupported_pool / _ll_n, 4) if _ll_n else None
    low_lag_no_counter_pool_rate_v2 = low_lag_no_counter_pool_rate  # alias for clarity
    low_lag_inactive_known_pool_rate = round(_ll_inactive / _ll_n, 4) if _ll_n else None
    low_lag_known_but_untradeable_rate = round(_ll_known_untradeable / _ll_n, 4) if _ll_n else None
    # M7.A.5.16: Pool contract truth summary (aggregate dex_family_guess histogram)
    _ll_pool_truth_list = [
        r.pool_contract_truth for r in _low_lag_all
        if r.pool_contract_truth is not None
    ]
    _ll_dex_family_hist: Dict[str, int] = {}
    for _pt in _ll_pool_truth_list:
        _fg = _pt.get("dex_family_guess", "unknown")
        _ll_dex_family_hist[_fg] = _ll_dex_family_hist.get(_fg, 0) + 1

    # M7.A.5.17: V2-specific low-lag metrics
    _ll_v2_resolved = [r for r in _low_lag_all if r.pool_state_read_path == "v2_getReserves"]
    _ll_v2_scored = [r for r in _ll_v2_resolved if id(r) in _scored_set]
    _ll_v2_n = len(_ll_v2_resolved)
    _ll_v2_no_counter = sum(
        1 for r in _ll_v2_resolved
        if r.reject_reason in (REJECT_NO_COUNTER_POOL, REJECT_NO_COUNTER_VENUE)
    )
    _ll_v2_inactive = sum(
        1 for r in _ll_v2_resolved
        if r.reject_reason in (
            REJECT_ALL_POOLS_TRULY_INACTIVE, REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_COVERAGE_LOCAL_MISMATCH,
        )
    )
    low_lag_v2_supported_rate = round(_ll_v2_n / _ll_n, 4) if _ll_n else None
    low_lag_v2_scored_results_rate = round(len(_ll_v2_scored) / _ll_v2_n, 4) if _ll_v2_n else None
    low_lag_v2_no_counter_pool_rate = round(_ll_v2_no_counter / _ll_v2_n, 4) if _ll_v2_n else None
    low_lag_v2_inactive_pool_rate = round(_ll_v2_inactive / _ll_v2_n, 4) if _ll_v2_n else None

    # M7.A.5.11/5.12: Pre-economics coverage metrics
    unscored_count = len(results) - len(scored_results)
    # Active coverage: results that had coverage_complete AND active liquidity
    _cov_results = [r for r in results if r.coverage_result is not None]
    _active_cov = [
        r for r in _cov_results
        if r.coverage_result.get("coverage_complete") is True
    ]
    # Inactive false-positive: coverage said complete in old sense but no active pools
    _inactive_fp = [
        r for r in _cov_results
        if r.coverage_result.get("known_pools_total", r.coverage_result.get("known_pools", 0)) > 0
        and r.coverage_result.get("active_pools_total", -1) == 0
    ]

    # M7.A.5.12: Coverage/local-sim consistency invariant metrics
    _cov_local_mismatch_count = reject_counts.get(
        "COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO", 0
    )
    _truly_inactive_count = reject_counts.get(
        "ALL_CANDIDATE_POOLS_TRULY_INACTIVE", 0
    )
    # Quote reachability: events with coverage_complete=True that reached quote stage
    _quote_reached = [
        r for r in _active_cov
        if r.quote_calls_attempted is not None and r.quote_calls_attempted > 0
    ]
    _cov_complete_no_quote = [
        r for r in _active_cov
        if (r.quote_calls_attempted is None or r.quote_calls_attempted == 0)
        and r.reject_reason not in (
            REJECT_COVERAGE_LOCAL_MISMATCH,
            REJECT_ALL_POOLS_TRULY_INACTIVE,
            REJECT_ALL_POOLS_ZERO_LIQUIDITY,
        )
    ]

    pre_econ_reject_rate = round(unscored_count / len(results), 4) if results else 0.0
    active_coverage_rate = round(len(_active_cov) / len(results), 4) if results else 0.0
    inactive_coverage_false_positive_rate = round(
        len(_inactive_fp) / len(results), 4
    ) if results else 0.0
    scored_results_rate = round(len(scored_results) / len(results), 4) if results else 0.0
    # M7.A.5.12: Consistency metrics
    coverage_local_mismatch_count = _cov_local_mismatch_count
    truly_inactive_count = _truly_inactive_count
    quote_reachability_rate = round(
        len(_quote_reached) / len(_active_cov), 4
    ) if _active_cov else None
    coverage_complete_no_quote_count = len(_cov_complete_no_quote)

    # M7.A.5.18: Low-lag watchlist — accumulated per-pair/pool truth across windows
    _ll_watchlist_map: Dict[str, Dict[str, Any]] = {}  # keyed by pool_address
    for r in _low_lag_all:
        _pool_addr = None
        # Try to get pool_address from event, coverage, or debug row
        _cov_r = r.coverage_result or {}
        _cand = _cov_r.get("candidate_pools", [])
        if _cand:
            _pool_addr = _cand[0].get("address")
        if _pool_addr is None:
            # Try to extract from pool_contract_truth
            _pct = r.pool_contract_truth or {}
            _pool_addr = _pct.get("pool_address")
        if _pool_addr is None:
            continue  # no pool to track
        _pool_addr = _pool_addr.lower()
        _eb = r.event_block or 0
        if _pool_addr in _ll_watchlist_map:
            _entry = _ll_watchlist_map[_pool_addr]
            _entry["last_seen_block"] = max(_entry["last_seen_block"], _eb)
            _entry["first_seen_block"] = min(_entry["first_seen_block"], _eb)
            _entry["seen_count"] += 1
        else:
            _ll_watchlist_map[_pool_addr] = {
                "pair": r.actual_pair,
                "pool_address": _pool_addr,
                "first_seen_block": _eb,
                "last_seen_block": _eb,
                "seen_count": 1,
                "reject_reason": r.reject_reason,
                "pair_unresolved_detail": r.pair_unresolved_detail,
                "pool_state_read_path": r.pool_state_read_path,
                "known_pools": _cov_r.get(
                    "known_pools_total", _cov_r.get("known_pools", 0)
                ),
                "active_pools": _cov_r.get("active_pools_total", 0),
            }
    low_lag_watchlist = list(_ll_watchlist_map.values())

    # M7.A.5.23→5.24: Registry-direct scoring path metrics
    _ll_registry_direct = [
        r for r in _low_lag_all
        if getattr(r, "scoring_path", None) == "registry_direct"
    ]
    _ll_registry_direct_scored = [
        r for r in _ll_registry_direct
        if id(r) in _scored_set
    ]
    low_lag_registry_direct_count = len(_ll_registry_direct)
    low_lag_registry_direct_scored_count = len(_ll_registry_direct_scored)

    # M7.A.5.20: Local-pricing metrics (scored via local state vs remote quoter)
    _ll_local_attempted = sum(
        1 for r in _low_lag_all if r.local_pricing_attempted
    )
    _ll_local_used = sum(
        1 for r in _low_lag_all if r.local_pricing_used
    )
    _ll_local_scored = [r for r in _low_lag_scored if r.local_pricing_used]
    _ll_remote_scored = [r for r in _low_lag_scored if not r.local_pricing_used]
    _ll_local_scored_net = [r.best_backrun_net_bps for r in _ll_local_scored]
    low_lag_scored_local_state_count = len(_ll_local_scored)
    low_lag_scored_remote_quoter_count = len(_ll_remote_scored)
    # Watchlist: how many scored low-lag events had pool in watchlist
    _ll_watchlist_addrs = set(_ll_watchlist_map.keys())
    _ll_scored_watchlist = [
        r for r in _low_lag_scored
        if any(
            (cp.get("address") or "").lower() in _ll_watchlist_addrs
            for cp in (r.coverage_result or {}).get("candidate_pools", [])
        )
    ]
    low_lag_scored_watchlist_count = len(_ll_scored_watchlist)
    best_net_bps_local = (
        round(max(_ll_local_scored_net), 4) if _ll_local_scored_net else None
    )

    # M7.A.5.18: Blocker tags — top-level structural-stopper summary
    _active_tags: List[str] = []
    if events_detected_low_lag == 0:
        _active_tags.append(BLOCKER_LOW_LAG_NONE_THIS_WINDOW)
    if _ll_no_counter > 0:
        _active_tags.append(BLOCKER_LOW_LAG_NO_COUNTER_POOL)
    if _ll_unsupported_pool > 0:
        _active_tags.append(BLOCKER_LOW_LAG_V2_UNSUPPORTED)
    if _ll_inactive > 0:
        _active_tags.append(BLOCKER_LOW_LAG_INACTIVE_POOL)
    # M7.A.5.19: RPC_QUOTE_FAIL — fire when low-lag reject histogram contains it
    if _ll_rpc_quote_fail > 0:
        _active_tags.append(BLOCKER_LOW_LAG_RPC_QUOTE_FAIL)
    # Latency: ONLY fire for scored low-lag paths where pipeline > budget
    # M7.A.5.30: Split by scoring_path — REMOTE_QUOTER only for non-registry_direct
    _ll_over_budget_remote = sum(
        1 for r in _low_lag_scored
        if r.quote_pipeline_latency_ms is not None
        and r.latency_budget_ms is not None
        and r.quote_pipeline_latency_ms > r.latency_budget_ms
        and getattr(r, "scoring_path", None) != "registry_direct"
    )
    if _ll_over_budget_remote > 0:
        _active_tags.append(BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY)
    # M7.A.5.29: Mid-pipeline abort dominant → completion latency blocker
    # Fire when scoring_path is registry_direct (no remote quoter) but
    # majority of events abort mid-pipeline (latency-to-completion issue).
    _mid_abort_count = sum(
        1 for r in results
        if r.pipeline_stage_latency_ms
        and isinstance(r.pipeline_stage_latency_ms, dict)
        and r.pipeline_stage_latency_ms.get("mid_pipeline_abort") is True
    )
    _registry_direct_count = sum(
        1 for r in results if getattr(r, "scoring_path", None) == "registry_direct"
    )
    if (
        _mid_abort_count > 0
        and len(results) > 0
        and _mid_abort_count / len(results) > 0.5
        and _registry_direct_count > _mid_abort_count * 0.5
    ):
        _active_tags.append(BLOCKER_LOW_LAG_COMPLETION_LATENCY)
    # Gas: check if GAS_EXCEEDS_GROSS is dominant reject
    _gas_dom = reject_counts.get(REJECT_GAS_EXCEEDS_GROSS, 0)
    if _gas_dom > 0 and (not scored_net_bps_clean or max(scored_net_bps_clean) < 0):
        _active_tags.append(BLOCKER_GAS_L1_DATA_DOMINANT)
    # Subgraph: always tag if endpoints are configured but no API key mechanism
    _active_tags.append(BLOCKER_SUBGRAPH_API_KEY_REQUIRED)

    blocker_tags = {
        "active_tags": _active_tags,
        "active_count": len(_active_tags),
        "all_canonical_tags": sorted(ALL_BLOCKER_TAGS),
    }

    # M7.A.5.41: Compact top-candidate persistence for rolling artifact.
    # Extract top-5 executable (route_viable) and top-5 stale-positive candidates
    # so the rolling artifact retains per-event diagnostic detail after results
    # are stripped by _ROLLING_EXCLUDE_KEYS.
    def _compact_candidate(r):
        _evt = getattr(r, '_source_event', None)
        # M7.A.5.44: Execution-time local verification — run profit_guard
        # on each compact candidate to verify ending > starting after costs.
        _verified = None
        _verified_net_bps = None
        if r.route_viable and (r.best_backrun_net_bps or 0) > 0 and r.size_valid_for_token:
            _size = getattr(r, 'amount_in_wei', 0) or 0
            _gross = getattr(r, 'gross_pnl_wei', 0) or 0
            if _size > 0:
                _sell = _size + _gross
                try:
                    from m7.orderflow.profit_guard import check_profit_guard
                    _pg = check_profit_guard(
                        buy_amount_wei=_size,
                        sell_amount_wei=_sell,
                        backrun_size_wei=_size,
                        pipeline_latency_ms=r.quote_pipeline_latency_ms,
                    )
                    _verified = _pg.passed
                    _verified_net_bps = round(_pg.net_bps, 4)
                except Exception:
                    pass
        return {
            "event_id": r.event_id,
            "actual_pair": r.actual_pair,
            "net_bps": round(r.best_backrun_net_bps, 4) if r.best_backrun_net_bps else 0,
            "block_lag": r.block_lag,
            "same_state_class": r.same_state_class,
            "route_viable": r.route_viable,
            "size_valid_for_token": r.size_valid_for_token,
            "scoring_path": r.scoring_path,
            "profit_guard_passed": r.profit_guard_passed,
            "pipeline_latency_ms": r.quote_pipeline_latency_ms,
            "reject_reason": r.reject_reason,
            # M7.A.5.43: Pool-address transport for hot lane bridge
            "pool_address": getattr(_evt, 'pool_address', None) if _evt else None,
            # M7.A.5.44: Execution-time local verification
            "verified_profitable": _verified,
            "verified_net_bps": _verified_net_bps,
        }

    _TOP_N = 5
    _exec_candidates = sorted(
        [r for r in results if r.route_viable],
        key=lambda r: r.best_backrun_net_bps or 0,
        reverse=True,
    )[:_TOP_N]
    top_executable_candidates = [_compact_candidate(r) for r in _exec_candidates]

    _stale_candidates = sorted(
        [r for r in results if _is_stale(r) and r.best_backrun_net_bps > 0],
        key=lambda r: r.best_backrun_net_bps or 0,
        reverse=True,
    )[:_TOP_N]
    top_stale_positive_candidates = [_compact_candidate(r) for r in _stale_candidates]

    # M7.A.5.43: Near-executable candidates — size_valid + not anomaly,
    # but rejected by GAS_EXCEEDS_GROSS or staleness (net_bps > -50).
    # These are the closest candidates to executable status.
    _near_exec_candidates = sorted(
        [
            r for r in results
            if r.size_valid_for_token
            and r.reject_reason in (REJECT_GAS_EXCEEDS_GROSS, REJECT_STALE_POSITIVE)
            and r.reject_reason not in _ANOMALY_REJECTS
            and (r.best_backrun_net_bps or 0) > -50
        ],
        key=lambda r: r.best_backrun_net_bps or 0,
        reverse=True,
    )[:_TOP_N]
    near_executable_candidates = [_compact_candidate(r) for r in _near_exec_candidates]

    # M7.A.5.47: Submit-size refinement — for top cold_executable and near_executable
    # candidates, test bounded sizes around observed amount_in_wei.
    # Purpose: verify whether candidate survives sizing adjustment at execution
    # time, not just at the original observed size. Uses profit_guard check
    # (ending balance > starting balance after costs).
    _MICRO_SIZE_MULTIPLIERS = [0.75, 1.0, 1.25, 1.5]
    _micro_refinement_results = []
    _micro_candidates = (_exec_candidates[:3] + _near_exec_candidates[:2])
    for r in _micro_candidates:
        _base_size = getattr(r, 'amount_in_wei', 0) or 0
        if _base_size <= 0:
            continue
        _gross = getattr(r, 'gross_pnl_wei', 0) or 0
        if _base_size <= 0 or _gross == 0:
            continue
        _gross_ratio = _gross / _base_size  # gross PnL per unit input
        _sizes_tried = 0
        _sizes_passed = 0
        _best_micro_net_bps = None
        _best_submit_size = None
        _gas_floor_gap_bps = None
        for mult in _MICRO_SIZE_MULTIPLIERS:
            _test_size = int(_base_size * mult)
            if _test_size <= 0:
                continue
            _test_sell = _test_size + int(_test_size * _gross_ratio)
            try:
                from m7.orderflow.profit_guard import check_profit_guard
                _pg = check_profit_guard(
                    buy_amount_wei=_test_size,
                    sell_amount_wei=_test_sell,
                    backrun_size_wei=_test_size,
                )
                _sizes_tried += 1
                if _pg.passed:
                    _sizes_passed += 1
                if _best_micro_net_bps is None or _pg.net_bps > _best_micro_net_bps:
                    _best_micro_net_bps = round(_pg.net_bps, 4)
                    _best_submit_size = _test_size
                # Track gap to gas floor (how close is net_bps to zero)
                if _gas_floor_gap_bps is None or abs(_pg.net_bps) < abs(_gas_floor_gap_bps):
                    _gas_floor_gap_bps = round(_pg.net_bps, 4)
            except Exception:
                _sizes_tried += 1
        _micro_refinement_results.append({
            "event_id": r.event_id,
            "actual_pair": r.actual_pair,
            "base_net_bps": round(r.best_backrun_net_bps, 4) if r.best_backrun_net_bps else 0,
            "sizes_tried": _sizes_tried,
            "sizes_passed": _sizes_passed,
            "best_micro_net_bps": _best_micro_net_bps,
            "best_submit_size": _best_submit_size,
            "gas_floor_gap_bps": _gas_floor_gap_bps,
            "verified_net_bps_after_refinement": _best_micro_net_bps if _sizes_passed > 0 else None,
            "reject_reason": r.reject_reason,
        })

    # M7.A.5.42: Signal classification — 4 tiers of signal maturity.
    # Only hot_execution_ready should ever be interpreted as "implementation-ready".
    _profit_guard_passed_count = sum(1 for r in results if r.profit_guard_passed)
    signal_classification = {
        "diagnostic_positive": {
            "count": positive_net_count_clean,
            "best_bps": best_net_bps_clean,
            "label": "Positive after anomaly exclusion (may be stale or size-invalid)",
        },
        "stale_positive": {
            "count": stale_positive_count,
            "best_bps": best_net_bps_stale_clean,
            "label": "Positive but stale (block_lag>2 or mid-pipeline abort)",
        },
        "cold_executable_positive": {
            "count": viable_count,
            "best_bps": best_net_bps_executable,
            "label": "Route-viable, fresh, size-valid — cold-lane confirmed",
        },
        "hot_execution_ready": {
            "count": _profit_guard_passed_count,
            "best_bps": None,
            "label": "Profit-guard passed in hot lane — ready for execution",
        },
    }

    # M7.A.5.44: Execution funnel — 5-stage machine-readable progression.
    # Each stage is a strict subset of the previous. The final stage
    # (realized_onchain_profit) is always 0 until M7.B execution is enabled.
    # hot_scored and profit_guard_passed are populated by the hot lane and
    # injected into this cold-lane artifact via the bridge. Cold lane cannot
    # compute them directly (separate process), so they default to 0 here.
    execution_funnel = {
        "diagnostic_positive": positive_net_count_clean,
        "cold_executable_positive": viable_count,
        "hot_scored": 0,  # injected by hot lane via bridge/artifact merge
        "profit_guard_passed": _profit_guard_passed_count,
        "realized_onchain_profit": 0,  # M7.B — not yet implemented
    }

    # M7.A.5.45: Headline level — highest confirmed funnel stage with count > 0.
    # Prevents UI/reports from claiming progress beyond confirmed level.
    _hl_stages = [
        "realized_onchain_profit",
        "profit_guard_passed",
        "hot_scored",
        "cold_executable_positive",
        "diagnostic_positive",
    ]
    _hl = "none"
    for _s in _hl_stages:
        if execution_funnel.get(_s, 0) > 0:
            _hl = _s
            break
    execution_funnel["headline_level"] = _hl

    # M7.A.5.42: Diagnostic-raw block — metrics that are informational but MUST NOT
    # be treated as headline or execution-readiness signals.
    diagnostic_raw = {
        "best_net_bps_any": best_net_bps_any,
        "best_net_bps_low_lag_scored": best_net_bps_low_lag_scored,
        "best_net_bps_stale": best_net_bps_stale,
        "mean_net_bps_stale": mean_net_bps_stale,
        "mean_net_bps_low_lag_scored": mean_net_bps_low_lag_scored,
        "positive_net_count_any": positive_net_count_any,
        "positive_net_count_low_lag": positive_net_count_low_lag,
    }

    return {
        "mode": mode,
        "timestamp": ts,
        "chain": M7A4_CHAIN,
        "events_count": len(events),
        "results_count": len(results),
        "viable_count": viable_count,
        "positive_net_count": positive_net_count,
        # M7.A.5.27: best_net_bps is anomaly-clean (excludes PRICING_ANOMALY)
        "best_net_bps": best_net_bps_clean,
        "worst_net_bps": (
            round(min(scored_net_bps_clean), 4) if scored_net_bps_clean else None
        ),
        "mean_net_bps": (
            round(sum(scored_net_bps_clean) / len(scored_net_bps_clean), 4)
            if scored_net_bps_clean else None
        ),
        "viable_best_net_bps": round(max(viable_net_bps), 4) if viable_net_bps else None,
        # M7.A.5.10: Split fields — best_net_bps_executable is the cold-lane headline
        "best_net_bps_executable": best_net_bps_executable,
        # M7.A.5.27: Anomaly-clean KPIs
        "best_net_bps_clean": best_net_bps_clean,
        "best_net_bps_stale_clean": best_net_bps_stale_clean,
        "positive_net_count_clean": positive_net_count_clean,
        "positive_net_count_low_lag_clean": positive_net_count_low_lag_clean,
        "stale_positive_count": stale_positive_count,
        "stale_positive_count_clean": stale_positive_count_clean,
        "scored_results_count": len(scored_results),
        "size_valid_count": size_valid_count,
        "size_fallback_count": size_fallback_count,
        # M7.A.5.11: Pre-economics coverage metrics
        "pre_econ_reject_rate": pre_econ_reject_rate,
        "active_coverage_rate": active_coverage_rate,
        "inactive_coverage_false_positive_rate": inactive_coverage_false_positive_rate,
        "scored_results_rate": scored_results_rate,
        # M7.A.5.12: Coverage/local-sim consistency metrics
        "coverage_local_mismatch_count": coverage_local_mismatch_count,
        "truly_inactive_count": truly_inactive_count,
        "quote_reachability_rate": quote_reachability_rate,
        "coverage_complete_no_quote_count": coverage_complete_no_quote_count,
        # M7.A.5.13: Stale vs low-lag scored split
        "events_detected_low_lag": events_detected_low_lag,
        "events_scored_low_lag": events_scored_low_lag,
        # M7.A.5.13: Machine-readable stale/low-lag comparison
        "stale_low_lag_comparison": {
            "stale_scored_count": stale_scored_count,
            "stale_positive_count": stale_positive_count_scored,
            "low_lag_scored_count": low_lag_scored_count,
            "low_lag_positive_count": low_lag_positive_count,
            "beats_m4_baseline_stale": beats_m4_baseline_stale,
            "beats_m4_baseline_low_lag": beats_m4_baseline_low_lag,
        },
        "reject_histogram": reject_counts,
        # M7.A.5.14: Low-lag reject decomposition
        "low_lag_reject_histogram": low_lag_reject_counts,
        "low_lag_pair_resolution_rate": low_lag_pair_resolution_rate,
        "low_lag_counter_coverage_rate": low_lag_counter_coverage_rate,
        "low_lag_scored_results_rate": low_lag_scored_results_rate,
        "low_lag_pre_econ_reject_rate": low_lag_pre_econ_reject_rate,
        # M7.A.5.15: Low-lag debug rows + coverage truth
        "low_lag_debug_rows": low_lag_debug_rows,
        "low_lag_coverage_truth": {
            "known_pools_total": _ll_known_pools,
            "active_pools_total": _ll_active_pools,
            "active_buy_venues": _ll_active_buy,
            "active_sell_venues": _ll_active_sell,
            "no_counter_pool_rate": low_lag_no_counter_pool_rate,
            "inactive_pool_rate": low_lag_inactive_pool_rate,
        },
        # M7.A.5.16: Low-lag pool-class truth + aggregated class metrics
        "low_lag_pool_class_truth": {
            "unsupported_pool_rate": low_lag_unsupported_pool_rate,
            "no_counter_pool_rate": low_lag_no_counter_pool_rate_v2,
            "inactive_known_pool_rate": low_lag_inactive_known_pool_rate,
            "known_but_untradeable_rate": low_lag_known_but_untradeable_rate,
            "dex_family_histogram": _ll_dex_family_hist,
            "pool_truth_count": len(_ll_pool_truth_list),
        },
        # M7.A.5.17: V2-specific low-lag metrics
        "low_lag_v2_truth": {
            "low_lag_v2_supported_rate": low_lag_v2_supported_rate,
            "low_lag_v2_scored_results_rate": low_lag_v2_scored_results_rate,
            "low_lag_v2_no_counter_pool_rate": low_lag_v2_no_counter_pool_rate,
            "low_lag_v2_inactive_pool_rate": low_lag_v2_inactive_pool_rate,
            "v2_resolved_count": _ll_v2_n,
            "v2_scored_count": len(_ll_v2_scored),
        },
        # M7.A.5.18: Low-lag watchlist (per-pair/pool truth accumulated across windows)
        "low_lag_watchlist": low_lag_watchlist,
        # M7.A.5.18: Blocker tags (top-level structural-stopper summary)
        "blocker_tags": blocker_tags,
        # M7.A.5.20: Local-pricing metrics
        "low_lag_local_pricing": {
            "local_attempted_count": _ll_local_attempted,
            "local_used_count": _ll_local_used,
            "low_lag_scored_local_state_count": low_lag_scored_local_state_count,
            "low_lag_scored_remote_quoter_count": low_lag_scored_remote_quoter_count,
            "low_lag_scored_watchlist_count": low_lag_scored_watchlist_count,
            "best_net_bps_local": best_net_bps_local,
        },
        # M7.A.5.23→5.24: Registry-direct scoring path metrics
        "m7a523_low_lag_fast_path": {
            "low_lag_registry_direct_count": low_lag_registry_direct_count,
            "low_lag_registry_direct_scored_count": low_lag_registry_direct_scored_count,
        },
        # M7.A.5.24: Pipeline optimization metrics
        "m7a524_pipeline_optimization": {
            "mid_pipeline_abort_count": sum(
                1 for r in results
                if r.pipeline_stage_latency_ms
                and isinstance(r.pipeline_stage_latency_ms, dict)
                and r.pipeline_stage_latency_ms.get("mid_pipeline_abort") is True
            ),
            "scoring_path_histogram": dict(
                sorted(
                    {
                        k: v for k, v in (
                            (sp, sum(1 for r2 in results if getattr(r2, "scoring_path", None) == sp))
                            for sp in set(getattr(r, "scoring_path", None) for r in results)
                        )
                    }.items(),
                    key=lambda x: -x[1],
                )
            ),
        },
        # M7.A.5.30: Per-stage latency breakdown (mean/max across scored results)
        "m7a530_latency_breakdown": _build_latency_breakdown(results),
        # M7.A.5.21: Factory registry + adapter-complete + gas-floor metrics
        "m7a521_registry_metrics": {
            "events_with_registry": sum(
                1 for r in results if r.registry_pools_found is not None
            ),
            "total_registry_pools_found": sum(
                r.registry_pools_found or 0 for r in results
            ),
            "total_registry_pools_active": sum(
                r.registry_pools_active or 0 for r in results
            ),
            "gas_floor_exceeded_count": sum(
                1 for r in results if r.gas_floor_exceeded
            ),
            "adapter_type_histogram": _build_adapter_histogram(results),
            "pricing_path_histogram": _build_pricing_path_histogram(results),
        },
        # M7.A.5.41: Compact top-candidate rows (survive _ROLLING_EXCLUDE_KEYS)
        "top_executable_candidates": top_executable_candidates,
        "top_stale_positive_candidates": top_stale_positive_candidates,
        # M7.A.5.43: Near-executable candidates (closest to viable)
        "near_executable_candidates": near_executable_candidates,
        # M7.A.5.44: Micro-refinement results (bounded size sweep for top candidates)
        "micro_refinement": _micro_refinement_results,
        # M7.A.5.42: Signal classification (4 tiers) + diagnostic raw block
        "signal_classification": signal_classification,
        # M7.A.5.44: Execution funnel (5-stage strict subset progression)
        "execution_funnel": execution_funnel,
        "diagnostic_raw": diagnostic_raw,
        # M7.A.5.46: compact=True skips heavy results/debug serialization.
        # Callers that need raw results use _raw_results (BackrunResult objects).
        "results": [] if compact else [asdict(r) for r in results],
        "low_lag_debug_rows": [] if compact else low_lag_debug_rows,
        "low_lag_watchlist": [] if compact else low_lag_watchlist,
        "two_leg_baseline_net_bps": -3.5062,
        "m7a_triangular_best_net_bps": -14.16,
        "beats_two_leg_baseline": positive_net_count_clean > 0,
        "beats_triangular_baseline": (
            max(scored_net_bps_clean) > -14.16 if scored_net_bps_clean else False
        ),
    }


