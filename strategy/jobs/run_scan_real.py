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
- strategy/scan_universe.py - Universe resolution (R28.28)
- strategy/roundtrip_selection.py - Candidate selection pipeline (R28.28)
- strategy/dynamic_sweep_runtime.py - Dynamic size sweep (R28.28)
- strategy/execution_probe.py - Live execution probe (R28.28)
- strategy/live_stream.py - Operator candidate stream (R28.28)
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


# ---------------------------------------------------------------------------
# R28.27: Cap-isolation toggles — modeled after quotes._get_runtime_filter_switches
# When active, hard caps are raised to very high values so their effect on the
# funnel can be measured independently (A/B style).
# Priority: ENV VAR → CONFIG KEY → DEFAULT (caps active).
# ---------------------------------------------------------------------------

# Canonical _env_flag_enabled lives in core.env; local alias for brevity
from core.env import env_flag_enabled as _env_flag_enabled


# Sentinel value: effectively uncapped while remaining an int
_UNCAPPED = 999_999


def _get_cap_isolation_switches(config: Dict[str, Any]) -> Dict[str, bool]:
    """Resolve which hard caps are in isolation (uncapped) mode.

    Contract:
    - When a cap is "isolated", its value is replaced with _UNCAPPED so
      the pipeline runs as if that cap didn't exist.
    - Default is all caps ACTIVE (normal production behavior).
    - Granular env vars allow isolating one cap at a time for A/B.

    Returns dict with keys: uncap_discovery_max_pairs, uncap_rt_max_candidates,
    uncap_rt_top_n.  True means the cap is REMOVED for this run.
    """
    uncap_all = _env_flag_enabled("ARBY_UNCAP_ALL") or bool(
        config.get("uncap_all", False)
    )
    uncap_discovery = uncap_all or _env_flag_enabled(
        "ARBY_UNCAP_DISCOVERY_MAX_PAIRS"
    ) or bool(config.get("uncap_discovery_max_pairs", False))
    uncap_rt_max = uncap_all or _env_flag_enabled(
        "ARBY_UNCAP_RT_MAX_CANDIDATES"
    ) or bool(config.get("uncap_rt_max_candidates", False))
    uncap_rt_top = uncap_all or _env_flag_enabled(
        "ARBY_UNCAP_RT_TOP_N"
    ) or bool(config.get("uncap_rt_top_n", False))
    return {
        "uncap_discovery_max_pairs": uncap_discovery,
        "uncap_rt_max_candidates": uncap_rt_max,
        "uncap_rt_top_n": uncap_rt_top,
    }


# R28.16: Phase event protocol — structured JSON lines for parent process consumption
# Parent (start.py) reads stdout and parses lines prefixed with ARBY_PHASE: to
# surface phase transitions in the live stream without needing IPC or shared files.
PHASE_LINE_PREFIX = "ARBY_PHASE:"


def _emit_phase(event: str, **data: Any) -> None:
    """Emit a structured phase event line for the parent process to consume."""
    import json as _phase_json
    payload = {"event": event, **data}
    print(f"{PHASE_LINE_PREFIX}{_phase_json.dumps(payload, default=str)}", flush=True)


def _build_live_candidate_stream(
    chain_key: str,
    opportunities: List[Dict[str, Any]],
    roundtrip_results: List[Any],
    dynamic_sweep: Optional[Dict[str, Any]],
    default_size_usd: float,
    max_candidates: int = 10,
    sweep_candidates: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build compact operator-facing pair candidates for hot-loop streaming.

    R28.28: Delegates to strategy.live_stream (extracted module).
    """
    from strategy.live_stream import build_live_candidate_stream
    return build_live_candidate_stream(
        chain_key=chain_key,
        opportunities=opportunities,
        roundtrip_results=roundtrip_results,
        dynamic_sweep=dynamic_sweep,
        default_size_usd=default_size_usd,
        max_candidates=max_candidates,
        sweep_candidates=sweep_candidates,
    )


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
    """Get current block via RPC, environment, or WS-observed block.

    R28.12: If ARBY_WS_BLOCK_NUMBER is set (from DirtySetTracker), use it
    directly — saves one RPC round-trip on hot re-quote cycles.
    """
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        block = int(os.environ.get("ARBY_FAKE_BLOCK", "100"))
        return block, 0
    ws_block = os.environ.get("ARBY_WS_BLOCK_NUMBER")
    if ws_block:
        try:
            block = int(ws_block)
            logger.info("Using WS-observed block %d (skip block-pin RPC)", block)
            return block, 0
        except ValueError:
            pass
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


# ---------------------------------------------------------------------------
# R39x: Sweep-frontier truth-probe reranking
# ---------------------------------------------------------------------------

_CATASTROPHIC_SLIPPAGE_BPS = 10_000


def _rerank_top_opportunities_by_sweep_frontier(
    stats: Dict[str, Any],
    logger: Any,
) -> None:
    """Post-sweep reranking of top_opportunities by frontier curves.

    When truth_mode_m42 and frontier curves exist, operator-facing
    top_opportunities should reflect measured multi-size sweep economics
    (gap_to_zero_bps), not seed-size spread_minus_required_bps.

    Also applies curve-quality guard: pairs with catastrophic slippage
    (>= 10000 bps) or ROUTE_KILL at any sweep size are penalised so they
    don't auto-beat pairs with stable curves.
    """
    oe = stats.get("opportunity_engine")
    if not oe:
        return

    ds = stats.get("roundtrip", {}).get("dynamic_sweep", {})
    results = ds.get("results") or []
    if not results:
        return

    # Preserve seed-signal ranked list for diagnostics
    _seed_top = oe.get("top_opportunities") or []
    oe["_seed_signal_top_opportunities"] = list(_seed_top)

    ranked_pairs: List[Dict[str, Any]] = []
    for r in results:
        pair = r.get("pair", "UNKNOWN")
        gap = r.get("gap_to_zero_bps")
        has_data = gap is not None

        # Curve-quality guard: check all sweep points for degradation
        curve_degraded = False
        degradation_reason = None
        for p in r.get("points") or []:
            slip = p.get("measured_slippage_bps")
            error = p.get("error")
            if slip is not None and slip >= _CATASTROPHIC_SLIPPAGE_BPS:
                curve_degraded = True
                degradation_reason = f"slippage={slip} at ${p.get('size_usd')}"
                break
            if error and "ROUTE_KILL" in str(error):
                curve_degraded = True
                degradation_reason = f"{error} at ${p.get('size_usd')}"
                break

        # Adjusted ranking score:
        # - No data (gap=None): 99_999 — worst; no executable evidence at all
        # - Degraded curve: gap + 10_000 — has data but unstable at larger sizes
        # - Clean curve: gap — best; stable across sweep sizes
        if not has_data:
            adjusted_gap = 99_999.0
        elif curve_degraded:
            adjusted_gap = gap + 10_000.0
        else:
            adjusted_gap = gap

        ranked_pairs.append({
            "pair": pair,
            "buy_dex": r.get("buy_dex"),
            "sell_dex": r.get("sell_dex"),
            "gap_to_zero_bps": gap,
            "best_net_pnl_bps": r.get("best_net_pnl_bps"),
            "best_slippage_bps": r.get("best_slippage_bps"),
            "frontier_reason": r.get("frontier_reason"),
            "curve_degraded": curve_degraded,
            "degradation_reason": degradation_reason,
            "has_data": has_data,
            "_adjusted_gap_bps": adjusted_gap,
            "ranking_source": "sweep_frontier",
        })

    # Sort by adjusted gap (ascending = closest to breakeven first)
    ranked_pairs.sort(key=lambda x: x["_adjusted_gap_bps"])

    oe["top_opportunities"] = ranked_pairs[:5]
    oe["_sweep_frontier_reranked"] = True

    logger.info(
        "SWEEP_FRONTIER_RERANK: top_pair=%s gap=%.2f (was seed-signal: %s), degraded=%d/%d",
        ranked_pairs[0]["pair"] if ranked_pairs else "NONE",
        ranked_pairs[0]["gap_to_zero_bps"] if ranked_pairs else 0,
        _seed_top[0].get("pair", "?") if _seed_top else "NONE",
        sum(1 for r in ranked_pairs if r["curve_degraded"]),
        len(ranked_pairs),
    )


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
    
    _emit_phase("discovery_started", chain=config.get("chain", "unknown"))
    
    # M4.2: Config validation - algebra DEXes require quoter
    dexes_list = config.get("dexes") or []
    use_quoter_v2 = config.get("use_quoter_v2", False)
    truth_mode_m42 = config.get("truth_mode_m42", False)  # v2.2.0 Fix Step 5
    algebra_dexes = [d for d in dexes_list if d in ("camelot_v3", "algebra", "swaap_v3")]
    
    if algebra_dexes and not use_quoter_v2:
        # R28.24: Auto-enable quoter_v2 for algebra DEXes instead of rejecting
        logger.info(
            "R28.24: Auto-enabling use_quoter_v2 for algebra DEXes: %s",
            algebra_dexes,
        )
        use_quoter_v2 = True
        config["use_quoter_v2"] = True
    
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
        "scan_mode": "full",  # R28.11: overridden to "hot" if hot_pairs loaded
    }
    
    # R28.27: Resolve cap-isolation switches early for consistent application
    _cap_switches = _get_cap_isolation_switches(config)
    if any(_cap_switches.values()):
        logger.info("CAP_ISOLATION active: %s", {k: v for k, v in _cap_switches.items() if v})
    stats["cap_isolation"] = _cap_switches

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
    
    # R28.28: Universe resolution extracted to strategy.scan_universe
    from strategy.scan_universe import resolve_universe
    _universe = resolve_universe(
        config=config,
        chain_key=chain_key,
        dexes_list=dexes_list,
        run_kind=run_kind,
        cap_switches=_cap_switches,
    )
    pairs_list = _universe["pairs_list"]
    _discovery_runtime_resolved = _universe["discovery_runtime_resolved"]
    _discovery_runtime_stats = _universe["discovery_runtime_stats"]
    stats.update(_universe["stats_updates"])
    use_discovery_runtime = (config.get("universe_source", "config") == "discovery_runtime")
    
    _phase_discovery_end = _time.monotonic()
    
    _emit_phase(
        "discovery_finished",
        chain=chain_key,
        pairs=len(pairs_list) if pairs_list else 0,
        universe_source=stats.get("universe_source", "config"),
        discovery_ms=int((_phase_discovery_end - _phase_t0) * 1000),
    )
    
    # Collect quotes with resolved pairs
    _phase_quote_start = _time.monotonic()

    # R39o: Reset per-cycle 429 quarantine before quotes
    from strategy.quote_rpc import reset_cycle_quarantine
    _quarantine_cleared = reset_cycle_quarantine()
    if _quarantine_cleared:
        logger.info("CYCLE_QUARANTINE_RESET: cleared %d entries", _quarantine_cleared)
    
    _emit_phase("quote_started", chain=chain_key, pairs=len(pairs_list) if pairs_list else 0)
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
    # R28.5: Multicall batch stats for performance observability
    if counts.get("multicall_stats"):
        stats["multicall_stats"] = counts["multicall_stats"]
    # R29: Per-DEX quoter success matrix for quoter health observability
    if counts.get("quoter_matrix"):
        stats["quoter_matrix"] = counts["quoter_matrix"]
    
    # v2.0.8: quotes_total = attempted quotes (valid + rejected), accounts for fee_tiers
    stats["quotes_total"] = len(quotes_sample) + len(rejected_quotes)
    stats["quotes_fetched"] = len(quotes_sample)
    # R29: Split quotes_fetched into executable vs diagnostic for Stage-2 clarity
    stats["quotes_fetched_executable"] = sum(1 for q in quotes_sample if not q.get("is_diagnostic_only"))
    stats["quotes_fetched_diagnostic"] = sum(1 for q in quotes_sample if q.get("is_diagnostic_only"))
    stats["quoter_v2_failed_count"] = counts.get("quoter_v2_failed", 0)
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

    # R39p: Prune hot-pairs cache — only keep pairs that produced executable quotes.
    # This prevents dead pairs from being re-quoted in hot loop cycles.
    if pairs_list and stats.get("scan_mode") != "hot":
        _executable_pairs = set()
        for _q in quotes_sample:
            if not _q.get("is_diagnostic_only"):
                _tin = _q.get("token_in", "")
                _tout = _q.get("token_out", "")
                if _tin and _tout:
                    _executable_pairs.add(f"{_tin}/{_tout}")
        if _executable_pairs:
            _pruned = [p for p in pairs_list if p.display_name in _executable_pairs]
            if len(_pruned) < len(pairs_list):
                logger.info(
                    "HOT_CACHE_PRUNE: %d -> %d pairs (executable: %s)",
                    len(pairs_list), len(_pruned), sorted(_executable_pairs),
                )
                from strategy.scan_universe import _write_hot_pairs_cache
                _write_hot_pairs_cache(chain_key, stats.get("universe_source", "config"), _pruned, stats_updates=stats)
    
    _phase_quote_end = _time.monotonic()
    
    _emit_phase(
        "quote_finished",
        chain=chain_key,
        quotes_fetched=len(quotes_sample),
        quotes_rejected=len(rejected_quotes),
        quote_rpc_ms=int((_phase_quote_end - _phase_quote_start) * 1000),
    )
    
    # R28.5: Postprocessing phase — spreads, opportunity engine, roundtrip, sweep
    _phase_postprocess_start = _time.monotonic()
    
    dexes_active_list = sorted({q.get("dex_id") for q in quotes_sample})
    stats["dexes_active"] = len(dexes_active_list)
    
    # R36: Surface coverage — compare scanned DEXes vs all DEXes in dexes.yaml for this chain
    try:
        from config import load_dexes
        _all_chain_dexes = sorted(load_dexes().get(chain_key, {}).keys())
    except Exception:
        _all_chain_dexes = []
    stats["scanned_surface_vs_supported_surface"] = {
        "dexes_supported_yaml": len(_all_chain_dexes),
        "dexes_in_scan_config": len(dexes_list),
        "dexes_active_scanned": stats["dexes_active"],
        "scan_coverage_ratio": round(stats["dexes_active"] / max(len(_all_chain_dexes), 1), 4),
        "config_coverage_ratio": round(len(dexes_list) / max(len(_all_chain_dexes), 1), 4),
        "missing_from_config": sorted(set(_all_chain_dexes) - set(dexes_list)),
        "missing_from_scan": sorted(set(dexes_list) - set(dexes_active_list)),
    }
    
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
        l1_gas_price_gwei = config.get("l1_gas_price_gwei", 3.0)
        gas_config = GasConfig(
            gas_price_gwei=live_gas_price_wei / 1e9,
            eth_usd_price=eth_usd,
            l1_data_gas_units=l1_data_gas_units,
            l1_gas_price_gwei=l1_gas_price_gwei,
            _live_mode=w3_instance is not None,
        )
        
        # R36: Scale min_net_profit_usd proportionally to probe-vs-target ratio.
        # Config min_net_profit_usd ($0.10) is calibrated for target_usd_notional ($150).
        # At discovery_probe_size_usd ($10), must scale: $0.10 × (10/150) ≈ $0.007.
        _probe_usd = config.get(
            "discovery_probe_size_usd",
            config.get("target_usd_notional", 1000.0),
        )
        _target_usd = config.get("target_usd_notional", 1000.0)
        _min_profit_raw = config.get("min_net_profit_usd", 0.10)
        _profit_scale = _probe_usd / _target_usd if _target_usd > 0 else 1.0
        _min_profit_scaled = _min_profit_raw * _profit_scale
        
        opps_list, opps_summary = evaluate_quotes(
            quotes_sample, cycle=0, timestamp=timestamp,
            eth_usd_price=eth_usd,
            min_net_profit_usd=_min_profit_scaled,
            gas_config=gas_config,
            # R36: Use discovery_probe_size_usd as OE target to match actual quote sizing.
            # Previously used target_usd_notional ($150), but quotes are sized at
            # discovery_probe_size_usd ($10) — causing 93% NOTIONAL_DRIFT rejection.
            target_notional_usd=_probe_usd,
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

        # R39v: Truth-lane reranking.
        # When truth_mode_m42, top_opportunities should reflect measured
        # economics (from spread_signals with QuoterV2 slippage), not paper
        # net_profit_usd.  This surfaces stable pairs (USDC/DAI: -17 bps)
        # above toxic volatile routes (WETH/USDC: -282 bps) that pass the
        # paper gate but are deeply unviable when measured.
        _paper_top = opps_list[:5] if opps_list else []
        if truth_mode_m42 and spread_signals:
            _actionable_signals = [
                s for s in spread_signals if not s.get("is_diagnostic_only")
            ]
            _truth_lane_top = sorted(
                _actionable_signals,
                key=lambda s: s.get("spread_minus_required_bps", -9999),
                reverse=True,
            )[:5]
        else:
            _truth_lane_top = None

        stats["opportunity_engine"] = {
            "enabled": True,
            "summary": opps_summary,
            # R39v: measured-economics ranked when truth_mode_m42
            "top_opportunities": _truth_lane_top if _truth_lane_top is not None else _paper_top,
            # R39v: paper-ranked OE opps preserved for diagnostic layer
            "_paper_top_opportunities": _paper_top if _truth_lane_top is not None else [],
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
        from engine.roundtrip import simulate_roundtrip, evaluate_roundtrip_candidates, aggregate_leg_sources
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
        
        # R33: Initialize before conditional block so reprieve/sweep path
        # is reachable even when opps_list is empty (0 gated opportunities).
        eligible_opps = []

        # R34: Hoist _rt_top_n to outer scope — _build_live_candidate_stream
        # uses it even when opps_list is empty (was UnboundLocalError before).
        _rt_top_n = config.get("roundtrip_top_n", 10)

        # R34: Hoist token_decimals to outer scope — reprieve/sweep path needs
        # it even when opps_list is empty (was UnboundLocalError before).
        token_decimals = {}
        if pairs_list:
            for p in pairs_list:
                token_decimals[p.token_in] = p.token_in_decimals
                token_decimals[p.token_out] = p.token_out_decimals
        else:
            try:
                core_tokens = load_core_tokens()
                chain_tokens = core_tokens.get(chain_key, {})
                for symbol, token_data in chain_tokens.items():
                    if isinstance(token_data, dict) and "decimals" in token_data:
                        token_decimals[symbol] = token_data["decimals"]
            except Exception as e:
                logger.warning("Failed to load token_decimals from core_tokens: %s", e)

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
            # R28.28: Candidate selection extracted to strategy.roundtrip_selection
            from strategy.roundtrip_selection import select_roundtrip_candidates, is_cross_dex, lp_fee_viable
            
            # R28.24: Config-driven caps (was hard-coded 20/5, too restrictive)
            _rt_max_candidates = config.get("roundtrip_max_candidates", 50)
            _rt_top_n = config.get("roundtrip_top_n", 10)
            _min_margin_bps = config.get("roundtrip_min_margin_bps", -5.0)
            # R28.27: Cap isolation — lift caps when investigating funnel bottlenecks
            if _cap_switches["uncap_rt_max_candidates"]:
                logger.info("CAP_ISOLATION: roundtrip_max_candidates uncapped (was %d)", _rt_max_candidates)
                _rt_max_candidates = _UNCAPPED
            if _cap_switches["uncap_rt_top_n"]:
                logger.info("CAP_ISOLATION: roundtrip_top_n uncapped (was %d)", _rt_top_n)
                _rt_top_n = _UNCAPPED
            
            eligible_opps, _rt_filter_stats = select_roundtrip_candidates(
                opps_list,
                rt_max_candidates=_rt_max_candidates,
                rt_top_n=_rt_top_n,
                min_margin_bps=_min_margin_bps,
                chain=chain_key,
                reserved_slots=config.get("reserved_candidate_slots"),
                lp_fee_max_bps=config.get("roundtrip_lp_fee_max_bps", 9999.0),
                slippage_max_bps=config.get("roundtrip_slippage_max_bps", 9999.0),
            )
            stats["roundtrip_lp_filter"] = _rt_filter_stats
            
            roundtrip_results, roundtrip_stats = evaluate_roundtrip_candidates(
                opportunities=eligible_opps,
                buy_quotes_by_key=quotes_by_key,
                sell_quotes_by_key=quotes_by_key,
                gas_price_wei=live_gas_price_wei,
                top_n=_rt_top_n,
                leg2_quote_callback_factory=make_leg2_callback,
                l1_cost_wei=l1_cost_wei,
                l1_cost_source=l1_cost_source,
                # v2.8.0: Pass USD prices for cross-token correctness
                eth_usd_price=eth_usd,
                token_usd_prices=config.get("tokens_usd_price") or {},
                token_decimals=token_decimals,  # v2.8.1: Fix decimals bug
            )
        
        # Summarize round-trip results
        # R28.17: Filter out "profitable" roundtrips with absurd PnL (accounting contamination)
        # R38: LST/derivative pairs use tighter threshold (50 bps) to suppress
        # rebasing-differential false positives (WSTETH/WETH, METH/WETH etc).
        from strategy.live_stream import _is_lst_pair, _SANE_RT_PNL_MAX_BPS, _SANE_RT_PNL_MAX_BPS_LST
        rt_profitable = [
            r for r in roundtrip_results
            if r.is_profitable and r.net_pnl_bps <= (
                _SANE_RT_PNL_MAX_BPS_LST if _is_lst_pair(r.pair) else _SANE_RT_PNL_MAX_BPS
            )
        ]
        rt_suspect_profitable = [
            r for r in roundtrip_results
            if r.is_profitable and r.net_pnl_bps > (
                _SANE_RT_PNL_MAX_BPS_LST if _is_lst_pair(r.pair) else _SANE_RT_PNL_MAX_BPS
            )
        ]
        if rt_suspect_profitable:
            logger.warning(
                "SUSPECT_ACCOUNTING: %d roundtrips with absurd pnl filtered from profitable_count",
                len(rt_suspect_profitable),
            )
        rt_using_real_quote = [r for r in roundtrip_results if r.leg2_is_real_quote]
        
        # v2.1.0: Track L1 cost source for transparency
        l1_cost_source_used = l1_cost_source if opps_list else "none"
        l1_cost_wei_used = l1_cost_wei if opps_list else 0
        
        stats["roundtrip"] = {
            "enabled": True,
            "evaluated_count": len(roundtrip_results),
            "profitable_count": len(rt_profitable),
            "suspect_profitable_count": len(rt_suspect_profitable),  # R28.17
            "real_quote_count": len(rt_using_real_quote),
            # R28.7: executable_candidates_count — how many candidates passed ALL pre-filters
            # and were sent to roundtrip evaluation. This is the new primary KPI:
            # signal != opportunity != executable candidate.
            "executable_candidates_count": len(eligible_opps),
            "gas_price_wei_used": live_gas_price_wei,
            "l1_cost_wei": l1_cost_wei_used,  # v2.1.0: L1 cost tracking
            "l1_cost_source": l1_cost_source_used,  # v2.1.0: "onchain" | "config" | "default"
            "results": [r.to_dict() for r in roundtrip_results[:3]],
            # R39i++: Per-leg quote source aggregation for RCA visibility
            "leg_source_summary": aggregate_leg_sources(roundtrip_results),
            # v3.0.0: Aggregation stats for visibility
            "candidates_total": roundtrip_stats.candidates_total,
            "gated_by_economics": roundtrip_stats.gated_by_economics,
            "rejected_reasons": roundtrip_stats.rejected_reasons,
            # v3.2.5: Warnings from roundtrip evaluation (L1 cost source, etc.)
            "warnings": roundtrip_stats.warnings or [],
        }
        
        # R28.18→R28.21: best_net_pnl_bps must be from sane-filtered universe only.
        # Both upper AND lower bound required: absurdly negative values (e.g. -10012 bps
        # on base from diagnostic contamination) are equally invalid as absurd positives.
        _SANE_RT_PNL_MIN = -_SANE_RT_PNL_MAX_BPS  # symmetric: ±500 bps
        sane_rts = [
            r for r in roundtrip_results
            if _SANE_RT_PNL_MIN <= r.net_pnl_bps <= _SANE_RT_PNL_MAX_BPS
        ]
        if sane_rts:
            best_rt = max(sane_rts, key=lambda r: r.net_pnl_bps)
            stats["roundtrip"]["best_net_pnl_bps"] = best_rt.net_pnl_bps
            if rt_profitable:
                logger.info(
                    "Roundtrip: %d/%d profitable, best(sane)=%.2f bps",
                    len(rt_profitable), len(roundtrip_results), best_rt.net_pnl_bps
                )
            else:
                logger.info(
                    "Roundtrip: 0/%d profitable, best(sane,negative)=%.2f bps",
                    len(roundtrip_results), best_rt.net_pnl_bps
                )
        elif roundtrip_results:
            # All roundtrips are insane — report None, not the absurd value
            stats["roundtrip"]["best_net_pnl_bps"] = None
            logger.warning(
                "Roundtrip: 0/%d profitable, ALL %d results outside sane range (±%d bps)",
                len(roundtrip_results), len(roundtrip_results), _SANE_RT_PNL_MAX_BPS,
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
        
        # v3.3.0: Dynamic size sweep — R28.28: extracted to strategy.dynamic_sweep_runtime
        dynamic_probe_cfg = config.get("dynamic_probe", {})
        # R32: Sweep reprieve — when eligible_opps is empty but NET_PROFIT_TOO_LOW
        # rejected opps exist with both legs executable, give them a frontier replay.
        # This prevents single-probe economics from being the final verdict.
        sweep_candidates = list(eligible_opps)
        sweep_reprieve_count = 0
        if not sweep_candidates and dynamic_probe_cfg.get("enabled"):
            from strategy.roundtrip_selection import select_sweep_reprieve_candidates
            # R33: Use rejected opportunities from OE (not gated opps_list)
            rejected_opps = opps_summary.get("_rejected_opportunities", [])
            _reprieve, _reprieve_stats = select_sweep_reprieve_candidates(
                rejected_opps, max_candidates=15
            )
            sweep_candidates = _reprieve
            sweep_reprieve_count = len(_reprieve)
            stats["roundtrip"]["sweep_reprieve_count"] = sweep_reprieve_count
            stats["roundtrip"]["sweep_reprieve_stats"] = _reprieve_stats
            logger.info(
                "Sweep reprieve: selected=%d from %d NET_PROFIT_TOO_LOW rejected (source_count=%d)",
                sweep_reprieve_count,
                _reprieve_stats.get("net_profit_too_low_total", 0),
                len(rejected_opps),
            )

        if dynamic_probe_cfg.get("enabled") and sweep_candidates:
            from strategy.dynamic_sweep_runtime import run_sweep

            sweep_result = run_sweep(
                eligible_opps=sweep_candidates,
                quotes_by_key=quotes_by_key,
                config=config,
                chain_key=chain_key,
                rpc_url=resolved_http,
                current_block=current_block,
                live_gas_price_wei=live_gas_price_wei,
                l1_cost_wei=l1_cost_wei,
                l1_cost_source=l1_cost_source,
                eth_usd=eth_usd,
                token_decimals=token_decimals,
            )
            stats["roundtrip"]["dynamic_sweep"] = sweep_result["dynamic_sweep"]
            stats["roundtrip"].update(sweep_result["executable_evidence"])

            # R36: Sweep frontier promotion — if sweep found a better frontier than
            # fixed-size RT, promote sweep result to headline metrics. This closes
            # the gap where sweep was visibility-only and never influenced the
            # official RT best_net_pnl_bps / profitable_count.
            sweep_ds = sweep_result["dynamic_sweep"]
            sweep_best_pnl = sweep_ds.get("best_net_pnl_bps")
            fixed_best_pnl = stats["roundtrip"].get("best_net_pnl_bps")
            if sweep_best_pnl is not None:
                if fixed_best_pnl is None or sweep_best_pnl > fixed_best_pnl:
                    stats["roundtrip"]["best_net_pnl_bps"] = sweep_best_pnl
                    stats["roundtrip"]["sweep_promoted"] = True
                    stats["roundtrip"]["sweep_promoted_size_usd"] = sweep_ds.get("best_size_usd")
                    stats["roundtrip"]["sweep_promoted_pair"] = sweep_ds.get("best_pair")
                    stats["roundtrip"]["sweep_promoted_frontier_reason"] = sweep_ds.get("best_frontier_reason")
                    logger.info(
                        "SWEEP_PROMOTED: best_net_pnl_bps %.2f bps (was %.2f) at $%s for %s",
                        sweep_best_pnl,
                        fixed_best_pnl if fixed_best_pnl is not None else float("nan"),
                        sweep_ds.get("best_size_usd"),
                        sweep_ds.get("best_pair"),
                    )

        # R39x: Sweep-frontier truth-probe reranking.
        # When truth_mode_m42 and frontier curves exist, rebuild
        # top_opportunities from sweep frontier (gap_to_zero_bps ascending)
        # instead of seed-size spread_minus_required_bps.  This ensures
        # operator-facing truth reflects measured multi-size economics:
        # USDC/DAI (gap=8.67) ranks above WETH/USDC (gap=71.36).
        if truth_mode_m42:
            _rerank_top_opportunities_by_sweep_frontier(stats, logger)

        # R38+R39: Promote sweep best_size_usd as default for live candidates,
        # but only when the frontier is executable (real measured costs, not paper-only).
        _sweep_ds = stats.get("roundtrip", {}).get("dynamic_sweep") or {}
        _sweep_best_size = _sweep_ds.get("best_size_usd")
        _config_size = float(config.get("target_usd_notional") or config.get("paper_size_usd") or 0.0)
        # R39: Guard — only promote when frontier is executable:
        # 1) frontier_reason indicates real evaluation (not ALL_FAILED/ALL_SUSPECT_OUTLIER)
        # 2) measured_total_cost_bps > 0 (some cost was measured)
        # 3) measured_slippage_bps is not None (slippage was explicitly measured)
        _sweep_frontier = _sweep_ds.get("best_frontier_reason") or _sweep_ds.get("sweep_best_frontier_reason")
        _sweep_total_cost = _sweep_ds.get("best_total_cost_bps")
        _sweep_slip = _sweep_ds.get("best_slippage_bps")
        _sweep_is_executable = (
            _sweep_best_size is not None
            and _sweep_best_size > 0
            and _sweep_frontier in ("BREAKEVEN_FRONTIER", "PROFITABLE", "EXECUTABLE_BEST_NEG")
            and _sweep_total_cost is not None
            and _sweep_total_cost > 0
            and _sweep_slip is not None
        )
        _default_size = float(_sweep_best_size) if _sweep_is_executable else _config_size
        stats["live_candidate_stream"] = _build_live_candidate_stream(
            chain_key=chain_key,
            opportunities=eligible_opps if opps_list else [],
            roundtrip_results=roundtrip_results,
            dynamic_sweep=_sweep_ds or None,
            default_size_usd=_default_size,
            max_candidates=_rt_top_n,
            sweep_candidates=sweep_candidates,
        )
        _emit_phase(
            "candidate_snapshot",
            chain=chain_key,
            candidate_count=len(stats["live_candidate_stream"]),
            candidates=stats["live_candidate_stream"],
        )
            
    except Exception as rt_err:
        logger.warning("Roundtrip evaluation error: %s", rt_err)
        # R34: Preserve sweep_reprieve data that was collected before the crash.
        # Don't blindly overwrite stats["roundtrip"] — merge error into existing.
        existing_rt = stats.get("roundtrip", {})
        stats["roundtrip"] = {
            "enabled": False,
            "error": str(rt_err),
            "sweep_reprieve_count": existing_rt.get("sweep_reprieve_count", 0),
            "sweep_reprieve_stats": existing_rt.get("sweep_reprieve_stats"),
            "dynamic_sweep": existing_rt.get("dynamic_sweep"),
            "executable_candidates_count": existing_rt.get("executable_candidates_count", 0),
        }
        # R34: Still attempt to build live_stream from whatever was collected
        try:
            # R38+R39: Same executable-frontier guard as primary path
            _err_ds = existing_rt.get("dynamic_sweep") or {}
            _err_sweep_size = _err_ds.get("best_size_usd")
            _err_config_size = float(config.get("target_usd_notional") or config.get("paper_size_usd") or 0.0)
            _err_frontier = _err_ds.get("best_frontier_reason") or _err_ds.get("sweep_best_frontier_reason")
            _err_total_cost = _err_ds.get("best_total_cost_bps")
            _err_slip = _err_ds.get("best_slippage_bps")
            _err_is_executable = (
                _err_sweep_size is not None
                and _err_sweep_size > 0
                and _err_frontier in ("BREAKEVEN_FRONTIER", "PROFITABLE", "EXECUTABLE_BEST_NEG")
                and _err_total_cost is not None
                and _err_total_cost > 0
                and _err_slip is not None
            )
            _err_default_size = float(_err_sweep_size) if _err_is_executable else _err_config_size
            stats["live_candidate_stream"] = _build_live_candidate_stream(
                chain_key=chain_key,
                opportunities=eligible_opps if opps_list else [],
                roundtrip_results=[],
                dynamic_sweep=_err_ds or None,
                default_size_usd=_err_default_size,
                max_candidates=_rt_top_n,
                sweep_candidates=sweep_candidates,
            )
        except Exception:
            stats["live_candidate_stream"] = []
    
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
    
    _emit_phase(
        "preflight_finished",
        chain=chain_key,
        passed=stats.get("preflight", {}).get("passed", False) if isinstance(stats.get("preflight"), dict) else False,
        execution_ready=stats.get("execution_ready_count", 0),
        would_execute=stats.get("would_execute_count", 0),
    )
    
    # v2.4.1: M4.3 Preflight EVIDENCE (eth_call/eth_estimateGas for top-N)
    # Collects actual RPC evidence without executing any transactions
    # Uses opps_list (gated opportunities) instead of spread_signals
    # R28.17: COVERAGE runs now use same truth path (no lightweight skip)
    _phase_preflight_start = _time.monotonic()
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
    
    # R28.15→R28.28: Live execution probe — extracted to strategy.execution_probe
    _phase_exec_start = _time.monotonic()
    from strategy.execution_probe import probe_live_execution
    stats["live_execution"] = probe_live_execution(config, provider_http, opps_list)
    _phase_exec_end = _time.monotonic()
    
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
        # R39s: Use post-clamp pair list when include_pairs clamp was applied.
        # _discovery_runtime_resolved has per-pool detail (dex, fee, pool_address);
        # pairs_list has PairConfig objects with different attributes.
        # Filter _discovery_runtime_resolved to match post-clamp whitelist.
        _clamp_info = stats.get("include_pairs_clamp")
        if _clamp_info:
            _allowed = set(config.get("include_pairs", []))
            _display_pairs = [
                p for p in _discovery_runtime_resolved
                if p.display_name in _allowed
            ]
        else:
            _display_pairs = _discovery_runtime_resolved
        _display_count = len(_display_pairs) if _display_pairs else _discovery_runtime_stats.cross_dex_pairs_count
        stats["discovery_runtime"]["cross_dex_pairs_count"] = _display_count
        stats["discovery_runtime"]["resolved_pairs"] = [
            {
                "pair": p.display_name,
                "dex": p.dex,
                "fee": p.fee,
                "pool": p.pool_address,
            }
            for p in (_display_pairs or [])
        ]
        if _clamp_info:
            stats["discovery_runtime"]["pre_clamp_resolved"] = _discovery_runtime_stats.cross_dex_pairs_count
        logger.info(
            "Discovery runtime (universe active): %d pairs resolved%s, %d rpc_calls",
            _display_count,
            f" (pre-clamp: {_discovery_runtime_stats.cross_dex_pairs_count})" if _clamp_info else "",
            _discovery_runtime_stats.rpc_calls,
        )
    elif discovery_runtime:
        try:
            from discovery.runtime import resolve_runtime_pairs, get_runtime_observability
            
            dexes_list_rt = config.get("dexes") or None
            max_pairs = config.get("discovery_runtime_max_pairs", 20)
            # R28.27: Cap isolation consistency with primary discovery path
            if _cap_switches["uncap_discovery_max_pairs"]:
                max_pairs = _UNCAPPED
            
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
    
    # =========================================================================
    # R28.24: Filter funnel artifact — per-chain stage counters
    # Consolidates all filter stages into a single diagnostic dict for
    # operator visibility into where candidates are lost in the pipeline.
    # =========================================================================
    _opp_engine = stats.get("opportunity_engine", {})
    _opp_summary = _opp_engine.get("summary", {}) if _opp_engine.get("enabled") else {}
    _rt = stats.get("roundtrip", {})
    _rt_filter = stats.get("roundtrip_lp_filter", {})
    # R28.30+: cross_dex_pairs_count — truthful for ALL universe paths
    # discovery_runtime tracks it via RuntimeStats; for config/intent/hot paths,
    # compute from actual fetched quotes (pairs with quotes from >=2 distinct DEXes).
    _disc_rt = stats.get("discovery_runtime", {})
    _cross_dex_pairs = _disc_rt.get("cross_dex_pairs_count", 0) if _disc_rt.get("universe_active") else 0
    if _cross_dex_pairs == 0 and quotes_sample:
        # R28.30+: Compute cross_dex from actual fetched quotes (fallback for config/intent/hot paths).
        # Quotes use token_in/token_out as pair identifier, not 'pair' key.
        _pair_dexes: dict = {}
        for _q in quotes_sample:
            # Construct pair key from token symbols (quotes use token_in/token_out)
            _tin = _q.get("token_in") or ""
            _tout = _q.get("token_out") or ""
            _pname = f"{_tin}/{_tout}" if _tin and _tout else ""
            _dex = _q.get("dex_id") or ""
            if _pname and _dex:
                _pair_dexes.setdefault(_pname, set()).add(_dex)
        _cross_dex_pairs = sum(1 for _dxs in _pair_dexes.values() if len(_dxs) >= 2)
    stats["filter_funnel"] = {
        # Stage 1: Universe resolution
        "resolved_pairs": len(pairs_list) if pairs_list else 0,
        "cross_dex_pairs_count": _cross_dex_pairs,
        # Stage 2: Quote collection
        "quotes_attempted": stats.get("quotes_total", 0),
        "quotes_fetched": stats.get("quotes_fetched", 0),
        "quarantined_skipped": stats.get("quarantined_count", 0),
        "runtime_disabled_skipped": stats.get("runtime_disabled_count", 0),
        "pool_missing_skipped": stats.get("pool_missing_count", 0),
        # Stage 3: Spread signal computation (cross-dex price comparisons)
        "spread_signals": len(spread_signals),
        # Stage 4: OpportunityEngine (pair×route×fee combinatorics — NOT downstream of spread_signals)
        # NOTE: opp_engine_combinations >= spread_signals is normal because OpportunityEngine
        # builds all pair×route×fee-tier combinations from quotes, independently of spread_signals.
        "opp_engine_combinations": _opp_summary.get("total_opportunities", 0),
        "opp_profitable_diagnostic": _opp_summary.get("profitable_count", 0),
        # Stage 5: Roundtrip candidate selection (cross-dex, LP viable, margin filter)
        "rt_candidates_considered": _rt_filter.get("candidates_considered", 0),
        "rt_cross_dex": _rt_filter.get("cross_dex_count", 0),
        "rt_lp_viable": _rt_filter.get("lp_viable_count", 0),
        "rt_unique_pairs": _rt_filter.get("unique_pairs_considered", 0),
        "rt_margin_filtered": _rt_filter.get("margin_filtered_count", 0),
        "rt_passed_to_eval": _rt_filter.get("passed_to_roundtrip", 0),
        # Stage 6: Roundtrip evaluation (live re-quote, cost model, PnL)
        "rt_evaluated": _rt.get("evaluated_count", 0),
        "rt_real_quote": _rt.get("real_quote_count", 0),
        "rt_profitable": _rt.get("profitable_count", 0),
        # R32: Sweep reprieve — NET_PROFIT_TOO_LOW opps promoted to frontier sweep
        "sweep_reprieve_count": _rt.get("sweep_reprieve_count", 0),
    }
    
    # =========================================================================
    # R29: Pair-level funnel trace (extracted to strategy/pair_trace.py)
    # =========================================================================
    try:
        roundtrip_results  # noqa: B018
    except NameError:
        roundtrip_results = []
    try:
        eligible_opps  # noqa: B018
    except NameError:
        eligible_opps = []
    try:
        sweep_candidates  # noqa: B018
    except NameError:
        sweep_candidates = []
    # R36: Collect per-route sweep results for pair_trace
    _sweep_results_for_trace = (stats.get("roundtrip") or {}).get("dynamic_sweep") or {}
    _sweep_results_for_trace = _sweep_results_for_trace.get("results", [])
    from strategy.pair_trace import build_pair_funnel_trace
    stats["pair_funnel_trace"] = build_pair_funnel_trace(
        pairs_list=pairs_list,
        quotes_sample=quotes_sample,
        rejected_quotes=rejected_quotes,
        spread_signals=spread_signals,
        opps_list=opps_list,
        roundtrip_results=roundtrip_results,
        eligible_opps=eligible_opps,
        sweep_candidates=sweep_candidates,
        sweep_results=_sweep_results_for_trace,
    )

    # R39r+: Per-pool usage report — pool-level visibility for operator RCA.
    # Shows which pools are productive vs dead weight in the active contour.
    _pool_usage: Dict[str, Dict[str, Any]] = {}
    for q in quotes_sample:
        _pa = q.get("pool_address", "")
        if not _pa:
            continue
        if _pa not in _pool_usage:
            _pool_usage[_pa] = {
                "pool_address": _pa,
                "pair": q.get("token_in", "") + "/" + q.get("token_out", ""),
                "dex_id": q.get("dex_id", ""),
                "fee": q.get("fee"),
                "quotes_fetched": 0,
                "quotes_rejected": 0,
                "spread_signals": 0,
                "opp_count": 0,
                "rt_evaluated": 0,
            }
        _pool_usage[_pa]["quotes_fetched"] += 1
    for rq in rejected_quotes:
        _pa = rq.get("pool_address", "")
        if not _pa:
            continue
        if _pa not in _pool_usage:
            _pool_usage[_pa] = {
                "pool_address": _pa,
                "pair": rq.get("pair", ""),
                "dex_id": rq.get("dex_id", ""),
                "fee": rq.get("fee"),
                "quotes_fetched": 0,
                "quotes_rejected": 0,
                "spread_signals": 0,
                "opp_count": 0,
                "rt_evaluated": 0,
            }
        _pool_usage[_pa]["quotes_rejected"] += 1
    for ss in spread_signals:
        for side in ("buy", "sell"):
            _pa = ss.get(f"{side}_pool", "")
            if _pa in _pool_usage:
                _pool_usage[_pa]["spread_signals"] += 1
    for opp in opps_list:
        if isinstance(opp, dict):
            _diag = opp.get("diagnostics") or {}
            for side in ("buy_pool", "sell_pool"):
                _pa = _diag.get(side, "")
                if _pa and _pa in _pool_usage:
                    _pool_usage[_pa]["opp_count"] += 1
    for rt_r in roundtrip_results:
        for attr in ("leg1_pool", "leg2_pool"):
            _pa = getattr(rt_r, attr, "") or ""
            if _pa in _pool_usage:
                _pool_usage[_pa]["rt_evaluated"] += 1
    stats["pool_usage_report"] = sorted(
        _pool_usage.values(),
        key=lambda x: x["quotes_fetched"],
        reverse=True,
    )

    # R39r+ steps 2-4: Flashblocks execution proof probe for Base chain.
    # Proves eth_simulateV1 and base_transactionStatus participate in runtime,
    # not just health badge. Uses Flashblocks HTTP for pending-state QuoterV2 call.
    if chain_key == "base" and spread_signals:
        try:
            from chains.flashblocks import (
                eth_simulate_v1,
                base_transaction_status,
                get_flashblocks_http_url,
            )
            from dex.adapters.uniswap_v3 import encode_quote_exact_input_single

            _fb_http = get_flashblocks_http_url(config.get("flashblocks_http_endpoint"))
            _fb_probe_results = []

            # Probe top 3 spread signals with eth_simulateV1
            for _ss in spread_signals[:3]:
                _buy_pool = _ss.get("buy_pool", "")
                _pair = _ss.get("pair", "")
                _buy_dex = _ss.get("buy_dex", "")
                _buy_fee = _ss.get("buy_fee", 3000)
                # Spread signals store tokens as pair string "TOKEN_IN/TOKEN_OUT"
                _pair_tokens = _pair.split("/") if _pair else []
                _tin = _pair_tokens[0] if len(_pair_tokens) > 1 else ""
                _tout = _pair_tokens[1] if len(_pair_tokens) > 1 else ""

                # Resolve token addresses for QuoterV2 encoding
                _tin_addr = get_token_address(chain_key, _tin) if _tin else None
                _tout_addr = get_token_address(chain_key, _tout) if _tout else None

                # Resolve quoter address for the buy DEX
                _dex_cfg = get_dex_config(chain_key, _buy_dex) if _buy_dex else None
                _quoter_addr = _dex_cfg.get_quoter_address() if _dex_cfg else None

                if not _tin_addr or not _tout_addr or not _quoter_addr:
                    _fb_probe_results.append({
                        "pair": _pair,
                        "dex": _buy_dex,
                        "sim_success": False,
                        "sim_error": "missing_addresses",
                        "sim_gas_used": None,
                    })
                    continue

                # Encode QuoterV2 call for eth_simulateV1
                _probe_amount = int(50e6)  # 50 USDC (6 decimals) as probe
                # For non-stablecoin inputs, use 1e16 (~0.01 ETH)
                if _tin not in ("USDC", "USDT", "DAI", "USDbC"):
                    _probe_amount = int(1e16)

                _calldata = encode_quote_exact_input_single(
                    token_in=_tin_addr,
                    token_out=_tout_addr,
                    amount_in=_probe_amount,
                    fee=_buy_fee,
                )
                _sim_tx = {
                    "from": "0x0000000000000000000000000000000000000000",
                    "to": _quoter_addr,
                    "data": "0x" + _calldata if not _calldata.startswith("0x") else _calldata,
                }
                _sim = eth_simulate_v1(_sim_tx, http_url=_fb_http, timeout_s=5.0)
                _fb_probe_results.append({
                    "pair": _pair,
                    "dex": _buy_dex,
                    "sim_success": _sim["success"],
                    "sim_error": _sim.get("error"),
                    "sim_gas_used": _sim.get("gas_used"),
                })

            # Diagnostic: call base_transactionStatus with a null hash
            # Proves the RPC method exists and endpoint responds
            _tx_status = base_transaction_status(
                tx_hash="0x0000000000000000000000000000000000000000000000000000000000000000",
                http_url=_fb_http,
                timeout_s=3.0,
            )

            _sim_success_count = sum(1 for r in _fb_probe_results if r["sim_success"])
            stats["flashblocks_execution_proof"] = {
                "http_endpoint": _fb_http,
                "probed_count": len(_fb_probe_results),
                "sim_success_count": _sim_success_count,
                "sim_results": _fb_probe_results,
                "tx_status_reachable": _tx_status.get("status") != "error",
                "tx_status_raw": _tx_status,
            }
            if _sim_success_count > 0:
                logger.info(
                    "Flashblocks execution proof: %d/%d sim OK via %s",
                    _sim_success_count, len(_fb_probe_results), _fb_http,
                )
            else:
                logger.info(
                    "Flashblocks execution proof: 0/%d sim OK (endpoint: %s, error: %s)",
                    len(_fb_probe_results), _fb_http,
                    _fb_probe_results[0].get("sim_error") if _fb_probe_results else "none",
                )
        except Exception as _fb_err:
            logger.debug("Flashblocks execution proof skipped: %s", _fb_err)
            stats["flashblocks_execution_proof"] = {
                "probed_count": 0,
                "sim_success_count": 0,
                "error": str(_fb_err),
            }

    # R28.24: Roundtrip truth status — separate from diagnostic profit_status.
    # When roundtrip.profitable_count=0 but one-leg total_net_usdc>0,
    # operator must see that no real roundtrip profit exists.
    # R28.28: Scanner produces granular 5-value status; m4 canonical is 3-value.
    # Both are emitted: roundtrip_truth_status (granular) + roundtrip_truth_canonical (m4-aligned).
    _TRUTH_TO_CANONICAL = {
        "PROFITABLE": "PROFITABLE",
        "EVALUATED_NOT_PROFITABLE": "NOT_PROFITABLE",
        "CANDIDATES_NOT_EVALUATED": "NOT_PROFITABLE",
        "NO_CANDIDATES": "NO_DATA",
        "ROUNDTRIP_DISABLED": "NO_DATA",
    }
    if _rt.get("enabled"):
        _rt_profitable_count = _rt.get("profitable_count", 0)
        if _rt_profitable_count > 0:
            stats["roundtrip_truth_status"] = "PROFITABLE"
        elif _rt.get("evaluated_count", 0) > 0:
            stats["roundtrip_truth_status"] = "EVALUATED_NOT_PROFITABLE"
        elif _rt_filter.get("passed_to_roundtrip", 0) > 0:
            stats["roundtrip_truth_status"] = "CANDIDATES_NOT_EVALUATED"
        else:
            stats["roundtrip_truth_status"] = "NO_CANDIDATES"
    else:
        stats["roundtrip_truth_status"] = "ROUNDTRIP_DISABLED"
    stats["roundtrip_truth_canonical"] = _TRUTH_TO_CANONICAL.get(
        stats["roundtrip_truth_status"], "NO_DATA"
    )
    
    # R28.5: Report phase — artifact writing and state flush
    _phase_report_start = _time.monotonic()
    
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
    
    # R28.5: Compute phase timers BEFORE write_artifacts so they appear in scan artifact.
    # build_scan_data stores stats by reference, so mutating stats here propagates.
    _phase_pre_write = _time.monotonic()
    stats["phase_timers_ms"] = {
        "total_ms": int((_phase_pre_write - _phase_t0) * 1000),
        "discovery_ms": int((_phase_discovery_end - _phase_t0) * 1000),
        "quote_rpc_ms": int((_phase_quote_end - _phase_quote_start) * 1000),
        "postprocess_ms": int((_phase_preflight_start - _phase_postprocess_start) * 1000),
        "preflight_ms": int((_phase_preflight_end - _phase_preflight_start) * 1000),
        "exec_probe_ms": int((_phase_exec_end - _phase_exec_start) * 1000),
        "report_ms": int((_phase_pre_write - _phase_report_start) * 1000),
        # Legacy aliases for backward compatibility
        "init_rpc_ms": int((_phase_discovery_end - _phase_t0) * 1000),
        "post_scan_ms": int((_phase_pre_write - _phase_preflight_end) * 1000),
    }
    
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
    
    # Update total_ms and report_ms with final values (including write + flush time)
    _phase_end = _time.monotonic()
    stats["phase_timers_ms"]["total_ms"] = int((_phase_end - _phase_t0) * 1000)
    stats["phase_timers_ms"]["report_ms"] = int((_phase_end - _phase_report_start) * 1000)
    stats["phase_timers_ms"]["post_scan_ms"] = int((_phase_end - _phase_preflight_end) * 1000)

    # R28.6: Patch scan artifact on disk with final phase_timers (including write+flush time)
    # Only needed when artifacts were written to disk (artifact_mode != "rolling" or status != "PASS")
    scan_artifact_path = artifacts.get("scan")
    if isinstance(scan_artifact_path, Path) and scan_artifact_path.exists():
        try:
            import json as _json_patch
            _scan_on_disk = _json_patch.loads(scan_artifact_path.read_text(encoding="utf-8"))
            _scan_on_disk["stats"]["phase_timers_ms"] = stats["phase_timers_ms"]
            from core.json_io import atomic_write_json
            atomic_write_json(scan_artifact_path, _scan_on_disk, default=str)
        except Exception as _patch_err:
            logger.debug("phase_timers patch skipped: %s", _patch_err)

    logger.info(
        "Phase timers: total=%dms discovery=%dms quote=%dms postprocess=%dms preflight=%dms report=%dms",
        stats["phase_timers_ms"]["total_ms"],
        stats["phase_timers_ms"]["discovery_ms"],
        stats["phase_timers_ms"]["quote_rpc_ms"],
        stats["phase_timers_ms"]["postprocess_ms"],
        stats["phase_timers_ms"]["preflight_ms"],
        stats["phase_timers_ms"]["report_ms"],
    )
    
    _emit_phase(
        "gate_finished",
        chain=chain_key,
        signals=len(spread_signals),
        total_ms=stats["phase_timers_ms"]["total_ms"],
        quotes_fetched=stats.get("quotes_fetched", 0),
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
