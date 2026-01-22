#!/usr/bin/env python
# PATH: scripts/ci_m3_gate.py
"""
CI Gate for M3 (Opportunity Engine).

This script runs:
  1. pytest -q (all tests must pass)
  2. Smoke scan (generates 4 artifacts)
  3. Artifact sanity check

Required artifacts:
  - snapshots/scan_*.json
  - reports/reject_histogram_*.json
  - reports/truth_report_*.json
  - scan.log

Usage:
  python scripts/ci_m3_gate.py

Exit codes:
  0 - All checks passed
  1 - Tests failed
  2 - Smoke scan failed
  3 - Artifact sanity check failed
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
    Check that smoke scan produced valid artifacts.

    Required artifacts (4 files):
      - snapshots/scan_*.json
      - reports/reject_histogram_*.json
      - reports/truth_report_*.json
      - scan.log

    truth_report must contain:
      - schema_version
      - health (with gate_breakdown)
      - top_opportunities
      - stats
    """
    print(f"\n{'='*60}")
    print("STEP: Artifact Sanity Check")
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

    # Print schema version
    if truth_files:
        with open(truth_files[0], "r") as f:
            truth_report = json.load(f)
        print(f"   schema_version: {truth_report.get('schema_version')}")

    return True


def main():
    print("\n" + "=" * 60)
    print("  ARBY M3 CI GATE")
    print("=" * 60)

    # Step 1: Run pytest
    if not run_command(
        [sys.executable, "-m", "pytest", "-q"],
        "Unit Tests (pytest -q)",
    ):
        print("\n❌ CI GATE FAILED: Tests did not pass")
        sys.exit(1)

    # Step 2: Run smoke scan (stable output-dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/runs") / f"ci_m3_gate_{timestamp}"

    if not run_command(
        [
            sys.executable, "-m", "strategy.jobs.run_scan",
            "--mode", "smoke",
            "--cycles", "1",
            "--output-dir", str(output_dir),
        ],
        "Smoke Scan (1 cycle)",
    ):
        print("\n❌ CI GATE FAILED: Smoke scan failed")
        sys.exit(2)

    # Step 3: Check artifact sanity
    if not check_artifact_sanity(output_dir):
        print("\n❌ CI GATE FAILED: Artifact sanity check failed")
        sys.exit(3)

    print("\n" + "=" * 60)
    print("  ✅ M3 CI GATE PASSED")
    print("=" * 60)
    print(f"\nArtifacts saved to: {output_dir}")
    sys.exit(0)


if __name__ == "__main__":
    main()
