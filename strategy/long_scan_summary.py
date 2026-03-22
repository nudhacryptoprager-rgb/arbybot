"""
strategy/long_scan_summary.py - Long-scan summary builder and analytics.

Extracted from start.py (R33). Builds the long_scan_latest.json summary
from accumulated per-chain stats, including frontier ranking, drift analysis,
KPI separation, profit truth summary, and truth path alignment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from strategy.chain_stats import SANE_ROUNDTRIP_PNL_BPS_MAX, SANE_ROUNDTRIP_PNL_BPS_MIN

# Imported constant for hot_loop section in summary
FULL_SWEEP_INTERVAL = 5


def _roundtrip_accounting_is_sane(stats: dict[str, Any]) -> bool:
    """R28.17: Guard against contaminated roundtrip accounting.

    Returns False if best_roundtrip_net_bps is outside sane bounds,
    or if suspect accounting events were recorded during accumulation.
    """
    best = stats.get("best_roundtrip_net_bps")
    if best is not None and not (SANE_ROUNDTRIP_PNL_BPS_MIN <= best <= SANE_ROUNDTRIP_PNL_BPS_MAX):
        return False
    if stats.get("_suspect_accounting_count", 0) > 0:
        return False
    return True


def classify_chain_profit_state(stats: dict[str, Any]) -> str:
    """R28.10/R28.17: Derive chain profit state from accumulated per-chain metrics.

    States (ordered by strength):
      CONFIRMED_POSITIVE_CONTROL - profitable RT with repeated real quotes AND sane accounting
      THIN_POSITIVE              - profitable RT exists but evidence thin or accounting suspect
      PRIMARY_BLOCKER            - RT evaluated with real quotes but none profitable
      SUSPECT_ACCOUNTING         - profitable RT reported but accounting is outside sane bounds
      CANDIDATE                  - runs exist but no roundtrip evaluation yet
      PROBE_ONLY                 - no runs or no meaningful data
    """
    profitable = stats.get("profitable_roundtrips_total", 0)
    evaluated = stats.get("roundtrip_evaluated_total", 0)
    rq_total = stats.get("real_quote_count_total", 0)
    runs = stats.get("runs", 0)
    sane = _roundtrip_accounting_is_sane(stats)
    # R28.18: Strict promotion guard — block CONFIRMED when evidence is diagnostic-only or quality FAIL
    last_prs = stats.get("last_profit_realism_status")
    last_qs = stats.get("last_quality_status")

    if profitable > 0 and not sane:
        return "SUSPECT_ACCOUNTING"
    if profitable > 0 and rq_total >= 2:
        if last_prs == "ONE_LEG_ONLY_DIAGNOSTIC" or last_qs == "FAIL_QUALITY":
            return "THIN_POSITIVE"
        return "CONFIRMED_POSITIVE_CONTROL"
    if profitable > 0:
        return "THIN_POSITIVE"
    if evaluated > 0 and rq_total > 0:
        return "PRIMARY_BLOCKER"
    if runs > 0:
        return "CANDIDATE"
    return "PROBE_ONLY"


def _compute_median(values: list[float]) -> float | None:
    """Compute median of a list of floats."""
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def build_summary(
    per_chain: dict[str, dict[str, Any]],
    wall_seconds: float,
    warnings: list[str],
) -> dict[str, Any]:
    pass_chains = [c for c, s in per_chain.items() if s["runs"] > 0 and s["fail"] == 0 and s["infra_fail"] == 0 and s["pass"] > 0]
    fail_chains = [c for c, s in per_chain.items() if s["fail"] > 0 or s["infra_fail"] > 0]
    probe_only_chains = [c for c, s in per_chain.items() if s["runs"] > 0 and s["pass"] == 0 and s["fail"] == 0]
    accepted_fail_chains = [c for c in fail_chains if per_chain[c].get("accepted_fail")]
    unexpected_fail_chains = [c for c in fail_chains if not per_chain[c].get("accepted_fail")]

    # R12: Compute cross-chain gap percentile context
    all_gap_values = []
    total_sweep_runs = 0
    for s in per_chain.values():
        all_gap_values.extend(s.get("_sweep_gap_values", []))
        total_sweep_runs += s.get("runs_with_sweep", 0)
    gap_best = min(all_gap_values) if all_gap_values else None
    gap_median = _compute_median(all_gap_values)

    # R26: run_context with run_timestamp for SHA-free provenance policy
    now_utc = datetime.now(timezone.utc)
    run_ts = now_utc.isoformat().replace("+00:00", "Z")

    # R28.10: Classify chain profit state for each chain
    for chain, s in per_chain.items():
        s["chain_profit_state"] = classify_chain_profit_state(s)

    summary = {
        "schema": "start:long_scan_summary:v1.14",  # R28.21: cache freshness observability
        "generated_at": run_ts,
        "run_context": {
            "run_timestamp": run_ts,
            "code_identity": f"ts:{run_ts}",
            "code_sha": None,
            "evidence_sha": None,
        },
        "wall_seconds": round(wall_seconds, 1),
        "total_runs": sum(s["runs"] for s in per_chain.values()),
        "total_pass": sum(s["pass"] for s in per_chain.values()),
        "total_no_data": sum(s["no_data"] for s in per_chain.values()),
        "total_fail": sum(s["fail"] for s in per_chain.values()),
        "total_infra_fail": sum(s["infra_fail"] for s in per_chain.values()),
        "total_included_signals": sum(s["included_signals_total"] for s in per_chain.values()),
        "total_net_usdc": round(sum(s["net_usdc_total"] for s in per_chain.values()), 4),
        "total_profitable_roundtrips": sum(s["profitable_roundtrips_total"] for s in per_chain.values()),
        "total_roundtrip_evaluated": sum(s.get("roundtrip_evaluated_total", 0) for s in per_chain.values()),
        "best_roundtrip_net_bps": max(
            (s["best_roundtrip_net_bps"] for s in per_chain.values() if s.get("best_roundtrip_net_bps") is not None),
            default=None,
        ),
        "best_measured_spread_gap_bps": max(
            (s["best_measured_spread_gap_bps"] for s in per_chain.values() if s.get("best_measured_spread_gap_bps") is not None),
            default=None,
        ),
        "sweep_best_net_pnl_bps": max(
            (s["sweep_best_net_pnl_bps"] for s in per_chain.values() if s.get("sweep_best_net_pnl_bps") is not None),
            default=None,
        ),
        "sweep_best_size_usd": next(
            (
                s["sweep_best_size_usd"]
                for s in sorted(per_chain.values(), key=lambda x: x.get("sweep_best_net_pnl_bps") or -9999, reverse=True)
                if s.get("sweep_best_size_usd") is not None
            ),
            None,
        ),
        # R12: Gap percentile context for frontier analysis
        "gap_percentile_context": {
            "best_gap_to_zero_bps": round(gap_best, 4) if gap_best is not None else None,
            "median_gap_to_zero_bps": round(gap_median, 4) if gap_median is not None else None,
            "runs_with_sweep": total_sweep_runs,
            "sweep_values_count": len(all_gap_values),
        },
        "pass_chains": pass_chains,
        "fail_chains": fail_chains,
        "accepted_fail_chains": accepted_fail_chains,
        "unexpected_fail_chains": unexpected_fail_chains,
        "probe_only_chains": probe_only_chains,
        "per_chain": per_chain,
        "warnings": warnings,
        "frontier_ranking": _compute_frontier_ranking(per_chain),
        # R21: Top-level per-chain drift summary (extracted from per_chain stats)
        "per_chain_drift_summary": _compute_per_chain_drift_summary(per_chain),
        # R21: Explicit discovery vs truth-probe universe split
        "universe_split": _compute_universe_split(per_chain, pass_chains, fail_chains),
        # R28.10: Strict KPI separation — signals vs executable vs profitable vs truth
        "kpi_separation": _compute_kpi_separation(per_chain),
        # R28.10: Profit truth summary — chain_profit_state rollup
        "profit_truth_summary": _compute_profit_truth_summary(per_chain),
        # R28.9: Live batch state for dashboard visibility
        "batch_state": {
            "chains_total": len(per_chain),
            "chains_with_runs": sum(1 for s in per_chain.values() if s["runs"] > 0),
            "last_completed_chain": next(
                (c for c in reversed(list(per_chain)) if per_chain[c]["runs"] > 0),
                None,
            ),
            "last_summary_write": run_ts,
        },
        # R28.11: Hot loop metrics — full sweep vs hot re-quote cycle counts
        "hot_loop": {
            "full_sweep_interval": FULL_SWEEP_INTERVAL,
            "total_full_sweeps": sum(s.get("full_sweep_count", 0) for s in per_chain.values()),
            "total_hot_requotes": sum(s.get("hot_requote_count", 0) for s in per_chain.values()),
            "per_chain_mode": {
                c: {
                    "last_scan_mode": s.get("last_scan_mode"),
                    "full_sweeps": s.get("full_sweep_count", 0),
                    "hot_requotes": s.get("hot_requote_count", 0),
                    # R28.21: Cache freshness observability
                    "last_full_refresh_utc": s.get("last_full_refresh_utc"),
                    "last_hot_requote_utc": s.get("last_hot_requote_utc"),
                    "pools_from_cache": s.get("last_pools_from_cache"),
                    "pools_from_rpc": s.get("last_pools_from_rpc"),
                }
                for c, s in per_chain.items()
            },
        },
        # R28.12: Truth path alignment — makes static-probe exceptions visible
        "truth_path_alignment": None,  # filled below
        # R28.14: Benchmark chain — strongest ALIGNED chain by merit
        "benchmark_chain": None,  # filled below
    }
    _tpa, _bench = _compute_truth_path_alignment(per_chain)
    summary["truth_path_alignment"] = _tpa
    summary["benchmark_chain"] = _bench
    return summary


def _compute_truth_path_alignment(per_chain: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], str | None]:
    """R28.14: Compute truth path alignment for all chains.

    Shows BOTH profit truth AND operational quality in one view, so the
    operator never sees a misleading ``POSITIVE + fail_chain`` without
    explanation.

    alignment values:
      ALIGNED        — profit proven + quality healthy (no fails)
      POSITIVE       — profitable roundtrips exist but quality has issues
      BLOCKED        — roundtrips evaluated with real quotes, none profitable
      NOT_PROVEN     — no real quote data or no runs yet
    """
    result: dict[str, Any] = {}
    for chain, s in per_chain.items():
        profit_state = s.get("chain_profit_state", "UNKNOWN")
        has_real_quotes = (s.get("real_quote_count_total", 0) or 0) > 0
        has_profitable_rt = (s.get("profitable_roundtrips_total", 0) or 0) > 0
        run_kind = "NORMAL" if s.get("config", "").endswith("real_minimal.yaml") else "COVERAGE"
        truth_mode = s.get("last_truth_mode", s.get("last_quality_level"))

        # R28.13: Operational quality — surface fail/pass alongside profit truth
        run_status = s.get("last_run_summary_status")
        quality_status = s.get("last_quality_status")
        fail_count = s.get("fail", 0) + s.get("infra_fail", 0)
        total_runs = s.get("runs", 0)
        quality_healthy = fail_count == 0 and total_runs > 0

        alignment = "ALIGNED"
        if profit_state == "PRIMARY_BLOCKER":
            alignment = "BLOCKED"
        elif profit_state == "CANDIDATE" or not has_real_quotes:
            alignment = "NOT_PROVEN"
        elif has_profitable_rt:
            # R28.13: Distinguish ALIGNED (profit + quality) from POSITIVE (profit only)
            alignment = "ALIGNED" if quality_healthy else "POSITIVE"

        result[chain] = {
            "run_kind": run_kind,
            "profit_state": profit_state,
            "has_real_quotes": has_real_quotes,
            "has_profitable_rt": has_profitable_rt,
            "alignment": alignment,
            "truth_mode": truth_mode,
            # R28.13: Operational quality context (Step 2 — no hidden contradictions)
            "run_status": run_status,
            "quality_status": quality_status,
            "quality_healthy": quality_healthy,
            "real_quote_count": s.get("real_quote_count_total", 0),
            "profitable_roundtrips": s.get("profitable_roundtrips_total", 0),
            "best_net_pnl_bps": s.get("best_roundtrip_net_bps"),
            "gap_to_zero_bps": s.get("sweep_gap_to_zero_bps"),
        }

    # R28.14: Identify benchmark chain — strongest ALIGNED chain by merit
    aligned_chains = [
        (ch, info) for ch, info in result.items()
        if info["alignment"] == "ALIGNED"
    ]
    benchmark_chain = None
    if aligned_chains:
        # Sort by profitable_roundtrips desc, then gap_to_zero_bps asc (lower is better)
        aligned_chains.sort(
            key=lambda x: (
                -(x[1].get("profitable_roundtrips") or 0),
                x[1].get("gap_to_zero_bps") if x[1].get("gap_to_zero_bps") is not None else 9999,
            )
        )
        benchmark_chain = aligned_chains[0][0]

    # R28.14: Unified truth standard fields per chain
    for ch, info in result.items():
        info["truth_standard_met"] = (
            info["alignment"] in ("ALIGNED", "POSITIVE")
            and info["has_real_quotes"]
            and (info.get("profitable_roundtrips") or 0) > 0
        )
        info["is_benchmark"] = ch == benchmark_chain

    return result, benchmark_chain


def _compute_per_chain_drift_summary(per_chain: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """R21: Build top-level per-chain drift summary from accumulated per-chain stats."""
    result = {}
    for chain, s in per_chain.items():
        drift_rates = s.get("_drift_rejection_rates", [])
        drift_bps_vals = s.get("_drift_median_bps_values", [])
        drift_rate_med = _compute_median(drift_rates)
        drift_bps_med = _compute_median(drift_bps_vals)
        result[chain] = {
            "drift_excluded_total": s.get("drift_excluded_total", 0),
            "drift_rejection_rate_median": round(drift_rate_med, 4) if drift_rate_med is not None else None,
            "notional_drift_median_bps": round(drift_bps_med, 1) if drift_bps_med is not None else None,
            "drift_pairs_with_data_total": s.get("drift_pairs_with_data_total", 0),
            "runs_sampled": len(drift_rates),
            # R22: Worst drift pair snapshot (from latest run)
            "drift_worst_pair": s.get("drift_worst_pair"),
            "drift_worst_pair_bps": s.get("drift_worst_pair_bps"),
        }
    return result


def _compute_universe_split(
    per_chain: dict[str, dict[str, Any]],
    pass_chains: list[str],
    fail_chains: list[str],
) -> dict[str, Any]:
    """R21: Compute explicit discovery vs truth-probe universe split."""
    discovery = []
    truth_probe = []
    monitoring_only = []
    for chain, s in per_chain.items():
        rk = s.get("run_kind")
        if s.get("accepted_fail", False):
            monitoring_only.append(chain)
        elif rk == "NORMAL":
            truth_probe.append(chain)
        else:
            discovery.append(chain)
    return {
        "discovery_chains": sorted(discovery),
        "truth_probe_chains": sorted(truth_probe),
        "monitoring_only_chains": sorted(monitoring_only),
        "total_chains": len(per_chain),
    }


def _compute_kpi_separation(per_chain: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """R28.10/R28.17: Three-tier signal classification per chain."""
    per_chain_kpi = {}
    totals = {"diagnostic_signals": 0, "real_quote_signals": 0, "executable_profitable": 0}
    for chain, s in per_chain.items():
        diagnostic = s.get("included_signals_total", 0)
        rq = s.get("real_quote_count_total", 0)
        profitable_rt = s.get("profitable_roundtrips_total", 0)
        sane = _roundtrip_accounting_is_sane(s)
        real_quote_sig = rq
        exec_profitable = profitable_rt if (sane and rq > 0) else 0
        per_chain_kpi[chain] = {
            "diagnostic_signals": diagnostic,
            "real_quote_signals": real_quote_sig,
            "executable_profitable": exec_profitable,
            "accounting_sane": sane,
            "real_quote_count": rq,
        }
        totals["diagnostic_signals"] += diagnostic
        totals["real_quote_signals"] += real_quote_sig
        totals["executable_profitable"] += exec_profitable
    return {"totals": totals, "per_chain": per_chain_kpi}


def _compute_profit_truth_summary(per_chain: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """R28.10/R28.17: Summarize chain profit state across all chains."""
    groups: dict[str, list[str]] = {}
    for chain, s in per_chain.items():
        state = s.get("chain_profit_state", "PROBE_ONLY")
        groups.setdefault(state, []).append(chain)

    promotion_eligible = sorted(groups.get("CONFIRMED_POSITIVE_CONTROL", []))
    primary_blockers = sorted(groups.get("PRIMARY_BLOCKER", []))
    thin_positive = sorted(groups.get("THIN_POSITIVE", []))
    suspect_accounting = sorted(groups.get("SUSPECT_ACCOUNTING", []))

    return {
        "chain_states": {state: sorted(chains) for state, chains in groups.items()},
        "promotion_eligible": promotion_eligible,
        "primary_blockers": primary_blockers,
        "thin_positive_needs_evidence": thin_positive,
        "suspect_accounting": suspect_accounting,
    }


# R33: Map auto-computed blocker_evidence to human-readable reason strings.
_BLOCKER_EVIDENCE_REASONS: dict[str | None, str | None] = {
    "ROUNDTRIP_PROFITABLE": None,  # not a blocker
    "OE_ECONOMICS": "Signals exist, all rejected by NET_PROFIT_TOO_LOW at probe size",
    "QUOTE_PATH_BLOCKED": "quoter_v2 failure rate or SLOT0_DIAGNOSTIC dominance too high",
    "MIXED_SOURCE": "OE rejects are dominated by MIXED_SOURCE (quoter_v2 on one leg only)",
    "NO_SIGNAL": "No spread signals produced",
    "INFRA_FAIL": "Chain consistently fails (>50% runs)",
}


def _blocker_evidence_reason(blocker_cls: str | None) -> str | None:
    return _BLOCKER_EVIDENCE_REASONS.get(blocker_cls)


def _compute_frontier_ranking(per_chain: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank chains by composite frontier score (R12→R22: robust multi-metric selection)."""
    ranked = []
    for chain, s in per_chain.items():
        gap = s.get("sweep_gap_to_zero_bps")
        pnl = s.get("sweep_best_net_pnl_bps")
        signals = s.get("included_signals_total", 0)
        xdex = s.get("last_cross_dex_pairs_count") or 0
        is_af = s.get("accepted_fail", False)
        runs_sweep = s.get("runs_with_sweep", 0)
        gap_values = s.get("_sweep_gap_values", [])
        median_gap = _compute_median(gap_values)
        if pnl is None and signals == 0:
            continue
        # R21: Per-chain drift aggregates
        drift_rates = s.get("_drift_rejection_rates", [])
        drift_bps_vals = s.get("_drift_median_bps_values", [])
        drift_rate_median = _compute_median(drift_rates)
        drift_bps_median = _compute_median(drift_bps_vals)
        # R26: Derive triage status from chain metrics
        chain_status = s.get("last_run_summary_status")
        chain_quality = s.get("last_chain_quality_level")
        # R33: Fall back to auto-computed blocker_evidence when config fields are null
        blocker_cls = s.get("blocker_classification") or s.get("blocker_evidence")
        blocker_rsn = s.get("blocker_reason") or _blocker_evidence_reason(blocker_cls)
        total_runs = s.get("runs", 0)
        pass_runs = s.get("pass", 0)
        route_health = round(pass_runs / total_runs, 4) if total_runs > 0 else None

        ranked.append({
            "chain": chain,
            "gap_to_zero_bps": gap,
            "median_gap_to_zero_bps": round(median_gap, 4) if median_gap is not None else None,
            "runs_with_sweep": runs_sweep,
            "sweep_best_net_pnl_bps": pnl,
            "sweep_best_size_usd": s.get("sweep_best_size_usd"),
            "frontier_pair": s.get("sweep_best_pair"),
            "measured_gas_bps": s.get("sweep_measured_gas_bps"),
            "measured_fee_bps": s.get("sweep_measured_fee_bps"),
            "measured_slippage_bps": s.get("sweep_measured_slippage_bps"),
            "measured_total_cost_bps": s.get("sweep_measured_total_cost_bps"),
            "included_signals_total": signals,
            "cross_dex_pairs_count": xdex,
            "accepted_fail": is_af,
            "frontier_ready": gap is not None and gap < 30 and not is_af,
            # R21: Per-chain drift summary in frontier ranking
            "drift_rejection_rate_median": round(drift_rate_median, 4) if drift_rate_median is not None else None,
            "notional_drift_median_bps": round(drift_bps_median, 1) if drift_bps_median is not None else None,
            "drift_excluded_total": s.get("drift_excluded_total", 0),
            "drift_pairs_with_data_total": s.get("drift_pairs_with_data_total", 0),
            # R22: Worst drift pair for operator analysis
            "drift_worst_pair": s.get("drift_worst_pair"),
            "drift_worst_pair_bps": s.get("drift_worst_pair_bps"),
            # R24: Discovery runtime coverage (latest snapshot)
            "discovery_coverage": s.get("last_discovery_runtime"),
            # R26: Triage fields for promotion decisions
            "status": chain_status,
            "route_health": route_health,
            "chain_quality_level": chain_quality,
            "blocker_classification": blocker_cls,
            "blocker_reason": blocker_rsn,
            # R28.10: Chain profit state and promotion eligibility
            "chain_profit_state": s.get("chain_profit_state"),
            "promotion_eligible": s.get("chain_profit_state") == "CONFIRMED_POSITIVE_CONTROL",
            # R28.13: Truth KPIs surfaced in frontier ranking (Step 5)
            "real_quote_count": s.get("real_quote_count_total", 0),
            "profitable_roundtrips": s.get("profitable_roundtrips_total", 0),
            "best_net_pnl_bps": s.get("best_roundtrip_net_bps"),
        })
    ranked.sort(key=lambda x: (
        x.get("accepted_fail", False),
        x.get("median_gap_to_zero_bps") if x.get("median_gap_to_zero_bps") is not None else 9999,
        x.get("gap_to_zero_bps") if x.get("gap_to_zero_bps") is not None else 9999,
        # R22: drift as secondary factor — lower drift = more reliable signal
        x.get("drift_rejection_rate_median") if x.get("drift_rejection_rate_median") is not None else 9999,
        -(x.get("runs_with_sweep", 0)),
        -(x.get("included_signals_total", 0)),
        -(x.get("cross_dex_pairs_count", 0)),
    ))
    # Annotate with rank, truth-probe target, and candidate score
    truth_probe_count = 0
    total_ranked = len(ranked)
    for i, entry in enumerate(ranked):
        entry["frontier_rank"] = i + 1
        entry["candidate_score"] = round(100.0 * (total_ranked - i) / max(total_ranked, 1), 2)
        if not entry.get("accepted_fail", False) and truth_probe_count < 2:
            entry["target_for_truth_probe"] = True
            truth_probe_count += 1
        else:
            entry["target_for_truth_probe"] = False
    return ranked
