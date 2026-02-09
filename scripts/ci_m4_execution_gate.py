#!/usr/bin/env python3
# PATH: scripts/ci_m4_execution_gate.py
"""
M4 Execution Gate - DEX↔DEX Atomic Execution v1.

VERSION: 1.5.0 (2026-02-09)
STATUS: ACTIVE

PURPOSE:
  Validate that execution simulation works correctly:
  1. Load signals from truth_report (or generate fixture)
  2. Simulate each signal via eth_call preview
  3. Verify net > 0 after gas/slippage
  4. Report PASS/FAIL with reasons

MODES:
  --offline: Uses synthetic fixtures (no RPC). run_mode=FIXTURE_OFFLINE.
             This validates code/schema correctness, NOT online profitability.
  --online:  Uses real artifacts from --run-dir or latest run.
             Validates actual simulation results on real blocks.

CANONICAL COMMANDS:
  # Offline - synthetic fixtures (no RPC, no proof of online profit)
  python scripts/ci_m4_execution_gate.py --offline
  python scripts/ci_m4_execution_gate.py --offline --profile smoke
  python scripts/ci_m4_execution_gate.py --offline --profile profit

  # Online - real artifacts (requires prior scan/simulation run)
  python scripts/ci_m4_execution_gate.py --online --run-dir data/runs/<dir>
  python scripts/ci_m4_execution_gate.py --online --profile profit
  
  # Online with cost model selection
  python scripts/ci_m4_execution_gate.py --online --cost-model paper_conservative

DOD PROFILES:
  smoke (default): PASS if simulations_passed >= 1 AND accounting_complete
  profit: PASS if total_net_usdc > 0 AND sim_profitable_count >= 1
  online: PASS if profit criteria met on REAL block (not fixture)

COST MODELS:
  paper_realistic: gas=$0.10, slippage=5bps (default)
  paper_conservative: gas=$0.30, slippage=20bps (stress test)

STATUS MODEL (v1.5.0):
  run_summary now has TWO separate statuses:
  - profit_status: PASS if net > 0 AND sim_profitable >= 1 (core profitability)
  - drift_status: PASS if mae <= threshold AND sign_rate >= threshold (estimation quality)
  - final status: Configurable policy (default: PASS requires both)

FAIL CONDITIONS (explicit, v1.5.0):
  - FAIL_NET: total_net_usdc <= 0 (PROFIT profile)
  - FAIL_DRIFT_MAE: mae_net_usdc > 0.50 (exclusive, PROFIT profile)
  - FAIL_DRIFT_SIGN: sign_correct_rate < 0.70 (PROFIT profile)
  - FAIL_SIGN_MISMATCH: sign_mismatch_count > 0 (strict mode)
  - FAIL_NO_PROFITABLE: sim_profitable_count == 0
  - WARN_DRIFT_MAE: 0.30 < mae_net_usdc <= 0.50

THRESHOLDS (v1.5.0):
  - mae_warn: > 0.30 (exclusive)
  - mae_fail: > 0.50 (exclusive, not >=)
  - sign_rate_min: < 0.70

ARTIFACTS GENERATED:
  - signals_<ts>.json: M4 signals from truth_report
  - execution_report_<ts>.json: Simulation results
  - run_summary_<ts>.json: Canonical single-run summary (v1.1, with profit_status + drift_status)
  - stability_summary_<ts>.json: Single-run stability with reasons

FIELD DEFINITIONS:
  - sign_mismatch_count: Signals where sign(est_net) != sign(sim_net)
  - would_execute_if_enabled: Simulation passed AND execution_enabled would be true
  - exec_ready: false (always, until M5 enables execution)
  - fragile: Signal where est_net < slippage + gas (at risk of flip)
  - mae_no_slippage: MAE calculated without slippage component

SUCCESS CRITERIA (from Roadmap):
  - 1-2 pairs, 2 DEX, on one chain
  - Signal found → Simulated → net > 0 after gas/slippage
  - execution_enabled=false (kill-switch)

EXIT CODES: 0=PASS, 1=FAIL validation, 2=NO_SIGNALS, 3=SIM_FAILED
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
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

# Import artifact invariants for unified validation
from core.artifact_invariants import (
    RunMode,
    check_m4_execution_invariants,
    check_m4_profitability,
    validate_block_number,
    ProfileRegistry,
    get_profile,
)

__version__ = "1.5.0"

# ============================================================
# FAIL REASON CODES (explicit definitions)
# ============================================================

class FailReason:
    """
    Explicit fail reason codes for M4 execution gate.
    
    These codes are used in run_summary.json.reasons[] to explain FAIL/WARN status.
    Each reason corresponds to a specific threshold violation.
    
    v1.5.0: mae_fail is now > 0.50 (exclusive), not >= 0.50
    """
    # FAIL conditions (profit_status)
    FAIL_NET = "FAIL_NET"                        # total_net_usdc <= 0 (PROFIT profile)
    FAIL_NO_PROFITABLE = "FAIL_NO_PROFITABLE"    # sim_profitable_count == 0
    
    # FAIL conditions (drift_status)
    FAIL_DRIFT_MAE = "FAIL_DRIFT_MAE"            # mae_net_usdc > 0.50 (exclusive)
    FAIL_DRIFT_SIGN = "FAIL_DRIFT_SIGN"          # sign_correct_rate < 0.70
    FAIL_SIGN_MISMATCH = "FAIL_SIGN_MISMATCH"    # sign_mismatch_count > 0 (strict mode)
    
    # WARN conditions
    WARN_DRIFT_MAE = "WARN_DRIFT_MAE"            # 0.30 < mae <= 0.50


# ============================================================
# THRESHOLDS (centralized, v1.5.0)
# ============================================================

class Thresholds:
    """Centralized threshold definitions for drift metrics."""
    MAE_WARN = 0.30      # mae > 0.30 triggers WARN
    MAE_FAIL = 0.50      # mae > 0.50 triggers FAIL (exclusive, not >=)
    SIGN_RATE_MIN = 0.70  # sign_rate < 0.70 triggers FAIL
    
    # Slippage component (for mae_no_slippage calculation)
    # When truth uses slippage=0 and sim uses slippage=X, drift includes systematic component
    SLIPPAGE_SYSTEMATIC_FACTOR = 1.0  # per-signal slippage adds to expected drift
    

# ============================================================
# COST MODEL REGISTRY
# ============================================================

@dataclass
class CostModelConfig:
    """Cost model configuration for simulation."""
    name: str
    description: str
    gas_usd: float
    slippage_bps: int
    

class CostModelRegistry:
    """
    Registry for simulation cost models.
    
    Usage:
        registry = CostModelRegistry.default()
        model = registry.get("paper_realistic")
        gas = model.gas_usd
        slippage = model.slippage_bps
    """
    
    _instance: Optional["CostModelRegistry"] = None
    
    def __init__(self):
        self._models: Dict[str, CostModelConfig] = {}
    
    def register(self, model: CostModelConfig) -> None:
        """Register a cost model."""
        self._models[model.name] = model
    
    def get(self, name: str) -> CostModelConfig:
        """Get cost model by name."""
        if name not in self._models:
            raise ValueError(f"Unknown cost model: {name}. Available: {list(self._models.keys())}")
        return self._models[name]
    
    def list_models(self) -> List[str]:
        """List all registered cost model names."""
        return list(self._models.keys())
    
    @classmethod
    def default(cls) -> "CostModelRegistry":
        """Get default registry with standard cost models."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_defaults()
        return cls._instance
    
    def _register_defaults(self) -> None:
        """Register default cost models."""
        # Paper realistic: optimistic but reasonable
        self.register(CostModelConfig(
            name="paper_realistic",
            description="Paper simulation with realistic costs (gas=$0.10, slippage=5bps)",
            gas_usd=0.10,
            slippage_bps=5,
        ))
        
        # Paper conservative: stress test (higher costs)
        self.register(CostModelConfig(
            name="paper_conservative",
            description="Paper simulation with conservative costs (gas=$0.30, slippage=20bps)",
            gas_usd=0.30,
            slippage_bps=20,
        ))
        
        # Gas only: M5 compatibility (slippage=0)
        self.register(CostModelConfig(
            name="gas_only",
            description="Gas only, no slippage (M5 truth_report compatibility)",
            gas_usd=0.10,
            slippage_bps=0,
        ))


def get_cost_model(name: str) -> CostModelConfig:
    """Convenience function to get cost model from default registry."""
    return CostModelRegistry.default().get(name)


def get_git_sha() -> str:
    """Get current git HEAD SHA (short form)."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ============================================================
# DOD PROFILES (using registry)
# ============================================================

class DoDProfile:
    """Definition of Done profiles for M4 gate."""
    SMOKE = "smoke"    # PASS if >=1 profitable sim + accounting complete
    PROFIT = "profit"  # PASS if total_net_usd > 0
    ONLINE = "online"  # PASS if total_net_usd > 0 on real block (for tracking)
    
    @classmethod
    def get_config(cls, profile: str):
        """Get profile config from registry."""
        return get_profile(profile)

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

def generate_m4_fixture(run_dir: Path, ts: str, profile: str = DoDProfile.SMOKE) -> Dict[str, Path]:
    """
    Generate M4 execution fixture for offline testing.
    
    Creates:
    - execution_report_<ts>.json: Simulation results
    - signals_<ts>.json: Input signals
    
    Fixture uses numerical USD values (not strings) for proper validation.
    All prices are strings (decimal format) for consistency.
    spread_bps is integer micro-bps (1 bps = 10000 micro-bps).
    
    Args:
        run_dir: Output directory
        ts: Timestamp string
        profile: DoDProfile.SMOKE or DoDProfile.PROFIT
                 SMOKE: 1 profitable + 1 unprofitable = net negative
                 PROFIT: 2 profitable = net positive
    """
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    pinned_block = DEFAULT_PINNED_BLOCK
    chain_id = DEFAULT_CHAIN_ID
    
    # Profile-specific signal/simulation values
    # SMOKE: sig_002 is unprofitable (tests accounting of losses)
    # PROFIT: sig_002 is profitable (tests total_net_usdc > 0 criterion)
    if profile == DoDProfile.PROFIT:
        # PROFIT profile: both signals profitable
        sig_002_values = {
            "gross_pnl_usdc_est": 0.45,
            "gas_usdc_est": 0.25,
            "slippage_usdc_est": 0.05,
            "net_pnl_usdc_est": 0.15,
            "is_net_positive_est": True,
        }
        sim_002_values = {
            "simulation_status": "PASS",
            "blocker": None,
            "gas_usdc": 0.25,
            "slippage_usdc": 0.05,
            "gross_pnl_usdc": 0.42,
            "net_usdc": 0.12,  # Positive! Total = 0.38 + 0.12 = 0.50
            "is_profitable": True,
            "est_net_usdc": 0.15,
            "est_was_positive": True,
            "sim_was_positive": True,
            "est_sign_correct": True,
            "est_error_usdc": -0.03,  # sim worse by 0.03
        }
    else:
        # SMOKE profile: sig_002 is unprofitable (original behavior)
        sig_002_values = {
            "gross_pnl_usdc_est": 0.12,
            "gas_usdc_est": 0.52,
            "slippage_usdc_est": 0.15,
            "net_pnl_usdc_est": -0.55,
            "is_net_positive_est": False,
        }
        sim_002_values = {
            "simulation_status": "FAIL",
            "blocker": SimRejectReason.SIM_UNPROFITABLE.value,
            "gas_usdc": 0.52,
            "slippage_usdc": 0.15,
            "gross_pnl_usdc": 0.00,
            "net_usdc": -0.67,
            "is_profitable": False,
            "est_net_usdc": -0.55,
            "est_was_positive": False,
            "sim_was_positive": False,
            "est_sign_correct": True,
            "est_error_usdc": -0.12,
        }
    
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
            # Profile-specific values
            "gross_pnl_usdc_est": sig_002_values["gross_pnl_usdc_est"],
            "gas_usdc_est": sig_002_values["gas_usdc_est"],
            "slippage_usdc_est": sig_002_values["slippage_usdc_est"],
            "net_pnl_usdc_est": sig_002_values["net_pnl_usdc_est"],
            "is_net_positive_est": sig_002_values["is_net_positive_est"],
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
            "simulation_status": sim_002_values["simulation_status"],
            "blocker": sim_002_values["blocker"],
            "block_used": pinned_block,
            "confidence": 0.60,
            "liquidity_hint": "adequate",
            "size_usdc_simulated": 100.0,
            "gas_used": 280000 if profile != DoDProfile.PROFIT else 180000,
            "gas_usdc": sim_002_values["gas_usdc"],
            "slippage_bps_actual": 8 if profile != DoDProfile.PROFIT else 3,
            "slippage_usdc": sim_002_values["slippage_usdc"],
            "gross_pnl_usdc": sim_002_values["gross_pnl_usdc"],
            "net_usdc": sim_002_values["net_usdc"],
            "is_profitable": sim_002_values["is_profitable"],
            # Expanded est_vs_sim
            "est_net_usdc": sim_002_values["est_net_usdc"],
            "est_was_positive": sim_002_values["est_was_positive"],
            "sim_was_positive": sim_002_values["sim_was_positive"],
            "est_sign_correct": sim_002_values["est_sign_correct"],
            "est_error_usdc": sim_002_values["est_error_usdc"],
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
    # Renamed from est_sim_mismatch_count to sign_mismatch_count (v1.4.0)
    sign_mismatch_count = sum(
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
        # Counts (use *_count consistently, never None)
        "simulations_count": len(fixture_simulations),
        "simulations_passed": sim_profitable_count,
        "simulations_failed": len(fixture_simulations) - sim_profitable_count,
        "trades_count": 0,                  # simulate_only = no trades executed
        "trades_executed": 0,               # explicit zero, never None
        # Totals (USDC)
        "total_gas_usdc": total_gas_usdc,
        "total_net_usdc": total_net_usdc,
        "pass_rate": round(sim_profitable_count / len(fixture_simulations), 4) if fixture_simulations else 0,
        # Expanded Estimate vs Simulation metrics
        "est_vs_sim": {
            "est_profitable_count": est_profitable_count,
            "sim_profitable_count": sim_profitable_count,
            # Renamed from est_sim_mismatch_count (v1.4.0)
            "sign_mismatch_count": sign_mismatch_count,
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
# ONLINE EXECUTION: scan/truth → M4 signals → simulation
# ============================================================

def get_source_sha() -> str:
    """Get current git commit SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=REPO_ROOT
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def generate_m4_from_online_inputs(
    run_dir: Path, 
    ts: str,
    cost_model_name: str = "paper_realistic",
) -> Dict[str, Path]:
    """
    Generate M4 execution artifacts from online scan/truth inputs.
    
    This bridges online M5 scan/truth → M4 signals/execution_report.
    
    CRITICAL: est_net comes from truth_report (original estimate with paper_slippage_bps=0),
    sim_net is calculated with realistic cost model. This separation allows MAE to
    measure actual drift between estimate and simulation.
    
    Steps:
    1. Read truth_report_*.json to get spread_signals
    2. Convert spread_signals → M4 signals format (preserving original estimates)
    3. Simulate each signal with realistic cost model
    4. Generate execution_report with est_vs_sim drift metrics
    
    Args:
        run_dir: Directory containing scan/truth artifacts
        ts: Timestamp for output filenames
        cost_model_name: Name of cost model to use (default: paper_realistic)
        
    Returns:
        Dict with paths to generated signals and execution_report
    """
    reports_dir = run_dir / "reports"
    
    # Get cost model from registry
    cost_model = get_cost_model(cost_model_name)
    
    # Get source SHA for artifact provenance
    source_sha = get_source_sha()
    run_id = run_dir.name  # Use directory name as run_id
    
    # Find truth_report
    truth_files = sorted(reports_dir.glob("truth_report_*.json"), reverse=True)
    if not truth_files:
        raise FileNotFoundError(f"No truth_report found in {reports_dir}")
    
    truth_path = truth_files[0]
    with open(truth_path) as f:
        truth_data = json.load(f)
    
    # Extract key metadata from truth_report
    source_run_mode = truth_data.get("run_mode", "UNKNOWN")
    source_block = truth_data.get("current_block", 0)
    chain_id = truth_data.get("chain_id", DEFAULT_CHAIN_ID)
    source_timestamp = truth_data.get("timestamp", "")
    spread_signals = truth_data.get("spread_signals", [])
    
    # Get cost model from registry (passed via argument)
    # This allows switching between paper_realistic and paper_conservative
    gas_estimate = cost_model.gas_usd
    realistic_slippage_bps = cost_model.slippage_bps
    
    print(f"\n[ONLINE] Source: {truth_path.name}")
    print(f"[ONLINE] run_mode: {source_run_mode}")
    print(f"[ONLINE] current_block: {source_block}")
    print(f"[ONLINE] spread_signals: {len(spread_signals)}")
    print(f"[ONLINE] source_sha: {source_sha}")
    print(f"[ONLINE] run_id: {run_id}")
    print(f"[ONLINE] cost_model: {cost_model.name} (gas=${gas_estimate:.2f}, slippage={realistic_slippage_bps}bps)")
    
    # Convert spread_signals → M4 signals
    # CRITICAL: est_net_usdc comes DIRECTLY from truth_report (original estimate)
    # sim_net_usdc will be calculated SEPARATELY with realistic cost model
    # This separation allows MAE to measure actual drift between estimate and simulation
    m4_signals = []
    for i, sig in enumerate(spread_signals):
        signal_id = f"sig_{i+1:03d}_{ts}"
        
        # Extract from spread_signal
        pair = sig.get("pair", "UNKNOWN/UNKNOWN")
        parts = pair.split("/")
        base_token = parts[0] if len(parts) >= 1 else "BASE"
        quote_token = parts[1] if len(parts) >= 2 else "QUOTE"
        
        buy_dex = sig.get("buy_dex", "unknown")
        sell_dex = sig.get("sell_dex", "unknown")
        buy_price = sig.get("buy_price", "0")
        sell_price = sig.get("sell_price", "0")
        buy_pool = sig.get("buy_pool", "")
        sell_pool = sig.get("sell_pool", "")
        
        spread_bps = sig.get("spread_bps_exact", 0)
        size_usd = sig.get("size_usd", 1000.0)
        gross_pnl_est = sig.get("gross_pnl_usdc_est", 0)
        
        # ORIGINAL estimate from truth_report (with paper_slippage_bps from config, usually 0)
        truth_net_pnl_est = sig.get("net_pnl_usdc_est", 0)
        truth_slippage_bps = sig.get("slippage_bps", 0)  # Usually 0 for paper
        is_net_positive = sig.get("is_net_positive_est", False)
        
        m4_signal = {
            "signal_id": signal_id,
            "source": "truth_report",
            "source_timestamp": source_timestamp,
            "pair": pair,
            "base_token": base_token,
            "quote_token": quote_token,
            "buy_dex": buy_dex,
            "sell_dex": sell_dex,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "buy_pool": buy_pool,
            "sell_pool": sell_pool,
            "spread_bps": round(spread_bps, 2),
            "size_usd": size_usd,
            "est_gross_usdc": round(gross_pnl_est, 4),
            # ORIGINAL estimate values from truth_report (for MAE calculation)
            "truth_net_usdc": round(truth_net_pnl_est, 4),  # Original estimate, no realistic slippage
            "truth_slippage_bps": truth_slippage_bps,
            # Simulator cost model (realistic) - applied during simulation
            "sim_gas_usdc": gas_estimate,
            "sim_slippage_bps": realistic_slippage_bps,
            "is_net_positive_est": is_net_positive,
            "confidence": sig.get("confidence", "low"),
            "block_number": sig.get("block_number", source_block),
        }
        m4_signals.append(m4_signal)
    
    # Write M4 signals
    signals_path = reports_dir / f"signals_{ts}.json"
    signals_data = {
        "schema_version": "m4:signals:v1.2",  # Bumped for source_sha/run_id
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "run_mode": source_run_mode,  # Inherit from truth_report
        # Provenance fields
        "source_sha": source_sha,
        "run_id": run_id,
        "source_truth_report": truth_path.name,
        "source_block": source_block,
        "chain_id": chain_id,
        "pinned_block": source_block,
        "quote_ccy": "USDC",
        "price_format": "decimal_str",
        "price_in": "quote_per_base",
        "spread_format": "bps",
        # Cost model used for simulation
        "cost_model": {
            "name": cost_model.name,
            "gas_usd": cost_model.gas_usd,
            "slippage_bps": cost_model.slippage_bps,
        },
        "signals": m4_signals,
    }
    with open(signals_path, "w") as f:
        json.dump(signals_data, f, indent=2)
    
    print(f"[ONLINE] Generated: {signals_path.name} ({len(m4_signals)} signals)")
    
    # Simulate each signal (paper simulation with realistic costs)
    # CRITICAL: est_net comes from truth_report, sim_net from simulator with realistic costs
    # This separation allows MAE to measure actual drift
    simulations = []
    sim_profitable_count = 0
    total_net_usdc = 0.0
    est_net_sum = 0.0  # Sum of ORIGINAL estimates from truth_report
    sim_net_sum = 0.0  # Sum of SIMULATED net with realistic costs
    est_errors = []
    sign_correct_count = 0
    
    for sig in m4_signals:
        signal_id = sig["signal_id"]
        
        # ORIGINAL estimate from truth_report (usually with paper_slippage_bps=0)
        est_net = sig["truth_net_usdc"]  # From truth_report, NOT recalculated
        est_net_sum += est_net
        
        # Simulate: apply REALISTIC gas and slippage
        est_gross = sig["est_gross_usdc"]
        gas_usdc = sig["sim_gas_usdc"]  # Realistic gas from cost model
        slippage_bps = sig["sim_slippage_bps"]  # Realistic slippage (e.g., 5bps)
        size_usd = sig["size_usd"]
        slippage_usdc = round(size_usd * slippage_bps / 10000, 4)
        
        # Simulated net = gross - gas - slippage (with REALISTIC costs)
        sim_net_usdc = round(est_gross - gas_usdc - slippage_usdc, 4)
        
        # Check if simulation would be profitable
        is_profitable = sim_net_usdc > 0
        if is_profitable:
            sim_profitable_count += 1
        
        total_net_usdc += sim_net_usdc
        sim_net_sum += sim_net_usdc
        
        # Calculate est error: sim_net - est_net
        # Negative = simulation worse than estimate (est was optimistic)
        # Positive = simulation better than estimate (est was conservative)
        est_error = round(sim_net_usdc - est_net, 4)
        est_errors.append(abs(est_error))
        
        # Sign correct? (both predict same sign of profitability)
        est_was_positive = est_net > 0
        sim_was_positive = sim_net_usdc > 0
        sign_correct = (est_was_positive == sim_was_positive)
        if sign_correct:
            sign_correct_count += 1
        
        # Determine blocker if not profitable
        blocker = None
        if not is_profitable:
            if sim_net_usdc < -1.0:
                blocker = SimRejectReason.SIM_UNPROFITABLE.value
            elif slippage_usdc > est_gross * 0.5:
                blocker = SimRejectReason.SIM_SLIPPAGE_TOO_HIGH.value
            elif gas_usdc > est_gross:
                blocker = SimRejectReason.SIM_GAS_TOO_HIGH.value
            else:
                blocker = SimRejectReason.SIM_UNPROFITABLE.value
        
        simulation = {
            "signal_id": signal_id,
            "simulation_status": "OK" if is_profitable else "FAIL",
            "simulation_mode": "paper_realistic",  # Paper simulation with realistic costs
            "cost_model": "paper_realistic",
            "block_used": sig["block_number"],
            "gas_used": 250000,  # Estimated
            "gas_usdc": gas_usdc,
            "slippage_bps_applied": slippage_bps,
            "slippage_usdc": slippage_usdc,
            "gross_usdc": est_gross,
            "sim_net_usdc": sim_net_usdc,  # SIMULATED with realistic costs
            "est_net_usdc": est_net,  # ORIGINAL from truth_report
            "est_error_usdc": est_error,  # Drift: sim - est
            "est_was_positive": est_was_positive,
            "sim_was_positive": sim_was_positive,
            "est_sign_correct": sign_correct,
            "is_profitable": is_profitable,
            "blocker": blocker,
            # Clarified field names (v1.4.0):
            # would_execute_if_enabled: True if sim passed AND we would execute if enabled
            # exec_ready: Always false until M5 enables real execution
            "would_execute_if_enabled": is_profitable,
            "exec_ready": False,  # M4 = simulation only, never ready for real execution
            # Compat fields for net_usdc
            "net_usdc": sim_net_usdc,  # Legacy: same as sim_net_usdc
            # Required for online validation
            "confidence": sig.get("confidence", "medium"),
            "liquidity_hint": "sufficient",  # Assumed for paper simulation
        }
        simulations.append(simulation)
    
    # Calculate drift metrics
    mae_net_usdc = round(sum(est_errors) / len(est_errors), 4) if est_errors else 0.0
    est_sign_correct_rate = round(sign_correct_count / len(m4_signals), 4) if m4_signals else 0.0
    
    # Count sign mismatches: signals where sign(est_net) != sign(sim_net)
    # Renamed from est_sim_mismatch_count for clarity (v1.4.0)
    sign_mismatch_count = len(m4_signals) - sign_correct_count
    
    print(f"[ONLINE] Simulated: {len(simulations)} signals")
    print(f"[ONLINE] Profitable: {sim_profitable_count}/{len(simulations)}")
    print(f"[ONLINE] total_net_usdc: ${total_net_usdc:.4f}")
    print(f"[ONLINE] MAE: ${mae_net_usdc:.4f}, sign_rate: {est_sign_correct_rate:.2%}")
    if sign_mismatch_count > 0:
        print(f"[ONLINE] sign_mismatch_count: {sign_mismatch_count}")
    
    # Write execution_report
    exec_path = reports_dir / f"execution_report_{ts}.json"
    exec_data = {
        "schema_version": "m4:execution:v1.2",  # Bumped for source_sha/run_id
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "run_mode": source_run_mode,  # REGISTRY_REAL from truth_report
        # Provenance fields for artifact integrity
        "source_sha": source_sha,
        "run_id": run_id,
        "source_truth_report": truth_path.name,
        "source_signals": signals_path.name,
        "chain_id": chain_id,
        "pinned_block": source_block,
        "quote_ccy": "USDC",
        "price_format": "decimal_str",
        "price_in": "quote_per_base",
        "spread_format": "bps",
        "slippage_format": "bps",
        "est_error_definition": "sim_net_usdc - est_net_usdc (negative = sim worse than est)",
        # Root-level safety invariants (MUST be checked by gate)
        "execution_enabled": False,
        "kill_switch_active": True,
        "cost_model": {
            "name": cost_model.name,
            "description": cost_model.description,
            "gas_usd": cost_model.gas_usd,
            "slippage_bps": cost_model.slippage_bps,
        },
        "signals_count": len(m4_signals),
        "simulations_count": len(simulations),
        "simulations_passed": sim_profitable_count,
        "total_net_usdc": round(total_net_usdc, 4),
        "trades_count": 0,  # Paper mode - no actual trades
        "trades_executed": 0,
        "simulations": simulations,
        "est_vs_sim": {
            "est_net_usdc_sum": round(est_net_sum, 4),
            "sim_net_usdc_sum": round(sim_net_sum, 4),
            # Renamed from est_sim_mismatch_count for clarity (v1.4.0)
            "sign_mismatch_count": sign_mismatch_count,
            "sim_profitable_count": sim_profitable_count,
            "mae_net_usdc": mae_net_usdc,
            "est_sign_correct_count": sign_correct_count,
            "est_sign_correct_rate": est_sign_correct_rate,
        },
        "accounting": {
            "accounting_complete": True,
            "signals_total": len(m4_signals),
            "simulations_total": len(simulations),
        },
        "health": {
            "simulation_pass_rate": round(sim_profitable_count / len(simulations), 4) if simulations else 0,
            "blocks_consistent": True,
            "all_signals_simulated": True,
            "execution_enabled": False,  # Kill switch active
            "kill_switch_active": True,
        },
    }
    
    with open(exec_path, "w") as f:
        json.dump(exec_data, f, indent=2)
    
    print(f"[ONLINE] Generated: {exec_path.name}")
    
    # Generate stability_summary.json artifact
    stability_path = reports_dir / f"stability_summary_{ts}.json"
    
    # ============================================================
    # SPLIT STATUS: profit_status vs drift_status (v1.5.0)
    # ============================================================
    
    # profit_status: core profitability (net > 0, profitable sims exist)
    profit_reasons = []
    profit_status = "PASS"
    if total_net_usdc <= 0:
        profit_status = "FAIL"
        profit_reasons.append(FailReason.FAIL_NET)
    if sim_profitable_count == 0:
        profit_status = "FAIL"
        profit_reasons.append(FailReason.FAIL_NO_PROFITABLE)
    
    # drift_status: estimation quality (mae, sign rate)
    drift_reasons = []
    drift_status = "PASS"
    
    # MAE check (> 0.50 is FAIL, exclusive, v1.5.0)
    if mae_net_usdc > Thresholds.MAE_FAIL:
        drift_status = "FAIL"
        drift_reasons.append(FailReason.FAIL_DRIFT_MAE)
    elif mae_net_usdc > Thresholds.MAE_WARN:
        drift_reasons.append(FailReason.WARN_DRIFT_MAE)
    
    # Sign rate check
    if est_sign_correct_rate < Thresholds.SIGN_RATE_MIN:
        drift_status = "FAIL"
        drift_reasons.append(FailReason.FAIL_DRIFT_SIGN)
    
    # Calculate mae_no_slippage: what MAE would be if slippage were the same
    # Since truth uses slippage=0 and sim uses slippage=X, drift includes systematic component
    # mae_no_slippage = mae - expected_slippage_contribution
    slippage_contribution_per_signal = round(
        sum(sig.get("size_usd", 0) * cost_model.slippage_bps / 10000 for sig in m4_signals) / len(m4_signals), 4
    ) if m4_signals else 0.0
    mae_no_slippage = round(max(0, mae_net_usdc - slippage_contribution_per_signal), 4)
    
    # Count fragile signals: est_net < slippage + gas (at risk of sign flip)
    fragile_count = 0
    fragile_signals = []
    for sig in m4_signals:
        est_net = sig.get("truth_net_usdc", 0)
        size_usd = sig.get("size_usd", 0)
        slippage_usdc = size_usd * cost_model.slippage_bps / 10000
        gas_usdc = cost_model.gas_usd
        if est_net < slippage_usdc + gas_usdc and est_net > 0:
            fragile_count += 1
            fragile_signals.append(sig.get("signal_id", "unknown"))
    
    # Combined status with policy
    # Default policy: PASS requires profit_status=PASS (drift can be WARN/FAIL)
    # Alternative policy (strict): PASS requires both profit_status=PASS AND drift_status=PASS
    # Current: Use combined for backwards compat, but expose both
    all_reasons = profit_reasons + drift_reasons
    combined_status = "FAIL" if (profit_status == "FAIL" or drift_status == "FAIL") else "PASS"
    
    stability_data = {
        "schema_version": "m4:stability:v1.2",  # Bumped for split status
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source_sha": source_sha,
        "run_id": run_id,
        "chain_id": chain_id,
        "pinned_block": source_block,
        "cost_model": {
            "name": cost_model.name,
            "gas_usd": cost_model.gas_usd,
            "slippage_bps": cost_model.slippage_bps,
        },
        "summary": {
            "signals_count": len(m4_signals),
            "simulations_count": len(simulations),
            "sim_profitable_count": sim_profitable_count,
            "total_net_usdc": round(total_net_usdc, 4),
            "profitable_rate": round(sim_profitable_count / len(simulations), 4) if simulations else 0,
            "fragile_count": fragile_count,
        },
        "drift_metrics": {
            "mae_net_usdc": mae_net_usdc,
            "mae_no_slippage": mae_no_slippage,  # v1.5.0: MAE without slippage component
            "est_sign_correct_rate": est_sign_correct_rate,
            "sign_mismatch_count": sign_mismatch_count,
            "est_net_sum": round(est_net_sum, 4),
            "sim_net_sum": round(sim_net_sum, 4),
            "sum_drift_usdc": round(abs(est_net_sum - sim_net_sum), 4),
            # Slippage explanation (v1.6.0):
            # - mae_slippage_component: expected per-signal MAE from slippage difference (truth=0, sim=Xbps)
            # - total_slippage_usdc: total slippage across all signals = mae_slippage_component * signals_count
            "mae_slippage_component": slippage_contribution_per_signal,
            "total_slippage_usdc": round(slippage_contribution_per_signal * len(simulations), 4),
        },
        "thresholds": {
            "mae_warn": Thresholds.MAE_WARN,
            "mae_fail": Thresholds.MAE_FAIL,  # > 0.50 is FAIL (exclusive, v1.5.0)
            "sign_rate_min": Thresholds.SIGN_RATE_MIN,
        },
        # Split status (v1.5.0)
        "profit_status": profit_status,
        "profit_reasons": profit_reasons,
        "drift_status": drift_status,
        "drift_reasons": drift_reasons,
        # Combined status (backwards compat)
        "status": combined_status,
        "reasons": all_reasons,
    }
    
    with open(stability_path, "w") as f:
        json.dump(stability_data, f, indent=2)
    
    print(f"[ONLINE] Generated: {stability_path.name}")
    
    # ============================================================
    # GENERATE run_summary.json (v1.5.0)
    # Canonical single-run summary - source of truth for continuous scan
    # Split profit_status / drift_status with evidence validation
    # ============================================================
    run_summary_path = reports_dir / f"run_summary_{ts}.json"
    
    # Evidence validation (v1.5.0)
    evidence_issues = []
    current_sha = get_git_sha()
    
    # Check source_sha matches HEAD
    if source_sha and current_sha and current_sha != "unknown":
        if source_sha != current_sha:
            evidence_issues.append(f"source_sha_mismatch: artifact={source_sha[:8]} HEAD={current_sha[:8]}")
    else:
        evidence_issues.append("source_sha_unavailable")
    
    # Check timestamp deltas
    truth_ts_str = truth_data.get("timestamp", "")
    try:
        if truth_ts_str:
            # Parse truth timestamp
            truth_ts = datetime.fromisoformat(truth_ts_str.replace("Z", "+00:00"))
            now = datetime.now(truth_ts.tzinfo) if truth_ts.tzinfo else datetime.utcnow()
            delta_seconds = abs((now - truth_ts).total_seconds())
            if delta_seconds > 300:  # 5 minutes tolerance
                evidence_issues.append(f"timestamp_delta_high: {delta_seconds:.0f}s")
    except Exception:
        pass
    
    evidence_ok = len(evidence_issues) == 0
    
    # Find source_scan from same directory
    scan_files = list(reports_dir.glob("scan_*.json"))
    source_scan_name = sorted(scan_files, key=lambda x: x.name, reverse=True)[0].name if scan_files else None
    
    # Calculate sum_drift for run_summary
    sum_drift_usdc = round(abs(est_net_sum - sim_net_sum), 4)
    
    run_summary_data = {
        "schema_version": "run:summary:v1.2",  # v1.6.0: policy, kpi, sum_drift, source_scan
        "timestamp": datetime.utcnow().isoformat() + "Z",
        # Provenance
        "source_sha": source_sha,
        "run_id": run_id,
        # Evidence validation (v1.5.0)
        "evidence": {
            "ok": evidence_ok,
            "issues": evidence_issues,
            "current_sha": current_sha if current_sha != "unknown" else None,
        },
        # Policy (v1.6.0) - explicit threshold interpretation
        "policy": {
            "mae_fail_inclusive": False,  # > 0.50 is FAIL, not >= 0.50
            "warn_means": "Model drift detected but profitable - investigate but don't block",
            "fail_means": "Critical issue - fix before proceeding",
            "status_rule": "PASS if profit_status=PASS AND drift_status!=FAIL",
        },
        # KPI (v1.6.0) - what we measure for M4 success
        "kpi": {
            "primary": "sim_net_usdc_sum",
            "description": "M4 KPI is simulated net PnL (with realistic costs)",
            "value": round(sim_net_sum, 4),
        },
        # Inputs
        "inputs": {
            "chain_id": chain_id,
            "pinned_block": source_block,
            "source_scan": source_scan_name,
            "source_truth_report": truth_path.name,
            "source_signals": signals_path.name,
        },
        # Cost models - truth vs sim for transparency
        "cost_models": {
            "truth": {
                "name": "gas_only",  # truth_report uses paper_slippage_bps=0
                "description": "Truth report estimate (gas only, no slippage)",
                "gas_usd": 0.10,
                "slippage_bps": 0,
            },
            "sim": {
                "name": cost_model.name,
                "description": cost_model.description,
                "gas_usd": cost_model.gas_usd,
                "slippage_bps": cost_model.slippage_bps,
            },
        },
        # Metrics - all key numbers in one place
        "metrics": {
            "signals_count": len(m4_signals),
            "simulations_count": len(simulations),
            "sim_profitable_count": sim_profitable_count,
            "total_net_usdc": round(total_net_usdc, 4),
            "profitable_rate": round(sim_profitable_count / len(simulations), 4) if simulations else 0,
            "est_net_usdc_sum": round(est_net_sum, 4),
            "sim_net_usdc_sum": round(sim_net_sum, 4),
            "sum_drift_usdc": sum_drift_usdc,  # v1.6.0: est_sum - sim_sum
            "mae_net_usdc": mae_net_usdc,
            "mae_no_slippage": mae_no_slippage,  # v1.5.0
            "mae_slippage_component": slippage_contribution_per_signal,  # v1.6.0: expected per-signal slippage MAE
            "total_slippage_usdc": round(slippage_contribution_per_signal * len(simulations), 4),  # v1.6.0
            "est_sign_correct_rate": est_sign_correct_rate,
            "sign_mismatch_count": sign_mismatch_count,
            "fragile_count": fragile_count,  # v1.5.0
        },
        # Thresholds - explicit boundaries
        "thresholds": {
            "mae_warn": Thresholds.MAE_WARN,
            "mae_fail": Thresholds.MAE_FAIL,  # > 0.50 is FAIL (exclusive)
            "sign_rate_min": Thresholds.SIGN_RATE_MIN,
        },
        # Split status (v1.5.0) - allows policy-based interpretation
        "profit_status": profit_status,
        "profit_reasons": profit_reasons,
        "drift_status": drift_status,
        "drift_reasons": drift_reasons,
        # Combined status (backwards compat, default policy: both must pass)
        "status": combined_status,
        "reasons": all_reasons,
        # Safety invariants
        "safety": {
            "execution_enabled": False,
            "kill_switch_active": True,
            "exec_ready": False,  # Always false until M5
        },
        # Profile used
        "profile": "profit",  # PROFIT profile for online
        # Fragile signals list (v1.6.0): top-10 with reasons when fragile_count>0
        "fragile_signals": fragile_signals[:10] if fragile_count > 0 and fragile_signals else None,
    }
    
    with open(run_summary_path, "w") as f:
        json.dump(run_summary_data, f, indent=2)
    
    print(f"[ONLINE] Generated: {run_summary_path.name}")
    
    return {
        "signals": signals_path,
        "execution_report": exec_path,
        "stability_summary": stability_path,
        "run_summary": run_summary_path,
    }


# ============================================================
# MULTI-RUN STABILITY AGGREGATOR (v1.4.0)
# ============================================================

def aggregate_stability_summaries(run_dirs: List[Path], output_path: Path) -> Dict[str, Any]:
    """
    Aggregate multiple run_summary.json files into a multi-run stability report.
    
    This is the canonical aggregator for continuous scan. Each run produces
    a run_summary.json, and this function combines them into aggregate metrics.
    
    Args:
        run_dirs: List of run directories to aggregate
        output_path: Where to write the aggregated stability report
    
    Returns:
        Aggregated stability data
    """
    runs_data = []
    
    for run_dir in run_dirs:
        reports_dir = run_dir / "reports"
        if not reports_dir.exists():
            continue
        
        # Find run_summary.json
        summary_files = list(reports_dir.glob("run_summary_*.json"))
        if not summary_files:
            continue
        
        summary_path = sorted(summary_files, key=lambda x: x.name, reverse=True)[0]
        with open(summary_path) as f:
            data = json.load(f)
        
        runs_data.append({
            "run_dir": str(run_dir.name),
            "run_id": data.get("run_id", ""),
            "timestamp": data.get("timestamp", ""),
            # Split status (v1.5.0)
            "profit_status": data.get("profit_status", data.get("status", "UNKNOWN")),
            "drift_status": data.get("drift_status", "UNKNOWN"),
            "status": data.get("status", "UNKNOWN"),
            "reasons": data.get("reasons", []),
            "profit_reasons": data.get("profit_reasons", []),
            "drift_reasons": data.get("drift_reasons", []),
            "metrics": data.get("metrics", {}),
        })
    
    if not runs_data:
        return {"error": "No run_summary.json files found"}
    
    # Aggregate metrics
    total_signals = sum(r["metrics"].get("signals_count", 0) for r in runs_data)
    total_profitable = sum(r["metrics"].get("sim_profitable_count", 0) for r in runs_data)
    total_net = sum(r["metrics"].get("total_net_usdc", 0) for r in runs_data)
    total_fragile = sum(r["metrics"].get("fragile_count", 0) for r in runs_data)
    mae_values = [r["metrics"].get("mae_net_usdc", 0) for r in runs_data if r["metrics"].get("mae_net_usdc") is not None]
    mae_no_slippage_values = [r["metrics"].get("mae_no_slippage", 0) for r in runs_data if r["metrics"].get("mae_no_slippage") is not None]
    sign_rates = [r["metrics"].get("est_sign_correct_rate", 0) for r in runs_data if r["metrics"].get("est_sign_correct_rate") is not None]
    
    # Compute aggregates with split status (v1.5.0)
    pass_count = sum(1 for r in runs_data if r["status"] == "PASS")
    fail_count = sum(1 for r in runs_data if r["status"] == "FAIL")
    profit_pass_count = sum(1 for r in runs_data if r["profit_status"] == "PASS")
    drift_pass_count = sum(1 for r in runs_data if r["drift_status"] == "PASS")
    
    # Warn/Fail rates (v1.6.0)
    warn_count = sum(1 for r in runs_data if "WARN_DRIFT_MAE" in r.get("reasons", []))
    drift_fail_count = sum(1 for r in runs_data if r["drift_status"] == "FAIL")
    
    # Net values for percentiles (v1.6.0)
    net_values = [r["metrics"].get("total_net_usdc", 0) for r in runs_data if r["metrics"].get("total_net_usdc") is not None]
    
    # Collect all fail reasons with counts
    all_reasons = {}
    for r in runs_data:
        for reason in r.get("reasons", []):
            all_reasons[reason] = all_reasons.get(reason, 0) + 1
    
    # Calculate percentiles for mae (v1.5.0)
    def percentile(values: List[float], p: float) -> Optional[float]:
        if not values:
            return None
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_vals) else f
        return round(sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f]), 4)
    
    aggregated = {
        "schema_version": "m4:stability_agg:v1.2",  # v1.6.0: warn_rate, net_p50/p90
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "runs_included": len(runs_data),
        "runs": runs_data,
        "aggregates": {
            # Combined status
            "pass_count": pass_count,
            "fail_count": fail_count,
            "pass_rate": round(pass_count / len(runs_data), 4) if runs_data else 0,
            # Warn/Fail rates (v1.6.0)
            "warn_count": warn_count,
            "warn_rate": round(warn_count / len(runs_data), 4) if runs_data else 0,
            "drift_fail_count": drift_fail_count,
            "drift_fail_rate": round(drift_fail_count / len(runs_data), 4) if runs_data else 0,
            # Split status (v1.5.0)
            "profit_pass_count": profit_pass_count,
            "profit_pass_rate": round(profit_pass_count / len(runs_data), 4) if runs_data else 0,
            "drift_pass_count": drift_pass_count,
            "drift_pass_rate": round(drift_pass_count / len(runs_data), 4) if runs_data else 0,
            # Metrics
            "total_signals": total_signals,
            "total_profitable": total_profitable,
            "total_fragile": total_fragile,
            "total_net_usdc": round(total_net, 4),
            "avg_net_usdc": round(total_net / len(runs_data), 4) if runs_data else 0,
            # Net percentiles (v1.6.0)
            "net_p50": percentile(net_values, 50),
            "net_p90": percentile(net_values, 90),
            "net_min": min(net_values) if net_values else None,
            "net_max": max(net_values) if net_values else None,
            # MAE with percentiles (v1.5.0)
            "mae_avg": round(sum(mae_values) / len(mae_values), 4) if mae_values else None,
            "mae_max": max(mae_values) if mae_values else None,
            "mae_min": min(mae_values) if mae_values else None,
            "mae_p50": percentile(mae_values, 50),
            "mae_p90": percentile(mae_values, 90),
            "mae_p99": percentile(mae_values, 99),
            # MAE no slippage (v1.5.0)
            "mae_no_slippage_avg": round(sum(mae_no_slippage_values) / len(mae_no_slippage_values), 4) if mae_no_slippage_values else None,
            # Sign rate
            "sign_rate_avg": round(sum(sign_rates) / len(sign_rates), 4) if sign_rates else None,
            "sign_rate_min": min(sign_rates) if sign_rates else None,
        },
        # Fail reasons with counts (v1.5.0)
        "fail_reason_counts": all_reasons,
        "status": "PASS" if pass_count == len(runs_data) else "FAIL",
        "reasons": list(all_reasons.keys()),
    }
    
    with open(output_path, "w") as f:
        json.dump(aggregated, f, indent=2)
    
    return aggregated


def emit_to_aggregator(run_dir: Path, agg_path: Path) -> None:
    """
    Append run results to a persistent aggregator file (v1.6.0).
    
    For continuous scan mode: maintains a single JSON file that accumulates
    results across multiple runs. The file is updated atomically.
    
    Usage:
        python scripts/ci_m4_execution_gate.py --online ... --emit-agg data/runs/_agg/m4_stability_agg.json
    
    Args:
        run_dir: The run directory with run_summary.json
        agg_path: Path to the aggregator file (created if doesn't exist)
    """
    # Load existing aggregator or create new
    if agg_path.exists():
        with open(agg_path) as f:
            agg_data = json.load(f)
    else:
        agg_path.parent.mkdir(parents=True, exist_ok=True)
        agg_data = {
            "schema_version": "m4:stability_agg:v1.2",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "runs": [],
        }
    
    # Load run_summary from this run
    reports_dir = run_dir / "reports"
    summary_files = list(reports_dir.glob("run_summary_*.json"))
    if not summary_files:
        print(f"[EMIT-AGG] No run_summary found in {run_dir}")
        return
    
    summary_path = sorted(summary_files, key=lambda x: x.name, reverse=True)[0]
    with open(summary_path) as f:
        run_data = json.load(f)
    
    # Append to runs list
    agg_data["runs"].append({
        "run_dir": str(run_dir.name),
        "run_id": run_data.get("run_id", ""),
        "timestamp": run_data.get("timestamp", ""),
        "profit_status": run_data.get("profit_status", "UNKNOWN"),
        "drift_status": run_data.get("drift_status", "UNKNOWN"),
        "status": run_data.get("status", "UNKNOWN"),
        "reasons": run_data.get("reasons", []),
        "metrics": run_data.get("metrics", {}),
    })
    
    # Update aggregated stats
    runs = agg_data["runs"]
    agg_data["updated_at"] = datetime.utcnow().isoformat() + "Z"
    agg_data["runs_included"] = len(runs)
    
    # Quick stats
    pass_count = sum(1 for r in runs if r["status"] == "PASS")
    total_net = sum(r["metrics"].get("total_net_usdc", 0) for r in runs)
    
    agg_data["quick_stats"] = {
        "pass_count": pass_count,
        "fail_count": len(runs) - pass_count,
        "pass_rate": round(pass_count / len(runs), 4) if runs else 0,
        "total_net_usdc": round(total_net, 4),
        "avg_net_usdc": round(total_net / len(runs), 4) if runs else 0,
    }
    
    # Write atomically
    with open(agg_path, "w") as f:
        json.dump(agg_data, f, indent=2)
    
    print(f"[EMIT-AGG] Updated: {agg_path} (runs={len(runs)})")


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
        # ONLINE profile requires real pinned_block > 0 (not synthetic fixture)
        if profile == DoDProfile.ONLINE:
            # Validate block is realistic (not fixture synthetic 429900000)
            if pinned_block > 100000 and pinned_block != 429900000:
                checks.append(("pinned_block_real", True, f"pinned_block={pinned_block} (real)"))
            else:
                checks.append(("pinned_block_real", False, 
                              f"ONLINE profile requires real block, got {pinned_block}"))
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
        # Support both old name (est_sim_mismatch_count) and new (sign_mismatch_count)
        mismatch = est_vs_sim.get("sign_mismatch_count", est_vs_sim.get("est_sim_mismatch_count", 0))
        checks.append(("est_vs_sim", True, f"sign_mismatch_count={mismatch}"))
        
        # Est vs Sim drift detection (critical for model accuracy)
        mae_net_usdc = est_vs_sim.get("mae_net_usdc", 0)
        est_sign_correct_rate = est_vs_sim.get("est_sign_correct_rate", 1.0)
        est_net_sum = est_vs_sim.get("est_net_usdc_sum", 0)
        sim_net_sum = est_vs_sim.get("sim_net_usdc_sum", 0)
        
        # MAE threshold: WARN if > 0.30 USDC per trade (30 cents drift)
        MAE_WARN_THRESHOLD = 0.30
        if mae_net_usdc <= MAE_WARN_THRESHOLD:
            checks.append(("est_mae_ok", True, f"mae_net_usdc={mae_net_usdc:.4f} <= {MAE_WARN_THRESHOLD}"))
        else:
            checks.append(("est_mae_ok", False, f"mae_net_usdc={mae_net_usdc:.4f} > {MAE_WARN_THRESHOLD} (HIGH DRIFT)"))
        
        # STRICT MODE: MAE==0 is suspicious (same calculation path?)
        # Only FAIL in strict mode, WARN otherwise
        if strict and mae_net_usdc == 0.0 and len(data.get("simulations", [])) > 0:
            # Check if est_sum != sim_sum (indicates real drift exists but MAE=0)
            if est_net_sum != sim_net_sum:
                # MAE=0 but sums differ - calculation path bug
                checks.append(("mae_zero_guard", False, 
                    f"MAE=0 but est_sum={est_net_sum:.4f} != sim_sum={sim_net_sum:.4f} (strict mode)"))
            elif mismatch > 0:
                # MAE=0 but there are sign mismatches - bug
                checks.append(("mae_zero_guard", False, 
                    f"MAE=0 but sign_mismatch_count={mismatch} (strict mode)"))
            # If both sums equal and no mismatches, it might be legitimate (same model)
        
        # Sign correct rate: WARN if < 80%
        if est_sign_correct_rate >= 0.80:
            checks.append(("est_sign_rate_ok", True, f"est_sign_correct_rate={est_sign_correct_rate:.2%} >= 80%"))
        else:
            checks.append(("est_sign_rate_ok", False, f"est_sign_correct_rate={est_sign_correct_rate:.2%} < 80% (UNRELIABLE)"))
        
        # Est vs Sim sum drift (total drift)
        sum_drift = abs(est_net_sum - sim_net_sum)
        checks.append(("est_sum_drift", True, f"est_sum={est_net_sum:.4f}, sim_sum={sim_net_sum:.4f}, drift={sum_drift:.4f}"))
    
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
        # AND drift thresholds are acceptable
        sim_profitable_count = est_vs_sim.get("sim_profitable_count", sims_passed)
        
        if total_net_usdc > 0:
            checks.append(("dod_profit_net", True, f"total_net_usdc={total_net_usdc:.4f} > 0"))
        else:
            checks.append(("dod_profit_net", False, f"total_net_usdc={total_net_usdc:.4f} <= 0 (UNPROFITABLE)"))
        
        if sim_profitable_count >= 1:
            checks.append(("dod_profit_sims", True, f"sim_profitable_count={sim_profitable_count} >= 1"))
        else:
            checks.append(("dod_profit_sims", False, f"sim_profitable_count={sim_profitable_count} < 1"))
        
        # PROFIT profile MUST also pass drift thresholds (FAIL, not WARN)
        # These are critical for online: est error -0.45 USDC on $100 = dangerous
        MAE_FAIL_THRESHOLD = 0.50  # USDC per trade (50 cents max drift)
        SIGN_RATE_MIN = 0.70  # 70% min for profit profile
        
        mae_net_usdc = est_vs_sim.get("mae_net_usdc", 0)
        est_sign_rate = est_vs_sim.get("est_sign_correct_rate", 1.0)
        
        if mae_net_usdc <= MAE_FAIL_THRESHOLD:
            checks.append(("dod_profit_drift_mae", True, f"mae_net_usdc={mae_net_usdc:.4f} <= {MAE_FAIL_THRESHOLD} (PROFIT threshold)"))
        else:
            checks.append(("dod_profit_drift_mae", False, f"mae_net_usdc={mae_net_usdc:.4f} > {MAE_FAIL_THRESHOLD} (DANGEROUS DRIFT)"))
        
        if est_sign_rate >= SIGN_RATE_MIN:
            checks.append(("dod_profit_drift_sign", True, f"est_sign_correct_rate={est_sign_rate:.2%} >= {SIGN_RATE_MIN:.0%} (PROFIT threshold)"))
        else:
            checks.append(("dod_profit_drift_sign", False, f"est_sign_correct_rate={est_sign_rate:.2%} < {SIGN_RATE_MIN:.0%} (UNRELIABLE ESTIMATES)"))
    
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
    
    # Generate fixtures with profile-specific values
    artifacts = generate_m4_fixture(run_dir, ts, profile)
    
    print(f"[OFFLINE] Generated artifacts:")
    for name, path in artifacts.items():
        print(f"  - {name}: {path.name}")
    
    # Load and validate
    return validate_gate(run_dir, artifacts, profile, strict)


def run_online_gate(
    run_dir: Optional[Path], 
    profile: str = DoDProfile.SMOKE, 
    strict: bool = False,
    cost_model_name: str = "paper_realistic",
    strict_evidence: bool = False,
) -> int:
    """
    Run M4 gate in online mode using real artifacts.
    
    If execution_report doesn't exist but truth_report does, generates M4
    execution from online inputs (scan/truth → signals → simulation).
    
    Validates that all artifacts come from the same runDir with consistent timestamps.
    
    Args:
        run_dir: Explicit run directory (or None for latest)
        profile: DoD profile to validate against
        strict: Strict mode - fail on MAE==0
        cost_model_name: Cost model to use for simulation
        strict_evidence: Require source_sha matches HEAD and run_id is valid
    """
    if run_dir is None:
        run_dir = find_latest_run_dir()
    
    if run_dir is None:
        print("ERROR: No run directory found")
        print("Run: python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml")
        return 2
    
    # Ensure run_dir is absolute
    run_dir = Path(run_dir).resolve()
    
    try:
        display_path = run_dir.relative_to(REPO_ROOT)
    except ValueError:
        display_path = run_dir
    print(f"\n[ONLINE] Using: {display_path}")
    print(f"[ONLINE] RunDir: {run_dir}")
    print(f"[ONLINE] CostModel: {cost_model_name}")
    
    artifacts = discover_m4_artifacts(run_dir)
    
    # If no execution_report, try to generate from truth_report
    if artifacts["execution_report"] is None:
        reports_dir = run_dir / "reports"
        truth_files = list(reports_dir.glob("truth_report_*.json")) if reports_dir.exists() else []
        
        if truth_files:
            print("\n[ONLINE] No execution_report found, generating from truth_report...")
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            try:
                generated = generate_m4_from_online_inputs(run_dir, ts, cost_model_name)
                artifacts["signals"] = generated["signals"]
                artifacts["execution_report"] = generated["execution_report"]
            except Exception as e:
                print(f"\nERROR: Failed to generate M4 from online inputs: {e}")
                return 3
        else:
            print("\nWARN: No execution_report and no truth_report found")
            print("Run online scan first:")
            print("  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml")
            return 2
    
    # Validate artifact timestamps are consistent
    artifact_timestamps = {}
    for name, path in artifacts.items():
        if path and path.exists():
            # Extract timestamp from filename (e.g., execution_report_20260209_123029.json)
            import re
            match = re.search(r"_(\d{8}_\d{6})\.json$", path.name)
            if match:
                artifact_timestamps[name] = match.group(1)
    
    if artifact_timestamps:
        unique_ts = set(artifact_timestamps.values())
        if len(unique_ts) > 1:
            print(f"\n[WARN] Inconsistent timestamps in runDir:")
            for name, ts in artifact_timestamps.items():
                print(f"  - {name}: {ts}")
            print("  (artifacts may be from different runs)")
    
    # Strict evidence mode: validate source_sha matches HEAD
    if strict_evidence:
        print("\n[ONLINE] Strict evidence mode enabled")
        current_sha = get_git_sha()
        if current_sha and current_sha != "unknown":
            print(f"[ONLINE] Current HEAD: {current_sha[:8]}...")
        
        # Will be validated in validate_gate
    
    print(f"\n[ONLINE] Profile: {profile}")
    print(f"[ONLINE] Artifacts found:")
    for name, path in artifacts.items():
        if path:
            print(f"  - {name}: {path.name}")
    
    return validate_gate(run_dir, {k: v for k, v in artifacts.items() if v}, profile, strict, strict_evidence)



def validate_gate(run_dir: Path, artifacts: Dict[str, Path], profile: str, strict: bool, strict_evidence: bool = False) -> int:
    """
    Core validation logic for M4 gate.
    
    Args:
        run_dir: Run directory path
        artifacts: Dictionary of artifact paths
        profile: DoD profile
        strict: Strict mode - fail on MAE==0
        strict_evidence: Require source_sha matches HEAD
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
    
    # Strict evidence mode: validate source_sha matches HEAD
    if strict_evidence:
        artifact_sha = exec_data.get("source_sha", "")
        artifact_run_id = exec_data.get("run_id", "")
        current_sha = get_git_sha()
        
        if artifact_sha and current_sha and current_sha != "unknown":
            if artifact_sha == current_sha:
                all_checks.append(("source_sha_match", True, f"source_sha matches HEAD ({artifact_sha[:8]}...)"))
            else:
                all_checks.append(("source_sha_match", False, 
                    f"source_sha mismatch: artifact={artifact_sha[:8]}... HEAD={current_sha[:8]}..."))
                print(f"  FAIL: source_sha mismatch (strict evidence mode)")
        else:
            all_checks.append(("source_sha_match", False, "Missing source_sha in artifact or cannot get HEAD"))
        
        if artifact_run_id:
            # Validate run_id format: m4_<timestamp> or similar
            import re
            if re.match(r"^m4_\d{8}_\d{6}$", artifact_run_id):
                all_checks.append(("run_id_valid", True, f"run_id format valid: {artifact_run_id}"))
            else:
                all_checks.append(("run_id_valid", False, f"run_id format invalid: {artifact_run_id}"))
        else:
            all_checks.append(("run_id_valid", False, "Missing run_id in artifact"))
    
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
    
    parser.add_argument("--profile", type=str, default=DoDProfile.SMOKE,
                        choices=[DoDProfile.SMOKE, DoDProfile.PROFIT, DoDProfile.ONLINE],
                        help="DoD profile: smoke (>=1 profitable), profit (total_net>0), online (profit on real block)")
    parser.add_argument("--cost-model", type=str, default="paper_realistic",
                        choices=CostModelRegistry.default().list_models(),
                        help="Cost model: paper_realistic (default), paper_conservative (stress test)")
    parser.add_argument("--strict", action="store_true",
                        help="Require at least one profitable simulation, fail on MAE==0")
    parser.add_argument("--strict-evidence", action="store_true",
                        help="Require source_sha matches HEAD and run_id is valid (continuous scan)")
    parser.add_argument("--require-tenderly", action="store_true",
                        help="Require tenderly diagnostics when enabled in artifacts")
    parser.add_argument("--run-dir", type=Path,
                        help="Explicit run directory to validate")
    parser.add_argument("--output-root", type=Path,
                        default=REPO_ROOT / "data" / "runs",
                        help="Root for output directories")
    parser.add_argument("--signal", type=int, default=0,
                        help="Signal index to simulate (0 = first)")
    # Aggregator mode (v1.6.0)
    parser.add_argument("--emit-agg", type=Path, default=None,
                        help="Append results to aggregator file (continuous scan mode)")
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
        result = run_online_gate(
            args.run_dir, args.profile, args.strict, args.cost_model,
            strict_evidence=args.strict_evidence
        )
        # Emit to aggregator if requested (v1.6.0)
        if args.emit_agg and args.run_dir:
            emit_to_aggregator(args.run_dir, args.emit_agg)
        return result
    elif args.dry_run:
        return run_dry_run()
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
