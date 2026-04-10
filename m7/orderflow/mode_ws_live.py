"""
M7 orderflow ws-live mode handler.

Extracted from cli.py to keep the CLI dispatcher under 1000 lines.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Set
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
    get_chainlink_feeds,
    get_prewarm_pairs,
)
from m7.orderflow.artifacts import build_replay_summary
from m7.orderflow.coverage import seed_tokens_from_subgraph
from m7.orderflow.events import normalize_swap_log
from m7.orderflow.pool_registry import PoolRegistry
from m7.orderflow.resolve import _build_address_to_symbol, batch_pre_resolve_pools
from m7.orderflow.scoring_parallel import score_backrun_live_parallel, score_backrun_fast
from m7.orderflow.contracts import BackrunResult

logger = logging.getLogger("m7.orderflow.cli")


def run_ws_live(
    args,
    *,
    external_registry=None,
    warm_registry=None,
    bridge_pool_addresses: Optional[Set[str]] = None,
    bridge_hit_deficit: bool = False,
    bridge_hit_deficit_severe: bool = False,
) -> dict:
    """Execute the ws-live WebSocket replay mode and return the artifact dict.

    Parameters
    ----------
    args : namespace with ws_blocks, ws_timeout, max_events, chain.
    external_registry : optional pre-warmed PoolRegistry.  When provided,
        session prewarm is skipped and this registry is used directly.
        The caller retains ownership and can accumulate state across calls.
        **Triggers hot mode** (score_backrun_fast for all events).
    warm_registry : optional pre-warmed PoolRegistry for cold mode.
        When provided, used as session_registry (skips fresh PoolRegistry
        creation + prewarm), but does NOT trigger hot mode. Cold lane
        still uses score_backrun_live_parallel, but registry_preload_ms
        drops to near-zero for already-cached pairs (M7.A.5.37).
    bridge_pool_addresses : optional set of checksummed/lowered pool addresses
        from cold→hot bridge. When provided in hot mode, eth_getLogs uses a
        targeted address filter so only events from bridge pools are fetched.
    bridge_hit_deficit : if True, the caller (loop) has detected that events
        exist but bridge_pool_hit_total == 0. Broad fallback interval is
        set to 2 (50% broad) to maximize coverage.
    bridge_hit_deficit_severe : if True, deficit is sustained (3+ windows
        with events but zero hits). Interval drops to 1 (100% broad).
        M7.A.5.47g: Escalated broad fallback for persistent conversion failure.
        M7.A.5.47: Focused event intake for bridge pools.
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
    # M7.E1: On Base, prefer Flashblocks WS for sub-block (~200ms) event delivery.
    # Flashblocks endpoint supports standard eth_subscribe newHeads but delivers
    # at sub-block granularity, giving a structural latency advantage over 2s blocks.
    _flashblocks_ws = None
    if args.chain == "base":
        from config import load_chains as _load_chains_fb
        from chains.flashblocks import get_flashblocks_ws_url
        _base_cfg = _load_chains_fb().get("base", {})
        _flashblocks_ws = get_flashblocks_ws_url(
            _base_cfg.get("flashblocks_ws_endpoint")
        )

    ws_url = None
    ws_provider = None
    ws_diag = {}
    if _flashblocks_ws:
        ws_url = _flashblocks_ws
        ws_provider = "flashblocks"
        ws_diag = {"source": "flashblocks_sub_block", "flashblocks": True}
        logger.info(
            "M7.E1: Using Flashblocks WS for Base sub-block newHeads: %s",
            urlparse(ws_url).netloc,
        )

    # Verify Flashblocks WS connectivity; fall back to standard WS if unreachable
    if ws_url and ws_provider == "flashblocks":
        try:
            import websocket as _ws_test
            _test_conn = _ws_test.create_connection(ws_url, timeout=5)
            _test_conn.close()
        except Exception as _fb_err:
            logger.warning(
                "M7.E1: Flashblocks WS unreachable (%s), falling back to standard WS",
                str(_fb_err)[:80],
            )
            ws_url = None  # trigger standard resolution below

    if not ws_url:
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
    # Ensure ws_diag is always a dict for downstream .get() calls
    if not isinstance(ws_diag, dict):
        ws_diag = {"source": str(ws_diag)}
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
    # M7.A.5.37: Accept warm_registry for cold mode (persistent, no hot trigger)
    _prewarm_count = 0
    if external_registry is not None:
        session_registry = external_registry
        _prewarm_count = -1  # signal: prewarm handled by caller
    elif warm_registry is not None:
        session_registry = warm_registry
        _prewarm_count = -2  # signal: warm registry provided, cold mode
    else:
        session_registry = PoolRegistry()

    # M7.A.5.24: Session prewarm — preload high-frequency pairs from known addresses
    # M7.E1: Chain-aware prewarm pairs
    # M7.E1.9: Profile-aware — discovery profile uses wider contour
    _profile = getattr(args, "profile", "production")
    _prewarm_pairs = get_prewarm_pairs(args.chain, _profile)
    if _prewarm_count not in (-1, -2):
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
        logger.info("Session prewarm skipped: %s registry provided",
                     "external" if _prewarm_count == -1 else "warm")

    # M7.A.5.8: Subgraph-backed bounded coverage seed
    # M7.A.5.47: Skip in hot mode — subgraph is currently 403 and hot lane
    # uses bridge pool_token_transport for token discovery, not subgraph.
    pre_seed_count = len(addr_to_symbol)
    subgraph_seed_stats = {"tokens_discovered": 0, "tokens_new": 0,
                           "tokens_verified": 0, "sources_queried": [], "errors": []}
    subgraph_seeded_addrs: set = set()
    _hot_mode_skip_subgraph = external_registry is not None
    if _hot_mode_skip_subgraph:
        logger.debug("Subgraph seed skipped: hot mode uses bridge for token discovery")
    else:
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
    # M7.A.5.47: Hybrid intake diagnostics
    _broad_blocks = 0       # blocks scanned with broad (no address filter)
    _focused_blocks = 0     # blocks scanned with focused (address filter)
    _broad_logs = 0         # raw logs from broad blocks
    _focused_logs = 0       # raw logs from focused blocks
    # M7.A.5.47c: Track pool addresses seen in hot events (for bridge miss diagnosis)
    _hot_event_pool_counts: Dict[str, int] = {}  # pool_address_lower -> count
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

        # M7.A.5.39: Reuse single Web3 instance for all blocks (was per-block)
        from web3 import Web3 as _W3_loop
        _w3_loop = _W3_loop(_W3_loop.HTTPProvider(rpc_url))

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
            # M7.A.5.47: Hybrid hot intake — focused + periodic broad fallback.
            # Focused: address filter for bridge pools (high hit rate when active).
            # Broad: every _BROAD_FALLBACK_INTERVAL blocks, scan ALL swaps.
            #   This catches events the focused filter misses and provides
            #   diagnostics (events_at_non_bridge_pools vs no_events_at_all).
            _hot_mode_active = external_registry is not None
            # M7.A.5.47e: Adaptive broad fallback — controlled by caller's
            # bridge_hit_deficit flag (from rollup: events>0 but hits=0).
            # Within-window: also go broad early if we see broad logs but
            # no focused logs (intra-iteration learning).
            _intra_window_deficit = (
                _broad_logs > 0
                and _hot_mode_active
                and bridge_pool_addresses
                and _focused_logs == 0
            )
            _BROAD_FALLBACK_INTERVAL = (
                1 if bridge_hit_deficit_severe
                else 2 if (bridge_hit_deficit or _intra_window_deficit)
                else 3
            )
            _is_broad_block = (blocks_processed % _BROAD_FALLBACK_INTERVAL) == 0
            try:
                _log_filter: dict = {
                    "fromBlock": detected_block,
                    "toBlock": detected_block,
                    "topics": [SWAP_EVENT_TOPIC],
                }
                if _hot_mode_active and bridge_pool_addresses and not _is_broad_block:
                    # Focused: only bridge pool addresses (up to cap)
                    # M7.A.5.47d: Adaptive cap — use all bridge addresses
                    # (already capped at 50-100 by bridge ranking in loop.py)
                    _addr_list = list(bridge_pool_addresses)
                    _log_filter["address"] = _addr_list
                # else: broad scan — no address filter
                logs = _w3_loop.eth.get_logs(_log_filter)
            except Exception as exc:
                logger.debug(
                    "Failed to fetch logs for block %d: %s",
                    detected_block,
                    str(exc)[:100],
                )
                continue

            raw_logs_total += len(logs)
            # M7.A.5.47: Track broad vs focused diagnostics
            if _is_broad_block or not (_hot_mode_active and bridge_pool_addresses):
                _broad_blocks += 1
                _broad_logs += len(logs)
            else:
                _focused_blocks += 1
                _focused_logs += len(logs)
            if not logs:
                continue

            # M7.A.5.47c: Track pool addresses from raw logs (before normalization)
            if _hot_mode_active:
                for _lg in logs:
                    _lg_addr = (_lg.get("address") or "").lower()
                    if _lg_addr:
                        _hot_event_pool_counts[_lg_addr] = _hot_event_pool_counts.get(_lg_addr, 0) + 1

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

            # M7.A.5.40: Cold-lane batch pre-resolve + pre-enrich + pre-registry.
            # Moves per-event RPC calls (resolve_ms, enrichment_ms, registry_preload_ms)
            # into a single batch pass before scoring. Individual scoring calls then
            # hit module-level caches for near-zero latency.
            _hot_mode = external_registry is not None
            if not _hot_mode and events_to_score:
                _pre_pool_addrs = list(set(
                    ev.pool_address for ev in events_to_score
                    if ev.pool_address
                ))
                if _pre_pool_addrs:
                    try:
                        _pre_resolved = batch_pre_resolve_pools(
                            _pre_pool_addrs, rpc_url, detected_block, addr_to_symbol,
                        )
                        # Batch-preload discovered token pairs into registry
                        _pre_pairs_done: set = set()
                        for _pa, _pinfo in _pre_resolved.items():
                            _t0 = _pinfo["token0"]
                            _t1 = _pinfo["token1"]
                            _ppk = f"{min(_t0.lower(), _t1.lower())}/{max(_t0.lower(), _t1.lower())}"
                            if _ppk not in _pre_pairs_done:
                                _pre_pairs_done.add(_ppk)
                                try:
                                    session_registry.preload_pair(
                                        _t0, _t1, dex_configs, rpc_url, detected_block,
                                    )
                                except Exception:
                                    pass
                    except Exception as _pre_exc:
                        logger.debug("Cold pre-resolve batch failed: %s", str(_pre_exc)[:100])

            # Score with parallel pipeline
            current_block = detected_block
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
                        chain=args.chain,  # M7.E1.6: chain-aware gas floor
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
    # M7.A.5.46: compact=True skips full results serialization (operational path).
    # Raw BackrunResult objects are carried separately for hot lane downstream.
    artifact = build_replay_summary(all_events, all_results, mode="ws_live", compact=True, chain=args.chain)
    artifact["_raw_results"] = all_results
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
        # M7.A.5.47: Hybrid intake diagnostics
        "broad_blocks": _broad_blocks,
        "focused_blocks": _focused_blocks,
        "broad_logs": _broad_logs,
        "focused_logs": _focused_logs,
        # M7.A.5.47c: Pool addresses seen in hot events (top 20 by count)
        "hot_event_pool_histogram": sorted(
            [{"pool": pa, "count": ct} for pa, ct in _hot_event_pool_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )[:20],
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
        stage_a_times = [r.pipeline_stage_latency_ms.get("stage_a_ms") for r in live_results if r.pipeline_stage_latency_ms and "stage_a_ms" in r.pipeline_stage_latency_ms]
        stage_b_times = [r.pipeline_stage_latency_ms.get("stage_b_ms") for r in live_results if r.pipeline_stage_latency_ms and "stage_b_ms" in r.pipeline_stage_latency_ms]
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
            "oracle_feeds_available": list(get_chainlink_feeds(args.chain).keys()),
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
        # M7.A.5.46: Legacy hypothesis strings removed from runtime path.
        # Historical context preserved in docs/status/Status_M7.md only.

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


def _set_rolling_m7_profile(profile: str) -> None:
    """M7.E1.9.1: Redirect the cold lane rolling path for discovery profile."""
    global _ROLLING_M7_PATH
    name = "m7_orderflow_latest.json"
    if profile == "discovery":
        name = "m7_orderflow_latest_discovery.json"
    _ROLLING_M7_PATH = os.path.join("data", "runs", "_rolling", name)

# Keys to exclude from the rolling dashboard artifact.
# M7.A.5.46: Legacy hypothesis blocks are no longer created in runtime path.
# Only _raw_results and heavy debug arrays need exclusion.
_ROLLING_EXCLUDE_KEYS = frozenset({
    "results",
    "low_lag_debug_rows",
    "low_lag_watchlist",
    "session_low_lag_pairs",
    "_raw_results",
})


def _write_rolling_m7(artifact: dict) -> None:
    """Overwrite the canonical rolling M7 artifact for dashboard consumption.

    M7.A.5.29: Anti-bad-overwrite — if the window is empty (events_count == 0),
    do NOT overwrite a previous useful snapshot. Instead, only update the
    m7_loop_context metadata in the existing file (if any).

    M7.E1.6.1: On empty-window preserve, stamp current_window_timestamp and
    snapshot_preserved=true so reviewers can distinguish "fresh runtime with
    empty window preserving old snapshot" from "stale artifact not running".
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
                    # M7.E1.6.1: Heartbeat — stamp fresh timestamps even on
                    # empty windows so reviewer sees the runtime is alive.
                    _now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    existing["current_window_timestamp"] = _now
                    existing["snapshot_preserved"] = True
                    # Keep snapshot_run_timestamp as the original scoring timestamp
                    existing.setdefault("snapshot_run_timestamp",
                                        existing.get("run_context", {}).get("run_timestamp"))
                    with open(_ROLLING_M7_PATH, "w", encoding="utf-8") as f:
                        json.dump(existing, f, indent=2, default=str)
                    logger.info(
                        "Rolling M7: empty window — preserved previous snapshot, "
                        "updated loop_context + heartbeat at %s", _now,
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
        # M7.E1.6.1: On non-empty write, clear preserved-snapshot flags
        rolling["current_window_timestamp"] = artifact.get(
            "timestamp", rolling.get("timestamp")
        )
        rolling["snapshot_preserved"] = False
        rolling["snapshot_run_timestamp"] = artifact.get(
            "run_context", {}
        ).get("run_timestamp", rolling.get("timestamp"))

        os.makedirs(os.path.dirname(_ROLLING_M7_PATH), exist_ok=True)
        with open(_ROLLING_M7_PATH, "w", encoding="utf-8") as f:
            json.dump(rolling, f, indent=2, default=str)
        logger.info("Rolling M7 artifact written to %s", _ROLLING_M7_PATH)
    except Exception as exc:
        logger.warning("Failed to write rolling M7 artifact: %s", str(exc)[:120])
