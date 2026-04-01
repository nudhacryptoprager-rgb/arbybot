"""
M7 orderflow CLI: argument parsing and mode orchestration.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from m7.shared.constants import (
    DEFAULT_LIVE_BLOCKS,
    M7A4_CHAIN,
    UNSCORED_REJECTS,
)
from m7.orderflow.events import (
    build_fixture_events,
    fetch_recent_swap_events,
    load_events_from_file,
    normalize_swap_log,
)
from m7.orderflow.pricing import (
    score_backrun_live,
    score_backrun_online,
)
from m7.orderflow.artifacts import (
    build_intent_scout_summary,
    build_intent_surface_assessments,
    build_replay_summary,
    score_backrun_offline,
)
from m7.orderflow.resolve import _build_address_to_symbol
from m7.orderflow.mode_ws_live import run_ws_live

logger = logging.getLogger("m7.orderflow.cli")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="M7.A.5 — Orderflow-driven replay with live block events",
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--offline",
        action="store_true",
        help="Score backrun opportunities from built-in fixture events",
    )
    mode_group.add_argument(
        "--replay",
        type=str,
        metavar="FILE",
        help="Score from imported event samples (JSON)",
    )
    mode_group.add_argument(
        "--online",
        action="store_true",
        help="Score fixture events using live RPC quotes at current block",
    )
    mode_group.add_argument(
        "--live-blocks",
        type=int,
        metavar="N",
        default=None,
        help="M7.A.5: Fetch real Swap events from last N blocks and score with live quotes",
    )
    mode_group.add_argument(
        "--intent-scout",
        action="store_true",
        help="Read-only feasibility assessment of orderflow surfaces",
    )
    mode_group.add_argument(
        "--ws-live",
        action="store_true",
        help="M7.A.5.3: WebSocket-triggered same-block/next-block replay with parallel scoring",
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON path (default: stdout)",
    )
    parser.add_argument(
        "--chain",
        type=str,
        default=M7A4_CHAIN,
        help=f"Chain to analyze (default: {M7A4_CHAIN})",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=20,
        help="Maximum number of live events to score (default: 20, limits RPC calls)",
    )
    parser.add_argument(
        "--ws-blocks",
        type=int,
        default=10,
        help="M7.A.5.3: Number of newHeads to process in ws-live mode (default: 10)",
    )
    parser.add_argument(
        "--ws-timeout",
        type=int,
        default=120,
        help="M7.A.5.3: Timeout in seconds for ws-live subscription (default: 120)",
    )

    return parser.parse_args()



def main():
    # M7.A.5.9: Load .env for reproducible --ws-live runs from clean shell
    from core.env import load_root_dotenv
    load_root_dotenv()

    args = parse_args()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if args.intent_scout:
        logger.info("Running intent/auction surface scout")
        assessments = build_intent_surface_assessments()
        artifact = build_intent_scout_summary(assessments)
        artifact["timestamp"] = ts
    elif args.offline:
        logger.info("Running offline backrun replay with fixture events")
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
    elif args.replay:
        logger.info("Running replay from imported events: %s", args.replay)
        events = load_events_from_file(args.replay)
        results = [score_backrun_offline(e) for e in events]
        for r in results:
            r.event_source = "imported"
        artifact = build_replay_summary(events, results, mode="replay")
    elif args.online:
        logger.info("Running online backrun scoring with live quotes")
        from config import load_dexes, get_all_token_addresses
        from core.rpc_urls import get_rpc_url

        rpc_url = get_rpc_url(args.chain)
        all_dexes = load_dexes()
        dex_configs = all_dexes.get(args.chain, {})
        token_addresses = get_all_token_addresses(args.chain)

        events = build_fixture_events()
        results = [
            score_backrun_online(e, rpc_url, dex_configs, token_addresses)
            for e in events
        ]
        artifact = build_replay_summary(events, results, mode="online")
    elif args.live_blocks is not None:
        # M7.A.5: Live block-event backrun replay
        logger.info(
            "Running M7.A.5 live block-event replay (%d blocks)",
            args.live_blocks,
        )
        import os
        from urllib.parse import urlparse

        from config import load_dexes, get_all_token_addresses
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID

        chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, rpc_provider, rpc_diag = resolve_rpc_http(
            chain_id=chain_id,
            network=args.chain,
            env=dict(os.environ),
        )
        if not rpc_url:
            raise SystemExit(f"No RPC URL found for chain: {args.chain}")
        rpc_host = urlparse(rpc_url).netloc
        logger.info(
            "RPC resolved: provider=%s source=%s host=%s",
            rpc_provider,
            rpc_diag.get("source", "unknown"),
            rpc_host,
            extra={"context": {"rpc_provider": rpc_provider, "rpc_host": rpc_host}},
        )

        all_dexes = load_dexes()
        dex_configs = all_dexes.get(args.chain, {})
        token_addresses = get_all_token_addresses(args.chain)
        addr_to_symbol = _build_address_to_symbol(token_addresses)

        # Fetch real Swap events from chain
        raw_logs, current_block = fetch_recent_swap_events(
            rpc_url=rpc_url,
            blocks_back=args.live_blocks,
        )

        # Normalize logs into OrderflowEvents
        events = []
        for i, log in enumerate(raw_logs):
            ev = normalize_swap_log(
                log=log,
                addr_to_symbol=addr_to_symbol,
                token_addresses=token_addresses,
                dex_configs=dex_configs,
                event_index=i,
            )
            if ev is not None:
                events.append(ev)

        logger.info(
            "Normalized %d events from %d raw logs",
            len(events),
            len(raw_logs),
            extra={"context": {"normalized": len(events), "raw": len(raw_logs)}},
        )

        # Limit events to conserve RPC calls
        if len(events) > args.max_events:
            # Take largest events by estimated_size_usd
            events.sort(key=lambda e: e.estimated_size_usd, reverse=True)
            events = events[:args.max_events]
            logger.info("Truncated to %d largest events", len(events))

        # Score each event with live QuoterV2 quotes
        results = []
        for ev in events:
            r = score_backrun_live(
                event=ev,
                rpc_url=rpc_url,
                dex_configs=dex_configs,
                token_addresses=token_addresses,
                current_block=current_block,
            )
            results.append(r)

        artifact = build_replay_summary(events, results, mode="live_blocks")
        # Add M7.A.5 specific fields
        artifact["m7a5_hypothesis"] = (
            "block_event_backrun on arbitrum_one may produce viable measured edge "
            "when replay uses real block events and post-event live quotes"
        )
        artifact["live_blocks_scanned"] = args.live_blocks
        artifact["raw_logs_count"] = len(raw_logs)
        artifact["normalized_events_count"] = len(events)
        artifact["current_block"] = current_block
        # M7.A.5.2: Provider provenance (machine-readable)
        artifact["rpc_provider"] = rpc_provider
        artifact["rpc_source"] = rpc_diag.get("source", "unknown")
        artifact["resolved_rpc_host"] = rpc_host
        artifact["fallback_used"] = rpc_diag.get("source") == "public_fallback"
        # Live replay state metrics
        live_results = [r for r in results if r.event_block is not None]
        if live_results:
            artifact["live_state_metrics"] = {
                "events_with_block_data": len(live_results),
                "mean_block_lag": round(
                    sum(r.block_lag or 0 for r in live_results) / len(live_results), 2
                ),
                "same_block_count": sum(
                    1 for r in live_results if r.same_state_class == "same_block"
                ),
                "next_block_count": sum(
                    1 for r in live_results if r.same_state_class == "next_block"
                ),
                "stale_count": sum(
                    1 for r in live_results if r.same_state_class == "stale"
                ),
                "venues_quoted_max": max(r.counter_venue_count for r in live_results),
                "venues_quoted_mean": round(
                    sum(r.counter_venue_count for r in live_results) / len(live_results), 2
                ),
            }
            live_net = [r.best_live_net_bps for r in live_results if r.best_live_net_bps is not None]
            if live_net:
                artifact["live_state_metrics"]["best_live_net_bps"] = round(max(live_net), 4)
                artifact["live_state_metrics"]["worst_live_net_bps"] = round(min(live_net), 4)
                artifact["live_state_metrics"]["mean_live_net_bps"] = round(
                    sum(live_net) / len(live_net), 4
                )
            # M7.A.5.2: Low-lag subset metrics (same_block + next_block only)
            low_lag = [
                r for r in live_results
                if r.same_state_class in ("same_block", "next_block")
            ]
            low_lag_net = [
                r.best_live_net_bps for r in low_lag
                if r.best_live_net_bps is not None
            ]
            # M7.A.5.13: Fix live-blocks low-lag to match scored-only contract
            _ll_scored_lb = [
                r for r in low_lag
                if r.reject_reason not in UNSCORED_REJECTS
            ]
            _ll_scored_lb_net = [
                r.best_live_net_bps for r in _ll_scored_lb
                if r.best_live_net_bps is not None
            ]
            artifact["live_state_metrics"]["events_detected_low_lag"] = len(low_lag)
            artifact["live_state_metrics"]["events_scored_low_lag"] = len(_ll_scored_lb)
            artifact["live_state_metrics"]["best_live_net_bps_low_lag"] = (
                round(max(_ll_scored_lb_net), 4) if _ll_scored_lb_net else None
            )
    elif args.ws_live:
        artifact = run_ws_live(args)
    else:
        parser_err = "No mode specified"
        raise SystemExit(parser_err)

    output_json = json.dumps(artifact, indent=2, default=str)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        logger.info("Artifact written to %s", out_path)
    else:
        print(output_json)

    # Summary log
    if "results_count" in artifact:
        logger.info(
            "Replay complete: %d events, %d viable, best_net=%.4f bps",
            artifact["events_count"],
            artifact["viable_count"],
            artifact.get("best_net_bps") or 0.0,
            extra={"context": {
                "mode": artifact.get("mode"),
                "viable": artifact["viable_count"],
                "best_net_bps": artifact.get("best_net_bps"),
            }},
        )
    else:
        logger.info(
            "Scout complete: %d surfaces assessed, best_near_term=%s",
            artifact.get("surfaces_assessed", 0),
            artifact.get("best_near_term", "none"),
        )


if __name__ == "__main__":
    main()
