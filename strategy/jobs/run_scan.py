# PATH: strategy/jobs/run_scan.py
"""
Scan job runner for ARBY.

Executes scan cycles using:
- Registry for pool discovery (discovery/registry.py)
- DEX adapters for quoting (dex/adapters/*.py)
- Gates for opportunity validation (strategy/gates.py)
- Paper trading for simulation (strategy/paper_trading.py)
- Truth reports for metrics (monitoring/truth_report.py)

Modes:
- SMOKE_SIMULATOR: Fake quotes for testing (default until real implementation)
- REGISTRY_REAL: Real quotes from RPC (TODO)

Usage:
    python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/scan
"""

import argparse
import logging
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class ScannerMode(str, Enum):
    """Scanner operation mode."""
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"
    REGISTRY_REAL = "REGISTRY_REAL"


# Current active mode
CURRENT_MODE = ScannerMode.SMOKE_SIMULATOR

logger = logging.getLogger("arby.scan")


def setup_logging(output_dir: Optional[Path] = None, level: int = logging.INFO) -> None:
    """Setup logging configuration."""
    handlers = [logging.StreamHandler(sys.stdout)]  # Use stdout, not stderr
    
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


def get_scanner_mode() -> ScannerMode:
    """Get current scanner mode."""
    return CURRENT_MODE


def run_scanner(
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> None:
    """
    Run the scanner for specified number of cycles.
    
    Currently runs in SMOKE_SIMULATOR mode.
    REGISTRY_REAL mode is under development.
    """
    # Log mode info (to stdout via logger, not stderr)
    logger.info(
        "Scanner mode: %s (real scanner under development)",
        CURRENT_MODE.value
    )
    
    # Import and run smoke simulator
    from strategy.jobs.run_scan_smoke import run_scanner as run_smoke
    run_smoke(
        cycles=cycles,
        output_dir=output_dir,
        config_path=config_path,
        scanner_mode=CURRENT_MODE,  # Pass mode for JSON output
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
