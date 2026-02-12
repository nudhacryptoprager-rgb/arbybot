"""
M4 Fixture Generation Module

Creates synthetic/real execution fixtures for M4 gate validation.

Functions:
- generate_m4_fixture(): Generate synthetic M4 fixtures for offline testing
- generate_m4_from_online_inputs(): Generate M4 artifacts from online scan/truth inputs

Usage:
    from m4.fixtures import generate_m4_fixture, generate_m4_from_online_inputs
    
    # Offline fixtures
    artifacts = generate_m4_fixture(run_dir, timestamp, profile='smoke')
    
    # Online fixtures from truth_report
    artifacts = generate_m4_from_online_inputs(run_dir, timestamp, cost_model_name='paper_realistic')
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# Import from m4 policy module
from .policy import (
    CostModelConfig,
    DoDProfile,
    FailReason,
    Thresholds,
    get_cost_model,
    DEFAULT_CHAIN_ID,
    DEFAULT_PINNED_BLOCK,
    POLICY_VERSION,
)

# Import from m4 evidence module
from .evidence import get_git_context

# Import canonical reject reasons
from core.reject_reasons import SimRejectReason

# Repository root - assumes this file is at m4/fixtures.py
REPO_ROOT = Path(__file__).resolve().parent.parent


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
                 
    Returns:
        Dict with paths to generated artifacts:
            - signals: Path to signals_<ts>.json
            - execution_report: Path to execution_report_<ts>.json
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
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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


def generate_m4_from_online_inputs(
    run_dir: Path, 
    ts: str,
    cost_model_name: str = "paper_realistic",
    profile: str = "smoke",
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
        profile: DoD profile for threshold evaluation (default: smoke)
        
    Returns:
        Dict with paths to generated signals and execution_report
        
    Raises:
        FileNotFoundError: If no truth_report found in run_dir
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
    
    # Compute aggregates by pair and route for diversity tracking (v1.9.9)
    signals_by_pair: Dict[str, int] = {}
    signals_by_route: Dict[str, int] = {}
    for sig in m4_signals:
        pair = sig.get("pair", "UNKNOWN")
        signals_by_pair[pair] = signals_by_pair.get(pair, 0) + 1
        route = f"{sig.get('buy_dex', '?')}->{sig.get('sell_dex', '?')}"
        signals_by_route[route] = signals_by_route.get(route, 0) + 1
    
    # Write M4 signals
    signals_path = reports_dir / f"signals_{ts}.json"
    signals_data = {
        "schema_version": "m4:signals:v1.2",  # Bumped for source_sha/run_id
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
    
    # Count fragile signals: est_net < slippage + gas (at risk of sign flip) (v1.5.0)
    # Fragile = at risk of sign flip due to cost model changes
    fragile_count = 0
    fragile_signals = []
    for sig in m4_signals:
        est_net = sig.get("truth_net_usdc", 0)
        size_usd = sig.get("size_usd", 0)
        slippage_usdc = size_usd * cost_model.slippage_bps / 10000
        gas_usdc = cost_model.gas_usd
        # Fragile: est_net < total_costs, so sim could flip to negative
        if est_net < slippage_usdc + gas_usdc and est_net > 0:
            fragile_count += 1
            fragile_signals.append({
                "signal_id": sig.get("signal_id", "unknown"),
                "est_net_usdc": est_net,
                "cost_margin_usdc": round(slippage_usdc + gas_usdc - est_net, 4),
                "reason": "est_net < slippage + gas"
            })
    
    # v1.9.7: Unified sample threshold
    # signals < MIN_SIGNALS_FOR_PASS (5) → NO_DATA (not counted in pass_rate)
    is_low_sample = len(m4_signals) < Thresholds.MIN_SIGNALS_FOR_PASS
    
    # v1.9.7: Quality warnings for run-level issues (structured)
    quality_warnings = []
    quality_reasons = []  # Canonical tokens for reasons array
    
    if is_low_sample and len(m4_signals) > 0:
        # Has signals but too few for statistical validity
        quality_warnings.append(f"LOW_SAMPLE({len(m4_signals)}<{Thresholds.MIN_SIGNALS_FOR_PASS})")
        quality_reasons.append(FailReason.WARN_LOW_SAMPLE)
    
    # v1.10.0: FAIL_FRAGILE_HIGH when fragile_rate violates limits
    # Priority: profile.fragile_rate_max (e.g., 0.20 for profit) → FAIL
    # Fallback: universal threshold 0.50 → FAIL (not just WARN)
    frag_rate = fragile_count / len(m4_signals) if m4_signals else 0
    from m4.policy import get_profile
    try:
        profile_config = get_profile(profile)
        fragile_rate_max = profile_config.fragile_rate_max
    except (ValueError, NameError):
        fragile_rate_max = 0.50  # v1.10.0: universal fail threshold (was 1.0)
    
    if not is_low_sample and frag_rate > fragile_rate_max:
        # v1.10.0: Hard filter - profile-specific or universal 0.50
        quality_warnings.append(f"FAIL_FRAGILE_RATE({frag_rate:.2f}>{fragile_rate_max})")
        quality_reasons.append("FAIL_FRAGILE_HIGH")
    elif not is_low_sample and frag_rate >= 0.30:
        # v1.10.0: WARN at 0.30 (early warning, before 0.50 cutoff)
        quality_warnings.append(f"WARN_FRAGILE_RATE({frag_rate:.2f}>=0.30)")
        quality_reasons.append("WARN_FRAGILE_ELEVATED")
    
    # v1.10.0: Determine quality_status (contract alignment)
    # NO_DATA if signals < MIN_SIGNALS_FOR_PASS (unified threshold)
    # FAIL_QUALITY if any FAIL_* reason present
    # WARN_QUALITY if any WARN_* reason present
    if len(m4_signals) < Thresholds.MIN_SIGNALS_FOR_PASS:
        quality_status = "NO_DATA"  # Not enough for statistical evaluation
    elif any(r.startswith("FAIL_") for r in quality_reasons):
        quality_status = "FAIL_QUALITY"  # v1.10.0: explicit FAIL_* check
    elif any("HIGH" in w for w in quality_warnings):
        quality_status = "FAIL_QUALITY"  # v1.9.7: HIGH fragile rate
    elif quality_warnings or quality_reasons:
        quality_status = "WARN_QUALITY"
    else:
        quality_status = "PASS"
    
    # Combined status with policy
    # v1.10.0: quality_status=FAIL_QUALITY now reflects in combined_status
    all_reasons = profit_reasons + drift_reasons + quality_reasons
    
    if len(m4_signals) < Thresholds.MIN_SIGNALS_FOR_PASS:
        combined_status = "NO_DATA"  # v1.9.7: unified - not enough signals
    elif profit_status == "FAIL" or drift_status == "FAIL":
        combined_status = "FAIL"
    elif quality_status == "FAIL_QUALITY":
        combined_status = "FAIL_QUALITY"  # v1.10.0: explicit quality fail (was WARN)
    elif quality_status == "WARN_QUALITY":
        combined_status = "WARN"  # v1.10.0: quality warn → WARN (not PASS)
    else:
        combined_status = "PASS"
    
    stability_data = {
        "schema_version": "m4:stability:v1.2",  # Bumped for split status
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
    
    # v2.0: Get timestamp-based provenance (SHA tracking removed)
    git_ctx = get_git_context()
    run_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    # v2.0: Evidence validation based on timestamp consistency only
    evidence_issues = []
    
    # Check timestamp deltas
    truth_ts_str = truth_data.get("timestamp", "")
    try:
        if truth_ts_str:
            # Parse truth timestamp
            truth_ts = datetime.fromisoformat(truth_ts_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            delta_seconds = abs((now - truth_ts).total_seconds())
            if delta_seconds > 300:  # 5 minutes tolerance
                evidence_issues.append(f"timestamp_delta_high: {delta_seconds:.0f}s")
    except Exception:
        pass
    
    evidence_ok = len(evidence_issues) == 0
    
    # v2.0: Dirty proof check removed - SHA tracking disabled
    # Provenance is now based on run_timestamp only
    is_dirty_proof = False
    
    run_summary_data = {
        "schema_version": "m4:run_summary:v2.0",  # v2.0: timestamp-based provenance
        "policy_version": POLICY_VERSION,
        "timestamp": run_timestamp,
        "run_id": run_id,
        # v2.0.0: run_context with timestamp-based provenance (SHA tracking removed)
        "run_context": {
            "run_timestamp": run_timestamp,
            "code_identity": f"ts:{run_timestamp}",  # v2.0: deterministic code ref
            "code_sha": None,  # v2.0: deprecated
            "code_dirty": None,  # v2.0: deprecated
            "code_desc": None,  # v2.0: deprecated
            "evidence_sha": None,  # v2.0: deprecated
        },
        "inputs": {
            "run_mode": source_run_mode,
            "run_dir_rel": str(run_dir.relative_to(REPO_ROOT)) if run_dir.is_relative_to(REPO_ROOT) else run_dir.name,  # v1.9.6: relative canonical
            "run_dir_name": run_dir.name,  # v1.9.4: basename for portability
            "run_dir_abs": str(run_dir),  # v1.9.6: debug only
            "truth_report": truth_path.name,
            "pinned_block": source_block,
            "chain_id": chain_id,
            "cost_model": cost_model.name,
            # v1.9.9: pairs/routes for diversity tracking
            "pairs": list(signals_by_pair.keys()),
            "routes": list(signals_by_route.keys()),
        },
        "metrics": {
            "signals_count": len(m4_signals),
            "sim_profitable_count": sim_profitable_count,
            "total_net_usdc": round(total_net_usdc, 4),
            "mae_net_usdc": mae_net_usdc,
            "est_sign_correct_rate": est_sign_correct_rate,
            "sign_mismatch_count": sign_mismatch_count,
            "fragile_count": fragile_count,
            "fragile_rate": round(frag_rate, 4),  # v1.9.6: use computed frag_rate
        },
        "thresholds": {
            "policy_version": POLICY_VERSION,  # v1.9.5: provenance
            "threshold_profile_name": "profit",  # v1.9.6: default profile
            "mae_warn": Thresholds.MAE_WARN,
            "mae_fail": Thresholds.MAE_FAIL,
            "sign_rate_min": Thresholds.SIGN_RATE_MIN,
            "min_signals_for_pass": Thresholds.MIN_SIGNALS_FOR_PASS,  # v1.9.7: unified
            "fragile_rate_warn": 0.50,  # v1.9.7: run-level fragile gate
        },
        # Split status (v1.5.0)
        "profit_status": profit_status,
        "profit_reasons": profit_reasons,
        "drift_status": drift_status,
        "drift_reasons": drift_reasons,
        # v1.9.6: quality_status (new canonical field)
        "quality_status": quality_status,
        "quality_reasons": quality_reasons,
        # Combined status (backwards compat)
        "status": combined_status,
        "reasons": all_reasons,
        # v1.9.5: Quality warnings (separate from status reasons)
        "quality_warnings": quality_warnings,
        # Evidence validation
        "evidence": {
            "ok": evidence_ok,
            "issues": evidence_issues,
        },
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
