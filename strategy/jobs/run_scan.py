# PATH: strategy/jobs/run_scan.py
"""
ARBY Scanner Entry Point.

STEP 7: Explicit mode error - no silent mode substitution.

If user runs with --mode real but REGISTRY_REAL is not implemented,
the scanner raises RuntimeError immediately (not silent fallback to smoke).

MODES:
  --mode smoke  → SMOKE_SIMULATOR (simulation only, always works)
  --mode real   → REGISTRY_REAL (not yet implemented, raises error)
"""

import argparse
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Feature flag: Set to True when REGISTRY_REAL is implemented
REGISTRY_REAL_IMPLEMENTED = False


def main():
    parser = argparse.ArgumentParser(
        description="ARBY Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # Run smoke simulator (default, always works)
  python -m strategy.jobs.run_scan --mode smoke --cycles 1

  # Run real scanner (not yet implemented)
  python -m strategy.jobs.run_scan --mode real --cycles 1
  # → RuntimeError: REGISTRY_REAL scanner not yet implemented

MODES:
  smoke  SMOKE_SIMULATOR - all data is simulated, execution disabled
  real   REGISTRY_REAL - live RPC calls (NOT YET IMPLEMENTED)
        """,
    )

    parser.add_argument(
        "--mode", "-m",
        choices=["smoke", "real"],
        default="smoke",
        help="Scanner mode: 'smoke' (simulation) or 'real' (live RPC). Default: smoke",
    )
    parser.add_argument(
        "--cycles", "-c",
        type=int,
        default=1,
        help="Number of scan cycles to run. Default: 1",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Output directory for artifacts. Default: data/runs/<timestamp>/",
    )
    parser.add_argument(
        "--config", "-f",
        type=str,
        default=None,
        help="Config file path. Default: None",
    )

    # Legacy flag (deprecated)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="[DEPRECATED] Use --mode smoke instead",
    )

    args = parser.parse_args()

    # Handle deprecated --smoke flag
    if args.smoke:
        warnings.warn(
            "--smoke is deprecated. Use --mode smoke instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        args.mode = "smoke"

    # STEP 7: Explicit mode check - no silent substitution
    if args.mode == "real":
        if not REGISTRY_REAL_IMPLEMENTED:
            raise RuntimeError(
                "REGISTRY_REAL scanner is not yet implemented.\n"
                "\n"
                "The --mode real option requires live RPC integration which is "
                "planned for M4 (Execution Layer).\n"
                "\n"
                "Current options:\n"
                "  1. Use --mode smoke for simulation (works now)\n"
                "  2. Wait for REGISTRY_REAL implementation in M4\n"
                "\n"
                "This error prevents silent fallback to smoke mode, which could "
                "cause confusion about whether you're running live or simulated."
            )
        # When implemented:
        # from strategy.jobs.run_scan_real import run_scanner as run_real_scanner
        # run_real_scanner(...)
        # return

    # Import smoke scanner (lazy to avoid circular imports)
    from strategy.jobs.run_scan_smoke import run_scanner, RunMode

    run_mode = RunMode.SMOKE_SIMULATOR if args.mode == "smoke" else RunMode.REGISTRY_REAL

    run_scanner(
        cycles=args.cycles,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        config_path=Path(args.config) if args.config else None,
        run_mode=run_mode,
    )


if __name__ == "__main__":
    main()
