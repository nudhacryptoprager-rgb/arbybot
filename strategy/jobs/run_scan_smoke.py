# PATH: strategy/jobs/run_scan_smoke.py
"""
SMOKE SIMULATOR for ARBY.

This is a SIMULATION-ONLY scanner for testing infrastructure without real RPC calls.
It generates simulated metrics for testing paper trading, truth reports, and logging.

Key features:
- Block numbers derived from timestamp (realistic)
- null instead of 0 for unknown values
- Standardized dex_id naming
- run_mode field in all outputs
- Paper trades linked via opportunity_id
- QUOTE_REVERT with error_class/error_message
- gate_name in reject_details for debugging
- histogram self-contained with totals
- pool address preserved even on INFRA_RPC_ERROR
- dexes_active counts actual unique dex_ids
- top_opportunities NEVER empty (includes rejected spreads with reason)

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
from typing import Any, Dict, List, Optional, Set
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


class RunMode(str, Enum):
    """Scanner runtime mode (distinct from TruthReport mode)."""
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"
    REGISTRY_REAL = "REGISTRY_REAL"


# Standardized DEX identifiers
KNOWN_DEX_IDS = [
    "uniswap_v3",
    "sushiswap_v3",
    "camelot_v3",
    "pancakeswap_v3",
]

logger = logging.getLogger("arby.scan")

MAX_FORENSIC_SAMPLES = 50


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


def shutdown_logging() -> None:
    """Shutdown logging handlers to release file locks (Windows fix)."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load scan configuration."""
    default_config = {
        "chains": [42161],
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


def _get_simulated_block() -> int:
    """Get simulated block number based on timestamp."""
    base_block = 150_000_000
    ts_offset = int(time.time()) % 1_000_000
    return base_block + ts_offset


def _make_forensic_sample(
    quote_id: str,
    dex_id: str,
    pool: str,
    token_in: str,
    token_out: str,
    amount_in: str,
    amount_out: Optional[str],
    gas_estimate: Optional[int],
    reject_reason: Optional[str] = None,
    reject_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a forensic sample record."""
    sample = {
        "quote_id": quote_id,
        "dex_id": dex_id,
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
    dex_id: str,
    block_number: int,
    error_class: str,
    error_message: str,
) -> Dict[str, Any]:
    """Create QUOTE_REVERT reject details with error info."""
    return {
        "gate_name": "quote_execution",
        "reason_family": "REVERT",
        "fn_or_selector": fn_or_selector,
        "params_summary": params_summary,
        "rpc_provider_tag": rpc_provider_tag,
        "pool": pool,
        "dex_id": dex_id,
        "block_number": block_number,
        "error_class": error_class,
        "error_message": error_message,
    }


def _make_slippage_details(
    expected_out: str,
    min_out: str,
    slippage_bps: int,
    implied_price: str,
    anchor_price: str,
    deviation_bps: int,
    block_number: int,
) -> Dict[str, Any]:
    """Create SLIPPAGE_TOO_HIGH reject details."""
    return {
        "gate_name": "slippage_gate",
        "reason_family": "SLIPPAGE",
        "expected_out": expected_out,
        "min_out": min_out,
        "slippage_bps": slippage_bps,
        "slippage_note": "slippage_bps = (expected_out - min_out) / expected_out * 10000",
        "implied_price": implied_price,
        "anchor_price": anchor_price,
        "deviation_bps": deviation_bps,
        "anchor_note": "anchor from CEX/oracle; deviation_bps = price difference used for sanity check",
        "block_number": block_number,
    }


def run_scan_cycle(
    cycle_num: int,
    config: Dict[str, Any],
    paper_session: PaperSession,
    rpc_metrics: RPCHealthMetrics,
    output_dir: Path,
    run_mode: RunMode = RunMode.SMOKE_SIMULATOR,
) -> Dict[str, Any]:
    """Run a single scan cycle."""
    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")

    current_block = _get_simulated_block()

    logger.info(
        f"Starting scan cycle {cycle_num}",
        extra={"context": {
            "cycle": cycle_num,
            "timestamp": timestamp.isoformat(),
            "run_mode": run_mode.value,
            "block": current_block,
        }}
    )

    seen_dex_ids: Set[str] = set()

    scan_stats = {
        "cycle": cycle_num,
        "timestamp": timestamp.isoformat(),
        "run_mode": run_mode.value,
        "current_block": current_block,
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
    all_spreads: List[Dict[str, Any]] = []  # For top_opportunities fallback
    sample_rejects: List[Dict[str, Any]] = []
    sample_passed: List[Dict[str, Any]] = []

    try:
        for i in range(10):
            quote_id = f"quote_{cycle_num}_{i}_{uuid4().hex[:8]}"
            rpc_metrics.record_quote_attempt()

            dex_id = random.choice(KNOWN_DEX_IDS)
            pool_addr = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            
            seen_dex_ids.add(dex_id)

            if random.random() > 0.1:
                latency = random.randint(50, 200)
                rpc_metrics.record_success(latency_ms=latency)
                scan_stats["quotes_fetched"] += 1

                if random.random() > 0.3:
                    scan_stats["gates_passed"] += 1

                    if len(sample_passed) < MAX_FORENSIC_SAMPLES:
                        sample_passed.append(_make_forensic_sample(
                            quote_id=quote_id,
                            dex_id=dex_id,
                            pool=pool_addr,
                            token_in="WETH",
                            token_out="USDC",
                            amount_in="1000000000000000000",
                            amount_out="2500000000",
                            gas_estimate=150000,
                        ))
                else:
                    if random.random() > 0.5:
                        reason = "QUOTE_REVERT"
                        details = _make_quote_revert_details(
                            fn_or_selector="0xf7729d43",
                            params_summary="tokenIn=WETH,tokenOut=USDC,fee=500,amountIn=1e18",
                            rpc_provider_tag="alchemy_arb_1",
                            pool=pool_addr,
                            dex_id=dex_id,
                            block_number=current_block,
                            error_class="ExecutionReverted",
                            error_message="STF",
                        )
                        amount_out_val = None
                        gas_est_val = None
                    else:
                        reason = "SLIPPAGE_TOO_HIGH"
                        details = _make_slippage_details(
                            expected_out="2500000000",
                            min_out="2475000000",
                            slippage_bps=150,
                            implied_price="2500.00",
                            anchor_price="2520.00",
                            deviation_bps=79,
                            block_number=current_block,
                        )
                        amount_out_val = "2500000000"
                        gas_est_val = 150000

                    reject_histogram[reason] = reject_histogram.get(reason, 0) + 1

                    if len(sample_rejects) < MAX_FORENSIC_SAMPLES:
                        sample_rejects.append(_make_forensic_sample(
                            quote_id=quote_id,
                            dex_id=dex_id,
                            pool=pool_addr,
                            token_in="WETH",
                            token_out="USDC",
                            amount_in="1000000000000000000",
                            amount_out=amount_out_val,
                            gas_estimate=gas_est_val,
                            reject_reason=reason,
                            reject_details=details,
                        ))
            else:
                rpc_metrics.record_failure()
                reject_histogram["INFRA_RPC_ERROR"] = reject_histogram.get("INFRA_RPC_ERROR", 0) + 1

                if len(sample_rejects) < MAX_FORENSIC_SAMPLES:
                    sample_rejects.append(_make_forensic_sample(
                        quote_id=quote_id,
                        dex_id=dex_id,
                        pool=pool_addr,
                        token_in="WETH",
                        token_out="USDC",
                        amount_in="1000000000000000000",
                        amount_out=None,
                        gas_estimate=None,
                        reject_reason="INFRA_RPC_ERROR",
                        reject_details={
                            "gate_name": "rpc_call",
                            "reason_family": "INFRA",
                            "rpc_provider_tag": "alchemy_arb_1",
                            "error_class": "TimeoutError",
                            "error_message": "RPC request timed out after 5000ms",
                            "block_number": current_block,
                            "target_pool": pool_addr,
                        },
                    ))

        scan_stats["quotes_total"] = 10
        scan_stats["pools_scanned"] = 10
        scan_stats["chains_active"] = 1
        scan_stats["dexes_active"] = len(seen_dex_ids)
        scan_stats["pairs_covered"] = 5

        if scan_stats["quotes_total"] > 0:
            scan_stats["quote_fetch_rate"] = scan_stats["quotes_fetched"] / scan_stats["quotes_total"]
        if scan_stats["quotes_fetched"] > 0:
            scan_stats["quote_gate_pass_rate"] = scan_stats["gates_passed"] / scan_stats["quotes_fetched"]

        # Always generate spreads (even if not profitable) for top_opportunities
        scan_stats["spread_ids_total"] = 3
        scan_stats["signals_total"] = scan_stats["spread_ids_total"]

        # Generate 3 spreads - some profitable, some not
        for spread_idx in range(3):
            spread_id = f"spread_{cycle_num}_{timestamp_str}_{spread_idx}"
            opportunity_id = f"opp_{spread_id}"
            
            dex_buy = random.choice(KNOWN_DEX_IDS)
            dex_sell = random.choice([d for d in KNOWN_DEX_IDS if d != dex_buy])
            pool_buy = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            pool_sell = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            
            seen_dex_ids.add(dex_buy)
            seen_dex_ids.add(dex_sell)

            # First spread is profitable, others are not
            if spread_idx == 0 and random.random() > 0.3:
                pnl_usdc = format_money(Decimal("0.50"))
                pnl_bps = "50.00"
                is_profitable = True
                reject_reason = None
            else:
                pnl_usdc = format_money(Decimal("-0.10"))
                pnl_bps = "-10.00"
                is_profitable = False
                reject_reason = random.choice(["SLIPPAGE_TOO_HIGH", "GAS_TOO_HIGH", "NOT_PROFITABLE"])

            spread = {
                "spread_id": spread_id,
                "opportunity_id": opportunity_id,
                "dex_buy": dex_buy,
                "dex_sell": dex_sell,
                "pool_buy": pool_buy,
                "pool_sell": pool_sell,
                "token_in": "WETH",
                "token_out": "USDC",
                "amount_in": "100.000000",
                "amount_out": "100.50" if is_profitable else "99.90",
                "net_pnl_usdc": pnl_usdc,
                "net_pnl_bps": pnl_bps,
                "confidence": 0.85 if is_profitable else 0.45,
                "chain_id": 42161,
                "block_number": current_block,
                "is_profitable": is_profitable,
                "reject_reason": reject_reason,
            }
            all_spreads.append(spread)

            if is_profitable:
                scan_stats["spread_ids_profitable"] += 1
                scan_stats["spread_ids_executable"] += 1
                scan_stats["signals_profitable"] = scan_stats["spread_ids_profitable"]
                scan_stats["signals_executable"] = scan_stats["spread_ids_executable"]
                opportunities.append(spread)

                # Record paper trade for profitable spread
                paper_trade = PaperTrade(
                    spread_id=spread_id,
                    outcome="WOULD_EXECUTE",
                    numeraire="USDC",
                    amount_in_numeraire="100.000000",
                    expected_pnl_numeraire=pnl_usdc,
                    expected_pnl_bps=pnl_bps,
                    gas_price_gwei="0.01",
                    gas_estimate=150000,
                    chain_id=42161,
                    dex_a=dex_buy,
                    dex_b=dex_sell,
                    pool_a=pool_buy,
                    pool_b=pool_sell,
                    token_in="WETH",
                    token_out="USDC",
                    metadata={
                        "simulated": True,
                        "run_mode": run_mode.value,
                        "opportunity_id": opportunity_id,
                        "block_number": current_block,
                    },
                )
                try:
                    recorded = paper_session.record_trade(paper_trade)
                    if recorded:
                        scan_stats["paper_executable_count"] += 1
                except Exception as e:
                    logger.error(
                        f"Paper trade recording failed: {e}",
                        exc_info=True,
                        extra={"context": {"spread_id": spread_id}}
                    )

        scan_stats["dexes_active"] = len(seen_dex_ids)

    except Exception as e:
        logger.error(
            f"Cycle error: {e}",
            exc_info=True,
            extra={"context": {"cycle": cycle_num, "error_type": type(e).__name__}}
        )

    # Save scan snapshot
    snapshot_path = output_dir / "snapshots" / f"scan_{timestamp_str}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_mode": run_mode.value,
            "current_block": current_block,
            "stats": scan_stats,
            "reject_histogram": reject_histogram,
            "opportunities": opportunities,
            "all_spreads": all_spreads,
            "sample_rejects": sample_rejects,
            "sample_passed": sample_passed,
        }, f, indent=2)

    logger.info(f"Snapshot saved: {snapshot_path}")

    # Save self-contained reject histogram
    reject_path = output_dir / "reports" / f"reject_histogram_{timestamp_str}.json"
    reject_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reject_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_mode": run_mode.value,
            "timestamp": timestamp.isoformat(),
            "chain_id": 42161,
            "current_block": current_block,
            "quotes_total": scan_stats["quotes_total"],
            "quotes_fetched": scan_stats["quotes_fetched"],
            "gates_passed": scan_stats["gates_passed"],
            "histogram": reject_histogram,
        }, f, indent=2)

    # Build truth report with all_spreads fallback
    paper_stats = paper_session.get_stats()
    truth_report = build_truth_report(
        scan_stats=scan_stats,
        reject_histogram=reject_histogram,
        opportunities=opportunities,
        paper_session_stats=paper_stats,
        rpc_metrics=rpc_metrics,
        mode="REGISTRY",
        run_mode=run_mode.value,
        all_spreads=all_spreads,  # For top_opportunities fallback
    )

    truth_path = output_dir / "reports" / f"truth_report_{timestamp_str}.json"
    truth_report.save(truth_path)

    print_truth_report(truth_report)

    logger.info(
        f"Scan cycle complete: {scan_stats['quotes_fetched']}/{scan_stats['quotes_total']} fetched, "
        f"{scan_stats['gates_passed']} passed gates, {scan_stats['spread_ids_executable']} executable, "
        f"{scan_stats['dexes_active']} DEXes active",
        extra={"context": scan_stats}
    )

    return {
        "stats": scan_stats,
        "reject_histogram": reject_histogram,
        "opportunities": opportunities,
        "all_spreads": all_spreads,
        "sample_rejects": sample_rejects,
        "sample_passed": sample_passed,
    }


def run_scanner(
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    run_mode: RunMode = RunMode.SMOKE_SIMULATOR,
) -> None:
    """Run the scanner for specified number of cycles."""
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("data/runs") / timestamp
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir)

    logger.info(
        f"Scanner starting: {cycles} cycles, run_mode: {run_mode.value}, output: {output_dir}",
        extra={"context": {"cycles": cycles, "run_mode": run_mode.value, "output_dir": str(output_dir)}}
    )

    config = load_config(config_path)

    paper_session = PaperSession(
        output_dir=output_dir,
        cooldown_seconds=config.get("cooldown_seconds", 60),
        notion_capital_usdc=config.get("notion_capital_usdc", "10000.000000"),
    )

    rpc_metrics = RPCHealthMetrics()

    try:
        for cycle in range(1, cycles + 1):
            run_scan_cycle(
                cycle_num=cycle,
                config=config,
                paper_session=paper_session,
                rpc_metrics=rpc_metrics,
                output_dir=output_dir,
                run_mode=run_mode,
            )

            if cycle < cycles:
                time.sleep(1)

    except KeyboardInterrupt:
        logger.info("Scanner interrupted by user")
    finally:
        logger.info("Final session summary", extra={"context": paper_session.get_stats()})
        logger.info("Paper session summary", extra={"context": paper_session.get_pnl_summary()})
        paper_session.close()
        shutdown_logging()  # Windows file lock fix
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
        run_mode=RunMode.SMOKE_SIMULATOR,
    )


if __name__ == "__main__":
    main()
