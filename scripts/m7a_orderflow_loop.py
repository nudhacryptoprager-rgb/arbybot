#!/usr/bin/env python3
"""
M7.A.5.30 — Continuous M7 orderflow ws-live loop with hot/cold lane split.

Repeatedly runs ws-live replay windows and overwrites the canonical
rolling artifact at data/runs/_rolling/m7_orderflow_latest.json.

This is a standalone runtime service — separate from start.py (M5/M4).
Both services write to _rolling/ and are read by one dashboard_server.

Lane modes:
  --lane cold   (default) Full diagnostic loop: all results, full artifact,
                dashboard-friendly. No budget constraint on artifact building.
  --lane hot    Minimal scoring loop: small max-events, tight block window,
                no bulky artifact append. Writes m7_hot_latest.json with only
                the top candidate (if any). Does NOT overwrite cold rolling.

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

logger = get_logger("m7.orderflow.loop")

_HOT_ARTIFACT_PATH = os.path.join("data", "runs", "_rolling", "m7_hot_latest.json")


def parse_args():
    parser = argparse.ArgumentParser(
        description="M7.A.5.30: Continuous M7 orderflow ws-live loop"
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


def _write_hot_artifact(artifact: dict, iteration: int) -> None:
    """Write minimal hot-lane artifact: only the best candidate, if positive."""
    results = artifact.get("results", [])
    best = None
    for r in results:
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)
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
    }
    if best is not None:
        hot["best_candidate"] = {
            "event_id": best.get("event_id") if isinstance(best, dict) else getattr(best, "event_id", None),
            "actual_pair": best.get("actual_pair") if isinstance(best, dict) else getattr(best, "actual_pair", None),
            "net_bps": best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", None),
            "scoring_path": best.get("scoring_path") if isinstance(best, dict) else getattr(best, "scoring_path", None),
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
            artifact = run_ws_live(ws_args)
            window_ended_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            events_count = artifact.get("events_count", 0)
            window_empty = events_count == 0

            # Inject loop runtime fields
            artifact["m7_loop_context"] = {
                "lane": lane,
                "loop_iteration": iteration,
                "window_started_at": window_started_at,
                "window_ended_at": window_ended_at,
                "window_empty": window_empty,
            }

            if lane == "cold":
                # Cold lane: full diagnostic rolling artifact
                _write_rolling_m7(artifact)
            else:
                # Hot lane: minimal artifact, doesn't overwrite cold rolling
                _write_hot_artifact(artifact, iteration)

            best = artifact.get("best_net_bps_clean")
            viable = artifact.get("viable_count", 0)
            logger.info(
                "M7 %s iteration %d: events=%d viable=%d best_clean=%s empty=%s",
                lane.upper(), iteration, events_count, viable, best, window_empty,
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
