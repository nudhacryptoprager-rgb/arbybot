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
    BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    M7A4_CHAIN,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_NO_COUNTER_POOL,
    REJECT_NO_COUNTER_VENUE,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
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



def build_replay_summary(
    events: List[OrderflowEvent],
    results: List[BackrunResult],
    mode: str,
) -> Dict[str, Any]:
    """Build machine-readable artifact from replay results."""
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

    # M7.A.5.10: Split summary fields
    # "any" = includes stale-positive results; "executable" = only viable (fresh + positive)
    # M7.A.5.13: Fix block_lag=0 falsy trap — use explicit None check
    def _lag(r): return r.block_lag if r.block_lag is not None else 999
    positive_net_count_any = sum(1 for r in results if r.best_backrun_net_bps > 0)
    positive_net_count_low_lag = sum(
        1 for r in results
        if r.best_backrun_net_bps > 0 and _lag(r) <= 2
    )
    stale_positive_count = sum(
        1 for r in results
        if r.best_backrun_net_bps > 0 and _lag(r) > 2
    )
    best_net_bps_any = round(max(scored_net_bps), 4) if scored_net_bps else None
    best_net_bps_executable = round(max(viable_net_bps), 4) if viable_net_bps else None

    # M7.A.5.13: Stale vs low-lag scored split
    # "detected" = all events with block metadata; "scored" = only economically evaluated
    _scored_set = frozenset(id(r) for r in scored_results)
    _low_lag_all = [r for r in results if _lag(r) <= 2]
    _low_lag_scored = [r for r in _low_lag_all if id(r) in _scored_set]
    _stale_all = [r for r in results if _lag(r) > 2]
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
    # Latency: check if any scored low-lag result had pipeline latency > budget
    _ll_over_budget = sum(
        1 for r in _low_lag_scored
        if r.quote_pipeline_latency_ms is not None
        and r.latency_budget_ms is not None
        and r.quote_pipeline_latency_ms > r.latency_budget_ms
    )
    if _ll_over_budget > 0 or (events_detected_low_lag > 0 and events_scored_low_lag == 0):
        _active_tags.append(BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY)
    # Gas: check if GAS_EXCEEDS_GROSS is dominant reject
    _gas_dom = reject_counts.get(REJECT_GAS_EXCEEDS_GROSS, 0)
    if _gas_dom > 0 and (not scored_net_bps or max(scored_net_bps) < 0):
        _active_tags.append(BLOCKER_GAS_L1_DATA_DOMINANT)
    # Subgraph: always tag if endpoints are configured but no API key mechanism
    _active_tags.append(BLOCKER_SUBGRAPH_API_KEY_REQUIRED)

    blocker_tags = {
        "active_tags": _active_tags,
        "active_count": len(_active_tags),
        "all_canonical_tags": sorted(ALL_BLOCKER_TAGS),
    }

    return {
        "m7a4_hypothesis": "orderflow_driven_backrun_replay",
        "mode": mode,
        "timestamp": ts,
        "chain": M7A4_CHAIN,
        "events_count": len(events),
        "results_count": len(results),
        "viable_count": viable_count,
        "positive_net_count": positive_net_count,
        # M7.A.5.10: best_net_bps from scored results only (excludes unscored rejects)
        "best_net_bps": round(max(scored_net_bps), 4) if scored_net_bps else None,
        "worst_net_bps": round(min(scored_net_bps), 4) if scored_net_bps else None,
        "mean_net_bps": round(sum(scored_net_bps) / len(scored_net_bps), 4) if scored_net_bps else None,
        "viable_best_net_bps": round(max(viable_net_bps), 4) if viable_net_bps else None,
        # M7.A.5.10: Split fields
        "best_net_bps_any": best_net_bps_any,
        "best_net_bps_executable": best_net_bps_executable,
        "positive_net_count_any": positive_net_count_any,
        "positive_net_count_low_lag": positive_net_count_low_lag,
        "stale_positive_count": stale_positive_count,
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
        "best_net_bps_stale": best_net_bps_stale,
        "best_net_bps_low_lag_scored": best_net_bps_low_lag_scored,
        "mean_net_bps_stale": mean_net_bps_stale,
        "mean_net_bps_low_lag_scored": mean_net_bps_low_lag_scored,
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
        "results": [asdict(r) for r in results],
        "two_leg_baseline_net_bps": -3.5062,
        "m7a_triangular_best_net_bps": -14.16,
        "beats_two_leg_baseline": positive_net_count > 0,
        "beats_triangular_baseline": (
            max(scored_net_bps) > -14.16 if scored_net_bps else False
        ),
    }


