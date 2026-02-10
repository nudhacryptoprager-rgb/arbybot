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
                data["schema_version"] = "m4:stability_agg:v1.8"
                return data
        except Exception:
            pass
    
    # Initialize new aggregator
    return {
        "schema_version": "m4:stability_agg:v1.8",  # v1.9.8: runs_since_sha, diversity
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
    git_ctx = get_git_context()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    
    # Archive current aggregator if exists
    if agg_path.exists():
        archive_name = f"m4_stability_agg_archive_{ts}.json"
        archive_path = agg_path.parent / archive_name
        
        with open(agg_path) as f:
            old_data = json.load(f)
        
        # Add archive metadata
        old_data["archived_at"] = datetime.now(timezone.utc).isoformat()
        old_data["archive_reason"] = reason
        old_data["archive_code_sha"] = git_ctx["code_sha"]
        
        with open(archive_path, "w") as f:
            json.dump(old_data, f, indent=2)
        
        print(f"[ROLLING-RESET] Archived: {archive_name} (runs={len(old_data.get('runs', []))})")
    
    # Create fresh aggregator
    fresh = {
        "schema_version": "m4:stability_agg:v1.8",  # v1.9.8: runs_since_sha, diversity
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reset_from_sha": git_ctx["code_sha"],
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
    max_runs: int = 200
) -> dict:
    """
    Emit run to rolling aggregator. Returns updated agg_data.
    
    Args:
        run_summary: Run summary dict with metrics
        agg_path: Path to aggregator file
        max_runs: Maximum runs to keep in window
        
    Returns:
        Updated aggregator data
    """
    agg_data = ensure_rolling_agg_exists(agg_path)
    
    # Extract key fields
    metrics = run_summary.get("metrics", {})
    status = run_summary.get("status", "UNKNOWN")
    signals_count = metrics.get("signals_count", 0)
    run_id = run_summary.get("run_id", "")
    reasons = run_summary.get("reasons", [])
    
    # Determine run status: NO_DATA if signals_count=0
    run_status = "NO_DATA" if signals_count == 0 else status
    
    # v1.9.3: Clean reasons for NO_DATA - no FAIL_* allowed
    if run_status == "NO_DATA":
        reasons = [r for r in reasons if not r.startswith("FAIL_")]
        if "NO_DATA" not in reasons:
            reasons = ["NO_DATA"] + reasons
        reasons = [r for r in reasons if r in ["NO_DATA", "WARN_LOW_SAMPLE"]]
    
    # DEDUPLICATION: Check if run_id already exists
    existing_run_ids = {r.get("run_id") for r in agg_data.get("runs", []) if r.get("run_id")}
    if run_id and run_id in existing_run_ids:
        print(f"[EMIT-AGG] SKIP duplicate run_id={run_id}")
        return agg_data
    
    # Get git context for run entry
    git_ctx = get_git_context()
    
    # Append light run info
    agg_data["runs"].append({
        "run_id": run_id,
        "timestamp": run_summary.get("timestamp", ""),
        "code_sha": git_ctx["code_sha"],
        "net_usdc": metrics.get("total_net_usdc", 0),
        "mae": metrics.get("mae_net_usdc", 0),
        "sign_rate": metrics.get("est_sign_correct_rate", 0),
        "reasons": reasons,
        "fragile_rate": metrics.get("fragile_rate", 0),
        "signals_count": signals_count,
        "run_status": run_status,
    })
    
    # Clean legacy: keep only light-format runs
    agg_data["runs"] = [r for r in agg_data["runs"] if "net_usdc" in r]
    runs = agg_data["runs"]
    
    # Rolling window: keep only last N runs
    if len(runs) > max_runs:
        agg_data["runs"] = runs[-max_runs:]
        runs = agg_data["runs"]
    
    # Compute quick stats
    agg_data = _compute_quick_stats(agg_data)
    
    # Write to disk
    with open(agg_path, "w") as f:
        json.dump(agg_data, f, indent=2)
    
    print(f"[EMIT-AGG] Updated: {agg_path} (runs={len(runs)}, "
          f"data_runs={agg_data['quick_stats']['pass_count'] + agg_data['quick_stats']['fail_count']}, "
          f"agg_status={agg_data.get('agg_status', 'UNKNOWN')})")
    
    return agg_data


def _compute_quick_stats(agg_data: dict) -> dict:
    """
    Compute quick stats and rolling window info for aggregator.
    
    v1.9.5 QUALITY GATES:
    - Enforces AGG_FRAGILE_P90_FAIL and AGG_LOW_SAMPLE_RATE_FAIL
    - Adds no_data_rate, effective_pass_rate
    - agg_status now has FAIL_QUALITY variant for quality gate failures
    """
    from m4.policy import Thresholds, POLICY_VERSION
    
    # Always upgrade schema_version on save (forward migration)
    agg_data["schema_version"] = "m4:stability_agg:v1.8"
    
    runs = agg_data.get("runs", [])
    
    # Count by status
    no_data_count = sum(1 for r in runs if r.get("run_status") == "NO_DATA" or r.get("signals_count", 0) == 0)
    data_runs = [r for r in runs if r.get("signals_count", 0) > 0]
    pass_count = sum(1 for r in data_runs if not any(x for x in r.get("reasons", []) if x.startswith("FAIL_")))
    fail_count = len(data_runs) - pass_count
    warn_count_core = sum(1 for r in data_runs if "WARN_DRIFT_MAE" in r.get("reasons", []))
    low_sample_count = sum(1 for r in runs if "WARN_LOW_SAMPLE" in r.get("reasons", []))
    total_net = sum(r.get("net_usdc", 0) for r in runs)
    total_signals = sum(r.get("signals_count", 0) for r in runs)
    
    # Percentile calculations
    fragile_rates = [r.get("fragile_rate", 0) for r in data_runs]
    mae_values = [r.get("mae", 0) for r in data_runs]
    net_values = [r.get("net_usdc", 0) for r in data_runs]
    
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
    in_warmup = len(runs) < min_runs or total_signals < min_signals
    
    # Quality metrics
    no_data_rate = no_data_count / len(runs) if runs else 0
    low_sample_rate = low_sample_count / len(runs) if runs else 0
    effective_pass_rate = pass_count / len(runs) if runs else 0  # True rate including NO_DATA
    pass_rate = pass_count / len(data_runs) if data_runs else 0  # Rate excluding NO_DATA
    warn_rate_core = warn_count_core / len(data_runs) if data_runs else 0
    fail_rate = fail_count / len(data_runs) if data_runs else 0
    fragile_rate_p90 = percentile(fragile_rates, 90)
    mae_p90 = percentile(mae_values, 90)
    
    agg_data["runs_included"] = len(runs)
    agg_data["runs_in_window"] = len(runs)
    agg_data["rolling_window"] = {
        "max": Thresholds.ROLLING_WINDOW_MAX,
        "current": len(runs),
        "min_runs": min_runs,
        "min_signals": min_signals,
        "in_warmup": in_warmup,
    }
    
    # v1.9.8: Diversity metrics - detect duplicate signals pattern
    unique_net_values = len(set(round(r.get("net_usdc", 0), 2) for r in data_runs))
    net_diversity_rate = unique_net_values / len(data_runs) if data_runs else 0
    
    # v1.9.8: Stats for current code_sha only (since_sha view)
    from m4.evidence import get_git_context
    current_sha = get_git_context()["code_sha"]
    current_sha_runs = [r for r in runs if r.get("code_sha") == current_sha]
    current_sha_data_runs = [r for r in current_sha_runs if r.get("signals_count", 0) > 0]
    current_sha_pass = sum(1 for r in current_sha_data_runs if not any(x for x in r.get("reasons", []) if x.startswith("FAIL_")))
    
    agg_data["quick_stats"] = {
        "pass_count": pass_count,
        "fail_count": fail_count,
        "no_data_count": no_data_count,
        "warn_count_core": warn_count_core,
        "low_sample_count": low_sample_count,
        "pass_rate": round(pass_rate, 4),
        "effective_pass_rate": round(effective_pass_rate, 4),  # v1.9.5: PRIMARY metric
        "no_data_rate": round(no_data_rate, 4),                # v1.9.5: NO_DATA fraction
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
    }
    
    # v1.9.8: Add runs_since_sha (current code stability)
    agg_data["runs_since_sha"] = {
        "sha": current_sha,
        "runs_count": len(current_sha_runs),
        "data_runs_count": len(current_sha_data_runs),
        "pass_count": current_sha_pass,
        "effective_pass_rate": round(current_sha_pass / len(current_sha_runs), 4) if current_sha_runs else 0,
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
    
    # Store quality warnings and reasons
    agg_data["quality_warnings"] = quality_warnings
    agg_data["policy_version"] = POLICY_VERSION
    
    # Determine agg_status with quality gate enforcement
    # v1.9.6: agg_reasons populated for ALL non-PASS statuses
    if in_warmup:
        agg_data["agg_status"] = "PASS_WARMUP"
        agg_data["agg_reasons"] = ["WARMUP"]
    elif any("HIGH" in w for w in quality_warnings):
        # Quality gate failure - data quality too poor for reliable signal
        agg_data["agg_status"] = "FAIL_QUALITY"
        agg_data["agg_reasons"] = agg_reasons  # Contains HIGH tokens
    elif fail_rate > Thresholds.AGG_FAIL_RATE_FAIL:
        agg_data["agg_status"] = "FAIL"
        agg_data["agg_reasons"] = agg_reasons + [f"FAIL_RATE_HIGH({fail_rate:.2f})"]
    elif warn_rate_core > Thresholds.AGG_WARN_RATE_FAIL:
        agg_data["agg_status"] = "WARN_EXCESSIVE"
        agg_data["agg_reasons"] = agg_reasons + [f"WARN_RATE_HIGH({warn_rate_core:.2f})"]
    elif any("ELEVATED" in w for w in quality_warnings):
        agg_data["agg_status"] = "WARN_QUALITY"
        agg_data["agg_reasons"] = agg_reasons  # Contains ELEVATED tokens
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
