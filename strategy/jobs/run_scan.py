# PATH: strategy/jobs/run_scan.py
"""
Scan job runner for ARBY.

Routes to appropriate scanner implementation based on mode.

Modes (Step 6: unified as run_mode):
- SMOKE_SIMULATOR: Fake quotes for testing (default)
- REGISTRY_REAL: Real quotes from RPC (TODO)

Usage:
    python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/scan
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
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> None:
    """
    Run the scanner for specified number of cycles.
    
    Currently routes to SMOKE_SIMULATOR.
    REGISTRY_REAL mode is under development.
    """
    # Log mode info
    logger.info(
        "Scanner run_mode: %s (real scanner under development)",
        RunMode.SMOKE_SIMULATOR.value
    )

    # Run smoke simulator
    run_smoke(
        cycles=cycles,
        output_dir=output_dir,
        config_path=config_path,
        run_mode=RunMode.SMOKE_SIMULATOR,
    )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ARBY Scanner")
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
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run in smoke/simulation mode (this is currently the default)"
    )

    args = parser.parse_args()

    # Setup logging first
    output_path = Path(args.output_dir) if args.output_dir else None
    setup_logging(output_path)

    run_scanner(
        cycles=args.cycles,
        output_dir=output_path,
        config_path=Path(args.config) if args.config else None,
    )


if __name__ == "__main__":
    main()
