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
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.env import load_root_dotenv
from core.logging import get_logger
from m7.orderflow.mode_ws_live import run_ws_live, _write_rolling_m7, _set_rolling_m7_profile
from m7.orderflow.profit_guard import check_profit_guard
from m7.orderflow.scoring_parallel import score_backrun_fast
from m7.shared.constants import (
    HOT_WATCHLIST_PAIRS,
    PROMOTED_CANDIDATE_MAX_PAIRS,
    PROMOTED_MAX_PAIRS,
    PROMOTED_MIN_COLD_APPEARANCES,
    PROMOTED_MIN_NET_BPS,
    get_prewarm_pairs,
)

# ---------------------------------------------------------------------------
# E1.12.2: Import from extracted modules (canonical locations)
# ---------------------------------------------------------------------------
from m7.orderflow.runtime_io import (
    _rolling_path,
    _init_artifact_paths as _init_artifact_paths_impl,
    _atomic_json_write,
    _write_promoted_pairs,
    _read_promoted_pairs,
    _read_discovery_scoreboard,
    _update_discovery_scoreboard,
    _write_discovery_scoreboard,
    _SESSION_ID as _SESSION_ID_IMPORTED,
)
from m7.orderflow.runtime_io import (
    _HOT_ARTIFACT_PATH as _HOT_ARTIFACT_PATH_DEFAULT,
    _PROMOTED_PAIRS_PATH as _PROMOTED_PAIRS_PATH_DEFAULT,
    _COLD_HOT_BRIDGE_PATH as _COLD_HOT_BRIDGE_PATH_DEFAULT,
    _HOT_INTENTS_PATH as _HOT_INTENTS_PATH_DEFAULT,
    _HOT_ROLLUP_PATH as _HOT_ROLLUP_PATH_DEFAULT,
    _DISCOVERY_SCOREBOARD_PATH as _DISCOVERY_SCOREBOARD_PATH_DEFAULT,
)
from m7.orderflow.bridge_runtime import (
    _write_cold_hot_bridge,
    _read_cold_hot_bridge,
    _populate_pool_token_cache_from_bridge,
    _prewarm_registry_from_bridge,
    _prewarm_registry_from_pairs,
    _promote_pairs_from_cold,
)
from m7.orderflow.execution_gate import (
    run_execution_gate,
    ExecutionGateResult,
    _run_profit_guard_on_results,
)

logger = get_logger("m7.orderflow.loop")

# ---------------------------------------------------------------------------
# E1.12.2: Module-level path constants — delegated to runtime_io.
# These remain as module-level names for backward compatibility with tests
# that import them from scripts.m7a_orderflow_loop.
# ---------------------------------------------------------------------------
import m7.orderflow.runtime_io as _rio

_HOT_ARTIFACT_PATH = _HOT_ARTIFACT_PATH_DEFAULT
_PROMOTED_PAIRS_PATH = _PROMOTED_PAIRS_PATH_DEFAULT
_COLD_HOT_BRIDGE_PATH = _COLD_HOT_BRIDGE_PATH_DEFAULT
_HOT_INTENTS_PATH = _HOT_INTENTS_PATH_DEFAULT
_HOT_ROLLUP_PATH = _HOT_ROLLUP_PATH_DEFAULT
_DISCOVERY_SCOREBOARD_PATH = _DISCOVERY_SCOREBOARD_PATH_DEFAULT


def _init_artifact_paths(profile: str) -> None:
    """Re-bind module-level artifact paths for the given profile.

    E1.12.2: Delegates to runtime_io._init_artifact_paths and syncs
    local module-level names for backward compat.
    """
    global _HOT_ARTIFACT_PATH, _PROMOTED_PAIRS_PATH, _COLD_HOT_BRIDGE_PATH
    global _HOT_INTENTS_PATH, _HOT_ROLLUP_PATH, _DISCOVERY_SCOREBOARD_PATH

    _init_artifact_paths_impl(profile)

    _HOT_ARTIFACT_PATH = _rio._HOT_ARTIFACT_PATH
    _PROMOTED_PAIRS_PATH = _rio._PROMOTED_PAIRS_PATH
    _COLD_HOT_BRIDGE_PATH = _rio._COLD_HOT_BRIDGE_PATH
    _HOT_INTENTS_PATH = _rio._HOT_INTENTS_PATH
    _HOT_ROLLUP_PATH = _rio._HOT_ROLLUP_PATH
    _DISCOVERY_SCOREBOARD_PATH = _rio._DISCOVERY_SCOREBOARD_PATH


# M7.A.5.47k: Session ID — unique per process lifetime
import uuid as _uuid
_SESSION_ID = _SESSION_ID_IMPORTED


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
    parser.add_argument(
        "--profile", type=str, default="production",
        choices=["production", "discovery"],
        help="Pair profile: production (narrow, default) or discovery (wider contour)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# E1.12.2 Phase 2: Hot artifact writers extracted to hot_runtime_artifacts.py
# Backward-compat re-exports for tests that import from this module.
# ---------------------------------------------------------------------------
from m7.orderflow.hot_runtime_artifacts import (  # noqa: F401
    _compute_headline_level,
    _write_hot_heartbeat_on_error,
    _write_hot_artifact,
    _write_hot_intents,
    _update_hot_rollup,
)


# ---------------------------------------------------------------------------
# E1.12.2 Phase 2: Loop runner extracted to loop_runner.py
# Backward-compat re-exports for tests and external callers.
# ---------------------------------------------------------------------------
from m7.orderflow.loop_runner import (  # noqa: F401
    LoopState,
    _apply_lane_defaults,
    _build_ws_args,
    _LANE_DEFAULTS,
    run_loop,
)

def main():
    load_root_dotenv()
    cli_args = parse_args()
    run_loop(cli_args)


if __name__ == "__main__":
    main()
