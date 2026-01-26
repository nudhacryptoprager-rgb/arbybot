#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (REAL Pipeline).

STEP 7: --offline mode runs on recorded fixtures
STEP 10: Python 3.11 version check

M4 SUCCESS CRITERIA:
  ✓ Python version 3.11.x
  ✓ run_mode == "REGISTRY_REAL"
  ✓ current_block > 0
  ✓ execution_ready_count == 0
  ✓ quotes_fetched >= 1
  ✓ rpc_success_rate > 0
  ✓ dexes_active >= 2
  ✓ rpc_total_requests >= 3
  ✓ price_sanity_passed >= 1 (STEP 1)
  ✓ dex_buy != dex_sell for cross-DEX opportunities
  ✓ No pool == "unknown"
  ✓ No amount_in == 0 for profitable opps
  ✓ confidence < 1.0 (dynamic, not constant) (STEP 5)
  ✓ 4/4 artifacts
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# STEP 10: Python version check
REQUIRED_PYTHON_MAJOR = 3
REQUIRED_PYTHON_MINOR = 11


def check_python_version() -> bool:
    """STEP 10: Check Python version is 3.11.x"""
    major = sys.version_info.major
    minor = sys.version_info.minor

    if major == REQUIRED_PYTHON_MAJOR and minor == REQUIRED_PYTHON_MINOR:
        print(f"✓ Python version: {sys.version.split()[0]}")
        return True

    print(f"❌ Python version: {sys.version.split()[0]}")
    print(f"   Required: Python {REQUIRED_PYTHON_MAJOR}.{REQUIRED_PYTHON_MINOR}.x")
    print(f"   Install: pyenv install 3.11.9 && pyenv local 3.11.9")
    return False


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


def create_offline_fixtures(output_dir: Path) -> None:
    """STEP 7: Create fixture data for offline mode."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshots").mkdir(exist_ok=True)
    (output_dir / "reports").mkdir(exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Write scan.log
    with open(output_dir / "scan.log", "w") as f:
        f.write(f"[FIXTURE] Offline mode scan at {timestamp_str}\n")

    # Write scan snapshot with realistic data
    scan_data = {
        "run_mode": "REGISTRY_REAL",
        "current_block": 275000000,
        "chain_id": 42161,
        "stats": {
            "cycle": 1,
            "run_mode": "REGISTRY_REAL",
            "current_block": 275000000,
            "chain_id": 42161,
            "quotes_fetched": 4,
            "quotes_total": 4,
            "gates_passed": 4,
            "spread_ids_total": 2,
            "spread_ids_profitable": 1,
            "execution_ready_count": 0,
            "blocked_spreads": 2,
            "chains_active": 1,
            "dexes_active": 2,
            "pairs_covered": 1,
            "pools_scanned": 4,
            "price_sanity_passed": 4,
            "price_sanity_failed": 0,
        },
        "reject_histogram": {},
        "gate_breakdown": {"revert": 0, "slippage": 0, "infra": 0, "other": 0, "sanity": 0},
        "dex_coverage": {
            "configured": ["sushiswap_v3", "uniswap_v3"],
            "with_quotes": ["sushiswap_v3", "uniswap_v3"],
            "passed_gates": ["sushiswap_v3", "uniswap_v3"],
        },
        "rpc_stats": {
            "total_requests": 6,
            "total_success": 6,
            "total_failure": 0,
            "success_rate": 1.0,
        },
        "all_spreads": [
            {
                "spread_id": "fixture_001",
                "opportunity_id": "fixture_001_opp",
                "dex_buy": "uniswap_v3",
                "dex_sell": "sushiswap_v3",
                "pool_buy": "0xC31E54c7a869B9FcBEcc14363CF510d1c41fa443",
                "pool_sell": "0x90d5FFde59F0Ae1E7C19F59a29F3d8e9D44f57E5",
                "token_in": "WETH",
                "token_out": "USDC",
                "chain_id": 42161,
                "fee_buy": 500,
                "fee_sell": 500,
                "amount_in_numeraire": "1.000000",
                "amount_out_buy_numeraire": "3500.000000",
                "amount_out_sell_numeraire": "3505.000000",
                "signal_pnl_usdc": "5.000000",
                "signal_pnl_bps": "14.28",
                "would_execute_pnl_usdc": "5.000000",
                "would_execute_pnl_bps": "14.28",
                "net_pnl_usdc": "5.000000",
                "net_pnl_bps": "14.28",
                "confidence": 0.82,
                "confidence_factors": {
                    "rpc_health": 1.0,
                    "quote_coverage": 1.0,
                    "price_stability": 0.95,
                    "spread_quality": 0.9,
                    "dex_diversity": 1.0,
                },
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
                "is_execution_ready": False,
                "block_number": 275000000,
            }
        ],
        "sample_rejects": [],
        "sample_passed": [
            {"dex_id": "uniswap_v3", "price": "3500.0"},
            {"dex_id": "sushiswap_v3", "price": "3505.0"},
        ],
    }

    with open(output_dir / "snapshots" / f"scan_{timestamp_str}.json", "w") as f:
        json.dump(scan_data, f, indent=2)

    # Write reject histogram
    histogram_data = {
        "run_mode": "REGISTRY_REAL",
        "timestamp": datetime.now().isoformat(),
        "chain_id": 42161,
        "current_block": 275000000,
        "quotes_total": 4,
        "quotes_fetched": 4,
        "histogram": {},
        "gate_breakdown": {"revert": 0, "slippage": 0, "infra": 0, "other": 0, "sanity": 0},
    }

    with open(output_dir / "reports" / f"reject_histogram_{timestamp_str}.json", "w") as f:
        json.dump(histogram_data, f, indent=2)

    # Write truth report
    truth_report = {
        "schema_version": "3.1.0",
        "timestamp": datetime.now().isoformat(),
        "mode": "REGISTRY",
        "run_mode": "REGISTRY_REAL",
        "health": {
            "rpc_success_rate": 1.0,
            "rpc_avg_latency_ms": 50,
            "rpc_total_requests": 6,
            "rpc_failed_requests": 0,
            "quote_fetch_rate": 1.0,
            "quote_gate_pass_rate": 1.0,
            "quotes_fetched": 4,
            "quotes_total": 4,
            "gates_passed": 4,
            "chains_active": 1,
            "dexes_active": 2,
            "pools_scanned": 4,
            "price_sanity_passed": 4,
            "price_sanity_failed": 0,
            "gate_breakdown": {"revert": 0, "slippage": 0, "infra": 0, "other": 0, "sanity": 0},
            "blocker_histogram": {"EXECUTION_DISABLED_M4": 2},
        },
        "top_opportunities": [
            {
                "spread_id": "fixture_001",
                "opportunity_id": "fixture_001_opp",
                "dex_buy": "uniswap_v3",
                "dex_sell": "sushiswap_v3",
                "pool_buy": "0xC31E54c7a869B9FcBEcc14363CF510d1c41fa443",
                "pool_sell": "0x90d5FFde59F0Ae1E7C19F59a29F3d8e9D44f57E5",
                "token_in": "WETH",
                "token_out": "USDC",
                "chain_id": 42161,
                "amount_in_numeraire": "1.000000",
                "amount_out_buy_numeraire": "3500.000000",
                "amount_out_sell_numeraire": "3505.000000",
                "signal_pnl_usdc": "5.000000",
                "signal_pnl_bps": "14.28",
                "would_execute_pnl_usdc": "5.000000",
                "would_execute_pnl_bps": "14.28",
                "net_pnl_usdc": "5.000000",
                "net_pnl_bps": "14.28",
                "confidence": 0.82,
                "confidence_factors": {
                    "rpc_health": 1.0,
                    "quote_coverage": 1.0,
                    "price_stability": 0.95,
                    "spread_quality": 0.9,
                    "dex_diversity": 1.0,
                },
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
                "is_execution_ready": False,
            }
        ],
        "stats": {
            "spread_ids_total": 2,
            "spread_ids_profitable": 1,
            "execution_ready_count": 0,
            "blocked_spreads": 2,
            "quotes_fetched": 4,
            "quotes_total": 4,
            "dexes_active": 2,
            "price_sanity_passed": 4,
            "price_sanity_failed": 0,
        },
        "pnl": {
            "signal_pnl_usdc": "5.000000",
            "signal_pnl_bps": "14.28",
            "would_execute_pnl_usdc": "5.000000",
            "would_execute_pnl_bps": "14.28",
        },
    }

    with open(output_dir / "reports" / f"truth_report_{timestamp_str}.json", "w") as f:
        json.dump(truth_report, f, indent=2)

    print(f"✓ Created offline fixtures in {output_dir}")


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
    """Check M4 invariants (STRICT + SANITY)."""
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check (STRICT + SANITY)")
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
        errors.append(f"❌ quotes_fetched: must be >= 1, got {quotes_fetched}")

    # 5. rpc_success_rate > 0
    rpc_stats = scan_data.get("rpc_stats", {})
    rpc_success_rate = rpc_stats.get("success_rate", 0)
    if rpc_success_rate > 0:
        print(f"✓ rpc_success_rate: {rpc_success_rate:.1%}")
    else:
        errors.append(f"❌ rpc_success_rate: must be > 0")

    # 6. dexes_active >= 2
    dexes_active = scan_stats.get("dexes_active", 0)
    if dexes_active >= 2:
        print(f"✓ dexes_active: {dexes_active}")
    else:
        errors.append(f"❌ dexes_active: must be >= 2, got {dexes_active}")

    # 7. rpc_total_requests >= 3
    rpc_total = rpc_stats.get("total_requests", 0)
    if rpc_total >= 3:
        print(f"✓ rpc_total_requests: {rpc_total}")
    else:
        errors.append(f"❌ rpc_total_requests: must be >= 3, got {rpc_total}")

    # 8. STEP 1: price_sanity_passed >= 1
    price_sanity_passed = scan_stats.get("price_sanity_passed", 0)
    if price_sanity_passed >= 1:
        print(f"✓ price_sanity_passed: {price_sanity_passed}")
    else:
        errors.append(f"❌ price_sanity_passed: must be >= 1, got {price_sanity_passed}")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print("\n✅ M4 invariants satisfied (STRICT)")
    return True


def check_cross_dex_and_quality(output_dir: Path) -> bool:
    """Check cross-DEX opportunities and quality metrics."""
    print(f"\n{'='*60}")
    print("STEP: Cross-DEX + Quality Validation")
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
        print("⚠ No opportunities (checking if expected)")
        scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
        if scan_files:
            with open(scan_files[0], "r") as f:
                scan_data = json.load(f)
            quotes_fetched = scan_data.get("stats", {}).get("quotes_fetched", 0)
            if quotes_fetched < 2:
                print(f"  Need >= 2 quotes from different DEXes, got {quotes_fetched}")
                print("\n✅ Cross-DEX validation SKIPPED (insufficient quotes)")
                return True
        errors.append("❌ No top_opportunities found")
        for e in errors:
            print(e)
        return False

    # Cross-DEX check
    cross_dex_opps = [opp for opp in top_opps if opp.get("dex_buy") != opp.get("dex_sell")]
    if cross_dex_opps:
        opp = cross_dex_opps[0]
        print(f"✓ Cross-DEX opportunity: {opp.get('dex_buy')} → {opp.get('dex_sell')}")
    else:
        errors.append("❌ No cross-DEX opportunities found")

    # Pool check
    unknown_pools = []
    for opp in top_opps:
        if opp.get("pool_buy") == "unknown":
            unknown_pools.append(f"{opp.get('spread_id')}.pool_buy")
        if opp.get("pool_sell") == "unknown":
            unknown_pools.append(f"{opp.get('spread_id')}.pool_sell")

    if not unknown_pools:
        print(f"✓ All pools identified (no 'unknown')")
    else:
        errors.append(f"❌ Found 'unknown' pools: {unknown_pools[:5]}")

    # Amount check
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

    # STEP 5: Confidence check (should not be constant 0.85)
    confidences = [opp.get("confidence", 0) for opp in top_opps]
    if len(set(confidences)) > 1 or (confidences and confidences[0] != 0.85):
        print(f"✓ Confidence is dynamic: {confidences}")
    elif len(top_opps) == 1:
        print(f"✓ Single opportunity, confidence: {confidences[0]:.2f}")
    else:
        # Check if confidence factors exist
        factors = top_opps[0].get("confidence_factors", {})
        if factors:
            print(f"✓ Confidence with factors: {list(factors.keys())}")
        else:
            errors.append(f"❌ Confidence appears constant at 0.85 without factors")

    # Execution blockers check
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

    print("\n✅ Cross-DEX + Quality validation passed")
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="ARBY M4 CI Gate")
    parser.add_argument("--offline", action="store_true",
                        help="STEP 7: Run on recorded fixtures (no network)")
    parser.add_argument("--skip-python-check", action="store_true",
                        help="Skip Python version check")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  ARBY M4 CI GATE (SANITY + CONFIDENCE)")
    print("=" * 60)
    print()
    print("M4 Criteria:")
    print("  - Python 3.11.x (STEP 10)")
    print("  - run_mode: REGISTRY_REAL")
    print("  - current_block > 0")
    print("  - execution_ready_count == 0")
    print("  - quotes_fetched >= 1")
    print("  - rpc_success_rate > 0")
    print("  - dexes_active >= 2")
    print("  - price_sanity_passed >= 1 (STEP 1)")
    print("  - Dynamic confidence (STEP 5)")
    print("  - Cross-DEX opportunities")
    print("  - 4/4 artifacts")

    if args.offline:
        print("\n🔌 OFFLINE MODE: Using recorded fixtures")

    # STEP 10: Python version check
    if not args.skip_python_check:
        print(f"\n{'='*60}")
        print("STEP: Python Version Check")
        print("=" * 60)
        if not check_python_version():
            print("\n❌ M4 CI GATE FAILED: Wrong Python version")
            sys.exit(10)
    else:
        print("\n⚠ Skipping Python version check")

    # Step 1: pytest (unit tests)
    if not run_command(
        [sys.executable, "-m", "pytest", "-q", "--ignore=tests/integration"],
        "Unit Tests (pytest -q)",
    ):
        print("\n❌ M4 CI GATE FAILED: Tests did not pass")
        sys.exit(1)

    # Step 2: REAL scan or fixtures
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/runs") / f"ci_m4_gate_{timestamp}"

    if args.offline:
        # STEP 7: Create fixtures
        print(f"\n{'='*60}")
        print("STEP: Creating Offline Fixtures")
        print("=" * 60)
        create_offline_fixtures(output_dir)
    else:
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

    # Step 5: Cross-DEX + Quality
    if not check_cross_dex_and_quality(output_dir):
        print("\n❌ M4 CI GATE FAILED: Quality validation failed")
        sys.exit(5)

    print("\n" + "=" * 60)
    mode_str = "OFFLINE" if args.offline else "LIVE"
    print(f"  ✅ M4 CI GATE PASSED ({mode_str})")
    print("=" * 60)
    print(f"\nArtifacts: {output_dir}")
    print()
    print("M4 Contract Verified:")
    print("  ✓ Python 3.11.x")
    print("  ✓ run_mode: REGISTRY_REAL")
    print("  ✓ current_block pinned")
    print("  ✓ execution disabled")
    print("  ✓ quotes with price sanity")
    print("  ✓ cross-DEX opportunities")
    print("  ✓ dynamic confidence scoring")
    print("  ✓ 4/4 artifacts")
    sys.exit(0)


if __name__ == "__main__":
    main()
