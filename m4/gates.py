"""
M4 Gates Module

Core gate logic for M4 execution validation.

Functions:
- run_offline_gate(): Run M4 gate with synthetic fixtures (no RPC)
- run_online_gate(): Run M4 gate with real artifacts  
- validate_gate(): Core validation logic for M4 artifacts

Usage:
    from m4.gates import run_offline_gate, run_online_gate, validate_gate
    
    # Offline gate
    exit_code = run_offline_gate(output_root, profile='smoke')
    
    # Online gate
    exit_code = run_online_gate(run_dir, profile='profit')

Dependencies (not yet extracted):
- validate_execution_report: Validates execution_report fields
- validate_simulations: Validates individual simulation fields
- validate_block_consistency: Validates pinned_block consistency

NOTE: This module relies on functions still in ci_m4_execution_gate.py.
The gate functions here are the extracted interfaces; full decoupling
requires moving the validation helpers as well.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import from m4 modules
from .policy import (
    CostModelConfig,
    CostModelRegistry,
    DoDProfile,
    FailReason,
    Thresholds,
    get_cost_model,
)
from .evidence import get_git_context, get_git_head_sha
from .rolling_store import emit_to_aggregator_light, ensure_rolling_agg_exists, reset_rolling_window
from .discovery import find_latest_run_dir, discover_m4_artifacts
from .fixtures import generate_m4_fixture, generate_m4_from_online_inputs

# Import reject reasons for simulation validation
from core.reject_reasons import SimRejectReason

# Repository root - assumes this file is at m4/gates.py
REPO_ROOT = Path(__file__).resolve().parent.parent


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
# VALIDATION HELPERS
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
    
    elif profile == DoDProfile.PROFIT or profile == DoDProfile.ONLINE:
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
    
    Creates synthetic fixtures and validates them against the specified profile.
    No RPC or external dependencies required.
    
    Args:
        output_root: Root directory for output (e.g., data/runs)
        profile: DoD profile to validate against (smoke, profit, online)
        strict: Strict mode - fail on MAE==0
        
    Returns:
        Exit code: 0=PASS, 1=FAIL, 2=NO_SIGNALS, 3=SIM_FAILED
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
    artifact_mode: str = "rolling",
    emit_agg: Optional[Path] = None,
    reset_window: bool = False,
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
        artifact_mode: "rolling" (default) or "full" 
        emit_agg: Path to emit aggregator (optional)
        reset_window: If True, delete aggregator before emitting
        
    Returns:
        Exit code: 0=PASS, 1=FAIL, 2=NO_SIGNALS, 3=SIM_FAILED
    """
    # Incident bundle persistence and retention
    def persist_incident_bundle(run_id, bundle_dict):
        incident_dir = REPO_ROOT / "data" / "runs" / "_incidents" / run_id
        incident_dir.mkdir(parents=True, exist_ok=True)
        for k, v in bundle_dict.items():
            path = incident_dir / f"{k}.json"
            with open(path, "w") as f:
                json.dump(v, f, indent=2)
        return incident_dir

    def cleanup_incidents(max_n=50, max_days=7):
        incidents_root = REPO_ROOT / "data" / "runs" / "_incidents"
        if not incidents_root.exists():
            return
        dirs = sorted([d for d in incidents_root.iterdir() if d.is_dir()], key=lambda x: x.stat().st_mtime, reverse=True)
        # Remove by count
        for d in dirs[max_n:]:
            for f in d.glob("*.json"):
                f.unlink()
            d.rmdir()
        # Remove by TTL
        now = datetime.utcnow()
        for d in dirs:
            age_days = (now - datetime.utcfromtimestamp(d.stat().st_mtime)).days
            if age_days > max_days:
                for f in d.glob("*.json"):
                    f.unlink()
                d.rmdir()

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

    # Load run_summary
    reports_dir = run_dir / "reports"
    summary_files = list(reports_dir.glob("run_summary_*.json"))
    if not summary_files:
        print(f"No run_summary found in {run_dir}")
        return 2
    summary_path = sorted(summary_files, key=lambda x: x.name, reverse=True)[0]
    with open(summary_path) as f:
        run_summary = json.load(f)

    if artifact_mode == "rolling":
        # Determine run mode (FIXTURE_OFFLINE, SMOKE_SIMULATOR = offline; REAL_ONLINE, ONLINE = online)
        run_mode = run_summary.get("inputs", {}).get("run_mode", "") or run_summary.get("run_mode", "")
        
        # Fallback: try to get from truth_report
        if not run_mode:
            truth_files = list((run_dir / "reports").glob("truth_report_*.json"))
            if truth_files:
                with open(sorted(truth_files)[-1]) as f:
                    truth_data = json.load(f)
                run_mode = truth_data.get("run_mode", "")
        
        # Fallback: infer from run_dir name
        if not run_mode:
            run_dir_name = run_dir.name.lower()
            if "offline" in run_dir_name or "fixture" in run_dir_name:
                run_mode = "FIXTURE_OFFLINE"
            elif "smoke" in run_dir_name or "simulator" in run_dir_name:
                run_mode = "SMOKE_SIMULATOR"
            else:
                run_mode = "UNKNOWN"
        
        run_mode_upper = run_mode.upper()
        # Offline patterns: FIXTURE, SMOKE, SIMULATOR
        is_offline = any(x in run_mode_upper for x in ["FIXTURE", "SMOKE", "SIMULATOR", "OFFLINE"])
        # Online patterns: explicitly REAL or ONLINE without OFFLINE
        is_online = ("REAL" in run_mode_upper) and not is_offline
        
        rolling_dir = REPO_ROOT / "data" / "runs" / "_rolling"
        rolling_dir.mkdir(parents=True, exist_ok=True)
        
        # Fixed path for rolling agg (always exists)
        agg_path = rolling_dir / "m4_stability_agg.json"
        
        # Update evidence with real git HEAD and dirty status (v1.9.1)
        git_ctx = get_git_context()
        git_sha = git_ctx["code_sha"]
        code_dirty = git_ctx["code_dirty"]
        
        if "evidence" in run_summary:
            run_summary["evidence"]["current_sha"] = git_sha
            
            # v1.9.3: Removed SHA_MISMATCH check - source_sha is now deprecated
            # Only check for dirty worktree
            evidence_issues = run_summary["evidence"].get("issues", [])
            
            # Remove any old SHA_MISMATCH issues (v1.9.3 cleanup)
            evidence_issues = [i for i in evidence_issues if not i.startswith("SHA_MISMATCH")]
            
            if code_dirty is True and "DIRTY_WORKTREE_PRECOMMIT" not in evidence_issues:
                evidence_issues.append("DIRTY_WORKTREE_PRECOMMIT")
            
            run_summary["evidence"]["issues"] = evidence_issues
            run_summary["evidence"]["ok"] = len(evidence_issues) == 0
        
        # Update run_context with current git state
        if "run_context" in run_summary:
            run_summary["run_context"]["code_sha"] = git_sha
            run_summary["run_context"]["code_dirty"] = code_dirty if code_dirty is not None else False
            run_summary["run_context"]["code_desc"] = git_ctx["code_desc"]
        
        # Determine status considering NO_DATA
        status = run_summary.get("status", "UNKNOWN")
        reasons = run_summary.get("reasons", [])
        signals_count = run_summary.get("metrics", {}).get("signals_count", 0)
        pinned_block = run_summary.get("inputs", {}).get("pinned_block", 0)
        
        # NO_DATA status for empty runs - clean semantic noise
        if signals_count == 0:
            status = "NO_DATA"
            # Remove all FAIL_* from reasons - they are meaningless for NO_DATA
            reasons = [r for r in reasons if not r.startswith("FAIL_")]
            if "NO_DATA" not in reasons:
                reasons = ["NO_DATA"] + reasons
            # Keep only relevant warnings
            reasons = [r for r in reasons if r in ["NO_DATA", "WARN_LOW_SAMPLE"]]
            
            run_summary["status"] = status
            run_summary["reasons"] = reasons
            run_summary["profit_status"] = "NO_DATA"
            run_summary["drift_status"] = "NO_DATA"
            # Clean profit/drift reasons too
            run_summary["profit_reasons"] = ["NO_DATA"]
            run_summary["drift_reasons"] = ["NO_DATA"]
        
        # Add block_is_synthetic flag for offline
        if "inputs" in run_summary:
            run_summary["inputs"]["block_is_synthetic"] = is_offline or pinned_block < 1000
        
        is_fail = status == "FAIL" or any(r.startswith("FAIL_") for r in reasons)
        is_incident = is_fail  # NO_DATA is not incident
        
        # Remove source_* filenames in rolling mode
        if "inputs" in run_summary and isinstance(run_summary["inputs"], dict):
            for k in list(run_summary["inputs"].keys()):
                if k.startswith("source_"):
                    run_summary["inputs"][k] = None
        
        # v1.9.7: Reset window with archive (archives old data before creating fresh)
        if reset_window and agg_path.exists():
            reset_rolling_window(agg_path, reason="cli_reset_window")
        
        # STEP 1: Emit to aggregator FIRST (always)
        agg_data = emit_to_aggregator_light(run_summary, agg_path)
        
        # STEP 2: Write run_summary_latest (only for ONLINE, or if no online exists)
        if is_offline:
            # Offline writes to separate file, does NOT overwrite online latest
            run_summary_path = rolling_dir / "run_summary_latest_offline.json"
            latest_file = "_latest_offline.json"
        else:
            run_summary_path = rolling_dir / "run_summary_latest.json"
            latest_file = "_latest.json"
        
        with open(run_summary_path, "w") as f:
            json.dump(run_summary, f, indent=2)
        
        # STEP 3: Incident bundle persistence (only for real incidents)
        incident_dir = None
        if is_incident:
            bundle_dict = {}
            for k in ["run_summary", "execution_report", "truth_report", "signals", "scan"]:
                if k in artifacts:
                    val = artifacts[k]
                    if isinstance(val, dict):
                        bundle_dict[k] = val
                    elif isinstance(val, Path) and val.exists():
                        with open(val) as f:
                            bundle_dict[k] = json.load(f)
            incident_dir = persist_incident_bundle(
                run_summary.get("run_id", datetime.now(timezone.utc).strftime("incident_%Y%m%d_%H%M%S")), 
                bundle_dict
            )
            cleanup_incidents(max_n=50, max_days=7)
        
        # STEP 4: Update _latest.json LAST (always consistent)
        latest_path = rolling_dir / latest_file
        
        # Compute relative paths from rolling_dir
        def rel_path(p: Path) -> str:
            try:
                return str(p.relative_to(rolling_dir.parent))  # Relative to data/runs
            except ValueError:
                return p.name  # Fallback to just filename
        
        # v1.9.6: Use agg_reasons from aggregator (computed in rolling_store)
        agg_reasons = agg_data.get("agg_reasons", [])
        
        # Fallback: add warmup reasons if not already present
        rolling_window = agg_data.get("rolling_window", {})
        if rolling_window.get("in_warmup", True) and not agg_reasons:
            if agg_data.get("runs_in_window", 0) < rolling_window.get("min_runs", 5):
                agg_reasons.append("WARMUP_MIN_RUNS")
            if agg_data.get("quick_stats", {}).get("total_signals", 0) < rolling_window.get("min_signals", 10):
                agg_reasons.append("WARMUP_MIN_SIGNALS")
        
        # Get git context
        git_ctx = get_git_context()
        head_sha = get_git_head_sha()
        
        # v1.9.4: Compute agg lag
        now_utc = datetime.now(timezone.utc)
        agg_updated_at = agg_data.get("updated_at")
        agg_lag_seconds = None
        if agg_updated_at:
            try:
                from datetime import datetime as dt
                if agg_updated_at.endswith('Z'):
                    agg_updated_at = agg_updated_at[:-1] + '+00:00'
                agg_ts = dt.fromisoformat(agg_updated_at)
                agg_lag_seconds = round((now_utc - agg_ts).total_seconds(), 1)
            except Exception:
                pass
        
        latest_data = {
            "schema_version": "m4:latest:v1.9",  # v1.9.7: unified thresholds, fragile_p50
            "updated_at": now_utc.isoformat(),
            # v1.9.2: Clear SHA naming
            "latest_run_code_sha": git_ctx["code_sha"],  # SHA of code that ran this scan
            "attached_evidence_sha": None,  # null until attach_evidence.py sets it
            "run_context": {
                "code_sha": git_ctx["code_sha"],
                "code_dirty": git_ctx["code_dirty"] if git_ctx["code_dirty"] is not None else False,
                "code_desc": git_ctx["code_desc"],
                "evidence_sha": None,  # null until attach_evidence sets it
            },
            "latest_mode": "ONLINE" if is_online else "OFFLINE",
            "latest_kind": "INCIDENT" if is_incident else "NORMAL",
            "run_status": status,
            "threshold_profile_name": profile,
            "agg_status": agg_data.get("agg_status", "UNKNOWN"),
            "agg_reasons": agg_reasons if agg_reasons else [],
            "quality_warnings": agg_data.get("quality_warnings", []),  # v1.9.5
            "policy_version": agg_data.get("policy_version", "unknown"),  # v1.9.5
            "agg_updated_at": agg_updated_at,  # v1.9.4: agg last update
            "agg_lag_seconds": agg_lag_seconds,  # v1.9.4: lag detection
            "runs_in_window": agg_data.get("runs_in_window", 0),
            "runs_by_code_sha": agg_data.get("runs_by_code_sha", {}),  # v1.9.4: breakdown
            "in_warmup": agg_data.get("rolling_window", {}).get("in_warmup", True),
            "total_signals_in_window": agg_data.get("quick_stats", {}).get("total_signals", 0),
            "quick_stats": agg_data.get("quick_stats", {}),  # v1.9.5: full stats visibility
            "paths": {
                "run_summary_latest": rel_path(run_summary_path),
                "rolling_agg": rel_path(agg_path),
                "last_incident": rel_path(incident_dir / "run_summary.json") if incident_dir else None,
            },
        }
        with open(latest_path, "w") as f:
            json.dump(latest_data, f, indent=2)
        
        print(f"[ROLLING] Mode: {'ONLINE' if is_online else 'OFFLINE'}, Status: {status}")
        print(f"[ROLLING] Updated: {run_summary_path.name}")
        print(f"[ROLLING] Aggregator: {agg_path.name} (runs={agg_data.get('runs_in_window', 0)})")
        print(f"[ROLLING] Latest: {latest_file}")
        if is_incident:
            print(f"[ROLLING] Incident: {incident_dir}")
        return 0
    else:
        # Legacy full mode
        print("[FULL] Legacy artifact mode: all per-run artifacts written.")
        return validate_gate(run_dir, {k: v for k, v in artifacts.items() if v}, profile, strict, strict_evidence)


def validate_gate(
    run_dir: Path, 
    artifacts: Dict[str, Path], 
    profile: str, 
    strict: bool, 
    strict_evidence: bool = False
) -> int:
    """
    Core validation logic for M4 gate.
    
    Validates execution_report, simulations, and block consistency.
    
    Args:
        run_dir: Run directory path
        artifacts: Dictionary of artifact paths
        profile: DoD profile
        strict: Strict mode - fail on MAE==0
        strict_evidence: Require source_sha matches HEAD
        
    Returns:
        Exit code: 0=PASS, 1=FAIL
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
