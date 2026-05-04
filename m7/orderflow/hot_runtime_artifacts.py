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
import m7.orderflow.runtime_io as _rio
from m7.orderflow.runtime_io import (
    _atomic_json_write,
)
from m7.shared.constants import get_prewarm_pairs

if TYPE_CHECKING:
    from m7.orderflow.execution_gate import ExecutionGateResult

logger = get_logger("m7.orderflow.hot_artifacts")


def _compute_rate_metrics(rollup: dict) -> dict:
    """Compute session-delta rates for the current hot worker session.

    Top-level rollup counters are cumulative across many supervisor runs. The
    rate block must therefore subtract a session baseline before dividing by
    the current worker-session elapsed time; otherwise an idle window after a
    restart can report absurd per-hour rates from historical roundtrips.
    """
    block: dict = {}
    sess = rollup.get("session") or {}
    baseline = sess.get("rate_baseline")
    if not isinstance(baseline, dict):
        baseline = {
            "roundtrip_attempted_total": int(
                rollup.get("roundtrip_attempted_total", 0) or 0
            ),
            "roundtrip_profitable_total": int(
                rollup.get("roundtrip_profitable_total", 0) or 0
            ),
            "windows_events_without_fast_score_total": int(
                rollup.get("windows_events_without_fast_score_total", 0) or 0
            ),
        }
        sess["rate_baseline"] = baseline
        rollup["session"] = sess

    def _delta_int(key: str) -> int:
        cur = int(rollup.get(key, 0) or 0)
        base = int(baseline.get(key, cur) or 0)
        return max(0, cur - base)

    elapsed_min = float(sess.get("session_elapsed_minutes") or 0.0)
    elapsed_hrs = elapsed_min / 60.0
    rt_attempted_delta = _delta_int("roundtrip_attempted_total")
    rt_profitable_delta = _delta_int("roundtrip_profitable_total")
    if elapsed_hrs > 0:
        block["roundtrip_attempt_rate_per_hour"] = round(
            rt_attempted_delta / elapsed_hrs, 4
        )
        block["profitable_event_rate_per_hour"] = round(
            rt_profitable_delta / elapsed_hrs, 4
        )
    else:
        block["roundtrip_attempt_rate_per_hour"] = None
        block["profitable_event_rate_per_hour"] = None

    wnd_total = int(sess.get("session_windows_seen", 0) or 0)
    wnd_blackhole_delta = _delta_int("windows_events_without_fast_score_total")
    if wnd_total > 0:
        block["scoring_blackhole_rate"] = round(wnd_blackhole_delta / wnd_total, 4)
    else:
        block["scoring_blackhole_rate"] = None

    block["session_elapsed_minutes"] = round(elapsed_min, 3)
    block["session_windows_seen"] = wnd_total
    block["roundtrip_attempted_delta"] = rt_attempted_delta
    block["roundtrip_profitable_delta"] = rt_profitable_delta
    block["scoring_blackhole_windows_delta"] = wnd_blackhole_delta
    block["rate_basis"] = "current_worker_session_delta"
    return block


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
    if os.path.exists(_rio._HOT_ARTIFACT_PATH):
        try:
            with open(_rio._HOT_ARTIFACT_PATH, "r", encoding="utf-8") as f:
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
        _atomic_json_write(_rio._HOT_ARTIFACT_PATH, existing, indent=2, default=str)
        logger.info(
            "Hot heartbeat written on error (iter %d): %s",
            iteration, _rio._HOT_ARTIFACT_PATH,
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
    # E1.56 Step 1: cold-positive immediate sim queue counters merge.
    # When the cold_immediate lane (ENV-gated) ran on this window, the
    # loop_runner places counters into `artifact["signal_counts"]`. Merge
    # them into the canonical `hot["signal_counts"]` so the rolling
    # rollup picks them up and produces `*_total` aggregates per window.
    _src_sc = artifact.get("signal_counts", {}) or {}
    for _ci_k in (
        "cold_immediate_sim_input_count",
        "cold_immediate_sim_attempted",
        "cold_immediate_sim_passed",
        "cold_immediate_sim_profitable",
    ):
        hot["signal_counts"][_ci_k] = int(_src_sc.get(_ci_k, 0) or 0)
    # E1.12.3: Per-window sim error + submit blocker detail
    if gate_result is not None:
        hot["sim_errors"] = list(getattr(gate_result, "sim_errors", []))
        hot["submit_blockers"] = list(getattr(gate_result, "submit_blockers_detail", []))
    else:
        hot["sim_errors"] = []
        hot["submit_blockers"] = []

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
        # E1.55: cold-start bridge/cache diagnostics. These make the
        # force-reload path reviewable from the per-window artifact.
        "bridge_file_exists": _bd.get("bridge_file_exists", False),
        "bridge_ptt_raw_count": _bd.get("bridge_ptt_raw_count", 0),
        "bridge_mtime_age_s": _bd.get("bridge_mtime_age_s"),
        "persistent_cache_forced_reload_count": _bd.get(
            "persistent_cache_forced_reload_count", 0
        ),
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

    # E1.56 step 6: pool-level visibility for STRATEGY_GATING analysis.
    # Cold lane writes `cold_executable` with pool addresses that were
    # profitable in cold simulation. We need to know whether hot WS event
    # stream actually delivers events on those pools (otherwise hot has
    # no chance to attempt sim regardless of code correctness).
    #   - cold_positive_pools_count: how many distinct positive pool
    #     addresses cold lane reported in current bridge.
    #   - cold_positive_pool_seen_in_hot_count: of those, how many hit
    #     the hot WS stream this window.
    #   - pool_address_mismatch_count: hot events on pool addresses that
    #     share token-pair (family) with a cold-positive entry but the
    #     pool address differs (different fee/factory/version).
    _cold_exec_list = _bd.get("_bridge_cold_executable", []) or []
    _cold_pos_pool_set: set = set()
    _cold_pos_pool_family_map: dict = {}
    for _ce_e in _cold_exec_list:
        if not isinstance(_ce_e, dict):
            continue
        _ce_pa = (_ce_e.get("pool_address") or "").lower()
        if not _ce_pa:
            continue
        _cold_pos_pool_set.add(_ce_pa)
        _t0 = (_ce_e.get("token_in") or "").lower() or None
        _t1 = (_ce_e.get("token_out") or "").lower() or None
        if _t0 and _t1:
            _fam_key = tuple(sorted((_t0, _t1)))
            _cold_pos_pool_family_map.setdefault(_fam_key, set()).add(_ce_pa)
    _cold_pos_seen_in_hot: set = set()
    _pool_addr_mismatch = 0
    _hot_evt_pools: list = []
    for _r_pl in _raw_results:
        _evt_pl = getattr(_r_pl, "_source_event", None)
        if not _evt_pl:
            continue
        _evt_pa = (getattr(_evt_pl, "pool_address", "") or "").lower()
        if not _evt_pa:
            continue
        _hot_evt_pools.append(_evt_pa)
        if _evt_pa in _cold_pos_pool_set:
            _cold_pos_seen_in_hot.add(_evt_pa)
            continue
        # mismatch: hot event family overlaps a cold-positive family but
        # exact pool address differs — different fee tier / factory.
        try:
            _t0_h = (
                getattr(_evt_pl, "token0", None)
                or getattr(_evt_pl, "token_in", None)
                or ""
            ).lower()
            _t1_h = (
                getattr(_evt_pl, "token1", None)
                or getattr(_evt_pl, "token_out", None)
                or ""
            ).lower()
        except Exception:
            _t0_h = _t1_h = ""
        if _t0_h and _t1_h:
            _fam_h = tuple(sorted((_t0_h, _t1_h)))
            if _fam_h in _cold_pos_pool_family_map:
                _pool_addr_mismatch += 1
    hot["hot_gap_debug"]["cold_positive_pools_count"] = len(_cold_pos_pool_set)
    hot["hot_gap_debug"]["cold_positive_pool_seen_in_hot_count"] = len(_cold_pos_seen_in_hot)
    hot["hot_gap_debug"]["pool_address_mismatch_count"] = _pool_addr_mismatch

    # M7.A.5.47o: Surface bridge counts at top level (not just in hot_gap_debug).
    hot["bridge_focused_pool_count"] = _bd.get("bridge_focused_pool_count", 0)
    hot["bridge_loaded_candidate_count"] = _bd.get("bridge_loaded_candidate_count", 0)
    # M7.A.5.47o: Gas-hopeless C3 tightening stats at top level.
    # M7.A.5.47p: Guarantee non-None вЂ” use `or` fallback for explicit None values.
    hot["c3_gas_hopeless_skipped"] = _bd.get("c3_gas_hopeless_skipped") or 0
    hot["c3_gas_hopeless_families"] = _bd.get("c3_gas_hopeless_families") or []
    # E1.56 Step 7: pool-level gas-hopeless quarantine surface fields.
    hot["c3_pool_gas_hopeless_skipped"] = _bd.get("c3_pool_gas_hopeless_skipped") or 0
    hot["pool_gas_hopeless"] = _bd.get("pool_gas_hopeless") or []
    hot["pool_gas_hopeless_count"] = len(_bd.get("pool_gas_hopeless") or [])

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

    # Reviewer post-soak19 fix #4: top-level latency budget block.
    # Aggregates ``quote_pipeline_latency_ms`` across all scored fast-path
    # events with p50/p90/p99 + within-target ratio. Target defaults to 200ms
    # (Base Flashblocks block time) and is overridable via
    # ``ARBY_LATENCY_TARGET_MS``. Stage breakdown reuses ``_stage_agg`` when
    # available so the dashboard/reviewer can see WHERE time goes.
    try:
        _lb_samples_raw = [
            r.quote_pipeline_latency_ms
            for r in (fast_results or [])
            if getattr(r, "quote_pipeline_latency_ms", None) is not None
        ]
        _lb_samples = sorted(_lb_samples_raw)
        try:
            _lb_target = float(os.getenv("ARBY_LATENCY_TARGET_MS", "200"))
        except Exception:
            _lb_target = 200.0

        def _lb_pct(seq, p):
            if not seq:
                return None
            idx = min(len(seq) - 1, int(len(seq) * p))
            return round(seq[idx], 2)

        _lb_within_pct = None
        if _lb_samples:
            _lb_within_count = sum(1 for v in _lb_samples if v <= _lb_target)
            _lb_within_pct = round(_lb_within_count / len(_lb_samples) * 100.0, 2)

        _lb_stage_ref = locals().get("_stage_agg") or None
        hot["latency_budget"] = {
            "samples_total": len(_lb_samples),
            "p50_ms": _lb_pct(_lb_samples, 0.50),
            "p90_ms": _lb_pct(_lb_samples, 0.90),
            "p99_ms": _lb_pct(_lb_samples, 0.99),
            "max_ms": round(_lb_samples[-1], 2) if _lb_samples else None,
            "target_ms": _lb_target,
            "within_target_pct": _lb_within_pct,
            "stage_breakdown": _lb_stage_ref if _lb_stage_ref else None,
        }
    except Exception:
        # Latency budget is observability-only; never block rollup emission.
        hot["latency_budget"] = {
            "samples_total": 0,
            "p50_ms": None,
            "p90_ms": None,
            "p99_ms": None,
            "max_ms": None,
            "target_ms": 200.0,
            "within_target_pct": None,
            "stage_breakdown": None,
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
                "guard_reject_reason": getattr(r, "guard_reject_reason", None),
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
    # N7: filter out guard==None entries (produced when ARBY_SIM_BYPASS_GUARD=1
    # forces [(r, None), ...] tuples in execution_gate). Only entries with a
    # real ProfitGuardResult can feed the best-guard / readiness summaries.
    _real_guards = [
        (r, g) for (r, g) in (guard_results or [])
        if g is not None and getattr(g, "net_bps", None) is not None
    ]
    if _real_guards:
        # Show best guard-passed candidate
        best_guard = max(_real_guards, key=lambda x: x[1].net_bps)
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
            "guard_checks_total": len(_real_guards),
            "mean_guard_latency_ms": round(
                sum(g.guard_latency_ms for _, g in _real_guards) / len(_real_guards), 2
            ),
            "max_guard_latency_ms": round(
                max(g.guard_latency_ms for _, g in _real_guards), 2
            ),
            "timeboost_eligible_count": sum(1 for _, g in _real_guards if g.timeboost_eligible),
            "timeboost_budget_ms": 50,
        }
    elif guard_results:
        # Bypass-guard mode: record only the count, no net_bps (guard==None).
        hot["guard_bypassed"] = True
        hot["guard_bypassed_count"] = len(guard_results)

    try:
        _atomic_json_write(_rio._HOT_ARTIFACT_PATH, hot, indent=2, default=str)
        logger.info("Hot lane artifact written to %s", _rio._HOT_ARTIFACT_PATH)
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
            "guard_reject_reason": getattr(r, "guard_reject_reason", None),
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
        _atomic_json_write(_rio._HOT_INTENTS_PATH, payload, indent=2, default=str)
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
    extra_signal_counts: dict | None = None,
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
        if os.path.exists(_rio._HOT_ROLLUP_PATH):
            with open(_rio._HOT_ROLLUP_PATH, "r", encoding="utf-8") as f:
                rollup = json.load(f)
    except Exception:
        rollup = {}

    # E3: Migration — drop deprecated cross-decimals sim_profit_bps keys.
    # These were written by pre-D1 code and produce garbage values because
    # single-leg swap between different-decimal tokens (WETH 18 vs USDC 6)
    # can never yield a meaningful bps metric. Removed at load time so the
    # rolling artifact heals itself on next update.
    for _deprecated in (
        "_sim_profit_bps_all",
        "sim_profit_bps_best",
        "sim_profit_bps_worst",
        "sim_profit_bps_median",
        "sim_profitable_count",
    ):
        rollup.pop(_deprecated, None)

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
    # M7.E1.34f fix #3: per-lane freshness anchors.
    # last_heartbeat_utc is written on every update (bounded worker cycle
    # completion OR mid-cycle heartbeat); last_event_utc only moves when
    # real order events were ingested; last_scored_utc only moves when
    # the fast path produced any scored candidate. Reviewer staleness
    # gates operate on these instead of wall-clock vs last_updated.
    rollup["last_heartbeat_utc"] = ts
    if events_count > 0:
        rollup["last_event_utc"] = ts
    if len(_fast) > 0:
        rollup["last_scored_utc"] = ts
    # M7.A.5.47e: Track first window timestamp for dashboard
    rollup.setdefault("first_window_at", ts)
    rollup["windows_seen"] = rollup.get("windows_seen", 0) + 1
    rollup["events_seen_total"] = rollup.get("events_seen_total", 0) + events_count

    # E1.51 slice-3c: surface local pool price-state registry counters
    # so canary acceptance can verify ``price_state_updates_delta>0``.
    # Defensive: never raise.
    try:
        from m7.orderflow.pool_price_state import get_registry as _ps_get_registry
        _ps_reg = _ps_get_registry()
        _ps_counters = _ps_reg.counters()
        rollup["pool_price_state"] = {
            "updates_total": int(_ps_counters.get("updates_total", 0)),
            "v2_updates_total": int(_ps_counters.get("v2_updates_total", 0)),
            "decode_errors_total": int(_ps_counters.get("decode_errors_total", 0)),
            "v2_decode_errors_total": int(_ps_counters.get("v2_decode_errors_total", 0)),
            "stale_drops_total": int(_ps_counters.get("stale_drops_total", 0)),
            "v2_stale_drops_total": int(_ps_counters.get("v2_stale_drops_total", 0)),
            "pools_tracked": _ps_reg.pools_tracked(),
        }
    except Exception:
        pass    # M7.E1.8: Error counters вЂ” track heartbeat-on-error windows vs normal
    _is_error_window = (events_count == 0 and fast_results is None and guard_results is None
                        and bridge_diagnostics is None and ws_live_stats is None)
    _er = rollup.get("error_counts") or {}
    _er["heartbeat_on_error_windows"] = _er.get("heartbeat_on_error_windows", 0) + (1 if _is_error_window else 0)
    _er["normal_windows"] = _er.get("normal_windows", 0) + (0 if _is_error_window else 1)
    rollup["error_counts"] = _er

    # M7.A.5.47k: Session-scoped counters вЂ” reset each supervisor start.
    # Uses _rio._SESSION_ID (generated at import time) to detect new sessions.
    _prev_sid = rollup.get("session", {}).get("session_id", "")
    if _prev_sid != _rio._SESSION_ID:
        rollup["session"] = {
            "session_id": _rio._SESSION_ID,
            "session_started_at": ts,
            "rate_baseline": {
                "roundtrip_attempted_total": int(
                    rollup.get("roundtrip_attempted_total", 0) or 0
                ),
                "roundtrip_profitable_total": int(
                    rollup.get("roundtrip_profitable_total", 0) or 0
                ),
                "windows_events_without_fast_score_total": int(
                    rollup.get("windows_events_without_fast_score_total", 0) or 0
                ),
            },
        }
    _sess = rollup["session"]
    # Reviewer post-20m-control fix #7: surface session_started_at at the
    # top level too so reviewer staleness logic does not need to dig into
    # the nested ``session`` block. ``supervisor_end_utc`` is reset to
    # None at session boundary; it is stamped by ``flush_rollup_shutdown``
    # on clean exit. With both fields present, reviewers can compute
    # staleness against the supervisor-end anchor instead of last_updated.
    rollup["current_session_started_at"] = _sess.get("session_started_at")
    if _prev_sid != _rio._SESSION_ID:
        rollup["supervisor_end_utc"] = None
    _sess["session_windows_seen"] = _sess.get("session_windows_seen", 0) + 1
    _sess["session_events_seen_total"] = (
        _sess.get("session_events_seen_total", 0) + events_count
    )
    # M7.E1.34g fix #1: feed-rate diagnostic. Reviewer's P0 finding after
    # 30m E1.34e soak was funnel starvation at input (PROD +5 events / 30m,
    # DISC +15 events / 30m). Exposing events_per_minute for the current
    # session lets the next soak classify this as WS feed starvation vs
    # scoring drop without external math.
    try:
        _start = _sess.get("session_started_at")
        if isinstance(_start, str):
            _start_dt = datetime.fromisoformat(_start.replace("Z", "+00:00"))
            if _start_dt.tzinfo is None:
                _start_dt = _start_dt.replace(tzinfo=timezone.utc)
            _now_dt = datetime.now(timezone.utc)
            _elapsed_min = max((_now_dt - _start_dt).total_seconds() / 60.0, 1.0 / 60.0)
            _sess["session_elapsed_minutes"] = round(_elapsed_min, 3)
            _sess["session_events_per_minute"] = round(
                _sess["session_events_seen_total"] / _elapsed_min, 3
            )
    except Exception:
        pass
    # M7.E1.34h fix #5: supervisor-window feed rate. Rollup-level
    # first_window_at + events_seen_total survive child restarts, so
    # these describe the full supervisor window rather than the most
    # recent short-lived child process. Reviewer must prefer these
    # whenever the supervisor restarts children across a soak.
    try:
        _sw = rollup.get("supervisor_window") or {}
        _fw = rollup.get("first_window_at")
        if isinstance(_fw, str):
            _fw_dt = datetime.fromisoformat(_fw.replace("Z", "+00:00"))
            if _fw_dt.tzinfo is None:
                _fw_dt = _fw_dt.replace(tzinfo=timezone.utc)
            _now_dt_sw = datetime.now(timezone.utc)
            _sw_elapsed = max((_now_dt_sw - _fw_dt).total_seconds() / 60.0, 1.0 / 60.0)
            _sw["first_window_at"] = _fw
            _sw["events_total"] = int(rollup.get("events_seen_total", 0) or 0)
            _sw["elapsed_minutes"] = round(_sw_elapsed, 3)
            _sw["events_per_minute"] = round(_sw["events_total"] / _sw_elapsed, 3)
            rollup["supervisor_window"] = _sw
    except Exception:
        pass
    # E1.46 reviewer fix #5: split supervisor_window into historical
    # (lifetime, persists across child restarts) and current_session
    # (resets on every new session_id). Reviewer / dashboard surface
    # the latter so a hot session producing ~10 events/min is not
    # confused with a long-tail supervisor_window of 0.46 events/min.
    try:
        _csw = {
            "session_started_at": _sess.get("session_started_at"),
            "events_total": int(_sess.get("session_events_seen_total", 0) or 0),
            "elapsed_minutes": _sess.get("session_elapsed_minutes"),
            "events_per_minute": _sess.get("session_events_per_minute"),
        }
        rollup["current_session_window"] = _csw
        # Back-compat alias: keep existing supervisor_window key, also
        # expose it under historical_window so the new naming is clear.
        if "supervisor_window" in rollup:
            rollup["historical_window"] = rollup["supervisor_window"]
    except Exception:
        pass
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
    # M7.E1.34m (soak7): histogram of WS-scan exit reasons across the
    # session. Lets the reviewer distinguish benign recv-timeouts (quiet
    # market) from pathological loop-not-entered / ws_429 cases.
    _exit_reason = (ws_live_stats or {}).get("exit_reason", "unknown")
    _exit_hist = _sess.get("session_exit_reason_histogram") or {}
    if not isinstance(_exit_hist, dict):
        _exit_hist = {}
    _exit_hist[_exit_reason] = int(_exit_hist.get(_exit_reason, 0)) + 1
    _sess["session_exit_reason_histogram"] = _exit_hist
    _sess["last_exit_reason"] = _exit_reason
    # M7.E1.34n (soak8): aggregate WS reconnect quality so reviewer gate
    # can distinguish a single peer drop (healthy recovery) from a
    # pathological reconnect-failure storm.
    _wls_src = ws_live_stats or {}
    for _k_src, _k_dst in (
        ("ws_reconnect_count", "session_ws_reconnect_total"),
        ("ws_recv_error_count", "session_ws_recv_error_total"),
        ("ws_recv_timeout_count", "session_ws_recv_timeout_total"),
        ("ws_subscribe_count", "session_ws_subscribe_total"),
    ):
        try:
            _sess[_k_dst] = int(_sess.get(_k_dst, 0)) + int(_wls_src.get(_k_src, 0) or 0)
        except (TypeError, ValueError):
            pass
    _last_err = _wls_src.get("ws_last_recv_error")
    if isinstance(_last_err, str) and _last_err:
        _sess["last_ws_recv_error"] = _last_err[:200]
    # M7.E1.34c: strict provider policy. When ARBY_STRICT_PROVIDER_POLICY=1,
    # any window served by public_fallback is counted as a policy breach and
    # surfaced in the rollup so the reviewer's production-grade guardrail
    # (fix step #7, 30m soak 2026-04-21) stays visible without silently
    # tolerating best-effort public RPCs.
    _strict_provider = os.environ.get("ARBY_STRICT_PROVIDER_POLICY", "0").strip() == "1"
    if _strict_provider and (_rpc_prov == "public_fallback" or _ws_prov == "public_fallback"):
        rollup["strict_provider_breaches_total"] = (
            rollup.get("strict_provider_breaches_total", 0) + 1
        )
        rollup["strict_provider_last_breach"] = {
            "rpc_provider": _rpc_prov,
            "ws_provider": _ws_prov,
        }
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
    # M7.E1.34f fix #5: bridge-hit-to-fast-score drop diagnostic.
    # If this window saw bridge pool hits but produced no fast_results,
    # record it so reviewer can distinguish "no bridge coverage" from
    # "bridge hit but scoring dropped the candidate".
    _bridge_hits_win = int(_bd.get("bridge_pool_address_hit_count", 0) or 0)
    # Reviewer post-20m-control fix #3: SCORING_BLACKHOLE artifact-level
    # accounting. The post-20m soak showed events_seen +100 with
    # fast_path_scored +0; without per-window classification it is
    # impossible to tell whether the bridge dropped events because the
    # pool universe was too narrow (NO_BRIDGE_HIT) or because the bridge
    # hit but scoring rejected the candidate (BRIDGE_HIT_NOT_SCORED).
    # These two top-level counters answer that question without a soak.
    if events_count > 0 and len(_fast) == 0:
        rollup["windows_events_without_fast_score_total"] = (
            rollup.get("windows_events_without_fast_score_total", 0) + 1
        )
        if _bridge_hits_win == 0:
            rollup["windows_events_without_bridge_hit_total"] = (
                rollup.get("windows_events_without_bridge_hit_total", 0) + 1
            )
    if _bridge_hits_win > 0 and len(_fast) == 0:
        _diag = rollup.get("bridge_hit_but_not_fast_scored") or {}
        _diag["windows"] = int(_diag.get("windows", 0) or 0) + 1
        _diag["bridge_hits"] = int(_diag.get("bridge_hits", 0) or 0) + _bridge_hits_win
        _diag["last_observed_at"] = ts
        # Reason hint (reviewer diagnostic bucket): most common cause is
        # that the bridge-hit event came from a pair the fast path did
        # not recognise as a scoring candidate. Concrete reason codes
        # (e.g. UNKNOWN_PAIR, FAST_PATH_DISABLED) can be added by callers
        # via bridge_diagnostics["bridge_hit_not_scored_reason"].
        _reason = (_bd.get("bridge_hit_not_scored_reason") or "UNKNOWN") if isinstance(_bd, dict) else "UNKNOWN"
        _rh = _diag.get("reason_histogram") or {}
        _rh[_reason] = int(_rh.get(_reason, 0) or 0) + 1
        # E1.46 reviewer fix #2: session-scoped mirror so the reviewer
        # can surface FRESH BRIDGE_HIT_NOT_SCORED reasons (lifetime
        # histogram is too noisy after multiple soaks). Sibling key
        # ``session_bridge_hit_not_scored_reason_histogram`` resets on
        # session_id change via the existing _sess block reset path.
        _srh = _sess.get("session_bridge_hit_not_scored_reason_histogram") or {}
        if not isinstance(_srh, dict):
            _srh = {}
        _srh[_reason] = int(_srh.get(_reason, 0) or 0) + 1
        _sess["session_bridge_hit_not_scored_reason_histogram"] = _srh
        _sess["session_bridge_hit_not_scored_windows"] = (
            int(_sess.get("session_bridge_hit_not_scored_windows", 0) or 0) + 1
        )
        _diag["reason_histogram"] = _rh
        # M7.E1.34h fix #3: propagate enriched sample (raw pair context)
        # into the rollup bucket so reviewer can route drops by pair
        # without re-running the soak. Bounded ring of 10 keeps size small.
        _sample = _bd.get("bridge_hit_not_scored_sample") if isinstance(_bd, dict) else None
        if isinstance(_sample, dict):
            _samples = _diag.get("samples") or []
            _samples.append({**_sample, "observed_at": ts})
            _diag["samples"] = _samples[-10:]
        rollup["bridge_hit_but_not_fast_scored"] = _diag
    rollup["fast_path_scored_total"] = (
        rollup.get("fast_path_scored_total", 0) + len(_fast)
    )
    rollup["fast_path_positive_total"] = (
        rollup.get("fast_path_positive_total", 0)
        + sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0)
    )
    # M7.E1.34g fix #3: net_bps distribution — cost-model vs spread visibility.
    # Reviewer's P2 finding is that most scored candidates fail
    # ARBY_SIM_MIN_NET_BPS=1.0 after gas+fees. Bucketing the observed
    # best_backrun_net_bps (signed int floor) across the session shows
    # whether the distribution is "close-to-threshold" (operational tuning)
    # or "deeply unprofitable" (cost model dominates).
    if _fast:
        _hist = rollup.get("fast_path_net_bps_histogram") or {}
        for _r in _fast:
            _bps = getattr(_r, "best_backrun_net_bps", None)
            if _bps is None:
                _bucket = "unknown"
            else:
                try:
                    _b = float(_bps)
                except (TypeError, ValueError):
                    _bucket = "unknown"
                else:
                    if _b < -10:
                        _bucket = "lt_-10"
                    elif _b < -1:
                        _bucket = "-10_to_-1"
                    elif _b < 0:
                        _bucket = "-1_to_0"
                    elif _b < 1:
                        _bucket = "0_to_1"
                    elif _b < 5:
                        _bucket = "1_to_5"
                    elif _b < 10:
                        _bucket = "5_to_10"
                    else:
                        _bucket = "gte_10"
            _hist[_bucket] = int(_hist.get(_bucket, 0) or 0) + 1
        rollup["fast_path_net_bps_histogram"] = _hist
    # soak16 P1.5: dump structured score-component samples so the reviewer can
    # see WHY 98% of fast_path_scored land in `lt_-10` / `-10_to_-1` buckets.
    # We keep a bounded ring (default 50, override via
    # ARBY_FAST_PATH_COMPONENTS_RING_SIZE) carrying the gross/gas/fee
    # decomposition + l1/l2 split per scored result. Each iteration appends
    # the latest scored batch and the ring drops oldest entries.
    if _fast:
        try:
            _ring_size = int(os.environ.get("ARBY_FAST_PATH_COMPONENTS_RING_SIZE", "50"))
        except (TypeError, ValueError):
            _ring_size = 50
        _components = rollup.get("fast_path_score_components_recent") or []
        for _r in _fast:
            _net = getattr(_r, "best_backrun_net_bps", None)
            _l2 = getattr(_r, "l2_gas_bps", None)
            _l1 = getattr(_r, "l1_data_bps", None)
            _tot_gas = getattr(_r, "total_gas_bps", None)
            _gross_wei = getattr(_r, "gross_pnl_wei", None) or 0
            _amt = getattr(_r, "amount_in_wei", None) or 0
            _gross_bps = None
            if _amt and _gross_wei:
                try:
                    _gross_bps = round((float(_gross_wei) / float(_amt)) * 10000.0, 4)
                except (TypeError, ValueError, ZeroDivisionError):
                    _gross_bps = None
            _components.append({
                "ts": ts,
                "pair": getattr(_r, "actual_pair", None),
                "buy_venue": getattr(_r, "best_buy_venue", None),
                "sell_venue": getattr(_r, "best_sell_venue", None),
                "amount_in_wei": _amt,
                "gross_bps": _gross_bps,
                "l2_gas_bps": _l2,
                "l1_data_bps": _l1,
                "total_gas_bps": _tot_gas,
                "net_bps": _net,
                "route_viable": bool(getattr(_r, "route_viable", False)),
                "block_lag": getattr(_r, "block_lag", None),
            })
        if _ring_size > 0:
            _components = _components[-_ring_size:]
        rollup["fast_path_score_components_recent"] = _components
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
    # M7.E1.34c/M7.E1.34e: invariant — profit_guard is gated on route_viable,
    # so the cumulative counters must obey
    # profit_guard_passed_total <= route_viable_total. Discovery lane 30m soak
    # 2026-04-21 showed +3 guard vs +0 viable, i.e. a contract smell.
    # M7.E1.34e fix #6: report SESSION-delta invariant in addition to the
    # cumulative one so historical pollution from prior sessions does not
    # mask whether the new code is correct. The session baseline is
    # captured the first time we observe this rollup under the current
    # _SESSION_ID; subsequent updates compare against that baseline.
    _pgpt = int(rollup.get("profit_guard_passed_total", 0) or 0)
    _rvt = int(rollup.get("route_viable_total", 0) or 0)
    _sess = rollup.get("session") or {}
    _sess_baseline = _sess.get("invariant_baseline")
    if not isinstance(_sess_baseline, dict):
        _sess_baseline = {
            "profit_guard_passed_total": _pgpt,
            "route_viable_total": _rvt,
        }
        _sess["invariant_baseline"] = _sess_baseline
        rollup["session"] = _sess
    _sess_pgpt_delta = _pgpt - int(_sess_baseline.get("profit_guard_passed_total", 0) or 0)
    _sess_rvt_delta = _rvt - int(_sess_baseline.get("route_viable_total", 0) or 0)
    if _pgpt > _rvt or _sess_pgpt_delta > _sess_rvt_delta:
        _inv = rollup.get("invariant_violations") or {}
        _inv["profit_guard_exceeds_route_viable"] = {
            "profit_guard_passed_total": _pgpt,
            "route_viable_total": _rvt,
            "delta": _pgpt - _rvt,
            "session_profit_guard_passed_delta": _sess_pgpt_delta,
            "session_route_viable_delta": _sess_rvt_delta,
            "session_delta": _sess_pgpt_delta - _sess_rvt_delta,
            "is_session_regression": _sess_pgpt_delta > _sess_rvt_delta,
        }
        rollup["invariant_violations"] = _inv
        if _sess_pgpt_delta > _sess_rvt_delta:
            logger.warning(
                "invariant SESSION regression: profit_guard_passed +%d > route_viable +%d",
                _sess_pgpt_delta, _sess_rvt_delta,
            )
        else:
            logger.warning(
                "invariant cumulative-only: profit_guard_passed_total=%d > route_viable_total=%d "
                "(session deltas in line: +%d vs +%d)",
                _pgpt, _rvt, _sess_pgpt_delta, _sess_rvt_delta,
            )
    _guard_hist = rollup.get("guard_reject_reason_histogram") or {}
    for r in _fast:
        _guard_reason = getattr(r, "guard_reject_reason", None)
        if _guard_reason:
            _guard_hist[_guard_reason] = _guard_hist.get(_guard_reason, 0) + 1
    rollup["guard_reject_reason_histogram"] = _guard_hist
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
        # E1.56 Step 1: cold-immediate sim queue rollup totals.
        # Counters live in artifact["signal_counts"] (set by loop_runner
        # after queue_cold_executable_for_sim runs). Aggregate per-window
        # into rollup *_total fields so the rolling artifact answers
        # "did cold-immediate fire across the soak?" in one read.
        _ci_sc = (extra_signal_counts or {})
        for _ci_k, _ci_total_k in (
            ("cold_immediate_sim_input_count", "cold_immediate_sim_input_total"),
            ("cold_immediate_sim_attempted", "cold_immediate_sim_attempted_total"),
            ("cold_immediate_sim_passed", "cold_immediate_sim_passed_total"),
            ("cold_immediate_sim_profitable", "cold_immediate_sim_profitable_total"),
        ):
            rollup[_ci_total_k] = int(rollup.get(_ci_total_k, 0) or 0) + int(
                _ci_sc.get(_ci_k, 0) or 0
            )
        # E1.27/D1: Store last N sim output samples (bounded) for offline
        # profit analysis. Raw bps cannot be derived because token decimals
        # differ between token_in/token_out for single-leg swaps.
        _samples = getattr(gate_result, "sim_output_samples", [])
        if _samples:
            _existing = rollup.get("sim_output_samples_recent", [])
            _combined = (_existing + _samples)[-50:]  # keep last 50
            rollup["sim_output_samples_recent"] = _combined
            rollup["sim_output_samples_total"] = (
                rollup.get("sim_output_samples_total", 0) + len(_samples)
            )
        # E2: Round-trip cumulative counters (VALID same-token bps)
        _rt_att = getattr(gate_result, "roundtrip_attempted", 0)
        _rt_suc = getattr(gate_result, "roundtrip_success", 0)
        _rt_prof = getattr(gate_result, "roundtrip_profitable_count", 0)
        _rt_bps = getattr(gate_result, "roundtrip_profit_bps_values", [])
        _rt_err = getattr(gate_result, "roundtrip_errors", [])
        rollup["roundtrip_attempted_total"] = rollup.get("roundtrip_attempted_total", 0) + _rt_att
        rollup["roundtrip_success_total"] = rollup.get("roundtrip_success_total", 0) + _rt_suc
        rollup["roundtrip_profitable_total"] = rollup.get("roundtrip_profitable_total", 0) + _rt_prof
        if _rt_bps:
            _all_rt = rollup.get("_roundtrip_profit_bps_all", []) + _rt_bps
            # Cap cumulative list to bound disk usage
            if len(_all_rt) > 500:
                _all_rt = _all_rt[-500:]
            rollup["_roundtrip_profit_bps_all"] = _all_rt
        # soak16 P0.2: Always re-filter best/worst/median from the cumulative
        # buffer so stale catastrophic-loss outliers (-9957) frozen from
        # pre-soak13 samples eventually disappear once the floor takes effect.
        try:
            _floor = float(os.environ.get("ARBY_RT_BPS_FLOOR", "-1000"))
        except (TypeError, ValueError):
            _floor = -1000.0
        _cumul_rt = rollup.get("_roundtrip_profit_bps_all") or []
        _clean_rt = [v for v in _cumul_rt if isinstance(v, (int, float)) and v >= _floor]
        if _clean_rt:
            rollup["roundtrip_profit_bps_best"] = round(max(_clean_rt), 4)
            rollup["roundtrip_profit_bps_worst"] = round(min(_clean_rt), 4)
            rollup["roundtrip_profit_bps_median"] = round(
                sorted(_clean_rt)[len(_clean_rt) // 2], 4
            )
            rollup["roundtrip_profit_bps_outliers_dropped"] = (
                len(_cumul_rt) - len(_clean_rt)
            )
        elif _cumul_rt:
            rollup["roundtrip_profit_bps_best"] = None
            rollup["roundtrip_profit_bps_worst"] = None
            rollup["roundtrip_profit_bps_median"] = None
            rollup["roundtrip_profit_bps_outliers_dropped"] = len(_cumul_rt)
        if _rt_err:
            _rt_hist = rollup.get("roundtrip_error_histogram", {})
            for _e in _rt_err:
                _rt_hist[_e[:100]] = _rt_hist.get(_e[:100], 0) + 1
            rollup["roundtrip_error_histogram"] = _rt_hist
        # E1.12.4: Record which simulation backend is active
        rollup["simulation_backend"] = getattr(gate_result, "simulation_backend", None)
        if gate_result.sim_blocker:
            rollup["sim_blocker"] = gate_result.sim_blocker
        # E1.12.3: Cumulative simulation error histogram — surfaces WHY sim fails
        # P0 (2026-04-20): truncation 80→256 to preserve full classification
        # tags and (when needed) longer raw revert substrings for diagnosis.
        _sim_hist = rollup.get("simulation_error_histogram") or {}
        for _se in getattr(gate_result, "sim_errors", []):
            _se_key = (_se or "unknown")[:256]
            _sim_hist[_se_key] = _sim_hist.get(_se_key, 0) + 1
        rollup["simulation_error_histogram"] = _sim_hist
        # M7.E1.34f post-soak19 reviewer fix #2: classify Tenderly /
        # external sim-provider failures (HTTP 403, 429,
        # insufficient_permissions, credit/quota) into a dedicated
        # bucket so reviewer can immediately see whether sim emptiness
        # is caused by external provider limits rather than code/market.
        _ext_hist = rollup.get("external_provider_blocker_histogram") or {}
        _ext_total_delta = 0
        for _se in getattr(gate_result, "sim_errors", []):
            _txt = (_se or "")
            _low = _txt.lower()
            _tag = None
            if "http 403" in _low or "insufficient_permissions" in _low:
                _tag = "TENDERLY:HTTP_403_INSUFFICIENT_PERMISSIONS"
            elif "http 429" in _low or "rate limit" in _low or "rate_limit" in _low:
                _tag = "PROVIDER:HTTP_429_RATE_LIMIT"
            elif "credit" in _low and ("limit" in _low or "exhaust" in _low or "quota" in _low):
                _tag = "TENDERLY:CREDIT_QUOTA"
            elif "insufficient_funds" in _low and "tenderly" in _low:
                _tag = "TENDERLY:INSUFFICIENT_FUNDS"
            if _tag is not None:
                _ext_hist[_tag] = _ext_hist.get(_tag, 0) + 1
                _ext_total_delta += 1
        if _ext_hist:
            rollup["external_provider_blocker_histogram"] = _ext_hist
        rollup["external_provider_blocker_total"] = (
            rollup.get("external_provider_blocker_total", 0) + _ext_total_delta
        )
        # M7.E1.34c: Terminal-stage failed-sim samples (bounded ring of 50) so
        # reviewer can see token/venue/amount behind each histogram bucket
        # (answers fix step #5 from 30m control soak).
        # M7.E1.34e fix #7: tag every sample with session_id +
        # sample_updated_at so reviewers can drop stale samples from
        # previous sessions when judging a fresh soak.
        _failed_samples = getattr(gate_result, "sim_failed_samples", [])
        if _failed_samples:
            _sid_now = getattr(_rio, "_SESSION_ID", None)
            _now_iso = ts
            for _s in _failed_samples:
                if isinstance(_s, dict):
                    _s.setdefault("session_id", _sid_now)
                    _s["sample_updated_at"] = _now_iso
            _existing_f = rollup.get("sim_failed_samples_recent", [])
            # M7.E1.34h fix #7: prune ring to current session_id before
            # appending so stale samples from previous child sessions
            # cannot contaminate fresh-soak diagnosis.
            _existing_f = [
                _x for _x in _existing_f
                if isinstance(_x, dict) and _x.get("session_id") == _sid_now
            ]
            rollup["sim_failed_samples_recent"] = (_existing_f + _failed_samples)[-50:]
            rollup["sim_failed_samples_total"] = (
                rollup.get("sim_failed_samples_total", 0) + len(_failed_samples)
            )
        # E1.12.3: Cumulative submit blocker histogram — surfaces WHY submit blocked
        _sub_hist = rollup.get("submit_blocker_histogram") or {}
        for _sb in getattr(gate_result, "submit_blockers_detail", []):
            _sb_key = (_sb or "unknown")[:256]
            _sub_hist[_sb_key] = _sub_hist.get(_sb_key, 0) + 1
        rollup["submit_blocker_histogram"] = _sub_hist
        # M7.E1.34f post-soak19 reviewer fix #6: ring-buffer
        # PRE_SIM_SKIP samples (currently MISSING_SIZE_METADATA only) so
        # reviewer can target upstream sizing for specific pools/pairs.
        _pre_skip_samples = list(getattr(gate_result, "pre_sim_skip_samples", []) or [])
        if _pre_skip_samples:
            _sid_now = getattr(_rio, "_SESSION_ID", None)
            _now_iso = ts
            for _s in _pre_skip_samples:
                if isinstance(_s, dict):
                    _s.setdefault("session_id", _sid_now)
                    _s["sample_updated_at"] = _now_iso
            _existing_p = rollup.get("pre_sim_skip_samples_recent", [])
            _existing_p = [
                _x for _x in _existing_p
                if isinstance(_x, dict) and _x.get("session_id") == _sid_now
            ]
            rollup["pre_sim_skip_samples_recent"] = (_existing_p + _pre_skip_samples)[-50:]
            rollup["pre_sim_skip_samples_total"] = (
                rollup.get("pre_sim_skip_samples_total", 0) + len(_pre_skip_samples)
            )

        # Reviewer post-soak21 P0: ring-buffer SCORER_SIM_DIVERGENCE
        # reproducer samples so reviewer can replay each divergence
        # offline (pool/pair/fee/direction/amount/decimals + raw wei).
        _sid_now2 = getattr(_rio, "_SESSION_ID", None)
        _existing_d = rollup.get("scorer_sim_divergence_samples_recent", [])
        _existing_d = [
            _x for _x in _existing_d
            if isinstance(_x, dict) and _x.get("session_id") == _sid_now2
        ]
        rollup["scorer_sim_divergence_samples_recent"] = _existing_d[-50:]
        rollup["scorer_sim_divergence_samples_total"] = int(
            rollup.get("scorer_sim_divergence_samples_total", 0) or 0
        )

        _div_samples = list(getattr(gate_result, "scorer_sim_divergence_samples", []) or [])
        if _div_samples:
            _now_iso2 = ts
            for _s in _div_samples:
                if isinstance(_s, dict):
                    _s.setdefault("session_id", _sid_now2)
                    _s["sample_updated_at"] = _now_iso2
            rollup["scorer_sim_divergence_samples_recent"] = (
                _existing_d + _div_samples
            )[-50:]
            rollup["scorer_sim_divergence_samples_total"] = (
                rollup.get("scorer_sim_divergence_samples_total", 0) + len(_div_samples)
            )
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
        if _ept.get("pool_address") != _TARGET_POOL or _prev_sid != _rio._SESSION_ID:
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
    if _eft.get("family") != _target_family or _prev_sid != _rio._SESSION_ID:
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
    if _prev_sid != _rio._SESSION_ID:
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

    # Reviewer post-soak21 fix #4 (PARTIAL → FULL): rollup-level latency_budget.
    # Maintain a bounded session ring of ``quote_pipeline_latency_ms`` samples
    # (capped at 500) so percentiles reflect cumulative hot-path behaviour
    # rather than only the last window. Reset on session change.
    try:
        _RING_CAP = 500
        _lb_ring_key = "_latency_budget_samples_ring"
        if _prev_sid != _rio._SESSION_ID:
            rollup[_lb_ring_key] = []
        _ring = rollup.get(_lb_ring_key) or []
        for _r in _fast:
            _v = getattr(_r, "quote_pipeline_latency_ms", None)
            if _v is not None:
                try:
                    _ring.append(float(_v))
                except Exception:
                    continue
        if len(_ring) > _RING_CAP:
            _ring = _ring[-_RING_CAP:]
        rollup[_lb_ring_key] = _ring

        try:
            _lb_target_r = float(os.getenv("ARBY_LATENCY_TARGET_MS", "200"))
        except Exception:
            _lb_target_r = 200.0

        def _pct_r(seq, p):
            if not seq:
                return None
            idx = min(len(seq) - 1, int(len(seq) * p))
            return round(seq[idx], 2)

        _sorted = sorted(_ring)
        _within_pct = None
        if _sorted:
            _within = sum(1 for v in _sorted if v <= _lb_target_r)
            _within_pct = round(_within / len(_sorted) * 100.0, 2)

        # Inline per-window stage breakdown for rollup (mean/max per stage),
        # mirrors the per-iteration ``_stage_agg`` calculation in
        # ``_write_hot_artifact``. Reflects this window only; cumulative
        # ring is intentionally limited to total latency for memory budget.
        _stage_keys_r = [
            "registry_lookup_ms", "pool_state_ms", "local_math_ms",
            "profit_guard_ms", "tx_build_ms", "calldata_ms",
            "sign_or_bundle_prep_ms",
        ]
        _stage_breakdown_r: dict = {}
        for _sk in _stage_keys_r:
            _vals = []
            for _r in _fast:
                _stages = getattr(_r, "pipeline_stage_latency_ms", None)
                if _stages and _sk in _stages:
                    try:
                        _vals.append(float(_stages.get(_sk, 0)))
                    except Exception:
                        continue
            if _vals:
                _stage_breakdown_r[f"mean_{_sk}"] = round(sum(_vals) / len(_vals), 2)
                _stage_breakdown_r[f"max_{_sk}"] = round(max(_vals), 2)

        rollup["latency_budget"] = {
            "samples_total": len(_sorted),
            "p50_ms": _pct_r(_sorted, 0.50),
            "p90_ms": _pct_r(_sorted, 0.90),
            "p99_ms": _pct_r(_sorted, 0.99),
            "max_ms": round(_sorted[-1], 2) if _sorted else None,
            "target_ms": _lb_target_r,
            "within_target_pct": _within_pct,
            "stage_breakdown": _stage_breakdown_r if _stage_breakdown_r else None,
        }
    except Exception:
        rollup["latency_budget"] = {
            "samples_total": 0,
            "p50_ms": None,
            "p90_ms": None,
            "p99_ms": None,
            "max_ms": None,
            "target_ms": 200.0,
            "within_target_pct": None,
            "stage_breakdown": None,
        }

    # E1.42 Iter 3 — derived rate metrics (cumulative across the session).
    # Always computed, even when zero, so reviewers can classify a soak
    # window as "market_quiet" vs "scoring_blackhole" vs "active" without
    # ad-hoc math. Uses cumulative session counters; for short windows
    # the rates are noisy by construction — that is intentional, since
    # the metric exists to expose statistical insufficiency.
    # The helper below subtracts rate_baseline; do not divide lifetime totals
    # by this worker's elapsed time.
    try:
        rollup["rate_metrics"] = _compute_rate_metrics(rollup)
    except Exception as exc:
        logger.debug("rate_metrics computation failed: %s", str(exc)[:120])

    try:
        _atomic_json_write(_rio._HOT_ROLLUP_PATH, rollup, indent=2, default=str)
    except Exception as exc:
        logger.debug("Failed to write hot rollup: %s", str(exc)[:80])


def _flush_rollup_at_path(
    path: str,
    chain: str,
    is_supervisor_exit: bool,
) -> None:
    """E1.45 helper: flush a single rollup path atomically.

    Extracted so ``mark_supervisor_end`` can refresh both PROD and
    DISC rollups in one supervisor-exit hook (DISC parity for the
    rate_metrics shutdown write-through landed in E1.44).
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rollup: dict = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                rollup = json.load(f)
    except Exception:
        rollup = {}
    if not isinstance(rollup, dict):
        return
    rollup["last_heartbeat_utc"] = ts
    rollup["last_updated"] = ts
    rollup["shutdown_flush_at"] = ts
    if is_supervisor_exit:
        rollup["supervisor_end_utc"] = ts
    else:
        # E1.46 reviewer fix #3: count clean per-child exits at the
        # rollup level so the reviewer can FAIL with
        # ``NO_HOT_CYCLE_COMPLETED_DURING_SOAK`` when hot writes happen
        # but no child ever finished its cycle cleanly (supervisor
        # cycles_completed stays 0). The supervisor itself increments
        # its own counter on rc==0 exits; mirroring it here makes the
        # signal visible in the reviewer summary.
        rollup["clean_child_exits_total"] = (
            int(rollup.get("clean_child_exits_total", 0) or 0) + 1
        )
        rollup["last_clean_child_exit_at"] = ts
    rollup.setdefault("chain", chain)
    # E1.51 slice-3c: surface registry counters at every shutdown flush
    # so each clean child exit refreshes the ``pool_price_state`` block
    # even if the child never reached _update_hot_rollup.
    try:
        from m7.orderflow.pool_price_state import get_registry as _ps_get_registry
        _ps_reg = _ps_get_registry()
        _ps_counters = _ps_reg.counters()
        rollup["pool_price_state"] = {
            "updates_total": int(_ps_counters.get("updates_total", 0)),
            "v2_updates_total": int(_ps_counters.get("v2_updates_total", 0)),
            "decode_errors_total": int(_ps_counters.get("decode_errors_total", 0)),
            "v2_decode_errors_total": int(_ps_counters.get("v2_decode_errors_total", 0)),
            "stale_drops_total": int(_ps_counters.get("stale_drops_total", 0)),
            "v2_stale_drops_total": int(_ps_counters.get("v2_stale_drops_total", 0)),
            "pools_tracked": _ps_reg.pools_tracked(),
        }
    except Exception:
        pass
    try:
        rollup["rate_metrics"] = _compute_rate_metrics(rollup)
    except Exception as exc:
        logger.debug("rate_metrics shutdown refresh failed: %s", str(exc)[:120])
    try:
        _atomic_json_write(path, rollup, indent=2, default=str)
    except Exception as exc:
        logger.debug("Failed to flush hot rollup at shutdown: %s", str(exc)[:80])


def flush_rollup_shutdown(
    chain: str = "arbitrum_one",
    is_supervisor_exit: bool = False,
) -> None:
    """M7.E1.34h fix #6: stamp rollup with shutdown-flush timestamps.

    Called by loop_runner when the supervisor-managed child process
    exits cleanly (per-cycle clean exit). Writes ``last_heartbeat_utc``
    / ``last_updated`` / ``shutdown_flush_at`` = now() so the reviewer
    staleness gate sees a fresh rollup at supervisor end instead of
    the last mid-cycle stamp. No counters are mutated.

    Reviewer post-1h-soak fix: ``supervisor_end_utc`` is no longer
    stamped here by default \u2014 child clean-exits happen every cycle
    (~50s), and stamping ``supervisor_end_utc`` then mis-anchors the
    reviewer's staleness window early in the run. Pass
    ``is_supervisor_exit=True`` from the actual supervisor exit hook
    (``mark_supervisor_end``) when the runtime is truly shutting down.

    Operates on the currently bound ``_rio._HOT_ROLLUP_PATH``
    (profile-aware) so child loop_runner exits flush their own lane.
    """
    _flush_rollup_at_path(
        path=_rio._HOT_ROLLUP_PATH,
        chain=chain,
        is_supervisor_exit=is_supervisor_exit,
    )


def mark_supervisor_end(chain: str = "arbitrum_one") -> None:
    """Reviewer post-1h-soak fix: explicit supervisor-exit hook.

    E1.45: Refreshes BOTH the production and discovery rollups so the
    reviewer's DISC rate_metrics block also lands with the current
    schema (rate_basis + delta keys) at supervisor exit. Without this
    the DISC rollup would only refresh when m7_hot_discovery completes
    a cycle in-process \u2014 which is unreliable under drpc 429 storms.

    Resolves the discovery sibling path from the currently bound
    ``_rio._HOT_ROLLUP_PATH`` (so unit tests that monkeypatch the path
    keep working) by toggling the ``_discovery`` filename suffix.
    """
    bound = _rio._HOT_ROLLUP_PATH
    # Flush the currently bound path (preserves existing test contracts).
    _flush_rollup_at_path(path=bound, chain=chain, is_supervisor_exit=True)
    # Flush the sibling lane (production <-> discovery toggle on filename).
    base_dir = os.path.dirname(bound)
    fname = os.path.basename(bound)
    stem, ext = os.path.splitext(fname)
    if stem.endswith("_discovery"):
        sibling_stem = stem[: -len("_discovery")]
    else:
        sibling_stem = stem + "_discovery"
    sibling = os.path.join(base_dir, sibling_stem + ext)
    if sibling != bound and os.path.exists(sibling):
        _flush_rollup_at_path(path=sibling, chain=chain, is_supervisor_exit=True)


# ---------------------------------------------------------------------------
# E1.49 — Periodic mid-cycle heartbeat (speed-audit reviewer fix #3)
# ---------------------------------------------------------------------------
#
# Reviewer 30m soak verdict (2026-04-30): hot lane completes only 1 cycle
# in ~7 minutes when ws_timeout=600 and the WS provider 429-throttles. The
# rollup is only updated on iteration boundaries, so reviewers see stale
# `last_updated` even when the WS recv loop is alive and reconnecting.
#
# This helper writes a lightweight, additive-only heartbeat that:
#   - bumps `last_heartbeat_utc` and `last_periodic_heartbeat_at`
#   - stamps `cycle_window_started_at` (first call of a cycle)
#   - stamps `cycle_window_elapsed_s` (wall seconds since cycle start)
#   - stamps `last_hot_write_at` (every call)
# without mutating session counters or invariant baselines. It is safe to
# call many times per cycle.
def heartbeat_hot_rollup_cycle(
    cycle_started_monotonic: float,
    chain: str = "arbitrum_one",
) -> None:
    """E1.49: Mid-cycle heartbeat with cycle-elapsed telemetry.

    Designed to be called from inside the WS recv loop every
    ``ARBY_HOT_HEARTBEAT_INTERVAL_S`` seconds (default 30s). The caller
    is responsible for rate-limiting; this function does NOT throttle
    itself so unit tests can assert each call's effect deterministically.

    Parameters
    ----------
    cycle_started_monotonic
        ``time.monotonic()`` snapshot taken when the current hot cycle
        began. Used to compute ``cycle_window_elapsed_s``.
    chain
        Chain label (mirrors ``flush_rollup_shutdown``).
    """
    import time as _t  # local to avoid touching module-level imports
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = _rio._HOT_ROLLUP_PATH
    rollup: dict = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                rollup = json.load(f)
    except Exception:
        rollup = {}
    if not isinstance(rollup, dict):
        return

    elapsed_s = max(0.0, _t.monotonic() - cycle_started_monotonic)
    rollup["last_heartbeat_utc"] = ts
    rollup["last_periodic_heartbeat_at"] = ts
    rollup["last_hot_write_at"] = ts
    rollup.setdefault("cycle_window_started_at", ts)
    rollup["cycle_window_elapsed_s"] = round(elapsed_s, 2)
    rollup.setdefault("chain", chain)
    rollup["periodic_heartbeats_total"] = (
        int(rollup.get("periodic_heartbeats_total", 0) or 0) + 1
    )
    # E1.51 slice-3c: surface registry counters in heartbeat path too,
    # so even cycles that never reach _update_hot_rollup expose the
    # ``pool_price_state`` block for canary verification.
    try:
        from m7.orderflow.pool_price_state import get_registry as _ps_get_registry
        _ps_reg = _ps_get_registry()
        _ps_counters = _ps_reg.counters()
        rollup["pool_price_state"] = {
            "updates_total": int(_ps_counters.get("updates_total", 0)),
            "v2_updates_total": int(_ps_counters.get("v2_updates_total", 0)),
            "decode_errors_total": int(_ps_counters.get("decode_errors_total", 0)),
            "v2_decode_errors_total": int(_ps_counters.get("v2_decode_errors_total", 0)),
            "stale_drops_total": int(_ps_counters.get("stale_drops_total", 0)),
            "v2_stale_drops_total": int(_ps_counters.get("v2_stale_drops_total", 0)),
            "pools_tracked": _ps_reg.pools_tracked(),
        }
    except Exception:
        pass
    try:
        _atomic_json_write(path, rollup, indent=2, default=str)
    except Exception as exc:
        logger.debug("Failed to write periodic heartbeat: %s", str(exc)[:80])


def reset_cycle_window_marker(chain: str = "arbitrum_one") -> None:
    """E1.49: Stamp a fresh ``cycle_window_started_at`` at iteration start.

    Called by ``loop_runner`` at the top of each hot iteration so that the
    next periodic heartbeat anchors elapsed-seconds against the correct
    cycle (not the previous cycle's start).
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = _rio._HOT_ROLLUP_PATH
    rollup: dict = {}
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                rollup = json.load(f)
    except Exception:
        rollup = {}
    if not isinstance(rollup, dict):
        return
    rollup["cycle_window_started_at"] = ts
    rollup["cycle_window_elapsed_s"] = 0.0
    rollup.setdefault("chain", chain)
    try:
        _atomic_json_write(path, rollup, indent=2, default=str)
    except Exception as exc:
        logger.debug("Failed to reset cycle marker: %s", str(exc)[:80])

