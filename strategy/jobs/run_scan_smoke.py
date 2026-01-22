# PATH: strategy/jobs/run_scan_smoke.py
"""
SMOKE SIMULATOR for ARBY.

Key features:
<<<<<<< HEAD
- STF classifier for QUOTE_REVERT (revert_reason_tag + likely_causes)
- Unified units: amount_in_token vs amount_in_numeraire
- Adaptive slippage threshold for SMOKE mode (less strict)
- dexes_active = unique dex_ids from actual quotes
- execution_blockers explaining why not ready

Usage:
    python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data/runs/smoke
=======
- chain_id in ALL reject_details
- slippage_basis documenting the formula
- gate_breakdown synced between scan.json and truth_report
- fee_tier field in STF debug hook
- dexes_active = unique dex_ids from actual quotes (not config)
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
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

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.format_money import format_money
from strategy.paper_trading import PaperSession, PaperTrade
from monitoring.truth_report import (
    RPCHealthMetrics,
    build_truth_report,
<<<<<<< HEAD
=======
    build_gate_breakdown,
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    print_truth_report,
)


class RunMode(str, Enum):
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"
    REGISTRY_REAL = "REGISTRY_REAL"


KNOWN_DEX_IDS = ["uniswap_v3", "sushiswap_v3", "camelot_v3", "pancakeswap_v3"]

<<<<<<< HEAD
# STF Error Classification
=======
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
STF_LIKELY_CAUSES = [
    "wrong_token_path",
    "amountIn_decimals_mismatch",
    "insufficient_allowance",
    "wrong_fee_tier",
    "pool_liquidity_depleted",
]

logger = logging.getLogger("arby.scan")
MAX_FORENSIC_SAMPLES = 50
SMOKE_SLIPPAGE_THRESHOLD_BPS = 200

# SMOKE mode uses relaxed thresholds
SMOKE_SLIPPAGE_THRESHOLD_BPS = 200  # vs 50 in REAL


def setup_logging(output_dir: Optional[Path] = None, level: int = logging.INFO) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(output_dir / "scan.log", encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-9s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def shutdown_logging() -> None:
<<<<<<< HEAD
    """Windows file lock fix."""
=======
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    default_config = {
        "chains": [42161],
        "max_slippage_bps": 50,
        "min_net_bps": 10,
<<<<<<< HEAD
        "min_net_usd": "0.50",
        "min_confidence": 0.5,
=======
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
        "cooldown_seconds": 60,
        "notion_capital_usdc": "10000.000000",
    }
    if config_path and config_path.exists():
        with open(config_path, "r") as f:
            default_config.update(json.load(f))
    return default_config


def _get_simulated_block() -> int:
    return 150_000_000 + int(time.time()) % 1_000_000


<<<<<<< HEAD
def _classify_stf_error(error_message: str) -> Dict[str, Any]:
    """Classify STF (SafeTransferFrom) error with likely causes."""
    return {
        "revert_reason_tag": "STF_TRANSFER_FAILED",
        "likely_causes": STF_LIKELY_CAUSES,
=======
def _classify_stf_error(error_message: str, fee_tier: int) -> Dict[str, Any]:
    """STF classifier with fee_tier for debug."""
    return {
        "revert_reason_tag": "STF_TRANSFER_FAILED",
        "likely_causes": STF_LIKELY_CAUSES,
        "fee_tier": fee_tier,
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
        "debug_hint": "Check: token path, decimals, allowance, fee tier, pool address",
    }


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
    chain_id: int,
    error_class: str,
    error_message: str,
    fee_tier: int = 500,
) -> Dict[str, Any]:
<<<<<<< HEAD
    """QUOTE_REVERT with STF classification."""
=======
    """QUOTE_REVERT with chain_id and STF classification."""
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    details = {
        "gate_name": "quote_execution",
        "reason_family": "REVERT",
        "chain_id": chain_id,
        "fn_or_selector": fn_or_selector,
        "params_summary": params_summary,
        "rpc_provider_tag": rpc_provider_tag,
        "pool": pool,
        "dex_id": dex_id,
        "block_number": block_number,
        "error_class": error_class,
        "error_message": error_message,
        "fee_tier": fee_tier,
    }
<<<<<<< HEAD
    # STF classifier
    if error_message == "STF":
        details.update(_classify_stf_error(error_message))
=======
    if error_message == "STF":
        details.update(_classify_stf_error(error_message, fee_tier))
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    return details


def _make_slippage_details(
    expected_out: str,
    min_out: str,
    slippage_bps: int,
    implied_price: str,
    anchor_price: str,
    deviation_bps: int,
    block_number: int,
<<<<<<< HEAD
    threshold_bps: int,
) -> Dict[str, Any]:
    """SLIPPAGE_TOO_HIGH with threshold context."""
=======
    chain_id: int,
    threshold_bps: int,
) -> Dict[str, Any]:
    """SLIPPAGE_TOO_HIGH with chain_id and formula documentation."""
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    return {
        "gate_name": "slippage_gate",
        "reason_family": "SLIPPAGE",
        "chain_id": chain_id,
        "expected_out": expected_out,
        "min_out": min_out,
        "slippage_bps": slippage_bps,
        "threshold_bps": threshold_bps,
<<<<<<< HEAD
        "threshold_note": f"SMOKE mode uses {threshold_bps}bps vs 50bps in REAL",
=======
        # Formula documentation
        "slippage_basis": "expected_out",
        "slippage_formula": "slippage_bps = (expected_out - min_out) / expected_out * 10000",
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
        "implied_price": implied_price,
        "anchor_price": anchor_price,
        "deviation_bps": deviation_bps,
        "block_number": block_number,
    }


def _make_infra_error_details(
    rpc_provider_tag: str,
    error_class: str,
    error_message: str,
    block_number: int,
    chain_id: int,
    target_pool: str,
) -> Dict[str, Any]:
    """INFRA_RPC_ERROR with chain_id."""
    return {
        "gate_name": "rpc_call",
        "reason_family": "INFRA",
        "chain_id": chain_id,
        "rpc_provider_tag": rpc_provider_tag,
        "error_class": error_class,
        "error_message": error_message,
        "block_number": block_number,
        "target_pool": target_pool,
        "retry_note": "SMOKE mode: no retry; REAL mode would retry 1x with 200-400ms backoff",
    }


def run_scan_cycle(
    cycle_num: int,
    config: Dict[str, Any],
    paper_session: PaperSession,
    rpc_metrics: RPCHealthMetrics,
    output_dir: Path,
    run_mode: RunMode = RunMode.SMOKE_SIMULATOR,
) -> Dict[str, Any]:
    timestamp = datetime.now(timezone.utc)
    timestamp_str = timestamp.strftime("%Y%m%d_%H%M%S")
    current_block = _get_simulated_block()
    chain_id = 42161  # Arbitrum

    logger.info(f"Starting scan cycle {cycle_num}", extra={"context": {
<<<<<<< HEAD
        "cycle": cycle_num, "run_mode": run_mode.value, "block": current_block
=======
        "cycle": cycle_num, "run_mode": run_mode.value, "block": current_block, "chain_id": chain_id
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    }})

    # dexes_active from ACTUAL quotes, not config
    seen_dex_ids: Set[str] = set()
<<<<<<< HEAD
=======
    
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    scan_stats = {
        "cycle": cycle_num,
        "timestamp": timestamp.isoformat(),
        "run_mode": run_mode.value,
        "current_block": current_block,
        "chain_id": chain_id,
        "quotes_fetched": 0,
        "quotes_total": 0,
        "gates_passed": 0,
        "spread_ids_total": 0,
        "spread_ids_profitable": 0,
        "spread_ids_executable": 0,
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
    all_spreads: List[Dict[str, Any]] = []
    sample_rejects: List[Dict[str, Any]] = []
    sample_passed: List[Dict[str, Any]] = []

<<<<<<< HEAD
    # Adaptive slippage for SMOKE
=======
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    slippage_threshold = SMOKE_SLIPPAGE_THRESHOLD_BPS if run_mode == RunMode.SMOKE_SIMULATOR else 50

    try:
        for i in range(10):
            quote_id = f"quote_{cycle_num}_{i}_{uuid4().hex[:8]}"
            rpc_metrics.record_quote_attempt()

            dex_id = random.choice(KNOWN_DEX_IDS)
            pool_addr = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
<<<<<<< HEAD
=======
            fee_tier = random.choice([100, 500, 3000, 10000])
            
            # Track actual dex_ids from quotes
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
            seen_dex_ids.add(dex_id)

            if random.random() > 0.1:
                latency = random.randint(50, 200)
                rpc_metrics.record_success(latency_ms=latency)
                scan_stats["quotes_fetched"] += 1

<<<<<<< HEAD
                # SMOKE: higher gate pass rate (adaptive slippage)
                if random.random() > 0.2:  # 80% pass vs 70% before
=======
                if random.random() > 0.2:
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
                    scan_stats["gates_passed"] += 1
                    if len(sample_passed) < MAX_FORENSIC_SAMPLES:
                        sample_passed.append(_make_forensic_sample(
                            quote_id=quote_id, dex_id=dex_id, pool=pool_addr,
                            token_in="WETH", token_out="USDC",
                            amount_in="1000000000000000000",
                            amount_out="2500000000", gas_estimate=150000,
                        ))
                else:
                    if random.random() > 0.5:
                        reason = "QUOTE_REVERT"
                        details = _make_quote_revert_details(
                            fn_or_selector="0xf7729d43",
<<<<<<< HEAD
                            params_summary="tokenIn=WETH,tokenOut=USDC,fee=500",
                            rpc_provider_tag="alchemy_arb_1",
                            pool=pool_addr, dex_id=dex_id,
                            block_number=current_block,
=======
                            params_summary=f"tokenIn=WETH,tokenOut=USDC,fee={fee_tier}",
                            rpc_provider_tag="alchemy_arb_1",
                            pool=pool_addr, dex_id=dex_id,
                            block_number=current_block, chain_id=chain_id,
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
                            error_class="ExecutionReverted",
                            error_message="STF", fee_tier=fee_tier,
                        )
                        amount_out_val, gas_est_val = None, None
                    else:
                        reason = "SLIPPAGE_TOO_HIGH"
                        details = _make_slippage_details(
                            expected_out="2500000000", min_out="2475000000",
<<<<<<< HEAD
                            slippage_bps=250,  # Exceeds even SMOKE threshold
                            implied_price="2500.00", anchor_price="2520.00",
                            deviation_bps=79, block_number=current_block,
=======
                            slippage_bps=250, implied_price="2500.00",
                            anchor_price="2520.00", deviation_bps=79,
                            block_number=current_block, chain_id=chain_id,
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
                            threshold_bps=slippage_threshold,
                        )
                        amount_out_val, gas_est_val = "2500000000", 150000

                    reject_histogram[reason] = reject_histogram.get(reason, 0) + 1
                    if len(sample_rejects) < MAX_FORENSIC_SAMPLES:
                        sample_rejects.append(_make_forensic_sample(
                            quote_id=quote_id, dex_id=dex_id, pool=pool_addr,
                            token_in="WETH", token_out="USDC",
                            amount_in="1000000000000000000",
                            amount_out=amount_out_val, gas_estimate=gas_est_val,
                            reject_reason=reason, reject_details=details,
                        ))
            else:
                rpc_metrics.record_failure()
                reject_histogram["INFRA_RPC_ERROR"] = reject_histogram.get("INFRA_RPC_ERROR", 0) + 1
                if len(sample_rejects) < MAX_FORENSIC_SAMPLES:
                    sample_rejects.append(_make_forensic_sample(
                        quote_id=quote_id, dex_id=dex_id, pool=pool_addr,
                        token_in="WETH", token_out="USDC",
                        amount_in="1000000000000000000",
                        amount_out=None, gas_estimate=None,
                        reject_reason="INFRA_RPC_ERROR",
<<<<<<< HEAD
                        reject_details={
                            "gate_name": "rpc_call",
                            "reason_family": "INFRA",
                            "rpc_provider_tag": "alchemy_arb_1",
                            "error_class": "TimeoutError",
                            "error_message": "RPC request timed out after 5000ms",
                            "block_number": current_block,
                            "target_pool": pool_addr,
                            "retry_note": "SMOKE mode: no retry; REAL mode would retry 1x",
                        },
=======
                        reject_details=_make_infra_error_details(
                            rpc_provider_tag="alchemy_arb_1",
                            error_class="TimeoutError",
                            error_message="RPC request timed out after 5000ms",
                            block_number=current_block, chain_id=chain_id,
                            target_pool=pool_addr,
                        ),
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
                    ))

        scan_stats["quotes_total"] = 10
        scan_stats["pools_scanned"] = 10
        scan_stats["chains_active"] = 1
        # dexes_active from ACTUAL quotes (set of dex_ids)
        scan_stats["dexes_active"] = len(seen_dex_ids)
        scan_stats["pairs_covered"] = 5

        if scan_stats["quotes_total"] > 0:
            scan_stats["quote_fetch_rate"] = scan_stats["quotes_fetched"] / scan_stats["quotes_total"]
        if scan_stats["quotes_fetched"] > 0:
            scan_stats["quote_gate_pass_rate"] = scan_stats["gates_passed"] / scan_stats["quotes_fetched"]

        scan_stats["spread_ids_total"] = 3
<<<<<<< HEAD
        scan_stats["signals_total"] = 3

        # Generate spreads with unified units
=======

>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
        for spread_idx in range(3):
            spread_id = f"spread_{cycle_num}_{timestamp_str}_{spread_idx}"
            opportunity_id = f"opp_{spread_id}"

            dex_buy = random.choice(KNOWN_DEX_IDS)
            dex_sell = random.choice([d for d in KNOWN_DEX_IDS if d != dex_buy])
            pool_buy = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            pool_sell = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            seen_dex_ids.add(dex_buy)
            seen_dex_ids.add(dex_sell)

            is_profitable = spread_idx == 0 and random.random() > 0.3
            pnl_usdc = format_money(Decimal("0.50") if is_profitable else Decimal("-0.10"))
            pnl_bps = "50.00" if is_profitable else "-10.00"
            reject_reason = None if is_profitable else random.choice(["SLIPPAGE_TOO_HIGH", "NOT_PROFITABLE"])

            spread = {
                "spread_id": spread_id,
                "opportunity_id": opportunity_id,
                "dex_buy": dex_buy,
                "dex_sell": dex_sell,
                "pool_buy": pool_buy,
                "pool_sell": pool_sell,
                "token_in": "WETH",
                "token_out": "USDC",
<<<<<<< HEAD
                # Unified units
                "amount_in_token": "1.0",  # Human-readable token
                "amount_in_numeraire": "2500.000000",  # USDC notional
                "amount_out_token": "2500.50" if is_profitable else "2499.90",
                "amount_out_numeraire": "2500.500000" if is_profitable else "2499.900000",
                # Legacy compat
                "amount_in": "2500.000000",
                "amount_out": "2500.500000" if is_profitable else "2499.900000",
=======
                "chain_id": chain_id,
                # NO amount_in ambiguity - only amount_in_numeraire
                "amount_in_numeraire": "2500.000000",
                "amount_out_numeraire": "2500.500000" if is_profitable else "2499.900000",
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
                "net_pnl_usdc": pnl_usdc,
                "net_pnl_bps": pnl_bps,
                "confidence": 0.85 if is_profitable else 0.45,
                "block_number": current_block,
                "is_profitable": is_profitable,
                "reject_reason": reject_reason,
            }
            all_spreads.append(spread)

            if is_profitable:
                scan_stats["spread_ids_profitable"] += 1
                scan_stats["spread_ids_executable"] += 1
                opportunities.append(spread)

                paper_trade = PaperTrade(
                    spread_id=spread_id, outcome="WOULD_EXECUTE",
                    numeraire="USDC", amount_in_numeraire="2500.000000",
                    expected_pnl_numeraire=pnl_usdc, expected_pnl_bps=pnl_bps,
<<<<<<< HEAD
                    gas_price_gwei="0.01", gas_estimate=150000, chain_id=42161,
=======
                    gas_price_gwei="0.01", gas_estimate=150000, chain_id=chain_id,
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
                    dex_a=dex_buy, dex_b=dex_sell, pool_a=pool_buy, pool_b=pool_sell,
                    token_in="WETH", token_out="USDC",
                    metadata={"simulated": True, "run_mode": run_mode.value, "opportunity_id": opportunity_id},
                )
                try:
                    if paper_session.record_trade(paper_trade):
                        scan_stats["paper_executable_count"] += 1
                except Exception as e:
                    logger.error(f"Paper trade failed: {e}", extra={"context": {"spread_id": spread_id}})

        # Final dexes_active from all quotes
        scan_stats["dexes_active"] = len(seen_dex_ids)

    except Exception as e:
        logger.error(f"Cycle error: {e}", exc_info=True)

<<<<<<< HEAD
    # Save artifacts
=======
    # gate_breakdown synced between scan.json and truth_report
    gate_breakdown = build_gate_breakdown(reject_histogram)

    # Save scan snapshot with gate_breakdown
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    snapshot_path = output_dir / "snapshots" / f"scan_{timestamp_str}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({
<<<<<<< HEAD
            "run_mode": run_mode.value, "current_block": current_block,
            "stats": scan_stats, "reject_histogram": reject_histogram,
            "opportunities": opportunities, "all_spreads": all_spreads,
            "sample_rejects": sample_rejects, "sample_passed": sample_passed,
        }, f, indent=2)

=======
            "run_mode": run_mode.value,
            "current_block": current_block,
            "chain_id": chain_id,
            "stats": scan_stats,
            "reject_histogram": reject_histogram,
            "gate_breakdown": gate_breakdown,  # SYNCED with truth_report
            "opportunities": opportunities,
            "all_spreads": all_spreads,
            "sample_rejects": sample_rejects,
            "sample_passed": sample_passed,
        }, f, indent=2)

    # Save reject histogram
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    reject_path = output_dir / "reports" / f"reject_histogram_{timestamp_str}.json"
    reject_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reject_path, "w", encoding="utf-8") as f:
        json.dump({
<<<<<<< HEAD
            "run_mode": run_mode.value, "timestamp": timestamp.isoformat(),
            "chain_id": 42161, "current_block": current_block,
=======
            "run_mode": run_mode.value,
            "timestamp": timestamp.isoformat(),
            "chain_id": chain_id,
            "current_block": current_block,
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
            "quotes_total": scan_stats["quotes_total"],
            "quotes_fetched": scan_stats["quotes_fetched"],
            "gates_passed": scan_stats["gates_passed"],
            "slippage_threshold_bps": slippage_threshold,
            "histogram": reject_histogram,
            "gate_breakdown": gate_breakdown,
        }, f, indent=2)

<<<<<<< HEAD
=======
    # Build truth report
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)
    paper_stats = paper_session.get_stats()
    truth_report = build_truth_report(
        scan_stats=scan_stats, reject_histogram=reject_histogram,
        opportunities=opportunities, paper_session_stats=paper_stats,
        rpc_metrics=rpc_metrics, mode="REGISTRY", run_mode=run_mode.value,
        all_spreads=all_spreads,
    )

    truth_path = output_dir / "reports" / f"truth_report_{timestamp_str}.json"
    truth_report.save(truth_path)
    print_truth_report(truth_report)

<<<<<<< HEAD
    logger.info(f"Cycle complete: {scan_stats['gates_passed']}/{scan_stats['quotes_fetched']} gates passed")
    return {"stats": scan_stats, "reject_histogram": reject_histogram}
=======
    logger.info(f"Cycle complete: {scan_stats['gates_passed']}/{scan_stats['quotes_fetched']} gates passed, "
                f"dexes_active={scan_stats['dexes_active']} (from {len(seen_dex_ids)} unique dex_ids)")
    return {"stats": scan_stats, "reject_histogram": reject_histogram, "gate_breakdown": gate_breakdown}
>>>>>>> 7690cd0 (fix: <fix_10_steps_v3>)


def run_scanner(
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    run_mode: RunMode = RunMode.SMOKE_SIMULATOR,
) -> None:
    if output_dir is None:
        output_dir = Path("data/runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir)

    logger.info(f"Scanner starting: {cycles} cycles, run_mode: {run_mode.value}")

    config = load_config(config_path)
    paper_session = PaperSession(
        output_dir=output_dir,
        cooldown_seconds=config.get("cooldown_seconds", 60),
        notion_capital_usdc=config.get("notion_capital_usdc", "10000.000000"),
    )
    rpc_metrics = RPCHealthMetrics()

    try:
        for cycle in range(1, cycles + 1):
            run_scan_cycle(cycle, config, paper_session, rpc_metrics, output_dir, run_mode)
            if cycle < cycles:
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Scanner interrupted")
    finally:
        paper_session.close()
        shutdown_logging()


def main():
    parser = argparse.ArgumentParser(description="ARBY Scanner (Smoke Simulator)")
    parser.add_argument("--cycles", "-c", type=int, default=1)
    parser.add_argument("--output-dir", "-o", type=str, default=None)
    parser.add_argument("--config", "-f", type=str, default=None)
    args = parser.parse_args()

    run_scanner(
        cycles=args.cycles,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        config_path=Path(args.config) if args.config else None,
        run_mode=RunMode.SMOKE_SIMULATOR,
    )


if __name__ == "__main__":
    main()
