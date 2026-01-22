#!/usr/bin/env python
# PATH: scripts/ci_m3_gate.py
"""
CI Gate for M3 (Opportunity Engine).

This script runs:
  1. pytest -q (all tests must pass)
  2. Smoke scan (generates 3 artifacts)
  3. Artifact sanity check (truth_report has required keys)

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
import tempfile
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
    
    Required artifacts:
      - snapshots/scan_*.json
      - reports/reject_histogram_*.json
      - reports/truth_report_*.json
    
    truth_report must contain:
      - schema_version
      - health (with gate_breakdown)
      - top_opportunities
      - stats
    """
    print(f"\n{'='*60}")
    print("STEP: Artifact Sanity Check")
    print("=" * 60)
    
    errors = []
    
    # Check scan artifact
    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if not scan_files:
        errors.append("Missing snapshots/scan_*.json")
    
    # Check reject histogram
    histogram_files = list((output_dir / "reports").glob("reject_histogram_*.json"))
    if not histogram_files:
        errors.append("Missing reports/reject_histogram_*.json")
    
    # Check truth report
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("Missing reports/truth_report_*.json")
    else:
        # Validate truth report content
        with open(truth_files[0], "r") as f:
            truth_report = json.load(f)
        
        required_keys = ["schema_version", "health", "top_opportunities", "stats"]
        for key in required_keys:
            if key not in truth_report:
                errors.append(f"truth_report missing key: {key}")
        
        # Check health section
        if "health" in truth_report:
            health = truth_report["health"]
            if "gate_breakdown" not in health:
                errors.append("health missing gate_breakdown")
            else:
                gate_breakdown = health["gate_breakdown"]
                required_gates = ["revert", "slippage", "infra", "other"]
                for gate in required_gates:
                    if gate not in gate_breakdown:
                        errors.append(f"gate_breakdown missing key: {gate}")
    
    if errors:
        for error in errors:
            print(f"❌ {error}")
        return False
    
    print("✅ All artifacts present and valid")
    print(f"   - scan: {scan_files[0].name}")
    print(f"   - histogram: {histogram_files[0].name}")
    print(f"   - truth_report: {truth_files[0].name}")
    
    # Print schema version
    if truth_files:
        with open(truth_files[0], "r") as f:
            truth_report = json.load(f)
        print(f"   - schema_version: {truth_report.get('schema_version')}")
    
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
    
    # Step 2: Run smoke scan
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "ci_smoke_run"
        
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
    sys.exit(0)


if __name__ == "__main__":
    main()
