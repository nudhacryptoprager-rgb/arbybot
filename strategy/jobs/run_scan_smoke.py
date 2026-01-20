# PATH: strategy/jobs/run_scan_smoke.py
"""
SMOKE SIMULATOR for ARBY.

This is a SIMULATION-ONLY scanner for testing infrastructure without real RPC calls.
It generates simulated metrics for testing paper trading, truth reports, and logging.

Usage:
    python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data/runs/smoke
"""

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

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


class ScannerMode(str, Enum):
    """Scanner operation mode."""
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"
    REGISTRY_REAL = "REGISTRY_REAL"


logger = logging.getLogger("arby.scan")

# Max samples to store for forensics
MAX_FORENSIC_SAMPLES = 50


def setup_logging(output_dir: Optional[Path] = None, level: int = logging.INFO) -> None:
    """Setup logging configuration."""
    handlers = [logging.StreamHandler(sys.stdout)]  # stdout, not stderr

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


def _make_forensic_sample(
    quote_id: str,
    dex: str,
    pool: str,
    token_in: str,
    token_out: str,
    amount_in: str,
    amount_out: str,
    gas_estimate: int,
    reject_reason: Optional[str] = None,
    reject_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a forensic sample record (Step 5)."""
    sample = {
        "quote_id": quote_id,
        "dex": dex,
        "pool": pool,
        "token_in": token_in,
        "token_out": token_out,
        "amount_in": amount_in,
        "amount_out": amount_out,
        "gas_estimate": gas_estimate,
    }
    if reject_reason:
        sample["reject_reason"] = reject_reason
        sample["reject_details"] = reject_details or {}
    return sample


def _make_quote_revert_details(
    fn_or_selector: str,
    params_summary: str,
    rpc_provider_tag: str,
    pool: str,
    dex: str,
    block_number: int,
) -> Dict[str, Any]:
    """Create QUOTE_REVERT reject details (Step 6)."""
    return {
        "fn_or_selector": fn_or_selector,
        "params_summary": params_summary,
        "rpc_provider_tag": rpc_provider_tag,
        "pool": pool,
        "dex": dex,
        "block_number": block_number,
    }


def _make_slippage_details(
    expected_out: str,
    min_out: str,
    slippage_bps: int,
    implied_price: str,
    anchor_price: str,
    deviation_bps: int,
) -> Dict[str, Any]:
    """Create SLIPPAGE_TOO_HIGH reject details (Step 7)."""
    return {
        "expected_out": expected_out,
        "min_out": min_out,
        "slippage_bps": slippage_bps,
        "implied_price": implied_price,
        "anchor_price": anchor_price,
        "deviation_bps": deviation_bps,
    }


def run_scan_cycle(
    cycle_num: int,
    config: Dict[str, Any],
    paper_session: PaperSession,
    rpc_metrics: RPCHealthMetrics,
    output_dir: Path,
    scanner_mode: ScannerMode = ScannerMode.SMOKE_SIMULATOR,
) -> Dict[str, Any]:
    """
    Run a single scan cycle.

    Args:
        cycle_num: Cycle number
        config: Scan configuration
        paper_session: Paper trading session
        rpc_metrics: RPC health metrics tracker
        output_dir: Output directory for artifacts
        scanner_mode: Current scanner mode

    Returns:
        Dict with cycle stats and reject histogram
    """
    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

    logger.info(
        f"Starting scan cycle {cycle_num}",
        extra={"context": {"cycle": cycle_num, "timestamp": timestamp.isoformat(), "mode": scanner_mode.value}}
    )

    # Initialize stats
    scan_stats = {
        "cycle": cycle_num,
        "timestamp": timestamp.isoformat(),
        "scanner_mode": scanner_mode.value,  # Step 4: Add mode to stats
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
    
    # Step 5: Forensic samples
    sample_rejects: List[Dict[str, Any]] = []
    sample_passed: List[Dict[str, Any]] = []

    # Simulate scanning
    try:
        simulated_block = 12345678 + cycle_num

        # Simulate some quote attempts
        for i in range(10):
            quote_id = f"quote_{cycle_num}_{i}_{uuid4().hex[:8]}"
            rpc_metrics.record_quote_attempt()

            # Simulate RPC call success/failure
            if random.random() > 0.1:  # 90% success rate
                latency = random.randint(50, 200)
                rpc_metrics.record_success(latency_ms=latency)
                scan_stats["quotes_fetched"] += 1

                # Simulate gate checks
                if random.random() > 0.3:  # 70% pass gates
                    scan_stats["gates_passed"] += 1
                    
                    # Step 5: Add to sample_passed
                    if len(sample_passed) < MAX_FORENSIC_SAMPLES:
                        sample_passed.append(_make_forensic_sample(
                            quote_id=quote_id,
                            dex=random.choice(["uniswap_v3", "sushiswap"]),
                            pool=f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
                            token_in="WETH",
                            token_out="USDC",
                            amount_in="1000000000000000000",
                            amount_out="2500000000",
                            gas_estimate=150000,
                        ))
                else:
                    # Step 6: QUOTE_REVERT with details
                    if random.random() > 0.5:
                        reason = "QUOTE_REVERT"
                        details = _make_quote_revert_details(
                            fn_or_selector="0xf7729d43",  # quoteExactInputSingle
                            params_summary="tokenIn=WETH,tokenOut=USDC,fee=500,amountIn=1e18",
                            rpc_provider_tag="alchemy_arb_1",
                            pool=f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
                            dex="uniswap_v3",
                            block_number=simulated_block,
                        )
                    else:
                        # Step 7: SLIPPAGE_TOO_HIGH with details
                        reason = "SLIPPAGE_TOO_HIGH"
                        details = _make_slippage_details(
                            expected_out="2500000000",
                            min_out="2475000000",
                            slippage_bps=150,
                            implied_price="2500.00",
                            anchor_price="2520.00",
                            deviation_bps=79,
                        )
                    
                    reject_histogram[reason] = reject_histogram.get(reason, 0) + 1
                    
                    # Step 5: Add to sample_rejects with details
                    if len(sample_rejects) < MAX_FORENSIC_SAMPLES:
                        sample_rejects.append(_make_forensic_sample(
                            quote_id=quote_id,
                            dex="uniswap_v3",
                            pool=f"0x{''.join(random.choices('0123456789abcdef', k=40))}",
                            token_in="WETH",
                            token_out="USDC",
                            amount_in="1000000000000000000",
                            amount_out="0",
                            gas_estimate=0,
                            reject_reason=reason,
                            reject_details=details,
                        ))
            else:
                rpc_metrics.record_failure()
                reject_histogram["INFRA_RPC_ERROR"] = reject_histogram.get("INFRA_RPC_ERROR", 0) + 1
                
                if len(sample_rejects) < MAX_FORENSIC_SAMPLES:
                    sample_rejects.append(_make_forensic_sample(
                        quote_id=quote_id,
                        dex="uniswap_v3",
                        pool="unknown",
                        token_in="WETH",
                        token_out="USDC",
                        amount_in="1000000000000000000",
                        amount_out="0",
                        gas_estimate=0,
                        reject_reason="INFRA_RPC_ERROR",
                        reject_details={"rpc_provider_tag": "alchemy_arb_1", "error": "timeout"},
                    ))

        scan_stats["quotes_total"] = 10
        scan_stats["pools_scanned"] = 10
        scan_stats["chains_active"] = 1
        scan_stats["dexes_active"] = 2
        scan_stats["pairs_covered"] = 5

        # Calculate rates
        if scan_stats["quotes_total"] > 0:
            scan_stats["quote_fetch_rate"] = scan_stats["quotes_fetched"] / scan_stats["quotes_total"]

        if scan_stats["quotes_fetched"] > 0:
            scan_stats["quote_gate_pass_rate"] = scan_stats["gates_passed"] / scan_stats["quotes_fetched"]

        # Simulate some spreads
        scan_stats["spread_ids_total"] = 3
        scan_stats["signals_total"] = 3

        # Simulate a profitable opportunity
        if random.random() > 0.5:
            spread_id = f"spread_{cycle_num}_{timestamp_str}"

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
                pool_a="0x0000000000000000000000000000000000000001",
                pool_b="0x0000000000000000000000000000000000000002",
                token_in="WETH",
                token_out="USDC",
                metadata={"simulated": True, "smoke_mode": True},
            )

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
                logger.error(
                    f"Paper trade recording failed: {e}",
                    exc_info=True,
                    extra={"context": {"spread_id": spread_id, "error_type": type(e).__name__}}
                )

    except Exception as e:
        logger.error(
            f"Cycle error: {e}",
            exc_info=True,
            extra={"context": {"cycle": cycle_num, "error_type": type(e).__name__}}
        )

    # Save scan snapshot with forensic samples (Step 5)
    snapshot_path = output_dir / "snapshots" / f"scan_{timestamp_str}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({
            "scanner_mode": scanner_mode.value,  # Step 4
            "stats": scan_stats,
            "reject_histogram": reject_histogram,
            "opportunities": opportunities,
            "sample_rejects": sample_rejects,  # Step 5
            "sample_passed": sample_passed,    # Step 5
        }, f, indent=2)

    logger.info(f"Snapshot saved: {snapshot_path}", extra={"context": {"path": str(snapshot_path)}})

    # Save reject histogram
    reject_path = output_dir / "reports" / f"reject_histogram_{timestamp_str}.json"
    reject_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reject_path, "w", encoding="utf-8") as f:
        json.dump(reject_histogram, f, indent=2)

    # Build and save truth report
    paper_stats = paper_session.get_stats()
    truth_report = build_truth_report(
        scan_stats=scan_stats,
        reject_histogram=reject_histogram,
        opportunities=opportunities,
        paper_session_stats=paper_stats,
        rpc_metrics=rpc_metrics,
        mode=scanner_mode.value,  # Step 4: Pass actual mode
    )

    truth_path = output_dir / "reports" / f"truth_report_{timestamp_str}.json"
    truth_report.save(truth_path)

    print_truth_report(truth_report)

    logger.info(
        f"Scan cycle complete: {scan_stats['quotes_fetched']}/{scan_stats['quotes_total']} fetched, "
        f"{scan_stats['gates_passed']} passed gates, {scan_stats['spread_ids_total']} spreads, "
        f"{scan_stats['spread_ids_executable']} executable",
        extra={"context": scan_stats}
    )

    return {
        "stats": scan_stats,
        "reject_histogram": reject_histogram,
        "opportunities": opportunities,
        "sample_rejects": sample_rejects,
        "sample_passed": sample_passed,
    }


def run_scanner(
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    scanner_mode: ScannerMode = ScannerMode.SMOKE_SIMULATOR,
) -> None:
    """
    Run the scanner for specified number of cycles.

    Args:
        cycles: Number of scan cycles to run
        output_dir: Output directory for artifacts
        config_path: Path to configuration file
        scanner_mode: Scanner mode (passed from run_scan.py)
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
        f"Scanner starting: {cycles} cycles, mode: {scanner_mode.value}, output: {output_dir}",
        extra={"context": {"cycles": cycles, "mode": scanner_mode.value, "output_dir": str(output_dir)}}
    )

    # Load config
    config = load_config(config_path)

    # Initialize paper session
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
                scanner_mode=scanner_mode,
            )

            if cycle < cycles:
                time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Scanner interrupted by user")
    finally:
        logger.info("Final session summary", extra={"context": paper_session.get_stats()})
        logger.info("Paper session summary", extra={"context": paper_session.get_pnl_summary()})
        paper_session.close()
        logger.info("Scanner stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ARBY Scanner (Smoke Simulator)")
    parser.add_argument("--cycles", "-c", type=int, default=1, help="Number of scan cycles")
    parser.add_argument("--output-dir", "-o", type=str, default=None, help="Output directory")
    parser.add_argument("--config", "-f", type=str, default=None, help="Config file path")

    args = parser.parse_args()

    run_scanner(
        cycles=args.cycles,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        config_path=Path(args.config) if args.config else None,
        scanner_mode=ScannerMode.SMOKE_SIMULATOR,
    )


if __name__ == "__main__":
    main()
