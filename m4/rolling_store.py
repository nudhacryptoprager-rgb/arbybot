"""
M4 Rolling Store Module

Rolling artifact persistence for aggregator, latest files, and incidents.

Artifacts:
- _latest.json: Pointer to latest run status (schema m4:latest:v1.6)
- run_summary_latest.json: Full run summary for latest run
- m4_stability_agg.json: Rolling window aggregator

Key concepts:
- Rolling window: Only keeps last N runs (default 200)
- Light format: Aggregator stores minimal fields per run
- Deduplication: Same run_id is skipped
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from .evidence import get_git_context


def ensure_rolling_agg_exists(agg_path: Path) -> dict:
    """
    Ensure aggregator file exists with valid schema.
    
    Args:
        agg_path: Path to m4_stability_agg.json
        
    Returns:
        Loaded or initialized aggregator data
    """
    if agg_path.exists():
        try:
            with open(agg_path) as f:
                data = json.load(f)
            # Validate has required fields
            if "runs" in data and "schema_version" in data:
                # Upgrade schema to current version on load
                data["schema_version"] = "m4:stability_agg:v1.12"
                return data
        except Exception:
            pass
    
    # Initialize new aggregator
    return {
        "schema_version": "m4:stability_agg:v1.12",  # v1.12.0: taxonomy contract, thresholds bite
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runs": [],
    }


def reset_rolling_window(agg_path: Path, reason: str = "manual_reset") -> dict:
    """
    Reset rolling window by archiving current aggregator and creating fresh one.
    
    Use after major policy changes, threshold recalibrations, or version upgrades.
    
    Args:
        agg_path: Path to m4_stability_agg.json
        reason: Reason for reset (stored in archive)
        
    Returns:
        Fresh aggregator data
    """
    from m4.evidence import get_run_timestamp
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_timestamp = get_run_timestamp()
    
    # Archive current aggregator if exists
    if agg_path.exists():
        archive_name = f"m4_stability_agg_archive_{ts}.json"
        archive_path = agg_path.parent / archive_name
        
        with open(agg_path) as f:
            old_data = json.load(f)
        
        # v2.0: Add archive metadata (SHA-free)
        old_data["archived_at"] = datetime.now(timezone.utc).isoformat()
        old_data["archive_reason"] = reason
        old_data["archive_run_timestamp"] = run_timestamp  # v2.0: timestamp instead of SHA
        
        with open(archive_path, "w") as f:
            json.dump(old_data, f, indent=2)
        
        print(f"[ROLLING-RESET] Archived: {archive_name} (runs={len(old_data.get('runs', []))})")
    
    # v2.0: Create fresh aggregator (SHA-free)
    fresh = {
        "schema_version": "m4:stability_agg:v2.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reset_run_timestamp": run_timestamp,  # v2.0: timestamp instead of SHA
        "reset_reason": reason,
        "runs": [],
    }
    
    with open(agg_path, "w") as f:
        json.dump(fresh, f, indent=2)
    
    print(f"[ROLLING-RESET] Fresh aggregator created at {agg_path.name}")
    return fresh


def emit_to_aggregator_light(
    run_summary: dict,
    agg_path: Path,
    max_runs: int = 200,
    target_sha: str = None  # v2.0: DEPRECATED, kept for backward compat
) -> dict:
    """
    Emit run to rolling aggregator. Returns updated agg_data.
    
    Args:
        run_summary: Run summary dict with metrics
        agg_path: Path to aggregator file
        max_runs: Maximum runs to keep in window
        target_sha: DEPRECATED (v2.0: SHA tracking removed)
        
    Returns:
        Updated aggregator data
    """
    from m4.policy import Thresholds
    
    agg_data = ensure_rolling_agg_exists(agg_path)
    
    # Extract key fields
    metrics = run_summary.get("metrics", {})
    status = run_summary.get("status", "UNKNOWN")
    signals_count = metrics.get("signals_count", 0)
    run_id = run_summary.get("run_id", "")
    reasons = run_summary.get("reasons", [])
    total_net = metrics.get("total_net_usdc", 0)
    
    # v1.11.0: Determine run_kind from run_id/context
    run_kind = "NORMAL"  # default
    if "offline" in run_id.lower() or "fixture" in run_id.lower():
        run_kind = "OFFLINE"
    elif "coverage" in run_id.lower():
        run_kind = "COVERAGE"
    elif "smoke" in run_id.lower():
        run_kind = "SMOKE"
    # Override from run_summary if explicitly set
    run_kind = run_summary.get("run_kind", run_kind)
    
    # v1.11.0: STATUS CONTRACT - NO_DATA ONLY when signals_count == 0
    # For signals > 0: status based on profit/quality independently
    is_data_run = signals_count >= Thresholds.MIN_SIGNALS_FOR_PASS
    
    # v1.10.0: Detect INFRA failures
    is_infra_fail = any(r.startswith("INFRA_") for r in reasons)
    
    # v1.11.0: Proper NO_DATA semantic
    if signals_count == 0:
        run_status = "NO_DATA"
        reasons = ["NO_DATA"]
    else:
        # signals > 0 → use status from run_summary (computed by gates.py)
        run_status = status
        # Add WARN_LOW_SAMPLE if below threshold but not in reasons
        if signals_count < Thresholds.MIN_SIGNALS_FOR_PASS:
            if "WARN_LOW_SAMPLE" not in reasons:
                reasons = list(reasons) + ["WARN_LOW_SAMPLE"]
    
    # DEDUPLICATION: Check if run_id already exists
    existing_run_ids = {r.get("run_id") for r in agg_data.get("runs", []) if r.get("run_id")}
    if run_id and run_id in existing_run_ids:
        print(f"[EMIT-AGG] SKIP duplicate run_id={run_id}")
        return agg_data
    
    # v2.0: SHA tracking removed - use run_timestamp from run_context
    run_context = run_summary.get("run_context", {})
    run_timestamp = run_context.get("run_timestamp", run_summary.get("timestamp", ""))
    
    # Append light run info
    # v1.9.9: Add pair, route, dex diversity tracking
    run_pairs = run_summary.get("inputs", {}).get("pairs", [])
    run_routes = run_summary.get("inputs", {}).get("routes", [])
    
    agg_data["runs"].append({
        "run_id": run_id,
        "timestamp": run_summary.get("timestamp", ""),
        "run_timestamp": run_timestamp,  # v2.0: primary provenance field
        "code_sha": None,  # v2.0: DEPRECATED
        "net_usdc": metrics.get("total_net_usdc", 0),
        "mae": metrics.get("mae_net_usdc", 0),
        "sign_rate": metrics.get("est_sign_correct_rate", 0),
        "reasons": reasons,
        "fragile_rate": metrics.get("fragile_rate", 0),
        "signals_count": signals_count,
        "run_status": run_status,
        "run_kind": run_kind,                  # v1.11.0: segmentation by purpose
        "is_data_run": is_data_run,            # v1.10.0: profit-grade data run
        "is_infra_fail": is_infra_fail,        # v1.10.0: INFRA_* failure
        "pairs": run_pairs[:10] if run_pairs else [],  # v1.9.9: pairs (limit 10)
        "routes": run_routes[:10] if run_routes else [],  # v1.9.9: routes (limit 10)
    })
    
    # Clean legacy: keep only light-format runs
    agg_data["runs"] = [r for r in agg_data["runs"] if "net_usdc" in r]
    runs = agg_data["runs"]
    
    # Rolling window: keep only last N runs
    if len(runs) > max_runs:
        agg_data["runs"] = runs[-max_runs:]
        runs = agg_data["runs"]
    
    # Compute quick stats
    agg_data = _compute_quick_stats(agg_data, run_summary=run_summary, target_sha=target_sha)
    
    # Write to disk
    with open(agg_path, "w") as f:
        json.dump(agg_data, f, indent=2)
    
    print(f"[EMIT-AGG] Updated: {agg_path} (runs={len(runs)}, "
          f"data_runs={agg_data['quick_stats']['pass_count'] + agg_data['quick_stats']['fail_count']}, "
          f"agg_status={agg_data.get('agg_status', 'UNKNOWN')})")
    
    return agg_data


def _compute_quick_stats(
    agg_data: dict,
    run_summary: dict = None,
    target_sha: str = None  # v2.0: DEPRECATED, kept for backward compat
) -> dict:
    """
    Compute quick stats and rolling window info for aggregator.
    
    Args:
        agg_data: Aggregator data dict with runs list
        run_summary: Latest run summary (optional, for future use)
        target_sha: DEPRECATED (v2.0: SHA tracking removed)
    
    v2.0 STATUS CONTRACT:
    - SHA tracking removed, timestamp-based provenance
    - NO_DATA: ONLY when signals_count == 0
    - Segments by run_kind: NORMAL, COVERAGE, SMOKE, OFFLINE
    - Main KPIs computed on NORMAL runs only
    - All runs treated as same code identity (no per-SHA breakdown)
    """
    from m4.policy import Thresholds, POLICY_VERSION
    
    # v2.0: Upgrade schema_version (SHA-free)
    agg_data["schema_version"] = "m4:stability_agg:v2.0"
    
    runs = agg_data.get("runs", [])
    
    # v1.11.0: Segment runs by kind
    # Main KPIs are computed on NORMAL runs only
    normal_runs = [r for r in runs if r.get("run_kind", "NORMAL") == "NORMAL"]
    coverage_runs = [r for r in runs if r.get("run_kind") == "COVERAGE"]
    other_runs = [r for r in runs if r.get("run_kind") in ("SMOKE", "OFFLINE")]
    
    # v1.10.0: Use is_data_run flag (profit-grade threshold)
    # Fallback to signals_count >= MIN_SIGNALS_FOR_PASS for legacy runs
    min_signals = Thresholds.MIN_SIGNALS_FOR_PASS
    
    # v1.11.0: Compute stats on NORMAL runs for main KPIs
    # This prevents coverage/stress runs from penalizing data_run_rate
    data_runs = [r for r in normal_runs if r.get("is_data_run", r.get("signals_count", 0) >= min_signals)]
    no_data_count = sum(1 for r in normal_runs if r.get("signals_count", 0) == 0)  # v1.11.0: true NO_DATA only
    low_sample_count = sum(1 for r in normal_runs if "WARN_LOW_SAMPLE" in r.get("reasons", []))
    data_run_count = len(data_runs)
    
    # v1.10.0: INFRA failure tracking (across all runs)
    infra_fail_count = sum(1 for r in runs if r.get("is_infra_fail", False) or 
                           any("INFRA_" in str(x) for x in r.get("reasons", [])))
    
    # v1.11.0: Main KPIs on NORMAL runs only
    pass_count = sum(1 for r in data_runs if not any(x for x in r.get("reasons", []) if x.startswith("FAIL_")))
    fail_count = len(data_runs) - pass_count
    warn_count_core = sum(1 for r in data_runs if "WARN_DRIFT_MAE" in r.get("reasons", []))
    total_net = sum(r.get("net_usdc", 0) for r in normal_runs)
    total_signals = sum(r.get("signals_count", 0) for r in normal_runs)
    
    # Percentile calculations
    fragile_rates = [r.get("fragile_rate", 0) for r in data_runs]
    mae_values = [r.get("mae", 0) for r in data_runs]
    net_values = [r.get("net_usdc", 0) for r in data_runs]
    
    # v1.11.0: Signals per run stats (operational KPI for continuous scan)
    signals_per_run = [r.get("signals_count", 0) for r in normal_runs]
    
    def percentile(values, p):
        """Compute percentile with linear interpolation."""
        if not values:
            return 0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_vals) else f
        return round(sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f]), 4)
    
    # Rolling window
    min_runs = Thresholds.MIN_RUNS_FOR_AGG
    min_signals = Thresholds.MIN_SIGNALS_FOR_AGG
    in_warmup = len(normal_runs) < min_runs or total_signals < min_signals
    
    # v1.11.0: Quality metrics on NORMAL runs only
    # This prevents coverage/stress runs from penalizing operational KPIs
    no_data_rate = no_data_count / len(normal_runs) if normal_runs else 0
    low_sample_rate = low_sample_count / len(normal_runs) if normal_runs else 0
    data_run_rate = data_run_count / len(normal_runs) if normal_runs else 0  # v1.11.0: NORMAL only
    effective_pass_rate = pass_count / len(normal_runs) if normal_runs else 0  # True rate including NO_DATA
    pass_rate = pass_count / len(data_runs) if data_runs else 0  # Rate excluding NO_DATA
    warn_rate_core = warn_count_core / len(data_runs) if data_runs else 0
    fail_rate = fail_count / len(data_runs) if data_runs else 0
    fragile_rate_p90 = percentile(fragile_rates, 90)
    mae_p90 = percentile(mae_values, 90)
    
    # v1.11.0: Coverage runs stats (separate)
    coverage_signals = sum(r.get("signals_count", 0) for r in coverage_runs)
    coverage_net = sum(r.get("net_usdc", 0) for r in coverage_runs)
    
    agg_data["runs_included"] = len(runs)
    agg_data["runs_in_window"] = len(runs)
    agg_data["rolling_window"] = {
        "max": Thresholds.ROLLING_WINDOW_MAX,
        "current": len(runs),
        "normal_runs": len(normal_runs),     # v1.11.0: main KPI runs
        "coverage_runs": len(coverage_runs), # v1.11.0: coverage runs (separate)
        "other_runs": len(other_runs),       # v1.11.0: smoke/offline
        "min_runs": min_runs,
        "min_signals": min_signals,
        "in_warmup": in_warmup,
    }
    
    # v1.9.8: Diversity metrics - detect duplicate signals pattern
    unique_net_values = len(set(round(r.get("net_usdc", 0), 2) for r in data_runs))
    net_diversity_rate = unique_net_values / len(data_runs) if data_runs else 0
    
    # v1.9.9: Pair/Route/DEX diversity across window
    all_pairs = set()
    all_routes = set()
    for r in runs:
        all_pairs.update(r.get("pairs", []))
        all_routes.update(r.get("routes", []))
    unique_pairs = len(all_pairs)
    unique_routes = len(all_routes)
    
    # v2.0: SHA tracking removed - all runs treated as same code identity
    # No per-SHA filtering, use all NORMAL runs for stats
    current_sha_all_runs = normal_runs  # All normal runs (no SHA filter)
    current_sha_runs = normal_runs  # NORMAL only
    current_sha_data_runs = [r for r in current_sha_runs 
                             if r.get("signals_count", 0) >= Thresholds.MIN_SIGNALS_FOR_PASS]
    current_sha_pass = sum(1 for r in current_sha_data_runs 
                          if not any(x for x in r.get("reasons", []) if x.startswith("FAIL_")))
    current_sha_fail = sum(1 for r in current_sha_data_runs 
                          if any(x for x in r.get("reasons", []) if x.startswith("FAIL_")))
    current_sha_no_data = sum(1 for r in current_sha_runs 
                             if r.get("signals_count", 0) == 0)  # v1.11.0: true NO_DATA only
    
    agg_data["quick_stats"] = {
        "pass_count": pass_count,
        "fail_count": fail_count,
        "no_data_count": no_data_count,
        "data_run_count": data_run_count,      # v1.9.9: runs with >= MIN_SIGNALS_FOR_PASS
        "warn_count_core": warn_count_core,
        "low_sample_count": low_sample_count,
        "pass_rate": round(pass_rate, 4),
        "effective_pass_rate": round(effective_pass_rate, 4),  # v1.9.5: PRIMARY metric
        "data_run_rate": round(data_run_rate, 4),              # v1.11.0: NORMAL runs only
        "no_data_rate": round(no_data_rate, 4),                # v1.11.0: true NO_DATA (signals=0)
        "warn_rate_core": round(warn_rate_core, 4),
        "low_sample_rate": round(low_sample_rate, 4),
        "fail_rate": round(fail_rate, 4),
        "total_signals": total_signals,
        "fragile_rate_p50": percentile(fragile_rates, 50),  # v1.9.7: median fragile
        "fragile_rate_p90": fragile_rate_p90,
        "mae_p90": mae_p90,
        "total_net_usdc": round(total_net, 4),
        "avg_net_usdc": round(total_net / len(data_runs), 4) if data_runs else 0,
        "net_p10": percentile(net_values, 10),
        "mae_p50": percentile(mae_values, 50),
        # v1.9.8: Diversity metrics
        "unique_net_values": unique_net_values,
        "net_diversity_rate": round(net_diversity_rate, 4),
        # v1.9.9: Pair/Route diversity
        "unique_pairs": unique_pairs,
        "unique_routes": unique_routes,
        # v1.10.0: INFRA failure tracking
        "infra_fail_count": infra_fail_count,
        "infra_fail_rate": round(infra_fail_count / len(runs), 4) if runs else 0,
        # v1.11.0: Coverage stats (separate from main KPIs)
        "coverage_runs_count": len(coverage_runs),
        "coverage_signals_total": coverage_signals,
        "coverage_net_usdc": round(coverage_net, 4),
        # v1.11.0: Signals per run stats (operational KPI)
        "signals_per_run_p50": percentile(signals_per_run, 50),
        "signals_per_run_p90": percentile(signals_per_run, 90),
        "signals_per_run_avg": round(sum(signals_per_run) / len(signals_per_run), 2) if signals_per_run else 0,
    }
    
    # v1.11.0: Enhanced runs_since_sha (current code stability - PRIMARY view)
    # Use is_data_run flag for accurate data_runs counting, NORMAL runs only
    current_sha_infra_fails = sum(1 for r in current_sha_runs if r.get("is_infra_fail", False))
    sha_data_run_rate = len(current_sha_data_runs) / len(current_sha_runs) if current_sha_runs else 0
    sha_effective_pass_rate = current_sha_pass / len(current_sha_data_runs) if current_sha_data_runs else 0
    sha_fail_rate = current_sha_fail / len(current_sha_data_runs) if current_sha_data_runs else 0
    sha_total_signals = sum(r.get("signals_count", 0) for r in current_sha_data_runs)
    
    # v1.11.0: Count low_sample runs for SHA (signals 1-4)
    sha_low_sample_count = sum(1 for r in current_sha_runs 
                               if 0 < r.get("signals_count", 0) < Thresholds.MIN_SIGNALS_FOR_PASS)
    
    # v2.0: SHA tracking removed - renamed to runs_since_timestamp
    # All runs treated as same code identity, no per-SHA breakdown
    agg_data["runs_since_timestamp"] = {
        "sha": None,  # v2.0: DEPRECATED
        "runs_count": len(current_sha_runs),
        "data_runs_count": len(current_sha_data_runs),
        "data_signals_total": sha_total_signals,
        "no_data_count": current_sha_no_data,
        "low_sample_count": sha_low_sample_count,
        "infra_fail_count": current_sha_infra_fails,
        "pass_count": current_sha_pass,
        "fail_count": current_sha_fail,
        "data_run_rate": round(sha_data_run_rate, 4),
        "effective_pass_rate": round(sha_effective_pass_rate, 4),
        "fail_rate": round(sha_fail_rate, 4),
        # v2.0: Simplified status (no per-SHA tracking)
        "status": (
            "OK" if len(current_sha_data_runs) >= 3 and sha_effective_pass_rate >= 0.80 and sha_data_run_rate >= 0.50 else
            "WARN" if len(current_sha_runs) >= 1 and (sha_effective_pass_rate >= 0.60 or len(current_sha_data_runs) < 3) else
            "FAIL" if len(current_sha_data_runs) >= 3 and sha_effective_pass_rate < 0.60 else
            "PENDING"
        ),
    }
    
    # v1.9.7: Compute fragile_rate_p50
    fragile_rate_p50 = percentile(fragile_rates, 50)
    
    # === Aggregate status with QUALITY GATES (v1.9.7) ===
    quality_warnings = []
    agg_reasons = []  # v1.9.6: canonical tokens for agg_status
    
    # Check quality thresholds
    if fragile_rate_p90 > Thresholds.AGG_FRAGILE_P90_FAIL:
        quality_warnings.append(f"FRAGILE_P90_HIGH({fragile_rate_p90:.2f}>{Thresholds.AGG_FRAGILE_P90_FAIL})")
        agg_reasons.append("FRAGILE_P90_HIGH")
    elif fragile_rate_p90 > Thresholds.AGG_FRAGILE_P90_WARN:
        quality_warnings.append(f"FRAGILE_P90_ELEVATED({fragile_rate_p90:.2f}>{Thresholds.AGG_FRAGILE_P90_WARN})")
        agg_reasons.append("FRAGILE_P90_ELEVATED")
    
    # v1.9.7: FRAGILE_P50 early warning (median fragile check)
    if fragile_rate_p50 > Thresholds.AGG_FRAGILE_P50_WARN:
        quality_warnings.append(f"FRAGILE_P50_ELEVATED({fragile_rate_p50:.2f}>{Thresholds.AGG_FRAGILE_P50_WARN})")
        agg_reasons.append("FRAGILE_P50_ELEVATED")
    
    if low_sample_rate > Thresholds.AGG_LOW_SAMPLE_RATE_FAIL:
        quality_warnings.append(f"LOW_SAMPLE_RATE_HIGH({low_sample_rate:.2f}>{Thresholds.AGG_LOW_SAMPLE_RATE_FAIL})")
        agg_reasons.append("LOW_SAMPLE_RATE_HIGH")
    elif low_sample_rate > Thresholds.AGG_LOW_SAMPLE_RATE_WARN:
        quality_warnings.append(f"LOW_SAMPLE_RATE_ELEVATED({low_sample_rate:.2f}>{Thresholds.AGG_LOW_SAMPLE_RATE_WARN})")
        agg_reasons.append("LOW_SAMPLE_RATE_ELEVATED")
    
    if mae_p90 > Thresholds.AGG_MAE_P90_FAIL:
        quality_warnings.append(f"MAE_P90_HIGH({mae_p90:.2f}>{Thresholds.AGG_MAE_P90_FAIL})")
        agg_reasons.append("MAE_P90_HIGH")
    
    # v1.9.9: DATA_RUN_RATE quality gate
    if data_run_rate < Thresholds.AGG_DATA_RUN_RATE_FAIL:
        quality_warnings.append(f"DATA_RUN_RATE_LOW({data_run_rate:.2f}<{Thresholds.AGG_DATA_RUN_RATE_FAIL})")
        agg_reasons.append("DATA_RUN_RATE_LOW")
    elif data_run_rate < Thresholds.AGG_DATA_RUN_RATE_WARN:
        quality_warnings.append(f"DATA_RUN_RATE_WARN({data_run_rate:.2f}<{Thresholds.AGG_DATA_RUN_RATE_WARN})")
        agg_reasons.append("DATA_RUN_RATE_WARN")
    
    # v1.10.0: Diversity KPI warnings
    # v1.12.0: Add FAIL thresholds for diversity (not just WARN)
    if unique_pairs < Thresholds.DIVERSITY_PAIRS_MIN:
        quality_warnings.append(f"DIVERSITY_PAIRS_FAIL({unique_pairs}<{Thresholds.DIVERSITY_PAIRS_MIN})")
        agg_reasons.append("DIVERSITY_PAIRS_FAIL")
    elif unique_pairs < Thresholds.DIVERSITY_PAIRS_TARGET:
        quality_warnings.append(f"DIVERSITY_PAIRS_LOW({unique_pairs}<{Thresholds.DIVERSITY_PAIRS_TARGET})")
        agg_reasons.append("DIVERSITY_PAIRS_LOW")
    if unique_routes < Thresholds.DIVERSITY_ROUTES_MIN:
        quality_warnings.append(f"DIVERSITY_ROUTES_FAIL({unique_routes}<{Thresholds.DIVERSITY_ROUTES_MIN})")
        agg_reasons.append("DIVERSITY_ROUTES_FAIL")
    elif unique_routes < Thresholds.DIVERSITY_ROUTES_TARGET:
        quality_warnings.append(f"DIVERSITY_ROUTES_LOW({unique_routes}<{Thresholds.DIVERSITY_ROUTES_TARGET})")
        agg_reasons.append("DIVERSITY_ROUTES_LOW")
    
    # Store quality warnings and reasons
    agg_data["quality_warnings"] = quality_warnings
    agg_data["policy_version"] = POLICY_VERSION
    
    # v1.12.1: Reworked agg_status logic with explicit threshold checks
    # Canonical statuses: PASS, FAIL, NO_DATA (with agg-specific WARN_* variants)
    # Check for FAIL-level threshold breaches explicitly
    has_fail_threshold = (
        any("FAIL" in w for w in quality_warnings) or  # DIVERSITY_PAIRS_FAIL, etc.
        fail_rate > Thresholds.AGG_FAIL_RATE_FAIL or
        data_run_rate < Thresholds.AGG_DATA_RUN_RATE_FAIL  # v1.12.1: data_run_rate as FAIL gate
    )
    has_warn_threshold = (
        any("ELEVATED" in w or "LOW" in w for w in quality_warnings) or
        warn_rate_core > Thresholds.AGG_WARN_RATE_FAIL
    )
    
    if in_warmup:
        agg_data["agg_status"] = "PASS_WARMUP"
        agg_data["agg_reasons"] = ["WARMUP"]
    elif has_fail_threshold:
        # v1.12.1: FAIL status with explicit reason (not FAIL_QUALITY)
        agg_data["agg_status"] = "FAIL"
        agg_data["agg_reasons"] = agg_reasons
    elif has_warn_threshold:
        agg_data["agg_status"] = "WARN_QUALITY"
        agg_data["agg_reasons"] = agg_reasons
    elif warn_count_core > 0 or fail_count > 0:
        agg_data["agg_status"] = "WARN"
        agg_data["agg_reasons"] = [f"WARN_RUNS({warn_count_core})", f"FAIL_RUNS({fail_count})"]
    else:
        agg_data["agg_status"] = "PASS"
        agg_data["agg_reasons"] = []
    
    # v1.9.4: Always update timestamp on emit
    agg_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # v1.9.4: Add runs_by_code_sha breakdown
    sha_counts = {}
    for r in runs:
        sha = r.get("code_sha", "unknown")
        sha_counts[sha] = sha_counts.get(sha, 0) + 1
    agg_data["runs_by_code_sha"] = sha_counts
    
    return agg_data
