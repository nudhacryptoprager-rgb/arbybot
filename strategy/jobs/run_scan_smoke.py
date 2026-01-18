# PATH: strategy/jobs/run_scan_smoke.py
"""
SMOKE SIMULATOR for ARBY.

This is a SIMULATION-ONLY scanner for testing infrastructure without real RPC calls.
It generates random/simulated metrics for testing paper trading, truth reports, and logging.

For REAL scanning, use run_scan.py with actual registry/adapter/gates pipeline.

Usage:
    python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data/runs/smoke
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.format_money import format_money, format_money_short
from strategy.paper_trading import PaperSession, PaperTrade
from monitoring.truth_report import (
    RPCHealthMetrics,
    TruthReport,
    build_truth_report,
    build_health_section,
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


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load scan configuration."""
    default_config = {
        "chains": [42161],  # Arbitrum
        "sizes_usd": [50, 100, 200, 400],
        "max_slippage_bps": 50,
        "min_net_bps": 10,
        "min_net_usd": "0.50",
        "max_latency_ms": 2000,
        "min_confidence": 0.5,
        "cooldown_seconds": 60,
        "notion_capital_usdc": "10000.000000",
    }
    
    if config_path and config_path.exists():
        with open(config_path, "r") as f:
            loaded = json.load(f)
            default_config.update(loaded)
    
    return default_config


def run_scan_cycle(
    cycle_num: int,
    config: Dict[str, Any],
    paper_session: PaperSession,
    rpc_metrics: RPCHealthMetrics,
    output_dir: Path,
) -> Dict[str, Any]:
    """
    Run a single scan cycle.
    
    Args:
        cycle_num: Cycle number
        config: Scan configuration
        paper_session: Paper trading session
        rpc_metrics: RPC health metrics tracker
        output_dir: Output directory for artifacts
    
    Returns:
        Dict with cycle stats and reject histogram
    """
    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    
    logger.info(
        f"Starting scan cycle {cycle_num}",
        extra={"context": {"cycle": cycle_num, "timestamp": timestamp.isoformat()}}
    )
    
    # Initialize stats
    scan_stats = {
        "cycle": cycle_num,
        "timestamp": timestamp.isoformat(),
        "quotes_fetched": 0,
        "quotes_total": 0,
        "gates_passed": 0,
        "spread_ids_total": 0,
        "spread_ids_profitable": 0,
        "spread_ids_executable": 0,
        "signals_total": 0,
        "signals_profitable": 0,
        "signals_executable": 0,
        "paper_executable_count": 0,
        "execution_ready_count": 0,
        "blocked_spreads": 0,
        "chains_active": 0,
        "dexes_active": 0,
        "pairs_covered": 0,
        "pools_scanned": 0,
        "quote_fetch_rate": 0.0,
        "quote_gate_pass_rate": 0.0,
    }
    
    reject_histogram: Dict[str, int] = {}
    opportunities: List[Dict[str, Any]] = []
    
    # Simulate scanning (in real implementation, this would call quote_engine)
    try:
        # Simulate some quote attempts
        for i in range(10):
            rpc_metrics.record_quote_attempt()
            
            # Simulate RPC call success/failure
            import random
            if random.random() > 0.1:  # 90% success rate
                rpc_metrics.record_success(latency_ms=random.randint(50, 200))
                scan_stats["quotes_fetched"] += 1
            else:
                rpc_metrics.record_failure()
                reject_histogram["INFRA_RPC_ERROR"] = reject_histogram.get("INFRA_RPC_ERROR", 0) + 1
        
        scan_stats["quotes_total"] = 10
        scan_stats["pools_scanned"] = 10
        scan_stats["chains_active"] = 1
        scan_stats["dexes_active"] = 2
        scan_stats["pairs_covered"] = 5
        
        # Calculate rates
        if scan_stats["quotes_total"] > 0:
            scan_stats["quote_fetch_rate"] = scan_stats["quotes_fetched"] / scan_stats["quotes_total"]
        
        # Simulate some spreads
        scan_stats["spread_ids_total"] = 3
        scan_stats["signals_total"] = 3
        
        # Simulate some rejects
        reject_histogram["QUOTE_REVERT"] = reject_histogram.get("QUOTE_REVERT", 0) + 2
        reject_histogram["SLIPPAGE_TOO_HIGH"] = reject_histogram.get("SLIPPAGE_TOO_HIGH", 0) + 1
        
        # Simulate a profitable opportunity that would execute
        if random.random() > 0.5:
            spread_id = f"spread_{cycle_num}_{timestamp_str}"
            
            # Create paper trade with ALL required context fields
            paper_trade = PaperTrade(
                spread_id=spread_id,
                outcome="WOULD_EXECUTE",
                numeraire="USDC",
                amount_in_numeraire=format_money(Decimal("100")),
                expected_pnl_numeraire=format_money(Decimal("0.50")),
                expected_pnl_bps=format_money(Decimal("50"), decimals=2),
                gas_price_gwei=format_money(Decimal("0.01"), decimals=2),
                gas_estimate=150000,
                chain_id=42161,
                dex_a="uniswap_v3",
                dex_b="sushiswap",
                # REQUIRED context fields (per Step 7)
                pool_a="0x0000000000000000000000000000000000000001",  # Simulated pool A
                pool_b="0x0000000000000000000000000000000000000002",  # Simulated pool B
                token_in="WETH",
                token_out="USDC",
                metadata={"simulated": True, "smoke_mode": True},
            )
            
            # Record the trade - this used to crash with :.2f on string
            try:
                recorded = paper_session.record_trade(paper_trade)
                if recorded:
                    scan_stats["paper_executable_count"] += 1
                    scan_stats["spread_ids_profitable"] += 1
                    scan_stats["spread_ids_executable"] += 1
                    
                    opportunities.append({
                        "spread_id": spread_id,
                        "net_pnl_usdc": paper_trade.expected_pnl_numeraire,
                        "net_pnl_bps": paper_trade.expected_pnl_bps,
                    })
            except Exception as e:
                # CORRECT: Use extra={"context": {...}} for contextual fields
                logger.error(
                    f"Paper trade recording failed: {e}",
                    exc_info=True,
                    extra={
                        "context": {
                            "spread_id": spread_id,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                        }
                    }
                )
        
        # Calculate gate pass rate
        gates_passed = scan_stats["quotes_fetched"] - len([r for r in reject_histogram.keys() if r != "INFRA_RPC_ERROR"])
        scan_stats["gates_passed"] = max(0, gates_passed)
        if scan_stats["quotes_fetched"] > 0:
            scan_stats["quote_gate_pass_rate"] = scan_stats["gates_passed"] / scan_stats["quotes_fetched"]
    
    except ValueError as ve:
        # CORRECT: Use extra={"context": {...}} instead of spread_id=...
        logger.error(
            f"Cycle error (ValueError): {ve}",
            exc_info=True,
            extra={
                "context": {
                    "cycle": cycle_num,
                    "error_type": "ValueError",
                    "phase": "scan_cycle",
                }
            }
        )
    except TypeError as te:
        # CORRECT: Use extra={"context": {...}} instead of spread_id=...
        logger.error(
            f"Cycle error (TypeError): {te}",
            exc_info=True,
            extra={
                "context": {
                    "cycle": cycle_num,
                    "error_type": "TypeError",
                    "phase": "scan_cycle",
                }
            }
        )
    except Exception as e:
        # CORRECT: Use extra={"context": {...}} for all contextual fields
        logger.error(
            f"Cycle error: {e}",
            exc_info=True,
            extra={
                "context": {
                    "cycle": cycle_num,
                    "error_type": type(e).__name__,
                    "phase": "scan_cycle",
                }
            }
        )
    
    # Save scan snapshot
    snapshot_path = output_dir / "snapshots" / f"scan_{timestamp_str}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({
            "stats": scan_stats,
            "reject_histogram": reject_histogram,
            "opportunities": opportunities,
        }, f, indent=2)
    
    logger.info(
        f"Snapshot saved: {snapshot_path}",
        extra={"context": {"path": str(snapshot_path)}}
    )
    
    # Save reject histogram
    reject_path = output_dir / "reports" / f"reject_histogram_{timestamp_str}.json"
    reject_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reject_path, "w", encoding="utf-8") as f:
        json.dump(reject_histogram, f, indent=2)
    
    logger.info(
        f"Reject histogram saved: {reject_path}",
        extra={"context": {"path": str(reject_path)}}
    )
    
    # Build and save truth report
    paper_stats = paper_session.get_stats()
    truth_report = build_truth_report(
        scan_stats=scan_stats,
        reject_histogram=reject_histogram,
        opportunities=opportunities,
        paper_session_stats=paper_stats,
        rpc_metrics=rpc_metrics,
        mode="REGISTRY",
    )
    
    truth_path = output_dir / "reports" / f"truth_report_{timestamp_str}.json"
    truth_report.save(truth_path)
    
    # Print truth report
    print_truth_report(truth_report)
    
    logger.info(
        f"Scan cycle complete: {scan_stats['quotes_fetched']}/{scan_stats['quotes_total']} fetched, "
        f"{scan_stats['gates_passed']} passed gates, {scan_stats['spread_ids_total']} spreads, "
        f"{scan_stats['spread_ids_executable']} executable, {scan_stats['blocked_spreads']} blocked",
        extra={"context": scan_stats}
    )
    
    return {
        "stats": scan_stats,
        "reject_histogram": reject_histogram,
        "opportunities": opportunities,
    }


def run_scanner(
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> None:
    """
    Run the scanner for specified number of cycles.
    
    Args:
        cycles: Number of scan cycles to run
        output_dir: Output directory for artifacts
        config_path: Path to configuration file
    """
    # Setup output directory
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("data/runs") / timestamp
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    setup_logging(output_dir)
    
    logger.info(
        f"Scanner starting: {cycles} cycles, output: {output_dir}",
        extra={"context": {"cycles": cycles, "output_dir": str(output_dir)}}
    )
    
    # Load config
    config = load_config(config_path)
    
    # Initialize paper session with output_dir so paper_trades.jsonl is created
    paper_session = PaperSession(
        output_dir=output_dir,
        cooldown_seconds=config.get("cooldown_seconds", 60),
        notion_capital_usdc=config.get("notion_capital_usdc", "10000.000000"),
    )
    
    # Initialize RPC metrics
    rpc_metrics = RPCHealthMetrics()
    
    try:
        for cycle in range(1, cycles + 1):
            run_scan_cycle(
                cycle_num=cycle,
                config=config,
                paper_session=paper_session,
                rpc_metrics=rpc_metrics,
                output_dir=output_dir,
            )
            
            # Brief pause between cycles
            if cycle < cycles:
                time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Scanner interrupted by user")
    
    finally:
        # Final session summary
        logger.info("Final session summary", extra={"context": paper_session.get_stats()})
        logger.info("Paper session summary", extra={"context": paper_session.get_pnl_summary()})
        paper_session.close()
        logger.info("Scanner stopped")


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
    
    args = parser.parse_args()
    
    run_scanner(
        cycles=args.cycles,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        config_path=Path(args.config) if args.config else None,
    )


if __name__ == "__main__":
    main()