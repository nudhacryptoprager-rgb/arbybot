#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (REAL Pipeline).

M4 SUCCESS CRITERIA (STEP 8):
  ✓ run_mode == "REGISTRY_REAL"
  ✓ current_block > 0 (pinned)
  ✓ execution_ready_count == 0 (execution disabled)
  ✓ quotes_fetched >= 1
  ✓ rpc_success_rate > 0
  ✓ dexes_active >= 2 (STEP 1: cross-DEX)
  ✓ rpc_total_requests >= 3
  ✓ 4/4 artifacts
  ✓ At least 1 opportunity with dex_buy != dex_sell (STEP 1)
  ✓ No pool_buy == "unknown" (STEP 2)
  ✓ No amount_in_numeraire == "0" for profitable opps (STEP 3)
  ✓ Consistency: truth_report ↔ scan match
"""

import json
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
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

    print("\n✅ All 4 artifacts present")
    return True


def check_m4_invariants(output_dir: Path) -> bool:
    """Check M4 invariants (STRICT + CROSS-DEX)."""
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check (STRICT + CROSS-DEX)")
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
        print(f"✓ current_block: {current_block}")
    else:
        errors.append(f"❌ current_block: must be > 0, got {current_block}")

    # 3. execution_ready_count == 0
    stats = truth_report.get("stats", {})
    execution_ready = stats.get("execution_ready_count", 0)
    if execution_ready == 0:
        print(f"✓ execution_ready_count: {execution_ready}")
    else:
        errors.append(f"❌ execution_ready_count: must be 0, got {execution_ready}")

    # 4. quotes_fetched >= 1
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

    # 5. rpc_success_rate > 0
    rpc_stats = scan_data.get("rpc_stats", {})
    rpc_success_rate = rpc_stats.get("success_rate", 0)
    if rpc_success_rate > 0:
        print(f"✓ rpc_success_rate: {rpc_success_rate:.1%}")
    else:
        errors.append(f"❌ rpc_success_rate: must be > 0, got {rpc_success_rate:.1%}")

    # 6. STEP 1: dexes_active >= 2 (cross-DEX)
    dexes_active = scan_stats.get("dexes_active", 0)
    dex_coverage = scan_data.get("dex_coverage", {})
    active_dexes = dex_coverage.get("with_quotes", [])
    if dexes_active >= 2:
        print(f"✓ dexes_active: {dexes_active} ({active_dexes})")
    else:
        errors.append(
            f"❌ dexes_active: must be >= 2 for cross-DEX, got {dexes_active}\n"
            f"   Active DEXes: {active_dexes}"
        )

    # 7. rpc_total_requests >= 3
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

    print("\n✅ M4 invariants satisfied (STRICT)")
    return True


def check_cross_dex_opportunities(output_dir: Path) -> bool:
    """
    STEP 1: Check at least 1 opportunity has dex_buy != dex_sell.
    STEP 2: Check no pool == "unknown".
    STEP 3: Check amount > 0 for profitable opps.
    """
    print(f"\n{'='*60}")
    print("STEP: Cross-DEX Opportunity Validation")
    print("=" * 60)

    errors = []

    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("❌ No truth_report_*.json found")
        for e in errors:
            print(e)
        return False

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    top_opps = truth_report.get("top_opportunities", [])

    if not top_opps:
        # Not an error if no quotes worked - check scan
        scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
        if scan_files:
            with open(scan_files[0], "r") as f:
                scan_data = json.load(f)
            quotes_fetched = scan_data.get("stats", {}).get("quotes_fetched", 0)
            if quotes_fetched < 2:
                print(f"⚠ No opportunities (need >= 2 successful quotes from different DEXes)")
                print(f"  quotes_fetched: {quotes_fetched}")
                print("\n✅ Cross-DEX validation SKIPPED (insufficient quotes)")
                return True
        errors.append("❌ No top_opportunities found")
        for e in errors:
            print(e)
        return False

    # STEP 1: At least 1 opportunity with dex_buy != dex_sell
    cross_dex_opps = [opp for opp in top_opps if opp.get("dex_buy") != opp.get("dex_sell")]
    if cross_dex_opps:
        opp = cross_dex_opps[0]
        print(f"✓ Found cross-DEX opportunity: {opp.get('dex_buy')} → {opp.get('dex_sell')}")
    else:
        errors.append(
            f"❌ No cross-DEX opportunities found (all {len(top_opps)} opps have dex_buy == dex_sell)"
        )

    # STEP 2: No pool == "unknown"
    unknown_pools = []
    for opp in top_opps:
        pool_buy = opp.get("pool_buy", "unknown")
        pool_sell = opp.get("pool_sell", "unknown")
        if pool_buy == "unknown":
            unknown_pools.append(f"{opp.get('spread_id')}.pool_buy")
        if pool_sell == "unknown":
            unknown_pools.append(f"{opp.get('spread_id')}.pool_sell")

    if not unknown_pools:
        print(f"✓ All pools identified (no 'unknown')")
    else:
        errors.append(f"❌ Found 'unknown' pools: {unknown_pools[:5]}")

    # STEP 3: amount > 0 for profitable opps
    zero_amounts = []
    for opp in top_opps:
        if not opp.get("is_profitable"):
            continue
        amount_in = opp.get("amount_in_numeraire", "0")
        try:
            if Decimal(amount_in) <= 0:
                zero_amounts.append(opp.get("spread_id"))
        except:
            zero_amounts.append(opp.get("spread_id"))

    if not zero_amounts:
        print(f"✓ All profitable opps have amount_in > 0")
    else:
        errors.append(f"❌ Profitable opps with amount=0: {zero_amounts[:5]}")

    # STEP 4: All opps have execution_blockers
    opps_without_blockers = [
        opp.get("spread_id") for opp in top_opps
        if not opp.get("execution_blockers")
    ]
    if not opps_without_blockers:
        print(f"✓ All opps have execution_blockers")
    else:
        errors.append(f"❌ Opps without blockers: {opps_without_blockers[:5]}")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print("\n✅ Cross-DEX validation passed")
    return True


def check_consistency(output_dir: Path) -> bool:
    """Check truth_report↔scan consistency."""
    print(f"\n{'='*60}")
    print("STEP: Consistency Check")
    print("=" * 60)

    errors = []

    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))

    if not scan_files or not truth_files:
        errors.append("❌ Missing files")
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

    # quotes_fetched
    scan_quotes = scan_stats.get("quotes_fetched", 0)
    truth_quotes = truth_stats.get("quotes_fetched", 0)
    if scan_quotes == truth_quotes:
        print(f"✓ quotes_fetched consistent: {scan_quotes}")
    else:
        errors.append(f"❌ quotes_fetched: scan={scan_quotes}, truth={truth_quotes}")

    # dexes_active
    scan_dexes = scan_stats.get("dexes_active", 0)
    truth_dexes = truth_health.get("dexes_active", 0)
    if scan_dexes == truth_dexes:
        print(f"✓ dexes_active consistent: {scan_dexes}")
    else:
        errors.append(f"❌ dexes_active: scan={scan_dexes}, truth={truth_dexes}")

    # No is_execution_ready=True when execution disabled
    exec_ready = truth_stats.get("execution_ready_count", 0)
    top_opps = truth_report.get("top_opportunities", [])
    if exec_ready == 0:
        ready_opps = [opp for opp in top_opps if opp.get("is_execution_ready")]
        if not ready_opps:
            print(f"✓ No is_execution_ready=True when disabled")
        else:
            errors.append(f"❌ Found {len(ready_opps)} ready opps when execution disabled")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print("\n✅ Consistency check passed")
    return True


def main():
    print("\n" + "=" * 60)
    print("  ARBY M4 CI GATE (REAL Pipeline - CROSS-DEX)")
    print("=" * 60)
    print()
    print("M4 Criteria:")
    print("  - run_mode: REGISTRY_REAL")
    print("  - current_block > 0")
    print("  - execution_ready_count == 0")
    print("  - quotes_fetched >= 1")
    print("  - rpc_success_rate > 0")
    print("  - dexes_active >= 2 (cross-DEX)")
    print("  - rpc_total_requests >= 3")
    print("  - dex_buy != dex_sell for at least 1 opp")
    print("  - pool != 'unknown'")
    print("  - amount > 0 for profitable opps")
    print("  - 4/4 artifacts")
    print("  - truth_report ↔ scan consistent")

    # Step 1: pytest
    if not run_command(
        [sys.executable, "-m", "pytest", "-q", "--ignore=tests/integration"],
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
        print("\n❌ M4 CI GATE FAILED: Artifacts missing")
        sys.exit(3)

    # Step 4: Invariants
    if not check_m4_invariants(output_dir):
        print("\n❌ M4 CI GATE FAILED: M4 invariants failed")
        sys.exit(4)

    # Step 5: Cross-DEX validation
    if not check_cross_dex_opportunities(output_dir):
        print("\n❌ M4 CI GATE FAILED: Cross-DEX validation failed")
        sys.exit(5)

    # Step 6: Consistency
    if not check_consistency(output_dir):
        print("\n❌ M4 CI GATE FAILED: Consistency failed")
        sys.exit(6)

    print("\n" + "=" * 60)
    print("  ✅ M4 CI GATE PASSED (CROSS-DEX)")
    print("=" * 60)
    print(f"\nArtifacts: {output_dir}")
    print()
    print("M4 Contract Verified:")
    print("  ✓ run_mode: REGISTRY_REAL")
    print("  ✓ current_block pinned")
    print("  ✓ execution disabled")
    print("  ✓ dexes_active >= 2")
    print("  ✓ cross-DEX opportunities")
    print("  ✓ pools identified")
    print("  ✓ amounts populated")
    print("  ✓ consistency verified")
    sys.exit(0)


if __name__ == "__main__":
    main()
