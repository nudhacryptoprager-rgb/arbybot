# PATH: strategy/jobs/run_scan.py
"""
ARBY Scanner Entry Point.

PUBLIC API CONTRACT (for tests and external use):
=================================================
from strategy.jobs.run_scan import run_scanner, ScannerMode

run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=Path(...))
run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=Path(...))

ScannerMode:
  - SMOKE: Simulation mode (all data simulated)
  - REAL: Live quoting mode (real RPC, execution disabled)
=================================================

M4 CONTRACT:
- --mode real runs live quoting pipeline
- Execution is disabled (EXECUTION_DISABLED_M4)
- Artifacts are same 4/4 as SMOKE
- run_mode in truth_report: "REGISTRY_REAL"
- quotes_fetched >= 1 required

MODES:
  --mode smoke  → SMOKE_SIMULATOR
  --mode real   → REGISTRY_REAL (live quoting, no execution)
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
    REAL: Live quoting mode - real RPC calls, execution disabled (M4)
    """
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
    
    PUBLIC API CONTRACT:
    - mode=ScannerMode.SMOKE: runs simulation (always works)
    - mode=ScannerMode.REAL: runs live quoting (M4: execution disabled)
    - cycles: number of scan cycles to run
    - output_dir: where to write artifacts
    - config_path: optional config file
    
    Artifacts generated in output_dir (same for SMOKE and REAL):
    - scan.log
    - snapshots/scan_*.json
    - reports/reject_histogram_*.json
    - reports/truth_report_*.json
    
    M4 REAL mode contract:
    - truth_report.run_mode: "REGISTRY_REAL"
    - execution_ready_count: 0 (EXECUTION_DISABLED_M4)
    - quotes_fetched >= 1 (required for M4 gate)
    - current_block must be pinned (not None)
    """
    if mode == ScannerMode.REAL:
        # M4: REAL mode runs live quoting pipeline
        from strategy.jobs.run_scan_real import run_scanner as _run_real_scanner
        _run_real_scanner(
            cycles=cycles,
            output_dir=output_dir,
            config_path=config_path,
        )
    else:
        # SMOKE mode: simulation
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

  # Run real scanner (M4: live quoting, no execution)
  python -m strategy.jobs.run_scan --mode real --cycles 1

  # Run real scanner with minimal config
  python -m strategy.jobs.run_scan --mode real --cycles 1 --config config/real_minimal.yaml

MODES:
  smoke  SMOKE_SIMULATOR - all data is simulated
  real   REGISTRY_REAL - live RPC quoting, execution disabled (M4)
        """,
    )

    parser.add_argument(
        "--mode", "-m",
        choices=["smoke", "real"],
        default="smoke",
        help="Scanner mode: 'smoke' (simulation) or 'real' (live quoting). Default: smoke",
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
        help="Config file path. Default: None (uses real_minimal for --mode real)",
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
    )


if __name__ == "__main__":
    main()
