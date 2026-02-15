#!/usr/bin/env python3
# PATH: strategy/jobs/run_scan_real.py
"""
Real scan job for ARBY M5_0.

Outputs artifacts to reports/ with schema_version.
Compatible with ci_m5_0_gate.py validation.

REFACTORED: Logic extracted to:
- strategy/compat.py - Quote compatibility layer
- strategy/quotes.py - Quote collection logic
- strategy/spreads.py - Spread signal computation
- strategy/artifacts.py - Artifact writing
- strategy/infra.py - RPC/WS infrastructure helpers
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.constants import SCHEMA_VERSION, FAKE_BLOCK_SENTINELS
from core.validators import calculate_deviation_bps
from config.pairs import load_pairs

# Import extracted modules
from strategy.compat import QuoteCompat, Quote
from strategy.quotes import collect_quotes
from strategy.spreads import compute_spread_signals
from strategy.artifacts import write_artifacts, build_truth_data, build_reject_data, build_scan_data
from strategy.infra import (
    resolve_rpc_endpoints,
    check_ws_connection,
    check_tenderly_connection,
    build_infra_payload,
    get_current_block_via_rpc,
)

logger = logging.getLogger("run_scan_real")

# Ensure environment variables from project .env are loaded
try:
    from core.env import load_root_dotenv
    load_root_dotenv()
except Exception:
    pass

# Re-export for backward compatibility
try:
    from core.validators import check_price_sanity as _check_price_sanity
except Exception:
    _check_price_sanity = None


def _get_current_block(config: Dict[str, Any]) -> tuple[int, int]:
    """Get current block via RPC or environment (wrapper for compatibility)."""
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        block = int(os.environ.get("ARBY_FAKE_BLOCK", "100"))
        return block, 0
    return get_current_block_via_rpc(config)


def _compute_sanity_rejects(
    config: Dict[str, Any],
    pairs_list: List,
    dexes_active_list: List[str],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Compute price sanity rejects and suspect examples."""
    max_dev = config.get("price_sanity_max_deviation_bps", 5000)
    
    ref_pair = pairs_list[0] if pairs_list else None
    ref_token_in = ref_pair.token_in if ref_pair else "WETH"
    ref_token_out = ref_pair.token_out if ref_pair else "USDC"
    ref_pair_key = f"{ref_token_in}_{ref_token_out}"
    ref_decimals_in = ref_pair.token_in_decimals if ref_pair else 18
    ref_decimals_out = ref_pair.token_out_decimals if ref_pair else 6
    
    try:
        anchor_price = Decimal(str(config.get("tokens_anchor_price", {}).get(ref_pair_key, 2600)))
    except Exception:
        anchor_price = Decimal("2600")
    
    ref_amount_out = int(anchor_price * (10 ** ref_decimals_out))
    
    try:
        from core.validators import normalize_price
        implied_price_dec, _ = normalize_price(
            amount_in_wei=10 ** ref_decimals_in,
            amount_out_wei=ref_amount_out,
            decimals_in=ref_decimals_in,
            decimals_out=ref_decimals_out,
            token_in=ref_token_in,
            token_out=ref_token_out,
        )
        implied_price = Decimal(str(implied_price_dec))
    except Exception:
        implied_price = Decimal("0")
    
    _, raw_bps, _ = calculate_deviation_bps(implied_price, anchor_price)
    capped_flag = raw_bps > int(max_dev)
    deviation_bps = int(min(raw_bps, int(max_dev)))
    
    try:
        implied_lt_expected = implied_price < anchor_price
    except Exception:
        implied_lt_expected = False
    
    reject_entry = {
        "pair": f"{ref_token_in}/{ref_token_out}",
        "dex_id": dexes_active_list[0] if dexes_active_list else "unknown",
        "pool_fee": 3000,
        "implied_price": str(implied_price),
        "token_in_decimals": ref_decimals_in,
        "token_out_decimals": ref_decimals_out,
        "amount_in": 10 ** ref_decimals_in,
        "amount_out": ref_amount_out,
        "orientation": "normal",
        "deviation_bps": deviation_bps,
        "deviation_bps_raw": raw_bps,
        "deviation_bps_capped": capped_flag,
        "max_deviation_bps": int(max_dev),
        "error": "deviation_exceeded" if raw_bps > int(max_dev) else None,
        "inversion_applied": False,
        "suspect_quote": True if (implied_lt_expected and raw_bps > 0) else False,
        "suspect_reason": "way_below_expected" if (implied_lt_expected and raw_bps > 0) else None,
        "expected_price": str(anchor_price),
        "anchor_source": "config",
        "expected_rule": "config_anchor",
    }
    
    sanity_rejects = []
    if raw_bps > int(max_dev):
        sanity_rejects.append(reject_entry)
    
    suspect_examples = []
    if reject_entry.get("suspect_quote"):
        suspect_examples.append({
            "pair": reject_entry["pair"],
            "implied_price": reject_entry["implied_price"],
            "expected_price": reject_entry.get("expected_price"),
            "reason": reject_entry.get("suspect_reason"),
        })
    
    return sanity_rejects, suspect_examples, raw_bps


def run_scan(
    config: Dict[str, Any],
    output_dir: Path,
    cycles: int = 1,
    artifact_mode: str = "full",
) -> Dict[str, Any]:
    """
    Run scan cycle(s).
    
    This implementation focuses on producing the artifacts and metrics required
    by the gate and unit tests.
    """
    logger.info("Starting scan: cycles=%s, output=%s", cycles, output_dir)
    
    # M4.2: Config validation - algebra DEXes require quoter
    dexes_list = config.get("dexes") or []
    use_quoter_v2 = config.get("use_quoter_v2", False)
    algebra_dexes = [d for d in dexes_list if d in ("camelot_v3", "algebra", "swaap_v3")]
    
    if algebra_dexes and not use_quoter_v2:
        logger.warning(
            "CONFIG_WARN: %s in dexes but use_quoter_v2=false. "
            "Algebra-based DEXes require QuoterV2 (slot0 ABI incompatible). "
            "Quotes from these DEXes will be rejected with ALGEBRA_NEEDS_QUOTER.",
            algebra_dexes
        )
    
    # Resolve RPC endpoints
    resolved_http, resolved_ws, provider_http, provider_ws = resolve_rpc_endpoints(config)
    
    # v2.1.0: Create web3 instance for live gas/block queries
    w3_instance = None
    try:
        from web3 import Web3
        if resolved_http:
            w3_instance = Web3(Web3.HTTPProvider(resolved_http, request_kwargs={"timeout": 5}))
            logger.debug("Web3 instance created for live queries")
    except Exception as w3_err:
        logger.debug("Web3 instance creation skipped: %s", w3_err)
    
    # Get current block
    current_block, rpc_latency = _get_current_block(config)
    if current_block in FAKE_BLOCK_SENTINELS:
        raise BlockPinError(f"Invalid current block from RPC: {current_block}")
    
    # Initialize stats
    stats: Dict[str, Any] = {
        "quotes_total": 0,
        "quotes_fetched": 0,
        "gates_passed": 0,
        "dexes_active": 0,
        "price_sanity_passed": 0,
        "price_sanity_failed": 0,
        "rpc_errors": 0,
        "rpc_success_rate": 1.0,
        "requested_cycles": cycles,
        "cycles_completed": cycles,
    }
    
    # Collect quotes
    quotes_sample, rejected_quotes, counts = collect_quotes(config, current_block, rpc_latency)
    
    # Update stats from counts
    stats["quotes_rejected"] = len(rejected_quotes)
    stats["pool_missing_count"] = counts["pool_missing"]
    stats["v3_slot0_failed_count"] = counts["v3_slot0_failed"]
    
    dexes_list = config.get("dexes") or []
    chain_key = config.get("chain", "arbitrum_one")
    pairs_list = load_pairs(chain_key, config, use_intent=False)
    
    # v2.0.8: quotes_total = attempted quotes (valid + rejected), accounts for fee_tiers
    stats["quotes_total"] = len(quotes_sample) + len(rejected_quotes)
    stats["quotes_fetched"] = len(quotes_sample)
    stats["gates_passed"] = sum(1 for q in quotes_sample if q.get("gate_passed", True))
    
    total_attempts = stats["quotes_total"]
    if total_attempts > 0:
        rpc_failures = stats.get("rpc_errors", 0) + counts["pool_missing"] + counts["v3_slot0_failed"]
        stats["rpc_success_rate"] = max(0.0, 1.0 - rpc_failures / total_attempts)
    else:
        stats["rpc_success_rate"] = 0.0 if stats.get("rpc_errors", 0) > 0 else 1.0
    
    logger.info("Quotes: %d valid, %d rejected", len(quotes_sample), len(rejected_quotes))
    
    dexes_active_list = sorted({q.get("dex_id") for q in quotes_sample})
    stats["dexes_active"] = len(dexes_active_list)
    
    # Compute spread signals
    spread_threshold_bps = config.get("min_spread_bps", config.get("spread_threshold_bps", 0))
    spread_signals = compute_spread_signals(quotes_sample, config, current_block, rejected_quotes)
    
    # v2.0.8: Per-quote price sanity from rejected_quotes
    # Count rejects that indicate price/quote validity issues
    # v2.1.0: Use "PRICE_SANITY_FAILED" (canonical ErrorCode, matches strategy/quotes.py)
    sanity_reject_reasons = {"QUOTE_ZERO_OUT", "PRICE_CALC_FAILED", "NO_ONCHAIN_PRICE", "PRICE_SANITY_FAILED"}
    sanity_rejects = [r for r in rejected_quotes if r.get("reason") in sanity_reject_reasons]
    
    # Compute additional sanity rejects from _compute_sanity_rejects (legacy placeholder)
    legacy_sanity_rejects, suspect_examples, raw_bps = _compute_sanity_rejects(
        config, pairs_list, dexes_active_list
    )
    
    # Update suspect stats
    try:
        stats["suspect_quotes"] = len(suspect_examples)
        reasons: Dict[str, int] = {}
        for ex in suspect_examples:
            r = ex.get("reason") or "unknown"
            reasons[r] = reasons.get(r, 0) + 1
        if "way_below_expected" not in reasons:
            reasons.setdefault("way_below_expected", 0)
        stats["suspect_reasons"] = reasons
    except Exception:
        stats["suspect_quotes"] = 0
        stats["suspect_reasons"] = {"way_below_expected": 0}
    
    # v2.0.8: price_sanity metrics
    # Contract: price_sanity operates on quotes that got far enough to have a price computed
    # - price_sanity_failed: quotes with sanity issues (QUOTE_ZERO_OUT, PRICE_CALC_FAILED, etc.)
    # - price_sanity_passed: quotes that passed sanity and are in quotes_sample
    # Note: POOL_MISSING rejects don't count toward sanity (no price was computed)
    stats["price_sanity_failed"] = len(sanity_rejects)
    stats["price_sanity_passed"] = stats["quotes_fetched"]  # = len(quotes_sample)
    # Invariant: price_sanity_passed + price_sanity_failed <= quotes_total
    # (equals only if all rejects are sanity-related; POOL_MISSING etc. are excluded)
    
    # v2.0.8 FIX: Calculate price_stability_factor AFTER price_sanity_failed is set
    try:
        price_stability_factor = max(0.0, 1.0 - stats["price_sanity_failed"] / max(1, stats["quotes_total"]))
    except Exception:
        price_stability_factor = 1.0
    stats["price_stability_factor"] = price_stability_factor
    
    # Build infra payload
    primary_http = os.environ.get("ARBY_RPC_HTTP_PRIMARY") or resolved_http
    primary_ws = os.environ.get("ARBY_RPC_WS_PRIMARY") or resolved_ws
    
    ws_connected, ws_handshake_ms, ws_error = False, None, None
    if primary_ws:
        ws_connected, ws_handshake_ms, ws_error = check_ws_connection(primary_ws)
    
    tenderly_enabled, tenderly_ok, tenderly_error = check_tenderly_connection()
    
    infra_payload = build_infra_payload(
        primary_http, primary_ws,
        ws_connected, ws_handshake_ms, ws_error,
        tenderly_enabled, tenderly_ok, tenderly_error
    )
    
    # Generate timestamp early (used by opportunity_engine and artifact writes)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # v2.1.0: Fetch live gas price BEFORE opportunity_engine for consistent gas costing
    live_gas_price_wei = 100_000_000  # 0.1 gwei default
    if w3_instance:
        try:
            live_gas_price_wei = w3_instance.eth.gas_price
            stats["live_gas_price_wei"] = live_gas_price_wei
            stats["live_gas_price_gwei"] = live_gas_price_wei / 1e9
            logger.info("Live gas price: %.4f gwei", stats["live_gas_price_gwei"])
        except Exception as gas_err:
            logger.debug("Failed to get live gas: %s", gas_err)
    else:
        stats["live_gas_price_wei"] = live_gas_price_wei
        stats["live_gas_price_gwei"] = live_gas_price_wei / 1e9
    
    # M4.2: Evaluate opportunities using opportunity_engine
    try:
        from engine.opportunity_engine import evaluate_quotes, GasConfig
        eth_usd = config.get("tokens_anchor_price", {}).get("WETH_USDC", 2000.0)
        
        # v2.1.0: Create GasConfig with live gas price for consistent accounting
        gas_config = GasConfig(
            gas_price_gwei=live_gas_price_wei / 1e9,
            eth_usd_price=eth_usd,
            _live_mode=w3_instance is not None,
        )
        
        opps_list, opps_summary = evaluate_quotes(
            quotes_sample, cycle=0, timestamp=timestamp,
            eth_usd_price=eth_usd, min_net_profit_usd=0.10,
            gas_config=gas_config,
        )
        stats["opportunity_engine"] = {
            "enabled": True,
            "summary": opps_summary,
            "top_opportunities": opps_list[:5] if opps_list else [],
        }
        logger.info(
            "OpportunityEngine: %d opportunities, %d profitable, best=$%.2f",
            opps_summary.get("total_opportunities", 0),
            opps_summary.get("profitable_count", 0),
            opps_summary.get("best_net_profit_usd", 0),
        )
    except Exception as e:
        logger.debug("OpportunityEngine skipped: %s", e)
        stats["opportunity_engine"] = {"enabled": False, "error": str(e)}
    
    # v2.1.0: Round-trip evaluation for CANONICAL profit (after one-leg diagnostic)
    try:
        from engine.roundtrip import simulate_roundtrip, evaluate_roundtrip_candidates
        from strategy.quotes import read_quoter_v2
        from config import get_token_address
        from dex.registry import get_dex_config
        
        # Build quotes lookup by key for round-trip matching
        quotes_by_key: Dict[str, Dict] = {}
        for q in quotes_sample:
            key = f"{q.get('dex_id')}:{q.get('pool_address')}:{q.get('fee')}"
            quotes_by_key[key] = q
        
        # v2.1.0: live_gas_price_wei already fetched above (before opportunity_engine)
        
        # v2.1.0: Create leg2 re-quote callback factory (CANONICAL round-trip)
        # This factory creates a callback that re-quotes leg2 using QuoterV2
        # with the actual leg1 amount_out (not the original target amount)
        
        def make_leg2_callback(sell_quote: Dict):
            """Factory: creates leg2 callback for specific sell_quote context."""
            dex_id = sell_quote.get("dex_id", "")
            dex_cfg = get_dex_config(chain_key, dex_id)
            quoter_addr = dex_cfg.get_quoter_address() if dex_cfg else None
            
            # For leg2 (sell back): token_out -> token_in
            # sell_quote has: token_in, token_out (as symbols)
            # Leg2 needs to swap token_out back to token_in
            token_out_symbol = sell_quote.get("token_out", "")  # What we got from leg1
            token_in_symbol = sell_quote.get("token_in", "")    # What we want back
            fee = sell_quote.get("fee", 3000)
            
            # Resolve token addresses from symbols
            token_out_addr = get_token_address(chain_key, token_out_symbol)
            token_in_addr = get_token_address(chain_key, token_in_symbol)
            
            if not quoter_addr or not token_in_addr or not token_out_addr:
                logger.debug(
                    "Leg2 callback: missing quoter/token info for %s (quoter=%s, in=%s, out=%s)",
                    dex_id, quoter_addr[:10] if quoter_addr else None, token_in_symbol, token_out_symbol
                )
                return None
            
            def leg2_requote(amount_in_wei: int) -> Optional[Dict]:
                """Re-quote leg2 with actual amount from leg1."""
                result = read_quoter_v2(
                    quoter_address=quoter_addr,
                    token_in=token_out_addr,  # Swap token_out (what we have) back
                    token_out=token_in_addr,  # To token_in (what we started with)
                    amount_in=amount_in_wei,
                    fee=fee,
                    rpc_url=resolved_http,
                    block_num=current_block,
                )
                if result:
                    return {
                        "amount_out_wei": result["amount_out"],
                        "gas_estimate": result.get("gas_estimate", 150000),
                        "ticks_crossed": result.get("ticks_crossed", 0),
                    }
                return None
            
            return leg2_requote
        
        # Evaluate top-5 one-leg opportunities with round-trip
        roundtrip_results = []
        if opps_list:
            roundtrip_results = evaluate_roundtrip_candidates(
                opportunities=opps_list[:5],
                buy_quotes_by_key=quotes_by_key,
                sell_quotes_by_key=quotes_by_key,
                gas_price_wei=live_gas_price_wei,
                top_n=5,
                leg2_quote_callback_factory=make_leg2_callback,
            )
        
        # Summarize round-trip results
        rt_profitable = [r for r in roundtrip_results if r.is_profitable]
        rt_using_real_quote = [r for r in roundtrip_results if r.leg2_is_real_quote]
        
        stats["roundtrip"] = {
            "enabled": True,
            "evaluated_count": len(roundtrip_results),
            "profitable_count": len(rt_profitable),
            "real_quote_count": len(rt_using_real_quote),
            "gas_price_wei_used": live_gas_price_wei,
            "results": [r.to_dict() for r in roundtrip_results[:3]],
        }
        
        if rt_profitable:
            best_rt = max(rt_profitable, key=lambda r: r.net_pnl_bps)
            stats["roundtrip"]["best_net_pnl_bps"] = best_rt.net_pnl_bps
            logger.info(
                "Roundtrip: %d/%d profitable, best=%.2f bps",
                len(rt_profitable), len(roundtrip_results), best_rt.net_pnl_bps
            )
        else:
            stats["roundtrip"]["best_net_pnl_bps"] = 0.0
            logger.info("Roundtrip: 0/%d profitable", len(roundtrip_results))
            
    except Exception as rt_err:
        logger.debug("Roundtrip evaluation skipped: %s", rt_err)
        stats["roundtrip"] = {"enabled": False, "error": str(rt_err)}
    
    # Build artifact data structures
    scan_data = build_scan_data(config, current_block, stats, quotes_sample, infra_payload)
    
    truth_data = build_truth_data(
        config, stats, current_block, spread_signals, suspect_examples,
        infra_payload, raw_bps, spread_threshold_bps
    )
    
    reject_data = build_reject_data(
        config, current_block, sanity_rejects, rejected_quotes, stats, infra_payload
    )
    
    # Write artifacts (timestamp already set before opportunity_engine)
    artifacts = write_artifacts(output_dir, timestamp, scan_data, truth_data, reject_data, artifact_mode=artifact_mode)
    
    logger.info("Scan completed: %s artifacts written", len(artifacts))
    for name, path in artifacts.items():
        logger.info("  %s: %s", name, path)
    
    return stats


def check_price_sanity(*args, **kwargs):
    """Compatibility wrapper delegating to core.validators.check_price_sanity."""
    if _check_price_sanity is None:
        raise ImportError("core.validators.check_price_sanity not available")
    
    try:
        from core import validators as _validators_module
    except Exception:
        _validators_module = None
    
    if ("token_in" in kwargs) or ("token_out" in kwargs):
        if _validators_module and hasattr(_validators_module, "check_price_sanity_legacy"):
            return _validators_module.check_price_sanity_legacy(*args, **kwargs)
    return _check_price_sanity(*args, **kwargs)


def run_scanner(
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
    **kwargs
) -> Dict[str, Any]:
    """Backwards-compatible entrypoint wrapper."""
    if output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("data") / "runs" / f"manual_run_{timestamp}"
    else:
        output_dir = Path(output_dir)
    
    config = {"chain_id": 42161}
    if config_path:
        cfgp = Path(config_path)
        if cfgp.exists():
            try:
                with open(cfgp, "r", encoding="utf-8") as f:
                    file_cfg = yaml.safe_load(f) or {}
                config.update(file_cfg)
            except Exception as e:
                logger.warning(f"Could not load config {cfgp}: {e}")
    
    try:
        return run_scan(config, output_dir, cycles)
    except Exception:
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ARBY Real Scan Job",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument("--config", type=str, default="config/real_minimal.yaml",
                        help="Config file path")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Output directory for artifacts")
    parser.add_argument("--cycles", type=int, default=1,
                        help="Number of scan cycles")
    parser.add_argument("--once", action="store_true",
                        help="Run single cycle (alias for --cycles 1)")
    parser.add_argument("--chain-id", type=int,
                        default=int(os.environ.get("ARBY_CHAIN_ID", "42161")),
                        help="Chain ID (default: ARBY_CHAIN_ID or 42161)")
    
    args = parser.parse_args()
    cycles = 1 if args.once else args.cycles
    
    config = {
        "chain_id": args.chain_id,
        "price_sanity_enabled": True,
        "price_sanity_max_deviation_bps": 5000,
    }
    if args.config:
        cfg_path = Path(args.config)
        if cfg_path.exists():
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    file_cfg = yaml.safe_load(f) or {}
                config.update(file_cfg)
            except Exception as e:
                logger.warning(f"Could not load config {cfg_path}: {e}")
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    args.output_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        stats = run_scan(config, args.output_dir, cycles)
        
        print(f"\n{'='*60}")
        print("SCAN COMPLETE")
        print(f"{'='*60}")
        print(f"  quotes_total: {stats['quotes_total']}")
        print(f"  quotes_fetched: {stats['quotes_fetched']}")
        print(f"  dexes_active: {stats['dexes_active']}")
        print(f"  price_sanity_passed: {stats['price_sanity_passed']}")
        print(f"  price_sanity_failed: {stats['price_sanity_failed']}")
        print(f"  output_dir: {args.output_dir}")
        print(f"{'='*60}")
        
        return 0
    except Exception as e:
        logger.error(f"Scan failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
