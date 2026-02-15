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

logger = logging.getLogger("strategy.artifacts")


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
    scan_path = reports_dir / f"scan_{timestamp}.json"
    with open(scan_path, "w") as f:
        json.dump(scan_data, f, indent=2, default=str)
    artifacts["scan"] = scan_path
    truth_path = reports_dir / f"truth_report_{timestamp}.json"
    with open(truth_path, "w") as f:
        json.dump(truth_data, f, indent=2, default=str)
    artifacts["truth_report"] = truth_path
    reject_path = reports_dir / f"reject_histogram_{timestamp}.json"
    with open(reject_path, "w") as f:
        json.dump(reject_data, f, indent=2, default=str)
    artifacts["reject_histogram"] = reject_path
    # LEGACY: snapshots/ (backward compat)
    snapshots_dir = output_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    snapshot_scan = snapshots_dir / f"scan_{timestamp}.json"
    with open(snapshot_scan, "w") as f:
        json.dump(scan_data, f, indent=2, default=str)
    scan_log = output_dir / "scan.log"
    with open(scan_log, "w") as f:
        f.write(f"scan completed: {timestamp}\n")
    return artifacts


def build_truth_data(
    config: Dict[str, Any],
    stats: Dict[str, Any],
    current_block: int,
    spread_signals: List[Dict[str, Any]],
    suspect_examples: List[Dict[str, Any]],
    infra_payload: Dict[str, Any],
    raw_bps: int,
    spread_threshold_bps: int,
) -> Dict[str, Any]:
    """
    Build truth report data structure.
    
    Returns:
        Truth report dict
    """
    now = datetime.now(timezone.utc).isoformat()
    
    truth_data = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": now,
        "run_mode": "REGISTRY_REAL",
        "execution_enabled": False,
        "execution_ready_count": 0,
        "execution_blocker": CURRENT_EXECUTION_BLOCKER.value,
        "execution_blocker_details": "EXECUTION_DISABLED_M5_0 - no execution cost model",
        "paper_cost_model_available": True,
        "execution_cost_model_available": False,
        "chain_id": config.get("chain_id", 42161),
        "current_block": current_block,
        "config_params": {
            "min_spread_bps": spread_threshold_bps,
            "min_net_pnl_usdc_est": config.get("min_net_pnl_usdc_est", 0.0),
            "paper_size_usd": config.get("paper_size_usd", 1000),
            "gas_usd_estimate": config.get("gas_usd_estimate", 0.10),
            "paper_slippage_bps": config.get("paper_slippage_bps", 0),
            "autosize": config.get("autosize", {}),
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
        "execution_pnl": {
            "signal_pnl_usdc": "0.000000",
            "would_execute_pnl_usdc": "0.000000",
            "gross_pnl_usdc": "0.000000",
            "net_pnl_usdc": None,
            "net_pnl_bps": None,
            "cost_model_available": False,
        },
        "pnl": {
            "_deprecated": True,
            "_migration": "Use 'execution_pnl' instead. This field will be removed in schema v3.3.",
            "signal_pnl_usdc": "0.000000",
            "would_execute_pnl_usdc": "0.000000",
            "gross_pnl_usdc": "0.000000",
            "net_pnl_usdc": None,
            "net_pnl_bps": None,
            "cost_model_available": False,
        },
        "spread_signals": spread_signals,
        "signals_total": len(spread_signals),
        "opportunities_total": len([s for s in spread_signals if s.get("is_net_positive_est")]),
        "infra": infra_payload,
        "suspect_summary": {
            "count": stats.get("suspect_quotes", 0),
            "reasons": stats.get("suspect_reasons", {}),
            "examples": suspect_examples,
        },
        # M4.2: Opportunity engine integration
        "opportunity_engine": stats.get("opportunity_engine", {}),
        # v2.1.0: Roundtrip reality check (Step 4 - roundtrip in truth_report)
        "roundtrip_summary": {
            "enabled": stats.get("roundtrip", {}).get("enabled", False),
            "evaluated_count": stats.get("roundtrip", {}).get("evaluated_count", 0),
            "profitable_count": stats.get("roundtrip", {}).get("profitable_count", 0),
            "real_quote_count": stats.get("roundtrip", {}).get("real_quote_count", 0),
            "best_net_pnl_bps": stats.get("roundtrip", {}).get("best_net_pnl_bps"),
        },
        # v2.1.0: truth_mode_m42 - when true, one-leg PnL is DIAGNOSTIC only, roundtrip is canonical
        "truth_mode_m42": config.get("truth_mode_m42", False),
        "profit_realism_status": (
            "ROUNDTRIP_PROFITABLE" if stats.get("roundtrip", {}).get("profitable_count", 0) > 0
            else "ROUNDTRIP_NOT_PROFITABLE" if stats.get("roundtrip", {}).get("evaluated_count", 0) > 0
            else "ONE_LEG_ONLY_DIAGNOSTIC"
        ),
    }
    
    try:
        truth_data["price_sanity_deviation_bps_raw_max"] = int(raw_bps)
    except Exception:
        truth_data["price_sanity_deviation_bps_raw_max"] = None
    
    return truth_data


def build_reject_data(
    config: Dict[str, Any],
    current_block: int,
    sanity_rejects: List[Dict[str, Any]],
    rejected_quotes: List[Dict[str, Any]],
    stats: Dict[str, Any],
    infra_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build reject histogram data structure.
    
    Note: sanity_rejects is a SUBSET of rejected_quotes (filtered by reason).
    We use rejected_quotes as canonical rejects list to avoid double-counting.
    
    Returns:
        Reject histogram dict
    """
    now = datetime.now(timezone.utc).isoformat()
    # v2.1.0: FIX double-count bug - sanity_rejects is subset of rejected_quotes
    total_rejects = len(rejected_quotes)
    
    # v2.1.0 Step 8: Build reason histogram with sample details
    reason_histogram = {}
    for r in rejected_quotes:
        reason = r.get("reason", "UNKNOWN")
        reason_histogram[reason] = reason_histogram.get(reason, 0) + 1
    
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
        "chain_id": config.get("chain_id", 42161),
        "current_block": current_block,
        "rejects": rejected_quotes,  # canonical list (includes sanity_rejects)
        "sample_rejects": rejected_quotes[:10] if rejected_quotes else [],
        "rejects_total": total_rejects,
        "total_rejects": total_rejects,  # deprecated alias
        "no_rejects": total_rejects == 0,
        "sanity_rejects_count": len(sanity_rejects),  # v2.1.0: separate field
        "price_sanity_failed": len(sanity_rejects),
        "pool_missing_count": stats.get("pool_missing_count", 0),
        "v3_slot0_failed_count": stats.get("v3_slot0_failed_count", 0),
        "price_outlier_count": sum(1 for r in rejected_quotes if r.get("reason") == "PRICE_OUTLIER"),
        # v2.1.0 Step 8: Enhanced histogram and samples
        "reason_histogram": reason_histogram,
        "price_sanity_samples": price_sanity_samples,
        "infra": infra_payload,
    }


def build_scan_data(
    config: Dict[str, Any],
    current_block: int,
    stats: Dict[str, Any],
    quotes_sample: List[Dict[str, Any]],
    infra_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build scan data structure.
    
    Returns:
        Scan data dict
    """
    now = datetime.now(timezone.utc).isoformat()
    dexes_active_list = sorted({q.get("dex_id") for q in quotes_sample})
    
    return {
        "timestamp": now,
        "run_mode": "REGISTRY_REAL",
        "chain_id": config.get("chain_id", 42161),
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
        "infra": infra_payload,
    }
