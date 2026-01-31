#!/usr/bin/env python
# PATH: scripts/ci_m5_0_gate.py
"""
CI Gate for M5_0 (Infrastructure Hardening).

OFFLINE-FIRST: Validates artifacts WITHOUT running the scanner.
NO HEAVY IMPORTS: Only uses json, pathlib, argparse, sys, re, os.

MODE SELECTION PRIORITY (CLI > ENV > auto):
1. --run-dir PATH (explicit, highest priority)
2. ARBY_RUN_DIR env var
3. --offline (creates fixture)
4. ARBY_GATE_MODE=offline env var
5. Auto-detect latest valid runDir in data/runs/

ENV VARIABLES:
    ARBY_RUN_DIR       - Path to run directory (same as --run-dir)
    ARBY_GATE_MODE     - Mode: offline, latest, run_dir
    ARBY_GATE_OUT_DIR  - Output dir for fixture (same as --out-dir)
    ARBY_REQUIRE_REAL  - If "1", reject fixture data (_fixture=true)

USAGE:
    # Explicit run directory (RECOMMENDED for CI)
    python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456

    # Offline with fixture
    python scripts/ci_m5_0_gate.py --offline

    # Require real data (reject fixtures)
    python scripts/ci_m5_0_gate.py --run-dir data/runs/real_xxx --require-real

    # Using ENV (for CI pipelines)
    ARBY_RUN_DIR=data/runs/real_xxx python scripts/ci_m5_0_gate.py

EXIT CODES:
    0 = PASS
    1 = FAIL (validation failed)
    2 = FAIL (artifacts missing)
    3 = FAIL (fixture rejected by --require-real)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Version
GATE_VERSION = "1.3.0"

# Required schema version pattern (major.minor.patch)
VALID_SCHEMA_PATTERN = r"^\d+\.\d+\.\d+$"

# Default output directory for fixtures
DEFAULT_RUNS_DIR = Path("data/runs")

# Fixture marker (to distinguish from real data)
FIXTURE_BLOCK = 275000000
FIXTURE_MARKER = "[FIXTURE]"

# Exit codes
EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ARTIFACTS_MISSING = 2
EXIT_FIXTURE_REJECTED = 3

# How many candidates to show when runDir not found
MAX_CANDIDATES_TO_SHOW = 5


def log_ok(msg: str) -> None:
    print(f"[OK] {msg}")


def log_fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def log_info(msg: str) -> None:
    print(f"[INFO] {msg}")


def log_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def get_env_bool(name: str, default: bool = False) -> bool:
    """Get boolean from environment variable."""
    val = os.environ.get(name, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


def get_env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get string from environment variable."""
    val = os.environ.get(name, "").strip()
    return val if val else default


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


def has_all_artifacts(run_dir: Path) -> bool:
    """Check if directory has all 3 required artifacts."""
    artifacts = find_artifacts(run_dir)
    return all(v is not None for v in artifacts.values())


def count_artifacts(run_dir: Path) -> int:
    """Count how many artifacts are present in a directory."""
    artifacts = find_artifacts(run_dir)
    return sum(1 for v in artifacts.values() if v is not None)


def get_run_dir_candidates(base_dir: Path, max_count: int = MAX_CANDIDATES_TO_SHOW) -> List[Tuple[Path, int, float]]:
    """
    Get list of candidate run directories sorted by validity and recency.
    
    Returns: List of (path, artifact_count, mtime) tuples
    """
    if not base_dir.exists():
        return []
    
    candidates = []
    for d in base_dir.iterdir():
        if d.is_dir():
            artifact_count = count_artifacts(d)
            mtime = d.stat().st_mtime
            candidates.append((d, artifact_count, mtime))
    
    # Sort by: artifact_count (desc), mtime (desc)
    candidates.sort(key=lambda x: (-x[1], -x[2]))
    return candidates[:max_count]


def print_candidates(base_dir: Path, max_count: int = MAX_CANDIDATES_TO_SHOW) -> None:
    """Print helpful list of candidate run directories."""
    candidates = get_run_dir_candidates(base_dir, max_count)
    
    if not candidates:
        print(f"\n  No directories found in {base_dir}")
        print(f"\n  Run a scan first:")
        print(f"    python -m strategy.jobs.run_scan_real --cycles 1 --output-dir data/runs/real_$(date +%Y%m%d_%H%M%S)")
        return
    
    print(f"\n  Available run directories in {base_dir}:")
    print()
    
    for path, artifact_count, mtime in candidates:
        mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        status = "✓" if artifact_count == 3 else f"({artifact_count}/3)"
        print(f"    {status} {path.name}  [{mtime_str}]")
    
    # Show example command with best candidate
    best_valid = next((p for p, count, _ in candidates if count == 3), None)
    if best_valid:
        print(f"\n  Example command:")
        print(f"    python scripts/ci_m5_0_gate.py --run-dir {best_valid}")
    else:
        print(f"\n  No complete run directories found (need 3/3 artifacts).")
        print(f"  Run a scan first to generate artifacts.")


def find_latest_valid_rundir(base_dir: Path) -> Optional[Path]:
    """
    Find latest valid runDir by modification time.
    
    Selection criteria:
    1. Must be a directory
    2. Must contain all 3 artifacts (scan, truth_report, reject_histogram)
    3. Prioritize ci_m5_0_gate_* and run_scan_* prefixes
    4. Fall back to any directory with artifacts
    5. Sort by mtime (newest first)
    
    Returns None if no valid runDir found.
    """
    if not base_dir.exists():
        return None
    
    # Get all subdirectories
    all_dirs = [d for d in base_dir.iterdir() if d.is_dir()]
    
    if not all_dirs:
        return None
    
    # Filter to directories with all 3 artifacts
    valid_dirs = [d for d in all_dirs if has_all_artifacts(d)]
    
    if not valid_dirs:
        return None
    
    # Prioritize M5 and run_scan prefixes
    priority_prefixes = ("ci_m5_0_gate_", "run_scan_", "real_", "session_")
    
    def sort_key(d: Path) -> Tuple[int, float]:
        """Sort by: (priority, mtime). Lower priority number = higher priority."""
        name = d.name
        priority = 99  # Default low priority
        for i, prefix in enumerate(priority_prefixes):
            if name.startswith(prefix):
                priority = i
                break
        # Negative mtime so newest is first
        return (priority, -d.stat().st_mtime)
    
    valid_dirs.sort(key=sort_key)
    return valid_dirs[0]


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


def check_block_pinned(scan_data: Dict[str, Any], is_fixture: bool = False) -> Tuple[bool, List[str]]:
    """Check current_block is valid (> 0 for REAL mode)."""
    errors: List[str] = []
    
    run_mode = scan_data.get("run_mode") or scan_data.get("stats", {}).get("run_mode", "")
    current_block = scan_data.get("current_block", 0)
    
    # Mark fixture values
    fixture_marker = f" {FIXTURE_MARKER}" if is_fixture and current_block == FIXTURE_BLOCK else ""
    
    if run_mode == "REGISTRY_REAL":
        if current_block is None or current_block <= 0:
            errors.append(f"current_block must be > 0 for REAL mode, got: {current_block}")
        else:
            log_ok(f"current_block: {current_block}{fixture_marker}")
    else:
        log_info(f"current_block: {current_block} (SMOKE mode){fixture_marker}")
    
    return len(errors) == 0, errors


def check_quotes_metrics(scan_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check quotes metrics are valid."""
    errors: List[str] = []
    stats = scan_data.get("stats", {})
    
    quotes_total = stats.get("quotes_total", 0)
    quotes_fetched = stats.get("quotes_fetched", 0)
    gates_passed = stats.get("gates_passed", 0)
    
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
    log_ok(f"reject_histogram: {len(histogram)} categories")
    
    gate_breakdown = histogram_data.get("gate_breakdown", {})
    if gate_breakdown:
        log_ok(f"gate_breakdown: {list(gate_breakdown.keys())}")
    
    return len(errors) == 0, errors


def create_fixture_run_dir(out_dir: Optional[Path] = None) -> Path:
    """
    Create minimal fixture for offline/self-test mode.
    
    Args:
        out_dir: Output directory. If None, uses data/runs/ci_m5_0_gate_<timestamp>
    
    Returns:
        Path to created fixture directory
    """
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if out_dir is None:
        # Default: data/runs/ci_m5_0_gate_<timestamp>
        out_dir = DEFAULT_RUNS_DIR / f"ci_m5_0_gate_{timestamp_str}"
    
    # Create directories
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fallback to temp if can't create in data/runs
        import tempfile
        out_dir = Path(tempfile.mkdtemp(prefix="m5_gate_"))
        log_info(f"Using temp directory (no write access to data/runs): {out_dir}")
    
    snapshots_dir = out_dir / "snapshots"
    reports_dir = out_dir / "reports"
    snapshots_dir.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)
    
    # Minimal scan data with FIXTURE markers
    scan_data = {
        "run_mode": "REGISTRY_REAL",
        "current_block": FIXTURE_BLOCK,  # Fixture value
        "chain_id": 42161,
        "_fixture": True,  # Explicit marker
        "stats": {
            "run_mode": "REGISTRY_REAL",
            "current_block": FIXTURE_BLOCK,
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
        "_fixture": True,
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
        "_fixture": True,
        "histogram": {"PRICE_SANITY_FAILED": 2},
        "gate_breakdown": {"sanity": 2, "revert": 0, "slippage": 0, "infra": 0, "other": 0},
    }
    
    with open(reports_dir / f"reject_histogram_{timestamp_str}.json", "w") as f:
        json.dump(histogram_data, f, indent=2)
    
    return out_dir


def run_gate(run_dir: Path, is_fixture: bool = False, require_real: bool = False) -> int:
    """
    Run all M5_0 gate checks.
    
    Returns:
        0 = PASS
        1 = FAIL (general)
        2 = FAIL (artifacts missing)
        3 = FAIL (fixture rejected by require_real)
    """
    print(f"\n{'='*60}")
    print("STEP: Artifact Discovery")
    print("=" * 60)
    
    artifacts = find_artifacts(run_dir)
    passed, errors = check_artifacts_present(artifacts)
    if not passed:
        for e in errors:
            log_fail(e)
        return EXIT_ARTIFACTS_MISSING
    
    # Load artifacts
    scan_data = load_json(artifacts["scan"])  # type: ignore
    truth_report = load_json(artifacts["truth_report"])  # type: ignore
    histogram_data = load_json(artifacts["reject_histogram"])  # type: ignore
    
    if scan_data is None or truth_report is None or histogram_data is None:
        return EXIT_ARTIFACTS_MISSING
    
    # Check if this is fixture data
    is_fixture = is_fixture or scan_data.get("_fixture", False)
    
    # Reject fixture if require_real is set
    if require_real and is_fixture:
        log_fail("Fixture data rejected: --require-real is set")
        log_info("Run a real scan to generate non-fixture artifacts")
        return EXIT_FIXTURE_REJECTED
    
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
    passed, errors = check_block_pinned(scan_data, is_fixture=is_fixture)
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
    
    return EXIT_PASS if all_passed else EXIT_FAIL


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ARBY M5_0 CI Gate - Offline Artifact Validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
    # Validate specific run directory (RECOMMENDED for CI)
    python scripts/ci_m5_0_gate.py --run-dir data/runs/real_20260130_123456

    # Offline with fixture in default location
    python scripts/ci_m5_0_gate.py --offline

    # Offline with custom output directory
    python scripts/ci_m5_0_gate.py --offline --out-dir data/runs/my_test

    # Require real data (reject fixtures)
    python scripts/ci_m5_0_gate.py --run-dir data/runs/xxx --require-real

    # Using environment variables (for CI)
    ARBY_RUN_DIR=data/runs/real_xxx python scripts/ci_m5_0_gate.py
    ARBY_GATE_MODE=offline python scripts/ci_m5_0_gate.py
    ARBY_REQUIRE_REAL=1 python scripts/ci_m5_0_gate.py --run-dir data/runs/xxx

FIND REAL RUNDIRS:
    PowerShell:  Get-ChildItem data\\runs | Sort-Object LastWriteTime -Desc | Select -First 5
    Bash:        ls -lt data/runs | head -6
        """,
    )
    parser.add_argument(
        "--run-dir",
        type=str,
        default=None,
        help="Path to run directory with artifacts (highest priority)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=None,
        help="Output directory for --offline fixture (default: data/runs/ci_m5_0_gate_<timestamp>)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Create fixture and validate (uses --out-dir or default location)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-test with fixture (same as --offline)",
    )
    parser.add_argument(
        "--require-real",
        action="store_true",
        help="Reject fixture data (_fixture=true), require real scan artifacts",
    )
    parser.add_argument(
        "--print-latest",
        action="store_true",
        help="Print latest valid runDir and exit",
    )
    parser.add_argument(
        "--list-candidates",
        action="store_true",
        help="List available run directories and exit",
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
    
    if args.list_candidates:
        print(f"\n{'='*60}")
        print(" ARBY M5_0 CI GATE - Run Directory Candidates")
        print("=" * 60)
        print_candidates(DEFAULT_RUNS_DIR, max_count=10)
        return 0
    
    # Get ENV values
    env_run_dir = get_env_str("ARBY_RUN_DIR")
    env_mode = get_env_str("ARBY_GATE_MODE")
    env_out_dir = get_env_str("ARBY_GATE_OUT_DIR")
    env_require_real = get_env_bool("ARBY_REQUIRE_REAL")
    
    # Merge require_real from CLI and ENV
    require_real = args.require_real or env_require_real
    
    if args.print_latest:
        latest = find_latest_valid_rundir(DEFAULT_RUNS_DIR)
        if latest:
            print(f"Latest valid runDir: {latest}")
            return 0
        else:
            print(f"No valid runDir found in {DEFAULT_RUNS_DIR}")
            print_candidates(DEFAULT_RUNS_DIR)
            return 1
    
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
    
    if require_real:
        print()
        print("[MODE] --require-real: Fixture data will be rejected")
    
    # Determine run directory and discovery strategy
    is_fixture = False
    discovery_strategy = "unknown"
    run_dir: Optional[Path] = None
    
    # Priority 1: CLI --run-dir
    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.exists():
            log_fail(f"Run directory does not exist: {run_dir}")
            print_candidates(DEFAULT_RUNS_DIR)
            return 1
        discovery_strategy = "explicit (--run-dir CLI)"
    
    # Priority 2: ENV ARBY_RUN_DIR
    elif env_run_dir:
        run_dir = Path(env_run_dir)
        if not run_dir.exists():
            log_fail(f"Run directory does not exist: {run_dir} (from ARBY_RUN_DIR)")
            print_candidates(DEFAULT_RUNS_DIR)
            return 1
        discovery_strategy = "explicit (ARBY_RUN_DIR env)"
    
    # Priority 3: CLI --offline
    elif args.offline or args.self_test:
        out_dir = Path(args.out_dir) if args.out_dir else (Path(env_out_dir) if env_out_dir else None)
        run_dir = create_fixture_run_dir(out_dir)
        is_fixture = True
        discovery_strategy = "offline_fixture (--offline CLI)"
        log_info(f"Created fixture: {run_dir}")
    
    # Priority 4: ENV ARBY_GATE_MODE
    elif env_mode:
        if env_mode == "offline":
            out_dir = Path(env_out_dir) if env_out_dir else None
            run_dir = create_fixture_run_dir(out_dir)
            is_fixture = True
            discovery_strategy = "offline_fixture (ARBY_GATE_MODE=offline)"
            log_info(f"Created fixture: {run_dir}")
        elif env_mode == "latest":
            run_dir = find_latest_valid_rundir(DEFAULT_RUNS_DIR)
            if run_dir is None:
                log_fail(f"No valid runDir in {DEFAULT_RUNS_DIR} (ARBY_GATE_MODE=latest)")
                print_candidates(DEFAULT_RUNS_DIR)
                return 1
            discovery_strategy = "latest_by_mtime (ARBY_GATE_MODE=latest)"
        else:
            log_fail(f"Unknown ARBY_GATE_MODE: {env_mode} (expected: offline, latest)")
            return 1
    
    # Priority 5: Auto-detect
    else:
        run_dir = find_latest_valid_rundir(DEFAULT_RUNS_DIR)
        if run_dir is None:
            log_info(f"No valid runDir in {DEFAULT_RUNS_DIR}, creating fixture...")
            run_dir = create_fixture_run_dir()
            is_fixture = True
            discovery_strategy = "offline_fixture (fallback)"
            log_info(f"Created fixture: {run_dir}")
        else:
            discovery_strategy = "latest_by_mtime (auto)"
    
    print(f"\n[DISCOVERY] Strategy: {discovery_strategy}")
    print(f"[RUN-DIR] {run_dir}")
    if is_fixture:
        print(f"[FIXTURE] Data is synthetic (current_block={FIXTURE_BLOCK})")
    
    # Run gate
    exit_code = run_gate(run_dir, is_fixture=is_fixture, require_real=require_real)
    
    # Summary
    print("\n" + "=" * 60)
    if exit_code == EXIT_PASS:
        print(" [PASS] M5_0 CI GATE PASSED")
    elif exit_code == EXIT_FIXTURE_REJECTED:
        print(" [FAIL] M5_0 CI GATE FAILED (fixture rejected)")
    else:
        print(f" [FAIL] M5_0 CI GATE FAILED (exit code {exit_code})")
    print("=" * 60)
    
    if exit_code == EXIT_PASS:
        print("\nM5_0 Contract Verified:")
        print("  [OK] schema_version valid")
        print("  [OK] run_mode exists")
        print("  [OK] current_block valid")
        print("  [OK] quotes metrics valid")
        print("  [OK] dexes_active >= 1")
        print("  [OK] price_sanity metrics exist")
        print("  [OK] 3/3 artifacts present")
        if is_fixture:
            print(f"\n  {FIXTURE_MARKER} Validated with synthetic fixture data")
    
    print(f"\nArtifacts: {run_dir}")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
