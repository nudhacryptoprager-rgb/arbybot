#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (REAL Pipeline).

M4 SUCCESS CRITERIA:
- REAL scan executes without RuntimeError
- 4 artifacts generated
- run_mode == "REGISTRY_REAL"
- current_block > 0 (pinned)
- execution_ready_count == 0 (execution disabled)
- quotes_fetched >= 1
- rpc_success_rate > 0
- dexes_active >= 1
- rpc_total_requests >= 3
- CONSISTENCY: truth_report matches scan for key metrics

STEP 8: Consistency checks ensure truth_report doesn't "lie"
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

    if not (output_dir / "scan.log").exists():
        errors.append("❌ Missing: scan.log")
    else:
        print("✓ Found: scan.log")

    snapshots_dir = output_dir / "snapshots"
    scan_files = list(snapshots_dir.glob("scan_*.json")) if snapshots_dir.exists() else []
    if not scan_files:
        errors.append("❌ Missing: snapshots/scan_*.json")
    else:
        print(f"✓ Found: {scan_files[0].name}")

    reports_dir = output_dir / "reports"
    histogram_files = list(reports_dir.glob("reject_histogram_*.json")) if reports_dir.exists() else []
    if not histogram_files:
        errors.append("❌ Missing: reports/reject_histogram_*.json")
    else:
        print(f"✓ Found: {histogram_files[0].name}")

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
    """Check M4 invariants (STRICT)."""
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check (STRICT)")
    print("=" * 60)

    errors = []

    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if not scan_files:
        errors.append("❌ No scan_*.json found")
        for e in errors:
            print(e)
        return False

    with open(scan_files[0], "r") as f:
        scan_data = json.load(f)

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
        errors.append(
            f"❌ quotes_fetched: must be >= 1, got {quotes_fetched}/{quotes_total}\n"
            f"   Reject histogram: {reject_histogram}"
        )

    # 5. rpc_success_rate > 0 (STRICT)
    rpc_stats = scan_data.get("rpc_stats", {})
    rpc_success_rate = rpc_stats.get("success_rate", 0)
    if rpc_success_rate > 0:
        print(f"✓ rpc_success_rate: {rpc_success_rate:.1%}")
    else:
        errors.append(f"❌ rpc_success_rate: must be > 0, got {rpc_success_rate:.1%}")

    # 6. dexes_active >= 1 (STRICT)
    dexes_active = scan_stats.get("dexes_active", 0)
    if dexes_active >= 1:
        print(f"✓ dexes_active: {dexes_active}")
    else:
        errors.append(f"❌ dexes_active: must be >= 1, got {dexes_active}")

    # 7. rpc_total_requests >= 3 (STRICT)
    rpc_total = rpc_stats.get("total_requests", 0)
    if rpc_total >= 3:
        print(f"✓ rpc_total_requests: {rpc_total}")
    else:
        errors.append(f"❌ rpc_total_requests: must be >= 3, got {rpc_total}")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print()
    print("✅ M4 invariants satisfied (STRICT)")
    return True


def check_consistency(output_dir: Path) -> bool:
    """
    STEP 8: Check truth_report↔scan consistency.
    
    This catches "lying telemetry" where truth_report shows 0% metrics
    but scan shows 100% quotes_fetched.
    """
    print(f"\n{'='*60}")
    print("STEP: Consistency Check (truth_report↔scan)")
    print("=" * 60)

    errors = []

    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))

    if not scan_files or not truth_files:
        errors.append("❌ Missing files for consistency check")
        for e in errors:
            print(e)
        return False

    with open(scan_files[0], "r") as f:
        scan_data = json.load(f)

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    scan_stats = scan_data.get("stats", {})
    truth_stats = truth_report.get("stats", {})
    truth_health = truth_report.get("health", {})

    # 1. quotes_fetched consistency
    scan_quotes = scan_stats.get("quotes_fetched", 0)
    truth_quotes = truth_stats.get("quotes_fetched", 0)
    if scan_quotes == truth_quotes:
        print(f"✓ quotes_fetched consistent: {scan_quotes}")
    else:
        errors.append(f"❌ quotes_fetched mismatch: scan={scan_quotes}, truth={truth_quotes}")

    # 2. quote_fetch_rate consistency
    scan_total = scan_stats.get("quotes_total", 0)
    if scan_total > 0:
        expected_rate = round(scan_quotes / scan_total, 3)
        truth_rate = truth_health.get("quote_fetch_rate", 0)
        if abs(expected_rate - truth_rate) < 0.01:
            print(f"✓ quote_fetch_rate consistent: {truth_rate}")
        else:
            errors.append(f"❌ quote_fetch_rate mismatch: expected={expected_rate}, truth={truth_rate}")

    # 3. rpc_success_rate consistency
    rpc_stats = scan_data.get("rpc_stats", {})
    scan_rpc_rate = rpc_stats.get("success_rate", 0)
    truth_rpc_rate = truth_health.get("rpc_success_rate", 0)
    if abs(scan_rpc_rate - truth_rpc_rate) < 0.01:
        print(f"✓ rpc_success_rate consistent: {truth_rpc_rate}")
    else:
        errors.append(f"❌ rpc_success_rate mismatch: scan={scan_rpc_rate}, truth={truth_rpc_rate}")

    # 4. execution_ready_count consistency
    scan_exec_ready = scan_stats.get("execution_ready_count", 0)
    truth_exec_ready = truth_stats.get("execution_ready_count", 0)
    if scan_exec_ready == truth_exec_ready:
        print(f"✓ execution_ready_count consistent: {scan_exec_ready}")
    else:
        errors.append(f"❌ execution_ready_count mismatch: scan={scan_exec_ready}, truth={truth_exec_ready}")

    # 5. If execution_ready_count == 0, no opportunity can have is_execution_ready=True
    top_opps = truth_report.get("top_opportunities", [])
    if truth_exec_ready == 0:
        ready_opps = [opp for opp in top_opps if opp.get("is_execution_ready", False)]
        if len(ready_opps) == 0:
            print(f"✓ No is_execution_ready=True when execution disabled")
        else:
            errors.append(
                f"❌ Found {len(ready_opps)} opps with is_execution_ready=True but execution_ready_count=0\n"
                f"   Violating spread_ids: {[opp.get('spread_id') for opp in ready_opps]}"
            )

    # 6. All opportunities must have execution_blockers when execution disabled
    if truth_exec_ready == 0:
        opps_without_blockers = [opp for opp in top_opps if not opp.get("execution_blockers")]
        if len(opps_without_blockers) == 0:
            print(f"✓ All opportunities have execution_blockers")
        else:
            errors.append(
                f"❌ Found {len(opps_without_blockers)} opps without execution_blockers\n"
                f"   Violating spread_ids: {[opp.get('spread_id') for opp in opps_without_blockers]}"
            )

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print()
    print("✅ Consistency check passed (truth_report matches scan)")
    return True


def main():
    print("\n" + "=" * 60)
    print("  ARBY M4 CI GATE (REAL Pipeline - STRICT + CONSISTENCY)")
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
    print("  - CONSISTENCY: truth_report ↔ scan match")

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
        sys.exit(4)

    # Step 5: Consistency (truth_report↔scan)
    if not check_consistency(output_dir):
        print("\n❌ M4 CI GATE FAILED: Consistency check failed")
        print()
        print("TROUBLESHOOTING:")
        print("  - truth_report must match scan for key metrics")
        print("  - If execution_ready_count=0, no opp can be is_execution_ready=True")
        print("  - All opps must have execution_blockers when execution disabled")
        sys.exit(5)

    print("\n" + "=" * 60)
    print("  ✅ M4 CI GATE PASSED (STRICT + CONSISTENCY)")
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
    print("  ✓ truth_report ↔ scan CONSISTENT")
    sys.exit(0)


if __name__ == "__main__":
    main()
