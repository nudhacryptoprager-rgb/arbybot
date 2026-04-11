"""
E1.12.2 Phase 2 - Hot runtime artifacts: write/update hot-lane artifacts.

Extracted from scripts/m7a_orderflow_loop.py. Contains:
  - _compute_headline_level()       - execution funnel stage classifier
  - _write_hot_heartbeat_on_error() - heartbeat on WS/processing failure
  - _write_hot_artifact()           - per-window hot-lane artifact writer
  - _write_hot_intents()            - hot execution intents artifact
  - _update_hot_rollup()            - cumulative session rollup
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from core.logging import get_logger
from m7.orderflow.runtime_io import (
    _atomic_json_write,
    _HOT_ARTIFACT_PATH,
    _HOT_INTENTS_PATH,
    _HOT_ROLLUP_PATH,
    _SESSION_ID,
)
from m7.shared.constants import get_prewarm_pairs

if TYPE_CHECKING:
    from m7.orderflow.execution_gate import ExecutionGateResult

logger = get_logger("m7.orderflow.hot_artifacts")

def _write_hot_heartbeat_on_error(
    iteration: int,
    window_started_at: str,
    window_ended_at: str,
    error_msg: str,
    chain: str = "arbitrum_one",
) -> None:
    """M7.E1.7: Write heartbeat hot artifact when run_ws_live() or processing fails.

    Ensures hot artifacts always carry a fresh current_window_timestamp so
    reviewers can distinguish "runtime alive but WS failed" from "runtime dead".
    Same heartbeat contract as cold lane (current_window_timestamp,
    snapshot_preserved, snapshot_run_timestamp).
    """
    _ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Try to preserve existing artifact (anti-bad-overwrite, like cold lane)
    existing: dict | None = None
    if os.path.exists(_HOT_ARTIFACT_PATH):
        try:
            with open(_HOT_ARTIFACT_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = None

    if existing is not None:
        # Preserve previous snapshot, just stamp heartbeat fields
        existing["current_window_timestamp"] = _ts_now
        existing["snapshot_preserved"] = True
        existing.setdefault("chain", chain)
        existing.setdefault(
            "snapshot_run_timestamp",
            existing.get("run_context", {}).get("run_timestamp"),
        )
        # M7.E1.8: Accumulate error count on heartbeat path
        _ec = existing.get("error_counts") or {}
        _ec["heartbeat_on_error"] = _ec.get("heartbeat_on_error", 0) + 1
        existing["error_counts"] = _ec
        existing["m7_loop_context"] = {
            "lane": "hot",
            "loop_iteration": iteration,
            "window_started_at": window_started_at,
            "window_ended_at": window_ended_at,
            "window_empty": True,
            "error_in_window": error_msg,
        }
    else:
        # No existing artifact вЂ” write minimal heartbeat from scratch
        existing = {
            "lane": "hot",
            "chain": chain,
            "timestamp": _ts_now,
            "loop_iteration": iteration,
            "events_count": 0,
            "best_net_bps_clean": 0,
            "viable_count": 0,
            "has_positive": False,
            "profit_guard_passed_count": 0,
            "current_window_timestamp": _ts_now,
            "snapshot_preserved": True,
            "snapshot_run_timestamp": _ts_now,
            "signal_counts": {
                "events_count": 0,
                "fast_scored": 0,
                "fast_positive": 0,
                "guard_passed": 0,
                "viable_count": 0,
                "sim_attempted": 0,
                "sim_passed": 0,
                "submit_ready": 0,
                "realized": 0,
            },
            "error_counts": {"heartbeat_on_error": 1},
            "run_context": {
                "run_timestamp": _ts_now,
                "chain": chain,
                "code_sha": None,
                "code_dirty": None,
                "code_desc": None,
                "evidence_sha": None,
            },
            "headline_level": "none",
            "m7_loop_context": {
                "lane": "hot",
                "loop_iteration": iteration,
                "window_started_at": window_started_at,
                "window_ended_at": window_ended_at,
                "window_empty": True,
                "error_in_window": error_msg,
            },
        }

    try:
        _atomic_json_write(_HOT_ARTIFACT_PATH, existing, indent=2, default=str)
        logger.info(
            "Hot heartbeat written on error (iter %d): %s",
            iteration, _HOT_ARTIFACT_PATH,
        )
    except Exception as exc:
        logger.warning("Failed to write hot heartbeat: %s", str(exc)[:120])


def _write_hot_artifact(artifact: dict, iteration: int, guard_results: list = None,
                        fast_results: list = None, promoted_pairs: list = None,
                        candidate_pairs: list = None,
                        bridge_diagnostics: dict = None,
                        chain: str = "arbitrum_one",
                        profile: str = "production",
                        gate_result: "ExecutionGateResult | None" = None) -> list:
    """Write minimal hot-lane artifact: best candidate + profit guard status.

    fast_results: list of BackrunResult from score_backrun_fast() (M7.A.5.32)
    promoted_pairs: list of "SYM_A/SYM_B" execution-promoted from cold (M7.A.5.39)
    candidate_pairs: list of "SYM_A/SYM_B" candidate-promoted (wider, M7.A.5.39)
    bridge_diagnostics: dict with bridge prewarm stats (M7.A.5.43)
    """
    # M7.A.5.46: Use _raw_results for BackrunResult access (compact mode).
    results = artifact.get("_raw_results", artifact.get("results", []))
    best = None
    for r in results:
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)
        sv = r.get("size_valid_for_token") if isinstance(r, dict) else getattr(r, "size_valid_for_token", None)
        rr = r.get("reject_reason") if isinstance(r, dict) else getattr(r, "reject_reason", None)
        # M7.A.5.31: Skip size_valid=false from hot headline
        if sv is False:
            continue
        # M7.A.5.34: Hard-exclude PRICING_ANOMALY from hot headline
        if rr == "REJECT_PRICING_ANOMALY":
            continue
        if net is not None and net > 0:
            if best is None or net > (best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", 0)):
                best = r

    _ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _events_count = artifact.get("events_count", 0)
    hot = {
        "lane": "hot",
        "chain": chain,
        "timestamp": _ts_now,
        "loop_iteration": iteration,
        "events_count": _events_count,
        "best_net_bps_clean": artifact.get("best_net_bps_clean") or 0,
        "viable_count": artifact.get("viable_count", 0),
        "has_positive": best is not None,
        "profit_guard_passed_count": len(guard_results) if guard_results else 0,
        # M7.E1.6.1: Always-fresh heartbeat timestamp so reviewer knows runtime is alive
        "current_window_timestamp": _ts_now,
        "snapshot_preserved": _events_count == 0,
        # M7.E1.7: Complete heartbeat contract вЂ” same fields as cold lane
        "snapshot_run_timestamp": _ts_now,
        # M7.E1.8: signal_counts always present (honest 0/{} on empty windows)
        "signal_counts": {},
        # M7.E1.10: WS connection health вЂ” critical for distinguishing
        # "no market events" from "couldn't connect to data source"
        "ws_connection_status": artifact.get("ws_connection_status", "unknown"),
        "blocks_processed": (artifact.get("ws_live_stats") or {}).get("blocks_processed", 0),
        # M7.E1.10: Actual provider path after fallback resolution
        "rpc_provider": artifact.get("rpc_provider", "unknown"),
        "ws_provider": artifact.get("ws_provider", "unknown"),
        "http_fallback_used": artifact.get("http_fallback_used", False),
        "ws_fallback_used": artifact.get("ws_fallback_used", False),
        # M7.A.5.47m: Provenance вЂ” run_context with run_timestamp
        "run_context": {
            "run_timestamp": _ts_now,
            "chain": chain,
            "code_sha": None,
            "code_dirty": None,
            "code_desc": None,
            "evidence_sha": None,
        },
    }

    # M7.A.5.46: Compute headline_level for hot artifact.
    # Hot lane only knows: hot_scored, profit_guard_passed, realized_onchain_profit.
    # diagnostic_positive and cold_executable_positive come from bridge (cold lane truth).
    _fast_scored = len(fast_results) if fast_results else 0
    _fast_positive = sum(1 for r in (fast_results or []) if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0)
    _guard_count = len(guard_results) if guard_results else 0
    # Read cold_executable_positive from bridge, not synthesized from fast_positive.
    _bridge_cold_exec_count = len(
        (bridge_diagnostics or {}).get("_bridge_cold_executable", [])
    ) if bridge_diagnostics else 0
    hot["headline_level"] = _compute_headline_level({
        "diagnostic_positive": _fast_positive,
        "cold_executable_positive": _bridge_cold_exec_count,
        "hot_scored": _fast_scored,
        "profit_guard_passed": _guard_count,
        "realized_onchain_profit": 0,
    })

    # M7.E1.8: signal_counts вЂ” always honest 0/{} on empty windows, never null
    _sim_attempted = gate_result.sim_attempted if gate_result else 0
    _sim_passed = gate_result.sim_passed if gate_result else 0
    _submit_ready = gate_result.submit_ready if gate_result else 0
    hot["signal_counts"] = {
        "events_count": _events_count,
        "fast_scored": _fast_scored,
        "fast_positive": _fast_positive,
        "guard_passed": _guard_count,
        "viable_count": artifact.get("viable_count", 0),
        "sim_attempted": _sim_attempted,
        "sim_passed": _sim_passed,
        "submit_ready": _submit_ready,
        "realized": 0,
    }

    # M7.E1.8: Error counters вЂ” always present (honest 0 on normal path)
    hot["error_counts"] = {"heartbeat_on_error": 0}

    # M7.A.5.39: Two-level promoted watchlist info
    _cand = candidate_pairs or []
    _exec = promoted_pairs or []
    if _exec or _cand:
        hot["promoted_watchlist"] = {
            "count": len(_exec),
            "pairs": _exec,
            "candidate_count": len(_cand),
            "candidate_pairs": _cand,
        }
    else:
        # M7.E1.10: Use profile-aware seed pairs instead of production-only HOT_WATCHLIST_PAIRS.
        _seed = get_prewarm_pairs(chain, profile)
        hot["promoted_watchlist"] = {
            "count": 0,
            "pairs": [f"{a}/{b}" for a, b in _seed],
            "candidate_count": 0,
            "candidate_pairs": [],
            "source": "seed_only",
        }

    # M7.A.5.37: Always emit fast_path block and hot_skip_count even when empty.
    # This ensures rolling hot artifact always surfaces p50/p90/hot_skip metrics.
    _raw_results = artifact.get("_raw_results", [])
    _hot_skip_count = sum(
        1 for r in _raw_results
        if getattr(r, "scoring_path", None) == "hot_skip"
    )
    hot["hot_skip_count"] = _hot_skip_count

    # M7.A.5.42: Hot-gap debug counters вЂ” diagnose conversion gap
    # M7.A.5.47e: Disentangle counters. "admitted" = entered scoring pipeline
    # (total events minus hot_skip). "scored" = got registry_fast result.
    _fast_scored = sum(
        1 for r in _raw_results
        if getattr(r, "scoring_path", None) == "registry_fast"
    )
    _admitted_to_scoring = len(_raw_results) - _hot_skip_count
    # M7.A.5.43: 3 hot-miss counters from bridge diagnostics
    _bd = bridge_diagnostics or {}
    hot["hot_gap_debug"] = {
        "total_events": len(_raw_results),
        # M7.A.5.47e: admission = events that passed registry check (not skipped)
        "admitted_to_scoring": _admitted_to_scoring,
        "fast_path_scored_count": _fast_scored,
        "not_in_hot_registry_count": _hot_skip_count,
        "watchlist_match_count": _bd.get("bridge_pool_address_hit_count", 0),
        # M7.A.5.43: Bridge-driven diagnostics
        "pool_address_match_count": _bd.get("pool_address_match_count", 0),
        "canonical_pair_match_count": _bd.get("canonical_pair_match_count", 0),
        "registry_has_pair_but_not_pool_count": _bd.get("registry_has_pair_but_not_pool_count", 0),
        "bridge_cache_populated": _bd.get("bridge_cache_populated", 0),
        "bridge_registry_prewarmed": _bd.get("bridge_registry_prewarmed", 0),
        # M7.A.5.44: Bridge-hit counters
        "bridge_pool_address_hit_count": _bd.get("bridge_pool_address_hit_count", 0),
        "bridge_pair_hit_count": _bd.get("bridge_pair_hit_count", 0),
        "bridge_loaded_candidate_count": _bd.get("bridge_loaded_candidate_count", 0),
        # M7.A.5.47j: Track actual focused bridge size (all buckets)
        "bridge_focused_pool_count": _bd.get("bridge_focused_pool_count", 0),
        # M7.A.5.46: Pair-level fallback counter
        "bridge_pair_fallback_count": _bd.get("bridge_pair_fallback_count", 0),
        # M7.A.5.47e: Canonical per-window scoring counters
        "fast_score_attempted": _admitted_to_scoring,
        "fast_score_scored": _fast_scored,
        "fast_score_rejected_economics": sum(
            1 for r in _raw_results
            if getattr(r, "scoring_path", None) == "registry_fast"
            and getattr(r, "reject_reason", None) in (
                "REJECT_GAS_EXCEEDS_GROSS", "REJECT_STALE_POSITIVE",
            )
        ),
    }

    # M7.E1.3: Explicit bridge-matched registry vs gas rejection separation.
    # This separates hot zero-hit into two orthogonal blocker classes:
    # (a) event pool is in bridge but NOT in hot registry в†’ registry rejection
    # (b) event pool is in bridge AND registry but gas-killed в†’ gas rejection
    _bridge_set_h = _bd.get("_bridge_pool_addrs_set", set())
    _m_bridge_reg_rejected = 0
    _m_bridge_gas_rejected = 0
    _m_bridge_scored_positive = 0
    for _r_h in _raw_results:
        _evt_h = getattr(_r_h, "_source_event", None)
        if not _evt_h:
            continue
        _ep_h = getattr(_evt_h, "pool_address", "").lower()
        if _ep_h not in _bridge_set_h:
            continue
        if getattr(_r_h, "scoring_path", None) == "hot_skip":
            _m_bridge_reg_rejected += 1
        elif (getattr(_r_h, "best_backrun_net_bps", None) or 0) <= 0:
            _m_bridge_gas_rejected += 1
        else:
            _m_bridge_scored_positive += 1
    hot["hot_gap_debug"]["matched_bridge_then_registry_rejected"] = _m_bridge_reg_rejected
    hot["hot_gap_debug"]["matched_bridge_then_gas_rejected"] = _m_bridge_gas_rejected
    hot["hot_gap_debug"]["matched_bridge_then_scored_positive"] = _m_bridge_scored_positive

    # M7.A.5.47o: Surface bridge counts at top level (not just in hot_gap_debug).
    hot["bridge_focused_pool_count"] = _bd.get("bridge_focused_pool_count", 0)
    hot["bridge_loaded_candidate_count"] = _bd.get("bridge_loaded_candidate_count", 0)
    # M7.A.5.47o: Gas-hopeless C3 tightening stats at top level.
    # M7.A.5.47p: Guarantee non-None вЂ” use `or` fallback for explicit None values.
    hot["c3_gas_hopeless_skipped"] = _bd.get("c3_gas_hopeless_skipped") or 0
    hot["c3_gas_hopeless_families"] = _bd.get("c3_gas_hopeless_families") or []

    # M7.A.5.47d: Surface bridge miss sample at top level for diagnostics
    hot["bridge_miss_sample_top"] = _bd.get("bridge_miss_sample_top", [])
    # M7.A.5.47k: Bridge exclusion reasons at top level
    hot["bridge_excluded_top"] = _bd.get("bridge_excluded_top", [])
    # M7.A.5.47l: Bridge selected pools at assembly time
    hot["bridge_selected_pools_top"] = _bd.get("bridge_selected_at_assembly", [])

    # M7.A.5.47m: bridge_hit_trace_top вЂ” exact-pool diagnostic for each
    # cold_executable pool. Uses the FULL bridge set (not truncated list)
    # so in_bridge is always truthful.
    _bridge_hit_trace: list = []
    _bridge_cold_execs = _bd.get("_bridge_cold_executable", [])
    _full_bridge_set = _bd.get("_bridge_pool_addrs_set", set())
    _bucket_a_set = _bd.get("_bucket_a", set())
    for _cet in _bridge_cold_execs:
        _cet_pa = (_cet.get("pool_address") or "").lower() if isinstance(_cet, dict) else ""
        if not _cet_pa:
            continue
        # Check: is this pool in the full bridge set (truthful check)?
        _cet_in_bridge = _cet_pa in _full_bridge_set
        # Determine selected bucket
        _cet_bucket = None
        if _cet_in_bridge:
            # Find bucket from assembly list first (labeled)
            for _sel in _bd.get("bridge_selected_at_assembly", []):
                if (_sel.get("pool_address") or "").lower() == _cet_pa:
                    _cet_bucket = _sel.get("bucket")
                    break
            if _cet_bucket is None:
                _cet_bucket = "A_cold_exec" if _cet_pa in _bucket_a_set else "unlabeled_in_bridge"
        # Check: did any hot event arrive at this pool?
        _cet_hot_events = 0
        _cet_fast_attempted = 0
        _cet_fast_scored = 0
        for _r in _raw_results:
            _evt = getattr(_r, "_source_event", None)
            if _evt and getattr(_evt, "pool_address", "").lower() == _cet_pa:
                _cet_hot_events += 1
                if getattr(_r, "scoring_path", None) != "hot_skip":
                    _cet_fast_attempted += 1
                    if (getattr(_r, "best_backrun_net_bps", None) or 0) != 0:
                        _cet_fast_scored += 1
        # Reason if not hit
        _cet_reason: str | None = None
        if not _cet_in_bridge:
            _cet_reason = "not_in_bridge"
        elif _cet_hot_events == 0:
            _cet_reason = "no_hot_events_at_pool"
        elif _cet_fast_attempted == 0:
            _cet_reason = "hot_skip_no_scoring"
        elif _cet_fast_scored == 0:
            _cet_reason = "scored_but_no_result"
        _bridge_hit_trace.append({
            "pool_address": _cet_pa,
            "actual_pair": _cet.get("actual_pair", ""),
            "cold_net_bps": _cet.get("net_bps", 0),
            "in_bridge": _cet_in_bridge,
            "selected_bucket": _cet_bucket,
            "hot_events_seen": _cet_hot_events,
            "registry_match": _cet_pa in _full_bridge_set,
            "fast_score_attempted": _cet_fast_attempted,
            "fast_score_scored": _cet_fast_scored,
            "reason_if_not_hit": _cet_reason,
            # M7.A.5.47q: Surface stale_sub_reason so pipeline_abort
            # is distinguishable from block_lag in the trace.
            "stale_sub_reason": _cet.get("stale_sub_reason"),
        })
    hot["bridge_hit_trace_top"] = _bridge_hit_trace
    # M7.A.5.47m: Keep backward compat alias
    hot["cold_exec_pool_trace"] = _bridge_hit_trace

    # M7.A.5.47o: other_live_pool_trace_top вЂ” shows live pools (from hot events)
    # that are NOT in bridge_hit_trace (i.e. not cold-exec pools) but had events.
    # Answers: why do OTHER live pools not get hit?
    _cold_exec_addrs = {(c.get("pool_address") or "").lower() for c in _bridge_cold_execs}
    _ptt_ref = _bd.get("_ptt", {})  # pool_token_transport if available
    _other_pool_events: dict = {}
    for _r in _raw_results:
        _evt = getattr(_r, "_source_event", None)
        if not _evt:
            continue
        _op = getattr(_evt, "pool_address", "").lower()
        if not _op or _op in _cold_exec_addrs:
            continue
        if _op not in _other_pool_events:
            _other_pool_events[_op] = {"hot_events": 0, "fast_attempted": 0, "fast_scored": 0}
        _other_pool_events[_op]["hot_events"] += 1
        if getattr(_r, "scoring_path", None) != "hot_skip":
            _other_pool_events[_op]["fast_attempted"] += 1
            if (getattr(_r, "best_backrun_net_bps", None) or 0) != 0:
                _other_pool_events[_op]["fast_scored"] += 1
    _other_trace: list = []
    for _op, _oc in sorted(_other_pool_events.items(), key=lambda x: x[1]["hot_events"], reverse=True)[:10]:
        _op_in_bridge = _op in _full_bridge_set
        _op_bucket = None
        if _op_in_bridge:
            for _sel in _bd.get("bridge_selected_at_assembly", []):
                if (_sel.get("pool_address") or "").lower() == _op:
                    _op_bucket = _sel.get("bucket")
                    break
            if _op_bucket is None:
                _op_bucket = "unlabeled_in_bridge"
        _op_reason = None
        if not _op_in_bridge:
            _op_reason = "not_in_bridge"
        elif _oc["fast_attempted"] == 0:
            _op_reason = "hot_skip_no_scoring"
        elif _oc["fast_scored"] == 0:
            _op_reason = "scored_but_no_result"
        else:
            _op_reason = None
        _op_info = _ptt_ref.get(_op) if _ptt_ref else None
        _op_family = f"{_op_info[0]}/{_op_info[1]}" if _op_info and len(_op_info) >= 2 else "family_unresolved"
        _other_trace.append({
            "pool_address": _op,
            "family": _op_family,
            "in_bridge": _op_in_bridge,
            "selected_bucket": _op_bucket,
            "hot_events_seen": _oc["hot_events"],
            "fast_score_attempted": _oc["fast_attempted"],
            "fast_score_scored": _oc["fast_scored"],
            "reason_if_not_hit": _op_reason,
        })
    hot["other_live_pool_trace_top"] = _other_trace

    # M7.A.5.47p: bridge_selection_diff_top вЂ” bidirectional mismatch diagnostic.
    # Shows: (a) hot-seen pools absent from bridge, (b) bridge pools with zero hot events.
    _sel_diff: dict = {"hot_seen_not_in_bridge": [], "bridge_selected_but_no_hot_events": []}
    # (a) Hot-seen pools not in bridge (from other_live_pool_trace)
    for _ot in _other_trace:
        if not _ot.get("in_bridge"):
            _sel_diff["hot_seen_not_in_bridge"].append({
                "pool_address": _ot["pool_address"],
                "family": _ot["family"],
                "hot_events_seen": _ot["hot_events_seen"],
                "reason_if_absent": _ot.get("reason_if_not_hit", "not_in_bridge"),
            })
    # (b) Bridge-selected pools with zero hot events this window
    _all_event_pools: set = set()
    for _r in _raw_results:
        _evt = getattr(_r, "_source_event", None)
        if _evt:
            _ep = getattr(_evt, "pool_address", "").lower()
            if _ep:
                _all_event_pools.add(_ep)
    for _sel in _bd.get("bridge_selected_at_assembly", [])[:20]:
        _sel_pa = (_sel.get("pool_address") or "").lower()
        if _sel_pa and _sel_pa not in _all_event_pools:
            _sel_info = _ptt_ref.get(_sel_pa) if _ptt_ref else None
            _sel_fam = f"{_sel_info[0]}/{_sel_info[1]}" if _sel_info and len(_sel_info) >= 2 else "family_unresolved"
            _sel_diff["bridge_selected_but_no_hot_events"].append({
                "pool_address": _sel_pa,
                "family": _sel_fam,
                "selected_bucket": _sel.get("bucket"),
            })
    # Truncate to top 10 each
    _sel_diff["hot_seen_not_in_bridge"] = _sel_diff["hot_seen_not_in_bridge"][:10]
    _sel_diff["bridge_selected_but_no_hot_events"] = _sel_diff["bridge_selected_but_no_hot_events"][:10]
    hot["bridge_selection_diff_top"] = _sel_diff

    # M7.A.5.47q: bridge_selected_family_diff_top вЂ” family-level aggregation.
    # Groups bridge-selected pools by family, counts total selected, events at ANY
    # pool of that family this window, and exact hit count. Answers: is the family
    # starved of events, or just the exact pool?
    _fam_diff: dict = {}  # family_str -> {selected_pool_count, hot_events_any_pool, exact_hit_count, pools}
    for _sel in _bd.get("bridge_selected_at_assembly", [])[:30]:
        _sel_pa = (_sel.get("pool_address") or "").lower()
        _sel_fam = _sel.get("family") or "family_unresolved"
        if not _sel_fam or _sel_fam == "":
            _sel_fam = "family_unresolved"
        if _sel_fam not in _fam_diff:
            _fam_diff[_sel_fam] = {
                "family": _sel_fam,
                "selected_pool_count": 0,
                "hot_events_any_pool": 0,
                "exact_hit_count": 0,
                "pools": [],
            }
        _fd = _fam_diff[_sel_fam]
        _fd["selected_pool_count"] += 1
        # Count events at this specific pool
        _sel_events = 0
        for _r in _raw_results:
            _evt = getattr(_r, "_source_event", None)
            if _evt and getattr(_evt, "pool_address", "").lower() == _sel_pa:
                _sel_events += 1
        _fd["hot_events_any_pool"] += _sel_events
        if _sel_events > 0:
            _fd["exact_hit_count"] += 1
        _fd["pools"].append(_sel_pa)
    # Determine reason_if_zero for families with no events
    _fam_diff_list = []
    for _fd in sorted(_fam_diff.values(), key=lambda x: x["selected_pool_count"], reverse=True):
        _reason_z = None
        if _fd["hot_events_any_pool"] == 0:
            _reason_z = "no_events_at_any_family_pool"
        elif _fd["exact_hit_count"] == 0:
            _reason_z = "events_at_family_but_no_exact_match"
        _fd["reason_if_zero"] = _reason_z
        del _fd["pools"]  # strip internal pool list from artifact
        _fam_diff_list.append(_fd)
    # M7.E1.5: Separate family_unresolved from resolved families in bridge summary.
    _resolved_fam = [f for f in _fam_diff_list if f.get("family") != "family_unresolved"]
    _unresolved_fam = [f for f in _fam_diff_list if f.get("family") == "family_unresolved"]
    hot["bridge_selected_family_diff_top"] = _resolved_fam[:10]
    hot["family_unresolved_pool_count"] = sum(f.get("selected_pool_count", 0) for f in _unresolved_fam)

    if fast_results:
        fast_viable = [r for r in fast_results if r.route_viable]
        fast_positive = [r for r in fast_results if (r.best_backrun_net_bps or 0) > 0]
        fast_guard_passed = [r for r in fast_results if r.profit_guard_passed]
        fast_latencies = [r.quote_pipeline_latency_ms for r in fast_results if r.quote_pipeline_latency_ms]
        # M7.A.5.33/5.34: Aggregate stage-level timing (includes calldata + sign)
        _stage_keys = ["registry_lookup_ms", "pool_state_ms", "local_math_ms",
                       "profit_guard_ms", "tx_build_ms", "calldata_ms",
                       "sign_or_bundle_prep_ms"]
        _stage_agg = {}
        for sk in _stage_keys:
            vals = [
                r.pipeline_stage_latency_ms.get(sk, 0)
                for r in fast_results
                if r.pipeline_stage_latency_ms
            ]
            if vals:
                _stage_agg[f"mean_{sk}"] = round(sum(vals) / len(vals), 2)
                _stage_agg[f"max_{sk}"] = round(max(vals), 2)
        hot["fast_path"] = {
            "scored": len(fast_results),
            "positive": len(fast_positive),
            "viable": len(fast_viable),
            "profit_guard_passed": len(fast_guard_passed),
            "mean_latency_ms": round(sum(fast_latencies) / len(fast_latencies), 2) if fast_latencies else None,
            "max_latency_ms": round(max(fast_latencies), 2) if fast_latencies else None,
            "p50_latency_ms": round(sorted(fast_latencies)[len(fast_latencies) // 2], 2) if fast_latencies else None,
            "p90_latency_ms": round(sorted(fast_latencies)[int(len(fast_latencies) * 0.9)], 2) if fast_latencies else None,
            "best_net_bps": round(max((r.best_backrun_net_bps or 0) for r in fast_results), 4) if fast_results else None,
            "scoring_paths": list(set(r.scoring_path for r in fast_results if r.scoring_path)),
            "stage_timings": _stage_agg if _stage_agg else None,
        }
        # Check if fast path found a better candidate
        for r in fast_positive:
            net = r.best_backrun_net_bps or 0
            if best is None or net > (best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", 0)):
                best = r  # fast-path result is a BackrunResult object
    else:
        # M7.A.5.37: Always emit fast_path block with zeros/nulls
        hot["fast_path"] = {
            "scored": 0,
            "positive": 0,
            "viable": 0,
            "profit_guard_passed": 0,
            "mean_latency_ms": None,
            "max_latency_ms": None,
            "p50_latency_ms": None,
            "p90_latency_ms": None,
            "best_net_bps": None,
            "scoring_paths": [],
            "stage_timings": None,
        }

    # M7.A.5.41: Compact top-hot-candidate rows for auditability
    _TOP_HOT_N = 5
    if fast_results:
        _sorted_hot = sorted(
            fast_results,
            key=lambda r: r.best_backrun_net_bps or 0,
            reverse=True,
        )[:_TOP_HOT_N]
        hot["top_hot_candidates"] = [
            {
                "event_id": r.event_id,
                "actual_pair": r.actual_pair,
                "net_bps": round(r.best_backrun_net_bps, 4) if r.best_backrun_net_bps else 0,
                "block_lag": r.block_lag,
                "route_viable": r.route_viable,
                "scoring_path": r.scoring_path,
                "profit_guard_passed": r.profit_guard_passed,
                "pipeline_latency_ms": r.quote_pipeline_latency_ms,
            }
            for r in _sorted_hot
        ]
    else:
        hot["top_hot_candidates"] = []

    if best is not None:
        hot["best_candidate"] = {
            "event_id": best.get("event_id") if isinstance(best, dict) else getattr(best, "event_id", None),
            "actual_pair": best.get("actual_pair") if isinstance(best, dict) else getattr(best, "actual_pair", None),
            "net_bps": best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", None),
            "scoring_path": best.get("scoring_path") if isinstance(best, dict) else getattr(best, "scoring_path", None),
            "size_valid": best.get("size_valid_for_token") if isinstance(best, dict) else getattr(best, "size_valid_for_token", None),
        }
    if guard_results:
        # Show best guard-passed candidate
        best_guard = max(guard_results, key=lambda x: x[1].net_bps)
        r_dict, guard = best_guard
        hot["best_guard_passed"] = {
            "event_id": r_dict.get("event_id") if isinstance(r_dict, dict) else getattr(r_dict, "event_id", None),
            "net_bps": guard.net_bps,
            "guard_mode": guard.guard_mode,
            "guard_latency_ms": guard.guard_latency_ms,
            "timeboost_eligible": guard.timeboost_eligible,
        }
        # M7.A.5.31: Execution readiness timing summary
        hot["execution_readiness"] = {
            "guard_checks_total": len(guard_results),
            "mean_guard_latency_ms": round(
                sum(g.guard_latency_ms for _, g in guard_results) / len(guard_results), 2
            ),
            "max_guard_latency_ms": round(
                max(g.guard_latency_ms for _, g in guard_results), 2
            ),
            "timeboost_eligible_count": sum(1 for _, g in guard_results if g.timeboost_eligible),
            "timeboost_budget_ms": 50,
        }

    try:
        _atomic_json_write(_HOT_ARTIFACT_PATH, hot, indent=2, default=str)
        logger.info("Hot lane artifact written to %s", _HOT_ARTIFACT_PATH)
    except Exception as exc:
        logger.warning("Failed to write hot artifact: %s", str(exc)[:120])
    # M7.A.5.47n: Return bridge hit trace so caller can merge into bridge file.
    # M7.A.5.47p: Also return other_live_pool_trace for live-miss auto-pin.
    # M7.E1.5: Return resolved families only (family_unresolved filtered out).
    # M7.E1.6: Also return family_unresolved_pool_count for bridge contract.
    _family_unresolved_count = hot.get("family_unresolved_pool_count", 0)
    return _bridge_hit_trace, _other_trace, _resolved_fam, _family_unresolved_count


def _compute_headline_level(funnel: dict) -> str:
    """Return the highest confirmed execution funnel stage with count > 0.

    M7.A.5.45: Headline enforcement вЂ” the UI and reports must not claim
    progress beyond this level. Stages are checked in reverse order
    (most advanced first). Returns the stage name string.
    """
    _STAGES = [
        "realized_onchain_profit",
        "profit_guard_passed",
        "hot_scored",
        "cold_executable_positive",
        "diagnostic_positive",
    ]
    for stage in _STAGES:
        if funnel.get(stage, 0) > 0:
            return stage
    return "none"


def _write_hot_intents(
    fast_results: list | None,
    guard_results: list | None,
    iteration: int,
    bridge: dict | None = None,
    chain: str = "arbitrum_one",
) -> None:
    """Write hot execution intents artifact вЂ” compact rows for hot-scored
    and profit-guard-checked candidates only.

    M7.A.5.45: This artifact is the canonical "ready to submit" queue.
    Only candidates that were actually scored in hot lane (scoring_path=
    registry_fast) appear. Rows include profit_guard_passed status.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []

    # Extract hot-scored candidates from fast_results
    _fast = fast_results or []
    # Build set of guard-passed event_ids for cross-reference
    _guard_event_ids: set = set()
    if guard_results:
        for r_dict, _g in guard_results:
            eid = r_dict.get("event_id") if isinstance(r_dict, dict) else getattr(r_dict, "event_id", None)
            if eid:
                _guard_event_ids.add(eid)

    # M7.A.5.47b: Build micro_refinement lookup from bridge for priority ordering.
    # Keys by actual_pair since hot events score different event_ids than cold.
    _micro_lookup: dict = {}
    if bridge:
        for mr in bridge.get("micro_refinement", []):
            _mr_pair = mr.get("actual_pair")
            if _mr_pair:
                _micro_lookup[_mr_pair] = mr

    # M7.E1.4: Build convergence lookups from bridge for cold-hot cross-reference.
    _cold_exec_pool_set: set = set()
    _selected_pool_info: dict = {}  # pool_address -> {bucket, family}
    _ptt_intents: dict = {}
    if bridge:
        for _ce in bridge.get("cold_executable", []):
            _ce_pa = (_ce.get("pool_address") or "").lower()
            if _ce_pa:
                _cold_exec_pool_set.add(_ce_pa)
        for _sp in bridge.get("bridge_selected_pools_top", []):
            _sp_pa = (_sp.get("pool_address") or "").lower()
            if _sp_pa:
                _selected_pool_info[_sp_pa] = {
                    "bucket": _sp.get("bucket"),
                    "family": _sp.get("family"),
                }
        _ptt_intents = bridge.get("pool_token_transport", {})

    for r in _fast:
        eid = getattr(r, "event_id", None)
        net = getattr(r, "best_backrun_net_bps", None) or 0
        _pair = getattr(r, "actual_pair", None)
        _mr = _micro_lookup.get(_pair, {})
        # M7.E1.4: Extract pool_address from source event for convergence
        _evt_src = getattr(r, "_source_event", None)
        _pool_addr = (getattr(_evt_src, "pool_address", "") or "").lower() if _evt_src else ""
        # Derive family from PTT or bridge_selected_pools_top
        _sel = _selected_pool_info.get(_pool_addr, {})
        _family_raw = _sel.get("family")
        if not _family_raw and _pool_addr and _ptt_intents:
            _ptt_info = _ptt_intents.get(_pool_addr)
            if _ptt_info and len(_ptt_info) >= 2:
                _family_raw = f"{_ptt_info[0]}/{_ptt_info[1]}"
        rows.append({
            "event_id": eid,
            "actual_pair": _pair,
            "net_bps": round(net, 4) if net else 0,
            "profit_guard_passed": getattr(r, "profit_guard_passed", False),
            "guard_passed_in_hot": eid in _guard_event_ids,
            "scoring_path": getattr(r, "scoring_path", None),
            "pipeline_latency_ms": getattr(r, "quote_pipeline_latency_ms", None),
            "route_viable": getattr(r, "route_viable", False),
            # M7.E1.4: Convergence fields for cold-hot cross-reference
            "pool_address": _pool_addr or None,
            "family": _family_raw,
            "selected_bucket": _sel.get("bucket"),
            "same_pool_as_cold_exec": _pool_addr in _cold_exec_pool_set if _pool_addr else False,
            # M7.A.5.47b: Submit-size refinement from cold bridge
            "cold_verified_net_bps": _mr.get("verified_net_bps_after_refinement"),
            "cold_best_submit_size": _mr.get("best_submit_size"),
            "cold_gas_floor_gap_bps": _mr.get("gas_floor_gap_bps"),
            # M7.E1.5: Submit-stage placeholders (populated when sim infra exists)
            "sim_passed": None,
            "submit_ready": None,
        })

    # Sort by cold_verified_net_bps (cold-verified first), then net_bps descending
    rows.sort(
        key=lambda x: (
            x.get("cold_verified_net_bps") or -9999,
            x.get("net_bps", 0),
        ),
        reverse=True,
    )

    # Compute funnel counts for hot lane
    _hot_scored = len(_fast)
    _hot_positive = sum(1 for x in rows if x.get("net_bps", 0) > 0)
    _guard_passed = sum(1 for x in rows if x.get("guard_passed_in_hot"))

    # M7.A.5.46: cold_executable_positive comes from bridge, not synthesized from hot.
    _bridge_cold_exec_count = len(bridge.get("cold_executable", [])) if bridge else 0
    headline_level = _compute_headline_level({
        "diagnostic_positive": _hot_positive,
        "cold_executable_positive": _bridge_cold_exec_count,
        "hot_scored": _hot_scored,
        "profit_guard_passed": _guard_passed,
        "realized_onchain_profit": 0,
    })

    payload = {
        "timestamp": ts,
        "chain": chain,
        "loop_iteration": iteration,
        # M7.E1.6.1: Heartbeat вЂ” always-fresh timestamp for reviewer
        "current_window_timestamp": ts,
        "headline_level": headline_level,
        "hot_scored_count": _hot_scored,
        "hot_positive_count": _hot_positive,
        "profit_guard_passed_count": _guard_passed,
        "cold_executable_pool_count": len(bridge.get("cold_executable", [])) if bridge else 0,
        "intents": rows[:20],  # Cap at 20 rows
        # M7.E1.8.1: run_context for full provenance (chain + run_timestamp)
        "run_context": {
            "run_timestamp": ts,
            "chain": chain,
            "code_sha": None,
            "code_dirty": None,
            "code_desc": None,
            "evidence_sha": None,
        },
    }

    try:
        _atomic_json_write(_HOT_INTENTS_PATH, payload, indent=2, default=str)
        logger.info(
            "Hot intents written: scored=%d positive=%d guard_passed=%d headline=%s",
            _hot_scored, _hot_positive, _guard_passed, headline_level,
        )
    except Exception as exc:
        logger.warning("Failed to write hot intents: %s", str(exc)[:120])


def _update_hot_rollup(
    events_count: int,
    fast_results: list | None,
    guard_results: list | None,
    bridge_diagnostics: dict | None,
    ws_live_stats: dict | None = None,
    hot_active_pools: dict | None = None,
    bridge: dict | None = None,
    chain: str = "arbitrum_one",
    gate_result: "ExecutionGateResult | None" = None,
) -> None:
    """Update cumulative hot rollup artifact вЂ” survives across windows.

    M7.A.5.47: The latest-window hot artifact masks progress because
    empty windows reset counters to zero. The rollup accumulates totals
    across ALL hot windows in the session, giving visibility into
    whether any hot-scored or profit-guard-passed events occurred.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Read existing rollup (or start fresh)
    rollup: dict = {}
    try:
        if os.path.exists(_HOT_ROLLUP_PATH):
            with open(_HOT_ROLLUP_PATH, "r", encoding="utf-8") as f:
                rollup = json.load(f)
    except Exception:
        rollup = {}

    # Increment counters
    _bd = bridge_diagnostics or {}
    _fast = fast_results or []
    _guard = guard_results or []

    rollup["last_updated"] = ts
    # M7.E1.8: Chain provenance вЂ” always present in rolling artifacts
    rollup["chain"] = chain
    # M7.E1.6.1: Heartbeat вЂ” always-fresh timestamp for reviewer
    rollup["current_window_timestamp"] = ts
    # M7.E1.7: Complete heartbeat contract вЂ” same fields as cold lane
    rollup["snapshot_run_timestamp"] = ts
    # M7.A.5.47e: Track first window timestamp for dashboard
    rollup.setdefault("first_window_at", ts)
    rollup["windows_seen"] = rollup.get("windows_seen", 0) + 1
    rollup["events_seen_total"] = rollup.get("events_seen_total", 0) + events_count

    # M7.E1.8: Error counters вЂ” track heartbeat-on-error windows vs normal
    _is_error_window = (events_count == 0 and fast_results is None and guard_results is None
                        and bridge_diagnostics is None and ws_live_stats is None)
    _er = rollup.get("error_counts") or {}
    _er["heartbeat_on_error_windows"] = _er.get("heartbeat_on_error_windows", 0) + (1 if _is_error_window else 0)
    _er["normal_windows"] = _er.get("normal_windows", 0) + (0 if _is_error_window else 1)
    rollup["error_counts"] = _er

    # M7.A.5.47k: Session-scoped counters вЂ” reset each supervisor start.
    # Uses _SESSION_ID (generated at import time) to detect new sessions.
    _prev_sid = rollup.get("session", {}).get("session_id", "")
    if _prev_sid != _SESSION_ID:
        rollup["session"] = {"session_id": _SESSION_ID, "session_started_at": ts}
    _sess = rollup["session"]
    _sess["session_windows_seen"] = _sess.get("session_windows_seen", 0) + 1
    _sess["session_events_seen_total"] = (
        _sess.get("session_events_seen_total", 0) + events_count
    )
    _sess["session_bridge_pool_hit_total"] = (
        _sess.get("session_bridge_pool_hit_total", 0)
        + _bd.get("bridge_pool_address_hit_count", 0)
    )
    _sess["session_fast_path_scored_total"] = (
        _sess.get("session_fast_path_scored_total", 0) + len(_fast)
    )
    # M7.E1.10: Track WS connection failures in session
    _ws_status = (ws_live_stats or {}).get("ws_connection_status", "unknown")
    _sess["session_ws_connected_windows"] = (
        _sess.get("session_ws_connected_windows", 0)
        + (1 if _ws_status == "connected" else 0)
    )
    _sess["session_ws_failed_windows"] = (
        _sess.get("session_ws_failed_windows", 0)
        + (1 if _ws_status.startswith("failed") else 0)
    )
    _sess["session_ws_failed_429_windows"] = (
        _sess.get("session_ws_failed_429_windows", 0)
        + (1 if _ws_status == "failed_429" else 0)
    )
    # M7.E1.10: Track actual provider path per window
    _ws_prov = (ws_live_stats or {}).get("ws_provider", "unknown")
    _rpc_prov = (ws_live_stats or {}).get("rpc_provider", "unknown")
    _sess["session_http_fallback_windows"] = (
        _sess.get("session_http_fallback_windows", 0)
        + (1 if _rpc_prov == "public_fallback" else 0)
    )
    _sess["session_ws_fallback_windows"] = (
        _sess.get("session_ws_fallback_windows", 0)
        + (1 if _ws_prov == "public_fallback" else 0)
    )
    # M7.E1.11: Track provider switches (provider changed from previous window)
    _prev_rpc = _sess.get("last_rpc_provider", _rpc_prov)
    _prev_ws = _sess.get("last_ws_provider", _ws_prov)
    _sess["provider_switch_count"] = (
        _sess.get("provider_switch_count", 0)
        + (1 if _rpc_prov != _prev_rpc else 0)
        + (1 if _ws_prov != _prev_ws else 0)
    )
    _sess["last_ws_connection_status"] = _ws_status
    _sess["last_rpc_provider"] = _rpc_prov
    _sess["last_ws_provider"] = _ws_prov
    rollup["bridge_loaded_candidate_count_total"] = (
        rollup.get("bridge_loaded_candidate_count_total", 0)
        + _bd.get("bridge_loaded_candidate_count", 0)
    )
    rollup["pool_address_match_count_total"] = (
        rollup.get("pool_address_match_count_total", 0)
        + _bd.get("pool_address_match_count", 0)
    )
    rollup["bridge_pool_address_hit_count_total"] = (
        rollup.get("bridge_pool_address_hit_count_total", 0)
        + _bd.get("bridge_pool_address_hit_count", 0)
    )
    rollup["fast_path_scored_total"] = (
        rollup.get("fast_path_scored_total", 0) + len(_fast)
    )
    rollup["fast_path_positive_total"] = (
        rollup.get("fast_path_positive_total", 0)
        + sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0)
    )
    # M7.E1.5: route_viable_total вЂ” route-level economics check (gas < gross, fee < gross, net > 0)
    rollup["route_viable_total"] = (
        rollup.get("route_viable_total", 0)
        + sum(1 for r in _fast if getattr(r, "route_viable", False))
    )
    # M7.E1.5: profit_guard_passed_total вЂ” from _fast inline attribute (gated on route_viable in scoring)
    rollup["profit_guard_passed_total"] = (
        rollup.get("profit_guard_passed_total", 0)
        + sum(1 for r in _fast if getattr(r, "profit_guard_passed", False))
    )
    # M7.E1.5: Submit-stage counters вЂ” populated from execution gate result
    if gate_result is not None:
        rollup["sim_attempted_total"] = (
            rollup.get("sim_attempted_total", 0) + gate_result.sim_attempted
        )
        rollup["sim_passed_total"] = (
            rollup.get("sim_passed_total", 0) + gate_result.sim_passed
        )
        rollup["submit_ready_total"] = (
            rollup.get("submit_ready_total", 0) + gate_result.submit_ready
        )
        rollup["sim_disabled"] = gate_result.sim_disabled
        if gate_result.sim_blocker:
            rollup["sim_blocker"] = gate_result.sim_blocker
    else:
        rollup.setdefault("sim_attempted_total", 0)
        rollup.setdefault("sim_passed_total", 0)
        rollup.setdefault("submit_ready_total", 0)
    # M7.A.5.47: 6 canonical hot miss counters (cumulative)
    rollup["bridge_candidate_loaded_total"] = (
        rollup.get("bridge_candidate_loaded_total", 0)
        + _bd.get("bridge_loaded_candidate_count", 0)
    )
    rollup["bridge_pool_hit_total"] = (
        rollup.get("bridge_pool_hit_total", 0)
        + _bd.get("bridge_pool_address_hit_count", 0)
    )
    rollup["bridge_pair_hit_total"] = (
        rollup.get("bridge_pair_hit_total", 0)
        + _bd.get("bridge_pair_hit_count", 0)
    )
    rollup["registry_hit_for_event_pool_total"] = (
        rollup.get("registry_hit_for_event_pool_total", 0)
        + _bd.get("pool_address_match_count", 0)
    )
    # M7.A.5.47e: admitted = events that entered pipeline (not hot_skip)
    _hot_skip_in_window = sum(
        1 for r in _fast
        if getattr(r, "scoring_path", None) == "hot_skip"
    )
    _admitted_in_window = events_count - _hot_skip_in_window
    rollup["fast_score_attempted_total"] = (
        rollup.get("fast_score_attempted_total", 0) + _admitted_in_window
    )
    rollup["fast_score_rejected_economics_total"] = (
        rollup.get("fast_score_rejected_economics_total", 0)
        + sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) <= 0)
    )

    # M7.A.5.47b: 4 new temporal/diagnostic rollup counters
    _wls = ws_live_stats or {}
    if events_count > 0:
        rollup["windows_with_events"] = rollup.get("windows_with_events", 0) + 1
    else:
        rollup.setdefault("windows_with_events", 0)
    if _bd.get("bridge_pool_address_hit_count", 0) > 0:
        rollup["windows_with_bridge_hits"] = rollup.get("windows_with_bridge_hits", 0) + 1
    else:
        rollup.setdefault("windows_with_bridge_hits", 0)
    if len(_fast) > 0:
        rollup["windows_with_fast_scores"] = rollup.get("windows_with_fast_scores", 0) + 1
    else:
        rollup.setdefault("windows_with_fast_scores", 0)
    rollup["broad_fallback_events_total"] = (
        rollup.get("broad_fallback_events_total", 0)
        + _wls.get("broad_logs", 0)
    )
    # M7.A.5.47c: Cumulative bridge_pool_hit_but_registry_miss
    rollup["bridge_pool_hit_but_registry_miss_total"] = (
        rollup.get("bridge_pool_hit_but_registry_miss_total", 0)
        + _bd.get("bridge_pool_hit_but_registry_miss", 0)
    )
    # M7.A.5.47j: Snapshot of focused bridge size (last window value)
    rollup["bridge_focused_pool_count_last"] = _bd.get("bridge_focused_pool_count", 0)

    # M7.A.5.47c: Hot-seen pool histogram (cumulative top 10)
    # Shows which pools are ACTUALLY active on-chain in hot windows
    if hot_active_pools:
        _hap_sorted = sorted(
            hot_active_pools.items(),
            key=lambda x: x[1].get("event_count", 0),
            reverse=True,
        )[:10]
        rollup["hot_seen_pool_histogram_top"] = [
            {"pool": pa, "count": info["event_count"], "last_iter": info.get("last_iter", 0)}
            for pa, info in _hap_sorted
        ]
    else:
        rollup.setdefault("hot_seen_pool_histogram_top", [])

    # M7.A.5.47d: Hot-seen unresolved/resolved tracking from bridge
    _br = bridge or {}
    _hu_pools = _br.get("hot_seen_unresolved_pools", [])
    _hu_unresolved = sum(1 for p in _hu_pools if isinstance(p, dict) and not p.get("resolved", False))
    _hu_resolved = sum(1 for p in _hu_pools if isinstance(p, dict) and p.get("resolved", False))
    # These are point-in-time snapshots from the latest bridge write
    rollup["hot_seen_unresolved_pool_count"] = _hu_unresolved
    rollup["resolved_from_hot_seen_count"] = _hu_resolved
    # Also track cumulative max for trending
    rollup["hot_seen_unresolved_pool_count_max"] = max(
        rollup.get("hot_seen_unresolved_pool_count_max", 0), _hu_unresolved
    )

    # M7.A.5.47e: Per-window classification (mutually exclusive).
    # Each window falls into exactly ONE miss category. Rollup tracks
    # per-category window counts, then dominant = max by window count.
    _window_class = "none"
    if events_count == 0:
        _window_class = "no_events_in_window"
    elif _bd.get("bridge_pool_address_hit_count", 0) == 0:
        _window_class = "events_but_no_bridge_hit"
    elif len(_fast) == 0:
        _window_class = "bridge_hit_but_not_scored"
    elif sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0) == 0:
        _window_class = "scored_but_rejected_economics"
    elif len(_guard) == 0:
        _window_class = "positive_but_no_guard_pass"
    else:
        _window_class = "guard_passed"

    # Accumulate per-class window counts
    rollup.setdefault("window_miss_classes", {})
    rollup["window_miss_classes"][_window_class] = (
        rollup["window_miss_classes"].get(_window_class, 0) + 1
    )
    # Dominant = class with most windows (excluding guard_passed)
    _miss_only = {
        k: v for k, v in rollup["window_miss_classes"].items()
        if k != "guard_passed"
    }
    rollup["dominant_hot_miss_reason"] = (
        max(_miss_only, key=_miss_only.get) if _miss_only else "none"
    )

    # M7.A.5.47m: Provenance вЂ” run_context with run_timestamp
    rollup["run_context"] = {
        "run_timestamp": ts,
        "chain": chain,
        "code_sha": None,
        "code_dirty": None,
        "code_desc": None,
        "evidence_sha": None,
    }

    # M7.A.5.47m: Flatten session fields to top level for easy access.
    # Session dict remains as canonical source; top-level keys are aliases.
    for _sk in ("session_id", "session_started_at", "session_windows_seen",
                "session_events_seen_total", "session_bridge_pool_hit_total",
                "session_fast_path_scored_total",
                "session_ws_connected_windows", "session_ws_failed_windows",
                "session_ws_failed_429_windows",
                "session_http_fallback_windows", "session_ws_fallback_windows",
                "provider_switch_count",
                "last_ws_connection_status", "last_rpc_provider", "last_ws_provider"):
        rollup[_sk] = _sess.get(_sk)

    # M7.E1.3: Event-to-bridge classification counters (chain-agnostic).
    # For each event in _fast, classify whether its pool is in the bridge set,
    # and if matched, separate registry rejection from gas rejection.
    _bridge_addrs_set = _bd.get("_bridge_pool_addrs_set", set())
    _ptt_rollup = _bd.get("_ptt", {})
    _events_in_bridge_window = 0
    _events_not_in_bridge_window = 0
    _matched_registry_rejected_window = 0
    _matched_gas_rejected_window = 0
    _matched_scored_positive_window = 0
    # Also build per-family event map for architecture_blocker_trace
    _family_event_counts: dict = {}  # family_str -> event_count
    for _r in _fast:
        _evt = getattr(_r, "_source_event", None)
        if not _evt:
            continue
        _ep = getattr(_evt, "pool_address", "").lower()
        _in_bridge = _ep in _bridge_addrs_set
        if _in_bridge:
            _events_in_bridge_window += 1
            if getattr(_r, "scoring_path", None) == "hot_skip":
                _matched_registry_rejected_window += 1  # in bridge but not in hot registry
            elif (getattr(_r, "best_backrun_net_bps", None) or 0) <= 0:
                _matched_gas_rejected_window += 1  # passed registry, gas-killed
            else:
                _matched_scored_positive_window += 1
        else:
            _events_not_in_bridge_window += 1
        # Map event pool to family for architecture blocker trace
        _evt_info = _ptt_rollup.get(_ep)
        if _evt_info and len(_evt_info) >= 2:
            _evt_fam = f"{_evt_info[0]}/{_evt_info[1]}"
            _family_event_counts[_evt_fam] = _family_event_counts.get(_evt_fam, 0) + 1
    # Accumulate into rollup
    rollup["events_in_bridge_total"] = (
        rollup.get("events_in_bridge_total", 0) + _events_in_bridge_window
    )
    rollup["events_not_in_bridge_total"] = (
        rollup.get("events_not_in_bridge_total", 0) + _events_not_in_bridge_window
    )
    rollup["matched_then_registry_rejected_total"] = (
        rollup.get("matched_then_registry_rejected_total", 0) + _matched_registry_rejected_window
    )
    rollup["matched_then_gas_rejected_total"] = (
        rollup.get("matched_then_gas_rejected_total", 0) + _matched_gas_rejected_window
    )
    rollup["matched_then_scored_positive_total"] = (
        rollup.get("matched_then_scored_positive_total", 0) + _matched_scored_positive_window
    )

    # M7.E1.2: Chain-aware target pool selection вЂ” pick first A_cold_exec
    # pool from bridge_selected_at_assembly instead of hardcoded Arbitrum pool.
    _bsa = _bd.get("bridge_selected_at_assembly", [])
    _TARGET_POOL = None
    for _sel in _bsa:
        if _sel.get("bucket") == "A_cold_exec" and _sel.get("pool_address"):
            _TARGET_POOL = _sel["pool_address"].lower()
            break
    if _TARGET_POOL is None:
        for _sel in _bsa:
            if _sel.get("pool_address"):
                _TARGET_POOL = _sel["pool_address"].lower()
                break

    # M7.A.5.47n: Exact-pool session trace вЂ” per-window tracking for target
    # cold-executable pool. Answers: is the pool consistently in bridge?
    # Did any hot event arrive at this exact pool across the session?
    _ept = rollup.get("exact_pool_trace", {})
    if _TARGET_POOL is None:
        _ept = {"pool_address": None, "reason_if_not_hit": "no_bridge_data"}
    else:
        # M7.A.5.47o: Reset exact_pool_trace on session/target change.
        if _ept.get("pool_address") != _TARGET_POOL or _prev_sid != _SESSION_ID:
            _ept = {
                "pool_address": _TARGET_POOL,
                "session_windows_seen": 0,
                "session_windows_in_bridge": 0,
                "session_hot_events_seen": 0,
                "session_fast_attempted": 0,
                "session_fast_scored": 0,
                "in_bridge_every_window": True,
                "last_seen_window": None,
                "reason_if_not_hit": None,
            }
        _ept["session_windows_seen"] = _ept.get("session_windows_seen", 0) + 1
        _target_in_bridge = _TARGET_POOL in _bridge_addrs_set
        if _target_in_bridge:
            _ept["session_windows_in_bridge"] = _ept.get("session_windows_in_bridge", 0) + 1
        else:
            _ept["in_bridge_every_window"] = False
        _target_hot_events = 0
        _target_fast_attempted = 0
        _target_fast_scored = 0
        for _r in _fast:
            _evt = getattr(_r, "_source_event", None)
            if _evt and getattr(_evt, "pool_address", "").lower() == _TARGET_POOL:
                _target_hot_events += 1
                if getattr(_r, "scoring_path", None) != "hot_skip":
                    _target_fast_attempted += 1
                    if (getattr(_r, "best_backrun_net_bps", None) or 0) != 0:
                        _target_fast_scored += 1
        _ept["session_hot_events_seen"] = _ept.get("session_hot_events_seen", 0) + _target_hot_events
        _ept["session_fast_attempted"] = _ept.get("session_fast_attempted", 0) + _target_fast_attempted
        _ept["session_fast_scored"] = _ept.get("session_fast_scored", 0) + _target_fast_scored
        if _target_hot_events > 0:
            _ept["last_seen_window"] = ts
        if not _target_in_bridge:
            _ept["reason_if_not_hit"] = "not_in_bridge"
        elif _target_hot_events == 0:
            _ept["reason_if_not_hit"] = "no_hot_events_at_pool"
        elif _target_fast_attempted == 0:
            _ept["reason_if_not_hit"] = "hot_skip_no_scoring"
        elif _target_fast_scored == 0:
            _ept["reason_if_not_hit"] = "scored_but_no_result"
        else:
            _ept["reason_if_not_hit"] = None
    rollup["exact_pool_trace"] = _ept

    # M7.A.5.47q: exact_family_trace вЂ” family-level session trace.
    _target_info = _ptt_rollup.get(_TARGET_POOL) if _TARGET_POOL else None
    _target_family = (
        f"{_target_info[0]}/{_target_info[1]}"
        if _target_info and len(_target_info) >= 2
        else "family_unresolved"
    )
    _eft = rollup.get("exact_family_trace", {})
    if _eft.get("family") != _target_family or _prev_sid != _SESSION_ID:
        _eft = {
            "family": _target_family,
            "selected_pools": [],
            "session_family_events_seen": 0,
            "session_exact_pool_events_seen": 0,
            "reason_if_no_exact_hit": None,
        }
    _sibling_pools_this_window: list = []
    for _sel in _bsa:
        _sp_fam = _sel.get("family", "")
        if _sp_fam == _target_family or (
            _target_info and _sp_fam and _target_info[0] in _sp_fam and _target_info[1] in _sp_fam
        ):
            _sp_pa = (_sel.get("pool_address") or "").lower()
            if _sp_pa and _sp_pa not in _eft.get("selected_pools", []):
                _eft.setdefault("selected_pools", []).append(_sp_pa)
            _sibling_pools_this_window.append(_sp_pa)
    _family_events_this_window = 0
    _exact_events_this_window = 0
    if _TARGET_POOL:
        for _r in _fast:
            _evt = getattr(_r, "_source_event", None)
            if not _evt:
                continue
            _ep = getattr(_evt, "pool_address", "").lower()
            if _ep == _TARGET_POOL:
                _exact_events_this_window += 1
                _family_events_this_window += 1
            elif _ep in _sibling_pools_this_window:
                _family_events_this_window += 1
    _eft["session_family_events_seen"] = (
        _eft.get("session_family_events_seen", 0) + _family_events_this_window
    )
    _eft["session_exact_pool_events_seen"] = (
        _eft.get("session_exact_pool_events_seen", 0) + _exact_events_this_window
    )
    if _family_events_this_window == 0 and _exact_events_this_window == 0:
        _eft["reason_if_no_exact_hit"] = "no_events_at_any_family_pool"
    elif _family_events_this_window > 0 and _exact_events_this_window == 0:
        _eft["reason_if_no_exact_hit"] = "events_at_sibling_not_exact_pool"
    else:
        _eft["reason_if_no_exact_hit"] = None
    _eft["selected_pools"] = _eft.get("selected_pools", [])[:20]
    rollup["exact_family_trace"] = _eft

    # M7.E1.2: architecture_blocker_trace вЂ” canonical session summary.
    # Fixed: families_with_any_hot_events now checks ALL bridge families
    # against the per-family event map, not just the single target family.
    _abt = rollup.get("architecture_blocker_trace", {})
    if _prev_sid != _SESSION_ID:
        _abt = {}
    _abt["session_windows_seen"] = _sess.get("session_windows_seen", 0)
    _abt["session_events_seen_total"] = _sess.get("session_events_seen_total", 0)
    _bsa_for_abt = _bsa
    _abt_families = set()
    for _s_abt in _bsa_for_abt:
        _sf_abt = _s_abt.get("family", "")
        if _sf_abt and _sf_abt != "family_unresolved":
            _abt_families.add(_sf_abt)
    _abt["families_selected_count"] = len(_abt_families)
    # M7.E1.2: Count families with ANY hot events across ALL bridge families
    _families_hit_this_window = sum(
        1 for fam in _abt_families if _family_event_counts.get(fam, 0) > 0
    )
    _abt["families_with_any_hot_events"] = (
        _abt.get("families_with_any_hot_events", 0) + _families_hit_this_window
    )
    _abt["families_with_exact_hits"] = (
        1 if _eft.get("session_exact_pool_events_seen", 0) > 0 else 0
    )
    # M7.E1.2: Three-way blocker classification:
    # - event_source_absence: no events at ANY bridge family (not just target)
    # - gas_economics_only: events arrive but all gas-rejected (no registry/overlap issue)
    # - selection_or_scoring: events arrive but hit/scoring pipeline blocks them
    _total_events_session = _sess.get("session_events_seen_total", 0)
    _total_bridge_hits_session = _sess.get("session_bridge_pool_hit_total", 0)
    _events_in_bridge_session = rollup.get("events_in_bridge_total", 0)
    if _total_events_session == 0:
        _abt["blocker_class"] = "event_source_absence"
    elif _events_in_bridge_session == 0 and _total_bridge_hits_session == 0:
        _abt["blocker_class"] = "events_not_reaching_bridge"
    elif rollup.get("matched_then_scored_positive_total", 0) > 0:
        _abt["blocker_class"] = "selection_or_scoring"
    else:
        _abt["blocker_class"] = "gas_economics_only"
    rollup["architecture_blocker_trace"] = _abt

    try:
        _atomic_json_write(_HOT_ROLLUP_PATH, rollup, indent=2, default=str)
    except Exception as exc:
        logger.debug("Failed to write hot rollup: %s", str(exc)[:80])

