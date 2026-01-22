# PATH: strategy/jobs/run_scan.py
"""
Scan job runner for ARBY.

Routes to appropriate scanner implementation based on mode.

Modes:
- SMOKE_SIMULATOR: Fake quotes for testing (--mode smoke)
- REGISTRY_REAL: Real quotes from RPC (--mode real) - NOT YET IMPLEMENTED

Usage:
    python -m strategy.jobs.run_scan --mode smoke --cycles 1 --output-dir data/runs/scan
    python -m strategy.jobs.run_scan --mode real --cycles 1  # Will raise RuntimeError
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from strategy.jobs.run_scan_smoke import RunMode, run_scanner as run_smoke

logger = logging.getLogger("arby.scan")


class ScannerMode:
    """Scanner mode constants."""
    SMOKE = "smoke"
    REAL = "real"
    
    VALID_MODES = {SMOKE, REAL}


def setup_logging(output_dir: Optional[Path] = None, level: int = logging.INFO) -> None:
    """Setup logging configuration."""
    handlers = [logging.StreamHandler(sys.stdout)]
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        log_file = output_dir / "scan.log"
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-9s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def run_scanner(
    mode: str,
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> None:
    """
    Run the scanner for specified number of cycles.
    
    Args:
        mode: Scanner mode - "smoke" or "real"
        cycles: Number of scan cycles
        output_dir: Output directory for artifacts
        config_path: Path to config file
    
    Raises:
        RuntimeError: If mode is "real" (not yet implemented)
        ValueError: If mode is invalid
    """
    if mode not in ScannerMode.VALID_MODES:
        raise ValueError(f"Invalid mode: {mode}. Valid modes: {ScannerMode.VALID_MODES}")
    
    if mode == ScannerMode.REAL:
        # STEP 1: No silent redirect - explicit error for REAL mode
        raise RuntimeError(
            "Real scanner (REGISTRY_REAL) not yet implemented. "
            "Use --mode smoke for simulation. "
            "See docs/status/Status_M3.md for implementation roadmap."
        )
    
    # SMOKE mode
    logger.info(f"Scanner mode: {mode} -> {RunMode.SMOKE_SIMULATOR.value}")
    run_smoke(
        cycles=cycles,
        output_dir=output_dir,
        config_path=config_path,
        run_mode=RunMode.SMOKE_SIMULATOR,
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="ARBY Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m strategy.jobs.run_scan --mode smoke --cycles 1
  python -m strategy.jobs.run_scan --mode smoke --output-dir data/runs/myrun

Modes:
  smoke   Run in simulation mode (generates fake quotes)
  real    Run with real RPC quotes (NOT YET IMPLEMENTED)
"""
    )
    parser.add_argument(
        "--mode", "-m",
        type=str,
        choices=list(ScannerMode.VALID_MODES),
        default=ScannerMode.SMOKE,
        help="Scanner mode: smoke (simulation) or real (RPC). Default: smoke"
    )
    parser.add_argument(
        "--cycles", "-c",
        type=int,
        default=1,
        help="Number of scan cycles to run (default: 1)"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Output directory for artifacts"
    )
    parser.add_argument(
        "--config", "-f",
        type=str,
        default=None,
        help="Path to configuration file"
    )
    # Legacy flag for backward compat
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="[DEPRECATED] Use --mode smoke instead"
    )

    args = parser.parse_args()
    
    # Handle legacy --smoke flag
    mode = args.mode
    if args.smoke:
        logger.warning("--smoke is deprecated, use --mode smoke instead")
        mode = ScannerMode.SMOKE

    output_path = Path(args.output_dir) if args.output_dir else None
    setup_logging(output_path)

    run_scanner(
        mode=mode,
        cycles=args.cycles,
        output_dir=output_path,
        config_path=Path(args.config) if args.config else None,
    )


if __name__ == "__main__":
    main()
