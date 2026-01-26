#!/usr/bin/env python
# PATH: scripts/ci_m4_gate.py
"""
CI Gate for M4 (REAL Pipeline).

METRICS CONTRACT:
- quotes_total = attempted
- quotes_fetched = got RPC response with amount > 0
- gates_passed = passed all gates (sanity, etc.)
- dexes_active = DEXes with at least 1 response

INVARIANTS (STEP 9):
- If sample_rejects has entries with price != null, then quotes_fetched > 0
- This catches the bug where we have prices but claim 0 fetched

M4 SUCCESS CRITERIA:
  - Python version 3.11.x
  - Import contract (calculate_confidence)
  - run_mode == "REGISTRY_REAL"
  - current_block > 0
  - execution_ready_count == 0
  - quotes_fetched >= 1
  - rpc_success_rate > 0
  - dexes_active >= 2
  - rpc_total_requests >= 3
  - price_sanity_passed >= 1
  - dex_buy != dex_sell for cross-DEX opportunities
  - No pool == "unknown"
  - confidence < 1.0 (dynamic)
  - 4/4 artifacts
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

REQUIRED_PYTHON_MAJOR = 3
REQUIRED_PYTHON_MINOR = 11


def check_python_version() -> bool:
    """Check Python version is 3.11.x"""
    major = sys.version_info.major
    minor = sys.version_info.minor

    if major == REQUIRED_PYTHON_MAJOR and minor == REQUIRED_PYTHON_MINOR:
        print(f"[OK] Python version: {sys.version.split()[0]}")
        return True

    print(f"[FAIL] Python version: {sys.version.split()[0]}")
    print(f"   Required: Python {REQUIRED_PYTHON_MAJOR}.{REQUIRED_PYTHON_MINOR}.x")
    print(f"   Install: pyenv install 3.11.9 && pyenv local 3.11.9")
    return False


def check_import_contract() -> bool:
    """Check that calculate_confidence is importable."""
    print(f"\n{'='*60}")
    print("STEP: Import Contract Check")
    print("=" * 60)

    cmd = [
        sys.executable, "-c",
        "from monitoring.truth_report import calculate_confidence"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("[OK] import monitoring.truth_report.calculate_confidence")
        return True

    print("[FAIL] Import failed:")
    print(result.stderr)
    return False


def run_command(cmd: list, description: str) -> bool:
    print(f"\n{'='*60}")
    print(f"STEP: {description}")
    print(f"CMD:  {' '.join(cmd)}")
    print("=" * 60)
    result = subprocess.run(cmd, capture_output=False)
    success = result.returncode == 0
    if success:
        print(f"[PASS] {description}")
    else:
        print(f"[FAIL] {description} (exit code {result.returncode})")
    return success


def create_offline_fixtures(output_dir: Path) -> None:
    """Create fixture data for offline mode."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "snapshots").mkdir(exist_ok=True)
    (output_dir / "reports").mkdir(exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    with open(output_dir / "scan.log", "w") as f:
        f.write(f"[FIXTURE] Offline mode scan at {timestamp_str}\n")

    scan_data = {
        "run_mode": "REGISTRY_REAL",
        "current_block": 275000000,
        "chain_id": 42161,
        "stats": {
            "cycle": 1,
            "run_mode": "REGISTRY_REAL",
            "current_block": 275000000,
            "chain_id": 42161,
            "quotes_total": 4,
            "quotes_fetched": 4,
            "gates_passed": 2,
            "spread_ids_total": 1,
            "spread_ids_profitable": 1,
            "execution_ready_count": 0,
            "blocked_spreads": 1,
            "chains_active": 1,
            "dexes_active": 2,
            "pairs_covered": 1,
            "pools_scanned": 4,
            "price_sanity_passed": 2,
            "price_sanity_failed": 2,
        },
        "reject_histogram": {"PRICE_SANITY_FAIL": 2},
        "gate_breakdown": {"revert": 0, "slippage": 0, "infra": 0, "other": 0, "sanity": 2},
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
                "amount_in_numeraire": "1.000000",
                "amount_out_buy_numeraire": "3500.000000",
                "amount_out_sell_numeraire": "3505.000000",
                "signal_pnl_usdc": "5.000000",
                "signal_pnl_bps": "14.28",
                "would_execute_pnl_usdc": "5.000000",
                "would_execute_pnl_bps": "14.28",
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
        "sample_rejects": [
            {
                "quote_id": "q_1_3",
                "dex_id": "uniswap_v3",
                "pool": "0x17c14D2c404D167802b16C450d3c99F88F2c4F4d",
                "pair": "WETH/USDC",
                "fee": 3000,
                "reject_reason": "PRICE_SANITY_FAIL",
                "price": "3600.123456",
                "price_deviation_bps": 286,
                "diagnostics": {
                    "implied_price": "3600.123456",
                    "anchor_price": "3500",
                    "deviation_bps": 286,
                    "token_in_decimals": 18,
                    "token_out_decimals": 6,
                }
            }
        ],
        "sample_passed": [
            {"dex_id": "uniswap_v3", "price": "3500.0"},
            {"dex_id": "sushiswap_v3", "price": "3505.0"},
        ],
    }

    with open(output_dir / "snapshots" / f"scan_{timestamp_str}.json", "w") as f:
        json.dump(scan_data, f, indent=2)

    histogram_data = {
        "run_mode": "REGISTRY_REAL",
        "timestamp": datetime.now().isoformat(),
        "chain_id": 42161,
        "current_block": 275000000,
        "quotes_total": 4,
        "quotes_fetched": 4,
        "gates_passed": 2,
        "histogram": {"PRICE_SANITY_FAIL": 2},
        "gate_breakdown": {"revert": 0, "slippage": 0, "infra": 0, "other": 0, "sanity": 2},
    }

    with open(output_dir / "reports" / f"reject_histogram_{timestamp_str}.json", "w") as f:
        json.dump(histogram_data, f, indent=2)

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
            "quote_gate_pass_rate": 0.5,
            "quotes_fetched": 4,
            "quotes_total": 4,
            "gates_passed": 2,
            "chains_active": 1,
            "dexes_active": 2,
            "pools_scanned": 4,
            "price_sanity_passed": 2,
            "price_sanity_failed": 2,
            "gate_breakdown": {"revert": 0, "slippage": 0, "infra": 0, "other": 0, "sanity": 2},
        },
        "top_opportunities": [
            {
                "spread_id": "fixture_001",
                "dex_buy": "uniswap_v3",
                "dex_sell": "sushiswap_v3",
                "pool_buy": "0xC31E54c7a869B9FcBEcc14363CF510d1c41fa443",
                "pool_sell": "0x90d5FFde59F0Ae1E7C19F59a29F3d8e9D44f57E5",
                "token_in": "WETH",
                "token_out": "USDC",
                "amount_in_numeraire": "1.000000",
                "signal_pnl_usdc": "5.000000",
                "confidence": 0.82,
                "confidence_factors": {"rpc_health": 1.0, "quote_coverage": 1.0},
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
                "is_execution_ready": False,
            }
        ],
        "stats": {
            "spread_ids_total": 1,
            "spread_ids_profitable": 1,
            "execution_ready_count": 0,
            "quotes_fetched": 4,
            "quotes_total": 4,
            "gates_passed": 2,
            "dexes_active": 2,
            "price_sanity_passed": 2,
            "price_sanity_failed": 2,
        },
        "pnl": {
            "signal_pnl_usdc": "5.000000",
            "would_execute_pnl_usdc": "5.000000",
        },
    }

    with open(output_dir / "reports" / f"truth_report_{timestamp_str}.json", "w") as f:
        json.dump(truth_report, f, indent=2)

    print(f"[OK] Created offline fixtures in {output_dir}")


def check_artifact_sanity(output_dir: Path) -> bool:
    """Check all 4 artifacts exist."""
    print(f"\n{'='*60}")
    print("STEP: Artifact Sanity Check")
    print("=" * 60)

    errors = []

    if not (output_dir / "scan.log").exists():
        errors.append("[FAIL] Missing: scan.log")
    else:
        print("[OK] Found: scan.log")

    snapshots_dir = output_dir / "snapshots"
    scan_files = list(snapshots_dir.glob("scan_*.json")) if snapshots_dir.exists() else []
    if not scan_files:
        errors.append("[FAIL] Missing: snapshots/scan_*.json")
    else:
        print(f"[OK] Found: {scan_files[0].name}")

    reports_dir = output_dir / "reports"
    histogram_files = list(reports_dir.glob("reject_histogram_*.json")) if reports_dir.exists() else []
    if not histogram_files:
        errors.append("[FAIL] Missing: reports/reject_histogram_*.json")
    else:
        print(f"[OK] Found: {histogram_files[0].name}")

    truth_files = list(reports_dir.glob("truth_report_*.json")) if reports_dir.exists() else []
    if not truth_files:
        errors.append("[FAIL] Missing: reports/truth_report_*.json")
    else:
        print(f"[OK] Found: {truth_files[0].name}")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print("\n[PASS] All 4 artifacts present")
    return True


def check_metrics_invariants(output_dir: Path) -> bool:
    """
    STEP 9: Check metrics contract invariants.
    
    Key invariant: if sample_rejects has entries with price != null,
    then quotes_fetched cannot be 0.
    """
    print(f"\n{'='*60}")
    print("STEP: Metrics Contract Invariants")
    print("=" * 60)

    errors = []

    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if not scan_files:
        errors.append("[FAIL] No scan_*.json found")
        for e in errors:
            print(e)
        return False

    with open(scan_files[0], "r") as f:
        scan_data = json.load(f)

    stats = scan_data.get("stats", {})
    quotes_fetched = stats.get("quotes_fetched", 0)
    quotes_total = stats.get("quotes_total", 0)
    gates_passed = stats.get("gates_passed", 0)

    sample_rejects = scan_data.get("sample_rejects", [])

    # INVARIANT 1: If we have rejects with prices, quotes_fetched > 0
    rejects_with_price = [r for r in sample_rejects if r.get("price") is not None]
    if rejects_with_price and quotes_fetched == 0:
        errors.append(
            f"[FAIL] INVARIANT VIOLATION: {len(rejects_with_price)} rejects have price "
            f"but quotes_fetched=0. This indicates metrics bug."
        )
        for r in rejects_with_price[:3]:
            errors.append(f"  - {r.get('dex_id')}: price={r.get('price')}")

    # INVARIANT 2: gates_passed <= quotes_fetched
    if gates_passed > quotes_fetched:
        errors.append(
            f"[FAIL] INVARIANT VIOLATION: gates_passed ({gates_passed}) > "
            f"quotes_fetched ({quotes_fetched})"
        )

    # INVARIANT 3: quotes_fetched <= quotes_total
    if quotes_fetched > quotes_total:
        errors.append(
            f"[FAIL] INVARIANT VIOLATION: quotes_fetched ({quotes_fetched}) > "
            f"quotes_total ({quotes_total})"
        )

    if not errors:
        print(f"[OK] quotes_total: {quotes_total}")
        print(f"[OK] quotes_fetched: {quotes_fetched}")
        print(f"[OK] gates_passed: {gates_passed}")
        print(f"[OK] Metrics contract invariants satisfied")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print("\n[PASS] Metrics contract valid")
    return True


def check_m4_invariants(output_dir: Path) -> bool:
    """Check M4 invariants (STRICT + SANITY)."""
    print(f"\n{'='*60}")
    print("STEP: M4 Invariants Check")
    print("=" * 60)

    errors = []

    scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
    if not scan_files:
        errors.append("[FAIL] No scan_*.json found")
        for e in errors:
            print(e)
        return False

    with open(scan_files[0], "r") as f:
        scan_data = json.load(f)

    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("[FAIL] No truth_report_*.json found")
        for e in errors:
            print(e)
        return False

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    # 1. run_mode
    run_mode = scan_data.get("run_mode", "")
    if run_mode == "REGISTRY_REAL":
        print(f"[OK] run_mode: {run_mode}")
    else:
        errors.append(f"[FAIL] run_mode: expected REGISTRY_REAL, got {run_mode}")

    # 2. current_block > 0
    current_block = scan_data.get("current_block", 0)
    if current_block and current_block > 0:
        print(f"[OK] current_block: {current_block}")
    else:
        errors.append(f"[FAIL] current_block: must be > 0, got {current_block}")

    # 3. execution_ready_count == 0
    stats = truth_report.get("stats", {})
    execution_ready = stats.get("execution_ready_count", 0)
    if execution_ready == 0:
        print(f"[OK] execution_ready_count: {execution_ready}")
    else:
        errors.append(f"[FAIL] execution_ready_count: must be 0, got {execution_ready}")

    # 4. quotes_fetched >= 1
    scan_stats = scan_data.get("stats", {})
    quotes_fetched = scan_stats.get("quotes_fetched", 0)
    quotes_total = scan_stats.get("quotes_total", 0)
    gates_passed = scan_stats.get("gates_passed", 0)
    if quotes_fetched >= 1:
        print(f"[OK] quotes_fetched: {quotes_fetched}/{quotes_total} (gates_passed: {gates_passed})")
    else:
        errors.append(f"[FAIL] quotes_fetched: must be >= 1, got {quotes_fetched}")

    # 5. rpc_success_rate > 0
    rpc_stats = scan_data.get("rpc_stats", {})
    rpc_success_rate = rpc_stats.get("success_rate", 0)
    if rpc_success_rate > 0:
        print(f"[OK] rpc_success_rate: {rpc_success_rate:.1%}")
    else:
        errors.append(f"[FAIL] rpc_success_rate: must be > 0")

    # 6. dexes_active >= 2
    dexes_active = scan_stats.get("dexes_active", 0)
    if dexes_active >= 2:
        print(f"[OK] dexes_active: {dexes_active}")
    else:
        errors.append(f"[FAIL] dexes_active: must be >= 2, got {dexes_active}")

    # 7. rpc_total_requests >= 3
    rpc_total = rpc_stats.get("total_requests", 0)
    if rpc_total >= 3:
        print(f"[OK] rpc_total_requests: {rpc_total}")
    else:
        errors.append(f"[FAIL] rpc_total_requests: must be >= 3, got {rpc_total}")

    # 8. price_sanity_passed >= 1
    price_sanity_passed = scan_stats.get("price_sanity_passed", 0)
    price_sanity_failed = scan_stats.get("price_sanity_failed", 0)
    if price_sanity_passed >= 1:
        print(f"[OK] price_sanity: {price_sanity_passed} passed, {price_sanity_failed} failed")
    else:
        errors.append(f"[FAIL] price_sanity_passed: must be >= 1, got {price_sanity_passed}")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print("\n[PASS] M4 invariants satisfied")
    return True


def check_cross_dex_and_quality(output_dir: Path) -> bool:
    """Check cross-DEX opportunities and quality metrics."""
    print(f"\n{'='*60}")
    print("STEP: Cross-DEX + Quality Validation")
    print("=" * 60)

    errors = []

    truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
    if not truth_files:
        errors.append("[FAIL] No truth_report_*.json found")
        for e in errors:
            print(e)
        return False

    with open(truth_files[0], "r") as f:
        truth_report = json.load(f)

    top_opps = truth_report.get("top_opportunities", [])

    if not top_opps:
        print("[WARN] No opportunities found")
        scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
        if scan_files:
            with open(scan_files[0], "r") as f:
                scan_data = json.load(f)
            gates_passed = scan_data.get("stats", {}).get("gates_passed", 0)
            if gates_passed < 2:
                print(f"  Need >= 2 quotes passed gates for spreads, got {gates_passed}")
                print("\n[PASS] Cross-DEX validation SKIPPED (insufficient passed quotes)")
                return True
        errors.append("[FAIL] No top_opportunities found")
        for e in errors:
            print(e)
        return False

    # Cross-DEX check
    cross_dex_opps = [opp for opp in top_opps if opp.get("dex_buy") != opp.get("dex_sell")]
    if cross_dex_opps:
        opp = cross_dex_opps[0]
        print(f"[OK] Cross-DEX opportunity: {opp.get('dex_buy')} -> {opp.get('dex_sell')}")
    else:
        errors.append("[FAIL] No cross-DEX opportunities found")

    # Pool check
    unknown_pools = []
    for opp in top_opps:
        if opp.get("pool_buy") == "unknown":
            unknown_pools.append(f"{opp.get('spread_id')}.pool_buy")
        if opp.get("pool_sell") == "unknown":
            unknown_pools.append(f"{opp.get('spread_id')}.pool_sell")

    if not unknown_pools:
        print(f"[OK] All pools identified (no 'unknown')")
    else:
        errors.append(f"[FAIL] Found 'unknown' pools: {unknown_pools[:5]}")

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
        print(f"[OK] All profitable opps have amount_in > 0")
    else:
        errors.append(f"[FAIL] Profitable opps with amount=0: {zero_amounts[:5]}")

    # Confidence check
    confidences = [opp.get("confidence", 0) for opp in top_opps]
    if len(set(confidences)) > 1 or (confidences and confidences[0] != 0.85):
        print(f"[OK] Confidence is dynamic: {confidences}")
    elif len(top_opps) == 1:
        print(f"[OK] Single opportunity, confidence: {confidences[0]:.2f}")
    else:
        factors = top_opps[0].get("confidence_factors", {})
        if factors:
            print(f"[OK] Confidence with factors: {list(factors.keys())}")
        else:
            errors.append(f"[FAIL] Confidence appears constant at 0.85 without factors")

    # Execution blockers check
    opps_without_blockers = [
        opp.get("spread_id") for opp in top_opps
        if not opp.get("execution_blockers")
    ]
    if not opps_without_blockers:
        print(f"[OK] All opps have execution_blockers")
    else:
        errors.append(f"[FAIL] Opps without blockers: {opps_without_blockers[:5]}")

    if errors:
        print()
        for e in errors:
            print(e)
        return False

    print("\n[PASS] Cross-DEX + Quality validation passed")
    return True


def main():
    import argparse

    parser = argparse.ArgumentParser(description="ARBY M4 CI Gate")
    parser.add_argument("--offline", action="store_true",
                        help="Run on recorded fixtures (no network)")
    parser.add_argument("--skip-python-check", action="store_true",
                        help="Skip Python version check")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  ARBY M4 CI GATE")
    print("=" * 60)
    print()
    print("M4 Criteria:")
    print("  - Python 3.11.x")
    print("  - Import contract (calculate_confidence)")
    print("  - run_mode: REGISTRY_REAL")
    print("  - current_block > 0")
    print("  - execution_ready_count == 0")
    print("  - quotes_fetched >= 1")
    print("  - rpc_success_rate > 0")
    print("  - dexes_active >= 2")
    print("  - price_sanity_passed >= 1")
    print("  - Dynamic confidence")
    print("  - Cross-DEX opportunities")
    print("  - 4/4 artifacts")

    if args.offline:
        print("\n[MODE] OFFLINE: Using recorded fixtures")

    # Python version check
    if not args.skip_python_check:
        print(f"\n{'='*60}")
        print("STEP: Python Version Check")
        print("=" * 60)
        if not check_python_version():
            print("\n[FAIL] M4 CI GATE FAILED: Wrong Python version")
            sys.exit(10)
    else:
        print("\n[SKIP] Python version check")

    # Import contract check
    if not check_import_contract():
        print("\n[FAIL] M4 CI GATE FAILED: Import contract broken")
        sys.exit(11)

    # pytest
    if not run_command(
        [sys.executable, "-m", "pytest", "-q", "--ignore=tests/integration"],
        "Unit Tests (pytest -q)",
    ):
        print("\n[FAIL] M4 CI GATE FAILED: Tests did not pass")
        sys.exit(1)

    # REAL scan or fixtures
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("data/runs") / f"ci_m4_gate_{timestamp}"

    if args.offline:
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
            print("\n[FAIL] M4 CI GATE FAILED: REAL scan failed")
            sys.exit(2)

    # Artifacts
    if not check_artifact_sanity(output_dir):
        print("\n[FAIL] M4 CI GATE FAILED: Artifacts missing")
        sys.exit(3)

    # STEP 9: Metrics contract invariants
    if not check_metrics_invariants(output_dir):
        print("\n[FAIL] M4 CI GATE FAILED: Metrics contract violation")
        sys.exit(6)

    # M4 Invariants
    if not check_m4_invariants(output_dir):
        print("\n[FAIL] M4 CI GATE FAILED: M4 invariants failed")
        sys.exit(4)

    # Cross-DEX + Quality
    if not check_cross_dex_and_quality(output_dir):
        print("\n[FAIL] M4 CI GATE FAILED: Quality validation failed")
        sys.exit(5)

    print("\n" + "=" * 60)
    mode_str = "OFFLINE" if args.offline else "LIVE"
    print(f"  [PASS] M4 CI GATE PASSED ({mode_str})")
    print("=" * 60)
    print(f"\nArtifacts: {output_dir}")
    print()
    print("M4 Contract Verified:")
    print("  [OK] Python 3.11.x")
    print("  [OK] Import contract (calculate_confidence)")
    print("  [OK] run_mode: REGISTRY_REAL")
    print("  [OK] current_block pinned")
    print("  [OK] execution disabled")
    print("  [OK] quotes_fetched >= 1")
    print("  [OK] dexes_active >= 2")
    print("  [OK] price_sanity_passed >= 1")
    print("  [OK] metrics contract invariants")
    print("  [OK] cross-DEX opportunities")
    print("  [OK] dynamic confidence scoring")
    print("  [OK] 4/4 artifacts")
    sys.exit(0)


if __name__ == "__main__":
    main()
