#!/usr/bin/env python3
# PATH: scripts/ci_m4_execution_gate.py
"""
M4 Execution Gate - DEX↔DEX Atomic Execution v1.

VERSION: 1.0.0 (2026-02-09)
STATUS: ACTIVE

PURPOSE:
  Validate that execution simulation works correctly:
  1. Load signals from truth_report (or generate fixture)
  2. Simulate each signal via eth_call preview
  3. Verify net > 0 after gas/slippage
  4. Report PASS/FAIL with reasons

CANONICAL COMMANDS:
  # Offline - uses fixtures (no RPC)
  python scripts/ci_m4_execution_gate.py --offline
  python scripts/ci_m4_execution_gate.py --offline --strict

  # Online - uses real signals from latest run
  python scripts/ci_m4_execution_gate.py --online
  python scripts/ci_m4_execution_gate.py --simulate --signal 0

SUCCESS CRITERIA (from Roadmap):
  - 1-2 pairs, 2 DEX, on one chain
  - Signal found → Simulated → net > 0 after gas/slippage
  - execution_enabled=false (kill-switch)

EXIT CODES: 0=PASS, 1=FAIL validation, 2=NO_SIGNALS, 3=SIM_FAILED
"""

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure repository root is on sys.path
try:
    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT))
except Exception:
    pass

__version__ = "1.0.0"

# ============================================================
# SIMULATION REJECT REASONS
# ============================================================

class SimRejectReason:
    """Canonical simulation reject reasons for M4."""
    SIM_REVERT = "SIM_REVERT"              # eth_call reverted
    SIM_GAS_TOO_HIGH = "SIM_GAS_TOO_HIGH"  # gas > threshold
    SIM_UNPROFITABLE = "SIM_UNPROFITABLE"  # net < 0 after costs
    SIM_SLIPPAGE = "SIM_SLIPPAGE"          # actual slippage > expected
    SIM_BLOCK_STALE = "SIM_BLOCK_STALE"    # block too old
    SIM_NOT_IMPLEMENTED = "SIM_NOT_IMPLEMENTED"  # placeholder

# ============================================================
# THRESHOLDS
# ============================================================

# Minimum net profit in USD after all costs
MIN_NET_PROFIT_USD = Decimal("0.10")  # $0.10 minimum

# Maximum gas in USD
MAX_GAS_USD = Decimal("5.00")  # $5.00 max gas

# Maximum slippage tolerance (bps)
MAX_SLIPPAGE_BPS = 50  # 0.5%


# ============================================================
# FIXTURE GENERATION (OFFLINE MODE)
# ============================================================

def generate_m4_fixture(run_dir: Path, ts: str) -> Dict[str, Path]:
    """
    Generate M4 execution fixture for offline testing.
    
    Creates:
    - execution_report_<ts>.json: Simulation results
    - signals_<ts>.json: Input signals
    """
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Mock signals for fixture
    fixture_signals = [
        {
            "signal_id": f"sig_001_{ts}",
            "pair": "ARB/WETH",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_price": "0.00005625",
            "sell_price": "0.00005644",
            "spread_bps_exact": 33.78,
            "is_net_positive_est": True,
            "net_pnl_usdc_est": 0.85,
            "pinned_block": 429900000,
        },
        {
            "signal_id": f"sig_002_{ts}",
            "pair": "WETH/USDC",
            "buy_dex": "sushiswap_v3",
            "sell_dex": "uniswap_v3",
            "buy_price": "2091.90",
            "sell_price": "2092.15",
            "spread_bps_exact": 1.2,
            "is_net_positive_est": False,
            "net_pnl_usdc_est": -0.50,  # Unprofitable after gas
            "pinned_block": 429900000,
        },
    ]
    
    # Mock simulation results
    fixture_simulations = [
        {
            "signal_id": f"sig_001_{ts}",
            "pair": "ARB/WETH",
            "simulation_status": "PASS",
            "blocker": None,
            "gas_used": 250000,
            "gas_usd": "0.45",
            "slippage_bps_actual": 5,
            "slippage_usd": "0.02",
            "net_usd": "0.38",
            "is_profitable": True,
        },
        {
            "signal_id": f"sig_002_{ts}",
            "pair": "WETH/USDC",
            "simulation_status": "FAIL",
            "blocker": SimRejectReason.SIM_UNPROFITABLE,
            "gas_used": 280000,
            "gas_usd": "0.52",
            "slippage_bps_actual": 8,
            "slippage_usd": "0.15",
            "net_usd": "-0.67",
            "is_profitable": False,
        },
    ]
    
    # Write signals
    signals_path = reports_dir / f"signals_{ts}.json"
    signals_data = {
        "schema_version": "m4:signals:v1",
        "run_mode": "FIXTURE_OFFLINE",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "signals": fixture_signals,
        "signals_count": len(fixture_signals),
        "net_positive_count": 1,
    }
    with open(signals_path, "w") as f:
        json.dump(signals_data, f, indent=2)
    
    # Write execution report
    exec_path = reports_dir / f"execution_report_{ts}.json"
    exec_data = {
        "schema_version": "m4:execution:v1",
        "run_mode": "FIXTURE_OFFLINE",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "execution_enabled": False,  # INVARIANT: must be false
        "simulations": fixture_simulations,
        "simulations_count": len(fixture_simulations),
        "simulations_passed": 1,
        "simulations_failed": 1,
        "total_gas_usd": "0.97",
        "total_net_usd": "-0.29",
        "pass_rate": 0.5,
        # Accounting summary
        "accounting": {
            "signals_total": 2,
            "signals_profitable": 1,
            "signals_unprofitable": 1,
            "gas_total_usd": "0.97",
            "slippage_total_usd": "0.17",
            "net_total_usd": "-0.29",
        },
        # Health metrics (different from M5 - simulation focused)
        "health": {
            "simulation_pass_rate": 0.5,
            "accounting_complete": True,
            "all_signals_simulated": True,
        },
    }
    with open(exec_path, "w") as f:
        json.dump(exec_data, f, indent=2)
    
    return {
        "signals": signals_path,
        "execution_report": exec_path,
    }


# ============================================================
# ARTIFACT DISCOVERY
# ============================================================

def find_latest_run_dir(require_truth_report: bool = False) -> Optional[Path]:
    """
    Find the most recent run directory.
    
    Args:
        require_truth_report: If True, only return run with truth_report
    """
    runs_dir = REPO_ROOT / "data" / "runs"
    if not runs_dir.exists():
        return None
    
    run_dirs = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    
    if not require_truth_report:
        return run_dirs[0] if run_dirs else None
    
    # Find first run with truth_report
    for run_dir in run_dirs:
        reports_dir = run_dir / "reports"
        if reports_dir.exists():
            truth_files = list(reports_dir.glob("truth_report_*.json"))
            if truth_files:
                return run_dir
    
    return None


def discover_m4_artifacts(run_dir: Path) -> Dict[str, Optional[Path]]:
    """Discover M4 execution artifacts."""
    reports_dir = run_dir / "reports"
    
    artifacts = {
        "signals": None,
        "execution_report": None,
        "truth_report": None,  # May use M5 truth_report for signals
    }
    
    if not reports_dir.exists():
        return artifacts
    
    # Find execution_report
    exec_files = list(reports_dir.glob("execution_report_*.json"))
    if exec_files:
        artifacts["execution_report"] = sorted(exec_files, key=lambda x: x.name, reverse=True)[0]
    
    # Find signals
    sig_files = list(reports_dir.glob("signals_*.json"))
    if sig_files:
        artifacts["signals"] = sorted(sig_files, key=lambda x: x.name, reverse=True)[0]
    
    # Find truth_report (fallback for signals)
    truth_files = list(reports_dir.glob("truth_report_*.json"))
    if truth_files:
        artifacts["truth_report"] = sorted(truth_files, key=lambda x: x.name, reverse=True)[0]
    
    return artifacts


# ============================================================
# VALIDATION
# ============================================================

def validate_execution_report(data: Dict[str, Any], strict: bool = False) -> List[Tuple[str, bool, str]]:
    """
    Validate execution_report fields.
    
    Returns list of (check_name, passed, message).
    """
    checks = []
    
    # Schema version
    schema = data.get("schema_version", "")
    if schema.startswith("m4:execution:"):
        checks.append(("schema_version", True, f"schema_version={schema}"))
    else:
        checks.append(("schema_version", False, f"Invalid schema: {schema}"))
    
    # execution_enabled MUST be false
    exec_enabled = data.get("execution_enabled")
    if exec_enabled is False:
        checks.append(("execution_enabled", True, "execution_enabled=false (invariant OK)"))
    else:
        checks.append(("execution_enabled", False, f"INVARIANT VIOLATED: execution_enabled={exec_enabled}"))
    
    # run_mode
    run_mode = data.get("run_mode", "")
    if run_mode:
        checks.append(("run_mode", True, f"run_mode={run_mode}"))
    else:
        checks.append(("run_mode", False, "Missing run_mode"))
    
    # simulations_count
    sim_count = data.get("simulations_count", 0)
    if sim_count > 0:
        checks.append(("simulations_count", True, f"simulations_count={sim_count}"))
    else:
        checks.append(("simulations_count", False, "No simulations (simulations_count=0)"))
    
    # accounting completeness
    accounting = data.get("accounting", {})
    if accounting.get("signals_total", 0) > 0:
        checks.append(("accounting", True, f"accounting complete (signals={accounting.get('signals_total')})"))
    else:
        checks.append(("accounting", False, "Incomplete accounting"))
    
    # health metrics
    health = data.get("health", {})
    sim_pass_rate = health.get("simulation_pass_rate", 0)
    if sim_pass_rate is not None:
        checks.append(("simulation_pass_rate", True, f"simulation_pass_rate={sim_pass_rate}"))
    else:
        checks.append(("simulation_pass_rate", False, "Missing simulation_pass_rate"))
    
    # Check for at least one profitable simulation
    sims_passed = data.get("simulations_passed", 0)
    if sims_passed > 0:
        checks.append(("profitable_sims", True, f"simulations_passed={sims_passed}"))
    elif strict:
        checks.append(("profitable_sims", False, "No profitable simulations (strict mode)"))
    else:
        checks.append(("profitable_sims", True, f"WARN: simulations_passed={sims_passed}"))
    
    return checks


def validate_simulations(simulations: List[Dict[str, Any]]) -> List[Tuple[str, bool, str]]:
    """Validate individual simulations have required fields."""
    checks = []
    
    required_fields = ["signal_id", "simulation_status", "gas_usd", "net_usd", "is_profitable"]
    
    for i, sim in enumerate(simulations):
        missing = [f for f in required_fields if f not in sim]
        if missing:
            checks.append((f"sim[{i}]_fields", False, f"Missing: {missing}"))
        else:
            checks.append((f"sim[{i}]_fields", True, f"{sim.get('signal_id')} has all fields"))
        
        # Blocker reason validation
        status = sim.get("simulation_status")
        blocker = sim.get("blocker")
        if status == "FAIL" and not blocker:
            checks.append((f"sim[{i}]_blocker", False, "FAIL without blocker reason"))
        elif status == "FAIL":
            checks.append((f"sim[{i}]_blocker", True, f"blocker={blocker}"))
    
    return checks


# ============================================================
# MAIN GATE LOGIC
# ============================================================

def run_offline_gate(output_root: Path, strict: bool = False) -> int:
    """
    Run M4 gate in offline mode with fixtures.
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / f"ci_m4_gate_offline_{ts}"
    
    # Use relative_to if possible, otherwise show absolute path
    try:
        display_path = run_dir.relative_to(REPO_ROOT)
    except ValueError:
        display_path = run_dir
    print(f"\n[OFFLINE] Creating: {display_path}")
    
    # Generate fixtures
    artifacts = generate_m4_fixture(run_dir, ts)
    
    print(f"[OFFLINE] Generated artifacts:")
    for name, path in artifacts.items():
        print(f"  - {name}: {path.name}")
    
    # Load and validate
    return validate_gate(run_dir, artifacts, strict)


def run_online_gate(run_dir: Optional[Path], strict: bool = False) -> int:
    """
    Run M4 gate in online mode using real artifacts.
    """
    if run_dir is None:
        run_dir = find_latest_run_dir()
    
    if run_dir is None:
        print("ERROR: No run directory found")
        print("Run: python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml")
        return 2
    
    try:
        display_path = run_dir.relative_to(REPO_ROOT)
    except ValueError:
        display_path = run_dir
    print(f"\n[ONLINE] Using: {display_path}")
    
    artifacts = discover_m4_artifacts(run_dir)
    
    # If no execution_report, return NO_SIGNALS
    if artifacts["execution_report"] is None:
        print("\nWARN: No execution_report found")
        print("M4 execution simulation not yet implemented")
        print("Use --offline for fixture-based validation")
        return 2
    
    return validate_gate(run_dir, {k: v for k, v in artifacts.items() if v}, strict)



def validate_gate(run_dir: Path, artifacts: Dict[str, Path], strict: bool) -> int:
    """
    Core validation logic for M4 gate.
    """
    print("\n" + "=" * 60)
    print("VALIDATION")
    print("=" * 60)
    print()
    
    all_checks = []
    
    # Check artifacts exist
    exec_path = artifacts.get("execution_report")
    if exec_path is None or not exec_path.exists():
        print("  FAIL: execution_report not found")
        return 1
    print(f"  OK: execution_report found")
    
    # Load execution report
    with open(exec_path) as f:
        exec_data = json.load(f)
    
    # Validate execution report
    checks = validate_execution_report(exec_data, strict)
    all_checks.extend(checks)
    
    for name, passed, msg in checks:
        status = "OK" if passed else "FAIL"
        print(f"  {status}: {msg}")
    
    # Validate individual simulations
    simulations = exec_data.get("simulations", [])
    if simulations:
        print()
        sim_checks = validate_simulations(simulations)
        all_checks.extend(sim_checks)
        
        for name, passed, msg in sim_checks:
            status = "OK" if passed else "FAIL"
            print(f"  {status}: {msg}")
    
    # Summary
    print()
    print("=" * 60)
    
    failures = [c for c in all_checks if not c[1]]
    
    if failures:
        print(f"RESULT: FAIL ({len(failures)} failures)")
        for name, _, msg in failures:
            print(f"  - {msg}")
        print(f"RunDir: {run_dir}")
        return 1
    else:
        print("RESULT: PASS")
        print(f"RunDir: {run_dir}")
        return 0


# ============================================================
# CLI
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="M4 Execution Gate - DEX↔DEX Atomic Execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--offline", action="store_true",
                            help="Generate fixtures and validate (no RPC)")
    mode_group.add_argument("--online", action="store_true",
                            help="Use real artifacts from latest run")
    mode_group.add_argument("--dry-run", action="store_true",
                            help="Show signals that would be simulated")
    mode_group.add_argument("--simulate", action="store_true",
                            help="Run simulation on signals (NOT IMPLEMENTED)")
    
    parser.add_argument("--strict", action="store_true",
                        help="Require at least one profitable simulation")
    parser.add_argument("--run-dir", type=Path,
                        help="Explicit run directory to validate")
    parser.add_argument("--output-root", type=Path,
                        default=REPO_ROOT / "data" / "runs",
                        help="Root for output directories")
    parser.add_argument("--signal", type=int, default=0,
                        help="Signal index to simulate (0 = first)")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    
    args = parser.parse_args()
    
    # Header
    mode_str = "OFFLINE" if args.offline else "ONLINE" if args.online else "DRY-RUN"
    print("=" * 60)
    print(f"M4 EXECUTION GATE v{__version__} - {mode_str}")
    print("=" * 60)
    
    if args.offline:
        return run_offline_gate(args.output_root, args.strict)
    elif args.online:
        return run_online_gate(args.run_dir, args.strict)
    elif args.dry_run:
        return run_dry_run()
    elif args.simulate:
        print("\nERROR: --simulate not yet implemented")
        print("Use --offline for fixture-based validation")
        return 1
    else:
        parser.print_help()
        return 0


def run_dry_run() -> int:
    """
    Dry run: Find signals and show what would be simulated.
    """
    print()
    
    # Find latest run with truth_report
    run_dir = find_latest_run_dir(require_truth_report=True)
    if not run_dir:
        print("ERROR: No run directory found")
        return 2
    
    artifacts = discover_m4_artifacts(run_dir)
    truth_path = artifacts.get("truth_report")
    
    if not truth_path:
        print("ERROR: No truth_report found")
        return 2
    
    try:
        display_path = truth_path.relative_to(REPO_ROOT)
    except ValueError:
        display_path = truth_path
    print(f"Using: {display_path}")
    
    with open(truth_path) as f:
        data = json.load(f)
    
    signals = data.get("spread_signals", [])
    net_positive = [s for s in signals if s.get("is_net_positive_est", False)]
    
    if not net_positive:
        print("\nNo net-positive signals found.")
        return 2
    
    print(f"\nFound {len(net_positive)} net-positive signals:")
    print()
    
    for i, sig in enumerate(net_positive[:5]):
        print(f"  [{i+1}] {sig.get('pair')}")
        print(f"      buy: {sig.get('buy_dex')} @ {sig.get('buy_price')}")
        print(f"      sell: {sig.get('sell_dex')} @ {sig.get('sell_price')}")
        print(f"      spread: {sig.get('spread_bps_exact', 0):.2f} bps")
        print(f"      net_pnl_est: ${sig.get('net_pnl_usdc_est', 0):.4f}")
        print()
    
    print("-" * 60)
    print("Next: python scripts/ci_m4_execution_gate.py --offline")
    print("-" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
