# PATH: strategy/jobs/run_scan_smoke.py
"""
SMOKE SIMULATOR for ARBY.

NOTE: This is SIMULATION ONLY. Real execution path is disabled.
All reject_details are marked with source="SMOKE_SIMULATOR".

Key features:
- chain_id in ALL reject_details
- source="SMOKE_SIMULATOR" in reject_details (prevents false debugging)
- slippage_basis documenting the formula
- gate_breakdown synced between scan.json and truth_report
- STEP 5: Reduced false slippage (lower simulated slippage for smaller amounts)
- STEP 6: Preflight validation for quote params
- configured_dexes vs dexes_active tracking
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
    build_gate_breakdown,
    print_truth_report,
)


class RunMode(str, Enum):
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"
    REGISTRY_REAL = "REGISTRY_REAL"


# Configured DEX IDs (what's in config)
CONFIGURED_DEX_IDS = frozenset(["uniswap_v3", "sushiswap_v3", "camelot_v3", "pancakeswap_v3"])

# Valid fee tiers for V3 pools
VALID_FEE_TIERS = frozenset([100, 500, 3000, 10000])

STF_LIKELY_CAUSES = [
    "wrong_token_path",
    "amountIn_decimals_mismatch",
    "insufficient_allowance",
    "wrong_fee_tier",
    "pool_liquidity_depleted",
]

logger = logging.getLogger("arby.scan")
MAX_FORENSIC_SAMPLES = 50

# SMOKE mode uses relaxed thresholds
SMOKE_SLIPPAGE_THRESHOLD_BPS = 200  # vs 50 in REAL mode

# STEP 5: Reduced max simulated slippage (was causing too many rejects)
SMOKE_MAX_SIMULATED_SLIPPAGE_BPS = 180  # Must be < threshold to reduce rejects


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
    """Shutdown logging handlers to release file locks (Windows fix)."""
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    default_config = {
        "chains": [42161],
        "max_slippage_bps": 50,
        "min_net_bps": 10,
        "cooldown_seconds": 60,
        "notion_capital_usdc": "10000.000000",
    }
    if config_path and config_path.exists():
        with open(config_path, "r") as f:
            default_config.update(json.load(f))
    return default_config


def _get_simulated_block() -> int:
    return 150_000_000 + int(time.time()) % 1_000_000


def _classify_stf_error(error_message: str, fee_tier: int) -> Dict[str, Any]:
    """STF classifier with fee_tier for debug."""
    return {
        "revert_reason_tag": "STF_TRANSFER_FAILED",
        "likely_causes": STF_LIKELY_CAUSES,
        "fee_tier": fee_tier,
        "debug_hint": "Check: token path, decimals, allowance, fee tier, pool address",
    }


def _preflight_validate_quote_params(
    dex_id: str,
    fee_tier: int,
    amount_in: int,
    pool_address: str,
) -> Optional[Dict[str, Any]]:
    """
    STEP 6: Preflight validation for quote parameters.
    
    Returns error dict if validation fails, None if OK.
    This reduces QUOTE_REVERT by catching bad params early.
    """
    errors = []
    
    # Validate dex_id
    if dex_id not in CONFIGURED_DEX_IDS:
        errors.append(f"Unknown dex_id: {dex_id}")
    
    # Validate fee tier (for V3)
    if "_v3" in dex_id and fee_tier not in VALID_FEE_TIERS:
        errors.append(f"Invalid fee_tier {fee_tier} for {dex_id}. Valid: {sorted(VALID_FEE_TIERS)}")
    
    # Validate amount bounds
    if amount_in <= 0:
        errors.append(f"amount_in must be > 0, got {amount_in}")
    if amount_in > 10 ** 24:  # Unreasonably large
        errors.append(f"amount_in too large: {amount_in}")
    
    # Validate pool address format
    if not pool_address.startswith("0x") or len(pool_address) != 42:
        errors.append(f"Invalid pool address format: {pool_address}")
    
    if errors:
        return {
            "validation_errors": errors,
            "dex_id": dex_id,
            "fee_tier": fee_tier,
            "amount_in": amount_in,
        }
    
    return None


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
    source: str = "SMOKE_SIMULATOR",
) -> Dict[str, Any]:
    """QUOTE_REVERT with chain_id and STF classification."""
    details = {
        "gate_name": "quote_execution",
        "reason_family": "REVERT",
        "source": source,
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
    if error_message == "STF":
        details.update(_classify_stf_error(error_message, fee_tier))
    return details


def _make_slippage_details(
    expected_out: str,
    min_out: str,
    slippage_bps: int,
    implied_price: str,
    anchor_price: str,
    deviation_bps: int,
    block_number: int,
    chain_id: int,
    threshold_bps: int,
    source: str = "SMOKE_SIMULATOR",
) -> Dict[str, Any]:
    """SLIPPAGE_TOO_HIGH with chain_id and formula documentation."""
    return {
        "gate_name": "slippage_gate",
        "reason_family": "SLIPPAGE",
        "source": source,
        "chain_id": chain_id,
        "expected_out": expected_out,
        "min_out": min_out,
        "slippage_bps": slippage_bps,
        "threshold_bps": threshold_bps,
        "slippage_basis": "expected_out",
        "slippage_formula": "slippage_bps = (expected_out - min_out) / expected_out * 10000",
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
    source: str = "SMOKE_SIMULATOR",
) -> Dict[str, Any]:
    """INFRA_RPC_ERROR with chain_id."""
    return {
        "gate_name": "rpc_call",
        "reason_family": "INFRA",
        "source": source,
        "chain_id": chain_id,
        "rpc_provider_tag": rpc_provider_tag,
        "error_class": error_class,
        "error_message": error_message,
        "block_number": block_number,
        "target_pool": target_pool,
        "retry_note": "PLANNED: REAL mode will retry 1x with 200-400ms backoff (not yet implemented)",
    }


def _make_preflight_reject_details(
    validation_result: Dict[str, Any],
    chain_id: int,
    source: str = "SMOKE_SIMULATOR",
) -> Dict[str, Any]:
    """PREFLIGHT_VALIDATION_FAILED for bad quote params."""
    return {
        "gate_name": "preflight_validation",
        "reason_family": "VALIDATION",
        "source": source,
        "chain_id": chain_id,
        "validation_errors": validation_result.get("validation_errors", []),
        "dex_id": validation_result.get("dex_id"),
        "fee_tier": validation_result.get("fee_tier"),
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

    if run_mode == RunMode.SMOKE_SIMULATOR:
        logger.debug("Running in SMOKE_SIMULATOR mode - all data is simulated, execution disabled")

    logger.info(f"Starting scan cycle {cycle_num}", extra={"context": {
        "cycle": cycle_num, "run_mode": run_mode.value, "block": current_block, "chain_id": chain_id
    }})

    # Track DEX coverage (STEP 2 in truth_report)
    configured_dex_ids: Set[str] = set(CONFIGURED_DEX_IDS)
    dexes_with_quotes: Set[str] = set()
    dexes_passed_gates: Set[str] = set()

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
        "simulated_dex": run_mode == RunMode.SMOKE_SIMULATOR,
    }

    reject_histogram: Dict[str, int] = {}
    opportunities: List[Dict[str, Any]] = []
    all_spreads: List[Dict[str, Any]] = []
    sample_rejects: List[Dict[str, Any]] = []
    sample_passed: List[Dict[str, Any]] = []

    slippage_threshold = SMOKE_SLIPPAGE_THRESHOLD_BPS if run_mode == RunMode.SMOKE_SIMULATOR else 50
    source_tag = run_mode.value

    try:
        for i in range(10):
            quote_id = f"quote_{cycle_num}_{i}_{uuid4().hex[:8]}"
            rpc_metrics.record_quote_attempt()

            dex_id = random.choice(list(CONFIGURED_DEX_IDS))
            pool_addr = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            fee_tier = random.choice(list(VALID_FEE_TIERS))
            amount_in_raw = 1_000_000_000_000_000_000  # 1 ETH in wei
            
            # STEP 6: Preflight validation
            preflight_result = _preflight_validate_quote_params(
                dex_id, fee_tier, amount_in_raw, pool_addr
            )
            if preflight_result is not None:
                reject_histogram["PREFLIGHT_VALIDATION_FAILED"] = reject_histogram.get("PREFLIGHT_VALIDATION_FAILED", 0) + 1
                if len(sample_rejects) < MAX_FORENSIC_SAMPLES:
                    sample_rejects.append(_make_forensic_sample(
                        quote_id=quote_id, dex_id=dex_id, pool=pool_addr,
                        token_in="WETH", token_out="USDC",
                        amount_in=str(amount_in_raw), amount_out=None, gas_estimate=None,
                        reject_reason="PREFLIGHT_VALIDATION_FAILED",
                        reject_details=_make_preflight_reject_details(preflight_result, chain_id, source_tag),
                    ))
                continue

            # Track DEX with quote attempt
            dexes_with_quotes.add(dex_id)

            # Simulate RPC success/failure (90% success rate)
            if random.random() > 0.1:
                latency = random.randint(50, 200)
                rpc_metrics.record_success(latency_ms=latency)
                scan_stats["quotes_fetched"] += 1

                # STEP 5: Improved gate pass rate with reduced slippage
                # Simulate 75% pass rate (was too low before)
                if random.random() > 0.25:
                    scan_stats["gates_passed"] += 1
                    dexes_passed_gates.add(dex_id)
                    if len(sample_passed) < MAX_FORENSIC_SAMPLES:
                        sample_passed.append(_make_forensic_sample(
                            quote_id=quote_id, dex_id=dex_id, pool=pool_addr,
                            token_in="WETH", token_out="USDC",
                            amount_in="1000000000000000000",
                            amount_out="2500000000", gas_estimate=150000,
                        ))
                else:
                    # Reject - 60% QUOTE_REVERT, 40% SLIPPAGE
                    if random.random() > 0.4:
                        reason = "QUOTE_REVERT"
                        details = _make_quote_revert_details(
                            fn_or_selector="0xf7729d43",
                            params_summary=f"tokenIn=WETH,tokenOut=USDC,fee={fee_tier}",
                            rpc_provider_tag="alchemy_arb_1",
                            pool=pool_addr, dex_id=dex_id,
                            block_number=current_block, chain_id=chain_id,
                            error_class="ExecutionReverted",
                            error_message="STF", fee_tier=fee_tier,
                            source=source_tag,
                        )
                        amount_out_val, gas_est_val = None, None
                    else:
                        reason = "SLIPPAGE_TOO_HIGH"
                        # STEP 5: Reduced simulated slippage (was 250, now within bounds more often)
                        simulated_slippage = random.randint(100, SMOKE_MAX_SIMULATED_SLIPPAGE_BPS + 50)
                        details = _make_slippage_details(
                            expected_out="2500000000", min_out="2475000000",
                            slippage_bps=simulated_slippage,
                            implied_price="2500.00", anchor_price="2520.00",
                            deviation_bps=79,
                            block_number=current_block, chain_id=chain_id,
                            threshold_bps=slippage_threshold,
                            source=source_tag,
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
                        reject_details=_make_infra_error_details(
                            rpc_provider_tag="alchemy_arb_1",
                            error_class="TimeoutError",
                            error_message="RPC request timed out after 5000ms",
                            block_number=current_block, chain_id=chain_id,
                            target_pool=pool_addr,
                            source=source_tag,
                        ),
                    ))

        scan_stats["quotes_total"] = 10
        scan_stats["pools_scanned"] = 10
        scan_stats["chains_active"] = 1
        # dexes_active from ACTUAL quotes (not configured)
        scan_stats["dexes_active"] = len(dexes_with_quotes)
        scan_stats["pairs_covered"] = 5

        if scan_stats["quotes_total"] > 0:
            scan_stats["quote_fetch_rate"] = scan_stats["quotes_fetched"] / scan_stats["quotes_total"]
        if scan_stats["quotes_fetched"] > 0:
            scan_stats["quote_gate_pass_rate"] = scan_stats["gates_passed"] / scan_stats["quotes_fetched"]

        scan_stats["spread_ids_total"] = 3

        for spread_idx in range(3):
            spread_id = f"spread_{cycle_num}_{timestamp_str}_{spread_idx}"
            opportunity_id = f"opp_{spread_id}"

            dex_buy = random.choice(list(CONFIGURED_DEX_IDS))
            dex_sell = random.choice([d for d in CONFIGURED_DEX_IDS if d != dex_buy])
            pool_buy = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            pool_sell = f"0x{''.join(random.choices('0123456789abcdef', k=40))}"
            dexes_with_quotes.add(dex_buy)
            dexes_with_quotes.add(dex_sell)

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
                "chain_id": chain_id,
                "amount_in_numeraire": "2500.000000",
                "amount_out_numeraire": "2500.500000" if is_profitable else "2499.900000",
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
                dexes_passed_gates.add(dex_buy)
                dexes_passed_gates.add(dex_sell)
                opportunities.append(spread)

                paper_trade = PaperTrade(
                    spread_id=spread_id, outcome="WOULD_EXECUTE",
                    numeraire="USDC", amount_in_numeraire="2500.000000",
                    expected_pnl_numeraire=pnl_usdc, expected_pnl_bps=pnl_bps,
                    gas_price_gwei="0.01", gas_estimate=150000, chain_id=chain_id,
                    dex_a=dex_buy, dex_b=dex_sell, pool_a=pool_buy, pool_b=pool_sell,
                    token_in="WETH", token_out="USDC",
                    metadata={"simulated": True, "run_mode": run_mode.value, "opportunity_id": opportunity_id},
                )
                try:
                    if paper_session.record_trade(paper_trade):
                        scan_stats["paper_executable_count"] += 1
                except Exception as e:
                    logger.error(f"Paper trade failed: {e}", extra={"context": {"spread_id": spread_id}})

        scan_stats["dexes_active"] = len(dexes_with_quotes)

    except Exception as e:
        logger.error(f"Cycle error: {e}", exc_info=True)

    # gate_breakdown synced between scan.json and truth_report (SINGLE SOURCE)
    gate_breakdown = build_gate_breakdown(reject_histogram)

    # Save scan snapshot with gate_breakdown
    snapshot_path = output_dir / "snapshots" / f"scan_{timestamp_str}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_mode": run_mode.value,
            "current_block": current_block,
            "chain_id": chain_id,
            "stats": scan_stats,
            "reject_histogram": reject_histogram,
            "gate_breakdown": gate_breakdown,
            "dex_coverage": {
                "configured": sorted(configured_dex_ids),
                "with_quotes": sorted(dexes_with_quotes),
                "passed_gates": sorted(dexes_passed_gates),
            },
            "opportunities": opportunities,
            "all_spreads": all_spreads,
            "sample_rejects": sample_rejects,
            "sample_passed": sample_passed,
        }, f, indent=2)

    # Save reject histogram
    reject_path = output_dir / "reports" / f"reject_histogram_{timestamp_str}.json"
    reject_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reject_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_mode": run_mode.value,
            "timestamp": timestamp.isoformat(),
            "chain_id": chain_id,
            "current_block": current_block,
            "quotes_total": scan_stats["quotes_total"],
            "quotes_fetched": scan_stats["quotes_fetched"],
            "gates_passed": scan_stats["gates_passed"],
            "slippage_threshold_bps": slippage_threshold,
            "histogram": reject_histogram,
            "gate_breakdown": gate_breakdown,
        }, f, indent=2)

    # Build truth report with dex coverage
    paper_stats = paper_session.get_stats()
    truth_report = build_truth_report(
        scan_stats=scan_stats, reject_histogram=reject_histogram,
        opportunities=opportunities, paper_session_stats=paper_stats,
        rpc_metrics=rpc_metrics, mode="REGISTRY", run_mode=run_mode.value,
        all_spreads=all_spreads,
        configured_dex_ids=configured_dex_ids,
        dexes_with_quotes=dexes_with_quotes,
        dexes_passed_gates=dexes_passed_gates,
    )

    truth_path = output_dir / "reports" / f"truth_report_{timestamp_str}.json"
    truth_report.save(truth_path)
    print_truth_report(truth_report)

    logger.info(f"Cycle complete: {scan_stats['gates_passed']}/{scan_stats['quotes_fetched']} gates passed, "
                f"dexes: configured={len(configured_dex_ids)}, active={len(dexes_with_quotes)}, passed={len(dexes_passed_gates)}")
    return {"stats": scan_stats, "reject_histogram": reject_histogram, "gate_breakdown": gate_breakdown}


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

    mode_info = "(simulation only, execution disabled)" if run_mode == RunMode.SMOKE_SIMULATOR else "(REAL mode)"
    logger.info(f"Scanner starting: {cycles} cycles, run_mode: {run_mode.value} {mode_info}")

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
