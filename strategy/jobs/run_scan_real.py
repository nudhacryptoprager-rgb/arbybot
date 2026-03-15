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
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.constants import SCHEMA_VERSION, FAKE_BLOCK_SENTINELS
from core.no_data import compute_no_data_reason, canonicalize_config_path
from config.pairs import load_pairs
from config import load_core_tokens

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


def _extract_suspect_from_rejects(
    sanity_rejects: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], int]:
    """Extract suspect examples and max deviation bps from real rejected quotes.

    Only uses actual PRICE_SANITY_FAILED rejects — no synthetic fabrication.
    Returns (suspect_examples, raw_bps_max).
    """
    suspect_examples: List[Dict[str, Any]] = []
    raw_bps_max = 0
    for r in sanity_rejects:
        dev = r.get("deviation_bps", 0) or 0
        if dev > raw_bps_max:
            raw_bps_max = dev
        suspect_examples.append({
            "pair": r.get("pair"),
            "implied_price": r.get("price_exact"),
            "expected_price": r.get("anchor_price"),
            "reason": r.get("reason", "PRICE_SANITY_FAILED"),
        })
    return suspect_examples, raw_bps_max


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
    
    _phase_t0 = _time.monotonic()  # Phase timing: scan start
    
    # M4.2: Config validation - algebra DEXes require quoter
    dexes_list = config.get("dexes") or []
    use_quoter_v2 = config.get("use_quoter_v2", False)
    truth_mode_m42 = config.get("truth_mode_m42", False)  # v2.2.0 Fix Step 5
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
    
    # v2.6.0: Resolve universe BEFORE collect_quotes() so resolved pairs are used
    dexes_list = config.get("dexes") or []
    
    # v3.2.7: Strict chain_key contract - warn if missing in ONLINE mode
    chain_key = config.get("chain")
    if chain_key is None:
        chain_key = "unknown"
        logger.warning("chain_key not specified in config - using 'unknown'. Set config['chain'] for multi-chain observability.")
    
    # v3.2.7: Include chain_key in stats for artifact observability
    stats["chain_key"] = chain_key
    
    # v3.2.10: run_kind for smoke run isolation (NORM-only rolling policy)
    # Valid values: NORMAL, SMOKE, COVERAGE (see m4.policy.RunKind)
    # SMOKE runs are excluded from rolling window to avoid polluting KPIs
    run_kind = config.get("run_kind", "NORMAL")
    stats["run_kind"] = run_kind
    if run_kind == "SMOKE":
        logger.info("run_kind=SMOKE: this run will be excluded from rolling window")
    
    # R28: Universe Discovery — two canonical paths (see docs/WORKFLOW.md):
    #   config            → hardcoded pairs + pre-verified pools (Arbitrum production)
    #   discovery_runtime  → intent.txt → factory RPC → RuntimePair (chain bring-up, canonical successor)
    universe_source = config.get("universe_source", "config")
    use_intent = (universe_source == "intent")
    force_intent = (universe_source in ("intent_verified", "intent_forced"))
    use_discovery_runtime = (universe_source == "discovery_runtime")
    
    # R27.3: Forbid intent/intent_forced for NORMAL/COVERAGE runs (no on-chain verify)
    if universe_source in ("intent", "intent_forced") and run_kind in ("NORMAL", "COVERAGE"):
        raise RuntimeError(
            f"universe_source='{universe_source}' is forbidden for run_kind={run_kind}. "
            "Intent-based universes lack on-chain verification. "
            "Use 'config' or 'discovery_runtime'."
        )
    
    # Resolve pairs based on universe_source BEFORE quoting
    _discovery_runtime_resolved = []
    _discovery_runtime_stats = None
    pairs_list = None
    
    if use_discovery_runtime:
        try:
            from discovery.runtime import resolve_runtime_pairs, runtime_pairs_to_pair_configs
            
            max_pairs = config.get("discovery_runtime_max_pairs", 20)
            require_cross_dex = config.get("require_cross_dex", False)
            excluded_hints = config.get("excluded_pair_hints") or []
            _discovery_runtime_resolved, _discovery_runtime_stats = resolve_runtime_pairs(
                chain=chain_key,
                dexes=dexes_list if dexes_list else None,
                max_pairs=max_pairs,
                require_cross_dex=require_cross_dex,
                excluded_pair_hints=excluded_hints,
            )
            pairs_list = runtime_pairs_to_pair_configs(_discovery_runtime_resolved)
            
            logger.info(
                "Using discovery_runtime universe (%d pools resolved -> %d unique pairs for quoting)",
                len(_discovery_runtime_resolved),
                len(pairs_list),
            )
            stats["universe_source"] = "discovery_runtime"
            stats["discovery_runtime_pairs_count"] = len(pairs_list)
            stats["discovery_runtime_pools_resolved"] = len(_discovery_runtime_resolved)
            if _discovery_runtime_stats:
                stats["discovery_runtime"] = _discovery_runtime_stats.to_dict()
        except Exception as dr_err:
            allow_fallback = config.get("discovery_runtime_allow_fallback", False)
            if allow_fallback:
                logger.warning("discovery_runtime failed, falling back to config (allowed by config): %s", dr_err)
                pairs_list = load_pairs(chain_key, config, use_intent=False, force_intent=False)
                stats["universe_source"] = "config (discovery_runtime fallback)"
                stats["discovery_runtime_error"] = str(dr_err)
            else:
                logger.error("discovery_runtime failed (strict mode, no fallback): %s", dr_err)
                stats["universe_source"] = "discovery_runtime_failed"
                stats["discovery_runtime_error"] = str(dr_err)
                raise RuntimeError(
                    f"discovery_runtime resolution failed and fallback is disabled: {dr_err}"
                ) from dr_err
    elif force_intent:
        pairs_list = load_pairs(chain_key, config, use_intent=use_intent, force_intent=force_intent)
        logger.info("Using intent.txt universe FORCED (universe_source=%s -> intent_forced, %d pairs)", universe_source, len(pairs_list))
        stats["universe_source"] = "intent_forced"
        stats["intent_pairs_count"] = len(pairs_list)
        stats["intent_on_chain_verified"] = False
    elif use_intent:
        pairs_list = load_pairs(chain_key, config, use_intent=use_intent, force_intent=force_intent)
        logger.info("Using intent.txt universe (universe_source=intent)")
        stats["universe_source"] = "intent"
    else:
        # Default: config pairs (let collect_quotes load them)
        pairs_list = None
        logger.debug("Using config pairs (universe_source=config)")
        stats["universe_source"] = "config"
    
    # R27.3: Encode strategy mode for artifact observability
    _us = stats["universe_source"]
    if _us == "discovery_runtime":
        stats["strategy_mode"] = "DYNAMIC_VERIFIED"
    elif _us in ("intent", "intent_forced"):
        stats["strategy_mode"] = "BOOTSTRAP"
    elif _us.startswith("config"):
        stats["strategy_mode"] = "TRUTH_PROBE"
    else:
        stats["strategy_mode"] = "UNKNOWN"
    stats["same_dex_only"] = not config.get("require_cross_dex", True)
    
    _phase_discovery_end = _time.monotonic()
    
    # Collect quotes with resolved pairs
    _phase_quote_start = _time.monotonic()
    quotes_sample, rejected_quotes, counts = collect_quotes(config, current_block, rpc_latency, pairs_list=pairs_list)
    
    # Update stats from counts
    stats["quotes_rejected"] = len(rejected_quotes)
    stats["pool_missing_count"] = counts["pool_missing"]
    stats["pool_disabled_count"] = counts.get("pool_disabled", 0)
    stats["quarantined_count"] = counts.get("quarantined", 0)
    stats["v3_slot0_failed_count"] = counts["v3_slot0_failed"]
    # v2.3.0: Track failed pool addresses for actionable diagnostics
    stats["failed_pool_addresses"] = counts.get("failed_pool_addresses", [])
    # v2.3.2: Track pool_missing_keys for observability (what pools were skipped)
    stats["pool_missing_keys"] = counts.get("pool_missing_keys", [])
    stats["pool_missing_keys_total"] = counts.get("pool_missing_keys_total", 0)
    
    # v2.0.8: quotes_total = attempted quotes (valid + rejected), accounts for fee_tiers
    stats["quotes_total"] = len(quotes_sample) + len(rejected_quotes)
    stats["quotes_fetched"] = len(quotes_sample)
    stats["gates_passed"] = sum(1 for q in quotes_sample if q.get("gate_passed", True))
    
    # v2.2.2: Config transparency - propagate to scan.stats for cross-artifact consistency
    stats["require_cross_dex"] = config.get("require_cross_dex", False)
    # v3.2.7: Canonicalize to POSIX format for OS-independent comparison
    stats["config_path"] = canonicalize_config_path(config.get("_config_path", None))
    # v2.3.0: Sizing params for audit trail
    stats["use_usd_notional"] = config.get("use_usd_notional", False)
    stats["target_usd_notional"] = config.get("target_usd_notional", None)
    # v3.2.0: Enhanced observability - config transparency
    stats["min_spread_bps"] = config.get("min_spread_bps", config.get("spread_threshold_bps", 0))
    stats["paper_size_usd"] = config.get("paper_size_usd", None)
    stats["default_fee_tiers"] = config.get("default_fee_tiers", [])
    stats["runtime_disabled_count"] = counts.get("runtime_disabled", 0)
    stats["liquidity_zero_count"] = counts.get("liquidity_zero", 0)
    
    # v2.3.1: Quote block skew for snapshot consistency validation
    # Measures how many blocks elapsed during quote collection
    quote_blocks = [q.get("block_number") for q in quotes_sample if q.get("block_number")]
    if quote_blocks:
        stats["quote_block_skew"] = max(quote_blocks) - min(quote_blocks)
    else:
        stats["quote_block_skew"] = 0
    
    total_attempts = stats["quotes_total"]
    if total_attempts > 0:
        rpc_failures = stats.get("rpc_errors", 0) + counts["pool_missing"] + counts["v3_slot0_failed"]
        stats["rpc_success_rate"] = max(0.0, 1.0 - rpc_failures / total_attempts)

    else:
        stats["rpc_success_rate"] = 0.0 if stats.get("rpc_errors", 0) > 0 else 1.0
    
    logger.info("Quotes: %d valid, %d rejected", len(quotes_sample), len(rejected_quotes))
    
    _phase_quote_end = _time.monotonic()
    
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
    
    # Extract suspect examples from real sanity rejects (no synthetic fabrication)
    suspect_examples, raw_bps = _extract_suspect_from_rejects(sanity_rejects)
    
    # Update suspect stats from real data
    stats["suspect_quotes"] = len(suspect_examples)
    reasons: Dict[str, int] = {}
    for ex in suspect_examples:
        r = ex.get("reason") or "unknown"
        reasons[r] = reasons.get(r, 0) + 1
    stats["suspect_reasons"] = reasons
    
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
    
    # v3.2.7: Compute no_data_reason for deterministic NO_DATA classification
    # Uses centralized helper from core/no_data.py to avoid logic duplication
    stats["no_data_reason"] = compute_no_data_reason(
        quotes_total=stats["quotes_total"],
        quotes_fetched=stats["quotes_fetched"],
        spread_signals_count=len(spread_signals),
    )
    
    # Build infra payload
    # v3.2.33: resolved_http takes priority over env var (config rpc_endpoints contract)
    primary_http = resolved_http or os.environ.get("ARBY_RPC_HTTP_PRIMARY")
    primary_ws = resolved_ws or os.environ.get("ARBY_RPC_WS_PRIMARY")
    
    ws_connected, ws_handshake_ms, ws_error = False, None, None
    if primary_ws:
        ws_connected, ws_handshake_ms, ws_error = check_ws_connection(primary_ws)
    
    tenderly_enabled, tenderly_ok, tenderly_error = check_tenderly_connection()
    
    infra_payload = build_infra_payload(
        primary_http, primary_ws,
        ws_connected, ws_handshake_ms, ws_error,
        tenderly_enabled, tenderly_ok, tenderly_error,
        provider_http=provider_http,  # v2.2.0 Fix Step 4: actually used provider
        provider_ws=provider_ws,
        config=config,
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
        
        # v2.1.0: Create GasConfig with live gas price and L1 params from config
        l1_data_gas_units = config.get("l1_data_gas_units", 2000)
        l1_gas_price_gwei = config.get("l1_gas_price_gwei", 30.0)
        gas_config = GasConfig(
            gas_price_gwei=live_gas_price_wei / 1e9,
            eth_usd_price=eth_usd,
            l1_data_gas_units=l1_data_gas_units,
            l1_gas_price_gwei=l1_gas_price_gwei,
            _live_mode=w3_instance is not None,
        )
        
        opps_list, opps_summary = evaluate_quotes(
            quotes_sample, cycle=0, timestamp=timestamp,
            eth_usd_price=eth_usd, min_net_profit_usd=0.10,
            gas_config=gas_config,
            # v3.2.2: Use drift_warning_pct to align opportunity gates with spreads policy
            target_notional_usd=config.get("target_usd_notional", 1000.0),
            max_notional_drift_pct=config.get("drift_warning_pct", 20.0),
            # v3.2.63: Per-chain SUSPECT_SPREAD_HARD threshold from config
            max_gross_spread_bps=config.get("suspect_spread_bps_hard"),
            # R27.3: Unified economics — same paper_slippage_bps as spreads.py
            paper_slippage_bps=config.get("paper_slippage_bps", 0.0),
        )
        
        # v3.2.5: Link opportunities to spread_signals and copy economics
        # Build lookup: (pair, buy_dex, sell_dex) -> spread_signal (with correct economics)
        spread_signal_lookup = {}
        for sig in spread_signals:
            key = (sig.get("pair"), sig.get("buy_dex"), sig.get("sell_dex"))
            spread_signal_lookup[key] = sig
        
        # Patch each opportunity with traceability fields from spread_signal.
        # IMPORTANT: Do NOT overwrite viability gate fields (min_required_spread_bps,
        # spread_minus_required_bps, is_roundtrip_viable) because the opportunity
        # engine calculated them with paper slippage (5 bps) which is correct for
        # the roundtrip gate. The spread_signal uses measured slippage (often 50-120 bps)
        # which makes the gate too conservative and blocks all roundtrip evaluation.
        # Store measured-slippage economics as separate _measured fields for RCA.
        for opp in opps_list:
            if isinstance(opp, dict):
                key = (opp.get("pair"), opp.get("buy_dex"), opp.get("sell_dex"))
                sig = spread_signal_lookup.get(key)
                if sig:
                    # Traceability: route and spread
                    opp["route"] = sig.get("route")
                    opp["spread_bps"] = sig.get("spread_bps") or sig.get("spread_bps_ui")
                    # Cost breakdown for RCA (informational, does NOT gate roundtrip)
                    opp["lp_fee_bps_roundtrip"] = sig.get("lp_fee_bps_roundtrip")
                    opp["effective_slippage_bps"] = sig.get("effective_slippage_bps")
                    opp["gas_usd_estimate"] = sig.get("gas_usd_estimate")
                    opp["size_usd"] = sig.get("size_usd")
                    # Measured-slippage economics for truth reporting (does NOT overwrite gate)
                    opp["measured_min_required_spread_bps"] = sig.get("min_required_spread_bps")
                    opp["measured_spread_minus_required_bps"] = sig.get("spread_minus_required_bps")
                    opp["measured_is_roundtrip_viable"] = sig.get("is_roundtrip_viable", False)
                    logger.debug(
                        "Linked opp %s: paper_gate(min_req=%.1f, surplus=%.1f, viable=%s) "
                        "measured(min_req=%.1f, surplus=%.1f, viable=%s)",
                        key,
                        opp.get("min_required_spread_bps", 0), opp.get("spread_minus_required_bps", 0), opp.get("is_roundtrip_viable"),
                        opp.get("measured_min_required_spread_bps", 0), opp.get("measured_spread_minus_required_bps", 0), opp.get("measured_is_roundtrip_viable"),
                    )
        
        # v3.5.0: Collect compared fee tiers from actual quotes
        # This proves which fee tiers were really compared for each route.
        _compared_fee_tiers: set[int] = set()
        _fee_tiers_per_route: dict[str, set[int]] = {}
        for opp in opps_list:
            if isinstance(opp, dict):
                bf = opp.get("buy_fee")
                sf = opp.get("sell_fee")
                route_key = opp.get("route", "unknown")
                if bf is not None:
                    _compared_fee_tiers.add(int(bf))
                if sf is not None:
                    _compared_fee_tiers.add(int(sf))
                if route_key not in _fee_tiers_per_route:
                    _fee_tiers_per_route[route_key] = set()
                if bf is not None:
                    _fee_tiers_per_route[route_key].add(int(bf))
                if sf is not None:
                    _fee_tiers_per_route[route_key].add(int(sf))

        stats["opportunity_engine"] = {
            "enabled": True,
            "summary": opps_summary,
            "top_opportunities": opps_list[:5] if opps_list else [],
            "truth_mode_m42": truth_mode_m42,
            "one_leg_profit_is_diagnostic": truth_mode_m42,
            # v3.5.0: Runtime proof of which fee tiers were really compared
            "compared_fee_tiers": sorted(_compared_fee_tiers),
            # R17: Per-route fee tier breakdown
            "compared_fee_tiers_per_route": {
                k: sorted(v) for k, v in sorted(_fee_tiers_per_route.items())
            },
        }
        
        # v3.2.58: Reconcile opportunity_engine with spread_signals for same-DEX fallback
        # When require_cross_dex=false (same-DEX fallback), spread_signals can have signals
        # even when total_opportunities=0 (because OpportunityEngine is for cross-DEX only).
        # Add explicit fields to avoid artifact contract mismatch.
        require_cross_dex = config.get("require_cross_dex", True)
        same_dex_fallback = not require_cross_dex
        stats["opportunity_engine"]["same_dex_fallback_mode"] = same_dex_fallback
        stats["opportunity_engine"]["spread_signals_count"] = len(spread_signals)
        if same_dex_fallback and len(spread_signals) > 0 and opps_summary.get("total_opportunities", 0) == 0:
            # Same-DEX signals exist but no cross-DEX opportunities - this is expected
            stats["opportunity_engine"]["summary"]["same_dex_signals_active"] = True
            stats["opportunity_engine"]["summary"]["note"] = "Same-DEX fallback: spread_signals are fee-tier arbitrage, not cross-DEX opportunities"
        
        # v2.2.0 Fix Step 5: Normalize truth-mode reporting
        # When truth_mode=true, one-leg profits are diagnostic only
        if truth_mode_m42:
            logger.info(
                "OpportunityEngine: %d opportunities, %d one_leg_profitable (DIAGNOSTIC), best=$%.2f",
                opps_summary.get("total_opportunities", 0),
                opps_summary.get("profitable_count", 0),
                opps_summary.get("best_net_profit_usd", 0),
            )
        else:
            logger.info(
                "OpportunityEngine: %d opportunities, %d profitable, best=$%.2f",
                opps_summary.get("total_opportunities", 0),
                opps_summary.get("profitable_count", 0),
                opps_summary.get("best_net_profit_usd", 0),
            )
    except Exception as e:
        logger.debug("OpportunityEngine skipped: %s", e)
        stats["opportunity_engine"] = {"enabled": False, "error": str(e)}
    
    # v3.2.55: Refine no_data_reason with opportunity-level info
    # If opportunities were evaluated but NO signals passed through, that's a reject-driven outcome.
    # profitable_count is DIAGNOSTIC in truth_mode, so we don't condition on it.
    if stats.get("no_data_reason") == "NO_SPREAD_SIGNALS":
        opp_engine = stats.get("opportunity_engine", {})
        if opp_engine.get("enabled"):
            opp_summary = opp_engine.get("summary", {})
            total_opps = opp_summary.get("total_opportunities", 0)
            if total_opps > 0:
                # Opportunities were found and evaluated, but all rejected (0 spread signals passed)
                stats["no_data_reason"] = "ALL_OPPORTUNITIES_REJECTED"
                logger.info(
                    "no_data_reason refined: ALL_OPPORTUNITIES_REJECTED (total_opps=%d, profitable=%d diagnostic)",
                    total_opps, opp_summary.get("profitable_count", 0)
                )
    
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
        
        # v3.2.4: Initialize roundtrip_stats with defaults to avoid unbound errors
        from engine.roundtrip import RoundtripEvaluationStats as RTStats
        roundtrip_stats = RTStats(
            candidates_total=0,
            gated_by_economics=0,
            evaluated_count=0,
            results_count=0,
            rejected_reasons={},
            warnings=[],  # v3.2.5: Initialize warnings
        )
        
        # v3.2.4: Initialize l1_cost variables with defaults
        l1_cost_wei = 0
        l1_cost_source = "none"
        
        if opps_list:
            # v2.1.0: Get L1 cost with source tracking (prefer onchain if w3_instance available)
            # v2.1.0-fix: Pass representative swap calldata for accurate L1 estimation
            try:
                from chains.l1_cost import get_l1_cost_with_source, create_sample_swap_calldata
                
                # Create representative swap calldata using WETH/USDC (canonical pair)
                # L1 cost depends primarily on calldata SIZE, not actual tokens
                weth_addr = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"  # Arbitrum WETH
                usdc_addr = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # Arbitrum native USDC
                sample_calldata = create_sample_swap_calldata(
                    token_in=weth_addr,
                    token_out=usdc_addr,
                    amount_in=int(1e18),  # 1 WETH
                    fee=3000,
                )
                
                l1_cost_wei, l1_cost_source = get_l1_cost_with_source(
                    w3=w3_instance,
                    calldata=sample_calldata,
                    config={
                        "l1_data_gas_units": gas_config.l1_data_gas_units,
                        "l1_gas_price_gwei": gas_config.l1_gas_price_gwei,
                    },
                    prefer_onchain=True,
                )
            except Exception as l1_err:
                # v3.2.4: Catch ALL exceptions, not just ImportError
                # Fallback to config-based estimate
                logger.debug("L1 cost estimation failed: %s, using config fallback", l1_err)
                l1_cost_wei = int(gas_config.l1_data_gas_units * gas_config.l1_gas_price_gwei * 1e9)
                l1_cost_source = "config"
            
            # v2.2.0: Filter opportunities where gross spread covers LP fees
            # LP fee per leg = fee_tier / 100 (e.g., 500 -> 5 bps)
            # Roundtrip LP cost = buy_fee/100 + sell_fee/100
            # NOTE: opps_list contains dicts (from to_dict()), not Opportunity objects
            def lp_fee_viable(opp: dict) -> bool:
                """Check if gross spread covers roundtrip LP fees."""
                try:
                    lp_bps = (opp.get("buy_fee", 0) + opp.get("sell_fee", 0)) / 100
                    return float(opp.get("gross_spread_bps", 0)) > lp_bps
                except Exception:
                    return True  # Allow on error (conservative)
            
            # v2.2.1: Roundtrip MUST be cross-DEX (same-DEX fee-tier arb not viable as roundtrip)
            def is_cross_dex(opp: dict) -> bool:
                """Check if opportunity is cross-DEX (buy_dex != sell_dex)."""
                return opp.get("buy_dex") != opp.get("sell_dex")
            
            # v2.2.1: Combined filter: cross-DEX AND LP fee viable
            def roundtrip_eligible(opp: dict) -> bool:
                return is_cross_dex(opp) and lp_fee_viable(opp)
            
            # v3.2.4: Filter for minimum viability margin before roundtrip eval
            # Only candidates with spread_minus_required_bps > -5 get evaluated
            # This prevents wasting roundtrip evals on clearly non-viable candidates
            MIN_SPREAD_MINUS_THRESHOLD = -5.0  # bps
            
            def margin_viable(opp: dict) -> bool:
                """Check if candidate has viable economics margin."""
                margin = opp.get("spread_minus_required_bps", -999)
                return margin > MIN_SPREAD_MINUS_THRESHOLD
            
            # v2.8.0: Best-per-pair selection to improve coverage across pairs
            # Instead of taking top-N overall (which often clusters on one pair),
            # select best candidate per unique pair, then take top-5
            # v3.2.4: Sort by spread_minus_required_bps (desc) for viability-first selection
            def best_per_pair(opps, max_candidates=10):
                """Select best opportunity per pair by spread_minus_required_bps."""
                pairs_best = {}
                for o in opps[:max_candidates]:
                    pair = o.get("pair", "unknown")
                    # v3.2.4: Prioritize by spread_minus_required_bps (viability margin)
                    curr_margin = o.get("spread_minus_required_bps", -999)
                    best_margin = pairs_best[pair].get("spread_minus_required_bps", -999) if pair in pairs_best else -999
                    if pair not in pairs_best or curr_margin > best_margin:
                        pairs_best[pair] = o
                # v3.2.4: Sort by spread_minus_required_bps descending (viable first)
                return sorted(pairs_best.values(), key=lambda x: x.get("spread_minus_required_bps", -999), reverse=True)
            
            # Apply best-per-pair, filter by eligibility AND margin viability, take top 5
            per_pair_best = best_per_pair(opps_list, max_candidates=20)
            # v3.2.4: Filter by roundtrip_eligible AND margin_viable (spread_minus > -5 bps)
            eligible_opps = [o for o in per_pair_best if roundtrip_eligible(o) and margin_viable(o)][:5]
            margin_filtered_count = len([o for o in per_pair_best if roundtrip_eligible(o)]) - len([o for o in per_pair_best if roundtrip_eligible(o) and margin_viable(o)])
            stats["roundtrip_lp_filter"] = {
                "candidates_considered": min(20, len(opps_list)),
                "cross_dex_count": len([o for o in opps_list[:20] if is_cross_dex(o)]),
                "lp_viable_count": len([o for o in opps_list[:20] if lp_fee_viable(o)]),
                "unique_pairs_considered": len(per_pair_best),  # v2.8.0: Track pair diversity
                "margin_filtered_count": margin_filtered_count,  # v3.2.4: Count filtered by margin
                "passed_to_roundtrip": len(eligible_opps),
            }
            
            # v2.8.1: Build token_decimals dict for correct net_pnl_bps calculation
            # Source: pairs_list (if available) or core_tokens.yaml
            token_decimals = {}
            if pairs_list:
                for p in pairs_list:
                    token_decimals[p.token_in] = p.token_in_decimals
                    token_decimals[p.token_out] = p.token_out_decimals
            else:
                # Fallback: load from core_tokens.yaml
                try:
                    core_tokens = load_core_tokens()
                    chain_tokens = core_tokens.get(chain_key, {})
                    for symbol, token_data in chain_tokens.items():
                        if isinstance(token_data, dict) and "decimals" in token_data:
                            token_decimals[symbol] = token_data["decimals"]
                except Exception as e:
                    logger.warning("Failed to load token_decimals from core_tokens: %s", e)
            
            roundtrip_results, roundtrip_stats = evaluate_roundtrip_candidates(
                opportunities=eligible_opps,
                buy_quotes_by_key=quotes_by_key,
                sell_quotes_by_key=quotes_by_key,
                gas_price_wei=live_gas_price_wei,
                top_n=5,
                leg2_quote_callback_factory=make_leg2_callback,
                l1_cost_wei=l1_cost_wei,
                l1_cost_source=l1_cost_source,
                # v2.8.0: Pass USD prices for cross-token correctness
                eth_usd_price=eth_usd,
                token_usd_prices=config.get("tokens_usd_price") or {},
                token_decimals=token_decimals,  # v2.8.1: Fix decimals bug
            )
        
        # Summarize round-trip results
        rt_profitable = [r for r in roundtrip_results if r.is_profitable]
        rt_using_real_quote = [r for r in roundtrip_results if r.leg2_is_real_quote]
        
        # v2.1.0: Track L1 cost source for transparency
        l1_cost_source_used = l1_cost_source if opps_list else "none"
        l1_cost_wei_used = l1_cost_wei if opps_list else 0
        
        stats["roundtrip"] = {
            "enabled": True,
            "evaluated_count": len(roundtrip_results),
            "profitable_count": len(rt_profitable),
            "real_quote_count": len(rt_using_real_quote),
            "gas_price_wei_used": live_gas_price_wei,
            "l1_cost_wei": l1_cost_wei_used,  # v2.1.0: L1 cost tracking
            "l1_cost_source": l1_cost_source_used,  # v2.1.0: "onchain" | "config" | "default"
            "results": [r.to_dict() for r in roundtrip_results[:3]],
            # v3.0.0: Aggregation stats for visibility
            "candidates_total": roundtrip_stats.candidates_total,
            "gated_by_economics": roundtrip_stats.gated_by_economics,
            "rejected_reasons": roundtrip_stats.rejected_reasons,
            # v3.2.5: Warnings from roundtrip evaluation (L1 cost source, etc.)
            "warnings": roundtrip_stats.warnings or [],
        }
        
        # v2.1.0: FIX issue #8 - best_net_pnl_bps should show actual best, not 0.0 when all negative
        if roundtrip_results:
            best_rt = max(roundtrip_results, key=lambda r: r.net_pnl_bps)
            stats["roundtrip"]["best_net_pnl_bps"] = best_rt.net_pnl_bps
            if rt_profitable:
                logger.info(
                    "Roundtrip: %d/%d profitable, best=%.2f bps",
                    len(rt_profitable), len(roundtrip_results), best_rt.net_pnl_bps
                )
            else:
                logger.info(
                    "Roundtrip: 0/%d profitable, best(negative)=%.2f bps",
                    len(roundtrip_results), best_rt.net_pnl_bps
                )
        else:
            stats["roundtrip"]["best_net_pnl_bps"] = None
            logger.info("Roundtrip: no candidates evaluated")
        
        # Blocker metric: best measured_spread_minus_required_bps across evaluated opportunities
        # This tracks the gap between spread captured and real roundtrip cost.
        # As this approaches 0, we approach M4.2 closure.
        measured_gaps = [
            opp.get("measured_spread_minus_required_bps")
            for opp in opps_list
            if isinstance(opp, dict) and opp.get("measured_spread_minus_required_bps") is not None
        ]
        stats["roundtrip"]["best_measured_spread_gap_bps"] = max(measured_gaps) if measured_gaps else None
        
        # v3.3.0: Dynamic size sweep — find optimal notional per route
        dynamic_probe_cfg = config.get("dynamic_probe", {})
        if dynamic_probe_cfg.get("enabled") and eligible_opps:
            from engine.roundtrip import sweep_roundtrip_sizes, CANONICAL_SWEEP_SIZES_USD

            sweep_sizes = dynamic_probe_cfg.get("sizes_usd", None) or list(CANONICAL_SWEEP_SIZES_USD)
            max_routes = dynamic_probe_cfg.get("top_routes", 3)

            # Factory: re-quote leg1 on sell_dex (token_in → token_out, same direction)
            def _make_leg1_requote(quote: Dict):
                _dex_id = quote.get("dex_id", "")
                _dex_cfg = get_dex_config(chain_key, _dex_id)
                _quoter = _dex_cfg.get_quoter_address() if _dex_cfg else None
                _ti_sym = quote.get("token_in", "")
                _to_sym = quote.get("token_out", "")
                _fee = quote.get("fee", 3000)
                _ti_addr = get_token_address(chain_key, _ti_sym)
                _to_addr = get_token_address(chain_key, _to_sym)
                if not _quoter or not _ti_addr or not _to_addr:
                    return None

                def _requote(amount_in_wei: int) -> Optional[Dict]:
                    r = read_quoter_v2(
                        quoter_address=_quoter,
                        token_in=_ti_addr,
                        token_out=_to_addr,
                        amount_in=amount_in_wei,
                        fee=_fee,
                        rpc_url=resolved_http,
                        block_num=current_block,
                    )
                    if r:
                        return {
                            "amount_out_wei": r["amount_out"],
                            "gas_estimate": r.get("gas_estimate", 150000),
                            "ticks_crossed": r.get("ticks_crossed", 0),
                            "sqrt_price_after": r.get("sqrt_price_after"),
                        }
                    return None
                return _requote

            # Factory: re-quote leg2 on buy_dex (token_out → token_in, REVERSE)
            def _make_leg2_requote(quote: Dict):
                _dex_id = quote.get("dex_id", "")
                _dex_cfg = get_dex_config(chain_key, _dex_id)
                _quoter = _dex_cfg.get_quoter_address() if _dex_cfg else None
                _to_sym = quote.get("token_out", "")
                _ti_sym = quote.get("token_in", "")
                _fee = quote.get("fee", 3000)
                _to_addr = get_token_address(chain_key, _to_sym)
                _ti_addr = get_token_address(chain_key, _ti_sym)
                if not _quoter or not _ti_addr or not _to_addr:
                    return None

                def _requote(amount_in_wei: int) -> Optional[Dict]:
                    r = read_quoter_v2(
                        quoter_address=_quoter,
                        token_in=_to_addr,   # REVERSE: token_out → token_in
                        token_out=_ti_addr,
                        amount_in=amount_in_wei,
                        fee=_fee,
                        rpc_url=resolved_http,
                        block_num=current_block,
                    )
                    if r:
                        return {
                            "amount_out_wei": r["amount_out"],
                            "gas_estimate": r.get("gas_estimate", 150000),
                            "ticks_crossed": r.get("ticks_crossed", 0),
                            "sqrt_price_after": r.get("sqrt_price_after"),
                        }
                    return None
                return _requote

            sweep_results = []
            for opp in eligible_opps[:max_routes]:
                buy_key = f"{opp.get('buy_dex')}:{opp.get('diagnostics', {}).get('buy_pool')}:{opp.get('buy_fee')}"
                sell_key = f"{opp.get('sell_dex')}:{opp.get('diagnostics', {}).get('sell_pool')}:{opp.get('sell_fee')}"
                bq = quotes_by_key.get(buy_key)
                sq = quotes_by_key.get(sell_key)
                if not bq or not sq:
                    continue

                leg1_rq = _make_leg1_requote(sq)   # leg1 on sell_dex
                leg2_rq = _make_leg2_requote(bq)   # leg2 on buy_dex
                if not leg1_rq or not leg2_rq:
                    continue

                _ti = sq.get("token_in", "WETH")
                _ti_price = (config.get("tokens_usd_price") or {}).get(_ti)
                if not _ti_price:
                    _ti_price = eth_usd if _ti in ("WETH", "ETH") else None
                if not _ti_price:
                    continue

                _ti_dec = token_decimals.get(_ti, 18)

                sr = sweep_roundtrip_sizes(
                    buy_quote_base=sq,   # leg1 base (sell_dex quote)
                    sell_quote_base=bq,  # leg2 base (buy_dex quote)
                    requote_leg1=leg1_rq,
                    requote_leg2=leg2_rq,
                    sizes_usd=sweep_sizes,
                    token_in_usd_price=_ti_price,
                    token_in_decimals=_ti_dec,
                    gas_price_wei=live_gas_price_wei,
                    l1_cost_wei=l1_cost_wei,
                    l1_cost_source=l1_cost_source,
                    eth_usd_price=eth_usd,
                )
                sweep_results.append(sr)
                logger.info(
                    "Sweep %s: best=$%s, pnl=%.2f bps, frontier=%s",
                    sr.pair, sr.best_size_usd, sr.best_net_pnl_bps or 0.0, sr.frontier_reason,
                )

            # SUSPECT_ROUNDTRIP_OUTLIER: filter out sweep results with
            # extreme positive PnL, which indicates illiquid/garbage pool data.
            # Threshold aligned with SUSPECT_SPREAD_BPS_HARD (500 bps).
            SUSPECT_ROUNDTRIP_OUTLIER_BPS = 500
            suspect_outlier_count = 0
            clean_results = []
            for sr in sweep_results:
                if sr.best_net_pnl_bps is not None and sr.best_net_pnl_bps > SUSPECT_ROUNDTRIP_OUTLIER_BPS:
                    suspect_outlier_count += 1
                    logger.warning(
                        "SUSPECT_ROUNDTRIP_OUTLIER: %s pnl=%.1f bps > %d threshold",
                        sr.pair, sr.best_net_pnl_bps, SUSPECT_ROUNDTRIP_OUTLIER_BPS,
                    )
                else:
                    clean_results.append(sr)

            if clean_results:
                best_sweep = max(
                    clean_results,
                    key=lambda s: s.best_net_pnl_bps if s.best_net_pnl_bps is not None else -9999,
                )
                stats["roundtrip"]["dynamic_sweep"] = {
                    "enabled": True,
                    "routes_swept": len(sweep_results),
                    "routes_clean": len(clean_results),
                    "suspect_outlier_count": suspect_outlier_count,
                    "best_pair": best_sweep.pair,
                    "best_size_usd": best_sweep.best_size_usd,
                    "best_net_pnl_bps": best_sweep.best_net_pnl_bps,
                    "best_frontier_reason": best_sweep.frontier_reason,
                    "gap_to_zero_bps": best_sweep.gap_to_zero_bps,
                    "best_gas_bps": best_sweep.best_gas_bps,
                    "best_fee_bps": best_sweep.best_fee_bps,
                    "best_slippage_bps": best_sweep.best_slippage_bps,
                    "best_total_cost_bps": best_sweep.best_total_cost_bps,
                    "results": [s.to_dict() for s in sweep_results],
                }
            elif sweep_results:
                # All results were suspect outliers
                stats["roundtrip"]["dynamic_sweep"] = {
                    "enabled": True,
                    "routes_swept": len(sweep_results),
                    "routes_clean": 0,
                    "suspect_outlier_count": suspect_outlier_count,
                    "best_frontier_reason": "ALL_SUSPECT_OUTLIER",
                    "results": [s.to_dict() for s in sweep_results],
                }
            else:
                stats["roundtrip"]["dynamic_sweep"] = {"enabled": True, "routes_swept": 0}
            
    except Exception as rt_err:
        logger.debug("Roundtrip evaluation skipped: %s", rt_err)
        stats["roundtrip"] = {"enabled": False, "error": str(rt_err)}
    
    # v2.2.0: M4.3 Preflight check for execution readiness
    try:
        from execution.state_machine import run_preflight_check, get_execution_context
        
        # Use best roundtrip result if available
        best_roundtrip = None
        if "roundtrip" in stats and stats["roundtrip"].get("results"):
            best_roundtrip = stats["roundtrip"]["results"][0] if stats["roundtrip"]["results"] else None
        
        preflight_result = run_preflight_check(
            config=config,
            roundtrip_result=best_roundtrip,
            infra_payload=infra_payload,
        )
        
        stats["preflight"] = preflight_result.to_dict()
        
        # v2.2.0 FIX: Roadmap M5_0 DoD requires execution_ready_count=0 while kill switch ON
        # execution_ready_count: actual execution allowed (is_execution_allowed==True)
        # would_execute_count: diagnostic - preflight passed but execution blocked
        exec_ctx = get_execution_context()
        if exec_ctx.is_execution_allowed() and preflight_result.passed:
            stats["execution_ready_count"] = 1
        else:
            stats["execution_ready_count"] = 0
        
        # v2.2.0 Fix Step 6: would_execute_count semantics
        # When truth_mode_m42=true, would_execute only if roundtrip-profitable
        # (one-leg profit is diagnostic only, not execution-worthy)
        roundtrip_profitable = (
            best_roundtrip is not None and 
            best_roundtrip.get("is_profitable", False)
        )
        if truth_mode_m42:
            # Truth mode: require roundtrip profit for "would execute"
            stats["would_execute_count"] = 1 if (preflight_result.passed and roundtrip_profitable) else 0
        else:
            # Legacy mode: just preflight pass
            stats["would_execute_count"] = 1 if preflight_result.passed else 0
        
        logger.info(
            "M4.3 Preflight: %s (errors=%d, warnings=%d, execution_ready=%d, would_execute=%d)",
            "PASS" if preflight_result.passed else "FAIL",
            len(preflight_result.errors),
            len(preflight_result.warnings),
            stats["execution_ready_count"],
            stats["would_execute_count"],
        )
    except Exception as pf_err:
        logger.debug("Preflight check skipped: %s", pf_err)
        stats["preflight"] = {"enabled": False, "error": str(pf_err)}
        stats["execution_ready_count"] = 0
        stats["would_execute_count"] = 0
    
    # v2.4.1: M4.3 Preflight EVIDENCE (eth_call/eth_estimateGas for top-N)
    # Collects actual RPC evidence without executing any transactions
    # Uses opps_list (gated opportunities) instead of spread_signals
    # R28.4: Skip for COVERAGE runs (opt-in only for NORMAL/promotion checks)
    _phase_preflight_start = _time.monotonic()
    if run_kind == "COVERAGE":
        stats["preflight_evidence"] = {"enabled": False, "skipped": "COVERAGE_LIGHTWEIGHT"}
        logger.info("Preflight evidence skipped for COVERAGE run (lightweight mode)")
    else:
        try:
            from execution.preflight import (
                collect_top_n_preflight,
                preflight_not_available,
                adapt_opportunity_to_preflight_input,
            )
            
            # Check if we have opportunities and a web3 instance
            if opps_list and len(opps_list) > 0 and w3_instance:
                # Convert opportunities to preflight input format
                preflight_candidates = [
                    adapt_opportunity_to_preflight_input(opp, chain_key=chain_key)
                    for opp in opps_list[:3]  # Top-3 candidates
                ]
                
                preflight_evidence = collect_top_n_preflight(
                    w3=w3_instance,
                    spread_signals=preflight_candidates,
                    n=3,
                    current_block=current_block,
                )
                stats["preflight_evidence"] = preflight_evidence
                logger.info(
                    "M4.3 Preflight Evidence: %d/%d candidates passed",
                    preflight_evidence["passed_count"],
                    preflight_evidence["candidates_count"],
                )
            elif not w3_instance:
                stats["preflight_evidence"] = preflight_not_available("NO_W3_INSTANCE")
            else:
                stats["preflight_evidence"] = preflight_not_available("NO_OPPORTUNITIES")
        except Exception as pf_ev_err:
            logger.debug("Preflight evidence collection skipped: %s", pf_ev_err)
            stats["preflight_evidence"] = {
                "enabled": False,
                "error": str(pf_ev_err),
            }
    _phase_preflight_end = _time.monotonic()
    
    # v2.4.1: Discovery dry-run (count candidates without changing universe)
    # Uses chain_key (already resolved) and config.dexes for consistency
    discovery_dry_run = config.get("discovery_dry_run", False)
    if discovery_dry_run:
        try:
            from discovery.index_factories import count_discovery_candidates
            
            dexes_list = config.get("dexes") or None  # None = all known for chain
            
            discovery_stats = count_discovery_candidates(chain=chain_key, dexes=dexes_list)
            stats["discovery"] = {
                "enabled": True,
                "dry_run": True,
                "chain": chain_key,
                "resolvable_pairs": discovery_stats["resolvable_pairs"],
                "unresolvable_pairs": discovery_stats["unresolvable_pairs"],
                "dexes_available": discovery_stats["dexes_available"],
                "potential_v3_queries": discovery_stats["potential_v3_queries"],
                "potential_v2_queries": discovery_stats["potential_v2_queries"],
                "total_potential_queries": discovery_stats["total_potential_queries"],
            }
            logger.info(
                "Discovery dry-run: %d resolvable pairs, %d potential queries",
                discovery_stats["resolvable_pairs"],
                discovery_stats["total_potential_queries"],
            )
        except Exception as disc_err:
            logger.debug("Discovery dry-run failed: %s", disc_err)
            stats["discovery"] = {"enabled": False, "error": str(disc_err)}
    else:
        stats["discovery"] = {"enabled": False, "dry_run": False}
    
    # v2.4.2: Discovery runtime (resolve pool addresses via factory.getPool())
    # v2.5.0: If universe_source=discovery_runtime, reuse already-resolved data
    # Otherwise, resolve for observability (does not change quote universe)
    discovery_runtime = config.get("discovery_runtime", False)
    if use_discovery_runtime and _discovery_runtime_stats is not None:
        # Reuse already-resolved data from universe selection
        from discovery.runtime import get_runtime_observability
        
        stats["discovery_runtime"] = get_runtime_observability(_discovery_runtime_stats)
        stats["discovery_runtime"]["universe_active"] = True  # Actually affected quoting
        stats["discovery_runtime"]["cross_dex_pairs_count"] = _discovery_runtime_stats.cross_dex_pairs_count
        stats["discovery_runtime"]["resolved_pairs"] = [
            {
                "pair": p.display_name,
                "dex": p.dex,
                "fee": p.fee,
                "pool": p.pool_address,
            }
            for p in _discovery_runtime_resolved
        ]
        logger.info(
            "Discovery runtime (universe active): %d pairs resolved, %d rpc_calls",
            _discovery_runtime_stats.pairs_resolved,
            _discovery_runtime_stats.rpc_calls,
        )
    elif discovery_runtime:
        try:
            from discovery.runtime import resolve_runtime_pairs, get_runtime_observability
            
            dexes_list_rt = config.get("dexes") or None
            max_pairs = config.get("discovery_runtime_max_pairs", 20)
            
            resolved_pairs, runtime_stats = resolve_runtime_pairs(
                chain=chain_key,
                dexes=dexes_list_rt,
                max_pairs=max_pairs,
            )
            
            stats["discovery_runtime"] = get_runtime_observability(runtime_stats)
            stats["discovery_runtime"]["universe_active"] = False  # Observability only
            stats["discovery_runtime"]["cross_dex_pairs_count"] = runtime_stats.cross_dex_pairs_count
            stats["discovery_runtime"]["resolved_pairs"] = [
                {
                    "pair": p.display_name,
                    "dex": p.dex,
                    "fee": p.fee,
                    "pool": p.pool_address,
                }
                for p in resolved_pairs
            ]
            
            logger.info(
                "Discovery runtime (observability): %d pairs resolved, %d rpc_calls",
                runtime_stats.pairs_resolved,
                runtime_stats.rpc_calls,
            )
        except Exception as rt_err:
            logger.warning("Discovery runtime failed: %s", rt_err)
            stats["discovery_runtime"] = {"enabled": False, "error": str(rt_err)}
    else:
        stats["discovery_runtime"] = {"enabled": False}
    
    # Build artifact data structures
    # v2.3.0: Unified run_timestamp for provenance across all artifacts
    # v2.0.4: Use canonical timestamp helper from core/time.py
    from core.time import get_run_timestamp
    run_timestamp = get_run_timestamp()
    
    scan_data = build_scan_data(config, current_block, stats, quotes_sample, infra_payload, run_timestamp=run_timestamp, rejected_quotes=rejected_quotes)
    
    truth_data = build_truth_data(
        config, stats, current_block, spread_signals, suspect_examples,
        infra_payload, raw_bps, spread_threshold_bps, run_timestamp=run_timestamp,
        rejected_quotes=rejected_quotes,
    )
    
    reject_data = build_reject_data(
        config, current_block, sanity_rejects, rejected_quotes, stats, infra_payload, run_timestamp=run_timestamp, quotes_sample=quotes_sample
    )
    
    # Write artifacts (timestamp already set before opportunity_engine)
    artifacts = write_artifacts(output_dir, timestamp, scan_data, truth_data, reject_data, artifact_mode=artifact_mode)
    
    # v2.2.0: Flush quarantine and dynamic anchors state to disk
    # v2.3.1: Only flush anchors when running with live RPC to avoid polluting cache with stale/synthetic data
    # v3.2.11: Chain-scoped flush - pass chain_key to persist to correct cache file
    try:
        from strategy.quarantine import flush_quarantine_manager
        from strategy.dynamic_anchors import get_anchor_manager
        
        flush_quarantine_manager(chain_key=chain_key)
        if w3_instance is not None:
            get_anchor_manager(chain_key=chain_key).flush()
            logger.debug("Quarantine and dynamic anchors state flushed to disk (chain_key=%s)", chain_key)
        else:
            logger.debug("Quarantine flushed; anchors skipped (no live RPC)")
    except Exception as flush_err:
        logger.debug("State flush skipped: %s", flush_err)
    
    logger.info("Scan completed: %s artifacts written", len(artifacts))
    for name, path in artifacts.items():
        logger.info("  %s: %s", name, path)
    
    # R28.4: Phase timing metrics for performance observability
    _phase_end = _time.monotonic()
    stats["phase_timers_ms"] = {
        "total_ms": int((_phase_end - _phase_t0) * 1000),
        "init_rpc_ms": int((_phase_discovery_end - _phase_t0) * 1000),
        "quote_rpc_ms": int((_phase_quote_end - _phase_quote_start) * 1000),
        "preflight_ms": int((_phase_preflight_end - _phase_preflight_start) * 1000),
        "post_scan_ms": int((_phase_end - _phase_preflight_end) * 1000),
    }
    logger.info(
        "Phase timers: total=%dms init=%dms quote=%dms preflight=%dms post=%dms",
        stats["phase_timers_ms"]["total_ms"],
        stats["phase_timers_ms"]["init_rpc_ms"],
        stats["phase_timers_ms"]["quote_rpc_ms"],
        stats["phase_timers_ms"]["preflight_ms"],
        stats["phase_timers_ms"]["post_scan_ms"],
    )
    
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
                # v2.2.1: Preserve config path for artifact transparency
                config["_config_path"] = str(cfgp)
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
                # v2.2.1: Preserve config path for artifact transparency
                config["_config_path"] = str(cfg_path)
            except Exception as e:
                logger.warning(f"Could not load config {cfg_path}: {e}")
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    
    # R27.3: Pre-scan universe validation
    if args.config:
        try:
            from scripts.validate_universe import validate_universe
            vu_result = validate_universe(Path(args.config))
            if vu_result["status"] == "FAIL":
                for err in vu_result["errors"]:
                    logger.error("validate_universe: %s", err)
                logger.error("Pre-scan validation FAIL — aborting. Fix config or override run_kind.")
                return 1
            for w in vu_result.get("warnings", []):
                logger.warning("validate_universe: %s", w)
        except ImportError:
            logger.debug("validate_universe not available — skipping pre-scan check")
    
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
