#!/usr/bin/env python3
"""
M7.A.5.31 — Continuous M7 orderflow ws-live loop with hot/cold lane split.

Repeatedly runs ws-live replay windows and overwrites the canonical
rolling artifact at data/runs/_rolling/m7_orderflow_latest.json.

This is a standalone runtime service — separate from start.py (M5/M4).
Both services write to _rolling/ and are read by one dashboard_server.

Lane modes:
  --lane cold   (default) Full diagnostic loop: all results, full artifact,
                dashboard-friendly. No budget constraint on artifact building.
  --lane hot    Minimal scoring loop: small max-events, tight block window.
                Prewarms registry from session_low_lag_pairs accumulated across
                iterations. Integrates profit_guard for execution readiness.
                Writes m7_hot_latest.json. Does NOT overwrite cold rolling.

Usage:
    py -3.11 scripts/m7a_orderflow_loop.py [options]
    py -3.11 scripts/m7a_orderflow_loop.py --lane cold --ws-blocks 300 --max-events 30
    py -3.11 scripts/m7a_orderflow_loop.py --lane hot --ws-blocks 20 --max-events 5
    py -3.11 scripts/m7a_orderflow_loop.py --iterations 5 --pause 1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.env import load_root_dotenv
from core.logging import get_logger
from m7.orderflow.mode_ws_live import run_ws_live, _write_rolling_m7
from m7.orderflow.profit_guard import check_profit_guard

logger = get_logger("m7.orderflow.loop")

_HOT_ARTIFACT_PATH = os.path.join("data", "runs", "_rolling", "m7_hot_latest.json")


def parse_args():
    parser = argparse.ArgumentParser(
        description="M7.A.5.31: Continuous M7 orderflow ws-live loop"
    )
    parser.add_argument(
        "--chain", type=str, default="arbitrum_one",
        help="Chain to monitor (default: arbitrum_one)",
    )
    parser.add_argument(
        "--lane", type=str, default="cold", choices=["cold", "hot"],
        help="Lane mode: cold (diagnostic, default) or hot (execution-ready)",
    )
    parser.add_argument(
        "--ws-blocks", type=int, default=None,
        help="Blocks per window (default: 300 cold, 20 hot)",
    )
    parser.add_argument(
        "--ws-timeout", type=int, default=None,
        help="Timeout per window in seconds (default: 360 cold, 30 hot)",
    )
    parser.add_argument(
        "--max-events", type=int, default=None,
        help="Max events to score per window (default: 30 cold, 5 hot)",
    )
    parser.add_argument(
        "--iterations", type=int, default=0,
        help="Number of iterations (0 = infinite, default: 0)",
    )
    parser.add_argument(
        "--pause", type=int, default=None,
        help="Seconds to pause between windows (default: 5 cold, 1 hot)",
    )
    return parser.parse_args()


# Lane-specific defaults
_LANE_DEFAULTS = {
    "cold": {"ws_blocks": 300, "ws_timeout": 360, "max_events": 30, "pause": 5},
    "hot":  {"ws_blocks": 20,  "ws_timeout": 30,  "max_events": 5,  "pause": 1},
}


def _apply_lane_defaults(cli_args):
    """Fill in None args from lane-specific defaults."""
    defaults = _LANE_DEFAULTS[cli_args.lane]
    for k, v in defaults.items():
        if getattr(cli_args, k) is None:
            setattr(cli_args, k, v)


def _build_ws_args(cli_args) -> SimpleNamespace:
    """Build the args namespace that run_ws_live expects."""
    return SimpleNamespace(
        chain=cli_args.chain,
        ws_blocks=cli_args.ws_blocks,
        ws_timeout=cli_args.ws_timeout,
        max_events=cli_args.max_events,
    )


def _prewarm_registry_from_pairs(
    registry, session_pairs: dict, token_addresses: dict,
    dex_configs: dict, rpc_url: str, block_num: int,
) -> int:
    """Prewarm registry using accumulated session_low_lag_pairs.

    Returns number of pairs prewarmed.
    """
    count = 0
    reverse_map = {v.lower(): k for k, v in token_addresses.items() if v}
    for pair_key, info in session_pairs.items():
        if "/" not in pair_key:
            continue
        sym_a, sym_b = pair_key.split("/", 1)
        addr_a = token_addresses.get(sym_a, "")
        addr_b = token_addresses.get(sym_b, "")
        if not addr_a or not addr_b:
            continue
        try:
            registry.preload_pair(addr_a, addr_b, dex_configs, rpc_url, block_num)
            count += 1
        except Exception:
            pass
    return count


def _run_profit_guard_on_results(results: list) -> list:
    """Run profit_guard on all scored results with positive net_bps.

    Returns list of (result_dict, ProfitGuardResult) for candidates that
    pass the guard.
    """
    passed = []
    for r in results:
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)
        if net is None or net <= 0:
            continue
        buy = r.get("best_buy_amount_wei") if isinstance(r, dict) else getattr(r, "best_buy_amount_wei", 0)
        sell = r.get("best_sell_amount_wei") if isinstance(r, dict) else getattr(r, "best_sell_amount_wei", 0)
        size = r.get("amount_in_wei") if isinstance(r, dict) else getattr(r, "amount_in_wei", 0)
        sv = r.get("size_valid_for_token") if isinstance(r, dict) else getattr(r, "size_valid_for_token", None)

        # M7.A.5.31: Skip size_valid=false from profit guard (Step 5)
        if sv is False:
            continue

        if not buy or not sell or not size:
            continue
        pipeline_ms = r.get("quote_pipeline_latency_ms") if isinstance(r, dict) else getattr(r, "quote_pipeline_latency_ms", None)
        guard = check_profit_guard(
            buy_amount_wei=buy, sell_amount_wei=sell, backrun_size_wei=size,
            pipeline_latency_ms=pipeline_ms,
        )
        if guard.passed:
            passed.append((r, guard))
    return passed


def _write_hot_artifact(artifact: dict, iteration: int, guard_results: list = None) -> None:
    """Write minimal hot-lane artifact: best candidate + profit guard status."""
    results = artifact.get("results", [])
    best = None
    for r in results:
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)
        sv = r.get("size_valid_for_token") if isinstance(r, dict) else getattr(r, "size_valid_for_token", None)
        # M7.A.5.31: Skip size_valid=false from hot headline
        if sv is False:
            continue
        if net is not None and net > 0:
            if best is None or net > (best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", 0)):
                best = r

    hot = {
        "lane": "hot",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "loop_iteration": iteration,
        "events_count": artifact.get("events_count", 0),
        "best_net_bps_clean": artifact.get("best_net_bps_clean"),
        "viable_count": artifact.get("viable_count", 0),
        "has_positive": best is not None,
        "profit_guard_passed_count": len(guard_results) if guard_results else 0,
    }
    if best is not None:
        hot["best_candidate"] = {
            "event_id": best.get("event_id") if isinstance(best, dict) else getattr(best, "event_id", None),
            "actual_pair": best.get("actual_pair") if isinstance(best, dict) else getattr(best, "actual_pair", None),
            "net_bps": best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", None),
            "scoring_path": best.get("scoring_path") if isinstance(best, dict) else getattr(best, "scoring_path", None),
            "size_valid": best.get("size_valid_for_token") if isinstance(best, dict) else getattr(best, "size_valid_for_token", None),
        }
    if guard_results:
        # Show best guard-passed candidate
        best_guard = max(guard_results, key=lambda x: x[1].net_bps)
        r_dict, guard = best_guard
        hot["best_guard_passed"] = {
            "event_id": r_dict.get("event_id") if isinstance(r_dict, dict) else getattr(r_dict, "event_id", None),
            "net_bps": guard.net_bps,
            "guard_mode": guard.guard_mode,
            "guard_latency_ms": guard.guard_latency_ms,
            "timeboost_eligible": guard.timeboost_eligible,
        }
        # M7.A.5.31: Execution readiness timing summary
        hot["execution_readiness"] = {
            "guard_checks_total": len(guard_results),
            "mean_guard_latency_ms": round(
                sum(g.guard_latency_ms for _, g in guard_results) / len(guard_results), 2
            ),
            "max_guard_latency_ms": round(
                max(g.guard_latency_ms for _, g in guard_results), 2
            ),
            "timeboost_eligible_count": sum(1 for _, g in guard_results if g.timeboost_eligible),
            "timeboost_budget_ms": 50,
        }

    try:
        os.makedirs(os.path.dirname(_HOT_ARTIFACT_PATH), exist_ok=True)
        with open(_HOT_ARTIFACT_PATH, "w", encoding="utf-8") as f:
            json.dump(hot, f, indent=2, default=str)
        logger.info("Hot lane artifact written to %s", _HOT_ARTIFACT_PATH)
    except Exception as exc:
        logger.warning("Failed to write hot artifact: %s", str(exc)[:120])


def run_loop(cli_args) -> None:
    """Run the continuous ws-live loop."""
    _apply_lane_defaults(cli_args)
    ws_args = _build_ws_args(cli_args)
    iterations = cli_args.iterations
    pause = cli_args.pause
    lane = cli_args.lane
    infinite = iterations == 0

    # M7.A.5.31: Hot lane maintains cross-iteration state
    _accumulated_pairs: dict = {}  # pair_key -> session_low_lag_pairs info
    _hot_registry = None  # lazy-init on first hot iteration

    iteration = 0
    logger.info(
        "M7 %s loop starting: chain=%s ws_blocks=%d timeout=%ds max_events=%d "
        "iterations=%s pause=%ds",
        lane.upper(), cli_args.chain, cli_args.ws_blocks, cli_args.ws_timeout,
        cli_args.max_events, "infinite" if infinite else iterations, pause,
    )

    while infinite or iteration < iterations:
        iteration += 1
        window_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "=== M7 %s loop iteration %d started at %s ===",
            lane.upper(), iteration, window_started_at,
        )

        try:
            # M7.A.5.31: Hot lane prewarms registry from accumulated pairs
            _ext_registry = None
            if lane == "hot":
                if _hot_registry is None:
                    from m7.orderflow.pool_registry import PoolRegistry
                    _hot_registry = PoolRegistry()
                _ext_registry = _hot_registry

                if _accumulated_pairs and iteration > 1:
                    try:
                        from config import load_dexes, get_all_token_addresses
                        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
                        _chain_id = _CHAIN_KEY_TO_ID.get(cli_args.chain.lower())
                        _rpc, _, _ = resolve_rpc_http(
                            chain_id=_chain_id, network=cli_args.chain,
                            env=dict(os.environ),
                        )
                        if _rpc:
                            from web3 import Web3 as _W3
                            _block = _W3(_W3.HTTPProvider(_rpc)).eth.block_number
                            _all_dexes = load_dexes()
                            _dex_cfg = _all_dexes.get(cli_args.chain, {})
                            _token_addr = get_all_token_addresses(cli_args.chain)
                            _pw = _prewarm_registry_from_pairs(
                                _hot_registry, _accumulated_pairs,
                                _token_addr, _dex_cfg, _rpc, _block,
                            )
                            logger.info(
                                "Hot prewarm: %d pairs from %d accumulated",
                                _pw, len(_accumulated_pairs),
                            )
                    except Exception as _pw_exc:
                        logger.debug("Hot prewarm failed: %s", str(_pw_exc)[:120])

            artifact = run_ws_live(ws_args, external_registry=_ext_registry)
            window_ended_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            events_count = artifact.get("events_count", 0)
            window_empty = events_count == 0

            # M7.A.5.31: Accumulate session_low_lag_pairs for next hot prewarm
            if lane == "hot":
                for p in artifact.get("session_low_lag_pairs", []):
                    pk = p.get("pair")
                    if pk:
                        if pk in _accumulated_pairs:
                            _accumulated_pairs[pk]["seen_count"] += p.get("seen_count", 0)
                            _accumulated_pairs[pk]["scored_count"] += p.get("scored_count", 0)
                        else:
                            _accumulated_pairs[pk] = dict(p)

            # Inject loop runtime fields
            artifact["m7_loop_context"] = {
                "lane": lane,
                "loop_iteration": iteration,
                "window_started_at": window_started_at,
                "window_ended_at": window_ended_at,
                "window_empty": window_empty,
            }

            # M7.A.5.31: Run profit guard on hot lane results
            guard_results = None
            if lane == "hot":
                guard_results = _run_profit_guard_on_results(artifact.get("results", []))

            if lane == "cold":
                # Cold lane: full diagnostic rolling artifact
                _write_rolling_m7(artifact)
            else:
                # Hot lane: minimal artifact with profit guard
                _write_hot_artifact(artifact, iteration, guard_results)

            best = artifact.get("best_net_bps_clean")
            viable = artifact.get("viable_count", 0)
            _guard_msg = ""
            if guard_results is not None:
                _guard_msg = f" guard_passed={len(guard_results)}"
            logger.info(
                "M7 %s iteration %d: events=%d viable=%d best_clean=%s empty=%s%s",
                lane.upper(), iteration, events_count, viable, best, window_empty, _guard_msg,
            )

        except KeyboardInterrupt:
            logger.info("M7 loop interrupted by user at iteration %d", iteration)
            break
        except SystemExit as exc:
            logger.error("M7 loop SystemExit at iteration %d: %s", iteration, exc)
            break
        except Exception as exc:
            window_ended_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.error(
                "M7 %s iteration %d failed: %s",
                lane.upper(), iteration, str(exc)[:200],
                exc_info=True,
            )

        if infinite or iteration < iterations:
            logger.info("Pausing %ds before next window...", pause)
            try:
                time.sleep(pause)
            except KeyboardInterrupt:
                logger.info("M7 loop interrupted during pause")
                break

    logger.info("M7 %s loop finished after %d iterations", lane.upper(), iteration)


def main():
    load_root_dotenv()
    cli_args = parse_args()
    run_loop(cli_args)


if __name__ == "__main__":
    main()
