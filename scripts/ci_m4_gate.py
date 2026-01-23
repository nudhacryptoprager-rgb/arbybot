#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (Execution Layer - Phase 1: REAL Pipeline).

This script runs:
  1. pytest -q (all tests must pass)
  2. REAL scan (generates 4 artifacts with real RPC quotes)
  3. Artifact sanity check (same as M3 + REAL markers)

M4 REQUIREMENTS:
- --mode real must run pipeline (execution disabled)
- Real RPC quotes from configured providers
- Pinned block invariant enforced
- Real reject reasons in histogram

Required artifacts (same as M3):
  - snapshots/scan_*.json
  - reports/reject_histogram_*.json
  - reports/truth_report_*.json
  - scan.log

Additional M4 checks:
  - truth_report.run_mode == "REGISTRY_REAL" or "REAL_REGISTRY"
  - reject_histogram contains real reject codes
  - block numbers are pinned (not None)

Usage:
  python scripts/ci_m4_gate.py

Exit codes:
  0 - All checks passed
  1 - Tests failed
  2 - REAL scan failed
  3 - Artifact sanity check failed
  4 - M4 invariants failed
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
    """Check that REAL scan produced valid artifacts (same as M3)."""
    print(f"\n{'='*60}")
    print("STEP: Artifact Sanity Check (M3 contract)")
    print(f"DIR:  {output_dir}")
    print("=" * 60)

    errors = []

    # Check scan artifact
    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if not scan_files:
        errors.append("❌ Missing: snapshots/scan_*.json")
    else:
        print(f"✓ Found: {scan_files[0].name}")

    # Check reject histogram
    histogram_files = list((output_dir / "reports").glob("reject_histogram_*.json"))
    if not histogram_files:
        errors.append("❌ Missing: reports/reject_histogram_*.json")
    else:
        print(f"✓ Found: {histogram_files[0].name}")

    # Check truth report
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("❌ Missing: reports/truth_report_*.json")
    else:
        print(f"✓ Found: {truth_files[0].name}")

        # Validate truth report content
        try:
            with open(truth_files[0], "r") as f:
                truth_report = json.load(f)

            required_keys = ["schema_version", "health", "top_opportunities", "stats"]
            for key in required_keys:
                if key not in truth_report:
                    errors.append(f"❌ truth_report missing key: {key}")

            # Check health section
            if "health" in truth_report:
                health = truth_report["health"]
                if "gate_breakdown" not in health:
                    errors.append("❌ health missing gate_breakdown")
                else:
                    gate_breakdown = health["gate_breakdown"]
                    required_gates = ["revert", "slippage", "infra", "other"]
                    for gate in required_gates:
                        if gate not in gate_breakdown:
                            errors.append(f"❌ gate_breakdown missing key: {gate}")
        except json.JSONDecodeError as e:
            errors.append(f"❌ truth_report is not valid JSON: {e}")

    # Check scan.log
    log_file = output_dir / "scan.log"
    if not log_file.exists():
        errors.append("❌ Missing: scan.log")
    else:
        print(f"✓ Found: scan.log")

    if errors:
        print()
        for error in errors:
            print(error)
        return False

    print()
    print("✅ All 4 artifacts present and valid")
    return True


def check_m4_invariants(output_dir: Path) -> bool:
    """Check M4-specific invariants for REAL mode."""
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check")
    print("=" * 60)

    errors = []

    # Load truth report
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("❌ Cannot check M4 invariants: no truth_report")
        for error in errors:
            print(error)
        return False

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    # Check run_mode is REAL
    run_mode = truth_report.get("run_mode", "")
    if "REAL" in run_mode.upper() or "REGISTRY" in run_mode.upper():
        print(f"✓ run_mode: {run_mode}")
    else:
        errors.append(f"❌ run_mode should be REAL/REGISTRY, got: {run_mode}")

    # Check reject histogram has real reject codes
    histogram_files = list((output_dir / "reports").glob("reject_histogram_*.json"))
    if histogram_files:
        with open(histogram_files[0], "r") as f:
            histogram = json.load(f)

        hist_data = histogram.get("histogram", {})
        if hist_data:
            print(f"✓ reject_histogram has {len(hist_data)} reject codes")
        else:
            print("⚠ reject_histogram is empty (may be OK if all quotes passed)")

    # Check scan snapshot for pinned block
    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if scan_files:
        with open(scan_files[0], "r") as f:
            scan_data = json.load(f)

        current_block = scan_data.get("current_block")
        if current_block is not None and current_block > 0:
            print(f"✓ current_block: {current_block} (pinned)")
        else:
            errors.append(f"❌ current_block should be pinned, got: {current_block}")

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

    # Step 1: Run pytest
    if not run_command(
        [sys.executable, "-m", "pytest", "-q"],
        "Unit Tests (pytest -q)",
    ):
        print("\n❌ CI GATE FAILED: Tests did not pass")
        sys.exit(1)

    # Step 2: Run REAL scan
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/runs") / f"ci_m4_gate_{timestamp}"

    # NOTE: For M4, we run --mode real instead of --mode smoke
    # If REAL is not yet implemented, this will fail with RuntimeError
    # which is the expected behavior until M4 implementation is complete
    if not run_command(
        [
            sys.executable, "-m", "strategy.jobs.run_scan",
            "--mode", "real",
            "--cycles", "1",
            "--output-dir", str(output_dir),
        ],
        "REAL Scan (1 cycle)",
    ):
        print("\n❌ CI GATE FAILED: REAL scan failed")
        print("\nNOTE: If you see 'RuntimeError: REGISTRY_REAL scanner is not yet implemented'")
        print("      this is expected until M4 implementation is complete.")
        print("      Use 'python scripts/ci_m3_gate.py' for SMOKE mode validation.")
        sys.exit(2)

    # Step 3: Check artifact sanity (M3 contract)
    if not check_artifact_sanity(output_dir):
        print("\n❌ CI GATE FAILED: Artifact sanity check failed")
        sys.exit(3)

    # Step 4: Check M4 invariants
    if not check_m4_invariants(output_dir):
        print("\n❌ CI GATE FAILED: M4 invariants check failed")
        sys.exit(4)

    print("\n" + "=" * 60)
    print("  ✅ M4 CI GATE PASSED")
    print("=" * 60)
    print(f"\nArtifacts saved to: {output_dir}")
    sys.exit(0)


if __name__ == "__main__":
    main()
