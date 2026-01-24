#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (Execution Layer - Phase 1: REAL Pipeline).

This script runs:
  1. pytest -q (all tests must pass)
  2. REAL scan with EXPLICIT ENABLE (--allow-real --config)
  3. Artifact sanity check (same 4/4 as M3)
  4. M4 invariants check

REAL MODE SAFETY:
- Uses --allow-real --config config/real_minimal.yaml
- This is the ONLY place where REAL mode should be explicitly enabled in CI
- Tests do NOT enable REAL (they expect RuntimeError without explicit enable)

M4 REQUIREMENTS:
- --mode real runs pipeline (execution disabled)
- truth_report.run_mode == "REGISTRY_REAL"
- truth_report.schema_version == "3.0.0"
- quotes_fetched >= 1 (if quoting works)
- current_block is pinned (not None, > 0)
- execution_ready_count == 0 (EXECUTION_DISABLED_M4)

ARTIFACTS (same 4/4 as M3):
  - snapshots/scan_*.json
  - reports/reject_histogram_*.json
  - reports/truth_report_*.json
  - scan.log

Usage:
  python scripts/ci_m4_gate.py

Exit codes:
  0 - All checks passed
  1 - Tests failed
  2 - REAL scan failed
  3 - Artifact sanity check failed
  4 - M4 invariants failed (including quotes_fetched < 1)
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
    Check that REAL scan produced valid artifacts (same 4/4 as M3).
    
    Required artifacts:
    - snapshots/scan_*.json
    - reports/reject_histogram_*.json
    - reports/truth_report_*.json
    - scan.log
    """
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
    """
    Check M4-specific invariants for REAL mode.
    
    M4 INVARIANTS:
    - run_mode == "REGISTRY_REAL"
    - schema_version == "3.0.0"
    - quotes_fetched >= 1 (CRITICAL for M4)
    - current_block > 0 (pinned)
    - execution_ready_count == 0 (execution disabled)
    """
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check")
    print("=" * 60)

    errors = []
    warnings_list = []

    # Load truth report
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("❌ Cannot check M4 invariants: no truth_report")
        for error in errors:
            print(error)
        return False

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    # 1. Check run_mode == "REGISTRY_REAL"
    run_mode = truth_report.get("run_mode", "")
    if run_mode == "REGISTRY_REAL":
        print(f"✓ run_mode: {run_mode}")
    else:
        errors.append(f"❌ run_mode should be REGISTRY_REAL, got: {run_mode}")

    # 2. Check schema_version == "3.0.0"
    schema_version = truth_report.get("schema_version", "")
    if schema_version == "3.0.0":
        print(f"✓ schema_version: {schema_version}")
    else:
        errors.append(f"❌ schema_version should be 3.0.0, got: {schema_version}")

    # 3. Load scan snapshot for block and quotes
    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    quotes_fetched = 0
    current_block = None
    
    if scan_files:
        with open(scan_files[0], "r") as f:
            scan_data = json.load(f)

        # Check pinned block (M4 invariant)
        current_block = scan_data.get("current_block")
        if current_block is not None and current_block > 0:
            print(f"✓ current_block: {current_block} (pinned)")
        else:
            errors.append(f"❌ current_block must be pinned (> 0), got: {current_block}")

        # Check quotes_fetched >= 1 (CRITICAL M4 requirement)
        stats = scan_data.get("stats", {})
        quotes_fetched = stats.get("quotes_fetched", 0)
        quotes_total = stats.get("quotes_total", 0)
        
        if quotes_fetched >= 1:
            print(f"✓ quotes_fetched: {quotes_fetched}/{quotes_total} (>= 1 required)")
        else:
            # This is a CRITICAL failure - quoting didn't work
            reject_histogram = scan_data.get("reject_histogram", {})
            reject_summary = ", ".join(f"{k}={v}" for k, v in reject_histogram.items())
            errors.append(
                f"❌ quotes_fetched must be >= 1, got: {quotes_fetched}/{quotes_total}\n"
                f"   REAL pipeline ran but quoting failed.\n"
                f"   Reject reasons: {reject_summary or 'none'}\n"
                f"   Check: RPC connectivity, quoter addresses, network state."
            )

        # Check run_mode in scan matches
        scan_run_mode = scan_data.get("run_mode", "")
        if scan_run_mode == "REGISTRY_REAL":
            print(f"✓ scan.run_mode: {scan_run_mode}")
        else:
            warnings_list.append(f"⚠ scan.run_mode: {scan_run_mode} (expected REGISTRY_REAL)")

    # 4. Check reject histogram
    histogram_files = list((output_dir / "reports").glob("reject_histogram_*.json"))
    if histogram_files:
        with open(histogram_files[0], "r") as f:
            histogram = json.load(f)

        hist_data = histogram.get("histogram", {})
        if hist_data:
            print(f"✓ reject_histogram: {len(hist_data)} codes - {list(hist_data.keys())}")
        else:
            if quotes_fetched > 0:
                print("✓ reject_histogram: empty (all quotes passed)")
            else:
                warnings_list.append("⚠ reject_histogram is empty but quotes_fetched=0")

    # 5. Check execution is disabled (execution_ready_count == 0)
    stats = truth_report.get("stats", {})
    execution_ready = stats.get("execution_ready_count", 0)
    if execution_ready == 0:
        print(f"✓ execution_ready_count: {execution_ready} (M4: execution disabled)")
    else:
        errors.append(f"❌ execution_ready_count should be 0 (M4: execution disabled), got: {execution_ready}")

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
    print("M4 Requirements:")
    print("  - run_mode: REGISTRY_REAL")
    print("  - quotes_fetched >= 1")
    print("  - current_block pinned (> 0)")
    print("  - execution_ready_count == 0")
    print("  - 4/4 artifacts generated")
    print()
    print("REAL MODE: Using --allow-real --config config/real_minimal.yaml")

    # Step 1: Run pytest
    if not run_command(
        [sys.executable, "-m", "pytest", "-q"],
        "Unit Tests (pytest -q)",
    ):
        print("\n❌ CI GATE FAILED: Tests did not pass")
        sys.exit(1)

    # Step 2: Run REAL scan WITH EXPLICIT ENABLE
    # This is the ONLY place where REAL mode is explicitly enabled in CI
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/runs") / f"ci_m4_gate_{timestamp}"

    # Check config exists
    config_path = Path("config/real_minimal.yaml")
    if not config_path.exists():
        print(f"\n❌ CI GATE FAILED: Config not found: {config_path}")
        print("Create config/real_minimal.yaml for REAL mode.")
        sys.exit(2)

    if not run_command(
        [
            sys.executable, "-m", "strategy.jobs.run_scan",
            "--mode", "real",
            "--allow-real",  # Explicit enable
            "--config", str(config_path),  # Also explicit enable
            "--cycles", "1",
            "--output-dir", str(output_dir),
        ],
        "REAL Scan (1 cycle) with explicit enable",
    ):
        print("\n❌ CI GATE FAILED: REAL scan failed")
        sys.exit(2)

    # Step 3: Check artifact sanity (M3 contract - 4/4 artifacts)
    if not check_artifact_sanity(output_dir):
        print("\n❌ CI GATE FAILED: Artifact sanity check failed")
        sys.exit(3)

    # Step 4: Check M4 invariants (including quotes_fetched >= 1)
    if not check_m4_invariants(output_dir):
        print("\n❌ CI GATE FAILED: M4 invariants check failed")
        print()
        print("NOTE: If quotes_fetched=0, check:")
        print("  1. RPC endpoints in config/chains.yaml")
        print("  2. Quoter addresses in config/dexes.yaml")
        print("  3. Network connectivity")
        print("  4. ALCHEMY_API_KEY in .env (if using Alchemy)")
        sys.exit(4)

    print("\n" + "=" * 60)
    print("  ✅ M4 CI GATE PASSED")
    print("=" * 60)
    print(f"\nArtifacts saved to: {output_dir}")
    print()
    print("M4 Contract Verified:")
    print("  ✓ run_mode: REGISTRY_REAL")
    print("  ✓ quotes_fetched >= 1")
    print("  ✓ current_block pinned")
    print("  ✓ execution disabled")
    print("  ✓ 4/4 artifacts generated")
    sys.exit(0)


if __name__ == "__main__":
    main()
