#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (REAL Pipeline).

M4 SUCCESS CRITERIA (all must pass):
- REAL scan executes without RuntimeError
- 4 artifacts generated
- run_mode == "REGISTRY_REAL"
- current_block > 0 (pinned)
- execution_ready_count == 0 (execution disabled)
- quotes_fetched >= 1 (STRICT)
- rpc_success_rate > 0 (STRICT)
- dexes_active >= 1 (STRICT)
- rpc_total_requests >= 3 (STRICT)

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
    """Check all 4 artifacts exist."""
    print(f"\n{'='*60}")
    print("STEP: Artifact Sanity Check")
    print(f"DIR:  {output_dir}")
    print("=" * 60)

    errors = []

    # 1. scan.log
    if not (output_dir / "scan.log").exists():
        errors.append("❌ Missing: scan.log")
    else:
        print("✓ Found: scan.log")

    # 2. scan_*.json
    snapshots_dir = output_dir / "snapshots"
    scan_files = list(snapshots_dir.glob("scan_*.json")) if snapshots_dir.exists() else []
    if not scan_files:
        errors.append("❌ Missing: snapshots/scan_*.json")
    else:
        print(f"✓ Found: {scan_files[0].name}")

    # 3. reject_histogram_*.json
    reports_dir = output_dir / "reports"
    histogram_files = list(reports_dir.glob("reject_histogram_*.json")) if reports_dir.exists() else []
    if not histogram_files:
        errors.append("❌ Missing: reports/reject_histogram_*.json")
    else:
        print(f"✓ Found: {histogram_files[0].name}")

    # 4. truth_report_*.json
    truth_files = list(reports_dir.glob("truth_report_*.json")) if reports_dir.exists() else []
    if not truth_files:
        errors.append("❌ Missing: reports/truth_report_*.json")
    else:
        print(f"✓ Found: {truth_files[0].name}")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print()
    print("✅ All 4 artifacts present")
    return True


def check_m4_invariants(output_dir: Path) -> bool:
    """
    Check M4 invariants (STRICT).
    
    REQUIRED:
    - run_mode == "REGISTRY_REAL"
    - current_block > 0
    - execution_ready_count == 0
    - quotes_fetched >= 1
    - rpc_success_rate > 0
    - dexes_active >= 1
    - rpc_total_requests >= 3
    """
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check (STRICT)")
    print("=" * 60)

    errors = []

    # Load scan snapshot
    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if not scan_files:
        errors.append("❌ No scan_*.json found")
        for e in errors:
            print(e)
        return False

    with open(scan_files[0], "r") as f:
        scan_data = json.load(f)

    # Load truth report
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("❌ No truth_report_*.json found")
        for e in errors:
            print(e)
        return False

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    # 1. run_mode
    run_mode = scan_data.get("run_mode", "")
    if run_mode == "REGISTRY_REAL":
        print(f"✓ run_mode: {run_mode}")
    else:
        errors.append(f"❌ run_mode: expected REGISTRY_REAL, got {run_mode}")

    # 2. current_block > 0
    current_block = scan_data.get("current_block", 0)
    if current_block and current_block > 0:
        print(f"✓ current_block: {current_block} (pinned)")
    else:
        errors.append(f"❌ current_block: must be > 0, got {current_block}")

    # 3. execution_ready_count == 0
    stats = truth_report.get("stats", {})
    execution_ready = stats.get("execution_ready_count", 0)
    if execution_ready == 0:
        print(f"✓ execution_ready_count: {execution_ready} (execution disabled)")
    else:
        errors.append(f"❌ execution_ready_count: must be 0, got {execution_ready}")

    # 4. quotes_fetched >= 1 (STRICT)
    scan_stats = scan_data.get("stats", {})
    quotes_fetched = scan_stats.get("quotes_fetched", 0)
    quotes_total = scan_stats.get("quotes_total", 0)
    if quotes_fetched >= 1:
        print(f"✓ quotes_fetched: {quotes_fetched}/{quotes_total}")
    else:
        reject_histogram = scan_data.get("reject_histogram", {})
        sample_rejects = scan_data.get("sample_rejects", [])[:3]
        errors.append(
            f"❌ quotes_fetched: must be >= 1, got {quotes_fetched}/{quotes_total}\n"
            f"   Reject histogram: {reject_histogram}\n"
            f"   Sample rejects: {json.dumps(sample_rejects, indent=4)}"
        )

    # 5. rpc_success_rate > 0 (STRICT)
    rpc_stats = scan_data.get("rpc_stats", {})
    rpc_success_rate = rpc_stats.get("success_rate", 0)
    if rpc_success_rate > 0:
        print(f"✓ rpc_success_rate: {rpc_success_rate:.1%}")
    else:
        infra_samples = scan_data.get("infra_samples", [])
        errors.append(
            f"❌ rpc_success_rate: must be > 0, got {rpc_success_rate:.1%}\n"
            f"   Infra samples: {json.dumps(infra_samples, indent=4)}"
        )

    # 6. dexes_active >= 1 (STRICT)
    dexes_active = scan_stats.get("dexes_active", 0)
    if dexes_active >= 1:
        print(f"✓ dexes_active: {dexes_active}")
    else:
        dex_coverage = scan_data.get("dex_coverage", {})
        errors.append(
            f"❌ dexes_active: must be >= 1, got {dexes_active}\n"
            f"   DEX coverage: {dex_coverage}"
        )

    # 7. rpc_total_requests >= 3 (STRICT)
    rpc_total = rpc_stats.get("total_requests", 0)
    if rpc_total >= 3:
        print(f"✓ rpc_total_requests: {rpc_total}")
    else:
        errors.append(f"❌ rpc_total_requests: must be >= 3, got {rpc_total}")

    # Print errors
    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print()
    print("✅ M4 invariants satisfied (STRICT)")
    return True


def main():
    print("\n" + "=" * 60)
    print("  ARBY M4 CI GATE (REAL Pipeline - STRICT)")
    print("=" * 60)
    print()
    print("M4 STRICT Criteria:")
    print("  - run_mode: REGISTRY_REAL")
    print("  - current_block > 0 (pinned)")
    print("  - execution_ready_count == 0")
    print("  - quotes_fetched >= 1")
    print("  - rpc_success_rate > 0")
    print("  - dexes_active >= 1")
    print("  - rpc_total_requests >= 3")
    print("  - 4/4 artifacts")

    # Step 1: pytest
    if not run_command(
        [sys.executable, "-m", "pytest", "-q"],
        "Unit Tests (pytest -q)",
    ):
        print("\n❌ M4 CI GATE FAILED: Tests did not pass")
        sys.exit(1)

    # Step 2: REAL scan
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/runs") / f"ci_m4_gate_{timestamp}"
    config_path = Path("config/real_minimal.yaml")

    cmd = [
        sys.executable, "-m", "strategy.jobs.run_scan",
        "--mode", "real",
        "--cycles", "1",
        "--output-dir", str(output_dir),
    ]
    
    if config_path.exists():
        cmd.extend(["--config", str(config_path)])
        print(f"\nUsing config: {config_path}")

    if not run_command(cmd, "REAL Scan (1 cycle)"):
        print("\n❌ M4 CI GATE FAILED: REAL scan failed")
        sys.exit(2)

    # Step 3: Artifacts
    if not check_artifact_sanity(output_dir):
        print("\n❌ M4 CI GATE FAILED: Artifact check failed")
        sys.exit(3)

    # Step 4: Invariants (STRICT)
    if not check_m4_invariants(output_dir):
        print("\n❌ M4 CI GATE FAILED: M4 invariants failed")
        print()
        print("TROUBLESHOOTING:")
        print("  - Check RPC endpoints in config/real_minimal.yaml")
        print("  - Check network connectivity")
        print("  - Check quoter addresses in config/dexes.yaml")
        print("  - Run manually: python -m strategy.jobs.run_scan --mode real -c 1")
        sys.exit(4)

    print("\n" + "=" * 60)
    print("  ✅ M4 CI GATE PASSED (STRICT)")
    print("=" * 60)
    print(f"\nArtifacts: {output_dir}")
    print()
    print("M4 Contract Verified:")
    print("  ✓ run_mode: REGISTRY_REAL")
    print("  ✓ current_block pinned")
    print("  ✓ execution disabled")
    print("  ✓ quotes_fetched >= 1")
    print("  ✓ rpc_success_rate > 0")
    print("  ✓ dexes_active >= 1")
    print("  ✓ rpc_total_requests >= 3")
    print("  ✓ 4/4 artifacts")
    sys.exit(0)


if __name__ == "__main__":
    main()
