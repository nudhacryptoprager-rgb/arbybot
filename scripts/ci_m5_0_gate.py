#!/usr/bin/env python3
# PATH: scripts/ci_m5_0_gate.py
"""
M5_0 CI Gate v2.1.0.

STATUS: FROZEN (2026-02-08)
Changes only for M4 execution requirements. M5_0 infra is complete.

CANONICAL COMMANDS:
  python scripts/ci_m5_0_gate.py --offline
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

MODES (MUTUALLY EXCLUSIVE):
  --offline   ALWAYS works, IGNORES ALL ENV
  --online    Runs real scan, IGNORES ARBY_RUN_DIR

ENV VARIABLES (for --online and ADVANCED modes):
  ARBY_CONFIG       Override --config
  ARBY_CYCLES       Override --cycles
  ARBY_OUTPUT_ROOT  Override --output-root
  ARBY_RUN_DIR      [ADVANCED only] Explicit run directory
  ARBY_REQUIRE_REAL Require real (non-fixture) artifacts

EXIT CODES: 0=PASS, 1=FAIL validation, 2=FAIL missing, 3=FAIL scanner
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure repository root is on sys.path so `python scripts/ci_m5_0_gate.py` works
try:
    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT))
except Exception:
    pass

# Load .env from repo root (best-effort)
from core.env import load_root_dotenv
load_root_dotenv()

# Import canonical PRICE_SCALE_BOUNDS from core.constants
from core.constants import PRICE_SCALE_BOUNDS as CORE_PRICE_SCALE_BOUNDS

# v3.2.21: Primary rolling chain - only this chain can update rolling artifacts
# This prevents MIXED_CHAIN_KEYS contamination from multi-chain bring-up runs
PRIMARY_ROLLING_CHAIN = "arbitrum_one"

# Import artifact invariants for unified validation
from core.artifact_invariants import (
    RunMode,
    check_cross_artifact_invariants,
    validate_block_number,
    validate_schema_version as invariants_validate_schema,
)

__version__ = "2.6.0"  # v3.2.69: Fallback cross_dex_pairs_count from signals + truth_report


# =============================================================================
# v2.4.0: Non-stop loop helpers
# =============================================================================

def check_roundtrip_profitable(run_dir: Path) -> Tuple[bool, int, str]:
    """
    Check if the run produced a profitable roundtrip.
    
    Returns:
        Tuple[is_profitable, profitable_count, profit_realism_status]
    """
    try:
        reports_dir = run_dir / "reports"
        truth_reports = sorted(reports_dir.glob("truth_report_*.json"))
        if not truth_reports:
            return False, 0, "NO_TRUTH_REPORT"
        
        with open(truth_reports[-1], "r", encoding="utf-8") as f:
            truth = json.load(f)
        
        profit_realism_status = truth.get("profit_realism_status", "UNKNOWN")
        roundtrip_summary = truth.get("roundtrip_summary", {})
        profitable_count = roundtrip_summary.get("profitable_count", 0)
        
        is_profitable = profitable_count > 0
        return is_profitable, profitable_count, profit_realism_status
    except Exception as e:
        return False, 0, f"ERROR: {e}"


def emit_roundtrip_alert(run_dir: Path, profitable_count: int, profit_realism_status: str) -> None:
    """
    Emit alert when profitable roundtrip is detected.
    Writes to rolling directory (runtime-only, gitignored).
    """
    print(f"\n{'='*60}")
    print(f"[ALERT] ROUNDTRIP_PROFITABLE detected!")
    print(f"  profitable_count: {profitable_count}")
    print(f"  profit_realism_status: {profit_realism_status}")
    print(f"  runDir: {run_dir}")
    print(f"{'='*60}\n")
    
    # Write alert file to rolling directory
    try:
        rolling_dir = Path("data/runs/_rolling")
        rolling_dir.mkdir(parents=True, exist_ok=True)
        alert_path = rolling_dir / "last_roundtrip_profitable.json"
        
        alert_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_dir": str(run_dir),
            "run_dir_name": run_dir.name,
            "profitable_count": profitable_count,
            "profit_realism_status": profit_realism_status,
        }
        
        with open(alert_path, "w", encoding="utf-8") as f:
            json.dump(alert_data, f, indent=2)
        
        print(f"[ALERT] Written: {alert_path}")
    except Exception as e:
        print(f"[ALERT] WARN: Failed to write alert file: {e}")

DEFAULT_OUTPUT_ROOT = Path("data/runs")
DEFAULT_CONFIG = "config/real_minimal.yaml"


def generate_fixture_artifacts(output_dir: Path, timestamp: str) -> Dict[str, Path]:
    """Generate fixture artifacts for --offline."""
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    artifacts = {}
    now = datetime.now(timezone.utc).isoformat()
    
    scan_data = {
        "schema_version": "3.2.0",
        "timestamp": now,
        "run_mode": "FIXTURE_OFFLINE",
        "current_block": 100,
        "chain_id": 42161,
        "infra": {"rpc_provider": "fixture", "transport": "http", "ws_enabled": False, "tenderly_enabled": False},
        # Top-level metrics
        "quotes_total": 4,
        "quotes_fetched": 4,
        "dexes_active": 2,
        "price_sanity_passed": 3,
        "price_sanity_failed": 1,
        # Nested stats
        "stats": {
            "quotes_total": 4, "quotes_fetched": 4, "gates_passed": 3,
            "dexes_active": 2, "price_sanity_passed": 3, "price_sanity_failed": 1,
        },
        # v3.2.19: Per-DEX promotion metrics
        "per_dex_stats": {
            "uniswap_v3": {
                "quotes_fetched": 2,
                "quotes_rejected": 0,
                "quotes_total": 2,
                "quote_success_rate": 1.0,
                "top_reject_reasons": [],
                "health_status": "HEALTHY",
            },
            "sushiswap_v3": {
                "quotes_fetched": 2,
                "quotes_rejected": 1,
                "quotes_total": 3,
                "quote_success_rate": 0.6667,
                "top_reject_reasons": ["PRICE_SANITY_FAILED"],
                "health_status": "HEALTHY",
            },
        },
    }
    scan_path = reports_dir / f"scan_{timestamp}.json"
    with open(scan_path, "w") as f:
        json.dump(scan_data, f, indent=2)
    artifacts["scan"] = scan_path
    
    truth_data = {
        "schema_version": "3.2.0",
        "timestamp": now,
        "run_mode": "FIXTURE_OFFLINE",
        "current_block": 100,
        "chain_id": 42161,
        "execution_enabled": False,
        "execution_blocker": "EXECUTION_DISABLED",
        "execution_ready_count": 0,
        "infra": {"rpc_provider": "fixture", "transport": "http", "ws_enabled": False, "tenderly_enabled": False},
        # Top-level metrics
        "quotes_total": 4,
        "quotes_fetched": 4,
        "dexes_active": 2,
        "price_sanity_passed": 3,
        "price_sanity_failed": 1,
        # Nested health
        "health": {
            "quotes_total": 4, "quotes_fetched": 4, "gates_passed": 3,
            "dexes_active": 2, "price_sanity_passed": 3, "price_sanity_failed": 1,
            "rpc_success_rate": 1.0,
        },
        # Nested stats (v3.2.5: includes roundtrip)
        "stats": {
            "quotes_total": 4, "quotes_fetched": 4, "gates_passed": 3,
            "dexes_active": 2, "price_sanity_passed": 3, "price_sanity_failed": 1,
            "roundtrip": {
                "enabled": True,
                "evaluated_count": 0,
                "profitable_count": 0,
                "candidates_total": 0,
                "gated_by_economics": 0,
                "rejected_reasons": {},
                "warnings": [],  # v3.2.5: Always present
            },
        },
        # Spread signals (empty for fixture)
        "spread_signals": [],
    }
    truth_path = reports_dir / f"truth_report_{timestamp}.json"
    with open(truth_path, "w") as f:
        json.dump(truth_data, f, indent=2)
    artifacts["truth_report"] = truth_path
    
    # reject_histogram: Contains individual reject samples (not aggregated histogram)
    # Semantics: "rejects" is a list of suspect/rejected quotes with details
    # "rejects_total" is the count of samples, "price_sanity_failed" is aggregate metric
    reject_data = {
        "schema_version": "3.2.0",
        "timestamp": now,
        "run_mode": "FIXTURE_OFFLINE",
        "chain_id": 42161,
        "current_block": 100,
        "infra": {"rpc_provider": "fixture", "transport": "http", "ws_enabled": False, "tenderly_enabled": False},
        # "rejects" = list of individual reject samples (NOT aggregated counts)
        "rejects": [{
            "pair": "WETH/USDC", "dex_id": "sushiswap_v3",
            "deviation_bps": 10000, "deviation_bps_capped": False,
            "inversion_applied": False, "suspect_quote": True,
        }],
        "rejects_total": 1,      # Count of samples in "rejects" list
        "total_rejects": 1,      # Deprecated alias
        "price_sanity_failed": 1,  # Aggregate metric (may differ from rejects_total)
        "no_rejects": False,
        # v3.2.19: Per-DEX promotion metrics
        "per_dex_stats": {
            "uniswap_v3": {
                "quotes_fetched": 2,
                "quotes_rejected": 0,
                "quotes_total": 2,
                "quote_success_rate": 1.0,
                "top_reject_reasons": [],
                "health_status": "HEALTHY",
            },
            "sushiswap_v3": {
                "quotes_fetched": 2,
                "quotes_rejected": 1,
                "quotes_total": 3,
                "quote_success_rate": 0.6667,
                "top_reject_reasons": ["PRICE_SANITY_FAILED"],
                "health_status": "HEALTHY",
            },
        },
    }
    reject_path = reports_dir / f"reject_histogram_{timestamp}.json"
    with open(reject_path, "w") as f:
        json.dump(reject_data, f, indent=2)
    artifacts["reject_histogram"] = reject_path
    
    return artifacts


def discover_artifacts(run_dir: Path) -> Dict[str, Optional[Path]]:
    """
    Discover artifacts in run directory.
    
    Looks in:
    1. reports/ (PRIMARY - ci_m5_0_gate.py standard)
    2. snapshots/ (FALLBACK - legacy location)
    """
    artifacts = {"scan": None, "truth_report": None, "reject_histogram": None}
    
    # Try reports/ first (PRIMARY)
    reports_dir = run_dir / "reports"
    if reports_dir.exists():
        for f in reports_dir.glob("*.json"):
            name = f.name
            if name.startswith("scan_") and artifacts["scan"] is None:
                artifacts["scan"] = f
            elif name.startswith("truth_report_") and artifacts["truth_report"] is None:
                artifacts["truth_report"] = f
            elif name.startswith("reject_histogram_") and artifacts["reject_histogram"] is None:
                artifacts["reject_histogram"] = f
    
    # Fallback to snapshots/ for scan only
    if artifacts["scan"] is None:
        snapshots_dir = run_dir / "snapshots"
        if snapshots_dir.exists():
            for f in snapshots_dir.glob("scan_*.json"):
                artifacts["scan"] = f
                break
    
    return artifacts


def get_run_dir_candidates(output_root: Path = DEFAULT_OUTPUT_ROOT) -> List[Path]:
    """Get run directories sorted by recency."""
    if not output_root.exists():
        return []
    
    candidates = []
    for d in output_root.iterdir():
        if d.is_dir():
            # Check both reports/ and snapshots/
            has_reports = (d / "reports").exists() and list((d / "reports").glob("*.json"))
            has_snapshots = (d / "snapshots").exists() and list((d / "snapshots").glob("*.json"))
            if has_reports or has_snapshots:
                all_files = list((d / "reports").glob("*.json")) if has_reports else []
                all_files += list((d / "snapshots").glob("*.json")) if has_snapshots else []
                if all_files:
                    mtime = max(f.stat().st_mtime for f in all_files)
                    candidates.append((d, mtime))
    
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in candidates]


def validate_schema_version(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate schema_version exists and is valid."""
    version = data.get("schema_version")
    if not version:
        return False, "Missing schema_version"
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        return False, f"Invalid schema_version: {version}"
    return True, f"schema_version={version}"


def validate_anti_placeholder(data: Dict[str, Any], require_real: bool = False) -> Tuple[bool, str]:
    """Validate anti-placeholder invariant: no quotes with null pool_address/tick/sqrt_price_x96.
    
    This catches the BLOCKER bug where fake quotes with placeholder prices slipped through.
    
    M4.2 UPDATE: When quote_source="quoter_v2", tick/sqrt_price_x96 are legitimately null
    because QuoterV2 returns amount_out directly without tick/sqrt state.
    """
    quotes = data.get("quotes_sample", [])
    if not quotes:
        # No quotes to check
        return True, "anti_placeholder OK (no quotes_sample)"
    
    violations = []
    for i, q in enumerate(quotes):
        dex_id = q.get("dex_id", "unknown")
        pair = f"{q.get('token_in', '?')}/{q.get('token_out', '?')}"
        quote_source = q.get("quote_source", "slot0")
        
        # Check pool_address
        pool_addr = q.get("pool_address")
        if pool_addr is None or pool_addr == "" or pool_addr == "0x0000000000000000000000000000000000000000":
            violations.append(f"quote[{i}] {dex_id} {pair}: pool_address=null")
        
        # Check tick/sqrt_price_x96 for v3 pools (only if NOT quoter_v2)
        # M4.2: quoter_v2 quotes legitimately have null tick/sqrt because
        # QuoterV2 returns amount_out directly without pool state
        if "v3" in dex_id.lower() and quote_source != "quoter_v2":
            tick = q.get("tick")
            sqrt_price = q.get("sqrt_price_x96")
            if tick is None:
                violations.append(f"quote[{i}] {dex_id} {pair}: tick=null (v3 requires tick)")
            if sqrt_price is None:
                violations.append(f"quote[{i}] {dex_id} {pair}: sqrt_price_x96=null (v3 requires sqrt)")
    
    if violations:
        msg = f"ANTI_PLACEHOLDER VIOLATION: {len(violations)} placeholder quotes: {violations[:3]}"
        if require_real:
            return False, msg
        else:
            return True, f"WARN: {msg}"  # Warn in offline mode
    
    return True, f"anti_placeholder OK ({len(quotes)} quotes checked)"


# PRICE_SCALE_BOUNDS - import from canonical source (core.constants)
# Local alias for backward compatibility with tests that import from here
PRICE_SCALE_BOUNDS = CORE_PRICE_SCALE_BOUNDS


def validate_price_scale(data: Dict[str, Any], require_real: bool = False) -> Tuple[bool, str]:
    """Validate price scale invariant: detect inverted direction bugs.
    
    This catches bugs where price is calculated as token0/token1 instead of token1/token0
    (or vice versa), resulting in prices that are orders of magnitude wrong.
    
    M4.2 UPDATE: Tolerance for < 10% of quotes with wrong scale (data quality issue,
    not a code bug). Fails only if > 10% of quotes have wrong scale.
    """
    quotes = data.get("quotes_sample", [])
    if not quotes:
        return True, "price_scale OK (no quotes_sample)"
    
    violations = []
    for q in quotes:
        pair = f"{q.get('token_in', '?')}/{q.get('token_out', '?')}"
        price_str = q.get("price_exact") or q.get("price")
        if not price_str:
            continue
        
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            continue
        
        bounds = PRICE_SCALE_BOUNDS.get(pair)
        if bounds:
            min_p, max_p = bounds
            if price < min_p or price > max_p:
                violations.append(
                    f"{pair}: price={price:.6g} outside [{min_p}, {max_p}] (likely inverted direction)"
                )
    
    if violations:
        # M4.2: Tolerate up to 10% bad quotes (data quality issue from low-liquidity pools)
        violation_rate = len(violations) / len(quotes) if quotes else 0
        msg = f"PRICE_SCALE VIOLATION: {len(violations)}/{len(quotes)} quotes ({violation_rate:.1%}) with wrong scale: {violations[:3]}"
        
        if require_real and violation_rate > 0.10:
            # More than 10% violations = likely code bug
            return False, msg
        else:
            # Few violations = data quality issue, warn only
            return True, f"WARN: {msg}"
    
    return True, f"price_scale OK ({len(quotes)} quotes checked)"


def validate_coverage(data: Dict[str, Any], min_pairs: int = 5, min_pools: int = 6) -> Tuple[bool, str]:
    """Validate minimum coverage: pairs_count >= min_pairs and pools_quoted >= min_pools.
    
    Prevents PASS on empty universe.
    """
    quotes = data.get("quotes_sample", [])
    
    # Count unique pairs
    pairs = set()
    pools = set()
    for q in quotes:
        pair = f"{q.get('token_in', '?')}/{q.get('token_out', '?')}"
        pairs.add(pair)
        pool = q.get("pool_address")
        if pool:
            pools.add(pool)
    
    pairs_count = len(pairs)
    pools_count = len(pools)
    
    issues = []
    if pairs_count < min_pairs:
        issues.append(f"pairs_count={pairs_count} < {min_pairs}")
    if pools_count < min_pools:
        issues.append(f"pools_count={pools_count} < {min_pools}")
    
    if issues:
        return False, f"COVERAGE FAIL: {', '.join(issues)}"
    
    return True, f"coverage OK (pairs={pairs_count} pools={pools_count})"


def validate_cross_check(
    scan_data: Dict[str, Any],
    daily_data: Dict[str, Any],
    strict: bool = False
) -> Tuple[bool, str]:
    """Cross-check daily_report vs scan for consistency.
    
    Validates:
    - daily.quotes_fetched == scan.quotes_fetched
    - daily.checks_count == scan.quotes_total
    - If reject_histogram.total_rejects > 0, daily.top_reject_reasons must not be empty
    
    Returns (ok, message).
    """
    issues = []
    
    scan_quotes_fetched = scan_data.get("quotes_fetched", 0)
    daily_quotes_fetched = daily_data.get("quotes_fetched", 0)
    
    if scan_quotes_fetched != daily_quotes_fetched:
        msg = f"quotes_fetched mismatch: scan={scan_quotes_fetched}, daily={daily_quotes_fetched}"
        if strict:
            issues.append(msg)
        # Non-strict: just warn
    
    scan_quotes_total = scan_data.get("quotes_total", 0)
    daily_checks_count = daily_data.get("checks_count", 0)
    
    if scan_quotes_total != daily_checks_count:
        msg = f"quotes_total mismatch: scan={scan_quotes_total}, daily.checks_count={daily_checks_count}"
        if strict:
            issues.append(msg)
    
    if issues:
        return False, f"CROSS_CHECK FAIL: {'; '.join(issues)}"
    
    return True, "cross_check OK"


def validate_scan_fields(data: Dict[str, Any], path: Optional[Path] = None, require_real: bool = False) -> Tuple[bool, str]:
    """Validate top-level scan fields required by M5_0.

    Returns (ok, message).
    """
    try:
        keys = list(data.keys())
        # schema and run_mode already checked elsewhere
        cb = data.get("current_block")
        if cb is None:
            return False, f"scan.current_block missing; keys={keys}"
        if not isinstance(cb, int):
            return False, f"scan.current_block not int: {type(cb).__name__} ({cb})"
        if require_real and cb <= 0:
            return False, f"scan.current_block must be >0 for online runs, got {cb}"

        quotes_total = data.get("quotes_total")
        if quotes_total is None:
            return False, f"scan.quotes_total missing; keys={keys}"
        # allow zero in offline but require >=1 in online
        if require_real and int(quotes_total) < 1:
            return False, f"scan.quotes_total < 1 for online runs: {quotes_total}"

        dexes_active = data.get("dexes_active")
        if dexes_active is None:
            return False, f"scan.dexes_active missing; keys={keys}"
        if int(dexes_active) < 1:
            return False, f"scan.dexes_active < 1: {dexes_active}"

        return True, f"scan fields OK"
    except Exception as e:
        return False, f"Exception validating scan fields: {type(e).__name__}: {e}"


def validate_truth_report_fields(data: Dict[str, Any], path: Optional[Path] = None, require_real: bool = False) -> Tuple[bool, str]:
    """Validate truth_report required fields per M5_0.

    Returns (ok, message).
    """
    try:
        keys = list(data.keys())
        # schema and run_mode expected to be checked
        cb = data.get("current_block")
        if cb is None:
            return False, f"truth_report.current_block missing; keys={keys}"
        if not isinstance(cb, int):
            return False, f"truth_report.current_block not int: {type(cb).__name__} ({cb})"
        if require_real and cb <= 0:
            return False, f"truth_report.current_block must be >0 for online runs, got {cb}"

        quotes_total = data.get("quotes_total")
        quotes_fetched = data.get("quotes_fetched")
        if quotes_total is None or quotes_fetched is None:
            return False, f"truth_report.quotes_total/quotes_fetched missing; keys={keys}"
        if require_real and int(quotes_fetched) < 1:
            return False, f"truth_report.quotes_fetched < 1 for online runs: {quotes_fetched}"

        dexes_active = data.get("dexes_active")
        if dexes_active is None:
            return False, f"truth_report.dexes_active missing; keys={keys}"
        if int(dexes_active) < 1:
            return False, f"truth_report.dexes_active < 1: {dexes_active}"

        # price sanity metrics existence
        if "price_sanity_passed" not in data or "price_sanity_failed" not in data:
            # also check nested health
            health = data.get("health", {}) or {}
            if "price_sanity_passed" not in health or "price_sanity_failed" not in health:
                return False, f"price_sanity_passed/failed missing in truth_report (keys={keys})"

        return True, "truth_report fields OK"
    except Exception as e:
        return False, f"Exception validating truth_report fields: {type(e).__name__}: {e}"


def validate_reject_histogram_fields(data: Dict[str, Any], path: Optional[Path] = None, require_real: bool = False) -> Tuple[bool, str]:
    try:
        keys = list(data.keys())
        if "rejects" not in data:
            return False, f"reject_histogram.missing 'rejects' key; keys={keys}"
        if not isinstance(data.get("rejects"), list):
            return False, f"reject_histogram.rejects not a list"
        
        # Cross-artifact invariant: current_block and chain_id required
        cb = data.get("current_block")
        if cb is None:
            return False, f"reject_histogram.current_block missing (cross-artifact invariant); keys={keys}"
        
        chain_id = data.get("chain_id")
        if chain_id is None:
            return False, f"reject_histogram.chain_id missing; keys={keys}"
        
        # Canonical totals field
        rejects_total = data.get("rejects_total") or data.get("total_rejects")
        if rejects_total is None:
            return False, f"reject_histogram.rejects_total missing; keys={keys}"
        
        return True, "reject_histogram fields OK"
    except Exception as e:
        return False, f"Exception validating reject_histogram: {type(e).__name__}: {e}"


def validate_health_metrics(data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate health metrics exist and are reasonable."""
    # Check both top-level and nested health
    health = data.get("health", {})
    stats = data.get("stats", {})
    
    quotes_total = data.get("quotes_total") or health.get("quotes_total") or stats.get("quotes_total", 0)
    dexes_active = data.get("dexes_active") or health.get("dexes_active") or stats.get("dexes_active", 0)
    
    if quotes_total < 1:
        return False, f"quotes_total={quotes_total} < 1"
    if dexes_active < 1:
        return False, f"dexes_active={dexes_active} < 1"
    
    return True, f"quotes_total={quotes_total}, dexes_active={dexes_active}"


def validate_artifacts(artifacts: Dict[str, Optional[Path]], require_real: bool = False,
                       require_infra_hosts: bool = False,
                       require_cross_artifact: bool = False,
                       require_tenderly: bool = False,
                       require_cross_dex: bool = True) -> Tuple[bool, List[str]]:
    """Validate all artifacts.
    
    Args:
        require_cross_dex: If True (default), discovery_runtime must have cross_dex_pairs_count >= 1.
                           If False (e.g. Scroll with single DEX), allows cross_dex_pairs_count=0.
    """
    messages = []
    all_passed = True
    
    # Check all artifacts exist
    for name, path in artifacts.items():
        if path is None:
            messages.append(f"FAIL: {name} missing")
            all_passed = False
            continue
        messages.append(f"OK: {name} found")
    
    if not all_passed:
        return False, messages
    
    # Validate each artifact
    loaded_data: Dict[str, Dict[str, Any]] = {}
    for name, path in artifacts.items():
        try:
            with open(path) as f:
                data = json.load(f)
            loaded_data[name] = data
            
            # Validate schema_version (required for all)
            ok, msg = validate_schema_version(data)
            messages.append(f"{'OK' if ok else 'FAIL'}: {name} - {msg}")
            if not ok:
                all_passed = False
            
            # Check run_mode presence and value
            if "run_mode" not in data:
                messages.append(f"FAIL: {name} - missing run_mode")
                all_passed = False
            else:
                run_mode = data.get("run_mode", "")
                if require_real and "FIXTURE" in run_mode:
                    messages.append(f"FAIL: {name} - fixture rejected (require_real=True)")
                    all_passed = False
                else:
                    messages.append(f"OK: {name} - run_mode={run_mode}")
            
            # Validate health metrics for truth_report
            if name == "truth_report":
                ok, msg = validate_health_metrics(data)
                messages.append(f"{'OK' if ok else 'FAIL'}: {name} - {msg}")
                if not ok:
                    all_passed = False
                # Strict truth_report field validation
                ok_tr, msg_tr = validate_truth_report_fields(data, path)
                messages.append(f"{'OK' if ok_tr else 'FAIL'}: {name} - {msg_tr}")
                if not ok_tr:
                    all_passed = False
            
            # Anti-placeholder validation for scan (CRITICAL)
            if name == "scan":
                ok_ap, msg_ap = validate_anti_placeholder(data, require_real=require_real)
                if ok_ap:
                    messages.append(f"OK: {name} - {msg_ap}")
                else:
                    messages.append(f"FAIL: {name} - {msg_ap}")
                    all_passed = False
                
                # Price scale validation (CRITICAL - detects inverted direction bugs)
                ok_ps, msg_ps = validate_price_scale(data, require_real=require_real)
                if ok_ps:
                    messages.append(f"OK: {name} - {msg_ps}")
                else:
                    messages.append(f"FAIL: {name} - {msg_ps}")
                    all_passed = False
                
                # Coverage validation for online runs
                if require_real:
                    # discovery_runtime mode has lower coverage expectations (intentional limited universe)
                    stats = data.get("stats", {})
                    universe_source = stats.get("universe_source", "config")
                    if universe_source == "discovery_runtime":
                        # discovery_runtime: min 1 pair, 2 pools (cross-dex requires at least 2)
                        ok_cov, msg_cov = validate_coverage(data, min_pairs=1, min_pools=2)
                    else:
                        # standard mode: min 5 pairs, 6 pools
                        ok_cov, msg_cov = validate_coverage(data, min_pairs=5, min_pools=6)
                    if ok_cov:
                        messages.append(f"OK: {name} - {msg_cov}")
                    else:
                        messages.append(f"FAIL: {name} - {msg_cov}")
                        all_passed = False
                    
                    # discovery_runtime specific validation
                    if universe_source == "discovery_runtime":
                        dr_stats = stats.get("discovery_runtime", {})
                        dr_enabled = dr_stats.get("enabled", False)
                        dr_quotes = stats.get("quotes_fetched", 0)
                        dr_cross_dex = dr_stats.get("cross_dex_pairs_count", 0)
                        if not dr_enabled:
                            messages.append(f"FAIL: {name} - discovery_runtime.enabled=false but universe_source=discovery_runtime")
                            all_passed = False
                        elif dr_quotes < 1:
                            messages.append(f"FAIL: {name} - discovery_runtime quotes_fetched={dr_quotes} < 1")
                            all_passed = False
                        elif require_cross_dex and dr_cross_dex < 1:
                            # v3.2.36: Only fail on cross_dex < 1 if require_cross_dex=True
                            # BLOCKED_BY chains (e.g. Scroll) can pass infra validation with single DEX
                            messages.append(f"FAIL: {name} - discovery_runtime cross_dex_pairs_count={dr_cross_dex} < 1")
                            all_passed = False
                        elif not require_cross_dex and dr_cross_dex < 1:
                            # v3.2.36: BLOCKED_BY chain - warn but don't fail
                            messages.append(f"WARN: {name} - discovery_runtime cross_dex_pairs_count={dr_cross_dex} (require_cross_dex=false, BLOCKED_BY SECOND_DEX)")
                        else:
                            messages.append(f"OK: {name} - discovery_runtime (enabled=true, quotes={dr_quotes}, cross_dex={dr_cross_dex})")
            
            # Additional check: validate reject histogram cap semantics
            if name == "reject_histogram":
                try:
                    rejects = data.get("rejects", [])
                    for r in rejects:
                        raw = r.get("deviation_bps_raw")
                        maxd = r.get("max_deviation_bps")
                        capped = r.get("deviation_bps_capped")
                        if raw is not None and maxd is not None:
                            try:
                                if int(raw) > int(maxd) and not bool(capped):
                                    messages.append(f"FAIL: {name} - reject {r.get('pair')} raw({raw})>max({maxd}) but capped=false")
                                    all_passed = False
                            except Exception:
                                messages.append(f"WARN: {name} - could not evaluate cap for reject {r}")
                except Exception:
                    messages.append(f"WARN: {name} - could not validate reject_histogram semantics")
                # Strict reject_histogram validation
                ok_rh, msg_rh = validate_reject_histogram_fields(data, path)
                messages.append(f"{'OK' if ok_rh else 'FAIL'}: {name} - {msg_rh}")
                if not ok_rh:
                    all_passed = False
                    
        except json.JSONDecodeError as e:
            messages.append(f"FAIL: {name} - invalid JSON: {e}")
            all_passed = False
        except Exception as e:
            messages.append(f"FAIL: {name} - {e}")
            all_passed = False
    
    # =========================================================================
    # Cross-artifact validations (AFTER loading all artifacts)
    # =========================================================================
    
    try:
        if "scan" in loaded_data and "truth_report" in loaded_data:
            ok_cb, msg_cb = validate_current_block(loaded_data.get("scan", {}), loaded_data.get("truth_report", {}))
            if ok_cb:
                messages.append(f"OK: current_block - {msg_cb}")
            else:
                messages.append(f"FAIL: current_block - {msg_cb}")
                all_passed = False
        
        # Cross-artifact: reject_histogram.current_block must match scan/truth_report
        if "reject_histogram" in loaded_data and "scan" in loaded_data:
            scan_block = loaded_data["scan"].get("current_block")
            reject_block = loaded_data["reject_histogram"].get("current_block")
            if scan_block is not None and reject_block is not None:
                if int(scan_block) != int(reject_block):
                    if require_cross_artifact:
                        messages.append(f"FAIL: cross-artifact - reject_histogram.current_block ({reject_block}) != scan ({scan_block})")
                        all_passed = False
                    else:
                        messages.append(f"WARN: cross-artifact - reject_histogram.current_block ({reject_block}) != scan ({scan_block})")
    except Exception as e:
        messages.append(f"FAIL: current_block validation exception: {type(e).__name__}: {e}")

    # Cross-artifact summary cross-checks (scan vs truth_report vs reject_histogram)
    try:
        s = loaded_data.get("scan", {})
        t = loaded_data.get("truth_report", {})
        r = loaded_data.get("reject_histogram", {})

        def _get(d, key):
            return d.get(key) if d else None

        # Compare top-level counts
        mismatches = []
        for key in ("quotes_total", "quotes_fetched", "dexes_active", "price_sanity_passed", "price_sanity_failed"):
            sv = _get(s, key)
            tv = _get(t, key)
            if sv is not None and tv is not None and int(sv) != int(tv):
                mismatches.append((key, sv, tv))

        if mismatches:
            for key, sv, tv in mismatches:
                if require_cross_artifact:
                    messages.append(f"FAIL: summary_mismatch - {key} scan={sv} truth_report={tv}")
                    all_passed = False
                else:
                    messages.append(f"WARN: summary_mismatch - {key} scan={sv} truth_report={tv}")

        # Basic reject histogram vs totals sanity
        try:
            total_rejects = int(r.get("total_rejects", 0)) if r else 0
            rejects_len = len(r.get("rejects", [])) if r else 0
            if total_rejects != rejects_len:
                messages.append(f"WARN: reject_histogram.total_rejects ({total_rejects}) != len(rejects) ({rejects_len})")
        except Exception:
            messages.append("WARN: could not cross-check reject_histogram totals")
    except Exception as e:
        messages.append(f"WARN: cross-artifact checks failed: {type(e).__name__}: {e}")

    # Determine if this is offline mode (fixture artifacts)
    # In offline mode, infra fields are intentionally absent - skip validation
    run_mode_s = s.get("run_mode", "")
    run_mode_t = t.get("run_mode", "")
    is_offline = "FIXTURE" in run_mode_s or "FIXTURE" in run_mode_t
    
    # Infra transparency checks: confirm provider and host present and consistent
    # SKIP in offline mode - fixtures don't have real infra data
    if is_offline:
        # Silently skip infra validation for offline fixtures
        pass
    else:
        try:
            infra_s = (s.get("infra") or {})
            infra_t = (t.get("infra") or {})
            infra_r = (r.get("infra") or {})

            # Extract provider/hosts
            prov_s = infra_s.get("rpc_provider")
            prov_t = infra_t.get("rpc_provider")
            host_s = infra_s.get("rpc_http_host")
            host_t = infra_t.get("rpc_http_host")

            if not prov_s or not host_s:
                if require_infra_hosts or require_real:
                    messages.append("FAIL: scan.infra missing rpc_provider or rpc_http_host")
                    all_passed = False
                # In online mode without --require-infra-hosts, still warn
                elif prov_s != "alchemy" and prov_s != "public":
                    messages.append(f"WARN: scan.infra missing rpc_http_host (provider={prov_s})")
            if not prov_t or not host_t:
                if require_infra_hosts or require_real:
                    messages.append("FAIL: truth_report.infra missing rpc_provider or rpc_http_host")
                    all_passed = False
                elif prov_t != "alchemy" and prov_t != "public":
                    messages.append(f"WARN: truth_report.infra missing rpc_http_host (provider={prov_t})")

            # If env required Alchemy, ensure provider is alchemy
            # Team policy: Base is allowed to use public RPC endpoints (non-Alchemy).
            require_alchemy_env = (
                os.environ.get("ARBY_REQUIRE_ALCHEMY") == "1" or os.environ.get("REQUIRE_ALCHEMY") == "1"
            )
            if require_alchemy_env:
                chain_id_val = s.get("chain_id") or t.get("chain_id")
                try:
                    chain_id_int = int(chain_id_val) if chain_id_val is not None else None
                except Exception:
                    chain_id_int = None
                if chain_id_int not in {8453}:
                    if prov_s != "alchemy" or prov_t != "alchemy":
                        messages.append(
                            f"FAIL: REQUIRE_ALCHEMY set but provider != alchemy (scan={prov_s} truth={prov_t})"
                        )
                        all_passed = False

            # Heuristic: chain_id vs rpc host mismatch (blocker)
            # v3.2.33: Use validate_chain_rpc_consistency() for all chains
            try:
                chain_id_s = s.get("chain_id")
                chain_id_t = t.get("chain_id")
                # prefer scan chain_id if present
                chain_id_val = chain_id_s or chain_id_t
                if chain_id_val is not None:
                    try:
                        from core.rpc_urls import validate_chain_rpc_consistency
                        cid = int(chain_id_val)
                        
                        # v3.2.33: Validate all chains using consistent function
                        for artifact_name, host in [("scan", host_s), ("truth_report", host_t)]:
                            if host:
                                is_valid, error_msg = validate_chain_rpc_consistency(cid, host)
                                if not is_valid:
                                    messages.append(f"FAIL: {artifact_name} infra chain/RPC mismatch: {error_msg}")
                                    all_passed = False
                        
                        # v3.2.55: Validate WS hosts as well (prevent WS pollution between chains)
                        ws_host_s = infra_s.get("rpc_ws_host")
                        ws_host_t = infra_t.get("rpc_ws_host")
                        for artifact_name, ws_host in [("scan", ws_host_s), ("truth_report", ws_host_t)]:
                            if ws_host:
                                is_valid_ws, error_msg_ws = validate_chain_rpc_consistency(cid, ws_host)
                                if not is_valid_ws:
                                    messages.append(f"FAIL: {artifact_name} infra WS chain/RPC mismatch: {error_msg_ws}")
                                    all_passed = False
                    except ImportError:
                        # Fallback to legacy heuristic if import fails
                        if cid == 42161:
                            hs = (host_s or "").lower()
                            ht = (host_t or "").lower()
                            if "mantle" in hs or "mantle" in ht:
                                messages.append(f"FAIL: chain_id=42161 (Arbitrum) but rpc_http_host contains 'mantle' (scan={host_s} truth={host_t})")
                                all_passed = False
                    except Exception:
                        pass
            except Exception:
                pass

            # Tenderly diagnostic consistency
            for artifact_name, infra in (("scan", infra_s), ("truth_report", infra_t)):
                if infra.get("tenderly_enabled"):
                    ok = infra.get("tenderly_ok")
                    err = infra.get("tenderly_error")
                    if ok is not True and (not err):
                        if require_tenderly:
                            messages.append(f"FAIL: {artifact_name}.infra tenderly_enabled true but no tenderly_ok or tenderly_error")
                            all_passed = False
                        else:
                            messages.append(f"WARN: {artifact_name}.infra tenderly_enabled true but no tenderly_ok or tenderly_error")

            # WS diagnostics validation
            for artifact_name, infra in (("scan", infra_s), ("truth_report", infra_t)):
                if infra.get("ws_enabled"):
                    attempted = infra.get("ws_attempted")
                    connected = infra.get("ws_connected")
                    fallback = infra.get("ws_fallback_to_http")
                    ws_err = infra.get("ws_error")
                    if attempted is not True and attempted is not False:
                        messages.append(f"WARN: {artifact_name}.infra missing ws_attempted")
                    if connected is not True and connected is not False:
                        messages.append(f"WARN: {artifact_name}.infra missing ws_connected")
                    if connected is False and not (ws_err or fallback):
                        messages.append(f"FAIL: {artifact_name}.infra ws_enabled true but not connected and no ws_error/fallback provided")
                        all_passed = False
        except Exception as e:
            messages.append(f"WARN: infra transparency checks failed: {type(e).__name__}: {e}")

    return all_passed, messages


def validate_current_block(scan_data: Dict[str, Any], truth_data: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate current_block present, int>0 and equal between scan and truth_report.

    Returns (ok, message)
    """
    try:
        # Only consider top-level fields per contract
        scan_cb = scan_data.get("current_block")
        truth_cb = truth_data.get("current_block")

        missing = []
        if scan_cb is None:
            missing.append("scan.current_block")
        if truth_cb is None:
            missing.append("truth_report.current_block")
        if missing:
            return False, f"Missing current_block in: {', '.join(missing)}; truth keys: {list(truth_data.keys())}, scan keys: {list(scan_data.keys())}"

        # Type checks: must be int
        if not isinstance(scan_cb, int):
            return False, f"scan.current_block not int: {type(scan_cb).__name__} ({scan_cb})"
        if not isinstance(truth_cb, int):
            return False, f"truth_report.current_block not int: {type(truth_cb).__name__} ({truth_cb})"

        # Value checks
        if scan_cb <= 0:
            return False, f"scan.current_block must be >0, got {scan_cb}"
        if truth_cb <= 0:
            return False, f"truth_report.current_block must be >0, got {truth_cb}"

        # Equality
        if scan_cb != truth_cb:
            return False, f"current_block mismatch: scan={scan_cb} truth_report={truth_cb}"

        return True, f"current_block OK: {scan_cb}"
    except Exception as e:
        return False, f"Exception validating current_block: {type(e).__name__}: {e}"


def run_real_scan(output_dir: Path, config: str, cycles: int = 1) -> Tuple[bool, str]:
    """Run real scan via strategy.jobs.run_scan_real."""
    cmd = [
        sys.executable, "-m", "strategy.jobs.run_scan_real",
        "--cycles", str(cycles),
        "--output-dir", str(output_dir),
    ]
    if config:
        cmd.extend(["--config", config])
    
    print(f"\n[ONLINE] Running: {' '.join(cmd)}")
    print("-" * 60)
    
    # Resolve RPC URLs from env: prefer explicit ALCHEMY_RPC_HTTP/WS, else build from ALCHEMY_API_KEY
    try:
        from core.rpc_urls import resolve_rpc_http, resolve_rpc_ws
    except Exception:
        resolve_rpc_http = resolve_rpc_ws = None

    env_for_run = os.environ.copy()
    # Determine canonical network/chain: prefer config chain_id, then ENV
    # v3.2.54: Read chain_id from config file for correct WS resolution
    config_chain_id = None
    config_network = None
    if config:
        try:
            import yaml
            with open(config, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            config_chain_id = cfg.get("chain_id")
            config_network = cfg.get("chain") or cfg.get("network")
        except Exception:
            pass
    
    network = config_network or os.environ.get("NETWORK") or os.environ.get("CHAIN")
    chain_id = config_chain_id or os.environ.get("CHAIN_ID")
    try:
        chain_id_int = int(chain_id) if chain_id else None
    except Exception:
        chain_id_int = None

    # Use resolver to find the best HTTP and WS endpoints and provider metadata
    primary_http = None
    primary_ws = None
    provider_http = "unknown"
    provider_ws = "unknown"
    http_diag = {}
    ws_diag = {}

    if resolve_rpc_http:
        url, provider, diag = resolve_rpc_http(chain_id=chain_id_int, network=network, env=os.environ)
        primary_http = url
        provider_http = provider
        http_diag = diag or {}

    if resolve_rpc_ws:
        urlw, providerw, diagw = resolve_rpc_ws(chain_id=chain_id_int, network=network, env=os.environ)
        primary_ws = urlw
        provider_ws = providerw
        ws_diag = diagw or {}

    # Inject resolved endpoints into scanner env (do not log keys)
    # v3.2.54: Use OVERWRITE (not setdefault) to prevent env pollution from prior chain runs
    if primary_http:
        env_for_run["ARBY_RPC_HTTP_PRIMARY"] = primary_http
        env_for_run["ARBY_RPC_PROVIDER"] = provider_http
        # expose host only (no keys)
        try:
            from urllib.parse import urlparse
            env_for_run["ARBY_RPC_HTTP_HOST"] = urlparse(primary_http).netloc
        except Exception:
            pass
    if primary_ws:
        env_for_run["ARBY_RPC_WS_PRIMARY"] = primary_ws
        env_for_run["ARBY_RPC_WS_PROVIDER"] = provider_ws
        try:
            from urllib.parse import urlparse
            env_for_run["ARBY_RPC_WS_HOST"] = urlparse(primary_ws).netloc
        except Exception:
            pass
    else:
        # v3.2.54: Clear stale WS env vars if no WS resolved for this chain
        for key in ["ARBY_RPC_WS_PRIMARY", "ARBY_RPC_WS_PROVIDER", "ARBY_RPC_WS_HOST"]:
            env_for_run.pop(key, None)

    # Enforce Require-Alchemy behavior if requested
    require_alchemy = os.environ.get("ARBY_REQUIRE_ALCHEMY") == "1" or os.environ.get("REQUIRE_ALCHEMY") == "1"
    # Team policy: Base is allowed to use public RPC endpoints (non-Alchemy).
    alchemy_optional_chain_ids = {8453}
    # v3.2.54: Use chain_id_int from config (already read above)
    if require_alchemy and provider_http != "alchemy" and (chain_id_int or 0) not in alchemy_optional_chain_ids:
        print(
            f"FAIL: Alchemy expected but resolved provider={provider_http} (host={env_for_run.get('ARBY_RPC_HTTP_HOST')})"
        )
        return False, "Alchemy expected but public fallback used"

    # NOTE: WS preference flags are read from the calling process env by the scanner.

    try:
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=300, env=env_for_run)
        if result.returncode == 0:
            return True, "Scan completed successfully"
        else:
            return False, f"Exit code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Timeout (300s)"
    except FileNotFoundError:
        return False, "Module strategy.jobs.run_scan_real not found"
    except Exception as e:
        return False, str(e)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"M5_0 CI Gate v{__version__}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CANONICAL COMMANDS:
  python scripts/ci_m5_0_gate.py --offline
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

ENV VARIABLES:
  ARBY_CONFIG       Override --config (--online/ADVANCED)
  ARBY_CYCLES       Override --cycles (--online/ADVANCED)
  ARBY_OUTPUT_ROOT  Override --output-root
  ARBY_RUN_DIR      Explicit run directory (ADVANCED only)
  ARBY_REQUIRE_REAL Require real artifacts (set to "1")
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--offline", action="store_true",
                            help="Offline mode (IGNORES ALL ENV)")
    mode_group.add_argument("--online", action="store_true",
                            help="Online mode (runs real scan)")
    
    parser.add_argument("--run-dir", type=Path,
                        help="[ADVANCED] Explicit run directory")
    parser.add_argument("--require-real", action="store_true",
                        help="Reject fixture artifacts")
    parser.add_argument("--list-candidates", action="store_true",
                        help="List available run directories")
    
    # With ENV fallbacks for --online/ADVANCED
    parser.add_argument("--config", type=str,
                        default=os.environ.get("ARBY_CONFIG", DEFAULT_CONFIG),
                        help=f"Config file (default: $ARBY_CONFIG or {DEFAULT_CONFIG})")
    parser.add_argument("--output-root", type=Path,
                        default=Path(os.environ.get("ARBY_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT))),
                        help=f"Output root (default: $ARBY_OUTPUT_ROOT or {DEFAULT_OUTPUT_ROOT})")
    parser.add_argument("--cycles", type=int,
                        default=int(os.environ.get("ARBY_CYCLES", "1")),
                        help="Scan cycles (default: $ARBY_CYCLES or 1)")
    parser.add_argument("--ws", action="store_true",
                        help="Prefer WS transport when resolving endpoints")
    parser.add_argument("--ws-required", action="store_true",
                        help="Require WS to be available; fail if WS not connected")
    parser.add_argument("--require-infra-hosts", action="store_true",
                        help="Fail if artifacts do not include infra.rpc_provider or infra.rpc_http_host")
    parser.add_argument("--require-cross-artifact", action="store_true",
                        help="Treat cross-artifact summary mismatches as FAIL instead of WARN")
    parser.add_argument("--require-tenderly", action="store_true",
                        help="Require tenderly diagnostics to be present and passing when enabled in artifacts")
    
    # M5 additions: strict mode and cost model
    parser.add_argument("--strict", action="store_true",
                        help="Enable strict validation (fail on any WARN)")
    parser.add_argument("--gas-usd-estimate", type=float,
                        help="Gas USD estimate for cost model (overrides config)")
    parser.add_argument("--slippage-usd-estimate", type=float, default=0.0,
                        help="Slippage USD estimate for cost model")
    
    # v2.1.0: Prune automation
    parser.add_argument("--prune-keep", type=int, default=0,
                        help="After successful run, prune runDirs keeping N most recent (0=disabled)")
    
    # v2.1.0: Rolling refresh automation
    parser.add_argument("--refresh-rolling", action="store_true",
                        help="Regenerate _rolling artifacts from current run before exit")
    parser.add_argument("--refresh-rolling-strict", action="store_true",
                        help="If --refresh-rolling fails, treat as fatal error (exit FAIL)")
    
    # v2.3.0: Failover stress-test
    parser.add_argument("--failover-stress", type=int, default=0, metavar="N",
                        help="Simulate N failures on primary endpoint to prove failover (sets ARBY_FAILOVER_STRESS_N)")
    
    # v2.4.0: Non-stop loop mode
    parser.add_argument("--loop", action="store_true",
                        help="Run in continuous loop mode (non-stop scan demo)")
    parser.add_argument("--sleep-seconds", type=int, default=20,
                        help="Sleep interval between scans in loop mode (default: 20)")
    parser.add_argument("--max-consecutive-failures", type=int, default=5,
                        help="Max consecutive failures before exponential backoff maxes out (default: 5)")
    
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    
    args = parser.parse_args()

    # Log presence of sensitive env keys (presence only; do not print values)
    print(f"ENV: ALCHEMY_API_KEY present={bool(os.environ.get('ALCHEMY_API_KEY'))}, TENDERLY_ACCESS_KEY present={bool(os.environ.get('TENDERLY_ACCESS_KEY'))}")
    
    # Handle --list-candidates
    if args.list_candidates:
        candidates = get_run_dir_candidates(args.output_root)
        if candidates:
            print(f"Available run directories in {args.output_root}:")
            for i, d in enumerate(candidates[:10], 1):
                artifacts = discover_artifacts(d)
                count = sum(1 for v in artifacts.values() if v is not None)
                print(f"  {i}. {d.name} ({count}/3 artifacts)")
        else:
            print(f"No run directories found in {args.output_root}")
        return 0
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # =========================================================================
    # OFFLINE MODE
    # =========================================================================
    if args.offline:
        print(f"\n{'='*60}")
        print(f"M5_0 GATE v{__version__} - OFFLINE")
        print(f"{'='*60}")
        print("\n[OFFLINE] IGNORING ALL ENV VARIABLES")
        
        run_dir = args.output_root / f"ci_m5_gate_offline_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"[OFFLINE] Creating: {run_dir}")
        
        artifacts_paths = generate_fixture_artifacts(run_dir, timestamp)
        artifacts = discover_artifacts(run_dir)
        # Log resolved artifact paths for clarity
        print("\n[OFFLINE] Artifact paths:")
        for k, p in artifacts.items():
            print(f"  {k}: {p}")
        
        print(f"\n[OFFLINE] Generated {len(artifacts_paths)} artifacts:")
        for name, path in artifacts_paths.items():
            print(f"  - {name}: {path.name}")
        
        print(f"\n{'='*60}")
        print("VALIDATION")
        print(f"{'='*60}\n")
        
        passed, messages = validate_artifacts(
            artifacts,
            require_real=False,
            require_infra_hosts=args.require_infra_hosts,
            require_cross_artifact=args.require_cross_artifact,
            require_tenderly=args.require_tenderly,
        )
        for msg in messages:
            print(f"  {msg}")
        
        print(f"\n{'='*60}")
        print(f"RESULT: {'PASS' if passed else 'FAIL'}")
        print(f"RunDir: {run_dir}")
        
        # v3.3.0: Generate gate_result.json for offline mode as well
        try:
            from datetime import timezone
            utc_now = datetime.now(timezone.utc)
            # v3.3.1: Use ISO-8601 format for consistency
            run_timestamp = utc_now.isoformat()
            
            fail_reasons = [m.replace("FAIL: ", "") for m in messages if m.startswith("FAIL:")]
            
            gate_result = {
                "schema_version": "m5_0:gate_result:v1.0",
                "gate": "ci_m5_0_gate",
                "version": __version__,
                "run_context": {
                    "run_timestamp": run_timestamp,
                },
                "status": "PASS" if passed else "FAIL",
                "reasons": fail_reasons,
                "config_path": None,  # Offline mode has no config
                "chain_key": None,
                "require_cross_dex": False,
                "quotes_fetched": 0,
                "cross_dex_pairs_count": 0,
                "generated_at": utc_now.isoformat(),
            }
            
            reports_dir = run_dir / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            gate_result_path = reports_dir / "gate_result.json"
            with open(gate_result_path, "w", encoding="utf8") as f:
                json.dump(gate_result, f, indent=2, ensure_ascii=False)
            print(f"[OFFLINE] Generated: {gate_result_path}")
        except Exception as e:
            print(f"[OFFLINE] WARN: gate_result.json generation failed: {e}")
        
        return 0 if passed else 1
    
    # =========================================================================
    # ONLINE MODE
    # =========================================================================
    if args.online:
        # v2.4.0: Loop mode for non-stop scanning
        loop_mode = args.loop
        sleep_seconds = args.sleep_seconds
        max_consecutive_failures = args.max_consecutive_failures
        consecutive_failures = 0
        iteration_count = 0
        
        if loop_mode:
            print(f"\n{'='*60}")
            print(f"M5_0 GATE v{__version__} - ONLINE (LOOP MODE)")
            print(f"{'='*60}")
            print(f"\n[LOOP] Non-stop scan mode enabled")
            print(f"[LOOP] Sleep interval: {sleep_seconds}s")
            print(f"[LOOP] Max consecutive failures: {max_consecutive_failures}")
            print(f"[LOOP] Press Ctrl+C to stop")
        
        while True:
            iteration_count += 1
            
            # Generate new timestamp for each iteration
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if loop_mode and iteration_count > 1:
                print(f"\n{'='*60}")
                print(f"[LOOP] Iteration #{iteration_count}")
                print(f"{'='*60}")
            elif not loop_mode and iteration_count == 1:
                print(f"\n{'='*60}")
                print(f"M5_0 GATE v{__version__} - ONLINE")
                print(f"{'='*60}")
            
            print("\n[ONLINE] IGNORING ARBY_RUN_DIR (creating new run directory)")
            
            run_dir = args.output_root / f"ci_m5_gate_{timestamp}"
            run_dir.mkdir(parents=True, exist_ok=True)
            
            print(f"[ONLINE] RunDir: {run_dir}")
            print(f"[ONLINE] Config: {args.config}")
            print(f"[ONLINE] Cycles: {args.cycles}")
            
            # v1.12.2: Chain/RPC validation precheck
            # Detect mismatches like chain_id=42161 with Mantle RPC host
            # v3.2.32: Use config rpc_endpoints as primary source (multi-chain safety)
            try:
                import yaml
                from core.rpc_urls import validate_chain_rpc_consistency, resolve_rpc_http
                
                cfg_path = Path(args.config)
                if cfg_path.exists():
                    with open(cfg_path, "r", encoding="utf8") as f:
                        cfg = yaml.safe_load(f)
                    cfg_chain_id = cfg.get("chain_id", 42161)
                    
                    # v3.2.32: Config rpc_endpoints take highest priority
                    config_rpc_endpoints = cfg.get("rpc_endpoints") or []
                    if config_rpc_endpoints:
                        rpc_url = config_rpc_endpoints[0]
                        print(f"[ONLINE] Using config rpc_endpoint (highest priority): {rpc_url}")
                    else:
                        # Fall back to resolve_rpc_http (which now has chain-safety)
                        rpc_url, _, _ = resolve_rpc_http(chain_id=cfg_chain_id, env=dict(os.environ))
                    
                    if rpc_url:
                        from urllib.parse import urlparse
                        rpc_host = urlparse(rpc_url).netloc
                        is_valid, error_msg = validate_chain_rpc_consistency(cfg_chain_id, rpc_host)
                    
                        if not is_valid:
                            print(f"\n{'='*60}")
                            print(f"RESULT: FAIL - Chain/RPC mismatch")
                            print(f"  {error_msg}")
                            print(f"  RPC URL: {rpc_url}")
                            print(f"{'='*60}")
                            return 3
                        else:
                            print(f"[ONLINE] Chain/RPC validated: chain_id={cfg_chain_id}, host={rpc_host}")
            except Exception as e:
                print(f"[ONLINE] WARN: Chain/RPC validation skipped: {e}")
        
            # Export WS preference flags into the environment so run_real_scan picks them up
            if args.ws:
                os.environ.setdefault("ARBY_PREFER_WS", "1")
            if args.ws_required:
                os.environ.setdefault("ARBY_WS_REQUIRED", "1")
        
            # v2.3.0: Failover stress-test mode
            # When stress-test is active, disable rolling refresh by default to avoid polluting
            # rolling artifacts with artificial failures (unless explicitly requested)
            failover_stress_active = args.failover_stress > 0
            if failover_stress_active:
                os.environ["ARBY_FAILOVER_STRESS_N"] = str(args.failover_stress)
                print(f"[ONLINE] FAILOVER-STRESS: Will simulate {args.failover_stress} failures on primary endpoint")
                # v2.3.0: Disable rolling refresh unless explicitly requested
                if not args.refresh_rolling:
                    print("[ONLINE] FAILOVER-STRESS: Rolling refresh disabled (use --refresh-rolling to override)")
                    args._rolling_defaults_set = True  # Prevent auto-enable below

            # v3.2.11: NORM-only rolling policy - disable rolling refresh for non-NORMAL runs
            # SMOKE and COVERAGE runs should not update rolling artifacts
            # v3.2.17: Stricter enforcement - even if --refresh-rolling was explicitly passed
            # v3.2.18: FAIL if explicit run_kind is missing (no defaulting for strict runs)
            try:
                cfg_path = Path(args.config)
                if cfg_path.exists():
                    import yaml
                    with open(cfg_path, "r", encoding="utf8") as f:
                        cfg_for_run_kind = yaml.safe_load(f) or {}
                    
                    # v3.2.18: Check for explicit run_kind (no defaulting)
                    has_explicit_run_kind = ("run_kind" in cfg_for_run_kind)
                    run_kind = cfg_for_run_kind.get("run_kind", "NORMAL")
                    
                    # v3.2.18: FAIL if refresh-rolling is requested but run_kind is missing
                    if args.refresh_rolling and not has_explicit_run_kind:
                        print(f"[ONLINE] ERROR: --refresh-rolling requested but config missing explicit 'run_kind'")
                        print(f"[ONLINE] ERROR: Add 'run_kind: NORMAL' to config to enable rolling refresh")
                        return 1
                    
                    # v3.2.18: FAIL if refresh-rolling is requested but run_kind != NORMAL
                    if args.refresh_rolling and run_kind != "NORMAL":
                        print(f"[ONLINE] ERROR: --refresh-rolling requested but run_kind={run_kind}")
                        print(f"[ONLINE] ERROR: NORM-only rolling policy: only run_kind=NORMAL can update rolling")
                        return 1
                    
                    # v3.2.21: FAIL if refresh-rolling is requested but chain != PRIMARY_ROLLING_CHAIN
                    # This prevents MIXED_CHAIN_KEYS contamination from multi-chain bring-up runs
                    config_chain = cfg_for_run_kind.get("chain", "arbitrum_one")
                    if args.refresh_rolling and config_chain != PRIMARY_ROLLING_CHAIN:
                        print(f"[ONLINE] ERROR: --refresh-rolling requested but chain={config_chain}")
                        print(f"[ONLINE] ERROR: Rolling chain discipline: only chain={PRIMARY_ROLLING_CHAIN} can update rolling")
                        print(f"[ONLINE] ERROR: Multi-chain bring-up must use COVERAGE mode without --refresh-rolling")
                        return 1
                    
                    if run_kind != "NORMAL":
                        # v3.2.17: Warn if user explicitly requested refresh_rolling for non-NORMAL
                        if args.refresh_rolling:
                            print(f"[ONLINE] WARN: --refresh-rolling ignored for run_kind={run_kind}")
                            print(f"[ONLINE] WARN: NORM-only rolling policy: _latest.json protected from non-NORMAL runs")
                        print(f"[ONLINE] run_kind={run_kind}: Rolling refresh disabled (NORM-only rolling policy)")
                        args.refresh_rolling = False
                        args._rolling_defaults_set = True  # Prevent auto-enable below
            except Exception as rk_err:
                print(f"[ONLINE] WARN: run_kind check failed: {rk_err}")

            # For M5_0 DoD: make infra-hosts and cross-artifact checks strict by default in online runs
            # These can still be overridden by explicit flags if needed.
            args.require_infra_hosts = True
            args.require_cross_artifact = True
            
            # v2.2.0: Rolling freshness enforcement — default for online runs
            # Ensures rolling artifacts are always refreshed when scanning online
            # Prevents stale rolling evidence (Issue: rolling not matching latest runDir)
            # v2.3.0: Skip if failover-stress disables it
            if not hasattr(args, '_rolling_defaults_set'):
                args.refresh_rolling = True
                args.refresh_rolling_strict = True
                if args.prune_keep == 0:
                    args.prune_keep = 50
                args._rolling_defaults_set = True
            
            # v3.2.22: Re-check chain guard AFTER auto-enable
            # This prevents bypassing via implicit refresh_rolling
            # (Issue: user runs --online without --refresh-rolling on non-primary chain,
            # first check passes because refresh_rolling=False, then auto-enable sets it True)
            if args.refresh_rolling:
                try:
                    cfg_path = Path(args.config)
                    if cfg_path.exists():
                        import yaml
                        with open(cfg_path, "r", encoding="utf8") as f:
                            cfg_for_chain = yaml.safe_load(f) or {}
                        config_chain = cfg_for_chain.get("chain", "arbitrum_one")
                        if config_chain != PRIMARY_ROLLING_CHAIN:
                            print(f"[ONLINE] ERROR: auto-enabled refresh_rolling blocked - chain={config_chain}")
                            print(f"[ONLINE] ERROR: Rolling chain discipline: only chain={PRIMARY_ROLLING_CHAIN} can update rolling")
                            print(f"[ONLINE] ERROR: Omit --refresh-rolling or switch config to chain={PRIMARY_ROLLING_CHAIN}")
                            return 1
                except Exception:
                    pass  # Guard already checked earlier, this is redundant safety

            success, message = run_real_scan(run_dir, args.config, args.cycles)
            
            print(f"\n[ONLINE] {message}")
        
            if not success:
                print(f"\n{'='*60}")
                print(f"RESULT: FAIL - Scanner error")
                return 3
            
            # Generate daily_report with cost model
            # v2.6.1: Use CostModelRegistry from m4.policy (single source of truth)
            # aggregate_run() auto-loads paper_realistic model when available
            try:
                from scripts.generate_daily_report import aggregate_run
                
                # v2.6.1: Let aggregate_run use CostModelRegistry internally
                # No need to pass gas_usd_estimate/slippage_usd_estimate manually
                # v1.8.0: Pass session_context for session completion gate
                # v3.2.68: Automated CI runs explicitly mark run_type="automated"
                session_context = {
                    "session_goal": f"M5 online scan ({args.config})",
                    "goal_status": "IN_PROGRESS",
                    "close_allowed": False,
                    "remaining_blockers": [],
                    "evidence_session_run_dirs": [run_dir.name],
                    # v3.2.68: Automated runs have no human-defined blocker
                    "primary_blocker_of_session": "CI_AUTOMATED_RUN",
                    "blocker_status_before": "N/A",
                    "blocker_status_after": "N/A",
                    "docs_reread_confirmed": False,
                    # v3.2.68: Explicit marker that this is an automated CI run
                    "run_type": "automated",
                }
                report = aggregate_run(run_dir, session_context=session_context)
                
                # Write daily_report
                report_dir = run_dir / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                from datetime import date
                report_path = report_dir / f"daily_report_{date.today().isoformat()}.json"
                with open(report_path, "w", encoding="utf8") as f:
                    json.dump(report, f, indent=2, ensure_ascii=False)
                print(f"[ONLINE] Generated: {report_path}")
            except Exception as e:
                print(f"[ONLINE] WARN: daily_report generation failed: {e}")
            
            artifacts = discover_artifacts(run_dir)
            missing = [name for name, path in artifacts.items() if path is None]
            if missing:
                print(f"\n{'='*60}")
                print(f"RESULT: FAIL - Missing artifacts: {missing}")
                return 2
            
            # v3.2.36: Load require_cross_dex from config for validation
            # BLOCKED_BY chains (e.g. Scroll) can set require_cross_dex=false
            config_require_cross_dex = True  # default: require cross-dex
            config_chain_key = None
            try:
                cfg_path = Path(args.config)
                if cfg_path.exists():
                    import yaml
                    with open(cfg_path, "r", encoding="utf8") as f:
                        cfg_for_validation = yaml.safe_load(f) or {}
                    config_require_cross_dex = cfg_for_validation.get("require_cross_dex", True)
                    config_chain_key = cfg_for_validation.get("chain")
                    if not config_require_cross_dex:
                        print(f"[ONLINE] require_cross_dex=false (chain={config_chain_key}, BLOCKED_BY SECOND_DEX)")
            except Exception as e:
                print(f"[ONLINE] WARN: Could not load require_cross_dex from config: {e}")
            
            print(f"\n{'='*60}")
            print("VALIDATION")
            print(f"{'='*60}\n")
            
            passed, messages = validate_artifacts(
                artifacts,
                require_real=True,
                require_infra_hosts=args.require_infra_hosts,
                require_cross_artifact=args.require_cross_artifact,
                require_tenderly=args.require_tenderly,
                require_cross_dex=config_require_cross_dex,
            )
            for msg in messages:
                print(f"  {msg}")
            
            print(f"\n{'='*60}")
            print(f"RESULT: {'PASS' if passed else 'FAIL'}")
            print(f"RunDir: {run_dir}")
            
            # v3.2.36: Write gate_result.json for canonical provenance
            # Contains status, reasons, config_path, chain_key, quotes_fetched, cross_dex_pairs_count
            try:
                # Extract key metrics from scan artifact
                scan_path = artifacts.get("scan")
                quotes_fetched = 0
                cross_dex_pairs_count = 0
                scan_run_timestamp = None
                if scan_path and scan_path.exists():
                    with open(scan_path) as f:
                        scan_data = json.load(f)
                    quotes_fetched = scan_data.get("stats", {}).get("quotes_fetched", 0)
                    cross_dex_pairs_count = scan_data.get("stats", {}).get("discovery_runtime", {}).get("cross_dex_pairs_count", 0)
                    # v3.3.1: Extract run_timestamp from scan artifact (ISO-8601)
                    scan_run_timestamp = scan_data.get("run_context", {}).get("run_timestamp")
                
                # v3.2.69: Fallback - calculate cross_dex_pairs_count from signals if discovery_runtime disabled
                if cross_dex_pairs_count == 0:
                    cross_dex_pairs = set()
                    
                    # Fallback 1: Try signals.json
                    signals_path = artifacts.get("signals")
                    if signals_path and signals_path.exists():
                        try:
                            with open(signals_path) as f:
                                signals_data = json.load(f)
                            for sig in signals_data.get("signals", []):
                                buy_dex = sig.get("buy_dex", "")
                                sell_dex = sig.get("sell_dex", "")
                                pair = sig.get("pair", "")
                                if buy_dex and sell_dex and buy_dex != sell_dex and pair:
                                    cross_dex_pairs.add(pair)
                        except (json.JSONDecodeError, IOError):
                            pass
                    
                    # Fallback 2: Try truth_report.spread_signals
                    if not cross_dex_pairs:
                        truth_path = artifacts.get("truth")
                        if truth_path and truth_path.exists():
                            try:
                                with open(truth_path) as f:
                                    truth_data = json.load(f)
                                for sig in truth_data.get("spread_signals", []):
                                    buy_dex = sig.get("buy_dex", "")
                                    sell_dex = sig.get("sell_dex", "")
                                    pair = sig.get("pair", "")
                                    if buy_dex and sell_dex and buy_dex != sell_dex and pair:
                                        cross_dex_pairs.add(pair)
                            except (json.JSONDecodeError, IOError):
                                pass
                    
                    if cross_dex_pairs:
                        cross_dex_pairs_count = len(cross_dex_pairs)
                
                # Build fail_reasons from messages
                fail_reasons = [m.replace("FAIL: ", "") for m in messages if m.startswith("FAIL:")]
                
                # v3.3.1: Use run_timestamp from scan artifact (ISO-8601) for provenance alignment
                from datetime import timezone
                utc_now = datetime.now(timezone.utc)
                # Prefer scan artifact's run_timestamp; fallback to UTC ISO format
                run_timestamp = scan_run_timestamp if scan_run_timestamp else utc_now.isoformat()
                
                gate_result = {
                    "schema_version": "m5_0:gate_result:v1.0",
                    "gate": "ci_m5_0_gate",
                    "version": __version__,
                    "run_context": {
                        "run_timestamp": run_timestamp,
                    },
                    "status": "PASS" if passed else "FAIL",
                    "reasons": fail_reasons,
                    "config_path": str(args.config),
                    "chain_key": config_chain_key,
                    "require_cross_dex": config_require_cross_dex,
                    "quotes_fetched": quotes_fetched,
                    "cross_dex_pairs_count": cross_dex_pairs_count,
                    "generated_at": utc_now.isoformat(),
                }
                
                # v3.3.0: Write to reports/ directory for schema compliance
                reports_dir = run_dir / "reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                gate_result_path = reports_dir / "gate_result.json"
                with open(gate_result_path, "w", encoding="utf8") as f:
                    json.dump(gate_result, f, indent=2, ensure_ascii=False)
                print(f"[ONLINE] Generated: {gate_result_path}")
            except Exception as e:
                print(f"[ONLINE] WARN: gate_result.json generation failed: {e}")
            
            # v3.2.19: Always run M4 gate for ONLINE PASS to generate run_summary
            # This ensures every runDir has provenance artifacts for evidence tracking
            # artifact-mode controls whether rolling is updated:
            #   - "full": generate run_summary in runDir only (no rolling update)
            #   - "rolling": generate run_summary AND update rolling artifacts
            refresh_rolling_ok = True
            m4_gate_ok = True
            if passed:
                try:
                    artifact_mode = "rolling" if args.refresh_rolling else "full"
                    purpose = "generate run_summary + update rolling" if args.refresh_rolling else "generate run_summary"
                    print(f"\n[ONLINE] Running M4 gate to {purpose}...")
                    import subprocess
                    m4_cmd = [
                        sys.executable,
                        "scripts/ci_m4_execution_gate.py",
                        "--online",
                        "--profile", "profit",
                        "--artifact-mode", artifact_mode,
                        "--run-dir", str(run_dir),
                    ]
                    m4_result = subprocess.run(m4_cmd, capture_output=True, text=True, timeout=180)
                    if m4_result.returncode == 0:
                        if args.refresh_rolling:
                            print(f"[ONLINE] M4 gate passed, rolling artifacts updated")
                        else:
                            print(f"[ONLINE] M4 gate passed, run_summary generated (rolling not updated)")
                        # v1.8.0: Regenerate daily_report AFTER M4 gate to pick up execution_report
                        # First daily_report generation (line ~1507) happens before M4 creates execution_report
                        try:
                            from scripts.generate_daily_report import aggregate_run
                            # v3.2.68: Automated CI runs explicitly mark run_type="automated"
                            session_context = {
                                "session_goal": f"M5 online scan ({args.config})",
                                "goal_status": "IN_PROGRESS",
                                "close_allowed": False,
                                "remaining_blockers": [],
                                "evidence_session_run_dirs": [run_dir.name],
                                # v3.2.68: Automated runs have no human-defined blocker
                                "primary_blocker_of_session": "CI_AUTOMATED_RUN",
                                "blocker_status_before": "N/A",
                                "blocker_status_after": "N/A",
                                "docs_reread_confirmed": False,
                                # v3.2.68: Explicit marker that this is an automated CI run
                                "run_type": "automated",
                            }
                            report = aggregate_run(run_dir, session_context=session_context)
                            from datetime import date
                            report_path = reports_dir / f"daily_report_{date.today().isoformat()}.json"
                            with open(report_path, "w", encoding="utf8") as f:
                                json.dump(report, f, indent=2, ensure_ascii=False)
                            m4_net = report.get("theoretical_net_profit", {}).get("m4_sim_net_usdc")
                            print(f"[ONLINE] Regenerated daily_report with m4_sim_net_usdc={m4_net}")
                        except Exception as e:
                            print(f"[ONLINE] WARN: daily_report regeneration failed: {e}")
                    else:
                        print(f"[ONLINE] M4 gate returned {m4_result.returncode}")
                        m4_gate_ok = False
                        if args.refresh_rolling:
                            refresh_rolling_ok = False
                        if args.refresh_rolling_strict:
                            print(f"[ONLINE] FAIL: --refresh-rolling-strict mode, M4 gate failed")
                except subprocess.TimeoutExpired:
                    print(f"[ONLINE] M4 gate timeout (180s)")
                    m4_gate_ok = False
                    if args.refresh_rolling:
                        refresh_rolling_ok = False
                    if args.refresh_rolling_strict:
                        print(f"[ONLINE] FAIL: --refresh-rolling-strict mode, M4 gate timeout")
                except Exception as e:
                    print(f"[ONLINE] WARN: M4 gate failed: {e}")
                    m4_gate_ok = False
                    if args.refresh_rolling:
                        refresh_rolling_ok = False
                    if args.refresh_rolling_strict:
                        print(f"[ONLINE] FAIL: --refresh-rolling-strict mode, M4 gate exception")
            else:
                # v3.2.22: Generate minimal run_summary for NO_DATA/FAIL runs
                # This ensures every ONLINE runDir has provenance (run_timestamp) for triage
                # Uses separate schema (m4:run_summary_min:v2.0) to avoid contract conflicts
                # with full m4:run_summary:v2.0 (which requires policy_version, run_id, etc.)
                try:
                    print(f"\n[ONLINE] Generating minimal run_summary for NO_DATA/FAIL run...")
                    reports_dir = run_dir / "reports"
                    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    run_summary_path = reports_dir / f"run_summary_{ts}.json"
                    
                    # Load truth_report for run_context if available
                    # v3.2.37: Fix malformed timestamp - use replace(+00:00, Z) instead of appending Z
                    run_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    no_data_reason = "UNKNOWN"
                    chain_key = "unknown"
                    signals_count = 0
                    
                    truth_files = list(reports_dir.glob("truth_report_*.json"))
                    if truth_files:
                        with open(truth_files[0]) as f:
                            truth_data = json.load(f)
                        truth_ctx = truth_data.get("run_context", {})
                        run_timestamp = truth_ctx.get("run_timestamp", run_timestamp)
                        # v3.2.23: Use len(spread_signals) instead of stats.total_signals (doesn't exist)
                        signals_count = len(truth_data.get("spread_signals", []))
                        # NO_DATA reason mapping: NO_QUOTES, NO_TOKENS, NO_POOL, RPC_ERROR, etc.
                        truth_stats = truth_data.get("stats", {})
                        no_data_reason = truth_stats.get("no_data_reason", "NO_QUOTES")
                        chain_key = truth_data.get("chain_key", "unknown")
                    
                    # v3.2.22: Determine status based on actual validation result
                    # - NO_DATA: zero signals AND validation passed OR no truth_report
                    # - FAIL: validation failed (passed=False even with signals)
                    if not passed:
                        actual_status = "FAIL"
                        actual_reasons = ["VALIDATION_FAILED"]
                        if no_data_reason == "UNKNOWN":
                            no_data_reason = "VALIDATION_FAILED"
                    elif signals_count == 0:
                        actual_status = "NO_DATA"
                        actual_reasons = ["NO_DATA"]
                    else:
                        # Shouldn't happen (passed=True with signals should go to M4 gate)
                        actual_status = "NO_DATA"
                        actual_reasons = ["NO_DATA", "M4_GATE_SKIPPED"]
                    
                    run_summary_data = {
                        # v3.2.22: Use explicit minimal schema to avoid contract conflicts
                        "schema_version": "m4:run_summary_min:v2.0",
                        # v3.2.37: Fix malformed timestamp - use replace(+00:00, Z) instead of appending Z
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "run_id": run_dir.name,
                        "run_context": {
                            "run_timestamp": run_timestamp,
                            "run_dir_name": run_dir.name,
                            "code_identity": f"ts:{run_timestamp}",
                            "code_sha": None,  # v2.0: deprecated
                            "code_dirty": None,
                            "code_desc": None,
                            "evidence_sha": None,
                        },
                        "status": actual_status,
                        "profit_status": actual_status,
                        "drift_status": actual_status,
                        "quality_status": actual_status,
                        "reasons": actual_reasons,
                        "metrics": {
                            "signals_count": signals_count,
                            "included_signals_count": 0,
                            "total_net_usdc": 0.0,
                            "no_data_reason": no_data_reason,
                        },
                        "inputs": {
                            "chain_key": chain_key,
                            "run_mode": getattr(args, 'mode', 'online').upper(),  # v3.2.23: actual value
                            "config_path": getattr(args, 'config', None),
                        },
                    }
                    
                    # v3.2.22: Use atomic write to prevent partial JSON on kill/crash
                    from core.json_io import atomic_write_json
                    atomic_write_json(run_summary_path, run_summary_data)
                    
                    print(f"[ONLINE] Generated minimal: {run_summary_path.name} ({actual_status})")
                except Exception as e:
                    print(f"[ONLINE] WARN: Failed to generate minimal run_summary: {e}")
            
            # v2.1.0: Auto-prune if enabled
            # v2.6.1: Prune on every iteration (not just PASS) to prevent disk fill on RPC/drift failures
            if args.prune_keep > 0:
                try:
                    from scripts.prune_run_dirs import prune_run_dirs
                    print(f"\n[ONLINE] Pruning runDirs (keeping {args.prune_keep} most recent)...")
                    prune_result = prune_run_dirs(keep=args.prune_keep, dry_run=False, yes=True)
                    print(f"[ONLINE] Pruned {prune_result.get('delete_count', 0)} old directories")
                except Exception as e:
                    print(f"[ONLINE] WARN: Prune failed: {e}")
            
            # v2.1.0: Determine final status considering rolling refresh
            final_pass = passed
            if args.refresh_rolling_strict and not refresh_rolling_ok:
                final_pass = False
            
            # v2.4.0: Check for roundtrip profitable and emit alert
            if final_pass:
                is_profitable, profitable_count, profit_status = check_roundtrip_profitable(run_dir)
                if is_profitable:
                    emit_roundtrip_alert(run_dir, profitable_count, profit_status)
            
            # v2.4.0: Loop mode handling
            if not loop_mode:
                # Single run mode - return immediately
                return 0 if final_pass else 1
            
            # Loop mode continues here
            if final_pass:
                consecutive_failures = 0
                sleep_seconds_actual = sleep_seconds
                print(f"\n[LOOP] Iteration #{iteration_count} PASS - sleeping {sleep_seconds}s...")
            else:
                consecutive_failures += 1
                # Exponential backoff: base * 2^failures, capped at 5 minutes
                sleep_seconds_actual = min(sleep_seconds * (2 ** consecutive_failures), 300)
                print(f"\n[LOOP] Iteration #{iteration_count} FAIL (consecutive: {consecutive_failures})")
                print(f"[LOOP] Backoff: sleeping {sleep_seconds_actual}s...")
            
            try:
                import time
                time.sleep(sleep_seconds_actual)
            except KeyboardInterrupt:
                print(f"\n[LOOP] Interrupted by user after {iteration_count} iterations")
                return 0 if final_pass else 1
    
    # =========================================================================
    # ADVANCED MODE (uses ARBY_RUN_DIR or --run-dir)
    # =========================================================================
    print(f"\n{'='*60}")
    print(f"M5_0 GATE v{__version__} - ADVANCED")
    print(f"{'='*60}")
    print("\nTIP: Use --offline or --online for standard workflows")
    
    run_dir = None
    if args.run_dir:
        run_dir = args.run_dir
        print(f"\n[ADVANCED] Using --run-dir: {run_dir}")
    elif os.environ.get("ARBY_RUN_DIR"):
        run_dir = Path(os.environ["ARBY_RUN_DIR"])
        print(f"\n[ADVANCED] Using ARBY_RUN_DIR: {run_dir}")
    else:
        candidates = get_run_dir_candidates(args.output_root)
        if candidates:
            run_dir = candidates[0]
            print(f"\n[ADVANCED] Using latest: {run_dir}")
        else:
            print(f"\nERROR: No run directory found")
            print(f"Use --offline to create fixtures or --online to run real scan")
            return 2
    
    if not run_dir.exists():
        print(f"\nERROR: Run directory not found: {run_dir}")
        return 2
    
    require_real = args.require_real or os.environ.get("ARBY_REQUIRE_REAL") == "1"
    
    artifacts = discover_artifacts(run_dir)
    missing = [name for name, path in artifacts.items() if path is None]
    if missing:
        print(f"\nERROR: Missing artifacts: {missing}")
        return 2
    
    print(f"\n{'='*60}")
    print("VALIDATION")
    print(f"{'='*60}\n")
    
    passed, messages = validate_artifacts(
        artifacts,
        require_real=require_real,
        require_infra_hosts=args.require_infra_hosts,
        require_cross_artifact=args.require_cross_artifact,
        require_tenderly=args.require_tenderly,
    )
    for msg in messages:
        print(f"  {msg}")
    
    print(f"\n{'='*60}")
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    print(f"RunDir: {run_dir}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
