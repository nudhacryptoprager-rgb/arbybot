"""
E1.12.2 — Runtime I/O primitives for M7 rolling artifacts.

Extracted from scripts/m7a_orderflow_loop.py to enable modular
development of execution stages without touching the monolithic loop.

Provides:
  - _rolling_path / _init_artifact_paths: profile-aware path routing
  - _atomic_json_write: crash-safe JSON persistence
  - Promoted-pairs and discovery-scoreboard read/write
  - Module-level path constants (_HOT_ARTIFACT_PATH, etc.)
  - _SESSION_ID: per-process session identifier
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid as _uuid
from datetime import datetime, timezone

from core.logging import get_logger

logger = get_logger("m7.orderflow.runtime_io")


# ---------------------------------------------------------------------------
# M7.E1.9: Profile-aware artifact paths
# ---------------------------------------------------------------------------

def _rolling_path(name: str, profile: str = "production") -> str:
    """Build rolling artifact path, inserting _discovery suffix when needed."""
    if profile == "discovery":
        base, ext = os.path.splitext(name)
        name = f"{base}_discovery{ext}"
    return os.path.join("data", "runs", "_rolling", name)


_HOT_ARTIFACT_PATH = _rolling_path("m7_hot_latest.json")
_PROMOTED_PAIRS_PATH = _rolling_path("m7_promoted_pairs.json")
_COLD_HOT_BRIDGE_PATH = _rolling_path("m7_cold_hot_bridge.json")
_HOT_INTENTS_PATH = _rolling_path("m7_hot_intents_latest.json")
_HOT_ROLLUP_PATH = _rolling_path("m7_hot_rollup_latest.json")
_DISCOVERY_SCOREBOARD_PATH = _rolling_path("m7_discovery_scoreboard.json")


def _init_artifact_paths(profile: str) -> None:
    """Re-bind module-level artifact paths for the given profile.

    M7.E1.9: Discovery profile writes to separate files (e.g.
    m7_hot_latest_discovery.json) so parallel runs don't contaminate
    production evidence.
    """
    global _HOT_ARTIFACT_PATH, _PROMOTED_PAIRS_PATH, _COLD_HOT_BRIDGE_PATH
    global _HOT_INTENTS_PATH, _HOT_ROLLUP_PATH, _DISCOVERY_SCOREBOARD_PATH

    _HOT_ARTIFACT_PATH = _rolling_path("m7_hot_latest.json", profile)
    _PROMOTED_PAIRS_PATH = _rolling_path("m7_promoted_pairs.json", profile)
    _COLD_HOT_BRIDGE_PATH = _rolling_path("m7_cold_hot_bridge.json", profile)
    _HOT_INTENTS_PATH = _rolling_path("m7_hot_intents_latest.json", profile)
    _HOT_ROLLUP_PATH = _rolling_path("m7_hot_rollup_latest.json", profile)
    _DISCOVERY_SCOREBOARD_PATH = _rolling_path("m7_discovery_scoreboard.json", profile)
    # M7.E1.9.1: Also redirect the cold lane rolling path in mode_ws_live
    from m7.orderflow.mode_ws_live import _set_rolling_m7_profile
    _set_rolling_m7_profile(profile)


# M7.A.5.47k: Session ID — unique per process lifetime
_SESSION_ID = str(_uuid.uuid4())[:8]


def _atomic_json_write(path: str, data: dict, **kwargs) -> None:
    """Write *data* as JSON to *path* atomically (tmp -> os.replace).

    M7.A.5.47e: Prevents cross-process readers from seeing truncated JSON.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=os.path.dirname(path), suffix=".tmp", prefix=".arby_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **kwargs)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Promoted pairs (cross-lane cold -> hot)
# ---------------------------------------------------------------------------

def _write_promoted_pairs(promoted: dict) -> None:
    """Write promoted pairs to rolling artifact for cross-lane communication."""
    try:
        payload = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "candidate": promoted.get("candidate", []),
            "execution": promoted.get("execution", []),
        }
        _atomic_json_write(_PROMOTED_PAIRS_PATH, payload, indent=2)
    except Exception as exc:
        logger.debug("Failed to write promoted pairs: %s", str(exc)[:80])


def _read_promoted_pairs() -> dict:
    """Read promoted pairs written by cold lane. Returns empty dict on error."""
    try:
        if os.path.exists(_PROMOTED_PAIRS_PATH):
            with open(_PROMOTED_PAIRS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "candidate": data.get("candidate", []),
                "execution": data.get("execution", []),
            }
    except Exception as exc:
        logger.debug("Failed to read promoted pairs: %s", str(exc)[:80])
    return {"candidate": [], "execution": []}


# ---------------------------------------------------------------------------
# M7.E1.9: Discovery family repeatability scoreboard
# ---------------------------------------------------------------------------

def _read_discovery_scoreboard() -> dict:
    """Read the discovery scoreboard from rolling artifact."""
    try:
        if os.path.exists(_DISCOVERY_SCOREBOARD_PATH):
            with open(_DISCOVERY_SCOREBOARD_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        logger.debug("Failed to read discovery scoreboard: %s", str(exc)[:80])
    return {"families": {}, "updated_at": None, "profile": "discovery"}


def _update_discovery_scoreboard(
    scoreboard: dict, artifact: dict, iteration: int
) -> dict:
    """Update scoreboard from a cold lane artifact's scored results.

    Tracks per-family:
      - total_scored: times the family appeared in scored results
      - scored_positive: times best_net_bps > 0
      - route_viable: times at least one route was quotable
      - guard_passed: times profit guard passed
      - sessions_with_signal: distinct iteration numbers where scored_positive
      - last_iteration: most recent iteration this family was seen
    """
    families = scoreboard.get("families", {})
    results = artifact.get("results", [])
    if not results:
        return scoreboard

    for r in results:
        if not isinstance(r, dict):
            continue
        pair = r.get("pair_key") or r.get("pair", "")
        if not pair:
            continue
        parts = pair.split("/")
        if len(parts) != 2:
            continue
        family = parts[0]

        rec = families.get(family, {
            "total_scored": 0,
            "scored_positive": 0,
            "route_viable": 0,
            "guard_passed": 0,
            "sessions_with_signal": [],
            "last_iteration": 0,
        })

        rec["total_scored"] = rec.get("total_scored", 0) + 1
        rec["last_iteration"] = iteration

        best_net = r.get("best_net_bps", r.get("net_bps"))
        if best_net is not None and best_net > 0:
            rec["scored_positive"] = rec.get("scored_positive", 0) + 1
            sessions = rec.get("sessions_with_signal", [])
            if iteration not in sessions:
                sessions.append(iteration)
            rec["sessions_with_signal"] = sessions[-20:]

        reject = r.get("reject_reason", "")
        if not reject or reject in ("GAS_EXCEEDS_GROSS", "SLIPPAGE_EXCEEDS_GROSS",
                                     "INSUFFICIENT_IMPACT", "GAS_FLOOR_EXCEEDED"):
            rec["route_viable"] = rec.get("route_viable", 0) + 1

        if r.get("profit_guard_passed"):
            rec["guard_passed"] = rec.get("guard_passed", 0) + 1

        families[family] = rec

    scoreboard["families"] = families
    scoreboard["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    scoreboard["iteration"] = iteration
    return scoreboard


def _write_discovery_scoreboard(scoreboard: dict) -> None:
    """Write the discovery scoreboard to rolling artifact."""
    try:
        _atomic_json_write(_DISCOVERY_SCOREBOARD_PATH, scoreboard, indent=2)
    except Exception as exc:
        logger.debug("Failed to write discovery scoreboard: %s", str(exc)[:80])
