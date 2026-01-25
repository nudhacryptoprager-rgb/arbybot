# PATH: strategy/jobs/run_scan.py
"""
ARBY Scanner Entry Point.

PUBLIC API CONTRACT:
=================================================
from strategy.jobs.run_scan import run_scanner, ScannerMode

run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=Path(...))
run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=Path(...))

ScannerMode:
  - SMOKE: Simulation mode (all data simulated)
  - REAL: Live RPC mode (real quotes, execution disabled)
=================================================

M4 CONTRACT:
- REAL mode ALWAYS goes to run_scan_real (no silent fallback)
- REAL mode produces 4 artifacts
- REAL mode has execution disabled
- REAL mode pins current_block from RPC
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
    """Scanner mode."""
    SMOKE = "SMOKE"
    REAL = "REAL"


def run_scanner(
    mode: ScannerMode = ScannerMode.SMOKE,
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> None:
    """
    Run the ARBY scanner.
    
    M4 CONTRACT:
    - mode=REAL ALWAYS goes to run_scan_real (no fallback to SMOKE)
    - REAL mode may raise RuntimeError if all RPC endpoints fail
    - REAL mode produces 4 artifacts
    """
    if mode == ScannerMode.REAL:
        # REAL mode - ALWAYS use run_scan_real (no fallback)
        from strategy.jobs.run_scan_real import run_scanner as _run_real_scanner
        _run_real_scanner(
            cycles=cycles,
            output_dir=output_dir,
            config_path=config_path,
        )
    else:
        # SMOKE mode - simulation
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
  # Run smoke simulator (default)
  python -m strategy.jobs.run_scan --mode smoke --cycles 1

  # Run real scanner (M4)
  python -m strategy.jobs.run_scan --mode real --cycles 1

  # Run real scanner with config
  python -m strategy.jobs.run_scan --mode real --config config/real_minimal.yaml

MODES:
  smoke  SMOKE_SIMULATOR - all data simulated
  real   REGISTRY_REAL - live RPC, execution disabled (M4)
        """,
    )

    parser.add_argument(
        "--mode", "-m",
        choices=["smoke", "real"],
        default="smoke",
        help="Scanner mode. Default: smoke",
    )
    parser.add_argument(
        "--cycles", "-c",
        type=int,
        default=1,
        help="Number of scan cycles. Default: 1",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Output directory for artifacts.",
    )
    parser.add_argument(
        "--config", "-f",
        type=str,
        default=None,
        help="Config file path.",
    )

    # Legacy flags
    parser.add_argument("--smoke", action="store_true", help="[DEPRECATED]")
    parser.add_argument("--allow-real", action="store_true", help="[DEPRECATED]")

    args = parser.parse_args()

    if args.smoke:
        warnings.warn("--smoke is deprecated. Use --mode smoke", DeprecationWarning)
        args.mode = "smoke"

    if args.allow_real:
        warnings.warn("--allow-real is deprecated and no longer needed", DeprecationWarning)

    scanner_mode = ScannerMode.SMOKE if args.mode == "smoke" else ScannerMode.REAL

    run_scanner(
        mode=scanner_mode,
        cycles=args.cycles,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        config_path=Path(args.config) if args.config else None,
    )


if __name__ == "__main__":
    main()
