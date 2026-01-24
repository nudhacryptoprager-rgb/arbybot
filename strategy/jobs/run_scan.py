# PATH: strategy/jobs/run_scan.py
"""
ARBY Scanner Entry Point.

PUBLIC API CONTRACT (for tests and external use):
=================================================
from strategy.jobs.run_scan import run_scanner, ScannerMode

run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=Path(...))
run_scanner(mode=ScannerMode.REAL, ...)  # raises RuntimeError without explicit enable

ScannerMode:
  - SMOKE: Simulation mode (always works)
  - REAL: Live RPC mode (requires explicit enable)
=================================================

REAL MODE SAFETY CONTRACT:
- --mode real WITHOUT explicit enable → RuntimeError
- Explicit enable = --allow-real flag OR --config <file>
- This prevents accidental live RPC calls in tests/CI

MODES:
  --mode smoke  → SMOKE_SIMULATOR (simulation only, always works)
  --mode real   → REGISTRY_REAL (requires: --allow-real OR --config)
"""

import argparse
import sys
import warnings
from enum import Enum
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class ScannerMode(str, Enum):
    """
    Scanner mode for public API.
    
    SMOKE: Simulation mode - all data is simulated
    REAL: Live RPC mode - requires explicit enable (--allow-real or --config)
    """
    SMOKE = "SMOKE"
    REAL = "REAL"


def run_scanner(
    mode: ScannerMode = ScannerMode.SMOKE,
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    allow_real: bool = False,
) -> None:
    """
    Run the ARBY scanner.
    
    PUBLIC API CONTRACT:
    - mode=ScannerMode.SMOKE: runs simulation (always works)
    - mode=ScannerMode.REAL: requires explicit enable (allow_real=True or config_path set)
    
    REAL MODE SAFETY:
    - Without explicit enable: raises RuntimeError
    - With allow_real=True OR config_path: runs live RPC pipeline
    
    Args:
        mode: Scanner mode (SMOKE or REAL)
        cycles: Number of scan cycles
        output_dir: Output directory for artifacts
        config_path: Config file (also acts as explicit enable for REAL)
        allow_real: Explicit flag to enable REAL mode
    
    Raises:
        RuntimeError: If mode=REAL without explicit enable
    """
    if mode == ScannerMode.REAL:
        # REAL MODE SAFETY: Require explicit enable
        explicit_enable = allow_real or (config_path is not None)
        
        if not explicit_enable:
            raise RuntimeError(
                "REAL mode requires explicit enable.\n"
                "\n"
                "To run REAL mode (live RPC), you must explicitly enable it:\n"
                "  Option 1: --allow-real flag\n"
                "  Option 2: --config <config_file>\n"
                "\n"
                "Examples:\n"
                "  python -m strategy.jobs.run_scan --mode real --allow-real\n"
                "  python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml\n"
                "\n"
                "This safety check prevents accidental live RPC calls in tests/CI.\n"
                "Use --mode smoke for simulation (no explicit enable needed)."
            )
        
        # REAL mode with explicit enable - run live pipeline
        from strategy.jobs.run_scan_real import run_scanner as _run_real_scanner
        _run_real_scanner(
            cycles=cycles,
            output_dir=output_dir,
            config_path=config_path,
        )
    else:
        # SMOKE mode - always works
        from strategy.jobs.run_scan_smoke import run_scanner as _run_smoke_scanner, RunMode
        _run_smoke_scanner(
            cycles=cycles,
            output_dir=output_dir,
            config_path=config_path,
            run_mode=RunMode.SMOKE_SIMULATOR,
        )


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="ARBY Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:
  # Run smoke simulator (default, always works)
  python -m strategy.jobs.run_scan --mode smoke --cycles 1

  # Run real scanner (requires explicit enable)
  python -m strategy.jobs.run_scan --mode real --allow-real
  python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml

MODES:
  smoke  SMOKE_SIMULATOR - all data is simulated (no explicit enable needed)
  real   REGISTRY_REAL - live RPC (requires --allow-real OR --config)

SAFETY:
  --mode real without --allow-real or --config raises RuntimeError.
  This prevents accidental live RPC calls in tests/CI.
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
        help="Config file path. Acts as explicit enable for REAL mode.",
    )
    parser.add_argument(
        "--allow-real",
        action="store_true",
        help="Explicitly enable REAL mode (live RPC). Required for --mode real without --config.",
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

    # Map CLI mode to ScannerMode
    scanner_mode = ScannerMode.SMOKE if args.mode == "smoke" else ScannerMode.REAL

    run_scanner(
        mode=scanner_mode,
        cycles=args.cycles,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        config_path=Path(args.config) if args.config else None,
        allow_real=args.allow_real,
    )


if __name__ == "__main__":
    main()
