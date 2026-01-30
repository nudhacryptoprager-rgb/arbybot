#!/usr/bin/env python
# PATH: scripts/ci_m5_0_gate.py
"""
CI Gate for M5_0 (Infrastructure Hardening).

OFFLINE-FIRST: Validates artifacts WITHOUT running the scanner.
NO HEAVY IMPORTS: Only uses json, pathlib, argparse, sys, re.

M5_0 SUCCESS CRITERIA:
- schema_version exists and is valid (X.Y.Z format)
- run_mode exists (REGISTRY_REAL or SMOKE_SIMULATOR)
- current_block > 0 (for REAL mode)
- quotes_total >= 1
- quotes_fetched >= 1
- dexes_active >= 1
- price_sanity_passed + price_sanity_failed exist
- reject_histogram artifact exists
- 3 core artifacts present (scan, truth_report, reject_histogram)

USAGE:
    # Validate existing run directory
    python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456

    # Run with fixture (for CI)
    python scripts/ci_m5_0_gate.py --offline

    # Self-test mode
    python scripts/ci_m5_0_gate.py --self-test

ASCII-SAFE: No emoji or Unicode symbols (Windows compatibility).
"""

import argparse
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Version
GATE_VERSION = "1.0.0"

# Required schema version pattern (major.minor.patch)
VALID_SCHEMA_PATTERN = r"^\d+\.\d+\.\d+$"


def log_ok(msg: str) -> None:
    print(f"[OK] {msg}")


def log_fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_skip(msg: str) -> None:
    print(f"[SKIP] {msg}")


def find_artifacts(run_dir: Path) -> Dict[str, Optional[Path]]:
    """
    Find artifacts in run directory.
    
    Supports two layouts:
    1. Flat: scan_*.json, truth_report_*.json, reject_histogram_*.json
    2. Nested: snapshots/scan_*.json, reports/truth_report_*.json, reports/reject_histogram_*.json
    """
    artifacts: Dict[str, Optional[Path]] = {
        "scan": None,
        "truth_report": None,
        "reject_histogram": None,
    }
    
    # Try nested layout first (M4 style)
    snapshots_dir = run_dir / "snapshots"
    reports_dir = run_dir / "reports"
    
    if snapshots_dir.exists():
        scan_files = list(snapshots_dir.glob("scan_*.json"))
        if scan_files:
            artifacts["scan"] = sorted(scan_files)[-1]  # Latest
    
    if reports_dir.exists():
        truth_files = list(reports_dir.glob("truth_report_*.json"))
        if truth_files:
            artifacts["truth_report"] = sorted(truth_files)[-1]
        
        histogram_files = list(reports_dir.glob("reject_histogram_*.json"))
        if histogram_files:
            artifacts["reject_histogram"] = sorted(histogram_files)[-1]
    
    # Try flat layout (fallback)
    if artifacts["scan"] is None:
        scan_files = list(run_dir.glob("scan_*.json"))
        if scan_files:
            artifacts["scan"] = sorted(scan_files)[-1]
    
    if artifacts["truth_report"] is None:
        truth_files = list(run_dir.glob("truth_report_*.json"))
        if truth_files:
            artifacts["truth_report"] = sorted(truth_files)[-1]
    
    if artifacts["reject_histogram"] is None:
        histogram_files = list(run_dir.glob("reject_histogram_*.json"))
        if histogram_files:
            artifacts["reject_histogram"] = sorted(histogram_files)[-1]
    
    return artifacts


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON file safely."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log_fail(f"Failed to load {path}: {e}")
        return None


def check_artifacts_present(artifacts: Dict[str, Optional[Path]]) -> Tuple[bool, List[str]]:
    """Check all required artifacts are present."""
    errors: List[str] = []
    
    if artifacts["scan"] is None:
        errors.append("Missing: scan_*.json")
    else:
        log_ok(f"Found: {artifacts['scan'].name}")
    
    if artifacts["truth_report"] is None:
        errors.append("Missing: truth_report_*.json")
    else:
        log_ok(f"Found: {artifacts['truth_report'].name}")
    
    if artifacts["reject_histogram"] is None:
        errors.append("Missing: reject_histogram_*.json")
    else:
        log_ok(f"Found: {artifacts['reject_histogram'].name}")
    
    return len(errors) == 0, errors


def check_schema_version(truth_report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check schema_version exists and is valid."""
    errors: List[str] = []
    
    schema = truth_report.get("schema_version")
    if schema is None:
        errors.append("Missing: schema_version")
    elif not isinstance(schema, str):
        errors.append(f"schema_version must be string, got: {type(schema).__name__}")
    elif not re.match(VALID_SCHEMA_PATTERN, schema):
        errors.append(f"schema_version invalid format: {schema} (expected X.Y.Z)")
    else:
        log_ok(f"schema_version: {schema}")
    
    return len(errors) == 0, errors


def check_run_mode(scan_data: Dict[str, Any], truth_report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check run_mode exists and is consistent."""
    errors: List[str] = []
    
    # Check scan data
    scan_mode = scan_data.get("run_mode")
    if scan_mode is None:
        # Try stats.run_mode
        scan_mode = scan_data.get("stats", {}).get("run_mode")
    
    if scan_mode is None:
        errors.append("Missing: run_mode in scan data")
    else:
        log_ok(f"scan.run_mode: {scan_mode}")
    
    # Check truth report
    truth_mode = truth_report.get("run_mode")
    if truth_mode is None:
        errors.append("Missing: run_mode in truth_report")
    else:
        log_ok(f"truth_report.run_mode: {truth_mode}")
    
    # Check consistency
    if scan_mode and truth_mode and scan_mode != truth_mode:
        errors.append(f"run_mode mismatch: scan={scan_mode}, truth_report={truth_mode}")
    
    return len(errors) == 0, errors


def check_block_pinned(scan_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check current_block is valid (> 0 for REAL mode)."""
    errors: List[str] = []
    
    run_mode = scan_data.get("run_mode") or scan_data.get("stats", {}).get("run_mode", "")
    current_block = scan_data.get("current_block", 0)
    
    if run_mode == "REGISTRY_REAL":
        if current_block is None or current_block <= 0:
            errors.append(f"current_block must be > 0 for REAL mode, got: {current_block}")
        else:
            log_ok(f"current_block: {current_block}")
    else:
        # SMOKE mode - block is simulated, just report
        log_info(f"current_block: {current_block} (SMOKE mode)")
    
    return len(errors) == 0, errors


def check_quotes_metrics(scan_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check quotes metrics are valid."""
    errors: List[str] = []
    stats = scan_data.get("stats", {})
    
    quotes_total = stats.get("quotes_total", 0)
    quotes_fetched = stats.get("quotes_fetched", 0)
    gates_passed = stats.get("gates_passed", 0)
    
    # Invariant checks
    if quotes_total < 1:
        errors.append(f"quotes_total must be >= 1, got: {quotes_total}")
    else:
        log_ok(f"quotes_total: {quotes_total}")
    
    if quotes_fetched < 1:
        errors.append(f"quotes_fetched must be >= 1, got: {quotes_fetched}")
    else:
        log_ok(f"quotes_fetched: {quotes_fetched}")
    
    if quotes_fetched > quotes_total:
        errors.append(f"INVARIANT: quotes_fetched ({quotes_fetched}) > quotes_total ({quotes_total})")
    
    if gates_passed > quotes_fetched:
        errors.append(f"INVARIANT: gates_passed ({gates_passed}) > quotes_fetched ({quotes_fetched})")
    else:
        log_ok(f"gates_passed: {gates_passed}")
    
    return len(errors) == 0, errors


def check_dexes_active(scan_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check dexes_active >= 1."""
    errors: List[str] = []
    stats = scan_data.get("stats", {})
    
    dexes_active = stats.get("dexes_active", 0)
    
    if dexes_active < 1:
        errors.append(f"dexes_active must be >= 1, got: {dexes_active}")
    else:
        log_ok(f"dexes_active: {dexes_active}")
    
    return len(errors) == 0, errors


def check_price_sanity_metrics(scan_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check price sanity metrics exist."""
    errors: List[str] = []
    stats = scan_data.get("stats", {})
    
    passed = stats.get("price_sanity_passed")
    failed = stats.get("price_sanity_failed")
    
    if passed is None:
        errors.append("Missing: stats.price_sanity_passed")
    else:
        log_ok(f"price_sanity_passed: {passed}")
    
    if failed is None:
        errors.append("Missing: stats.price_sanity_failed")
    else:
        log_ok(f"price_sanity_failed: {failed}")
    
    return len(errors) == 0, errors


def check_reject_histogram(histogram_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check reject histogram exists and has expected structure."""
    errors: List[str] = []
    
    histogram = histogram_data.get("histogram", {})
    
    # Histogram can be empty (all passed)
    log_ok(f"reject_histogram: {len(histogram)} categories")
    
    # Check for gate_breakdown if present
    gate_breakdown = histogram_data.get("gate_breakdown", {})
    if gate_breakdown:
        log_ok(f"gate_breakdown: {list(gate_breakdown.keys())}")
    
    return len(errors) == 0, errors


def create_fixture_run_dir() -> Path:
    """Create minimal fixture for offline/self-test mode."""
    temp_dir = Path(tempfile.mkdtemp(prefix="m5_gate_"))
    snapshots_dir = temp_dir / "snapshots"
    reports_dir = temp_dir / "reports"
    snapshots_dir.mkdir()
    reports_dir.mkdir()
    
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Minimal scan data
    scan_data = {
        "run_mode": "REGISTRY_REAL",
        "current_block": 275000000,
        "chain_id": 42161,
        "stats": {
            "run_mode": "REGISTRY_REAL",
            "current_block": 275000000,
            "quotes_total": 4,
            "quotes_fetched": 4,
            "gates_passed": 2,
            "dexes_active": 2,
            "price_sanity_passed": 2,
            "price_sanity_failed": 2,
        },
        "reject_histogram": {"PRICE_SANITY_FAILED": 2},
    }
    
    with open(snapshots_dir / f"scan_{timestamp_str}.json", "w") as f:
        json.dump(scan_data, f, indent=2)
    
    # Minimal truth report
    truth_report = {
        "schema_version": "3.2.0",
        "timestamp": datetime.now().isoformat(),
        "run_mode": "REGISTRY_REAL",
        "execution_enabled": False,
        "health": {
            "quotes_total": 4,
            "quotes_fetched": 4,
            "gates_passed": 2,
            "dexes_active": 2,
            "price_sanity_passed": 2,
            "price_sanity_failed": 2,
            "price_stability_factor": 0.5,
        },
        "stats": {
            "quotes_total": 4,
            "quotes_fetched": 4,
        },
    }
    
    with open(reports_dir / f"truth_report_{timestamp_str}.json", "w") as f:
        json.dump(truth_report, f, indent=2)
    
    # Minimal reject histogram
    histogram_data = {
        "run_mode": "REGISTRY_REAL",
        "timestamp": datetime.now().isoformat(),
        "histogram": {"PRICE_SANITY_FAILED": 2},
        "gate_breakdown": {"sanity": 2, "revert": 0, "slippage": 0, "infra": 0, "other": 0},
    }
    
    with open(reports_dir / f"reject_histogram_{timestamp_str}.json", "w") as f:
        json.dump(histogram_data, f, indent=2)
    
    log_info(f"Created fixture in: {temp_dir}")
    return temp_dir


def run_gate(run_dir: Path) -> int:
    """
    Run all M5_0 gate checks.
    
    Returns:
        0 = PASS
        1 = FAIL (general)
        2 = FAIL (artifacts missing)
    """
    print(f"\n{'='*60}")
    print("STEP: Artifact Discovery")
    print("=" * 60)
    
    artifacts = find_artifacts(run_dir)
    passed, errors = check_artifacts_present(artifacts)
    if not passed:
        for e in errors:
            log_fail(e)
        return 2
    
    # Load artifacts
    scan_data = load_json(artifacts["scan"])  # type: ignore
    truth_report = load_json(artifacts["truth_report"])  # type: ignore
    histogram_data = load_json(artifacts["reject_histogram"])  # type: ignore
    
    if scan_data is None or truth_report is None or histogram_data is None:
        return 2
    
    all_passed = True
    
    # Schema version
    print(f"\n{'='*60}")
    print("STEP: Schema Version")
    print("=" * 60)
    passed, errors = check_schema_version(truth_report)
    if not passed:
        for e in errors:
            log_fail(e)
        all_passed = False
    
    # Run mode
    print(f"\n{'='*60}")
    print("STEP: Run Mode")
    print("=" * 60)
    passed, errors = check_run_mode(scan_data, truth_report)
    if not passed:
        for e in errors:
            log_fail(e)
        all_passed = False
    
    # Block pinned
    print(f"\n{'='*60}")
    print("STEP: Block Pinned")
    print("=" * 60)
    passed, errors = check_block_pinned(scan_data)
    if not passed:
        for e in errors:
            log_fail(e)
        all_passed = False
    
    # Quotes metrics
    print(f"\n{'='*60}")
    print("STEP: Quotes Metrics")
    print("=" * 60)
    passed, errors = check_quotes_metrics(scan_data)
    if not passed:
        for e in errors:
            log_fail(e)
        all_passed = False
    
    # DEXes active
    print(f"\n{'='*60}")
    print("STEP: DEXes Active")
    print("=" * 60)
    passed, errors = check_dexes_active(scan_data)
    if not passed:
        for e in errors:
            log_fail(e)
        all_passed = False
    
    # Price sanity metrics
    print(f"\n{'='*60}")
    print("STEP: Price Sanity Metrics")
    print("=" * 60)
    passed, errors = check_price_sanity_metrics(scan_data)
    if not passed:
        for e in errors:
            log_fail(e)
        all_passed = False
    
    # Reject histogram
    print(f"\n{'='*60}")
    print("STEP: Reject Histogram")
    print("=" * 60)
    passed, errors = check_reject_histogram(histogram_data)
    if not passed:
        for e in errors:
            log_fail(e)
        all_passed = False
    
    return 0 if all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ARBY M5_0 CI Gate - Offline Artifact Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
    # Validate existing run directory
    python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456

    # Run with auto-generated fixture
    python scripts/ci_m5_0_gate.py --offline

    # Self-test mode
    python scripts/ci_m5_0_gate.py --self-test

M5_0 INVARIANTS:
    - schema_version exists (X.Y.Z format)
    - run_mode exists (REGISTRY_REAL or SMOKE_SIMULATOR)
    - current_block > 0 (for REAL mode)
    - quotes_total >= 1
    - quotes_fetched >= 1
    - dexes_active >= 1
    - price_sanity_passed/failed metrics exist
    - reject_histogram artifact exists
        """,
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Path to run directory with artifacts",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Create fixture and validate (default if no --run-dir)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-test with fixture",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )
    
    args = parser.parse_args()
    
    if args.version:
        print(f"ci_m5_0_gate.py version {GATE_VERSION}")
        return 0
    
    print("\n" + "=" * 60)
    print(f" ARBY M5_0 CI GATE (v{GATE_VERSION})")
    print("=" * 60)
    print()
    print("M5_0 Criteria:")
    print("  - schema_version exists (X.Y.Z)")
    print("  - run_mode exists")
    print("  - current_block > 0 (REAL mode)")
    print("  - quotes_total >= 1")
    print("  - quotes_fetched >= 1")
    print("  - dexes_active >= 1")
    print("  - price_sanity metrics exist")
    print("  - 3 core artifacts present")
    
    # Determine run directory
    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            log_fail(f"Run directory does not exist: {run_dir}")
            return 1
        mode_str = f"RUN-DIR: {run_dir}"
    elif args.offline or args.self_test:
        run_dir = create_fixture_run_dir()
        mode_str = "OFFLINE (fixture)"
    else:
        # Default: try to find latest run
        data_runs = Path("data/runs")
        if data_runs.exists():
            run_dirs = sorted([d for d in data_runs.iterdir() if d.is_dir()])
            if run_dirs:
                run_dir = run_dirs[-1]
                mode_str = f"LATEST: {run_dir}"
            else:
                run_dir = create_fixture_run_dir()
                mode_str = "OFFLINE (no runs found, using fixture)"
        else:
            run_dir = create_fixture_run_dir()
            mode_str = "OFFLINE (no data/runs/, using fixture)"
    
    print(f"\n[MODE] {mode_str}")
    
    # Run gate
    exit_code = run_gate(run_dir)
    
    # Summary
    print("\n" + "=" * 60)
    if exit_code == 0:
        print(" [PASS] M5_0 CI GATE PASSED")
    else:
        print(f" [FAIL] M5_0 CI GATE FAILED (exit code {exit_code})")
    print("=" * 60)
    
    if exit_code == 0:
        print("\nM5_0 Contract Verified:")
        print("  [OK] schema_version valid")
        print("  [OK] run_mode exists")
        print("  [OK] current_block valid")
        print("  [OK] quotes metrics valid")
        print("  [OK] dexes_active >= 1")
        print("  [OK] price_sanity metrics exist")
        print("  [OK] 3/3 artifacts present")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
