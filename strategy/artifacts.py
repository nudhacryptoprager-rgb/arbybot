# PATH: strategy/artifacts.py
"""
Artifact writing and truth report building.

Extracted from run_scan_real.py for modularity.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

from core.constants import SCHEMA_VERSION, CURRENT_EXECUTION_BLOCKER
# v3.2.7: Atomic JSON writes for artifacts
from core.json_io import atomic_write_json
# v3.2.7: Path canonicalization for OS-independent artifacts
from core.no_data import canonicalize_config_path
from strategy.quarantine import get_quarantine_manager

# v2.0.4: Import canonical pool_key builder
from core.pool_keys import make_pool_key

logger = logging.getLogger("strategy.artifacts")


def _compute_per_dex_stats(
    quotes_sample: List[Dict[str, Any]],
    rejected_quotes: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    v3.2.19: Compute per-DEX promotion metrics for DEX safety decisions.
    
    Returns:
        Dict mapping dex_id -> {
            quotes_fetched: int,
            quotes_rejected: int,
            quotes_total: int,
            quote_success_rate: float,
            top_reject_reasons: List[str],  # Top 3 reasons
            health_status: str,  # HEALTHY/WARNING/CRITICAL
        }
    """
    per_dex: Dict[str, Dict[str, Any]] = {}
    
    # Count fetched quotes per DEX
    for q in quotes_sample:
        dex_id = q.get("dex_id", "unknown")
        if dex_id not in per_dex:
            per_dex[dex_id] = {
                "quotes_fetched": 0,
                "quotes_rejected": 0,
                "reject_reasons": {},
            }
        per_dex[dex_id]["quotes_fetched"] += 1
    
    # Count rejected quotes and reasons per DEX
    for r in rejected_quotes:
        dex_id = r.get("dex_id", "unknown")
        reason = r.get("reason", "UNKNOWN")
        if dex_id not in per_dex:
            per_dex[dex_id] = {
                "quotes_fetched": 0,
                "quotes_rejected": 0,
                "reject_reasons": {},
            }
        per_dex[dex_id]["quotes_rejected"] += 1
        per_dex[dex_id]["reject_reasons"][reason] = per_dex[dex_id]["reject_reasons"].get(reason, 0) + 1
    
    # Compute derived metrics
    results: Dict[str, Dict[str, Any]] = {}
    for dex_id, stats in per_dex.items():
        fetched = stats["quotes_fetched"]
        rejected = stats["quotes_rejected"]
        total = fetched + rejected
        
        # Quote success rate (0-1)
        success_rate = fetched / total if total > 0 else 0.0
        
        # Top 3 reject reasons
        reasons_sorted = sorted(
            stats["reject_reasons"].items(),
            key=lambda x: x[1],
            reverse=True
        )
        top_reasons = [r[0] for r in reasons_sorted[:3]]
        
        # Health status based on success rate
        # HEALTHY: >= 50% success, WARNING: 20-50%, CRITICAL: < 20%
        if success_rate >= 0.5:
            health_status = "HEALTHY"
        elif success_rate >= 0.2:
            health_status = "WARNING"
        else:
            health_status = "CRITICAL"
        
        results[dex_id] = {
            "quotes_fetched": fetched,
            "quotes_rejected": rejected,
            "quotes_total": total,
            "quote_success_rate": round(success_rate, 4),
            "top_reject_reasons": top_reasons,
            "health_status": health_status,
        }
    
    return results


def write_artifacts(
    output_dir: Path,
    timestamp: str,
    scan_data: Dict[str, Any],
    truth_data: Dict[str, Any],
    reject_data: Dict[str, Any],
    artifact_mode: str = "rolling",
    status: str = "PASS",
) -> Dict[str, Any]:
    """
    Write all artifacts with schema_version.
    
    Writes to output_dir/reports/ (PRIMARY - for ci_m5_0_gate.py).
    Also writes to output_dir/snapshots/ (LEGACY - backward compat).
    
    Returns:
        Dict mapping artifact names to paths
    """
    artifacts = {}
    # Ensure schema_version in all artifacts
    scan_data["schema_version"] = SCHEMA_VERSION
    truth_data["schema_version"] = SCHEMA_VERSION
    reject_data["schema_version"] = SCHEMA_VERSION

    if artifact_mode == "rolling" and status == "PASS":
        # In-memory only: return dicts, do not write files
        artifacts["scan"] = scan_data
        artifacts["truth_report"] = truth_data
        artifacts["reject_histogram"] = reject_data
        return artifacts

    # Otherwise (incident or full mode): write to disk
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    # v3.2.7: Use atomic writes for artifacts
    scan_path = reports_dir / f"scan_{timestamp}.json"
    atomic_write_json(scan_path, scan_data, default=str)
    artifacts["scan"] = scan_path
    truth_path = reports_dir / f"truth_report_{timestamp}.json"
    atomic_write_json(truth_path, truth_data, default=str)
    artifacts["truth_report"] = truth_path
    reject_path = reports_dir / f"reject_histogram_{timestamp}.json"
    atomic_write_json(reject_path, reject_data, default=str)
    artifacts["reject_histogram"] = reject_path
    # LEGACY: snapshots/ (backward compat)
    snapshots_dir = output_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot_scan = snapshots_dir / f"scan_{timestamp}.json"
    atomic_write_json(snapshot_scan, scan_data, default=str)
    scan_log = output_dir / "scan.log"
    with open(scan_log, "w") as f:
        f.write(f"scan completed: {timestamp}\n")
    return artifacts


def _compute_execution_pnl(
    spread_signals: List[Dict[str, Any]],
    config: Dict[str, Any],
    filter_excluded: bool = False,
) -> Dict[str, Any]:
    """
    Compute execution_pnl section with Clean PnL v2 (v3.2.58).
    
    Clean PnL v2 = paper estimates with gas + slippage + L1 cost.
    cost_model_available=True when we have gas_usd_estimate in config.
    
    v3.2.58: Fixed slippage calculation to use position-based (paper_size_usd),
    not profit-based, to match execution simulation accounting:
    - gas_usd: L2 execution gas cost (from config.gas_usd_estimate)
    - slippage_bps: Slippage in basis points
    - slippage_usd: Slippage in USD = paper_size_usd * slippage_bps / 10000
    - l1_data_gas_units: L1 data gas units from config
    - l1_gas_price_gwei: L1 gas price from config
    - l1_cost_usd: L1 data cost in USD (l1_data_gas_units * l1_gas_price_gwei * eth_price / 1e9)
    - total_cost_usd: gas_usd + slippage_usd + l1_cost_usd
    
    IMPORTANT: Slippage is based on position size (notional), NOT gross profit.
    This matches the canonical formula: slippage_usd = paper_size_usd * slippage_bps / 10000
    
    Args:
        spread_signals: List of spread signal dicts with net_pnl_usdc_est
        config: Config dict with gas_usd_estimate, paper_size_usd, paper_slippage_bps
        filter_excluded: If True, only include signals with is_excluded_spread=False
        
    Returns:
        execution_pnl dict with full cost breakdown
    """
    gas_usd_estimate = config.get("gas_usd_estimate", 0.0)
    
    # v2.3.2: Optionally filter to included signals only
    if filter_excluded:
        signals_to_use = [s for s in spread_signals if not s.get("is_excluded_spread", False)]
    else:
        signals_to_use = spread_signals
    
    # Compute totals from filtered signals
    # v2.3.2 FIX: Use gross_pnl_usdc_est (actual field name from strategy/spreads.py)
    total_gross_pnl = sum(s.get("gross_pnl_usdc_est", 0) for s in signals_to_use)
    total_net_pnl = sum(s.get("net_pnl_usdc_est", 0) for s in signals_to_use if s.get("is_net_positive_est"))
    signals_with_estimates = [s for s in signals_to_use if s.get("net_pnl_usdc_est") is not None]
    
    # cost_model_available = True when we have gas estimate AND at least one signal
    # This is Clean PnL v2 (paper estimates with full cost breakdown)
    cost_model_available = bool(gas_usd_estimate and signals_with_estimates)
    
    # v3.2.58: Slippage based on position size (notional), NOT gross profit
    # This matches execution simulation: slippage_usd = paper_size_usd * slippage_bps / 10000
    # R29: paper_size_usd is seed-size diagnostic only. Canonical economics truth
    # comes from dynamic sweep frontier (best_size_usd / best_net_pnl_bps).
    paper_size_usd = config.get("paper_size_usd", 100.0)
    slippage_bps = config.get("paper_slippage_bps", 0)
    # Position-based slippage per signal, times number of signals
    num_signals = len(signals_with_estimates)
    slippage_usd = (paper_size_usd * slippage_bps / 10000.0) * num_signals if slippage_bps > 0 else 0.0
    
    # L1 cost: computed from config parameters
    l1_data_gas_units = config.get("l1_data_gas_units", 0)
    l1_gas_price_gwei = config.get("l1_gas_price_gwei", 0)
    # Get ETH price from config (default 3000 for consistency with other configs)
    eth_price_usd = config.get("tokens_usd_price", {}).get("WETH", 3000.0)
    # L1 cost in USD: (gas_units * gwei * 1e-9) * eth_price
    l1_cost_usd = (l1_data_gas_units * l1_gas_price_gwei * 1e-9) * eth_price_usd if l1_data_gas_units > 0 else 0.0
    
    # Total cost: gas + slippage + L1 (gas is also per-signal)
    total_gas_usd = gas_usd_estimate * num_signals if num_signals > 0 else gas_usd_estimate
    total_cost_usd = total_gas_usd + slippage_usd + l1_cost_usd
    
    # Net PnL: gross - total_cost (canonical invariant)
    computed_net_pnl = total_gross_pnl - total_cost_usd if cost_model_available else None
    
    # Net PnL in BPS relative to total notional (paper_size_usd * num_signals)
    total_notional = paper_size_usd * num_signals if num_signals > 0 else 0.0
    computed_net_pnl_bps = round((computed_net_pnl / total_notional) * 10000, 2) if (computed_net_pnl is not None and total_notional > 0) else None
    
    # Format as strings for money fields
    return {
        "signal_pnl_usdc": f"{total_gross_pnl:.6f}",
        "would_execute_pnl_usdc": f"{computed_net_pnl:.6f}" if computed_net_pnl is not None and computed_net_pnl > 0 else "0.000000",
        "gross_pnl_usdc": f"{total_gross_pnl:.6f}",
        "net_pnl_usdc": f"{computed_net_pnl:.6f}" if computed_net_pnl is not None else None,
        "net_pnl_bps": computed_net_pnl_bps,
        "cost_model_available": cost_model_available,
        # v3.2.62: Clean PnL v3 with position-based slippage (formula fix)
        # v3 upgrade: slippage_usd = paper_size_usd * slippage_bps / 10000 * num_signals
        # (not gross_pnl * slippage_bps / 10000 which was v1/v2 bug)
        "cost_model_version": "paper_gas_slippage_l1_v3" if cost_model_available else None,
        "cost_model_components": {
            "gas_usd": total_gas_usd,
            "slippage_bps": slippage_bps,
            "slippage_usd": round(slippage_usd, 6),
            "l1_data_gas_units": l1_data_gas_units,
            "l1_gas_price_gwei": l1_gas_price_gwei,
            "l1_cost_usd": round(l1_cost_usd, 6),
            "total_cost_usd": round(total_cost_usd, 6),
            "eth_price_usd": eth_price_usd,
            "paper_size_usd": paper_size_usd,  # seed-size diagnostic (R29: NOT execution truth)
            "paper_size_source": "seed_diagnostic",  # R29: canonical truth is dynamic_sweep.best_size_usd
            "num_signals": num_signals,  # v3.2.58: Track signal count for verification
        } if cost_model_available else None,
    }


def _build_measured_economics(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Build top-level measured economics block from dynamic sweep results.

    This is the canonical operational truth — all values come from
    QuoterV2/live-gas path, NOT paper/baseline estimates.
    
    R28.7: Includes per-route cost breakdown (probe_slippage) for
    each swept route — raw_spread, measured_slippage, lp_fee, gas, gap_to_zero.
    """
    ds = stats.get("roundtrip", {}).get("dynamic_sweep", {})
    if not ds.get("enabled") or not ds.get("best_net_pnl_bps"):
        return {"available": False, "source": "dynamic_sweep"}
    
    # R28.7: Per-route cost breakdown from sweep results
    per_route_breakdown = []
    raw_results = ds.get("results", [])
    for r in raw_results:
        if isinstance(r, dict):
            route_info = {
                "pair": r.get("pair"),
                "buy_dex": r.get("buy_dex"),
                "sell_dex": r.get("sell_dex"),
                "best_size_usd": r.get("best_size_usd"),
                "best_net_pnl_bps": r.get("best_net_pnl_bps"),
                "best_gross_pnl_bps": r.get("best_gross_pnl_bps"),
                "measured_slippage_bps": r.get("best_slippage_bps"),
                "lp_fee_bps": r.get("best_fee_bps"),
                "gas_bps": r.get("best_gas_bps"),
                "total_cost_bps": r.get("best_total_cost_bps"),
                "gap_to_zero_bps": r.get("gap_to_zero_bps"),
                "frontier_reason": r.get("frontier_reason"),
            }
            per_route_breakdown.append(route_info)
    
    return {
        "available": True,
        "source": "dynamic_sweep",
        "frontier_pair": ds.get("best_pair"),
        "best_size_usd": ds.get("best_size_usd"),
        "best_net_pnl_bps": ds.get("best_net_pnl_bps"),
        "gap_to_zero_bps": ds.get("gap_to_zero_bps"),
        "measured_gas_bps": ds.get("best_gas_bps"),
        "measured_fee_bps": ds.get("best_fee_bps"),
        "measured_slippage_bps": ds.get("best_slippage_bps"),
        "measured_total_cost_bps": ds.get("best_total_cost_bps"),
        # R28.7: Per-route probe_slippage breakdown
        "per_route_breakdown": per_route_breakdown,
    }


def _build_viability_decision(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Build the arbitrage viability decision — answered AFTER dynamic sweep.

    The canonical decision point is post-sweep: raw spread alone is
    insufficient because LP fees, gas, and slippage can exceed gross spread.
    
    R28.7: Uses executable_evidence from promoted sweep results.
    signal != opportunity != executable candidate.
    """
    ds = stats.get("roundtrip", {}).get("dynamic_sweep", {})
    rt = stats.get("roundtrip", {})
    if not ds.get("enabled"):
        return {
            "decided": False,
            "decision_point": "dynamic_sweep",
            "reason": "SWEEP_NOT_ENABLED",
        }
    gap = ds.get("gap_to_zero_bps")
    # R28.7: Use executable_evidence as primary, profitable_count as secondary
    executable_evidence = rt.get("executable_evidence", "NO_DATA")
    sweep_profitable = executable_evidence == "SWEEP_PROFITABLE"
    baseline_profitable = rt.get("profitable_count", 0) > 0
    return {
        "decided": True,
        "decision_point": "dynamic_sweep",
        "is_profitable": sweep_profitable or baseline_profitable,
        "sweep_profitable": sweep_profitable,
        "baseline_profitable": baseline_profitable,
        "executable_evidence": executable_evidence,
        "gap_to_zero_bps": gap,
        "frontier_pair": ds.get("best_pair"),
        "frontier_reason": ds.get("best_frontier_reason", "NO_DATA"),
        "routes_swept": ds.get("routes_swept", 0),
        "executable_candidates_count": rt.get("executable_candidates_count", 0),
    }


def _build_roundtrip_summary(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Build the curated roundtrip_summary block for truth_report.

    Includes the fixed-baseline fields plus the canonical dynamic_sweep
    sub-block so gates/consumers see sweep results directly.
    """
    rt = stats.get("roundtrip", {})
    ds = rt.get("dynamic_sweep", {})
    summary: Dict[str, Any] = {
        "enabled": rt.get("enabled", False),
        "evaluated_count": rt.get("evaluated_count", 0),
        "profitable_count": rt.get("profitable_count", 0),
        "suspect_profitable_count": rt.get("suspect_profitable_count", 0),  # R28.19
        "real_quote_count": rt.get("real_quote_count", 0),
        # R28.7: New primary KPI — executable candidates that passed all pre-filters
        "executable_candidates_count": rt.get("executable_candidates_count", 0),
        "best_net_pnl_bps": rt.get("best_net_pnl_bps"),
        # R28.7: Promoted sweep evidence — core decision layer output
        "best_executable_size_usd": rt.get("best_executable_size_usd"),
        "best_executable_pnl_bps": rt.get("best_executable_pnl_bps"),
        "executable_evidence": rt.get("executable_evidence", "NO_DATA"),
        "l1_cost_wei": rt.get("l1_cost_wei", 0),
        "l1_cost_source": rt.get("l1_cost_source", "none"),
        "gas_price_wei_used": rt.get("gas_price_wei_used", 0),
        "best_measured_spread_gap_bps": rt.get("best_measured_spread_gap_bps"),
        # R28.19: Reject visibility — roundtrip pipeline rejection reasons and gating counts
        "candidates_total": rt.get("candidates_total", 0),
        "gated_by_economics": rt.get("gated_by_economics", 0),
        "rejected_reasons": rt.get("rejected_reasons", {}),
        # R34: Propagate runtime error and sweep reprieve data so truth_report
        # doesn't mask a crash as ordinary NO_DATA.
        "error": rt.get("error"),
        "sweep_reprieve_count": rt.get("sweep_reprieve_count", 0),
        "sweep_reprieve_stats": rt.get("sweep_reprieve_stats"),
        # R39i++: Per-leg quote source aggregation for RCA/blocker visibility
        "leg_source_summary": rt.get("leg_source_summary"),
    }
    # v3.3.0: Canonical dynamic sweep sub-block
    if ds.get("enabled"):
        summary["dynamic_sweep"] = {
            "enabled": True,
            "routes_swept": ds.get("routes_swept", 0),
            "sizes_evaluated": ds.get("results", [{}])[0].get("sizes_evaluated", 0) if ds.get("results") else 0,
            "sweep_best_size_usd": ds.get("best_size_usd"),
            "sweep_best_net_pnl_bps": ds.get("best_net_pnl_bps"),
            "sweep_best_frontier_reason": ds.get("best_frontier_reason", "NO_DATA"),
            "frontier_pair": ds.get("best_pair"),
            "gap_to_zero_bps": ds.get("gap_to_zero_bps"),
            "measured_gas_bps": ds.get("best_gas_bps"),
            "measured_fee_bps": ds.get("best_fee_bps"),
            "measured_slippage_bps": ds.get("best_slippage_bps"),
            "measured_total_cost_bps": ds.get("best_total_cost_bps"),
        }
        # Full frontier curve per route (truth_report only, not propagated to rolling)
        raw_results = ds.get("results")
        if raw_results:
            summary["dynamic_sweep"]["frontier_curves"] = raw_results
    return summary


def _build_drift_summary(
    rejected_quotes: List[Dict[str, Any]],
    spread_signals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build first-class notional drift summary from rejected quotes and spread signals.

    Returns per-pair drift stats (pct + bps), aggregate rejection rate,
    worst offenders, and per-pair included signal drift.
    """
    # Count drift-excluded rejects per pair
    drift_rejects_by_pair: Dict[str, List[float]] = {}
    total_drift_excluded = 0
    for r in rejected_quotes:
        if r.get("reason") == "NOTIONAL_DRIFT_EXCLUDED":
            total_drift_excluded += 1
            pair = r.get("pair", "unknown")
            drift_pct = r.get("notional_drift_pct") or r.get("drift_pct", 0)
            if pair not in drift_rejects_by_pair:
                drift_rejects_by_pair[pair] = []
            if drift_pct:
                drift_rejects_by_pair[pair].append(abs(float(drift_pct)))

    # Extract drift from included spread signals — per-pair
    signal_drifts: List[float] = []
    signal_drift_by_pair: Dict[str, List[float]] = {}
    for sig in spread_signals:
        pair = sig.get("pair", "unknown")
        if pair not in signal_drift_by_pair:
            signal_drift_by_pair[pair] = []
        for field in ("buy_notional_drift_pct", "sell_notional_drift_pct"):
            d = sig.get(field)
            if d is not None:
                v = abs(float(d))
                signal_drifts.append(v)
                signal_drift_by_pair[pair].append(v)

    total_quotes = len(rejected_quotes) + len(spread_signals) * 2  # approx
    rejection_rate = total_drift_excluded / max(1, total_quotes)

    # Per-pair summary (worst offenders, sorted by excluded count)
    per_pair: List[Dict[str, Any]] = []
    for pair, drifts in sorted(drift_rejects_by_pair.items(), key=lambda x: -len(x[1])):
        median_pct = round(sorted(drifts)[len(drifts) // 2], 2) if drifts else 0
        per_pair.append({
            "pair": pair,
            "excluded_count": len(drifts),
            "median_drift_pct": median_pct,
            "median_drift_bps": round(median_pct * 100, 1),
            "max_drift_pct": round(max(drifts), 2) if drifts else 0,
            "max_drift_bps": round(max(drifts) * 100, 1) if drifts else 0,
            "drift_reject_reason": "NOTIONAL_DRIFT_EXCLUDED",
        })

    # Full per-pair drift (included signals): for all pairs with signal data
    per_pair_signal: List[Dict[str, Any]] = []
    for pair, drifts in sorted(signal_drift_by_pair.items(), key=lambda x: -len(x[1])):
        s = sorted(drifts)
        med = s[len(s) // 2] if s else 0
        per_pair_signal.append({
            "pair": pair,
            "signal_count": len(drifts),
            "median_drift_pct": round(med, 2),
            "median_drift_bps": round(med * 100, 1),
            "p90_drift_pct": round(s[int(len(s) * 0.9)], 2) if s else 0,
            "max_drift_pct": round(max(drifts), 2) if drifts else 0,
        })

    # Signal-level drift stats
    signal_median = 0.0
    signal_p90 = 0.0
    if signal_drifts:
        s = sorted(signal_drifts)
        signal_median = round(s[len(s) // 2], 2)
        signal_p90 = round(s[int(len(s) * 0.9)], 2)

    # R21: Unified per-pair drift summary — merges excluded rejects + included signals
    per_pair_drift_summary: List[Dict[str, Any]] = []
    all_pairs = sorted(set(list(drift_rejects_by_pair.keys()) + list(signal_drift_by_pair.keys())))
    for pair in all_pairs:
        excl = drift_rejects_by_pair.get(pair, [])
        incl = signal_drift_by_pair.get(pair, [])
        all_drifts = excl + incl
        if not all_drifts:
            continue
        s_all = sorted(all_drifts)
        med = s_all[len(s_all) // 2]
        p90 = s_all[int(len(s_all) * 0.9)]
        total_for_pair = len(excl) + len(incl)
        pair_rejection_rate = len(excl) / max(1, total_for_pair)
        per_pair_drift_summary.append({
            "pair": pair,
            "excluded_count": len(excl),
            "included_count": len(incl),
            "rejection_rate": round(pair_rejection_rate, 4),
            "notional_drift_median_bps": round(med * 100, 1),
            "notional_drift_p90_bps": round(p90 * 100, 1),
            "notional_drift_max_bps": round(max(all_drifts) * 100, 1),
            "drift_reject_reason": "NOTIONAL_DRIFT_EXCLUDED" if excl else None,
        })
    per_pair_drift_summary.sort(key=lambda x: -x["notional_drift_median_bps"])

    return {
        "drift_excluded_count": total_drift_excluded,
        "drift_rejection_rate": round(rejection_rate, 4),
        "signal_drift_median_pct": signal_median,
        "signal_drift_median_bps": round(signal_median * 100, 1),
        "signal_drift_p90_pct": signal_p90,
        "signal_drift_p90_bps": round(signal_p90 * 100, 1),
        # R21: notional_drift_bps — canonical BPS-scale aggregate
        "notional_drift_bps": round(signal_median * 100, 1),
        "worst_pairs_by_drift": per_pair[:5],
        "per_pair_signal_drift": per_pair_signal[:10],
        # R21: Unified per-pair drift summary (all pairs with any drift data)
        "per_pair_drift_summary": per_pair_drift_summary,
        "pairs_with_drift_data": len(signal_drift_by_pair),
        "pairs_with_exclusions": len(drift_rejects_by_pair),
    }


def build_truth_data(
    config: Dict[str, Any],
    stats: Dict[str, Any],
    current_block: int,
    spread_signals: List[Dict[str, Any]],
    suspect_examples: List[Dict[str, Any]],
    infra_payload: Dict[str, Any],
    raw_bps: int,
    spread_threshold_bps: int,
    run_timestamp: Optional[str] = None,  # v2.3.0: Unified provenance
    rejected_quotes: Optional[List[Dict[str, Any]]] = None,  # For drift summary
) -> Dict[str, Any]:
    """
    Build truth report data structure.
    
    Args:
        run_timestamp: Optional ISO-8601 timestamp for unified provenance.
                       If not provided, generates new timestamp.
    
    Returns:
        Truth report dict
    """
    now = run_timestamp or datetime.now(timezone.utc).isoformat()
    
    truth_data = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": now,
        "run_mode": "REGISTRY_REAL",
        # v2.3.0: Explicit safety contract (R28.15: read from config, not hardcoded)
        "kill_switch_active": config.get("kill_switch_active", True),
        "execution_enabled": config.get("execution_enabled", False),
        "execution_ready_count": stats.get("execution_ready_count", 0),  # v2.2.0: From stats (respects kill switch)
        "would_execute_count": stats.get("would_execute_count", 0),      # v2.2.0: Diagnostic only
        "execution_blocker": CURRENT_EXECUTION_BLOCKER.value,
        "execution_blocker_details": "EXECUTION_DISABLED_M5_0 - no execution cost model",
        "paper_cost_model_available": True,
        "execution_cost_model_available": False,
        # v2.3.0: Provenance binding (run_context)
        "run_context": {
            "run_timestamp": now,
        },
        "chain_id": config.get("chain_id", 42161),
        # v3.2.7: chain_key for multi-chain observability (strict contract: 'unknown' if missing)
        "chain_key": config.get("chain", "unknown"),
        "current_block": current_block,
        "config_params": {
            "min_spread_bps": spread_threshold_bps,
            "min_net_pnl_usdc_est": config.get("min_net_pnl_usdc_est", 0.0),
            "paper_size_usd": config.get("paper_size_usd", 1000),
            "gas_usd_estimate": config.get("gas_usd_estimate", 0.10),
            "paper_slippage_bps": config.get("paper_slippage_bps", 0),
            "autosize": config.get("autosize", {}),
            # v2.2.1: Config transparency for reproducibility
            "require_cross_dex": config.get("require_cross_dex", False),
            # v3.2.7: POSIX-canonical config_path
            "config_path": canonicalize_config_path(config.get("_config_path")),
            # v3.2.10: run_kind for smoke run isolation (NORM-only rolling policy)
            "run_kind": config.get("run_kind", "NORMAL"),
            # v3.2.64: Policy threshold transparency for runtime evidence
            "suspect_spread_bps_hard": config.get("suspect_spread_bps_hard"),
        },
        "quotes_total": stats["quotes_total"],
        "quotes_fetched": stats["quotes_fetched"],
        "dexes_active": stats["dexes_active"],
        "price_sanity_passed": stats["price_sanity_passed"],
        "price_sanity_failed": stats["price_sanity_failed"],
        "health": {
            "quotes_total": stats.get("quotes_total"),
            "quotes_fetched": stats.get("quotes_fetched"),
            "gates_passed": stats.get("gates_passed"),
            "dexes_active": stats.get("dexes_active"),
            "price_sanity_passed": stats.get("price_sanity_passed"),
            "price_sanity_failed": stats.get("price_sanity_failed"),
            "price_stability_factor": stats.get("price_stability_factor"),
            "rpc_errors": stats.get("rpc_errors"),
            "rpc_success_rate": stats.get("rpc_success_rate"),
        },
        "stats": stats,
        # v2.3.2: Clean PnL v1 - compute net_pnl from spread signals
        # cost_model_available=True when we have gas+slippage estimates
        # execution_pnl: ALL spread signals (including excluded)
        "execution_pnl": _compute_execution_pnl(spread_signals, config),
        # v2.3.2: execution_pnl_included: only non-excluded signals
        # This should match run_summary.metrics.total_net_usdc
        "execution_pnl_included": _compute_execution_pnl(spread_signals, config, filter_excluded=True),
        "pnl": {
            "_deprecated": True,
            "_migration": "Use 'execution_pnl' instead. This field will be removed in schema v3.3.",
            "signal_pnl_usdc": "0.000000",
            "would_execute_pnl_usdc": "0.000000",
        },
        "spread_signals": spread_signals,
        "signals_total": len(spread_signals),
        # R28.20: Actionable signals exclude diagnostic-only (mixed-source, slot0-only).
        # Gates should use this count, not signals_total, for real signal flow assessment.
        "actionable_signals_count": len([
            s for s in spread_signals if not s.get("is_diagnostic_only")
        ]),
        "opportunities_total": len([s for s in spread_signals if s.get("is_net_positive_est")]),
        "infra": infra_payload,
        "suspect_summary": {
            "count": stats.get("suspect_quotes", 0),
            "reasons": stats.get("suspect_reasons", {}),
            "examples": suspect_examples,
        },
        # M4.2: Opportunity engine integration
        "opportunity_engine": stats.get("opportunity_engine", {}),
        # R28.15: Live execution probe results (dormant unless execution_enabled=true)
        "live_execution": stats.get("live_execution", {"enabled": False}),
        # v2.1.0: Roundtrip reality check (Step 4 - roundtrip in truth_report)
        "roundtrip_summary": _build_roundtrip_summary(stats),
        # v3.5.0: Top-level measured economics — canonical operational truth block.
        # Populated from dynamic_sweep (post-roundtrip, QuoterV2-based).
        # Paper/baseline economics are NOT included here — see execution_pnl for those.
        "measured_economics": _build_measured_economics(stats),
        # R21: operational_truth designation — measured_economics is the SOLE
        # source of truth for viability assessment. Paper PnL is diagnostic only.
        "operational_truth_source": "measured_economics",
        # v3.5.0: Canonical arbitrage viability decision — answered AFTER dynamic sweep.
        "arbitrage_viability_decision": _build_viability_decision(stats),
        # Notional drift summary — per-pair drift stats and rejection rate
        "drift_summary": _build_drift_summary(rejected_quotes or [], spread_signals),
        # v2.1.0: truth_mode_m42 - when true, one-leg PnL is DIAGNOSTIC only, roundtrip is canonical
        "truth_mode_m42": config.get("truth_mode_m42", False),
        # v2.3.0: Explicit DIAGNOSTIC vs CANONICAL profit semantics
        # profit_is_diagnostic=True means total_net_usdc is NOT canonical/realized profit
        # v2.3.2 FIX: profitable_count > 0 AND real_quote_count > 0 required for CANONICAL.
        # real_quote_count guards against suspect contamination (profitable_count from paper estimates).
        "profit_is_diagnostic": not (
            stats.get("roundtrip", {}).get("profitable_count", 0) > 0
            and stats.get("roundtrip", {}).get("real_quote_count", 0) > 0
        ),
        "profit_truth_source": (
            "ROUNDTRIP_CANONICAL" if (
                stats.get("roundtrip", {}).get("profitable_count", 0) > 0
                and stats.get("roundtrip", {}).get("real_quote_count", 0) > 0
            )
            else "ONE_LEG_DIAGNOSTIC" if config.get("truth_mode_m42", False)
            else "ONE_LEG_UNVERIFIED"
        ),
        "profit_realism_status": (
            "ROUNDTRIP_PROFITABLE" if (
                stats.get("roundtrip", {}).get("profitable_count", 0) > 0
                and stats.get("roundtrip", {}).get("real_quote_count", 0) > 0
            )
            else "ROUNDTRIP_NOT_PROFITABLE" if stats.get("roundtrip", {}).get("evaluated_count", 0) > 0
            else "ONE_LEG_ONLY_DIAGNOSTIC"
        ),
    }
    
    try:
        truth_data["price_sanity_deviation_bps_raw_max"] = int(raw_bps)
    except Exception:
        truth_data["price_sanity_deviation_bps_raw_max"] = None
    
    # R31: quote_source_summary — first-class visibility of executable vs diagnostic
    # quote split per DEX.  Previously buried inside stats; now surfaced for operator RCA.
    truth_data["quote_source_summary"] = {
        "quotes_fetched_executable": stats.get("quotes_fetched_executable", 0),
        "quotes_fetched_diagnostic": stats.get("quotes_fetched_diagnostic", 0),
        "quoter_v2_failed_count": stats.get("quoter_v2_failed_count", 0),
        "quoter_matrix": stats.get("quoter_matrix", {}),
    }

    # R31: OE rejection funnel — first-class summary of opportunity engine rejections.
    _oe = stats.get("opportunity_engine", {})
    _oe_summary = _oe.get("summary", {}) if isinstance(_oe, dict) else {}
    truth_data["oe_rejection_funnel"] = {
        "total_opportunities": _oe_summary.get("total_opportunities", 0),
        "gated_count": _oe_summary.get("gated_count", 0),
        "rejected_count": _oe_summary.get("rejected_count", 0),
        "rejected_reasons": _oe_summary.get("rejected_reasons", {}),
    }

    # R28.20: Inline reject histogram + samples so truth_report is self-contained
    # for RCA.  Previously this data was only in the separate reject_histogram artifact,
    # making failing-chain truth reports opaque.
    rq = rejected_quotes or []
    rh: Dict[str, int] = {}
    for r in rq:
        reason = r.get("reason", "UNKNOWN")
        rh[reason] = rh.get(reason, 0) + 1
    truth_data["reject_histogram"] = rh
    truth_data["reject_samples"] = [
        {
            "pair": r.get("pair"),
            "dex_id": r.get("dex_id"),
            "fee": r.get("fee"),
            "reason": r.get("reason"),
            "deviation_bps": r.get("deviation_bps"),
            "pool_address": r.get("pool_address"),
        }
        for r in rq[:10]
    ]
    
    # R29: Pair-level funnel trace — propagated from stats for truth-report self-containment
    if stats.get("pair_funnel_trace"):
        truth_data["pair_funnel_trace"] = stats["pair_funnel_trace"]
    
    return truth_data


def build_reject_data(
    config: Dict[str, Any],
    current_block: int,
    sanity_rejects: List[Dict[str, Any]],
    rejected_quotes: List[Dict[str, Any]],
    stats: Dict[str, Any],
    infra_payload: Dict[str, Any],
    run_timestamp: Optional[str] = None,  # v2.3.0: Unified provenance
    quotes_sample: Optional[List[Dict[str, Any]]] = None,  # v3.2.19: For per-DEX metrics
) -> Dict[str, Any]:
    """
    Build reject histogram data structure.
    
    Note: sanity_rejects is a SUBSET of rejected_quotes (filtered by reason).
    We use rejected_quotes as canonical rejects list to avoid double-counting.
    
    Args:
        run_timestamp: Optional ISO-8601 timestamp for unified provenance.
    
    Returns:
        Reject histogram dict
    """
    now = run_timestamp or datetime.now(timezone.utc).isoformat()
    # v2.1.0: FIX double-count bug - sanity_rejects is subset of rejected_quotes
    total_rejects = len(rejected_quotes)
    
    # v2.1.0 Step 8: Build reason histogram with sample details
    reason_histogram = {}
    for r in rejected_quotes:
        reason = r.get("reason", "UNKNOWN")
        reason_histogram[reason] = reason_histogram.get(reason, 0) + 1
    
    # v2.6.2: Build reason_keys_top for observability (pool keys per reason)
    # Groups rejected quotes by reason and extracts top-N pool_key/pool_address for each
    reason_keys_top = {}
    reason_rejects_by_key = {}
    for r in rejected_quotes:
        reason = r.get("reason", "UNKNOWN")
        dex_id = r.get("dex_id", "unknown")
        pair = r.get("pair", "unknown")
        fee = r.get("fee", 0)
        pool_addr = r.get("pool_address", "")
        # v2.0.4: Use canonical pool_key builder
        pool_key = make_pool_key(dex_id, pair, fee)
        
        if reason not in reason_rejects_by_key:
            reason_rejects_by_key[reason] = {}
        if pool_key not in reason_rejects_by_key[reason]:
            reason_rejects_by_key[reason][pool_key] = {
                "pool_key": pool_key,
                "pool_address": pool_addr,
                "dex_id": dex_id,
                "pair": pair,
                "fee": fee,
                "count": 0,
            }
        reason_rejects_by_key[reason][pool_key]["count"] += 1
    
    # Extract top-5 pool_keys for each reason
    for reason, keys_dict in reason_rejects_by_key.items():
        sorted_keys = sorted(keys_dict.values(), key=lambda x: -x["count"])
        reason_keys_top[reason] = sorted_keys[:5]
    
    # v2.1.0 Step 8: Extract PRICE_SANITY_FAILED samples with anchor/observed details
    price_sanity_samples = []
    for r in rejected_quotes:
        if r.get("reason") == "PRICE_SANITY_FAILED":
            price_sanity_samples.append({
                "pair": r.get("pair"),
                "dex_id": r.get("dex_id"),
                "fee": r.get("fee"),
                "deviation_bps": r.get("deviation_bps"),
                "anchor_price": r.get("anchor_price"),
                "price_exact": r.get("price_exact"),
                "price_ratio": r.get("price_ratio"),
                "anchor_source": r.get("anchor_source"),
            })
            if len(price_sanity_samples) >= 5:  # Cap at 5 samples
                break
    
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": now,
        "run_mode": "REGISTRY_REAL",
        # v2.3.0: Unified provenance
        "run_context": {
            "run_timestamp": now,
        },
        "chain_id": config.get("chain_id", 42161),
        # v3.2.7: chain_key for multi-chain observability (strict contract: 'unknown' if missing)
        "chain_key": config.get("chain", "unknown"),
        "current_block": current_block,
        "rejects": rejected_quotes,  # canonical list (includes sanity_rejects)
        "sample_rejects": rejected_quotes[:10] if rejected_quotes else [],
        "rejects_total": total_rejects,
        "total_rejects": total_rejects,  # deprecated alias
        "no_rejects": total_rejects == 0,
        "sanity_rejects_count": len(sanity_rejects),  # v2.1.0: separate field
        "price_sanity_failed": len(sanity_rejects),
        "pool_missing_count": stats.get("pool_missing_count", 0),
        "pool_disabled_count": stats.get("pool_disabled_count", 0),
        "quarantined_count": stats.get("quarantined_count", 0),
        "v3_slot0_failed_count": stats.get("v3_slot0_failed_count", 0),
        # v3.2.3: runtime_disabled_count for observability sync with scan.stats
        "runtime_disabled_count": stats.get("runtime_disabled_count", 0),
        "price_outlier_count": sum(1 for r in rejected_quotes if r.get("reason") == "PRICE_OUTLIER"),
        # v2.1.0 Step 8: Enhanced histogram and samples
        "reason_histogram": reason_histogram,
        # v2.6.2: Per-reason top pool keys for observability (quarantine/debug)
        "reason_keys_top": reason_keys_top,
        "price_sanity_samples": price_sanity_samples,
        # v3.2.11: chain_key from config for chain-scoped quarantine stats
        "quarantine_stats": get_quarantine_manager(config.get("chain")).to_dict(),
        # v3.2.19: Per-DEX promotion metrics (requires quotes_sample)
        "per_dex_stats": _compute_per_dex_stats(quotes_sample or [], rejected_quotes),
        "infra": infra_payload,
    }


def build_scan_data(
    config: Dict[str, Any],
    current_block: int,
    stats: Dict[str, Any],
    quotes_sample: List[Dict[str, Any]],
    infra_payload: Dict[str, Any],
    run_timestamp: Optional[str] = None,  # v2.3.0: Unified provenance
    rejected_quotes: Optional[List[Dict[str, Any]]] = None,  # v3.2.19: For per-DEX metrics
) -> Dict[str, Any]:
    """
    Build scan data structure.
    
    Args:
        run_timestamp: Optional ISO-8601 timestamp for unified provenance.
    
    Returns:
        Scan data dict
    """
    now = run_timestamp or datetime.now(timezone.utc).isoformat()
    dexes_active_list = sorted({q.get("dex_id") for q in quotes_sample})
    
    return {
        "timestamp": now,
        "run_mode": "REGISTRY_REAL",
        # v2.3.0: Unified provenance
        "run_context": {
            "run_timestamp": now,
        },
        "chain_id": config.get("chain_id", 42161),
        # v3.2.7: chain_key for multi-chain observability (strict contract: 'unknown' if missing)
        "chain_key": config.get("chain", "unknown"),
        "current_block": current_block,
        "quotes_total": stats["quotes_total"],
        "quotes_fetched": stats["quotes_fetched"],
        "dexes_active": stats["dexes_active"],
        "dexes_active_list": dexes_active_list,
        "price_sanity_passed": stats["price_sanity_passed"],
        "price_sanity_failed": stats["price_sanity_failed"],
        "stats": stats,
        "quotes": quotes_sample,
        "quotes_sample": quotes_sample,
        # v3.2.19: Per-DEX promotion metrics
        "per_dex_stats": _compute_per_dex_stats(quotes_sample, rejected_quotes or []),
        "infra": infra_payload,
    }
