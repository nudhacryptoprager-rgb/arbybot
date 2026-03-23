"""
strategy/chain_stats.py - Per-chain statistics accumulation and classification.

Extracted from start.py (R33). Manages per-chain aggregation of run results,
blocker evidence computation, and run classification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# R28.17: Sane bounds for roundtrip PnL — values outside this range indicate
# accounting contamination (mixed-source quotes, decimal mismatch, garbage pools).
SANE_ROUNDTRIP_PNL_BPS_MAX = 500  # aligned with SUSPECT_ROUNDTRIP_OUTLIER_BPS
SANE_ROUNDTRIP_PNL_BPS_MIN = -500


def classify_run(exit_code: int, summary: dict[str, Any] | None) -> str:
    """Return PASS / NO_DATA / FAIL / INFRA_FAIL for a single run."""
    if summary is None:
        return "INFRA_FAIL"
    status = summary.get("status", "")
    if status == "PASS":
        return "PASS"
    if status == "NO_DATA":
        return "NO_DATA"
    return "FAIL"


def new_chain_stats() -> dict[str, Any]:
    return {
        "config": "",
        "runs": 0,
        "infra_pass": 0,
        "pass": 0,
        "no_data": 0,
        "fail": 0,
        "infra_fail": 0,
        "included_signals_total": 0,
        "net_usdc_total": 0.0,
        "profitable_roundtrips_total": 0,
        "roundtrip_evaluated_total": 0,
        # R28.10: Profit realism tracking for chain state classification
        "real_quote_count_total": 0,
        "last_profit_realism_status": None,
        "best_roundtrip_net_bps": None,
        "_suspect_accounting_count": 0,  # R28.17: contaminated PnL events
        "best_measured_spread_gap_bps": None,
        "sweep_best_net_pnl_bps": None,
        "sweep_best_size_usd": None,
        "sweep_best_pair": None,
        "sweep_gap_to_zero_bps": None,
        "sweep_measured_gas_bps": None,
        "sweep_measured_fee_bps": None,
        "sweep_measured_slippage_bps": None,
        "sweep_measured_total_cost_bps": None,
        "sweep_best_frontier_reason": None,  # R36: ALL_FAILED vs BEST_NEG vs PROFITABLE
        "last_run_timestamp": None,
        "last_run_dir": None,
        # Richer per-chain fields (last-run snapshot)
        "last_run_summary_status": None,
        "last_quality_status": None,
        "last_chain_quality_level": None,
        "last_profit_truth_available": None,
        "run_kind": None,
        "last_cross_dex_pairs_count": None,
        "last_quality_reasons": [],
        "accepted_fail": False,
        # R19: Blocker classification from config
        "blocker_classification": None,
        "blocker_reason": None,
        # R12: Frontier ranking metrics (robust selection)
        "_sweep_gap_values": [],  # for median computation
        "runs_with_sweep": 0,
        # R21: Per-chain drift tracking
        "_drift_rejection_rates": [],
        "_drift_median_bps_values": [],
        "drift_excluded_total": 0,
        "drift_pairs_with_data_total": 0,
        # R22: Worst drift pair (latest snapshot)
        "drift_worst_pair": None,
        "drift_worst_pair_bps": None,
        # R28.9: Phase timers for dashboard performance visibility
        "last_phase_timers_ms": None,
        # R28.11: Pair-level live snapshot for dashboard/operator view
        "last_current_block": None,
        "last_top_spread_signals": [],
        "last_live_candidates": [],
        # R28.11: Pair history — last N snapshots for delta tracking
        "_pair_history": [],  # list of {block, signals} dicts, max 5
        # R28.11: Cache freshness from discovery_runtime
        "last_pools_from_cache": None,
        "last_pools_from_rpc": None,
        "last_rpc_calls": None,
        # R28.11: Suppression counters from truth_report stats
        "last_suppression": None,
        # R28.11: Hot loop tracking
        "_run_counter": 0,
        "last_scan_mode": None,  # "full" or "hot"
        "hot_requote_count": 0,
        "full_sweep_count": 0,
        # R28.13: Micro-requote stats (in-process per-pair re-quotes)
        "micro_requote_count": 0,
        "micro_requote_quotes": 0,
        # R28.21: Cache freshness observability
        "last_full_refresh_utc": None,
        "last_hot_requote_utc": None,
        # R28.25: Filter funnel per-chain (last-run snapshot)
        "last_filter_funnel": None,
        # R28.25: Roundtrip truth status (separate from diagnostic profit_status)
        "last_roundtrip_truth_status": None,
        # R28.30: Accumulated funnel productivity counters (across all runs in window)
        "funnel_quotes_attempted_total": 0,
        "funnel_quotes_fetched_total": 0,
        "funnel_spread_signals_total": 0,
        "funnel_rt_evaluated_total": 0,
        "funnel_rt_real_quote_total": 0,
        # R32: Per-chain R31 artifact fields (last-run snapshot)
        "last_truth_verdict": None,
        "last_quote_source_summary": None,
        "last_oe_rejection_funnel": None,
        # R32: Auto-computed blocker from evidence (overrides config YAML when evidence exists)
        "blocker_evidence": None,
    }


def _compute_blocker_evidence(stats: dict[str, Any]) -> None:
    """Compute blocker_evidence from fresh per-chain data.

    taxonomy:
      ROUNDTRIP_PROFITABLE — at least 1 profitable RT
      OE_ECONOMICS — signals exist but OE rejects on NET_PROFIT_TOO_LOW (dominant)
      QUOTE_PATH_BLOCKED — high quoter_v2 failure rate (>50% failed)
      QUOTE_PATH_CONSTRAINED — no signals, limited surface (few cross-dex pairs)
      MIXED_SOURCE — OE rejects on MIXED_SOURCE (dominant)
      NO_SIGNAL — no spread signals produced
      INFRA_FAIL — chain consistently fails (>50% runs)
    """
    verdict = stats.get("last_truth_verdict")
    qss = stats.get("last_quote_source_summary") or {}
    oe_rf = stats.get("last_oe_rejection_funnel") or {}

    if stats.get("profitable_roundtrips_total", 0) > 0:
        stats["blocker_evidence"] = "ROUNDTRIP_PROFITABLE"
        return

    runs = stats.get("runs", 0)
    fail = stats.get("fail", 0)
    if runs > 0 and fail / runs > 0.5:
        stats["blocker_evidence"] = "INFRA_FAIL"
        return

    if stats.get("included_signals_total", 0) == 0 and runs > 0:
        # R37: Distinguish surface-constrained chains (few cross-dex pairs, no expansion)
        # from generic no-signal chains. This separates base (quote-path limited)
        # from chains that are genuinely signal-dry for other reasons.
        xdex = stats.get("last_cross_dex_pairs_count") or 0
        if xdex <= 3:
            stats["blocker_evidence"] = "QUOTE_PATH_CONSTRAINED"
            return
        stats["blocker_evidence"] = "NO_SIGNAL"
        return

    # R35: If sweep evidence is strong (routes swept, sweep PnL observed),
    # the quote path is working for active pairs — skip QUOTE_PATH_BLOCKED
    # and fall through to economics/rejection classification.
    has_sweep_evidence = stats.get("runs_with_sweep", 0) > 0

    # Check quote-path: high quoter_v2 failure rate
    exec_q = qss.get("quotes_fetched_executable", 0)
    diag_q = qss.get("quotes_fetched_diagnostic", 0)
    fail_q = qss.get("quoter_v2_failed_count", 0)
    total_q = exec_q + diag_q + fail_q
    if total_q > 0 and fail_q / total_q > 0.5 and not has_sweep_evidence:
        stats["blocker_evidence"] = "QUOTE_PATH_BLOCKED"
        return

    # Check OE rejection reasons
    rejected_reasons = oe_rf.get("rejected_reasons", {})
    total_rej = oe_rf.get("rejected_count", 0)

    # R33: SLOT0_DIAGNOSTIC dominance in OE means quoter_v2 not answering
    # for those pairs — this is a quote-path issue, not economics.
    if total_rej > 0:
        slot0_rej = rejected_reasons.get("SLOT0_DIAGNOSTIC", 0)
        if slot0_rej / total_rej > 0.4 and not has_sweep_evidence:
            stats["blocker_evidence"] = "QUOTE_PATH_BLOCKED"
            return

    if total_rej > 0:
        net_low = rejected_reasons.get("NET_PROFIT_TOO_LOW", 0)
        mixed = rejected_reasons.get("MIXED_SOURCE", 0)
        if net_low / total_rej > 0.4:
            stats["blocker_evidence"] = "OE_ECONOMICS"
            return
        if mixed / total_rej > 0.3:
            stats["blocker_evidence"] = "MIXED_SOURCE"
            return

    if verdict == "DIAGNOSTIC_PROFIT_ONLY":
        stats["blocker_evidence"] = "OE_ECONOMICS"
    elif verdict == "NO_PROFIT":
        stats["blocker_evidence"] = "NO_SIGNAL"


def update_chain_stats(
    stats: dict[str, Any],
    exit_code: int,
    run_dir: Path | None,
    summary: dict[str, Any] | None,
    gate_result: dict[str, Any] | None = None,
    scan_stats: dict[str, Any] | None = None,
    truth_report: dict[str, Any] | None = None,
) -> None:
    stats["runs"] += 1
    cls = classify_run(exit_code, summary)
    stats[cls.lower()] = stats.get(cls.lower(), 0) + 1
    if exit_code == 0:
        stats["infra_pass"] += 1

    if summary:
        metrics = summary.get("metrics", {})
        stats["included_signals_total"] += metrics.get("included_signals_count", 0)
        stats["net_usdc_total"] += float(metrics.get("total_net_usdc", 0) or 0)
        rt = metrics.get("roundtrip", {}) or summary.get("roundtrip_summary", {})
        stats["profitable_roundtrips_total"] += int(rt.get("profitable_count", 0) or 0)
        stats["roundtrip_evaluated_total"] = stats.get("roundtrip_evaluated_total", 0) + int(rt.get("evaluated_count", 0) or 0)
        # R28.10: Accumulate real_quote_count and snapshot profit_realism_status
        stats["real_quote_count_total"] += int(rt.get("real_quote_count", 0) or 0)
        prs = metrics.get("profit_realism_status")
        if prs:
            stats["last_profit_realism_status"] = prs
        run_best = rt.get("best_net_pnl_bps")
        if run_best is not None:
            # R28.17: Guard against accumulating contaminated PnL values
            if SANE_ROUNDTRIP_PNL_BPS_MIN <= run_best <= SANE_ROUNDTRIP_PNL_BPS_MAX:
                prev = stats.get("best_roundtrip_net_bps")
                stats["best_roundtrip_net_bps"] = run_best if prev is None else max(prev, run_best)
            else:
                print(
                    f"[WARN] SUSPECT_ACCOUNTING: best_net_pnl_bps={run_best:.2f} outside sane range "
                    f"[{SANE_ROUNDTRIP_PNL_BPS_MIN}, {SANE_ROUNDTRIP_PNL_BPS_MAX}], skipping"
                )
                stats["_suspect_accounting_count"] = stats.get("_suspect_accounting_count", 0) + 1
        run_gap = rt.get("best_measured_spread_gap_bps")
        if run_gap is not None:
            prev_gap = stats.get("best_measured_spread_gap_bps")
            stats["best_measured_spread_gap_bps"] = run_gap if prev_gap is None else max(prev_gap, run_gap)
        sweep = rt.get("dynamic_sweep", {})
        sweep_pnl = sweep.get("best_net_pnl_bps") or sweep.get("sweep_best_net_pnl_bps")
        if sweep_pnl is not None:
            # R12: collect gap for median computation
            gap = sweep.get("gap_to_zero_bps")
            if gap is not None:
                stats["_sweep_gap_values"].append(gap)
                stats["runs_with_sweep"] = stats.get("runs_with_sweep", 0) + 1
            prev_sweep = stats.get("sweep_best_net_pnl_bps")
            if prev_sweep is None or sweep_pnl > prev_sweep:
                stats["sweep_best_net_pnl_bps"] = sweep_pnl
                stats["sweep_best_size_usd"] = sweep.get("best_size_usd") or sweep.get("sweep_best_size_usd")
                stats["sweep_best_pair"] = sweep.get("best_pair") or sweep.get("frontier_pair")
                stats["sweep_gap_to_zero_bps"] = gap
                _gas = sweep.get("measured_gas_bps")
                stats["sweep_measured_gas_bps"] = _gas if _gas is not None else sweep.get("best_gas_bps")
                _fee = sweep.get("measured_fee_bps")
                stats["sweep_measured_fee_bps"] = _fee if _fee is not None else sweep.get("best_fee_bps")
                _slip = sweep.get("measured_slippage_bps")
                stats["sweep_measured_slippage_bps"] = _slip if _slip is not None else sweep.get("best_slippage_bps")
                _tcost = sweep.get("measured_total_cost_bps")
                stats["sweep_measured_total_cost_bps"] = _tcost if _tcost is not None else sweep.get("best_total_cost_bps")
                # R36: Track frontier_reason to distinguish ALL_FAILED (no quotes) from
                # BEST_NEG (genuine zero/negative) in downstream summary aggregation.
                stats["sweep_best_frontier_reason"] = (
                    sweep.get("best_frontier_reason")
                    or sweep.get("sweep_best_frontier_reason")
                )
        ctx = summary.get("run_context", {})
        stats["last_run_timestamp"] = ctx.get("run_timestamp", stats["last_run_timestamp"])
        # Richer snapshot fields
        stats["last_run_summary_status"] = summary.get("status")
        stats["last_quality_status"] = summary.get("quality_status")
        stats["last_chain_quality_level"] = metrics.get("chain_quality_level")
        stats["last_profit_truth_available"] = metrics.get("profit_truth_available")
        stats["run_kind"] = summary.get("run_kind", stats["run_kind"])
        # R28.9: Capture quality_reasons for gate PASS + run_summary FAIL disambiguation
        stats["last_quality_reasons"] = summary.get("quality_reasons", [])

        # R21: Per-chain drift tracking from run_summary
        drift = metrics.get("drift_summary", {})
        if drift:
            dr = drift.get("drift_rejection_rate")
            if dr is not None:
                stats["_drift_rejection_rates"].append(dr)
            med_bps = drift.get("signal_drift_median_bps") or drift.get("notional_drift_bps")
            if med_bps is not None:
                stats["_drift_median_bps_values"].append(med_bps)
            stats["drift_excluded_total"] += drift.get("drift_excluded_count", 0)
            stats["drift_pairs_with_data_total"] += drift.get("pairs_with_drift_data", 0)
            # R22: Worst drift pair snapshot (always latest)
            ppds = drift.get("per_pair_drift_summary", [])
            if ppds:
                stats["drift_worst_pair"] = ppds[0].get("pair")
                stats["drift_worst_pair_bps"] = ppds[0].get("notional_drift_median_bps")

    if gate_result:
        stats["last_cross_dex_pairs_count"] = gate_result.get("cross_dex_pairs_count")

    if run_dir:
        stats["last_run_dir"] = str(run_dir.name)

    # R24→R25: Discovery runtime coverage from scan_*.json stats (not run_summary)
    if scan_stats:
        dr = scan_stats.get("discovery_runtime")
        if dr and dr.get("pairs_evaluated", 0) > 0:
            stats["last_discovery_runtime"] = {
                "pairs_evaluated": dr.get("pairs_evaluated", 0),
                "pairs_resolved": dr.get("pairs_resolved", 0),
                "cross_dex_pairs_count": dr.get("cross_dex_pairs_count", 0),
                "pairs_skipped_no_tokens": dr.get("pairs_skipped_no_tokens", 0),
                "pairs_skipped_no_pool": dr.get("pairs_skipped_no_pool", 0),
                "pairs_skipped_single_dex": dr.get("pairs_skipped_single_dex", 0),
                "pairs_skipped_excluded": dr.get("pairs_skipped_excluded", 0),
            }
            # R28.11: Cache freshness from discovery_runtime
            stats["last_pools_from_cache"] = dr.get("pools_from_cache")
            stats["last_pools_from_rpc"] = dr.get("pools_from_rpc")
            stats["last_rpc_calls"] = dr.get("rpc_calls")
            # R28.21: Track last time this chain did a real RPC refresh
            if (dr.get("pools_from_rpc") or 0) > 0:
                stats["last_full_refresh_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # R28.9: Propagate phase_timers_ms for dashboard performance visibility
        pt = scan_stats.get("phase_timers_ms")
        if pt:
            stats["last_phase_timers_ms"] = pt

    # R28.11: Suppression counters from truth_report stats
    if truth_report:
        tr_stats = truth_report.get("stats") or {}
        drift_sum = truth_report.get("drift_summary") or {}
        dr_rt = (scan_stats or {}).get("discovery_runtime") or {}
        live_candidates = truth_report.get("live_candidate_stream") or tr_stats.get("live_candidate_stream")
        if isinstance(live_candidates, list):
            stats["last_live_candidates"] = live_candidates[:5]
        suppression = {
            "single_dex": dr_rt.get("pairs_skipped_single_dex", 0),
            "no_pool": tr_stats.get("pool_missing_count", 0),
            "excluded": dr_rt.get("pairs_skipped_excluded", 0),
            "price_sanity_failed": tr_stats.get("price_sanity_failed", 0),
            "notional_drift_excluded": drift_sum.get("drift_excluded_count", 0),
            "quarantined": tr_stats.get("quarantined_count", 0),
        }
        if any(v for v in suppression.values()):
            stats["last_suppression"] = suppression
        # R28.20: Propagate reject histogram from truth_report for long_scan RCA
        rh = truth_report.get("reject_histogram")
        if rh:
            stats["last_reject_histogram"] = rh

    if truth_report:
        stats["last_current_block"] = truth_report.get("current_block")
        top_signals = []
        for sig in (truth_report.get("spread_signals") or [])[:5]:
            top_signals.append({
                "pair": sig.get("pair"),
                "buy_dex": sig.get("buy_dex"),
                "sell_dex": sig.get("sell_dex"),
                "spread_bps": sig.get("spread_bps"),
                "effective_slippage_bps": sig.get("effective_slippage_bps"),
                "spread_minus_required_bps": sig.get("spread_minus_required_bps"),
            })
        stats["last_top_spread_signals"] = top_signals

        # R28.11: Pair history — keep last 5 snapshots for run-to-run delta
        if top_signals or stats["last_current_block"] is not None:
            history = stats["_pair_history"]
            history.append({
                "block": stats["last_current_block"],
                "signals": top_signals,
            })
            # Keep only last 5 entries
            if len(history) > 5:
                stats["_pair_history"] = history[-5:]

    # R32: Propagate R31 artifact fields per-chain
    if truth_report:
        qss = truth_report.get("quote_source_summary")
        if qss:
            stats["last_quote_source_summary"] = qss
        oe_rf = truth_report.get("oe_rejection_funnel")
        if oe_rf:
            stats["last_oe_rejection_funnel"] = oe_rf
    if summary:
        tv = summary.get("truth_verdict")
        if tv:
            stats["last_truth_verdict"] = tv

    # R32: Auto-compute blocker_evidence from fresh data
    _compute_blocker_evidence(stats)

    # R28.25: Propagate filter_funnel and roundtrip_truth_status from scan_stats
    if scan_stats:
        ff = scan_stats.get("filter_funnel")
        if ff:
            stats["last_filter_funnel"] = ff
            # R28.30: Accumulate funnel productivity counters
            stats["funnel_quotes_attempted_total"] += ff.get("quotes_attempted", 0)
            stats["funnel_quotes_fetched_total"] += ff.get("quotes_fetched", 0)
            stats["funnel_spread_signals_total"] += ff.get("spread_signals", 0)
            stats["funnel_rt_evaluated_total"] += ff.get("rt_evaluated", 0)
            stats["funnel_rt_real_quote_total"] += ff.get("rt_real_quote", 0)
        rts = scan_stats.get("roundtrip_truth_status")
        if rts:
            stats["last_roundtrip_truth_status"] = rts


def check_guardrails(per_chain: dict[str, dict[str, Any]]) -> list[str]:
    """Return list of warning strings for suspicious patterns."""
    warnings: list[str] = []
    total_runs = sum(s["runs"] for s in per_chain.values())
    total_pass = sum(s["pass"] for s in per_chain.values())
    total_fail = sum(s["fail"] for s in per_chain.values())
    total_no_data = sum(s["no_data"] for s in per_chain.values())

    if total_runs >= 5 and total_fail == 0 and total_no_data == 0:
        warnings.append(
            "ALL_POSITIVE: Every run PASS, zero FAIL/NO_DATA -- "
            "verify against Roadmap.md Truth Engine expectation"
        )

    for chain, s in per_chain.items():
        if s["runs"] >= 3 and s["pass"] > 0 and s["fail"] == 0 and s["no_data"] == 0:
            warnings.append(
                f"CHAIN_ALL_POSITIVE [{chain}]: {s['runs']} runs all PASS -- "
                "check if data quality is real"
            )
        if s["runs"] >= 3 and s["infra_fail"] > s["runs"] * 0.5:
            warnings.append(
                f"CHAIN_INFRA_UNSTABLE [{chain}]: >{50}% runs had infra failures"
            )

        # R28.11: Narrow probe path stability warning
        hist = s.get("_pair_history", [])
        if len(hist) >= 3:
            pairs_sets = [frozenset(sig.get("pair", "") for sig in h.get("signals", [])) for h in hist[-3:]]
            if all(ps == pairs_sets[0] for ps in pairs_sets) and len(pairs_sets[0]) > 0:
                warnings.append(
                    f"STATIC_PROBE_PATH [{chain}]: same top pairs across last {len(hist[-3:])} runs — "
                    "apparent stability may reflect narrow probe config, not market health"
                )

        # R28.11: Single 0-fee route dominance warning
        top_sigs = s.get("last_top_spread_signals", [])
        if top_sigs and all(
            (sig.get("spread_bps") or 0) == 0 and (sig.get("spread_minus_required_bps") or 0) == 0
            for sig in top_sigs
        ):
            warnings.append(
                f"ZERO_FEE_DOMINANCE [{chain}]: all top signals have 0 bps spread — "
                "likely single structural 0-fee route (e.g. lynex_v3); not market edge"
            )

    return warnings
