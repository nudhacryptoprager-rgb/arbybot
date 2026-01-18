# PATH: strategy/jobs/run_scan.py
"""
Real scan job runner for ARBY.

Executes REAL scan cycles using:
- Registry for pool discovery (discovery/registry.py)
- DEX adapters for quoting (dex/adapters/*.py)
- Gates for opportunity validation (strategy/gates.py)
- Paper trading for simulation (strategy/paper_trading.py)
- Truth reports for metrics (monitoring/truth_report.py)

For SMOKE/SIMULATION testing, use run_scan_smoke.py instead.

Usage:
    python -m strategy.jobs.run_scan --cycles 1 --output-dir data/runs/scan

TODO: Implement real pipeline:
    1. Load registry from intent.txt
    2. For each pool candidate:
       a. Get quotes from both DEXes via adapters
       b. Calculate spread/opportunity
       c. Apply gates (slippage, liquidity, sanity checks)
       d. If passes: create PaperTrade and record
    3. Generate truth_report with real metrics
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.format_money import format_money
from strategy.paper_trading import PaperSession, PaperTrade
from monitoring.truth_report import (
    RPCHealthMetrics,
    TruthReport,
    build_truth_report,
    print_truth_report,
)

logger = logging.getLogger("arby.scan")


def setup_logging(output_dir: Optional[Path] = None, level: int = logging.INFO) -> None:
    """Setup logging configuration."""
    handlers = [logging.StreamHandler()]
    
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
    Run the REAL scanner for specified number of cycles.
    
    Currently NOT IMPLEMENTED - redirects to smoke for safety.
    """
    logger.warning(
        "REAL SCANNER NOT YET IMPLEMENTED - redirecting to smoke simulator",
        extra={"context": {"cycles": cycles, "output_dir": str(output_dir)}}
    )
    
    # Import and run smoke until real implementation is ready
    from strategy.jobs.run_scan_smoke import run_scanner as run_smoke
    run_smoke(cycles=cycles, output_dir=output_dir, config_path=config_path)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ARBY Scanner (Real Mode)")
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
        help="Run in smoke/simulation mode (recommended for testing)"
    )
    
    args = parser.parse_args()
    
    if args.smoke:
        # Explicitly requested smoke mode
        from strategy.jobs.run_scan_smoke import run_scanner as run_smoke
        run_smoke(
            cycles=args.cycles,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            config_path=Path(args.config) if args.config else None,
        )
    else:
        # Real mode (will redirect to smoke until implemented)
        run_scanner(
            cycles=args.cycles,
            output_dir=Path(args.output_dir) if args.output_dir else None,
            config_path=Path(args.config) if args.config else None,
        )


if __name__ == "__main__":
    main()
