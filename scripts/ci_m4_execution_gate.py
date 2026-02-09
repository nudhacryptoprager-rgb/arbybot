#!/usr/bin/env python3
# PATH: scripts/ci_m4_execution_gate.py
"""
M4 Execution Gate - DEX↔DEX Atomic Execution v1.

VERSION: 1.1.0 (2026-02-09)
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
  python scripts/ci_m4_execution_gate.py --offline --profile profit

  # Online - uses real signals from latest run
  python scripts/ci_m4_execution_gate.py --online
  python scripts/ci_m4_execution_gate.py --online --profile profit

DOD PROFILES:
  smoke (default): PASS if simulations_passed >= 1 AND accounting_complete
  profit: PASS if total_net_usd > 0 AND signals_profitable >= 1

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

# Import canonical reject reasons
from core.reject_reasons import SimRejectReason

__version__ = "1.1.0"

# ============================================================
# DOD PROFILES
# ============================================================

class DoDProfile:
    """Definition of Done profiles for M4 gate."""
    SMOKE = "smoke"    # PASS if >=1 profitable sim + accounting complete
    PROFIT = "profit"  # PASS if total_net_usd > 0

# ============================================================
# THRESHOLDS
# ============================================================

# Minimum net profit in USD after all costs
MIN_NET_PROFIT_USD = Decimal("0.10")  # $0.10 minimum

# Maximum gas in USD
MAX_GAS_USD = Decimal("5.00")  # $5.00 max gas

# Maximum slippage tolerance (bps)
MAX_SLIPPAGE_BPS = 50  # 0.5%

# Default chain for fixtures
DEFAULT_CHAIN_ID = 42161  # Arbitrum One

# Default pinned block for fixtures
DEFAULT_PINNED_BLOCK = 429900000


# ============================================================
# FIXTURE GENERATION (OFFLINE MODE)
# ============================================================

def generate_m4_fixture(run_dir: Path, ts: str) -> Dict[str, Path]:
    """
    Generate M4 execution fixture for offline testing.
    
    Creates:
    - execution_report_<ts>.json: Simulation results
    - signals_<ts>.json: Input signals
    
    Fixture uses numerical USD values (not strings) for proper validation.
    All prices are strings (decimal format) for consistency.
    spread_bps is integer micro-bps (1 bps = 10000 micro-bps).
    """
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    pinned_block = DEFAULT_PINNED_BLOCK
    chain_id = DEFAULT_CHAIN_ID
    
    # Mock signals for fixture - all with same pinned_block
    # Prices are ALWAYS string decimal, format: "quote_per_base"
    # spread_bps_micro is integer (1 bps = 10000 micro-bps)
    fixture_signals = [
        {
            "signal_id": f"sig_001_{ts}",
            "pair": "ARB/WETH",
            "base_token": "ARB",
            "quote_token": "WETH",
            "price_in": "quote_per_base",  # price = how much WETH per 1 ARB
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_price": "0.00005625",     # Always string decimal
            "sell_price": "0.00005644",    # Always string decimal
            "spread_bps_micro": 337800,    # 33.78 bps = 337800 micro-bps (integer)
            "size_usd_est": 100.0,         # Trade size in USD
            "gross_pnl_usdc_est": 1.30,    # Before costs
            "gas_usdc_est": 0.45,          # Estimated gas
            "slippage_usdc_est": 0.02,     # Estimated slippage
            "net_pnl_usdc_est": 0.83,      # net = gross - gas - slippage
            "is_net_positive_est": True,
            "confidence": 0.85,            # Signal confidence [0,1]
            "liquidity_hint": "adequate",  # "thin", "adequate", "deep"
            "pinned_block": pinned_block,
        },
        {
            "signal_id": f"sig_002_{ts}",
            "pair": "WETH/USDC",
            "base_token": "WETH",
            "quote_token": "USDC",
            "price_in": "quote_per_base",  # price = how much USDC per 1 WETH
            "buy_dex": "sushiswap_v3",
            "sell_dex": "uniswap_v3",
            "buy_price": "2091.90",        # Always string decimal
            "sell_price": "2092.15",       # Always string decimal
            "spread_bps_micro": 12000,     # 1.2 bps = 12000 micro-bps (integer)
            "size_usd_est": 100.0,
            "gross_pnl_usdc_est": 0.12,
            "gas_usdc_est": 0.52,
            "slippage_usdc_est": 0.15,
            "net_pnl_usdc_est": -0.55,
            "is_net_positive_est": False,
            "confidence": 0.60,
            "liquidity_hint": "adequate",
            "pinned_block": pinned_block,
        },
    ]
    
    # Mock simulation results - all monetary values in USDC
    # All USDC fields are numbers, rounded to avoid float artifacts
    # slippage_bps_actual is real bps (0-10000), NOT micro-bps
    # est_error_usdc = sim_net_usdc - est_net_usdc (negative = sim worse than estimate)
    fixture_simulations = [
        {
            "signal_id": f"sig_001_{ts}",
            "pair": "ARB/WETH",
            "base_token": "ARB",
            "quote_token": "WETH",
            "price_in": "quote_per_base",  # From signal
            "buy_dex": "uniswap_v3",       # Route from signal
            "sell_dex": "sushiswap_v3",    # Route from signal
            "simulation_status": "PASS",
            "blocker": None,
            "block_used": pinned_block,
            "confidence": 0.85,            # From signal
            "liquidity_hint": "adequate",  # From signal
            "size_usdc_simulated": 100.0,  # Actual size used in simulation
            "gas_used": 250000,
            "gas_usdc": 0.45,
            "slippage_bps_actual": 5,      # Real bps (0-10000), 5 bps = 0.05%
            "slippage_usdc": 0.02,
            "gross_pnl_usdc": 0.85,
            "net_usdc": 0.38,
            "is_profitable": True,
            # Expanded est_vs_sim (all USDC)
            "est_net_usdc": 0.83,          # From signal.net_pnl_usdc_est
            "est_was_positive": True,
            "sim_was_positive": True,
            "est_sign_correct": True,      # est_was_positive == sim_was_positive
            "est_error_usdc": -0.45,       # sim_net - est_net (negative = sim worse)
        },
        {
            "signal_id": f"sig_002_{ts}",
            "pair": "WETH/USDC",
            "base_token": "WETH",
            "quote_token": "USDC",
            "price_in": "quote_per_base",
            "buy_dex": "sushiswap_v3",
            "sell_dex": "uniswap_v3",
            "simulation_status": "FAIL",
            "blocker": SimRejectReason.SIM_UNPROFITABLE.value,
            "block_used": pinned_block,
            "confidence": 0.60,
            "liquidity_hint": "adequate",
            "size_usdc_simulated": 100.0,
            "gas_used": 280000,
            "gas_usdc": 0.52,
            "slippage_bps_actual": 8,      # Real bps, 8 bps = 0.08%
            "slippage_usdc": 0.15,
            "gross_pnl_usdc": 0.00,
            "net_usdc": -0.67,
            "is_profitable": False,
            # Expanded est_vs_sim
            "est_net_usdc": -0.55,
            "est_was_positive": False,
            "sim_was_positive": False,
            "est_sign_correct": True,
            "est_error_usdc": -0.12,       # sim worse than estimate
        },
    ]
    
    # Compute aggregates by pair and route
    signals_by_pair: Dict[str, int] = {}
    signals_by_route: Dict[str, int] = {}
    for sig in fixture_signals:
        pair = sig.get("pair", "UNKNOWN")
        signals_by_pair[pair] = signals_by_pair.get(pair, 0) + 1
        route = f"{sig.get('buy_dex', '?')}->{sig.get('sell_dex', '?')}"
        signals_by_route[route] = signals_by_route.get(route, 0) + 1
    
    # Compute est vs sim metrics
    est_profitable_count = sum(1 for s in fixture_signals if s.get("is_net_positive_est"))
    sim_profitable_count = sum(1 for s in fixture_simulations if s.get("is_profitable"))
    est_sim_mismatch_count = sum(
        1 for sig, sim in zip(fixture_signals, fixture_simulations)
        if sig.get("is_net_positive_est") != sim.get("is_profitable")
    )
    
    # Write signals with v1.1 schema
    signals_path = reports_dir / f"signals_{ts}.json"
    signals_data = {
        "schema_version": "m4:signals:v1.1",
        "run_mode": "FIXTURE_OFFLINE",
        "quote_ccy": "USDC",              # All monetary values in USDC
        "price_format": "decimal_str",    # All prices are string decimals
        "spread_format": "micro_bps",     # spread_bps_micro is integer (1 bps = 10000)
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "chain_id": chain_id,
        "pinned_block": pinned_block,
        "signals": fixture_signals,
        "signals_count": len(fixture_signals),
        "net_positive_count": est_profitable_count,
        "signals_by_pair": signals_by_pair,
        "signals_by_route": signals_by_route,
    }
    with open(signals_path, "w") as f:
        json.dump(signals_data, f, indent=2)
    
    # Compute totals (numerical) - ROUND to avoid float artifacts
    # All monetary values are in USDC
    total_gas_usdc = round(sum(s.get("gas_usdc", 0) for s in fixture_simulations), 4)
    total_slippage_usdc = round(sum(s.get("slippage_usdc", 0) for s in fixture_simulations), 4)
    total_net_usdc = round(sum(s.get("net_usdc", 0) for s in fixture_simulations), 4)
    
    # Compute expanded est_vs_sim metrics
    est_net_sum = round(sum(s.get("est_net_usdc", 0) for s in fixture_simulations), 4)
    sim_net_sum = total_net_usdc
    est_sign_correct_count = sum(1 for s in fixture_simulations if s.get("est_sign_correct", False))
    mae_net_usdc = round(sum(abs(s.get("est_error_usdc", 0)) for s in fixture_simulations) / len(fixture_simulations), 4) if fixture_simulations else 0
    
    # Write execution report
    exec_path = reports_dir / f"execution_report_{ts}.json"
    exec_data = {
        "schema_version": "m4:execution:v1.1",
        "run_mode": "FIXTURE_OFFLINE",
        "execution_mode": "simulate_only",  # INVARIANT: no real execution
        "quote_ccy": "USDC",                # All monetary values in USDC
        "price_format": "decimal_str",      # From signals schema
        "price_in": "quote_per_base",       # From signals schema  
        "slippage_format": "bps",           # slippage_bps_actual is real bps (0-10000)
        "est_error_definition": "sim_net_usdc - est_net_usdc",  # Negative = sim worse
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "chain_id": chain_id,
        "pinned_block": pinned_block,
        "execution_enabled": False,         # INVARIANT: must be false in M4
        "kill_switch_active": True,         # INVARIANT: no real execution allowed
        "simulations": fixture_simulations,
        "simulations_count": len(fixture_simulations),
        "simulations_passed": sim_profitable_count,
        "simulations_failed": len(fixture_simulations) - sim_profitable_count,
        "total_gas_usdc": total_gas_usdc,
        "total_net_usdc": total_net_usdc,
        "pass_rate": round(sim_profitable_count / len(fixture_simulations), 4) if fixture_simulations else 0,
        # Expanded Estimate vs Simulation metrics
        "est_vs_sim": {
            "est_profitable_count": est_profitable_count,
            "sim_profitable_count": sim_profitable_count,
            "est_sim_mismatch_count": est_sim_mismatch_count,
            "est_net_usdc_sum": est_net_sum,
            "sim_net_usdc_sum": sim_net_sum,
            "est_sign_correct_count": est_sign_correct_count,
            "est_sign_correct_rate": round(est_sign_correct_count / len(fixture_simulations), 4) if fixture_simulations else 0,
            "mae_net_usdc": mae_net_usdc,  # Mean Absolute Error
        },
        # Accounting summary (all numbers, rounded, in USDC)
        "accounting": {
            "signals_total": len(fixture_signals),
            "signals_profitable": sim_profitable_count,
            "signals_unprofitable": len(fixture_simulations) - sim_profitable_count,
            "gas_total_usdc": total_gas_usdc,
            "slippage_total_usdc": total_slippage_usdc,
            "net_total_usdc": total_net_usdc,
            "accounting_complete": True,
        },
        # Health metrics (includes execution safety invariants)
        "health": {
            "simulation_pass_rate": round(sim_profitable_count / len(fixture_simulations), 4) if fixture_simulations else 0,
            "blocks_consistent": True,  # All sims used same pinned_block
            "all_signals_simulated": True,
            # Execution safety invariants (strict: must be checked in gate)
            "execution_enabled": False,      # INVARIANT: must be false in M4
            "kill_switch_active": True,      # INVARIANT: must be true in M4
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

def validate_execution_report(
    data: Dict[str, Any], 
    profile: str = DoDProfile.SMOKE,
    strict: bool = False,
) -> List[Tuple[str, bool, str]]:
    """
    Validate execution_report fields.
    
    Args:
        data: Execution report data
        profile: DoD profile - "smoke" or "profit"
        strict: Require at least one profitable simulation
    
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
    
    # kill_switch_active MUST be true (M4 DoD - STRICT)
    kill_switch = data.get("kill_switch_active")
    if kill_switch is True:
        checks.append(("kill_switch", True, "kill_switch_active=true (no real execution)"))
    elif kill_switch is None:
        # STRICT: missing is a FAIL in M4 - must be explicitly true
        checks.append(("kill_switch", False, "MISSING: kill_switch_active must be true in M4"))
    else:
        checks.append(("kill_switch", False, f"DANGER: kill_switch_active={kill_switch}"))
    
    # run_mode
    run_mode = data.get("run_mode", "")
    if run_mode:
        checks.append(("run_mode", True, f"run_mode={run_mode}"))
    else:
        checks.append(("run_mode", False, "Missing run_mode"))
    
    # pinned_block and chain_id (new in v1.1)
    pinned_block = data.get("pinned_block")
    chain_id = data.get("chain_id")
    if pinned_block:
        checks.append(("pinned_block", True, f"pinned_block={pinned_block}"))
    else:
        checks.append(("pinned_block", False, "Missing pinned_block in header"))
    
    if chain_id:
        checks.append(("chain_id", True, f"chain_id={chain_id}"))
    else:
        checks.append(("chain_id", False, "Missing chain_id in header"))
    
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
    sim_pass_rate = health.get("simulation_pass_rate")
    if sim_pass_rate is not None:
        checks.append(("simulation_pass_rate", True, f"simulation_pass_rate={sim_pass_rate:.2%}"))
    else:
        checks.append(("simulation_pass_rate", False, "Missing simulation_pass_rate"))
    
    # Block consistency check
    blocks_consistent = health.get("blocks_consistent")  # None if not present
    if blocks_consistent is True:
        checks.append(("blocks_consistent", True, "All simulations used same pinned_block"))
    elif blocks_consistent is False:
        # Explicitly false - fail
        checks.append(("blocks_consistent", False, "blocks_consistent=false in health"))
    elif data.get("simulations"):
        # Not present but has simulations - validate manually
        sim_blocks = [s.get("block_used") for s in data.get("simulations", [])]
        if sim_blocks and all(b == sim_blocks[0] for b in sim_blocks):
            checks.append(("blocks_consistent", True, "All simulations used same block"))
            blocks_consistent = True  # Update for DoD checks
        else:
            checks.append(("blocks_consistent", False, f"Block mismatch in simulations: {set(sim_blocks)}"))
            blocks_consistent = False
    
    # est_vs_sim metrics
    est_vs_sim = data.get("est_vs_sim", {})
    if est_vs_sim:
        mismatch = est_vs_sim.get("est_sim_mismatch_count", 0)
        checks.append(("est_vs_sim", True, f"est_sim_mismatch_count={mismatch}"))
    
    # ============================================================
    # PROFILE-SPECIFIC CHECKS
    # ============================================================
    
    sims_passed = data.get("simulations_passed", 0)
    total_net_usdc = data.get("total_net_usdc", 0)
    
    # Convert to number if string
    if isinstance(total_net_usdc, str):
        try:
            total_net_usdc = float(total_net_usdc)
        except ValueError:
            total_net_usdc = 0
    
    if profile == DoDProfile.SMOKE:
        # SMOKE: PASS if simulations_passed >= 1 AND accounting_complete AND blocks_consistent AND all_signals_simulated
        if sims_passed >= 1:
            checks.append(("dod_smoke_profitable", True, f"simulations_passed={sims_passed} >= 1"))
        else:
            checks.append(("dod_smoke_profitable", False, f"simulations_passed={sims_passed} < 1"))
        
        # accounting_complete can be in health OR accounting
        accounting_complete = health.get("accounting_complete", accounting.get("accounting_complete", False))
        if accounting_complete:
            checks.append(("dod_smoke_accounting", True, "accounting_complete=true"))
        else:
            checks.append(("dod_smoke_accounting", False, "accounting_complete=false"))
        
        # blocks_consistent check
        if blocks_consistent:
            checks.append(("dod_smoke_blocks", True, "blocks_consistent=true"))
        else:
            checks.append(("dod_smoke_blocks", False, "blocks_consistent=false"))
        
        # all_signals_simulated check (new in v1.1)
        all_signals_simulated = health.get("all_signals_simulated", False)
        if all_signals_simulated:
            checks.append(("dod_smoke_all_simulated", True, "all_signals_simulated=true"))
        else:
            checks.append(("dod_smoke_all_simulated", False, "all_signals_simulated=false (MISSING simulations)"))
    
    elif profile == DoDProfile.PROFIT:
        # PROFIT: PASS if total_net_usdc > 0 AND sim_profitable_count >= 1
        sim_profitable_count = est_vs_sim.get("sim_profitable_count", sims_passed)
        
        if total_net_usdc > 0:
            checks.append(("dod_profit_net", True, f"total_net_usdc={total_net_usdc:.4f} > 0"))
        else:
            checks.append(("dod_profit_net", False, f"total_net_usdc={total_net_usdc:.4f} <= 0 (UNPROFITABLE)"))
        
        if sim_profitable_count >= 1:
            checks.append(("dod_profit_sims", True, f"sim_profitable_count={sim_profitable_count} >= 1"))
        else:
            checks.append(("dod_profit_sims", False, f"sim_profitable_count={sim_profitable_count} < 1"))
    
    # Strict mode: require at least one profitable
    if strict and sims_passed == 0:
        checks.append(("strict_profitable", False, "No profitable simulations (strict mode)"))
    
    return checks


def validate_simulations(simulations: List[Dict[str, Any]], run_mode: str = "") -> List[Tuple[str, bool, str]]:
    """Validate individual simulations have required fields and valid blockers.
    
    Args:
        simulations: List of simulation results
        run_mode: If not FIXTURE_OFFLINE, require confidence and liquidity_hint
    """
    checks = []
    
    required_fields = ["signal_id", "simulation_status", "gas_usdc", "net_usdc", "is_profitable"]
    
    # Valid blocker values from SimRejectReason enum
    valid_blockers = {r.value for r in SimRejectReason}
    
    # Online mode requires confidence and liquidity_hint (not null)
    is_online = run_mode and "OFFLINE" not in run_mode.upper()
    
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
            if blocker in valid_blockers:
                checks.append((f"sim[{i}]_blocker", True, f"blocker={blocker}"))
            else:
                checks.append((f"sim[{i}]_blocker", False, f"Unknown blocker: {blocker} (not in SimRejectReason)"))
        
        # Validate block_used if present
        block_used = sim.get("block_used")
        if block_used:
            checks.append((f"sim[{i}]_block", True, f"block_used={block_used}"))
        
        # Online mode: require confidence and liquidity_hint not null
        if is_online:
            confidence = sim.get("confidence")
            liquidity_hint = sim.get("liquidity_hint")
            
            if confidence is not None:
                checks.append((f"sim[{i}]_confidence", True, f"confidence={confidence}"))
            else:
                checks.append((f"sim[{i}]_confidence", False, "confidence is null (required for online)"))
            
            if liquidity_hint is not None:
                checks.append((f"sim[{i}]_liquidity", True, f"liquidity_hint={liquidity_hint}"))
            else:
                checks.append((f"sim[{i}]_liquidity", False, "liquidity_hint is null (required for online)"))
    
    return checks


def validate_block_consistency(
    signals_data: Optional[Dict[str, Any]], 
    exec_data: Dict[str, Any]
) -> List[Tuple[str, bool, str]]:
    """
    Validate that pinned_block is consistent across signals and execution report.
    
    Invariant: All signals[].pinned_block == signals header pinned_block == exec header pinned_block
    """
    checks = []
    
    exec_pinned = exec_data.get("pinned_block")
    
    if signals_data:
        signals_pinned = signals_data.get("pinned_block")
        
        # Check signals header vs exec header
        if signals_pinned and exec_pinned:
            if signals_pinned == exec_pinned:
                checks.append(("header_block_match", True, f"pinned_block={exec_pinned} matches"))
            else:
                checks.append(("header_block_match", False, 
                              f"Block mismatch: signals={signals_pinned} vs exec={exec_pinned}"))
        
        # Check individual signals
        signals_list = signals_data.get("signals", [])
        signal_blocks = [s.get("pinned_block") for s in signals_list if s.get("pinned_block")]
        if signal_blocks:
            if all(b == signal_blocks[0] for b in signal_blocks):
                if signals_pinned and signal_blocks[0] == signals_pinned:
                    checks.append(("signals_block_uniform", True, 
                                  f"All {len(signal_blocks)} signals use pinned_block={signal_blocks[0]}"))
                else:
                    checks.append(("signals_block_uniform", False,
                                  f"Signal blocks ({signal_blocks[0]}) != header ({signals_pinned})"))
            else:
                checks.append(("signals_block_uniform", False, 
                              f"Non-uniform pinned_block in signals: {set(signal_blocks)}"))
    
    # Check simulations block_used
    simulations = exec_data.get("simulations", [])
    sim_blocks = [s.get("block_used") for s in simulations if s.get("block_used")]
    if sim_blocks and exec_pinned:
        if all(b == exec_pinned for b in sim_blocks):
            checks.append(("sim_block_match", True, 
                          f"All {len(sim_blocks)} simulations used pinned_block"))
        else:
            checks.append(("sim_block_match", False, 
                          f"Simulation blocks != header: {set(sim_blocks)} vs {exec_pinned}"))
    
    return checks


# ============================================================
# MAIN GATE LOGIC
# ============================================================

def run_offline_gate(output_root: Path, profile: str = DoDProfile.SMOKE, strict: bool = False) -> int:
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
    print(f"[OFFLINE] Profile: {profile}")
    
    # Generate fixtures
    artifacts = generate_m4_fixture(run_dir, ts)
    
    print(f"[OFFLINE] Generated artifacts:")
    for name, path in artifacts.items():
        print(f"  - {name}: {path.name}")
    
    # Load and validate
    return validate_gate(run_dir, artifacts, profile, strict)


def run_online_gate(run_dir: Optional[Path], profile: str = DoDProfile.SMOKE, strict: bool = False) -> int:
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
    
    print(f"[ONLINE] Profile: {profile}")
    return validate_gate(run_dir, {k: v for k, v in artifacts.items() if v}, profile, strict)



def validate_gate(run_dir: Path, artifacts: Dict[str, Path], profile: str, strict: bool) -> int:
    """
    Core validation logic for M4 gate.
    """
    print("\n" + "=" * 60)
    print(f"VALIDATION (profile={profile})")
    print("=" * 60)
    print()
    
    all_checks = []
    signals_data = None
    
    # Check artifacts exist
    exec_path = artifacts.get("execution_report")
    if exec_path is None or not exec_path.exists():
        print("  FAIL: execution_report not found")
        return 1
    print(f"  OK: execution_report found")
    
    # Load signals if present
    signals_path = artifacts.get("signals")
    if signals_path and signals_path.exists():
        with open(signals_path) as f:
            signals_data = json.load(f)
        print(f"  OK: signals found")
    
    # Load execution report
    with open(exec_path) as f:
        exec_data = json.load(f)
    
    # Validate execution report with profile
    checks = validate_execution_report(exec_data, profile, strict)
    all_checks.extend(checks)
    
    for name, passed, msg in checks:
        status = "OK" if passed else "FAIL"
        print(f"  {status}: {msg}")
    
    # Validate individual simulations
    simulations = exec_data.get("simulations", [])
    run_mode = exec_data.get("run_mode", "")
    if simulations:
        print()
        sim_checks = validate_simulations(simulations, run_mode=run_mode)
        all_checks.extend(sim_checks)
        
        for name, passed, msg in sim_checks:
            status = "OK" if passed else "FAIL"
            print(f"  {status}: {msg}")
    
    # Validate block consistency
    print()
    block_checks = validate_block_consistency(signals_data, exec_data)
    all_checks.extend(block_checks)
    
    for name, passed, msg in block_checks:
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
        # Show key metrics
        total_net = exec_data.get("total_net_usdc", 0)
        sims_passed = exec_data.get("simulations_passed", 0)
        print(f"RESULT: PASS (profile={profile})")
        print(f"  simulations_passed: {sims_passed}")
        print(f"  total_net_usdc: {total_net}")
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
    
    parser.add_argument("--profile", type=str, default=DoDProfile.SMOKE,
                        choices=[DoDProfile.SMOKE, DoDProfile.PROFIT],
                        help="DoD profile: smoke (>=1 profitable) or profit (total_net>0)")
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
        return run_offline_gate(args.output_root, args.profile, args.strict)
    elif args.online:
        return run_online_gate(args.run_dir, args.profile, args.strict)
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
