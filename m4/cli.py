"""
M4 CLI Module

Command-line interface and orchestration for M4 execution gate.

Usage:
    python -m m4.cli --offline
    python -m m4.cli --online --profile profit
    python -m m4.cli --dry-run
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .policy import (
    DoDProfile,
    CostModelRegistry,
)
from .gates import run_offline_gate, run_online_gate
from .discovery import find_latest_run_dir, discover_m4_artifacts

__version__ = "1.9.3"

# Repository root - assumes this file is at m4/cli.py
REPO_ROOT = Path(__file__).resolve().parent.parent


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


def main(argv: Optional[list] = None) -> int:
    """
    Main entry point for M4 execution gate CLI.
    
    Args:
        argv: Command line arguments (default: sys.argv[1:])
        
    Returns:
        Exit code (0=PASS, 1=FAIL, 2=NO_DATA, 3=ERROR)
    """
    # Python 3.11 enforcement - warn only, don't block
    # Enforce via CI / pyproject.toml requires-python
    import os
    if sys.version_info[:2] != (3, 11) and not os.environ.get("ARBY_SKIP_PYTHON_CHECK"):
        print(f"[WARN] Python version: {sys.version.split()[0]} (expected 3.11.x)")
    
    parser = argparse.ArgumentParser(
        description="M4 Execution Gate - DEX<->DEX Atomic Execution",
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
                        help="Require valid run_timestamp and run_id (continuous scan mode)")
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
    
    parser.add_argument("--artifact-mode", type=str, default="rolling",
                        choices=["rolling", "full"],
                        help="Artifact mode: rolling (default, only rolling/incident), full (legacy per-run)")
    parser.add_argument("--reset-window", action="store_true",
                        help="Reset rolling aggregator window (start fresh after major refactor)")
    parser.add_argument("--require-clean", action="store_true",
                        help="Reject dirty worktree - refuse to write _latest if code_dirty=true")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="Allow dirty worktree for profit profile (override default require-clean)")

    args = parser.parse_args(argv)

    # v1.11.0: profit profile defaults to require-clean (evidence standard)
    # --allow-dirty explicitly overrides this default
    if args.profile == DoDProfile.PROFIT and not args.allow_dirty:
        if not args.require_clean:
            print("[POLICY] --profile profit -> enabling --require-clean (use --allow-dirty to override)")
            args.require_clean = True

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
            strict_evidence=args.strict_evidence,
            artifact_mode=args.artifact_mode,
            emit_agg=args.emit_agg,
            reset_window=args.reset_window,
            require_clean=args.require_clean
        )
        return result
    elif args.dry_run:
        return run_dry_run()
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
