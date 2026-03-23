#!/usr/bin/env python3
# PATH: scripts/ci_full_pipeline.py
"""
Full CI pipeline for ARBY.

MODES:
  --mode ci   : Offline only (fixtures), no RPC required - DEFAULT
  --mode e2e  : Online + offline (requires secrets)

Runs all gates in sequence:
1. pytest -q (unit tests)
2. ci_m5_0_gate.py --offline --strict
3. M5 gate: SKIPPED in CI mode (requires runDir), RUN in E2E mode
4. ci_m4_execution_gate.py --offline --profile smoke

Exit codes:
  0 = All gates PASS
  1 = pytest failed
  2 = M5_0 gate failed
  3 = M5 gate failed (E2E only)
  4 = M4 gate failed

Usage:
  python scripts/ci_full_pipeline.py              # CI mode (default)
  python scripts/ci_full_pipeline.py --mode ci    # Explicit CI mode
  python scripts/ci_full_pipeline.py --mode e2e   # E2E with online gates
  python scripts/ci_full_pipeline.py --skip-tests # Skip pytest
"""

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Ensure we're in project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

__version__ = "1.1.0"


def run_command(cmd: list, name: str) -> int:
    """Run a command and return exit code."""
    print(f"\n{'='*60}")
    print(f"RUNNING: {name}")
    print(f"CMD: {' '.join(cmd)}")
    print('='*60)
    
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    
    if result.returncode == 0:
        print(f"[OK] {name}: PASS")
    else:
        print(f"[FAIL] {name}: FAIL (exit code {result.returncode})")
    
    return result.returncode


def check_python_version() -> bool:
    """Check Python version is 3.11.x (hard fail for CI)."""
    major, minor = sys.version_info[:2]
    if (major, minor) == (3, 11):
        print(f"[OK] Python version: {sys.version.split()[0]}")
        return True
    print(f"[FAIL] Python version: {sys.version.split()[0]}")
    print("       Required: Python 3.11.x")
    print("       Fix: py -3.11 -m venv .venv && .venv\\Scripts\\Activate.ps1")
    return False


def main():
    # Python 3.11 hard check (CI requirement)
    if not check_python_version():
        return 1
    
    # v2.3.2: Repo safety check before any gates
    # Parse --allow-intent-edit early (before full argparse) for safety gate
    allow_intent = "--allow-intent-edit" in sys.argv
    repo_safety_script = PROJECT_ROOT / "scripts" / "check_repo_safety.py"
    if repo_safety_script.exists():
        safety_cmd = [sys.executable, "scripts/check_repo_safety.py"]
        if allow_intent:
            safety_cmd.append("--allow-intent-edit")
        result = subprocess.run(
            safety_cmd,
            cwd=PROJECT_ROOT
        )
        if result.returncode != 0:
            print(f"\n[FAIL] PIPELINE FAILED at repo safety (exit code 5)")
            return 5
        print("[OK] Repo Safety Check: PASS")
    
    parser = argparse.ArgumentParser(description="Full CI pipeline")
    parser.add_argument("--mode", choices=["ci", "e2e"], default="ci",
                        help="Pipeline mode: ci=offline only, e2e=online+offline")
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest")
    parser.add_argument("--config", default="config/real_minimal.yaml", 
                        help="Config for online gates (E2E mode)")
    parser.add_argument("--cycles", type=int, default=1,
                        help="Number of scan cycles in E2E mode (passed to ci_m5_0_gate.py)")
    parser.add_argument("--strict", action="store_true", default=True,
                        help="Enable strict validation in E2E mode (default: True)")
    parser.add_argument("--allow-intent-edit", action="store_true",
                        help="Allow uncommitted intent.txt changes (passed to repo safety gate)")
    args = parser.parse_args()
    
    is_e2e = args.mode == "e2e"
    start = datetime.now()
    results = {}
    
    mode_label = "E2E (online + offline)" if is_e2e else "CI (offline only)"
    
    print(f"""
============================================================
                    ARBY CI PIPELINE v{__version__}
                    {start.strftime('%Y-%m-%d %H:%M:%S')}
                    Mode: {mode_label}
============================================================
""")
    
    # ================================================================
    # 1. UNIT TESTS
    # ================================================================
    if not args.skip_tests:
        exit_code = run_command(
            [sys.executable, "-m", "pytest", "tests/unit", "-q", "--tb=short"],
            "Unit Tests (pytest)"
        )
        results["pytest"] = exit_code
        if exit_code != 0:
            print(f"\n[FAIL] PIPELINE FAILED at pytest (exit code 1)")
            return 1
    
    # ================================================================
    # 1.5 DOC VERIFICATION (fast, no RPC)
    # ================================================================
    # v2.0.2: Mandatory doc consistency checks before gates
    docs_script = PROJECT_ROOT / "scripts" / "ci_docs_consistency.py"
    if docs_script.exists():
        exit_code = run_command(
            [sys.executable, "scripts/ci_docs_consistency.py", "--verbose"],
            "Docs Consistency Check"
        )
        results["docs_consistency"] = exit_code
        if exit_code != 0:
            print(f"\n[FAIL] PIPELINE FAILED at docs consistency (exit code 1)")
            return 1
    
    status_script = PROJECT_ROOT / "scripts" / "check_status_md.py"
    if status_script.exists():
        exit_code = run_command(
            [sys.executable, "scripts/check_status_md.py", "--file", "Status_M4.md", "--verbose"],
            "Status_M4.md Check"
        )
        results["status_m4_check"] = exit_code
        if exit_code != 0:
            print(f"\n[FAIL] PIPELINE FAILED at Status_M4 check (exit code 1)")
            return 1
    
    # ================================================================
    # 2. M5_0 GATE (OFFLINE)
    # ================================================================
    exit_code = run_command(
        [sys.executable, "scripts/ci_m5_0_gate.py", "--offline", "--strict"],
        "M5_0 Gate (offline)"
    )
    results["m5_0_offline"] = exit_code
    if exit_code != 0:
        print(f"\n[FAIL] PIPELINE FAILED at M5_0 gate (exit code 2)")
        return 2
    
    # ================================================================
    # 3. M5 GATE
    # ================================================================
    # M5 validates daily_report which requires a complete runDir.
    # In CI mode: SKIPPED (daily_report is an aggregation layer)
    # In E2E mode: Run with --online to create runDir first
    
    if is_e2e:
        m5_gate = PROJECT_ROOT / "scripts" / "ci_m5_gate.py"
        if m5_gate.exists():
            cmd = [sys.executable, "scripts/ci_m5_gate.py", "--online", 
                   "--config", args.config]
            if args.strict:
                cmd.append("--strict")
            exit_code = run_command(cmd, "M5 Gate (online)")
            results["m5_online"] = exit_code
            if exit_code != 0:
                print(f"\n[FAIL] PIPELINE FAILED at M5 gate (exit code 3)")
                return 3
        else:
            print(f"\n[WARN] M5 gate script not found, skipping")
            results["m5_online"] = -1
    else:
        # CI mode: M5 skipped as expected
        print(f"\n[SKIP] M5 gate: SKIPPED (CI mode - daily_report requires runDir)")
        results["m5_offline"] = -1
    
    # ================================================================
    # 4. M4 EXECUTION GATE (OFFLINE)
    # ================================================================
    exit_code = run_command(
        [sys.executable, "scripts/ci_m4_execution_gate.py", "--offline", "--profile", "smoke"],
        "M4 Execution Gate (offline smoke)"
    )
    results["m4_smoke"] = exit_code
    if exit_code != 0:
        print(f"\n[FAIL] PIPELINE FAILED at M4 smoke gate (exit code 4)")
        return 4
    
    # M4 Profit profile
    exit_code = run_command(
        [sys.executable, "scripts/ci_m4_execution_gate.py", "--offline", "--profile", "profit"],
        "M4 Execution Gate (offline profit)"
    )
    results["m4_profit"] = exit_code
    if exit_code != 0:
        print(f"\n[FAIL] PIPELINE FAILED at M4 profit gate (exit code 4)")
        return 4
    
    # ================================================================
    # 5. E2E ONLINE GATES (if E2E mode)
    # ================================================================
    if is_e2e:
        print("\n" + "="*60)
        print("E2E: ONLINE GATES")
        print("="*60)
        
        # Build command with cycles and strict from args
        cmd = [sys.executable, "scripts/ci_m5_0_gate.py", "--online", 
               "--config", args.config, "--cycles", str(args.cycles)]
        if args.strict:
            cmd.append("--strict")
        
        exit_code = run_command(cmd, "M5_0 Gate (online)")
        results["m5_0_online"] = exit_code
        # Online failures are warnings in E2E, not blockers
        if exit_code != 0:
            print(f"[WARN] M5_0 online failed (non-blocking in E2E)")
    
    # ================================================================
    # SUMMARY
    # ================================================================
    elapsed = datetime.now() - start
    
    print(f"""
============================================================
                    PIPELINE SUMMARY
============================================================
""")
    
    for name, code in results.items():
        if code == -1:
            status = "[SKIP] SKIPPED"
        elif code == 0:
            status = "[OK] PASS"
        else:
            status = f"[FAIL] FAIL ({code})"
        print(f"  {name}: {status}")
    
    print(f"\n  Mode:    {args.mode.upper()}")
    print(f"  Elapsed: {elapsed.total_seconds():.1f}s")
    
    # In CI mode: only offline gates must pass
    # In E2E mode: offline gates must pass, online are warnings
    required_keys = ["m5_0_offline", "m4_smoke", "m4_profit"]
    if not args.skip_tests:
        required_keys.append("pytest")
    
    all_required_pass = all(results.get(k, 0) in (0, -1) for k in required_keys)
    
    if all_required_pass:
        print(f"\n[OK] ALL REQUIRED GATES PASSED")
        return 0
    else:
        print(f"\n[FAIL] PIPELINE FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
