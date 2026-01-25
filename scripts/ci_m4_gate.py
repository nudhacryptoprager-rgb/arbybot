#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (Execution Layer - Phase 1: REAL Pipeline).

This script runs:
  1. pytest -q (all tests must pass)
  2. REAL scan 1 cycle (must not raise)
  3. Artifact sanity check (4 artifacts)
  4. M4 invariants check

M4 SUCCESS CRITERIA:
- REAL scan executes without RuntimeError
- 4 artifacts generated: scan.log, scan_*.json, reject_histogram_*.json, truth_report_*.json
- current_block is pinned (> 0)
- execution_ready_count == 0 (execution disabled)

M4 DOES NOT REQUIRE:
- quotes_fetched >= 1 (network-dependent, warn only)

Usage:
  python scripts/ci_m4_gate.py

Exit codes:
  0 - All checks passed
  1 - Tests failed
  2 - REAL scan failed
  3 - Artifact sanity check failed
  4 - M4 invariants failed (pinned block or execution not disabled)
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_command(cmd: list, description: str) -> bool:
    """Run command and return success status."""
    print(f"\n{'='*60}")
    print(f"STEP: {description}")
    print(f"CMD:  {' '.join(cmd)}")
    print("=" * 60)

    result = subprocess.run(cmd, capture_output=False)
    success = result.returncode == 0

    if success:
        print(f"✅ {description} PASSED")
    else:
        print(f"❌ {description} FAILED (exit code {result.returncode})")

    return success


def check_artifact_sanity(output_dir: Path) -> bool:
    """
    Check that REAL scan produced valid artifacts (4 files).
    
    Required artifacts:
    - scan.log
    - snapshots/scan_*.json
    - reports/reject_histogram_*.json
    - reports/truth_report_*.json
    """
    print(f"\n{'='*60}")
    print("STEP: Artifact Sanity Check")
    print(f"DIR:  {output_dir}")
    print("=" * 60)

    errors = []

    # 1. Check scan.log
    log_file = output_dir / "scan.log"
    if not log_file.exists():
        errors.append("❌ Missing: scan.log")
    else:
        print(f"✓ Found: scan.log")

    # 2. Check scan_*.json
    snapshots_dir = output_dir / "snapshots"
    scan_files = list(snapshots_dir.glob("scan_*.json")) if snapshots_dir.exists() else []
    if not scan_files:
        errors.append("❌ Missing: snapshots/scan_*.json")
    else:
        print(f"✓ Found: {scan_files[0].name}")

    # 3. Check reject_histogram_*.json
    reports_dir = output_dir / "reports"
    histogram_files = list(reports_dir.glob("reject_histogram_*.json")) if reports_dir.exists() else []
    if not histogram_files:
        errors.append("❌ Missing: reports/reject_histogram_*.json")
    else:
        print(f"✓ Found: {histogram_files[0].name}")

    # 4. Check truth_report_*.json
    truth_files = list(reports_dir.glob("truth_report_*.json")) if reports_dir.exists() else []
    if not truth_files:
        errors.append("❌ Missing: reports/truth_report_*.json")
    else:
        print(f"✓ Found: {truth_files[0].name}")

        # Validate truth report structure
        try:
            with open(truth_files[0], "r") as f:
                truth_report = json.load(f)

            required_keys = ["schema_version", "health", "stats"]
            for key in required_keys:
                if key not in truth_report:
                    errors.append(f"❌ truth_report missing key: {key}")

            if "health" in truth_report:
                health = truth_report["health"]
                if "gate_breakdown" not in health:
                    errors.append("❌ health missing gate_breakdown")
        except json.JSONDecodeError as e:
            errors.append(f"❌ truth_report is not valid JSON: {e}")

    if errors:
        print()
        for error in errors:
            print(error)
        return False

    print()
    print("✅ All 4 artifacts present and valid")
    return True


def check_m4_invariants(output_dir: Path) -> bool:
    """
    Check M4-specific invariants for REAL mode.
    
    REQUIRED (gate fails if not met):
    - run_mode == "REGISTRY_REAL"
    - current_block > 0 (pinned)
    - execution_ready_count == 0 (execution disabled)
    
    OPTIONAL (warn only, gate does not fail):
    - quotes_fetched >= 1 (network-dependent)
    """
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check")
    print("=" * 60)

    errors = []
    warnings_list = []

    # Load scan snapshot
    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if not scan_files:
        errors.append("❌ Cannot check M4 invariants: no scan_*.json")
        for error in errors:
            print(error)
        return False

    with open(scan_files[0], "r") as f:
        scan_data = json.load(f)

    # Load truth report
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("❌ Cannot check M4 invariants: no truth_report_*.json")
        for error in errors:
            print(error)
        return False

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    # 1. Check run_mode == "REGISTRY_REAL"
    run_mode = scan_data.get("run_mode", "")
    if run_mode == "REGISTRY_REAL":
        print(f"✓ run_mode: {run_mode}")
    else:
        errors.append(f"❌ run_mode should be REGISTRY_REAL, got: {run_mode}")

    # 2. Check schema_version
    schema_version = truth_report.get("schema_version", "")
    if schema_version:
        print(f"✓ schema_version: {schema_version}")
    else:
        warnings_list.append("⚠ schema_version not found")

    # 3. Check pinned block (REQUIRED)
    current_block = scan_data.get("current_block")
    if current_block is not None and current_block > 0:
        print(f"✓ current_block: {current_block} (pinned)")
    else:
        errors.append(f"❌ current_block must be pinned (> 0), got: {current_block}")

    # 4. Check execution disabled (REQUIRED)
    stats = truth_report.get("stats", {})
    execution_ready = stats.get("execution_ready_count", 0)
    if execution_ready == 0:
        print(f"✓ execution_ready_count: {execution_ready} (execution disabled)")
    else:
        errors.append(f"❌ execution_ready_count should be 0 (M4: execution disabled), got: {execution_ready}")

    # 5. Check quotes (OPTIONAL - warn only)
    scan_stats = scan_data.get("stats", {})
    quotes_fetched = scan_stats.get("quotes_fetched", 0)
    quotes_total = scan_stats.get("quotes_total", 0)
    
    if quotes_fetched >= 1:
        print(f"✓ quotes_fetched: {quotes_fetched}/{quotes_total}")
    else:
        # NOT an error - just a warning
        reject_histogram = scan_data.get("reject_histogram", {})
        reject_summary = ", ".join(f"{k}={v}" for k, v in reject_histogram.items()) if reject_histogram else "none"
        warnings_list.append(
            f"⚠ quotes_fetched: {quotes_fetched}/{quotes_total} (network-dependent, not a gate failure)\n"
            f"   Reject reasons: {reject_summary}"
        )

    # 6. Check quotes_attempted (canary check)
    if quotes_total > 0:
        print(f"✓ quotes_attempted: {quotes_total}")
    else:
        warnings_list.append("⚠ quotes_attempted: 0 (no quote attempts made)")

    # Print warnings
    for warning in warnings_list:
        print(warning)

    if errors:
        print()
        for error in errors:
            print(error)
        return False

    print()
    print("✅ M4 invariants satisfied")
    return True


def main():
    print("\n" + "=" * 60)
    print("  ARBY M4 CI GATE (REAL Pipeline)")
    print("=" * 60)
    print()
    print("M4 Success Criteria:")
    print("  - REAL scan executes (no RuntimeError)")
    print("  - 4 artifacts generated")
    print("  - current_block pinned (> 0)")
    print("  - execution_ready_count == 0")
    print()
    print("NOTE: quotes_fetched may be 0 (network-dependent, not a failure)")

    # Step 1: Run pytest
    if not run_command(
        [sys.executable, "-m", "pytest", "-q"],
        "Unit Tests (pytest -q)",
    ):
        print("\n❌ M4 CI GATE FAILED: Tests did not pass")
        sys.exit(1)

    # Step 2: Run REAL scan
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/runs") / f"ci_m4_gate_{timestamp}"

    if not run_command(
        [
            sys.executable, "-m", "strategy.jobs.run_scan",
            "--mode", "real",
            "--cycles", "1",
            "--output-dir", str(output_dir),
        ],
        "REAL Scan (1 cycle)",
    ):
        print("\n❌ M4 CI GATE FAILED: REAL scan failed to execute")
        sys.exit(2)

    # Step 3: Check artifact sanity
    if not check_artifact_sanity(output_dir):
        print("\n❌ M4 CI GATE FAILED: Artifact sanity check failed")
        sys.exit(3)

    # Step 4: Check M4 invariants
    if not check_m4_invariants(output_dir):
        print("\n❌ M4 CI GATE FAILED: M4 invariants check failed")
        sys.exit(4)

    print("\n" + "=" * 60)
    print("  ✅ M4 CI GATE PASSED")
    print("=" * 60)
    print(f"\nArtifacts saved to: {output_dir}")
    print()
    print("M4 Contract Verified:")
    print("  ✓ REAL scan executed successfully")
    print("  ✓ 4 artifacts generated")
    print("  ✓ current_block pinned")
    print("  ✓ execution disabled")
    sys.exit(0)


if __name__ == "__main__":
    main()
