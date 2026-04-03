"""
M7 orderflow ws-live mode handler.

Extracted from cli.py to keep the CLI dispatcher under 1000 lines.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from config import load_dexes, get_all_token_addresses, load_chains
from core.rpc_urls import resolve_rpc_http, resolve_rpc_ws, _CHAIN_KEY_TO_ID

from m7.shared.constants import (
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_SUBGRAPH_VERIFIED,
    CHAINLINK_FEEDS_ARBITRUM,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    SWAP_EVENT_TOPIC,
    UNSCORED_REJECTS,
)
from m7.orderflow.artifacts import build_replay_summary
from m7.orderflow.coverage import seed_tokens_from_subgraph
from m7.orderflow.events import normalize_swap_log
from m7.orderflow.pool_registry import PoolRegistry
from m7.orderflow.resolve import _build_address_to_symbol
from m7.orderflow.scoring_parallel import score_backrun_live_parallel, score_backrun_fast
from m7.orderflow.contracts import BackrunResult

logger = logging.getLogger("m7.orderflow.cli")


def run_ws_live(args, *, external_registry=None) -> dict:
    """Execute the ws-live WebSocket replay mode and return the artifact dict.

    Parameters
    ----------
    args : namespace with ws_blocks, ws_timeout, max_events, chain.
    external_registry : optional pre-warmed PoolRegistry.  When provided,
        session prewarm is skipped and this registry is used directly.
        The caller retains ownership and can accumulate state across calls.
    """
    logger.info(
        "Running M7.A.5.3 ws-live replay (ws_blocks=%d, ws_timeout=%ds)",
        args.ws_blocks,
        args.ws_timeout,
    )

    chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())

    # Resolve HTTP RPC for quoting
    rpc_url, rpc_provider, rpc_diag = resolve_rpc_http(
        chain_id=chain_id,
        network=args.chain,
        env=dict(os.environ),
    )
    if not rpc_url:
        raise SystemExit(f"No HTTP RPC URL found for chain: {args.chain}")
    rpc_host = urlparse(rpc_url).netloc

    # Resolve WebSocket for newHeads subscription
    ws_url, ws_provider, ws_diag = resolve_rpc_ws(
        chain_id=chain_id,
        network=args.chain,
        env=dict(os.environ),
    )
    if not ws_url:
        raise SystemExit(
            f"No WebSocket RPC URL found for chain: {args.chain}. "
            "Set ALCHEMY_API_KEY or ALCHEMY_RPC_WS in .env"
        )
    ws_host = urlparse(ws_url).netloc

    logger.info(
        "RPC resolved: http=%s ws=%s ws_provider=%s",
        rpc_host,
        ws_host,
        ws_provider,
        extra={"context": {
            "rpc_provider": rpc_provider,
            "ws_provider": ws_provider,
            "rpc_host": rpc_host,
            "ws_host": ws_host,
        }},
    )

    all_dexes = load_dexes()
    dex_configs = all_dexes.get(args.chain, {})
    token_addresses = get_all_token_addresses(args.chain)
    addr_to_symbol = _build_address_to_symbol(token_addresses)

    # M7.A.5.22: Session-scoped pool registry for factory-driven discovery
    # M7.A.5.31: Accept external registry; skip prewarm if caller provided one
    _prewarm_count = 0
    if external_registry is not None:
        session_registry = external_registry
        _prewarm_count = -1  # signal: prewarm handled by caller
    else:
        session_registry = PoolRegistry()

    # M7.A.5.24: Session prewarm — preload high-frequency pairs from known addresses
    # Core pairs that appear frequently in Arbitrum orderflow
    _prewarm_pairs = [
        ("WETH", "USDC"), ("WETH", "USDT"), ("WETH", "ARB"),
        ("USDC", "USDT"), ("WETH", "WBTC"), ("ARB", "USDC"),
    ]
    if _prewarm_count != -1:
        _prewarm_count = 0
        try:
            from web3 import Web3 as _W3pw
            _w3pw = _W3pw(_W3pw.HTTPProvider(rpc_url))
            _pw_block = _w3pw.eth.block_number
            for _sym_a, _sym_b in _prewarm_pairs:
                _addr_a = token_addresses.get(_sym_a, "")
                _addr_b = token_addresses.get(_sym_b, "")
                if _addr_a and _addr_b:
                    try:
                        session_registry.preload_pair(
                            _addr_a, _addr_b, dex_configs, rpc_url, _pw_block,
                        )
                        _prewarm_count += 1
                    except Exception:
                        pass
            logger.info("Session prewarm: %d/%d pairs loaded", _prewarm_count, len(_prewarm_pairs))
        except Exception as _pw_exc:
            logger.debug("Session prewarm skipped: %s", str(_pw_exc)[:80])
    else:
        logger.info("Session prewarm skipped: external registry provided")

    # M7.A.5.8: Subgraph-backed bounded coverage seed
    pre_seed_count = len(addr_to_symbol)
    subgraph_seed_stats = {"tokens_discovered": 0, "tokens_new": 0,
                           "tokens_verified": 0, "sources_queried": [], "errors": []}
    subgraph_seeded_addrs: set = set()
    try:
        from web3 import Web3
        w3_seed = Web3(Web3.HTTPProvider(rpc_url))
        seed_block = w3_seed.eth.block_number
        subgraph_seed_stats = seed_tokens_from_subgraph(
            addr_to_symbol, rpc_url, seed_block, chain=args.chain,
        )
        post_seed_count = len(addr_to_symbol)
        if post_seed_count > pre_seed_count:
            canonical_addrs = set(_build_address_to_symbol(token_addresses).keys())
            subgraph_seeded_addrs = set(addr_to_symbol.keys()) - canonical_addrs
        logger.info(
            "Subgraph seed: discovered=%d new=%d verified=%d sources=%s",
            subgraph_seed_stats["tokens_discovered"],
            subgraph_seed_stats["tokens_new"],
            subgraph_seed_stats["tokens_verified"],
            subgraph_seed_stats["sources_queried"],
        )
    except Exception as exc:
        logger.debug("Subgraph seed failed (best-effort): %s", str(exc)[:100])
        subgraph_seed_stats["errors"].append(f"seed_init: {str(exc)[:80]}")

    # Load block_time_ms from chains.yaml for latency budget
    chain_cfg = load_chains().get(args.chain, {})
    block_time_ms = chain_cfg.get("block_time_ms", 250)

    # Subscribe to newHeads via WebSocket and process blocks
    import websocket as ws_mod

    all_events = []
    all_results = []
    blocks_processed = 0
    raw_logs_total = 0
    ws_start_time = time.monotonic()

    # M7.A.5.23: Session-persistent low-lag tracking across blocks
    _session_low_lag_pairs: Dict[str, Dict] = {}  # pair -> tracking info

    try:
        ws_conn = ws_mod.create_connection(ws_url, timeout=10)
        sub_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newHeads"],
        })
        ws_conn.send(sub_msg)
        sub_response = ws_conn.recv()
        sub_data = json.loads(sub_response)
        sub_id = sub_data.get("result")
        if not sub_id:
            raise RuntimeError(f"WebSocket subscription failed: {sub_data}")
        logger.info(
            "WebSocket newHeads subscribed: sub_id=%s",
            sub_id,
            extra={"context": {"ws_url": ws_host, "sub_id": sub_id}},
        )

        ws_conn.settimeout(args.ws_timeout)

        while blocks_processed < args.ws_blocks:
            elapsed = time.monotonic() - ws_start_time
            if elapsed > args.ws_timeout:
                logger.info("ws-live timeout reached (%ds)", args.ws_timeout)
                break

            try:
                msg = ws_conn.recv()
            except Exception:
                logger.info("WebSocket recv timeout or error after %d blocks", blocks_processed)
                break

            data = json.loads(msg)
            params = data.get("params", {})
            result = params.get("result", {})
            block_hex = result.get("number")
            if not block_hex:
                continue

            detected_block = int(block_hex, 16)
            blocks_processed += 1
            logger.info(
                "newHead #%d: block=%d (processed %d/%d)",
                detected_block,
                detected_block,
                blocks_processed,
                args.ws_blocks,
                extra={"context": {"block": detected_block}},
            )

            # Fetch swap logs for THIS block only
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(rpc_url))
            try:
                logs = w3.eth.get_logs({
                    "fromBlock": detected_block,
                    "toBlock": detected_block,
                    "topics": [SWAP_EVENT_TOPIC],
                })
            except Exception as exc:
                logger.debug(
                    "Failed to fetch logs for block %d: %s",
                    detected_block,
                    str(exc)[:100],
                )
                continue

            raw_logs_total += len(logs)
            if not logs:
                continue

            # Normalize logs
            block_events = []
            for i, log_entry in enumerate(logs):
                ev = normalize_swap_log(
                    log=log_entry,
                    addr_to_symbol=addr_to_symbol,
                    token_addresses=token_addresses,
                    dex_configs=dex_configs,
                    event_index=i,
                )
                if ev is not None:
                    block_events.append(ev)

            if not block_events:
                continue

            # Sort by size, take up to max_events per block
            block_events.sort(key=lambda e: e.estimated_size_usd, reverse=True)
            events_to_score = block_events[:max(1, args.max_events // args.ws_blocks)]

            # M7.A.5.24: Two-queue priority — low-lag events first
            # Events with detection_lag <= 2 get scored before stale events
            # so they don't compete for the same scoring budget.
            _low_lag_queue = [e for e in events_to_score if (detected_block - e.block_number) <= 2]
            _stale_queue = [e for e in events_to_score if (detected_block - e.block_number) > 2]
            events_to_score = _low_lag_queue + _stale_queue

            # Score with parallel pipeline
            current_block = detected_block
            _hot_mode = external_registry is not None
            for ev in events_to_score:
                r = None
                # M7.A.5.33: Hot-mode fast path — zero-RPC scoring via prewarmed registry
                if _hot_mode:
                    r = score_backrun_fast(
                        event=ev,
                        pool_registry=session_registry,
                        token_addresses=token_addresses,
                        current_block=current_block,
                        event_detected_at_block=detected_block,
                        block_time_ms=block_time_ms,
                        addr_to_symbol=addr_to_symbol,
                    )
                    # M7.A.5.34: Hot mode — no parallel fallback. If fast path
                    # returns None (pair not in registry / no state), create a
                    # lightweight skip result. This eliminates ~1940ms parallel
                    # pipeline latency from the hot lane entirely.
                    if r is None:
                        _pair = f"{ev.token_in}/{ev.token_out}"
                        r = BackrunResult(
                            event_id=ev.event_id,
                            event_source="live",
                            event_type=ev.event_type,
                            post_trade_state_used="live",
                            backrun_direction="skip",
                            reject_reason="REJECT_NOT_IN_HOT_REGISTRY",
                            event_block=ev.block_number,
                            quote_block=current_block,
                            block_lag=current_block - ev.block_number,
                            event_detected_at_block=detected_block,
                            actual_pair=_pair,
                            scoring_path="hot_skip",
                        )
                else:
                    # Cold lane: full pipeline
                    r = score_backrun_live_parallel(
                        event=ev,
                        rpc_url=rpc_url,
                        dex_configs=dex_configs,
                        token_addresses=token_addresses,
                        current_block=current_block,
                        ws_provider=ws_provider,
                        event_detected_at_block=detected_block,
                        fallback_rpc_urls=None,
                        block_time_ms=block_time_ms,
                        addr_to_symbol=addr_to_symbol,
                        subgraph_seeded_addrs=subgraph_seeded_addrs,
                        pool_registry=session_registry,
                    )
                # Attach source event for downstream fast-path re-scoring
                r._source_event = ev
                all_results.append(r)
                all_events.append(ev)

                # M7.A.5.23: Accumulate low-lag scoring path data
                # Use detection-time lag (current_block - event.block_number)
                # not final block_lag (which includes scoring latency)
                _ev_lag = current_block - ev.block_number
                if _ev_lag <= 2:
                    _pair_key = r.actual_pair or f"{ev.token_in}/{ev.token_out}"
                    if _pair_key in _session_low_lag_pairs:
                        _slp = _session_low_lag_pairs[_pair_key]
                        _slp["seen_count"] += 1
                        _slp["last_block"] = max(_slp["last_block"], ev.block_number)
                        if r.reject_reason is None or r.reject_reason not in UNSCORED_REJECTS:
                            _slp["scored_count"] += 1
                        if getattr(r, "scoring_path", None) == "registry_direct":
                            _slp["registry_direct_count"] += 1
                    else:
                        _session_low_lag_pairs[_pair_key] = {
                            "pair": _pair_key,
                            "first_block": ev.block_number,
                            "last_block": ev.block_number,
                            "seen_count": 1,
                            "scored_count": (
                                1 if r.reject_reason is None
                                or r.reject_reason not in UNSCORED_REJECTS
                                else 0
                            ),
                            "registry_direct_count": (
                                1 if getattr(r, "scoring_path", None)
                                == "registry_direct" else 0
                            ),
                        }

                if len(all_results) >= args.max_events:
                    break

            if len(all_results) >= args.max_events:
                logger.info("max_events reached (%d), stopping", args.max_events)
                break

    except Exception as exc:
        logger.warning(
            "WebSocket error: %s (scored %d events from %d blocks)",
            str(exc)[:200],
            len(all_results),
            blocks_processed,
        )
    finally:
        try:
            ws_conn.close()
        except Exception:
            pass

    ws_elapsed = time.monotonic() - ws_start_time

    # Build artifact
    artifact = build_replay_summary(all_events, all_results, mode="ws_live")
    # M7.A.5.34: Preserve raw BackrunResult objects for hot lane downstream.
    # build_replay_summary serialises results to dicts; the outer loop needs
    # the original objects for _write_hot_artifact() attribute access.
    artifact["_raw_results"] = all_results
    artifact["m7a56_hypothesis"] = (
        "same-chain backrun on arbitrum_one may become measurable only after "
        "pair-resolved counter-venue coverage is expanded for actual live-event "
        "tokens; no expansion outside current DEX domain"
    )
    artifact["m7a57_hypothesis"] = (
        "same-chain backrun on arbitrum_one may become measurable once "
        "pair-resolved live-event tokens are admitted through bounded discovery "
        "coverage (on-chain ERC-20 enrichment + oracle sanity rails), "
        "without leaving the current DEX domain"
    )
    artifact["m7a58_hypothesis"] = (
        "bounded coverage enrichment (The Graph subgraph seed) materially raises "
        "live admission and counter-venue coverage for pair-resolved Arbitrum "
        "event tokens within the same-chain DEX domain"
    )
    artifact["m7a518_hypothesis"] = (
        "same-chain low-lag scoring may unlock only if low-lag pair/pool truth "
        "is accumulated across windows and priced from local pool state, without "
        "expanding outside the current DEX domain"
    )
    artifact["m7a522_hypothesis"] = (
        "low-lag same-chain scoring may unlock only after PoolRegistry is actually "
        "instantiated in ws-live mode and used as the primary counter-venue "
        "discovery source before NO_COUNTER_POOL rejection"
    )
    artifact["ws_live_config"] = {
        "ws_blocks_requested": args.ws_blocks,
        "ws_timeout_seconds": args.ws_timeout,
        "max_events": args.max_events,
    }
    artifact["ws_live_stats"] = {
        "blocks_processed": blocks_processed,
        "raw_logs_total": raw_logs_total,
        "normalized_events": len(all_events),
        "events_scored": len(all_results),
        "ws_elapsed_seconds": round(ws_elapsed, 2),
    }
    # M7.A.5.22: Registry session stats
    artifact["registry_session_stats"] = {
        "preload_calls": session_registry.preload_calls,
        "cache_hits": session_registry.cache_hits,
        "pools_discovered": session_registry.pools_discovered,
        "pools_active": session_registry.pools_active,
        "unique_pairs_queried": len(session_registry._queried),
    }
    # M7.A.5.23: Session-persistent low-lag pair tracking
    artifact["session_low_lag_pairs"] = list(_session_low_lag_pairs.values())
    artifact["m7a523_hypothesis"] = (
        "low-lag same-chain scoring may unlock only if low-lag events are "
        "routed into adapter-specific local scoring via registry-direct path "
        "before any coverage-scan rejection"
    )
    artifact["m7a524_hypothesis"] = (
        "the next meaningful target is not better stale scoring, but the first "
        "genuinely low-lag scored event through the registry_direct local-pricing "
        "path; requires minimal pipeline (no size sweep, no remote quoter, "
        "mid-pipeline lag abort) and two-queue priority (low-lag first)"
    )
    # Provider provenance
    artifact["rpc_provider"] = rpc_provider
    artifact["rpc_source"] = rpc_diag.get("source", "unknown")
    artifact["resolved_rpc_host"] = rpc_host
    artifact["ws_provider"] = ws_provider
    artifact["ws_source"] = ws_diag.get("source", "unknown")
    artifact["resolved_ws_host"] = ws_host
    artifact["fallback_used"] = rpc_diag.get("source") == "public_fallback"

    # Live state metrics
    live_results = [r for r in all_results if r.event_block is not None]

    # M7.A.5.25: Detection-time lag helper for ws-live metrics
    def _det_lag(r):
        if r.event_detected_at_block is not None and r.event_block is not None:
            return r.event_detected_at_block - r.event_block
        return 999

    if live_results:
        artifact["live_state_metrics"] = {
            "events_with_block_data": len(live_results),
            "mean_block_lag": round(
                sum(r.block_lag or 0 for r in live_results) / len(live_results), 2
            ),
            # M7.A.5.25: same_block_count uses detection-time lag (not final same_state_class)
            "same_block_count": sum(
                1 for r in live_results if _det_lag(r) == 0
            ),
            "next_block_count": sum(
                1 for r in live_results if _det_lag(r) in (1, 2)
            ),
            "stale_count": sum(
                1 for r in live_results if _det_lag(r) > 2
            ),
            "venues_quoted_max": max(r.counter_venue_count for r in live_results) if live_results else 0,
            "venues_quoted_mean": round(
                sum(r.counter_venue_count for r in live_results) / len(live_results), 2
            ),
            "mean_pipeline_latency_ms": round(
                sum(r.quote_pipeline_latency_ms or 0 for r in live_results) / len(live_results), 2
            ),
            "total_venues_pruned_by_multicall": sum(
                r.venues_pruned_by_multicall for r in live_results
            ),
        }
        # M7.A.5.4: Two-stage pruning metrics
        calls_attempted = [r.quote_calls_attempted for r in live_results if r.quote_calls_attempted is not None]
        calls_after = [r.quote_calls_after_pruning for r in live_results if r.quote_calls_after_pruning is not None]
        if calls_attempted:
            artifact["live_state_metrics"]["mean_quote_calls_attempted"] = round(
                sum(calls_attempted) / len(calls_attempted), 2
            )
        if calls_after:
            artifact["live_state_metrics"]["mean_quote_calls_after_pruning"] = round(
                sum(calls_after) / len(calls_after), 2
            )
        # Aggregate prune_reason_histogram across all events
        agg_prune: Dict[str, int] = {}
        for r in live_results:
            if r.prune_reason_histogram:
                for reason, cnt in r.prune_reason_histogram.items():
                    agg_prune[reason] = agg_prune.get(reason, 0) + cnt
        if agg_prune:
            artifact["live_state_metrics"]["prune_reason_histogram"] = agg_prune
        # Aggregate stage latency
        stage_a_times = [r.pipeline_stage_latency_ms["stage_a_ms"] for r in live_results if r.pipeline_stage_latency_ms]
        stage_b_times = [r.pipeline_stage_latency_ms["stage_b_ms"] for r in live_results if r.pipeline_stage_latency_ms]
        if stage_a_times:
            artifact["live_state_metrics"]["mean_stage_a_ms"] = round(sum(stage_a_times) / len(stage_a_times), 2)
        if stage_b_times:
            artifact["live_state_metrics"]["mean_stage_b_ms"] = round(sum(stage_b_times) / len(stage_b_times), 2)
        live_net = [r.best_live_net_bps for r in live_results if r.best_live_net_bps is not None]
        if live_net:
            artifact["live_state_metrics"]["best_live_net_bps"] = round(max(live_net), 4)
            artifact["live_state_metrics"]["worst_live_net_bps"] = round(min(live_net), 4)
            artifact["live_state_metrics"]["mean_live_net_bps"] = round(
                sum(live_net) / len(live_net), 4
            )
        # Low-lag subset metrics (ws-specific: should have more than polling)
        # M7.A.5.25: Use detection-time lag, not final same_state_class
        low_lag = [
            r for r in live_results
            if _det_lag(r) <= 2
        ]
        low_lag_net = [
            r.best_live_net_bps for r in low_lag
            if r.best_live_net_bps is not None
        ]
        _ll_scored = [
            r for r in low_lag
            if r.reject_reason not in UNSCORED_REJECTS
        ]
        _ll_scored_net = [
            r.best_live_net_bps for r in _ll_scored
            if r.best_live_net_bps is not None
        ]
        artifact["live_state_metrics"]["events_detected_low_lag_ws"] = len(low_lag)
        artifact["live_state_metrics"]["events_scored_low_lag_ws"] = len(_ll_scored)
        artifact["live_state_metrics"]["best_live_net_bps_low_lag_ws"] = (
            round(max(_ll_scored_net), 4) if _ll_scored_net else None
        )
        artifact["live_state_metrics"]["events_detected_low_lag"] = len(low_lag)
        artifact["live_state_metrics"]["events_scored_low_lag"] = len(_ll_scored)
        artifact["live_state_metrics"]["best_live_net_bps_low_lag"] = (
            round(max(_ll_scored_net), 4) if _ll_scored_net else None
        )

        # M7.A.5.14: ws-live low-lag reject decomposition
        _ws_ll_reject_counts: Dict[str, int] = {}
        for r in low_lag:
            if r.reject_reason:
                _ws_ll_reject_counts[r.reject_reason] = (
                    _ws_ll_reject_counts.get(r.reject_reason, 0) + 1
                )
        artifact["live_state_metrics"]["low_lag_reject_histogram_ws"] = _ws_ll_reject_counts
        _ws_ll_n = len(low_lag)
        _ws_ll_pair_resolved = sum(
            1 for r in low_lag
            if r.reject_reason not in (REJECT_TOKEN_PAIR_UNRESOLVED,)
        )
        _ws_ll_pre_econ = sum(
            1 for r in low_lag if r.reject_reason in UNSCORED_REJECTS
        )
        artifact["live_state_metrics"]["low_lag_pair_resolution_rate_ws"] = (
            round(_ws_ll_pair_resolved / _ws_ll_n, 4) if _ws_ll_n else None
        )
        artifact["live_state_metrics"]["low_lag_pre_econ_reject_rate_ws"] = (
            round(_ws_ll_pre_econ / _ws_ll_n, 4) if _ws_ll_n else None
        )

        # M7.A.5.3.1 — Latency budget metrics (relative to chain block_time_ms)
        pipeline_latencies = [
            r.quote_pipeline_latency_ms for r in live_results
            if r.quote_pipeline_latency_ms is not None
        ]
        budget_hits = [
            lat for lat in pipeline_latencies if lat < block_time_ms
        ]
        artifact["live_state_metrics"]["latency_budget_ms"] = block_time_ms
        artifact["live_state_metrics"]["latency_budget_hit_rate"] = (
            round(len(budget_hits) / len(pipeline_latencies), 4)
            if pipeline_latencies else 0.0
        )
        artifact["live_state_metrics"]["sub_block_capable"] = len(budget_hits) > 0

        # M7.A.5.3.1 — Separate low-lag vs stale summaries
        # M7.A.5.25: Use detection-time lag for stale classification
        stale = [
            r for r in live_results
            if _det_lag(r) > 2
        ]
        stale_net = [
            r.best_live_net_bps for r in stale
            if r.best_live_net_bps is not None
        ]
        artifact["ws_low_lag_summary"] = {
            "count": len(low_lag),
            "best_net_bps": round(max(low_lag_net), 4) if low_lag_net else None,
            "worst_net_bps": round(min(low_lag_net), 4) if low_lag_net else None,
            "mean_net_bps": (
                round(sum(low_lag_net) / len(low_lag_net), 4)
                if low_lag_net else None
            ),
            # M7.A.5.25: same/next block counts use detection-time lag
            "same_block_count": sum(
                1 for r in low_lag if _det_lag(r) == 0
            ),
            "next_block_count": sum(
                1 for r in low_lag if _det_lag(r) in (1, 2)
            ),
            "mean_pipeline_latency_ms": (
                round(
                    sum(r.quote_pipeline_latency_ms or 0 for r in low_lag)
                    / len(low_lag), 2
                ) if low_lag else None
            ),
            "viable_count": sum(1 for r in low_lag if r.route_viable),
            "mean_quote_calls_after_pruning": (
                round(
                    sum(r.quote_calls_after_pruning or 0 for r in low_lag)
                    / len(low_lag), 2
                ) if low_lag else None
            ),
        }
        artifact["ws_stale_summary"] = {
            "count": len(stale),
            "best_net_bps": round(max(stale_net), 4) if stale_net else None,
            "worst_net_bps": round(min(stale_net), 4) if stale_net else None,
            "mean_net_bps": (
                round(sum(stale_net) / len(stale_net), 4)
                if stale_net else None
            ),
            "mean_block_lag": (
                round(
                    sum(r.block_lag or 0 for r in stale) / len(stale), 2
                ) if stale else None
            ),
            "mean_pipeline_latency_ms": (
                round(
                    sum(r.quote_pipeline_latency_ms or 0 for r in stale)
                    / len(stale), 2
                ) if stale else None
            ),
            "viable_count": sum(1 for r in stale if r.route_viable),
        }

        # M7.A.5.5: Pair resolution metrics
        resolved_results = [r for r in live_results if r.pair_resolved]
        unresolved_results = [r for r in live_results if not r.pair_resolved]
        resolved_net = [r.best_live_net_bps for r in resolved_results if r.best_live_net_bps is not None]
        unresolved_net = [r.best_live_net_bps for r in unresolved_results if r.best_live_net_bps is not None]
        actual_pairs_seen = list(set(r.actual_pair for r in resolved_results if r.actual_pair))
        size_sources = {}
        for r in live_results:
            src = r.size_source or "unknown"
            size_sources[src] = size_sources.get(src, 0) + 1
        artifact["pair_resolution_metrics"] = {
            "events_pair_resolved": len(resolved_results),
            "events_pair_unresolved": len(unresolved_results),
            "pair_resolution_rate": round(
                len(resolved_results) / len(live_results), 4
            ) if live_results else 0.0,
            "actual_pairs_seen": actual_pairs_seen,
            "resolved_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
            "resolved_mean_net_bps": (
                round(sum(resolved_net) / len(resolved_net), 4)
                if resolved_net else None
            ),
            "size_source_histogram": size_sources,
        }

        # M7.A.5.5: M4 vs M7 economics comparison block
        resolved_with_amounts = [r for r in resolved_results if r.amount_in_wei > 0]
        if resolved_with_amounts:
            mean_amount_wei = sum(r.amount_in_wei for r in resolved_with_amounts) // len(resolved_with_amounts)
            mean_gross_bps = round(
                sum(
                    (r.gross_pnl_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in resolved_with_amounts
                ) / len(resolved_with_amounts), 4
            )
            mean_gas_bps = round(
                sum(
                    (r.gas_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in resolved_with_amounts
                ) / len(resolved_with_amounts), 4
            )
        else:
            mean_amount_wei = 0
            mean_gross_bps = None
            mean_gas_bps = None

        artifact["m4_m7_comparison"] = {
            "m4_best_net_bps": -3.5062,
            "m4_frontier_pair": "WBTC/USDC",
            "m4_size_usd": 50,
            "m4_gas_bps": 2.01,
            "m7_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
            "m7_mean_gross_bps": mean_gross_bps,
            "m7_mean_gas_bps": mean_gas_bps,
            "m7_mean_size_wei": mean_amount_wei,
            "m7_latency_class": "stale" if not low_lag else "low_lag",
            "m7_pair_resolved_count": len(resolved_results),
            "note": "M4 uses pair-specific dynamic sweep; M7 uses event-driven replay with actual-pair resolution",
        }

        # ── M7.A.5.6: Coverage scan metrics ────────────────────────
        admitted_results = [r for r in live_results if r.token_admitted is True]
        not_admitted = [r for r in live_results if r.token_admitted is False]
        coverage_complete_results = [
            r for r in live_results
            if r.coverage_result and r.coverage_result.get("coverage_complete")
        ]
        coverage_blocker_hist: Dict[str, int] = {}
        for r in live_results:
            if r.coverage_result and r.coverage_result.get("coverage_blocker_reason"):
                reason = r.coverage_result["coverage_blocker_reason"]
                coverage_blocker_hist[reason] = coverage_blocker_hist.get(reason, 0) + 1

        artifact["coverage_scan_metrics"] = {
            "events_admitted": len(admitted_results),
            "events_not_admitted": len(not_admitted),
            "events_coverage_complete": len(coverage_complete_results),
            "coverage_blocker_histogram": coverage_blocker_hist,
            "admission_rate": round(
                len(admitted_results) / len(live_results), 4
            ) if live_results else 0.0,
        }

        # ── M7.A.5.6: Size sweep metrics ───────────────────────────
        sweep_events = [r for r in live_results if r.size_sweep_results]
        all_sweep_nets = []
        for r in sweep_events:
            for s in (r.size_sweep_results or []):
                if s.get("net_bps", 0) != 0.0:
                    all_sweep_nets.append(s["net_bps"])
        events_with_sweep_best = [r for r in live_results if r.best_sweep_net_bps is not None]

        artifact["size_sweep_metrics"] = {
            "events_with_sweep": len(sweep_events),
            "sweep_net_bps_all": all_sweep_nets,
            "best_sweep_net_bps": round(max(all_sweep_nets), 4) if all_sweep_nets else None,
            "mean_sweep_net_bps": (
                round(sum(all_sweep_nets) / len(all_sweep_nets), 4)
                if all_sweep_nets else None
            ),
            "events_with_positive_sweep": sum(1 for n in all_sweep_nets if n > 0),
        }

        # ── M7.A.5.6: m4_m7_comparison_v2 block ────────────────────
        v2_resolved_with_amounts = [r for r in resolved_results if r.amount_in_wei > 0]
        v2_gross_bps = None
        v2_gas_bps = None
        v2_fee_bps = None
        v2_size_usd = None
        if v2_resolved_with_amounts:
            v2_gross_bps = round(
                sum(
                    (r.gross_pnl_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in v2_resolved_with_amounts
                ) / len(v2_resolved_with_amounts), 4
            )
            v2_gas_bps = round(
                sum(
                    (r.gas_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in v2_resolved_with_amounts
                ) / len(v2_resolved_with_amounts), 4
            )
            v2_fee_bps = round(
                sum(
                    (r.fee_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in v2_resolved_with_amounts
                ) / len(v2_resolved_with_amounts), 4
            )
            v2_size_usd = round(
                sum(r.amount_in_wei for r in v2_resolved_with_amounts)
                / len(v2_resolved_with_amounts) / 10**18 * 3000, 2
            )

        artifact["m4_m7_comparison_v2"] = {
            "m4_best_net_bps": -3.5062,
            "m4_gross_pre_cost_bps": 36.35,
            "m4_gas_bps": 2.01,
            "m4_fee_bps": 31.0,
            "m4_slippage_bps": 6.85,
            "m4_size_usd": 50,
            "m4_pair": "WBTC/USDC",
            "m7_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
            "m7_gross_pre_cost_bps": v2_gross_bps,
            "m7_gas_bps": v2_gas_bps,
            "m7_fee_bps": v2_fee_bps,
            "m7_slippage_bps": None,
            "m7_size_usd": v2_size_usd,
            "m7_pair_resolved": True,
            "m7_coverage_complete_count": len(coverage_complete_results),
            "m7_latency_class": "stale" if not low_lag else "low_lag",
            "m7_best_sweep_net_bps": (
                round(max(all_sweep_nets), 4) if all_sweep_nets else None
            ),
            "note": (
                "M4 has mature pair-specific dynamic sweep; "
                "M7 now has pair-resolved coverage + bounded event-size evaluation"
            ),
        }

        # ── M7.A.5.6: Granular reject histogram ────────────────────
        granular_hist: Dict[str, int] = {}
        for r in live_results:
            if r.reject_reason:
                granular_hist[r.reject_reason] = granular_hist.get(r.reject_reason, 0) + 1
        artifact["reject_histogram_v2"] = granular_hist

        # ── M7.A.5.7: Enrichment metrics ───────────────────────────
        adm_source_hist: Dict[str, int] = {}
        for r in live_results:
            src = r.admission_source or "unknown"
            adm_source_hist[src] = adm_source_hist.get(src, 0) + 1
        enriched_count = sum(
            1 for r in live_results
            if r.admission_source in (ADMISSION_SUBGRAPH_VERIFIED, ADMISSION_ONCHAIN_ENRICHED)
        )
        artifact["enrichment_metrics"] = {
            "admission_source_histogram": adm_source_hist,
            "events_enriched_onchain": enriched_count,
            "enrichment_admission_rate": round(
                enriched_count / len(live_results), 4
            ) if live_results else 0.0,
            "total_admitted": sum(
                1 for r in live_results if r.token_admitted is True
            ),
            "total_rejected": sum(
                1 for r in live_results if r.token_admitted is False
            ),
        }

        # ── M7.A.5.7: Oracle guard metrics ─────────────────────────
        events_with_oracle = [
            r for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_price_available")
        ]
        guard_triggered = [
            r for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_guard_triggered")
        ]
        artifact["oracle_guard_metrics"] = {
            "events_with_oracle_price": len(events_with_oracle),
            "oracle_coverage_rate": round(
                len(events_with_oracle) / len(live_results), 4
            ) if live_results else 0.0,
            "guard_triggered_count": len(guard_triggered),
            "oracle_feeds_available": list(CHAINLINK_FEEDS_ARBITRUM.keys()),
        }

        # ── M7.A.5.7: Local-sim readiness metrics ──────────────────
        events_with_sim = [
            r for r in live_results
            if r.local_sim_state and r.local_sim_state.get("pools_with_state", 0) > 0
        ]
        total_pools_queried = sum(
            r.local_sim_state.get("pools_queried", 0)
            for r in live_results if r.local_sim_state
        )
        total_pools_with_state = sum(
            r.local_sim_state.get("pools_with_state", 0)
            for r in live_results if r.local_sim_state
        )
        artifact["local_sim_readiness"] = {
            "events_with_pool_state": len(events_with_sim),
            "sim_readiness_rate": round(
                len(events_with_sim) / len(live_results), 4
            ) if live_results else 0.0,
            "total_pools_queried": total_pools_queried,
            "total_pools_with_state": total_pools_with_state,
            "note": "State captured for future local-sim pricing path (sqrtPriceX96 + tick + liquidity)",
        }

        # ── M7.A.5.8: Oracle summary extended ──────────────────────
        oracle_price_avail = sum(
            1 for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_price_available")
        )
        oracle_guard_trig = sum(
            1 for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_guard_triggered")
        )
        oracle_staleness_vals = [
            r.oracle_guard.get("oracle_staleness_seconds", 0)
            for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_staleness_seconds") is not None
        ]
        events_blocked_oracle = sum(
            1 for r in live_results
            if r.reject_reason and "ORACLE" in (r.reject_reason or "").upper()
        )
        artifact["oracle_summary_extended"] = {
            "oracle_price_available_rate": round(
                oracle_price_avail / len(live_results), 4
            ) if live_results else 0.0,
            "oracle_guard_triggered_rate": round(
                oracle_guard_trig / len(live_results), 4
            ) if live_results else 0.0,
            "oracle_staleness_max_seconds": (
                max(oracle_staleness_vals) if oracle_staleness_vals else None
            ),
            "events_blocked_by_oracle": events_blocked_oracle,
        }

        # ── M7.A.5.8: Gas decomposition metrics ────────────────────
        events_with_gas = [
            r for r in live_results
            if r.total_gas_bps is not None
        ]
        artifact["gas_decomposition_metrics"] = {
            "events_with_gas_decomp": len(events_with_gas),
            "mean_l2_gas_bps": round(
                sum(r.l2_gas_bps or 0 for r in events_with_gas)
                / len(events_with_gas), 4
            ) if events_with_gas else None,
            "mean_l1_data_bps": round(
                sum(r.l1_data_bps or 0 for r in events_with_gas)
                / len(events_with_gas), 4
            ) if events_with_gas else None,
            "mean_total_gas_bps": round(
                sum(r.total_gas_bps or 0 for r in events_with_gas)
                / len(events_with_gas), 4
            ) if events_with_gas else None,
        }

        # ── M7.A.5.8: Subgraph seed stats ──────────────────────────
        sg_used_count = sum(
            1 for r in live_results
            if r.subgraph_seed_used is True
        )
        artifact["subgraph_seed_stats"] = {
            "tokens_discovered": subgraph_seed_stats.get("tokens_discovered", 0),
            "tokens_new": subgraph_seed_stats.get("tokens_new", 0),
            "tokens_verified": subgraph_seed_stats.get("tokens_verified", 0),
            "sources_queried": subgraph_seed_stats.get("sources_queried", []),
            "errors": subgraph_seed_stats.get("errors", []),
            "addr_to_symbol_size_before": pre_seed_count,
            "addr_to_symbol_size_after": len(addr_to_symbol),
            "subgraph_seeded_events_admitted": sg_used_count,
            "subgraph_seeded_admission_rate": round(
                sg_used_count / len(live_results), 4
            ) if live_results else 0.0,
        }

        # ── M7.A.5.9: Size normalization metrics ───────────────────
        norm_source_hist: Dict[str, int] = {}
        dec_hist: Dict[str, int] = {}
        valid_size_count = 0
        usd_estimates = []
        for r in live_results:
            ns = r.size_normalization_source or "not_set"
            norm_source_hist[ns] = norm_source_hist.get(ns, 0) + 1
            if r.token_in_decimals is not None:
                dk = str(r.token_in_decimals)
                dec_hist[dk] = dec_hist.get(dk, 0) + 1
            if r.size_valid_for_token is True:
                valid_size_count += 1
            if r.size_usd_estimate is not None:
                usd_estimates.append(r.size_usd_estimate)
        artifact["size_normalization_metrics"] = {
            "normalization_source_histogram": norm_source_hist,
            "token_decimals_histogram": dec_hist,
            "events_with_valid_size": valid_size_count,
            "valid_size_rate": round(
                valid_size_count / len(live_results), 4
            ) if live_results else 0.0,
            "events_with_usd_estimate": len(usd_estimates),
            "mean_size_usd": round(
                sum(usd_estimates) / len(usd_estimates), 2
            ) if usd_estimates else None,
        }
        artifact["m7a59_hypothesis"] = (
            "decimal-aware size normalization eliminates inflated economics "
            "for non-18-decimal tokens (USDC/USDT 6-dec), producing trustworthy "
            "gas_bps and gross_bps across the full token surface"
        )
        artifact["m7a513_hypothesis"] = (
            "orderflow backrun on arbitrum_one may be economically near-breakeven "
            "on the stale subset, but the project still lacks a truthful executable "
            "low-lag scored subset; this split isolates and measures that explicitly"
        )
        artifact["m7a514_hypothesis"] = (
            "low-lag events are already being detected, but they fail before economics "
            "scoring; explicit low-lag reject decomposition may reveal a fixable "
            "same-chain DEX coverage/resolution gap"
        )
        artifact["m7a515_hypothesis"] = (
            "low-lag events are detected on time, but same-block scoring still fails "
            "because token identity and active counter-pool truth are incomplete for "
            "the exact low-lag pairs; targeted low-lag pair/pool truth may unlock the "
            "first executable-scored subset without leaving the same-chain DEX domain"
        )
        artifact["m7a516_hypothesis"] = (
            "low-lag events are timely detected, but same-chain scoring still fails "
            "because low-lag pools split into three structural classes: unsupported "
            "pool ABI (token0/token1/slot0 reverts), no counter-pool, and known-but-"
            "inactive pool; explicit pool-class truth reveals which class dominates "
            "and whether any class is fixable within the same-chain DEX domain"
        )
        artifact["m7a517_hypothesis"] = (
            "low-lag same-chain scoring may unlock only if V2-family pool-state "
            "reading is added (getReserves instead of slot0), but this must be "
            "measured separately from no-counter-pool and inactive-pool classes; "
            "V2 direct resolve bypasses batch_token_info fee() revert and enables "
            "pair resolution for uniswap_v2_like pools"
        )

    # M7.A.5.28: Write canonical rolling M7 artifact (dashboard-facing, no bulky results)
    # M7.A.5.35: Only cold lane writes rolling artifact here.  When hot mode
    # is active (external_registry provided), the outer loop writes a separate
    # hot artifact via _write_hot_artifact() — we must NOT overwrite the cold
    # rolling artifact with hot_skip results.
    if external_registry is None:
        _write_rolling_m7(artifact)

    return artifact


# ---------------------------------------------------------------------------
# M7.A.5.28: Rolling artifact writer
# ---------------------------------------------------------------------------

_ROLLING_M7_PATH = os.path.join("data", "runs", "_rolling", "m7_orderflow_latest.json")

# Keys to extract from the full artifact for the rolling dashboard artifact.
# Excludes bulky debugging arrays (results, low_lag_debug_rows, low_lag_watchlist,
# session_low_lag_pairs) to keep the rolling file small and dashboard-friendly.
_ROLLING_EXCLUDE_KEYS = frozenset({
    "results",
    "low_lag_debug_rows",
    "low_lag_watchlist",
    "session_low_lag_pairs",
})


def _write_rolling_m7(artifact: dict) -> None:
    """Overwrite the canonical rolling M7 artifact for dashboard consumption.

    M7.A.5.29: Anti-bad-overwrite — if the window is empty (events_count == 0),
    do NOT overwrite a previous useful snapshot. Instead, only update the
    m7_loop_context metadata in the existing file (if any).
    """
    try:
        events_count = artifact.get("events_count", 0)
        rolling = {k: v for k, v in artifact.items() if k not in _ROLLING_EXCLUDE_KEYS}

        # M7.A.5.29: Anti-bad-overwrite rule
        if events_count == 0 and os.path.exists(_ROLLING_M7_PATH):
            # Preserve previous snapshot, only update loop context if present
            loop_ctx = artifact.get("m7_loop_context")
            if loop_ctx:
                try:
                    with open(_ROLLING_M7_PATH, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    loop_ctx["window_empty"] = True
                    existing["m7_loop_context"] = loop_ctx
                    existing.setdefault("last_nonempty_timestamp",
                                        existing.get("timestamp"))
                    with open(_ROLLING_M7_PATH, "w", encoding="utf-8") as f:
                        json.dump(existing, f, indent=2, default=str)
                    logger.info(
                        "Rolling M7: empty window — preserved previous snapshot, "
                        "updated loop_context only"
                    )
                except Exception as exc2:
                    logger.warning(
                        "Rolling M7: empty window — failed to update loop_context: %s",
                        str(exc2)[:120],
                    )
            else:
                logger.info(
                    "Rolling M7: empty window (events=0) — skipping overwrite "
                    "to preserve previous useful snapshot"
                )
            return

        # Non-empty window: track last_nonempty_timestamp
        rolling["last_nonempty_timestamp"] = artifact.get(
            "timestamp", rolling.get("timestamp")
        )

        os.makedirs(os.path.dirname(_ROLLING_M7_PATH), exist_ok=True)
        with open(_ROLLING_M7_PATH, "w", encoding="utf-8") as f:
            json.dump(rolling, f, indent=2, default=str)
        logger.info("Rolling M7 artifact written to %s", _ROLLING_M7_PATH)
    except Exception as exc:
        logger.warning("Failed to write rolling M7 artifact: %s", str(exc)[:120])
