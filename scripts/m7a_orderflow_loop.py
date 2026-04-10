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

logger = get_logger("m7.orderflow.loop")

# ---------------------------------------------------------------------------
# M7.E1.9: Profile-aware artifact paths
# ---------------------------------------------------------------------------
# Production profile uses canonical names; discovery profile uses _discovery
# suffix to prevent evidence contamination during parallel runs.

def _rolling_path(name: str, profile: str = "production") -> str:
    """Build rolling artifact path, inserting _discovery suffix when needed."""
    if profile == "discovery":
        base, ext = os.path.splitext(name)
        name = f"{base}_discovery{ext}"
    return os.path.join("data", "runs", "_rolling", name)


_HOT_ARTIFACT_PATH = _rolling_path("m7_hot_latest.json")
# M7.A.5.39: Cross-lane promoted pairs file — cold writes, hot reads.
_PROMOTED_PAIRS_PATH = _rolling_path("m7_promoted_pairs.json")
# M7.A.5.42: Cold→hot bridge queue — top executable candidates with TTL for hot lane consumption.
_COLD_HOT_BRIDGE_PATH = _rolling_path("m7_cold_hot_bridge.json")
# M7.A.5.45: Hot execution intents — compact rows for hot-scored + profit-guard-checked candidates.
_HOT_INTENTS_PATH = _rolling_path("m7_hot_intents_latest.json")
# M7.A.5.47: Cumulative hot rollup — survives across windows so progress is visible.
_HOT_ROLLUP_PATH = _rolling_path("m7_hot_rollup_latest.json")
# M7.E1.9: Discovery family repeatability scoreboard — tracks per-family stats
# across cold iterations for promotion decisions.
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
    _set_rolling_m7_profile(profile)

# M7.A.5.47k: Session ID — unique per process lifetime, used to reset session
# counters in the hot rollup when the supervisor restarts.
import uuid as _uuid
_SESSION_ID = str(_uuid.uuid4())[:8]


def _atomic_json_write(path: str, data: dict, **kwargs) -> None:
    """Write *data* as JSON to *path* atomically (tmp → os.replace).

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
      - gas_gap_median_bps: latest median gas gap (informational)
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
        # Family = base token of the pair (e.g., DEGEN from DEGEN/WETH)
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
            rec["sessions_with_signal"] = sessions[-20:]  # cap history

        # Route viable if scored (not rejected before quoting)
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


def _write_cold_hot_bridge(
    artifact: dict,
    cold_active_pools: dict | None = None,
    hot_active_pools: dict | None = None,
) -> None:
    """Write cold→hot bridge with per-candidate preload detail and pool→token transport.

    M7.A.5.43: Bridge now carries:
      - cold_executable / cold_stale_positive / near_executable with pool_address
      - pool_token_transport: full _pool_token_cache dump for hot lane to populate
        its own process-local cache (keys are pool addresses, values are
        [token0_addr, token1_addr, fee] tuples).
    M7.A.5.47d: Also carries hot_seen_unresolved_pools — pools discovered via
      hot broad fallback that cold lane should priority-resolve next iteration.
    """
    try:
        candidates = artifact.get("top_executable_candidates", [])
        stale_pos = artifact.get("top_stale_positive_candidates", [])
        recoverable_stale = artifact.get("top_recoverable_stale_candidates", [])
        recoverable_stale_viable = artifact.get("top_recoverable_stale_route_viable", [])
        recoverable_stale_not_viable = artifact.get("top_recoverable_stale_not_viable", [])
        near_exec = artifact.get("near_executable_candidates", [])

        # M7.A.5.43: Transport the full _pool_token_cache for hot lane.
        # This is the canonical solution to the cross-process cache gap:
        # cold lane populates _pool_token_cache via batch_pre_resolve_pools(),
        # hot lane process starts with an empty cache and cannot score events.
        _ptt = {}
        try:
            from m7.orderflow.resolve import _pool_token_cache
            for pa, (t0, t1, fee) in _pool_token_cache.items():
                _ptt[pa] = [t0, t1, fee]
        except Exception:
            pass

        os.makedirs(os.path.dirname(_COLD_HOT_BRIDGE_PATH), exist_ok=True)
        # M7.A.5.47c: Attach recent_active_pools_top from cold events
        _rap_top = []
        if cold_active_pools:
            _rap_sorted = sorted(
                cold_active_pools.items(),
                key=lambda x: x[1].get("event_count", 0),
                reverse=True,
            )[:30]
            _rap_top = [
                {"pool_address": pa, "seen_count": info["event_count"],
                 "last_iter": info.get("last_iter", 0), "source": "cold"}
                for pa, info in _rap_sorted
            ]
        payload = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cold_executable": candidates,
            "cold_stale_positive": stale_pos,
            "cold_recoverable_stale": recoverable_stale,
            "cold_recoverable_stale_route_viable": recoverable_stale_viable,
            "cold_recoverable_stale_not_viable": recoverable_stale_not_viable,
            "near_executable": near_exec,
            "signal_classification": artifact.get("signal_classification", {}),
            "pool_token_transport": _ptt,
            # M7.A.5.47b: Transport micro_refinement for hot queue ordering
            "micro_refinement": artifact.get("micro_refinement", []),
            # M7.A.5.47c: Pools actually seen in cold events (activity ranking)
            "recent_active_pools_top": _rap_top,
            # M7.A.5.47f: Source breakdown — how many pools from each category
            "candidate_source_breakdown": {
                "cold_exec": len(candidates),
                "near_exec": len(near_exec),
                "stale_positive": len(stale_pos),
                "recent_active": len(_rap_top),
                "hot_seen_backfill": 0,  # updated below after unresolved computation
                "ptt_total": len(_ptt),
            },
            # M7.A.5.47k: Initialize overlap/selected as empty lists so they
            # are never null. Hot lane merges actual values after hot windows.
            "hot_seen_vs_bridge_overlap_top": [],
            "bridge_selected_pools_top": [],
            # M7.E1.6: Always emit family_unresolved_pool_count as stable int (0 default).
            # Hot lane updates it via _HOT_PRESERVE_ALWAYS.
            "family_unresolved_pool_count": 0,
            # M7.A.5.47m: Always emit these as non-null (empty defaults).
            # Hot lane merges real values; cold lane guarantees contract.
            "bridge_excluded_top": [],
            "cut_stage_top": artifact.get("cut_stage_top", {}),
            # M7.A.5.47m: Provenance — run_context with run_timestamp
            "run_context": {
                "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "code_sha": None,
                "code_dirty": None,
                "code_desc": None,
                "evidence_sha": None,
            },
        }
        # M7.A.5.47d: Attach hot_seen_unresolved_pools — pools discovered via
        # hot broad fallback that are NOT in _pool_token_cache. Cold lane uses
        # this as a priority backlog for batch_pre_resolve_pools next iteration.
        # NOTE: hot_active_pools is process-local and empty in the cold lane
        # (separate process). Read the hot rollup artifact instead, which the
        # hot lane persists with hot_seen_pool_histogram_top.
        _hot_unresolved = []
        try:
            from m7.orderflow.resolve import _pool_token_cache as _ptc_bridge
            # Merge: in-memory hot_active_pools (if same process) + hot rollup file
            _hap_merged: dict = {}
            if hot_active_pools:
                for _hpa, _hinfo in hot_active_pools.items():
                    _hap_merged[_hpa.lower()] = _hinfo
            # Also read hot rollup artifact for cross-process data
            try:
                if os.path.exists(_HOT_ROLLUP_PATH):
                    with open(_HOT_ROLLUP_PATH, "r", encoding="utf-8") as _rf:
                        _rollup_data = json.load(_rf)
                    for _rh in _rollup_data.get("hot_seen_pool_histogram_top", []):
                        _rh_pa = (_rh.get("pool") or "").lower()
                        if _rh_pa and _rh_pa not in _hap_merged:
                            _hap_merged[_rh_pa] = {
                                "event_count": _rh.get("count", 0),
                                "last_iter": _rh.get("last_iter", 0),
                            }
            except Exception:
                pass
            if _hap_merged:
                _hu_sorted = sorted(
                    _hap_merged.items(),
                    key=lambda x: x[1].get("event_count", 0),
                    reverse=True,
                )
                for _hu_pa, _hu_info in _hu_sorted[:30]:
                    _resolved = _hu_pa in _ptc_bridge or _hu_pa in _ptt
                    _hot_unresolved.append({
                        "pool_address": _hu_pa,
                        "seen_count": _hu_info.get("event_count", 0),
                        "last_iter": _hu_info.get("last_iter", 0),
                        "resolved": _resolved,
                    })
        except Exception:
            pass
        payload["hot_seen_unresolved_pools"] = _hot_unresolved
        # M7.A.5.47f: Update hot_seen_backfill count
        payload["candidate_source_breakdown"]["hot_seen_backfill"] = len(_hot_unresolved)
        # M7.A.5.47n: Preserve hot-derived fields from existing bridge file.
        # Cold lane writes bridge_selected_pools_top=[] because it doesn't
        # do bridge assembly (hot-only). Without this, cold overwrites wipe
        # the hot-merged values every cold iteration.
        # M7.A.5.47p: Only preserve bridge_hit_trace_top / cold_exec_pool_trace
        # if current cold payload has cold_executable entries.  When cold
        # reports cold_executable=[], the trace is stale and must be cleared.
        _HOT_PRESERVE_ALWAYS = (
            "bridge_selected_pools_top", "bridge_excluded_top",
            # M7.A.5.47r: preserve these hot-merged fields across cold overwrites
            "c3_gas_hopeless_skipped", "c3_gas_hopeless_families",
            "bridge_selected_family_diff_top",
            # M7.E1.6: preserve family_unresolved_pool_count across cold overwrites
            "family_unresolved_pool_count",
        )
        _HOT_PRESERVE_IF_COLD_EXEC = (
            "bridge_hit_trace_top", "cold_exec_pool_trace",
        )
        _has_cold_exec = bool(payload.get("cold_executable"))
        try:
            if os.path.exists(_COLD_HOT_BRIDGE_PATH):
                with open(_COLD_HOT_BRIDGE_PATH, "r", encoding="utf-8") as _epf:
                    _existing = json.load(_epf)
                for _hpk in _HOT_PRESERVE_ALWAYS:
                    _existing_val = _existing.get(_hpk)
                    # M7.A.5.47r: use 'is not None' so falsy values (0, [])
                    # from hot merge survive cold overwrites.
                    if _existing_val is not None and _hpk not in payload:
                        payload[_hpk] = _existing_val
                if _has_cold_exec:
                    for _hpk in _HOT_PRESERVE_IF_COLD_EXEC:
                        _existing_val = _existing.get(_hpk)
                        if _existing_val and not payload.get(_hpk):
                            payload[_hpk] = _existing_val
                else:
                    # Explicitly clear stale trace when no cold executables
                    for _hpk in _HOT_PRESERVE_IF_COLD_EXEC:
                        payload[_hpk] = []
        except Exception:
            pass
        # M7.E1.6: After hot-preserve, update breakdown with actual bridge_selected count
        # so cold_exec=0 with bridge_selected_pools_count=20 is self-consistent.
        _bsp = payload.get("bridge_selected_pools_top", [])
        payload["candidate_source_breakdown"]["bridge_selected_pools_count"] = len(_bsp)
        _atomic_json_write(_COLD_HOT_BRIDGE_PATH, payload, indent=2)
    except Exception as exc:
        logger.debug("Failed to write cold-hot bridge: %s", str(exc)[:80])


def _read_cold_hot_bridge() -> dict:
    """Read cold→hot bridge file written by cold lane.

    M7.A.5.43: Returns bridge dict with pool_token_transport for
    hot lane to populate its process-local _pool_token_cache.
    """
    try:
        if not os.path.exists(_COLD_HOT_BRIDGE_PATH):
            return {}
        with open(_COLD_HOT_BRIDGE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.debug("Failed to read cold-hot bridge: %s", str(exc)[:80])
    return {}


def _populate_pool_token_cache_from_bridge(bridge: dict) -> int:
    """Populate hot lane's _pool_token_cache from bridge pool_token_transport.

    M7.A.5.43: This is the critical fix for the cross-process cache gap.
    Cold lane populates _pool_token_cache via batch_pre_resolve_pools().
    Hot lane process starts with empty cache. Bridge transports the cache.

    Returns number of entries populated.
    """
    ptt = bridge.get("pool_token_transport", {})
    if not ptt:
        return 0
    try:
        from m7.orderflow.resolve import _pool_token_cache
        count = 0
        for pa, triple in ptt.items():
            if len(triple) == 3:
                key = pa.lower()
                if key not in _pool_token_cache:
                    _pool_token_cache[key] = tuple(triple)
                    count += 1
        return count
    except Exception as exc:
        logger.debug("Failed to populate pool_token_cache from bridge: %s", str(exc)[:80])
    return 0


def _prewarm_registry_from_bridge(
    registry, bridge: dict,
    dex_configs: dict, rpc_url: str, block_num: int,
    priority_pools: set | None = None,
) -> int:
    """Prewarm hot registry from bridge entries using token addresses.

    M7.A.5.43: Pool-address-first matching. Bridge entries carry
    pool_address + token0_addr + token1_addr. We prewarm the registry
    using actual token addresses, not symbol-pair strings.

    M7.A.5.45: Priority prewarm. When priority_pools is provided (set of
    lowercase pool addresses from cold_executable), those pools are
    prewarmed first. Remaining ptt entries are prewarmed after.

    Returns number of pairs prewarmed.
    """
    ptt = bridge.get("pool_token_transport", {})
    if not ptt:
        return 0
    count = 0
    _seen_pairs: set = set()

    # M7.A.5.45: Sort ptt entries so priority_pools come first.
    _priority = priority_pools or set()
    _items = sorted(
        ptt.items(),
        key=lambda kv: (0 if kv[0].lower() in _priority else 1),
    )

    for pa, triple in _items:
        if len(triple) != 3:
            continue
        t0, t1, _fee = triple
        if not t0 or not t1:
            continue
        pair_key = f"{min(t0.lower(), t1.lower())}/{max(t0.lower(), t1.lower())}"
        if pair_key in _seen_pairs:
            continue
        _seen_pairs.add(pair_key)
        try:
            registry.preload_pair(t0, t1, dex_configs, rpc_url, block_num)
            count += 1
        except Exception:
            pass
    return count


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
        profile=getattr(cli_args, "profile", "production"),
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


def _promote_pairs_from_cold(cold_artifact: dict, accumulated_cold_stats: dict) -> dict:
    """Identify pairs to promote from cold lane results to hot watchlist.

    M7.A.5.39: Two-level promotion:

    **Candidate** (level 1) — relaxed; enters registry prewarm:
      - Appeared in >= PROMOTED_MIN_COLD_APPEARANCES cold iterations
      - reject_reason != PRICING_ANOMALY (no anomaly flag ever)
      - registry_pools_active > 0
      - best_net_bps > PROMOTED_MIN_NET_BPS (not total garbage)
      (Does NOT require size_valid_for_token)

    **Execution** (level 2) — strict; eligible for hot-path scoring:
      - All candidate rules PLUS:
      - size_valid_for_token=True in at least one scored result

    Returns dict with keys:
      "candidate": list of pair strings (capped at PROMOTED_CANDIDATE_MAX_PAIRS)
      "execution": list of pair strings (capped at PROMOTED_MAX_PAIRS)
    """
    # M7.A.5.46: Use _raw_results (BackrunResult objects) instead of
    # serialized results dicts — compact mode no longer serializes results.
    results = cold_artifact.get("_raw_results", cold_artifact.get("results", []))
    for r in results:
        pair = r.get("actual_pair") if isinstance(r, dict) else getattr(r, "actual_pair", None)
        if not pair or "/" not in pair:
            continue

        sv = r.get("size_valid_for_token") if isinstance(r, dict) else getattr(r, "size_valid_for_token", None)
        rr = r.get("reject_reason") if isinstance(r, dict) else getattr(r, "reject_reason", None)
        rpa = r.get("registry_pools_active") if isinstance(r, dict) else getattr(r, "registry_pools_active", None)
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)

        if pair not in accumulated_cold_stats:
            accumulated_cold_stats[pair] = {
                "appearances": 0,
                "size_valid_seen": False,
                "has_active_pools": False,
                "best_net_bps": None,
                "has_anomaly": False,
            }

        stats = accumulated_cold_stats[pair]
        stats["appearances"] += 1
        if sv is True:
            stats["size_valid_seen"] = True
        if rpa and rpa > 0:
            stats["has_active_pools"] = True
        if rr == "REJECT_PRICING_ANOMALY":
            stats["has_anomaly"] = True
        if net is not None:
            if stats["best_net_bps"] is None or net > stats["best_net_bps"]:
                stats["best_net_bps"] = net

    # M7.A.5.39: Apply two-level promotion rules
    candidates = []
    execution = []
    for pair, stats in accumulated_cold_stats.items():
        # Common rules (candidate level 1)
        if stats["appearances"] < PROMOTED_MIN_COLD_APPEARANCES:
            continue
        if not stats["has_active_pools"]:
            continue
        if stats["has_anomaly"]:
            continue
        if stats["best_net_bps"] is None or stats["best_net_bps"] < PROMOTED_MIN_NET_BPS:
            continue
        candidates.append(pair)
        # Execution level 2: additionally requires size_valid
        if stats["size_valid_seen"]:
            execution.append(pair)

    # Sort by best_net descending, cap at respective limits
    _sort_key = lambda p: accumulated_cold_stats[p].get("best_net_bps") or -999
    candidates.sort(key=_sort_key, reverse=True)
    execution.sort(key=_sort_key, reverse=True)
    return {
        "candidate": candidates[:PROMOTED_CANDIDATE_MAX_PAIRS],
        "execution": execution[:PROMOTED_MAX_PAIRS],
    }


def _run_profit_guard_on_results(results: list, chain: str = "arbitrum_one") -> list:
    """Run profit_guard on all scored results with positive net_bps.

    Returns list of (result_dict, ProfitGuardResult) for candidates that
    pass the guard.
    """
    passed = []
    for r in results:
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)
        if net is None or net <= 0:
            continue
        # M7.A.5.33: Derive buy/sell from existing fields.
        # best_buy_amount_wei / best_sell_amount_wei don't exist on BackrunResult.
        # Use amount_in_wei (backrun input) and gross_pnl_wei to reconstruct:
        #   sell_amount = amount_in_wei + gross_pnl_wei  (since gross = sell - input)
        size = r.get("amount_in_wei") if isinstance(r, dict) else getattr(r, "amount_in_wei", 0)
        gross = r.get("gross_pnl_wei") if isinstance(r, dict) else getattr(r, "gross_pnl_wei", 0)
        buy = size  # backrun input IS the buy amount
        sell = size + gross  # sell = input + gross PnL
        sv = r.get("size_valid_for_token") if isinstance(r, dict) else getattr(r, "size_valid_for_token", None)
        rr = r.get("reject_reason") if isinstance(r, dict) else getattr(r, "reject_reason", None)

        # M7.A.5.31: Skip size_valid=false from profit guard (Step 5)
        if sv is False:
            continue

        # M7.A.5.34: Hard-exclude PRICING_ANOMALY from profit guard
        if rr == "REJECT_PRICING_ANOMALY":
            continue

        if not buy or not sell or not size:
            continue
        pipeline_ms = r.get("quote_pipeline_latency_ms") if isinstance(r, dict) else getattr(r, "quote_pipeline_latency_ms", None)
        guard = check_profit_guard(
            buy_amount_wei=buy, sell_amount_wei=sell, backrun_size_wei=size,
            pipeline_latency_ms=pipeline_ms, chain=chain,
        )
        if guard.passed:
            passed.append((r, guard))
    return passed


def _write_hot_heartbeat_on_error(
    iteration: int,
    window_started_at: str,
    window_ended_at: str,
    error_msg: str,
    chain: str = "arbitrum_one",
) -> None:
    """M7.E1.7: Write heartbeat hot artifact when run_ws_live() or processing fails.

    Ensures hot artifacts always carry a fresh current_window_timestamp so
    reviewers can distinguish "runtime alive but WS failed" from "runtime dead".
    Same heartbeat contract as cold lane (current_window_timestamp,
    snapshot_preserved, snapshot_run_timestamp).
    """
    _ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Try to preserve existing artifact (anti-bad-overwrite, like cold lane)
    existing: dict | None = None
    if os.path.exists(_HOT_ARTIFACT_PATH):
        try:
            with open(_HOT_ARTIFACT_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = None

    if existing is not None:
        # Preserve previous snapshot, just stamp heartbeat fields
        existing["current_window_timestamp"] = _ts_now
        existing["snapshot_preserved"] = True
        existing.setdefault("chain", chain)
        existing.setdefault(
            "snapshot_run_timestamp",
            existing.get("run_context", {}).get("run_timestamp"),
        )
        # M7.E1.8: Accumulate error count on heartbeat path
        _ec = existing.get("error_counts") or {}
        _ec["heartbeat_on_error"] = _ec.get("heartbeat_on_error", 0) + 1
        existing["error_counts"] = _ec
        existing["m7_loop_context"] = {
            "lane": "hot",
            "loop_iteration": iteration,
            "window_started_at": window_started_at,
            "window_ended_at": window_ended_at,
            "window_empty": True,
            "error_in_window": error_msg,
        }
    else:
        # No existing artifact — write minimal heartbeat from scratch
        existing = {
            "lane": "hot",
            "chain": chain,
            "timestamp": _ts_now,
            "loop_iteration": iteration,
            "events_count": 0,
            "best_net_bps_clean": 0,
            "viable_count": 0,
            "has_positive": False,
            "profit_guard_passed_count": 0,
            "current_window_timestamp": _ts_now,
            "snapshot_preserved": True,
            "snapshot_run_timestamp": _ts_now,
            "signal_counts": {
                "events_count": 0,
                "fast_scored": 0,
                "fast_positive": 0,
                "guard_passed": 0,
                "viable_count": 0,
                "sim_attempted": 0,
                "sim_passed": 0,
                "submit_ready": 0,
                "realized": 0,
            },
            "error_counts": {"heartbeat_on_error": 1},
            "run_context": {
                "run_timestamp": _ts_now,
                "chain": chain,
                "code_sha": None,
                "code_dirty": None,
                "code_desc": None,
                "evidence_sha": None,
            },
            "headline_level": "none",
            "m7_loop_context": {
                "lane": "hot",
                "loop_iteration": iteration,
                "window_started_at": window_started_at,
                "window_ended_at": window_ended_at,
                "window_empty": True,
                "error_in_window": error_msg,
            },
        }

    try:
        _atomic_json_write(_HOT_ARTIFACT_PATH, existing, indent=2, default=str)
        logger.info(
            "Hot heartbeat written on error (iter %d): %s",
            iteration, _HOT_ARTIFACT_PATH,
        )
    except Exception as exc:
        logger.warning("Failed to write hot heartbeat: %s", str(exc)[:120])


def _write_hot_artifact(artifact: dict, iteration: int, guard_results: list = None,
                        fast_results: list = None, promoted_pairs: list = None,
                        candidate_pairs: list = None,
                        bridge_diagnostics: dict = None,
                        chain: str = "arbitrum_one",
                        profile: str = "production") -> list:
    """Write minimal hot-lane artifact: best candidate + profit guard status.

    fast_results: list of BackrunResult from score_backrun_fast() (M7.A.5.32)
    promoted_pairs: list of "SYM_A/SYM_B" execution-promoted from cold (M7.A.5.39)
    candidate_pairs: list of "SYM_A/SYM_B" candidate-promoted (wider, M7.A.5.39)
    bridge_diagnostics: dict with bridge prewarm stats (M7.A.5.43)
    """
    # M7.A.5.46: Use _raw_results for BackrunResult access (compact mode).
    results = artifact.get("_raw_results", artifact.get("results", []))
    best = None
    for r in results:
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)
        sv = r.get("size_valid_for_token") if isinstance(r, dict) else getattr(r, "size_valid_for_token", None)
        rr = r.get("reject_reason") if isinstance(r, dict) else getattr(r, "reject_reason", None)
        # M7.A.5.31: Skip size_valid=false from hot headline
        if sv is False:
            continue
        # M7.A.5.34: Hard-exclude PRICING_ANOMALY from hot headline
        if rr == "REJECT_PRICING_ANOMALY":
            continue
        if net is not None and net > 0:
            if best is None or net > (best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", 0)):
                best = r

    _ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _events_count = artifact.get("events_count", 0)
    hot = {
        "lane": "hot",
        "chain": chain,
        "timestamp": _ts_now,
        "loop_iteration": iteration,
        "events_count": _events_count,
        "best_net_bps_clean": artifact.get("best_net_bps_clean") or 0,
        "viable_count": artifact.get("viable_count", 0),
        "has_positive": best is not None,
        "profit_guard_passed_count": len(guard_results) if guard_results else 0,
        # M7.E1.6.1: Always-fresh heartbeat timestamp so reviewer knows runtime is alive
        "current_window_timestamp": _ts_now,
        "snapshot_preserved": _events_count == 0,
        # M7.E1.7: Complete heartbeat contract — same fields as cold lane
        "snapshot_run_timestamp": _ts_now,
        # M7.E1.8: signal_counts always present (honest 0/{} on empty windows)
        "signal_counts": {},
        # M7.E1.10: WS connection health — critical for distinguishing
        # "no market events" from "couldn't connect to data source"
        "ws_connection_status": artifact.get("ws_connection_status", "unknown"),
        "blocks_processed": (artifact.get("ws_live_stats") or {}).get("blocks_processed", 0),
        # M7.A.5.47m: Provenance — run_context with run_timestamp
        "run_context": {
            "run_timestamp": _ts_now,
            "chain": chain,
            "code_sha": None,
            "code_dirty": None,
            "code_desc": None,
            "evidence_sha": None,
        },
    }

    # M7.A.5.46: Compute headline_level for hot artifact.
    # Hot lane only knows: hot_scored, profit_guard_passed, realized_onchain_profit.
    # diagnostic_positive and cold_executable_positive come from bridge (cold lane truth).
    _fast_scored = len(fast_results) if fast_results else 0
    _fast_positive = sum(1 for r in (fast_results or []) if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0)
    _guard_count = len(guard_results) if guard_results else 0
    # Read cold_executable_positive from bridge, not synthesized from fast_positive.
    _bridge_cold_exec_count = len(
        (bridge_diagnostics or {}).get("_bridge_cold_executable", [])
    ) if bridge_diagnostics else 0
    hot["headline_level"] = _compute_headline_level({
        "diagnostic_positive": _fast_positive,
        "cold_executable_positive": _bridge_cold_exec_count,
        "hot_scored": _fast_scored,
        "profit_guard_passed": _guard_count,
        "realized_onchain_profit": 0,
    })

    # M7.E1.8: signal_counts — always honest 0/{} on empty windows, never null
    hot["signal_counts"] = {
        "events_count": _events_count,
        "fast_scored": _fast_scored,
        "fast_positive": _fast_positive,
        "guard_passed": _guard_count,
        "viable_count": artifact.get("viable_count", 0),
        "sim_attempted": 0,
        "sim_passed": 0,
        "submit_ready": 0,
        "realized": 0,
    }

    # M7.E1.8: Error counters — always present (honest 0 on normal path)
    hot["error_counts"] = {"heartbeat_on_error": 0}

    # M7.A.5.39: Two-level promoted watchlist info
    _cand = candidate_pairs or []
    _exec = promoted_pairs or []
    if _exec or _cand:
        hot["promoted_watchlist"] = {
            "count": len(_exec),
            "pairs": _exec,
            "candidate_count": len(_cand),
            "candidate_pairs": _cand,
        }
    else:
        # M7.E1.10: Use profile-aware seed pairs instead of production-only HOT_WATCHLIST_PAIRS.
        _seed = get_prewarm_pairs(chain, profile)
        hot["promoted_watchlist"] = {
            "count": 0,
            "pairs": [f"{a}/{b}" for a, b in _seed],
            "candidate_count": 0,
            "candidate_pairs": [],
            "source": "seed_only",
        }

    # M7.A.5.37: Always emit fast_path block and hot_skip_count even when empty.
    # This ensures rolling hot artifact always surfaces p50/p90/hot_skip metrics.
    _raw_results = artifact.get("_raw_results", [])
    _hot_skip_count = sum(
        1 for r in _raw_results
        if getattr(r, "scoring_path", None) == "hot_skip"
    )
    hot["hot_skip_count"] = _hot_skip_count

    # M7.A.5.42: Hot-gap debug counters — diagnose conversion gap
    # M7.A.5.47e: Disentangle counters. "admitted" = entered scoring pipeline
    # (total events minus hot_skip). "scored" = got registry_fast result.
    _fast_scored = sum(
        1 for r in _raw_results
        if getattr(r, "scoring_path", None) == "registry_fast"
    )
    _admitted_to_scoring = len(_raw_results) - _hot_skip_count
    # M7.A.5.43: 3 hot-miss counters from bridge diagnostics
    _bd = bridge_diagnostics or {}
    hot["hot_gap_debug"] = {
        "total_events": len(_raw_results),
        # M7.A.5.47e: admission = events that passed registry check (not skipped)
        "admitted_to_scoring": _admitted_to_scoring,
        "fast_path_scored_count": _fast_scored,
        "not_in_hot_registry_count": _hot_skip_count,
        "watchlist_match_count": _bd.get("bridge_pool_address_hit_count", 0),
        # M7.A.5.43: Bridge-driven diagnostics
        "pool_address_match_count": _bd.get("pool_address_match_count", 0),
        "canonical_pair_match_count": _bd.get("canonical_pair_match_count", 0),
        "registry_has_pair_but_not_pool_count": _bd.get("registry_has_pair_but_not_pool_count", 0),
        "bridge_cache_populated": _bd.get("bridge_cache_populated", 0),
        "bridge_registry_prewarmed": _bd.get("bridge_registry_prewarmed", 0),
        # M7.A.5.44: Bridge-hit counters
        "bridge_pool_address_hit_count": _bd.get("bridge_pool_address_hit_count", 0),
        "bridge_pair_hit_count": _bd.get("bridge_pair_hit_count", 0),
        "bridge_loaded_candidate_count": _bd.get("bridge_loaded_candidate_count", 0),
        # M7.A.5.47j: Track actual focused bridge size (all buckets)
        "bridge_focused_pool_count": _bd.get("bridge_focused_pool_count", 0),
        # M7.A.5.46: Pair-level fallback counter
        "bridge_pair_fallback_count": _bd.get("bridge_pair_fallback_count", 0),
        # M7.A.5.47e: Canonical per-window scoring counters
        "fast_score_attempted": _admitted_to_scoring,
        "fast_score_scored": _fast_scored,
        "fast_score_rejected_economics": sum(
            1 for r in _raw_results
            if getattr(r, "scoring_path", None) == "registry_fast"
            and getattr(r, "reject_reason", None) in (
                "REJECT_GAS_EXCEEDS_GROSS", "REJECT_STALE_POSITIVE",
            )
        ),
    }

    # M7.E1.3: Explicit bridge-matched registry vs gas rejection separation.
    # This separates hot zero-hit into two orthogonal blocker classes:
    # (a) event pool is in bridge but NOT in hot registry → registry rejection
    # (b) event pool is in bridge AND registry but gas-killed → gas rejection
    _bridge_set_h = _bd.get("_bridge_pool_addrs_set", set())
    _m_bridge_reg_rejected = 0
    _m_bridge_gas_rejected = 0
    _m_bridge_scored_positive = 0
    for _r_h in _raw_results:
        _evt_h = getattr(_r_h, "_source_event", None)
        if not _evt_h:
            continue
        _ep_h = getattr(_evt_h, "pool_address", "").lower()
        if _ep_h not in _bridge_set_h:
            continue
        if getattr(_r_h, "scoring_path", None) == "hot_skip":
            _m_bridge_reg_rejected += 1
        elif (getattr(_r_h, "best_backrun_net_bps", None) or 0) <= 0:
            _m_bridge_gas_rejected += 1
        else:
            _m_bridge_scored_positive += 1
    hot["hot_gap_debug"]["matched_bridge_then_registry_rejected"] = _m_bridge_reg_rejected
    hot["hot_gap_debug"]["matched_bridge_then_gas_rejected"] = _m_bridge_gas_rejected
    hot["hot_gap_debug"]["matched_bridge_then_scored_positive"] = _m_bridge_scored_positive

    # M7.A.5.47o: Surface bridge counts at top level (not just in hot_gap_debug).
    hot["bridge_focused_pool_count"] = _bd.get("bridge_focused_pool_count", 0)
    hot["bridge_loaded_candidate_count"] = _bd.get("bridge_loaded_candidate_count", 0)
    # M7.A.5.47o: Gas-hopeless C3 tightening stats at top level.
    # M7.A.5.47p: Guarantee non-None — use `or` fallback for explicit None values.
    hot["c3_gas_hopeless_skipped"] = _bd.get("c3_gas_hopeless_skipped") or 0
    hot["c3_gas_hopeless_families"] = _bd.get("c3_gas_hopeless_families") or []

    # M7.A.5.47d: Surface bridge miss sample at top level for diagnostics
    hot["bridge_miss_sample_top"] = _bd.get("bridge_miss_sample_top", [])
    # M7.A.5.47k: Bridge exclusion reasons at top level
    hot["bridge_excluded_top"] = _bd.get("bridge_excluded_top", [])
    # M7.A.5.47l: Bridge selected pools at assembly time
    hot["bridge_selected_pools_top"] = _bd.get("bridge_selected_at_assembly", [])

    # M7.A.5.47m: bridge_hit_trace_top — exact-pool diagnostic for each
    # cold_executable pool. Uses the FULL bridge set (not truncated list)
    # so in_bridge is always truthful.
    _bridge_hit_trace: list = []
    _bridge_cold_execs = _bd.get("_bridge_cold_executable", [])
    _full_bridge_set = _bd.get("_bridge_pool_addrs_set", set())
    _bucket_a_set = _bd.get("_bucket_a", set())
    for _cet in _bridge_cold_execs:
        _cet_pa = (_cet.get("pool_address") or "").lower() if isinstance(_cet, dict) else ""
        if not _cet_pa:
            continue
        # Check: is this pool in the full bridge set (truthful check)?
        _cet_in_bridge = _cet_pa in _full_bridge_set
        # Determine selected bucket
        _cet_bucket = None
        if _cet_in_bridge:
            # Find bucket from assembly list first (labeled)
            for _sel in _bd.get("bridge_selected_at_assembly", []):
                if (_sel.get("pool_address") or "").lower() == _cet_pa:
                    _cet_bucket = _sel.get("bucket")
                    break
            if _cet_bucket is None:
                _cet_bucket = "A_cold_exec" if _cet_pa in _bucket_a_set else "unlabeled_in_bridge"
        # Check: did any hot event arrive at this pool?
        _cet_hot_events = 0
        _cet_fast_attempted = 0
        _cet_fast_scored = 0
        for _r in _raw_results:
            _evt = getattr(_r, "_source_event", None)
            if _evt and getattr(_evt, "pool_address", "").lower() == _cet_pa:
                _cet_hot_events += 1
                if getattr(_r, "scoring_path", None) != "hot_skip":
                    _cet_fast_attempted += 1
                    if (getattr(_r, "best_backrun_net_bps", None) or 0) != 0:
                        _cet_fast_scored += 1
        # Reason if not hit
        _cet_reason: str | None = None
        if not _cet_in_bridge:
            _cet_reason = "not_in_bridge"
        elif _cet_hot_events == 0:
            _cet_reason = "no_hot_events_at_pool"
        elif _cet_fast_attempted == 0:
            _cet_reason = "hot_skip_no_scoring"
        elif _cet_fast_scored == 0:
            _cet_reason = "scored_but_no_result"
        _bridge_hit_trace.append({
            "pool_address": _cet_pa,
            "actual_pair": _cet.get("actual_pair", ""),
            "cold_net_bps": _cet.get("net_bps", 0),
            "in_bridge": _cet_in_bridge,
            "selected_bucket": _cet_bucket,
            "hot_events_seen": _cet_hot_events,
            "registry_match": _cet_pa in _full_bridge_set,
            "fast_score_attempted": _cet_fast_attempted,
            "fast_score_scored": _cet_fast_scored,
            "reason_if_not_hit": _cet_reason,
            # M7.A.5.47q: Surface stale_sub_reason so pipeline_abort
            # is distinguishable from block_lag in the trace.
            "stale_sub_reason": _cet.get("stale_sub_reason"),
        })
    hot["bridge_hit_trace_top"] = _bridge_hit_trace
    # M7.A.5.47m: Keep backward compat alias
    hot["cold_exec_pool_trace"] = _bridge_hit_trace

    # M7.A.5.47o: other_live_pool_trace_top — shows live pools (from hot events)
    # that are NOT in bridge_hit_trace (i.e. not cold-exec pools) but had events.
    # Answers: why do OTHER live pools not get hit?
    _cold_exec_addrs = {(c.get("pool_address") or "").lower() for c in _bridge_cold_execs}
    _ptt_ref = _bd.get("_ptt", {})  # pool_token_transport if available
    _other_pool_events: dict = {}
    for _r in _raw_results:
        _evt = getattr(_r, "_source_event", None)
        if not _evt:
            continue
        _op = getattr(_evt, "pool_address", "").lower()
        if not _op or _op in _cold_exec_addrs:
            continue
        if _op not in _other_pool_events:
            _other_pool_events[_op] = {"hot_events": 0, "fast_attempted": 0, "fast_scored": 0}
        _other_pool_events[_op]["hot_events"] += 1
        if getattr(_r, "scoring_path", None) != "hot_skip":
            _other_pool_events[_op]["fast_attempted"] += 1
            if (getattr(_r, "best_backrun_net_bps", None) or 0) != 0:
                _other_pool_events[_op]["fast_scored"] += 1
    _other_trace: list = []
    for _op, _oc in sorted(_other_pool_events.items(), key=lambda x: x[1]["hot_events"], reverse=True)[:10]:
        _op_in_bridge = _op in _full_bridge_set
        _op_bucket = None
        if _op_in_bridge:
            for _sel in _bd.get("bridge_selected_at_assembly", []):
                if (_sel.get("pool_address") or "").lower() == _op:
                    _op_bucket = _sel.get("bucket")
                    break
            if _op_bucket is None:
                _op_bucket = "unlabeled_in_bridge"
        _op_reason = None
        if not _op_in_bridge:
            _op_reason = "not_in_bridge"
        elif _oc["fast_attempted"] == 0:
            _op_reason = "hot_skip_no_scoring"
        elif _oc["fast_scored"] == 0:
            _op_reason = "scored_but_no_result"
        else:
            _op_reason = None
        _op_info = _ptt_ref.get(_op) if _ptt_ref else None
        _op_family = f"{_op_info[0]}/{_op_info[1]}" if _op_info and len(_op_info) >= 2 else "family_unresolved"
        _other_trace.append({
            "pool_address": _op,
            "family": _op_family,
            "in_bridge": _op_in_bridge,
            "selected_bucket": _op_bucket,
            "hot_events_seen": _oc["hot_events"],
            "fast_score_attempted": _oc["fast_attempted"],
            "fast_score_scored": _oc["fast_scored"],
            "reason_if_not_hit": _op_reason,
        })
    hot["other_live_pool_trace_top"] = _other_trace

    # M7.A.5.47p: bridge_selection_diff_top — bidirectional mismatch diagnostic.
    # Shows: (a) hot-seen pools absent from bridge, (b) bridge pools with zero hot events.
    _sel_diff: dict = {"hot_seen_not_in_bridge": [], "bridge_selected_but_no_hot_events": []}
    # (a) Hot-seen pools not in bridge (from other_live_pool_trace)
    for _ot in _other_trace:
        if not _ot.get("in_bridge"):
            _sel_diff["hot_seen_not_in_bridge"].append({
                "pool_address": _ot["pool_address"],
                "family": _ot["family"],
                "hot_events_seen": _ot["hot_events_seen"],
                "reason_if_absent": _ot.get("reason_if_not_hit", "not_in_bridge"),
            })
    # (b) Bridge-selected pools with zero hot events this window
    _all_event_pools: set = set()
    for _r in _raw_results:
        _evt = getattr(_r, "_source_event", None)
        if _evt:
            _ep = getattr(_evt, "pool_address", "").lower()
            if _ep:
                _all_event_pools.add(_ep)
    for _sel in _bd.get("bridge_selected_at_assembly", [])[:20]:
        _sel_pa = (_sel.get("pool_address") or "").lower()
        if _sel_pa and _sel_pa not in _all_event_pools:
            _sel_info = _ptt_ref.get(_sel_pa) if _ptt_ref else None
            _sel_fam = f"{_sel_info[0]}/{_sel_info[1]}" if _sel_info and len(_sel_info) >= 2 else "family_unresolved"
            _sel_diff["bridge_selected_but_no_hot_events"].append({
                "pool_address": _sel_pa,
                "family": _sel_fam,
                "selected_bucket": _sel.get("bucket"),
            })
    # Truncate to top 10 each
    _sel_diff["hot_seen_not_in_bridge"] = _sel_diff["hot_seen_not_in_bridge"][:10]
    _sel_diff["bridge_selected_but_no_hot_events"] = _sel_diff["bridge_selected_but_no_hot_events"][:10]
    hot["bridge_selection_diff_top"] = _sel_diff

    # M7.A.5.47q: bridge_selected_family_diff_top — family-level aggregation.
    # Groups bridge-selected pools by family, counts total selected, events at ANY
    # pool of that family this window, and exact hit count. Answers: is the family
    # starved of events, or just the exact pool?
    _fam_diff: dict = {}  # family_str -> {selected_pool_count, hot_events_any_pool, exact_hit_count, pools}
    for _sel in _bd.get("bridge_selected_at_assembly", [])[:30]:
        _sel_pa = (_sel.get("pool_address") or "").lower()
        _sel_fam = _sel.get("family") or "family_unresolved"
        if not _sel_fam or _sel_fam == "":
            _sel_fam = "family_unresolved"
        if _sel_fam not in _fam_diff:
            _fam_diff[_sel_fam] = {
                "family": _sel_fam,
                "selected_pool_count": 0,
                "hot_events_any_pool": 0,
                "exact_hit_count": 0,
                "pools": [],
            }
        _fd = _fam_diff[_sel_fam]
        _fd["selected_pool_count"] += 1
        # Count events at this specific pool
        _sel_events = 0
        for _r in _raw_results:
            _evt = getattr(_r, "_source_event", None)
            if _evt and getattr(_evt, "pool_address", "").lower() == _sel_pa:
                _sel_events += 1
        _fd["hot_events_any_pool"] += _sel_events
        if _sel_events > 0:
            _fd["exact_hit_count"] += 1
        _fd["pools"].append(_sel_pa)
    # Determine reason_if_zero for families with no events
    _fam_diff_list = []
    for _fd in sorted(_fam_diff.values(), key=lambda x: x["selected_pool_count"], reverse=True):
        _reason_z = None
        if _fd["hot_events_any_pool"] == 0:
            _reason_z = "no_events_at_any_family_pool"
        elif _fd["exact_hit_count"] == 0:
            _reason_z = "events_at_family_but_no_exact_match"
        _fd["reason_if_zero"] = _reason_z
        del _fd["pools"]  # strip internal pool list from artifact
        _fam_diff_list.append(_fd)
    # M7.E1.5: Separate family_unresolved from resolved families in bridge summary.
    _resolved_fam = [f for f in _fam_diff_list if f.get("family") != "family_unresolved"]
    _unresolved_fam = [f for f in _fam_diff_list if f.get("family") == "family_unresolved"]
    hot["bridge_selected_family_diff_top"] = _resolved_fam[:10]
    hot["family_unresolved_pool_count"] = sum(f.get("selected_pool_count", 0) for f in _unresolved_fam)

    if fast_results:
        fast_viable = [r for r in fast_results if r.route_viable]
        fast_positive = [r for r in fast_results if (r.best_backrun_net_bps or 0) > 0]
        fast_guard_passed = [r for r in fast_results if r.profit_guard_passed]
        fast_latencies = [r.quote_pipeline_latency_ms for r in fast_results if r.quote_pipeline_latency_ms]
        # M7.A.5.33/5.34: Aggregate stage-level timing (includes calldata + sign)
        _stage_keys = ["registry_lookup_ms", "pool_state_ms", "local_math_ms",
                       "profit_guard_ms", "tx_build_ms", "calldata_ms",
                       "sign_or_bundle_prep_ms"]
        _stage_agg = {}
        for sk in _stage_keys:
            vals = [
                r.pipeline_stage_latency_ms.get(sk, 0)
                for r in fast_results
                if r.pipeline_stage_latency_ms
            ]
            if vals:
                _stage_agg[f"mean_{sk}"] = round(sum(vals) / len(vals), 2)
                _stage_agg[f"max_{sk}"] = round(max(vals), 2)
        hot["fast_path"] = {
            "scored": len(fast_results),
            "positive": len(fast_positive),
            "viable": len(fast_viable),
            "profit_guard_passed": len(fast_guard_passed),
            "mean_latency_ms": round(sum(fast_latencies) / len(fast_latencies), 2) if fast_latencies else None,
            "max_latency_ms": round(max(fast_latencies), 2) if fast_latencies else None,
            "p50_latency_ms": round(sorted(fast_latencies)[len(fast_latencies) // 2], 2) if fast_latencies else None,
            "p90_latency_ms": round(sorted(fast_latencies)[int(len(fast_latencies) * 0.9)], 2) if fast_latencies else None,
            "best_net_bps": round(max((r.best_backrun_net_bps or 0) for r in fast_results), 4) if fast_results else None,
            "scoring_paths": list(set(r.scoring_path for r in fast_results if r.scoring_path)),
            "stage_timings": _stage_agg if _stage_agg else None,
        }
        # Check if fast path found a better candidate
        for r in fast_positive:
            net = r.best_backrun_net_bps or 0
            if best is None or net > (best.get("best_backrun_net_bps") if isinstance(best, dict) else getattr(best, "best_backrun_net_bps", 0)):
                best = r  # fast-path result is a BackrunResult object
    else:
        # M7.A.5.37: Always emit fast_path block with zeros/nulls
        hot["fast_path"] = {
            "scored": 0,
            "positive": 0,
            "viable": 0,
            "profit_guard_passed": 0,
            "mean_latency_ms": None,
            "max_latency_ms": None,
            "p50_latency_ms": None,
            "p90_latency_ms": None,
            "best_net_bps": None,
            "scoring_paths": [],
            "stage_timings": None,
        }

    # M7.A.5.41: Compact top-hot-candidate rows for auditability
    _TOP_HOT_N = 5
    if fast_results:
        _sorted_hot = sorted(
            fast_results,
            key=lambda r: r.best_backrun_net_bps or 0,
            reverse=True,
        )[:_TOP_HOT_N]
        hot["top_hot_candidates"] = [
            {
                "event_id": r.event_id,
                "actual_pair": r.actual_pair,
                "net_bps": round(r.best_backrun_net_bps, 4) if r.best_backrun_net_bps else 0,
                "block_lag": r.block_lag,
                "route_viable": r.route_viable,
                "scoring_path": r.scoring_path,
                "profit_guard_passed": r.profit_guard_passed,
                "pipeline_latency_ms": r.quote_pipeline_latency_ms,
            }
            for r in _sorted_hot
        ]
    else:
        hot["top_hot_candidates"] = []

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
        _atomic_json_write(_HOT_ARTIFACT_PATH, hot, indent=2, default=str)
        logger.info("Hot lane artifact written to %s", _HOT_ARTIFACT_PATH)
    except Exception as exc:
        logger.warning("Failed to write hot artifact: %s", str(exc)[:120])
    # M7.A.5.47n: Return bridge hit trace so caller can merge into bridge file.
    # M7.A.5.47p: Also return other_live_pool_trace for live-miss auto-pin.
    # M7.E1.5: Return resolved families only (family_unresolved filtered out).
    # M7.E1.6: Also return family_unresolved_pool_count for bridge contract.
    _family_unresolved_count = hot.get("family_unresolved_pool_count", 0)
    return _bridge_hit_trace, _other_trace, _resolved_fam, _family_unresolved_count


def _compute_headline_level(funnel: dict) -> str:
    """Return the highest confirmed execution funnel stage with count > 0.

    M7.A.5.45: Headline enforcement — the UI and reports must not claim
    progress beyond this level. Stages are checked in reverse order
    (most advanced first). Returns the stage name string.
    """
    _STAGES = [
        "realized_onchain_profit",
        "profit_guard_passed",
        "hot_scored",
        "cold_executable_positive",
        "diagnostic_positive",
    ]
    for stage in _STAGES:
        if funnel.get(stage, 0) > 0:
            return stage
    return "none"


def _write_hot_intents(
    fast_results: list | None,
    guard_results: list | None,
    iteration: int,
    bridge: dict | None = None,
    chain: str = "arbitrum_one",
) -> None:
    """Write hot execution intents artifact — compact rows for hot-scored
    and profit-guard-checked candidates only.

    M7.A.5.45: This artifact is the canonical "ready to submit" queue.
    Only candidates that were actually scored in hot lane (scoring_path=
    registry_fast) appear. Rows include profit_guard_passed status.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []

    # Extract hot-scored candidates from fast_results
    _fast = fast_results or []
    # Build set of guard-passed event_ids for cross-reference
    _guard_event_ids: set = set()
    if guard_results:
        for r_dict, _g in guard_results:
            eid = r_dict.get("event_id") if isinstance(r_dict, dict) else getattr(r_dict, "event_id", None)
            if eid:
                _guard_event_ids.add(eid)

    # M7.A.5.47b: Build micro_refinement lookup from bridge for priority ordering.
    # Keys by actual_pair since hot events score different event_ids than cold.
    _micro_lookup: dict = {}
    if bridge:
        for mr in bridge.get("micro_refinement", []):
            _mr_pair = mr.get("actual_pair")
            if _mr_pair:
                _micro_lookup[_mr_pair] = mr

    # M7.E1.4: Build convergence lookups from bridge for cold-hot cross-reference.
    _cold_exec_pool_set: set = set()
    _selected_pool_info: dict = {}  # pool_address -> {bucket, family}
    _ptt_intents: dict = {}
    if bridge:
        for _ce in bridge.get("cold_executable", []):
            _ce_pa = (_ce.get("pool_address") or "").lower()
            if _ce_pa:
                _cold_exec_pool_set.add(_ce_pa)
        for _sp in bridge.get("bridge_selected_pools_top", []):
            _sp_pa = (_sp.get("pool_address") or "").lower()
            if _sp_pa:
                _selected_pool_info[_sp_pa] = {
                    "bucket": _sp.get("bucket"),
                    "family": _sp.get("family"),
                }
        _ptt_intents = bridge.get("pool_token_transport", {})

    for r in _fast:
        eid = getattr(r, "event_id", None)
        net = getattr(r, "best_backrun_net_bps", None) or 0
        _pair = getattr(r, "actual_pair", None)
        _mr = _micro_lookup.get(_pair, {})
        # M7.E1.4: Extract pool_address from source event for convergence
        _evt_src = getattr(r, "_source_event", None)
        _pool_addr = (getattr(_evt_src, "pool_address", "") or "").lower() if _evt_src else ""
        # Derive family from PTT or bridge_selected_pools_top
        _sel = _selected_pool_info.get(_pool_addr, {})
        _family_raw = _sel.get("family")
        if not _family_raw and _pool_addr and _ptt_intents:
            _ptt_info = _ptt_intents.get(_pool_addr)
            if _ptt_info and len(_ptt_info) >= 2:
                _family_raw = f"{_ptt_info[0]}/{_ptt_info[1]}"
        rows.append({
            "event_id": eid,
            "actual_pair": _pair,
            "net_bps": round(net, 4) if net else 0,
            "profit_guard_passed": getattr(r, "profit_guard_passed", False),
            "guard_passed_in_hot": eid in _guard_event_ids,
            "scoring_path": getattr(r, "scoring_path", None),
            "pipeline_latency_ms": getattr(r, "quote_pipeline_latency_ms", None),
            "route_viable": getattr(r, "route_viable", False),
            # M7.E1.4: Convergence fields for cold-hot cross-reference
            "pool_address": _pool_addr or None,
            "family": _family_raw,
            "selected_bucket": _sel.get("bucket"),
            "same_pool_as_cold_exec": _pool_addr in _cold_exec_pool_set if _pool_addr else False,
            # M7.A.5.47b: Submit-size refinement from cold bridge
            "cold_verified_net_bps": _mr.get("verified_net_bps_after_refinement"),
            "cold_best_submit_size": _mr.get("best_submit_size"),
            "cold_gas_floor_gap_bps": _mr.get("gas_floor_gap_bps"),
            # M7.E1.5: Submit-stage placeholders (populated when sim infra exists)
            "sim_passed": None,
            "submit_ready": None,
        })

    # Sort by cold_verified_net_bps (cold-verified first), then net_bps descending
    rows.sort(
        key=lambda x: (
            x.get("cold_verified_net_bps") or -9999,
            x.get("net_bps", 0),
        ),
        reverse=True,
    )

    # Compute funnel counts for hot lane
    _hot_scored = len(_fast)
    _hot_positive = sum(1 for x in rows if x.get("net_bps", 0) > 0)
    _guard_passed = sum(1 for x in rows if x.get("guard_passed_in_hot"))

    # M7.A.5.46: cold_executable_positive comes from bridge, not synthesized from hot.
    _bridge_cold_exec_count = len(bridge.get("cold_executable", [])) if bridge else 0
    headline_level = _compute_headline_level({
        "diagnostic_positive": _hot_positive,
        "cold_executable_positive": _bridge_cold_exec_count,
        "hot_scored": _hot_scored,
        "profit_guard_passed": _guard_passed,
        "realized_onchain_profit": 0,
    })

    payload = {
        "timestamp": ts,
        "chain": chain,
        "loop_iteration": iteration,
        # M7.E1.6.1: Heartbeat — always-fresh timestamp for reviewer
        "current_window_timestamp": ts,
        "headline_level": headline_level,
        "hot_scored_count": _hot_scored,
        "hot_positive_count": _hot_positive,
        "profit_guard_passed_count": _guard_passed,
        "cold_executable_pool_count": len(bridge.get("cold_executable", [])) if bridge else 0,
        "intents": rows[:20],  # Cap at 20 rows
        # M7.E1.8.1: run_context for full provenance (chain + run_timestamp)
        "run_context": {
            "run_timestamp": ts,
            "chain": chain,
            "code_sha": None,
            "code_dirty": None,
            "code_desc": None,
            "evidence_sha": None,
        },
    }

    try:
        _atomic_json_write(_HOT_INTENTS_PATH, payload, indent=2, default=str)
        logger.info(
            "Hot intents written: scored=%d positive=%d guard_passed=%d headline=%s",
            _hot_scored, _hot_positive, _guard_passed, headline_level,
        )
    except Exception as exc:
        logger.warning("Failed to write hot intents: %s", str(exc)[:120])


def _update_hot_rollup(
    events_count: int,
    fast_results: list | None,
    guard_results: list | None,
    bridge_diagnostics: dict | None,
    ws_live_stats: dict | None = None,
    hot_active_pools: dict | None = None,
    bridge: dict | None = None,
    chain: str = "arbitrum_one",
) -> None:
    """Update cumulative hot rollup artifact — survives across windows.

    M7.A.5.47: The latest-window hot artifact masks progress because
    empty windows reset counters to zero. The rollup accumulates totals
    across ALL hot windows in the session, giving visibility into
    whether any hot-scored or profit-guard-passed events occurred.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Read existing rollup (or start fresh)
    rollup: dict = {}
    try:
        if os.path.exists(_HOT_ROLLUP_PATH):
            with open(_HOT_ROLLUP_PATH, "r", encoding="utf-8") as f:
                rollup = json.load(f)
    except Exception:
        rollup = {}

    # Increment counters
    _bd = bridge_diagnostics or {}
    _fast = fast_results or []
    _guard = guard_results or []

    rollup["last_updated"] = ts
    # M7.E1.8: Chain provenance — always present in rolling artifacts
    rollup["chain"] = chain
    # M7.E1.6.1: Heartbeat — always-fresh timestamp for reviewer
    rollup["current_window_timestamp"] = ts
    # M7.E1.7: Complete heartbeat contract — same fields as cold lane
    rollup["snapshot_run_timestamp"] = ts
    # M7.A.5.47e: Track first window timestamp for dashboard
    rollup.setdefault("first_window_at", ts)
    rollup["windows_seen"] = rollup.get("windows_seen", 0) + 1
    rollup["events_seen_total"] = rollup.get("events_seen_total", 0) + events_count

    # M7.E1.8: Error counters — track heartbeat-on-error windows vs normal
    _is_error_window = (events_count == 0 and fast_results is None and guard_results is None
                        and bridge_diagnostics is None and ws_live_stats is None)
    _er = rollup.get("error_counts") or {}
    _er["heartbeat_on_error_windows"] = _er.get("heartbeat_on_error_windows", 0) + (1 if _is_error_window else 0)
    _er["normal_windows"] = _er.get("normal_windows", 0) + (0 if _is_error_window else 1)
    rollup["error_counts"] = _er

    # M7.A.5.47k: Session-scoped counters — reset each supervisor start.
    # Uses _SESSION_ID (generated at import time) to detect new sessions.
    _prev_sid = rollup.get("session", {}).get("session_id", "")
    if _prev_sid != _SESSION_ID:
        rollup["session"] = {"session_id": _SESSION_ID, "session_started_at": ts}
    _sess = rollup["session"]
    _sess["session_windows_seen"] = _sess.get("session_windows_seen", 0) + 1
    _sess["session_events_seen_total"] = (
        _sess.get("session_events_seen_total", 0) + events_count
    )
    _sess["session_bridge_pool_hit_total"] = (
        _sess.get("session_bridge_pool_hit_total", 0)
        + _bd.get("bridge_pool_address_hit_count", 0)
    )
    _sess["session_fast_path_scored_total"] = (
        _sess.get("session_fast_path_scored_total", 0) + len(_fast)
    )
    # M7.E1.10: Track WS connection failures in session
    _ws_status = (ws_live_stats or {}).get("ws_connection_status", "unknown")
    _sess["session_ws_connected_windows"] = (
        _sess.get("session_ws_connected_windows", 0)
        + (1 if _ws_status == "connected" else 0)
    )
    _sess["session_ws_failed_windows"] = (
        _sess.get("session_ws_failed_windows", 0)
        + (1 if _ws_status.startswith("failed") else 0)
    )
    _sess["last_ws_connection_status"] = _ws_status
    rollup["bridge_loaded_candidate_count_total"] = (
        rollup.get("bridge_loaded_candidate_count_total", 0)
        + _bd.get("bridge_loaded_candidate_count", 0)
    )
    rollup["pool_address_match_count_total"] = (
        rollup.get("pool_address_match_count_total", 0)
        + _bd.get("pool_address_match_count", 0)
    )
    rollup["bridge_pool_address_hit_count_total"] = (
        rollup.get("bridge_pool_address_hit_count_total", 0)
        + _bd.get("bridge_pool_address_hit_count", 0)
    )
    rollup["fast_path_scored_total"] = (
        rollup.get("fast_path_scored_total", 0) + len(_fast)
    )
    rollup["fast_path_positive_total"] = (
        rollup.get("fast_path_positive_total", 0)
        + sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0)
    )
    # M7.E1.5: route_viable_total — route-level economics check (gas < gross, fee < gross, net > 0)
    rollup["route_viable_total"] = (
        rollup.get("route_viable_total", 0)
        + sum(1 for r in _fast if getattr(r, "route_viable", False))
    )
    # M7.E1.5: profit_guard_passed_total — from _fast inline attribute (gated on route_viable in scoring)
    rollup["profit_guard_passed_total"] = (
        rollup.get("profit_guard_passed_total", 0)
        + sum(1 for r in _fast if getattr(r, "profit_guard_passed", False))
    )
    # M7.E1.5: Submit-stage placeholder counters (populated when sim infra exists)
    rollup.setdefault("sim_attempted_total", 0)
    rollup.setdefault("sim_passed_total", 0)
    rollup.setdefault("submit_ready_total", 0)
    # M7.A.5.47: 6 canonical hot miss counters (cumulative)
    rollup["bridge_candidate_loaded_total"] = (
        rollup.get("bridge_candidate_loaded_total", 0)
        + _bd.get("bridge_loaded_candidate_count", 0)
    )
    rollup["bridge_pool_hit_total"] = (
        rollup.get("bridge_pool_hit_total", 0)
        + _bd.get("bridge_pool_address_hit_count", 0)
    )
    rollup["bridge_pair_hit_total"] = (
        rollup.get("bridge_pair_hit_total", 0)
        + _bd.get("bridge_pair_hit_count", 0)
    )
    rollup["registry_hit_for_event_pool_total"] = (
        rollup.get("registry_hit_for_event_pool_total", 0)
        + _bd.get("pool_address_match_count", 0)
    )
    # M7.A.5.47e: admitted = events that entered pipeline (not hot_skip)
    _hot_skip_in_window = sum(
        1 for r in _fast
        if getattr(r, "scoring_path", None) == "hot_skip"
    )
    _admitted_in_window = events_count - _hot_skip_in_window
    rollup["fast_score_attempted_total"] = (
        rollup.get("fast_score_attempted_total", 0) + _admitted_in_window
    )
    rollup["fast_score_rejected_economics_total"] = (
        rollup.get("fast_score_rejected_economics_total", 0)
        + sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) <= 0)
    )

    # M7.A.5.47b: 4 new temporal/diagnostic rollup counters
    _wls = ws_live_stats or {}
    if events_count > 0:
        rollup["windows_with_events"] = rollup.get("windows_with_events", 0) + 1
    else:
        rollup.setdefault("windows_with_events", 0)
    if _bd.get("bridge_pool_address_hit_count", 0) > 0:
        rollup["windows_with_bridge_hits"] = rollup.get("windows_with_bridge_hits", 0) + 1
    else:
        rollup.setdefault("windows_with_bridge_hits", 0)
    if len(_fast) > 0:
        rollup["windows_with_fast_scores"] = rollup.get("windows_with_fast_scores", 0) + 1
    else:
        rollup.setdefault("windows_with_fast_scores", 0)
    rollup["broad_fallback_events_total"] = (
        rollup.get("broad_fallback_events_total", 0)
        + _wls.get("broad_logs", 0)
    )
    # M7.A.5.47c: Cumulative bridge_pool_hit_but_registry_miss
    rollup["bridge_pool_hit_but_registry_miss_total"] = (
        rollup.get("bridge_pool_hit_but_registry_miss_total", 0)
        + _bd.get("bridge_pool_hit_but_registry_miss", 0)
    )
    # M7.A.5.47j: Snapshot of focused bridge size (last window value)
    rollup["bridge_focused_pool_count_last"] = _bd.get("bridge_focused_pool_count", 0)

    # M7.A.5.47c: Hot-seen pool histogram (cumulative top 10)
    # Shows which pools are ACTUALLY active on-chain in hot windows
    if hot_active_pools:
        _hap_sorted = sorted(
            hot_active_pools.items(),
            key=lambda x: x[1].get("event_count", 0),
            reverse=True,
        )[:10]
        rollup["hot_seen_pool_histogram_top"] = [
            {"pool": pa, "count": info["event_count"], "last_iter": info.get("last_iter", 0)}
            for pa, info in _hap_sorted
        ]
    else:
        rollup.setdefault("hot_seen_pool_histogram_top", [])

    # M7.A.5.47d: Hot-seen unresolved/resolved tracking from bridge
    _br = bridge or {}
    _hu_pools = _br.get("hot_seen_unresolved_pools", [])
    _hu_unresolved = sum(1 for p in _hu_pools if isinstance(p, dict) and not p.get("resolved", False))
    _hu_resolved = sum(1 for p in _hu_pools if isinstance(p, dict) and p.get("resolved", False))
    # These are point-in-time snapshots from the latest bridge write
    rollup["hot_seen_unresolved_pool_count"] = _hu_unresolved
    rollup["resolved_from_hot_seen_count"] = _hu_resolved
    # Also track cumulative max for trending
    rollup["hot_seen_unresolved_pool_count_max"] = max(
        rollup.get("hot_seen_unresolved_pool_count_max", 0), _hu_unresolved
    )

    # M7.A.5.47e: Per-window classification (mutually exclusive).
    # Each window falls into exactly ONE miss category. Rollup tracks
    # per-category window counts, then dominant = max by window count.
    _window_class = "none"
    if events_count == 0:
        _window_class = "no_events_in_window"
    elif _bd.get("bridge_pool_address_hit_count", 0) == 0:
        _window_class = "events_but_no_bridge_hit"
    elif len(_fast) == 0:
        _window_class = "bridge_hit_but_not_scored"
    elif sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0) == 0:
        _window_class = "scored_but_rejected_economics"
    elif len(_guard) == 0:
        _window_class = "positive_but_no_guard_pass"
    else:
        _window_class = "guard_passed"

    # Accumulate per-class window counts
    rollup.setdefault("window_miss_classes", {})
    rollup["window_miss_classes"][_window_class] = (
        rollup["window_miss_classes"].get(_window_class, 0) + 1
    )
    # Dominant = class with most windows (excluding guard_passed)
    _miss_only = {
        k: v for k, v in rollup["window_miss_classes"].items()
        if k != "guard_passed"
    }
    rollup["dominant_hot_miss_reason"] = (
        max(_miss_only, key=_miss_only.get) if _miss_only else "none"
    )

    # M7.A.5.47m: Provenance — run_context with run_timestamp
    rollup["run_context"] = {
        "run_timestamp": ts,
        "chain": chain,
        "code_sha": None,
        "code_dirty": None,
        "code_desc": None,
        "evidence_sha": None,
    }

    # M7.A.5.47m: Flatten session fields to top level for easy access.
    # Session dict remains as canonical source; top-level keys are aliases.
    for _sk in ("session_id", "session_started_at", "session_windows_seen",
                "session_events_seen_total", "session_bridge_pool_hit_total",
                "session_fast_path_scored_total",
                "session_ws_connected_windows", "session_ws_failed_windows",
                "last_ws_connection_status"):
        rollup[_sk] = _sess.get(_sk)

    # M7.E1.3: Event-to-bridge classification counters (chain-agnostic).
    # For each event in _fast, classify whether its pool is in the bridge set,
    # and if matched, separate registry rejection from gas rejection.
    _bridge_addrs_set = _bd.get("_bridge_pool_addrs_set", set())
    _ptt_rollup = _bd.get("_ptt", {})
    _events_in_bridge_window = 0
    _events_not_in_bridge_window = 0
    _matched_registry_rejected_window = 0
    _matched_gas_rejected_window = 0
    _matched_scored_positive_window = 0
    # Also build per-family event map for architecture_blocker_trace
    _family_event_counts: dict = {}  # family_str -> event_count
    for _r in _fast:
        _evt = getattr(_r, "_source_event", None)
        if not _evt:
            continue
        _ep = getattr(_evt, "pool_address", "").lower()
        _in_bridge = _ep in _bridge_addrs_set
        if _in_bridge:
            _events_in_bridge_window += 1
            if getattr(_r, "scoring_path", None) == "hot_skip":
                _matched_registry_rejected_window += 1  # in bridge but not in hot registry
            elif (getattr(_r, "best_backrun_net_bps", None) or 0) <= 0:
                _matched_gas_rejected_window += 1  # passed registry, gas-killed
            else:
                _matched_scored_positive_window += 1
        else:
            _events_not_in_bridge_window += 1
        # Map event pool to family for architecture blocker trace
        _evt_info = _ptt_rollup.get(_ep)
        if _evt_info and len(_evt_info) >= 2:
            _evt_fam = f"{_evt_info[0]}/{_evt_info[1]}"
            _family_event_counts[_evt_fam] = _family_event_counts.get(_evt_fam, 0) + 1
    # Accumulate into rollup
    rollup["events_in_bridge_total"] = (
        rollup.get("events_in_bridge_total", 0) + _events_in_bridge_window
    )
    rollup["events_not_in_bridge_total"] = (
        rollup.get("events_not_in_bridge_total", 0) + _events_not_in_bridge_window
    )
    rollup["matched_then_registry_rejected_total"] = (
        rollup.get("matched_then_registry_rejected_total", 0) + _matched_registry_rejected_window
    )
    rollup["matched_then_gas_rejected_total"] = (
        rollup.get("matched_then_gas_rejected_total", 0) + _matched_gas_rejected_window
    )
    rollup["matched_then_scored_positive_total"] = (
        rollup.get("matched_then_scored_positive_total", 0) + _matched_scored_positive_window
    )

    # M7.E1.2: Chain-aware target pool selection — pick first A_cold_exec
    # pool from bridge_selected_at_assembly instead of hardcoded Arbitrum pool.
    _bsa = _bd.get("bridge_selected_at_assembly", [])
    _TARGET_POOL = None
    for _sel in _bsa:
        if _sel.get("bucket") == "A_cold_exec" and _sel.get("pool_address"):
            _TARGET_POOL = _sel["pool_address"].lower()
            break
    if _TARGET_POOL is None:
        for _sel in _bsa:
            if _sel.get("pool_address"):
                _TARGET_POOL = _sel["pool_address"].lower()
                break

    # M7.A.5.47n: Exact-pool session trace — per-window tracking for target
    # cold-executable pool. Answers: is the pool consistently in bridge?
    # Did any hot event arrive at this exact pool across the session?
    _ept = rollup.get("exact_pool_trace", {})
    if _TARGET_POOL is None:
        _ept = {"pool_address": None, "reason_if_not_hit": "no_bridge_data"}
    else:
        # M7.A.5.47o: Reset exact_pool_trace on session/target change.
        if _ept.get("pool_address") != _TARGET_POOL or _prev_sid != _SESSION_ID:
            _ept = {
                "pool_address": _TARGET_POOL,
                "session_windows_seen": 0,
                "session_windows_in_bridge": 0,
                "session_hot_events_seen": 0,
                "session_fast_attempted": 0,
                "session_fast_scored": 0,
                "in_bridge_every_window": True,
                "last_seen_window": None,
                "reason_if_not_hit": None,
            }
        _ept["session_windows_seen"] = _ept.get("session_windows_seen", 0) + 1
        _target_in_bridge = _TARGET_POOL in _bridge_addrs_set
        if _target_in_bridge:
            _ept["session_windows_in_bridge"] = _ept.get("session_windows_in_bridge", 0) + 1
        else:
            _ept["in_bridge_every_window"] = False
        _target_hot_events = 0
        _target_fast_attempted = 0
        _target_fast_scored = 0
        for _r in _fast:
            _evt = getattr(_r, "_source_event", None)
            if _evt and getattr(_evt, "pool_address", "").lower() == _TARGET_POOL:
                _target_hot_events += 1
                if getattr(_r, "scoring_path", None) != "hot_skip":
                    _target_fast_attempted += 1
                    if (getattr(_r, "best_backrun_net_bps", None) or 0) != 0:
                        _target_fast_scored += 1
        _ept["session_hot_events_seen"] = _ept.get("session_hot_events_seen", 0) + _target_hot_events
        _ept["session_fast_attempted"] = _ept.get("session_fast_attempted", 0) + _target_fast_attempted
        _ept["session_fast_scored"] = _ept.get("session_fast_scored", 0) + _target_fast_scored
        if _target_hot_events > 0:
            _ept["last_seen_window"] = ts
        if not _target_in_bridge:
            _ept["reason_if_not_hit"] = "not_in_bridge"
        elif _target_hot_events == 0:
            _ept["reason_if_not_hit"] = "no_hot_events_at_pool"
        elif _target_fast_attempted == 0:
            _ept["reason_if_not_hit"] = "hot_skip_no_scoring"
        elif _target_fast_scored == 0:
            _ept["reason_if_not_hit"] = "scored_but_no_result"
        else:
            _ept["reason_if_not_hit"] = None
    rollup["exact_pool_trace"] = _ept

    # M7.A.5.47q: exact_family_trace — family-level session trace.
    _target_info = _ptt_rollup.get(_TARGET_POOL) if _TARGET_POOL else None
    _target_family = (
        f"{_target_info[0]}/{_target_info[1]}"
        if _target_info and len(_target_info) >= 2
        else "family_unresolved"
    )
    _eft = rollup.get("exact_family_trace", {})
    if _eft.get("family") != _target_family or _prev_sid != _SESSION_ID:
        _eft = {
            "family": _target_family,
            "selected_pools": [],
            "session_family_events_seen": 0,
            "session_exact_pool_events_seen": 0,
            "reason_if_no_exact_hit": None,
        }
    _sibling_pools_this_window: list = []
    for _sel in _bsa:
        _sp_fam = _sel.get("family", "")
        if _sp_fam == _target_family or (
            _target_info and _sp_fam and _target_info[0] in _sp_fam and _target_info[1] in _sp_fam
        ):
            _sp_pa = (_sel.get("pool_address") or "").lower()
            if _sp_pa and _sp_pa not in _eft.get("selected_pools", []):
                _eft.setdefault("selected_pools", []).append(_sp_pa)
            _sibling_pools_this_window.append(_sp_pa)
    _family_events_this_window = 0
    _exact_events_this_window = 0
    if _TARGET_POOL:
        for _r in _fast:
            _evt = getattr(_r, "_source_event", None)
            if not _evt:
                continue
            _ep = getattr(_evt, "pool_address", "").lower()
            if _ep == _TARGET_POOL:
                _exact_events_this_window += 1
                _family_events_this_window += 1
            elif _ep in _sibling_pools_this_window:
                _family_events_this_window += 1
    _eft["session_family_events_seen"] = (
        _eft.get("session_family_events_seen", 0) + _family_events_this_window
    )
    _eft["session_exact_pool_events_seen"] = (
        _eft.get("session_exact_pool_events_seen", 0) + _exact_events_this_window
    )
    if _family_events_this_window == 0 and _exact_events_this_window == 0:
        _eft["reason_if_no_exact_hit"] = "no_events_at_any_family_pool"
    elif _family_events_this_window > 0 and _exact_events_this_window == 0:
        _eft["reason_if_no_exact_hit"] = "events_at_sibling_not_exact_pool"
    else:
        _eft["reason_if_no_exact_hit"] = None
    _eft["selected_pools"] = _eft.get("selected_pools", [])[:20]
    rollup["exact_family_trace"] = _eft

    # M7.E1.2: architecture_blocker_trace — canonical session summary.
    # Fixed: families_with_any_hot_events now checks ALL bridge families
    # against the per-family event map, not just the single target family.
    _abt = rollup.get("architecture_blocker_trace", {})
    if _prev_sid != _SESSION_ID:
        _abt = {}
    _abt["session_windows_seen"] = _sess.get("session_windows_seen", 0)
    _abt["session_events_seen_total"] = _sess.get("session_events_seen_total", 0)
    _bsa_for_abt = _bsa
    _abt_families = set()
    for _s_abt in _bsa_for_abt:
        _sf_abt = _s_abt.get("family", "")
        if _sf_abt and _sf_abt != "family_unresolved":
            _abt_families.add(_sf_abt)
    _abt["families_selected_count"] = len(_abt_families)
    # M7.E1.2: Count families with ANY hot events across ALL bridge families
    _families_hit_this_window = sum(
        1 for fam in _abt_families if _family_event_counts.get(fam, 0) > 0
    )
    _abt["families_with_any_hot_events"] = (
        _abt.get("families_with_any_hot_events", 0) + _families_hit_this_window
    )
    _abt["families_with_exact_hits"] = (
        1 if _eft.get("session_exact_pool_events_seen", 0) > 0 else 0
    )
    # M7.E1.2: Three-way blocker classification:
    # - event_source_absence: no events at ANY bridge family (not just target)
    # - gas_economics_only: events arrive but all gas-rejected (no registry/overlap issue)
    # - selection_or_scoring: events arrive but hit/scoring pipeline blocks them
    _total_events_session = _sess.get("session_events_seen_total", 0)
    _total_bridge_hits_session = _sess.get("session_bridge_pool_hit_total", 0)
    _events_in_bridge_session = rollup.get("events_in_bridge_total", 0)
    if _total_events_session == 0:
        _abt["blocker_class"] = "event_source_absence"
    elif _events_in_bridge_session == 0 and _total_bridge_hits_session == 0:
        _abt["blocker_class"] = "events_not_reaching_bridge"
    elif rollup.get("matched_then_scored_positive_total", 0) > 0:
        _abt["blocker_class"] = "selection_or_scoring"
    else:
        _abt["blocker_class"] = "gas_economics_only"
    rollup["architecture_blocker_trace"] = _abt

    try:
        _atomic_json_write(_HOT_ROLLUP_PATH, rollup, indent=2, default=str)
    except Exception as exc:
        logger.debug("Failed to write hot rollup: %s", str(exc)[:80])


def run_loop(cli_args) -> None:
    """Run the continuous ws-live loop."""
    _apply_lane_defaults(cli_args)
    ws_args = _build_ws_args(cli_args)
    iterations = cli_args.iterations
    pause = cli_args.pause
    lane = cli_args.lane
    profile = getattr(cli_args, "profile", "production")
    _init_artifact_paths(profile)  # M7.E1.9.1: namespace isolation
    infinite = iterations == 0

    # M7.E1.9: Build seed pairs from profile-aware prewarm list.
    # Discovery profile gets wider contour; production uses HOT_WATCHLIST_PAIRS.
    _seed_pairs = get_prewarm_pairs(cli_args.chain, profile)

    # M7.A.5.31: Hot lane maintains cross-iteration state
    _accumulated_pairs: dict = {}  # pair_key -> session_low_lag_pairs info
    _hot_registry = None  # lazy-init on first hot iteration

    # M7.A.5.35/M7.A.5.39: Cross-iteration cold stats for two-level promotion
    _cold_pair_stats: dict = {}   # pair_key -> promotion stats from cold results
    _promoted_pairs: dict = {"candidate": [], "execution": []}  # two-level promotion

    # M7.A.5.47: Track pool addresses seen in cold events — used to rank
    # bridge pools by actual activity (pools with no recent events are
    # deprioritized in the hot address filter).
    _cold_active_pools: dict = {}  # pool_address_lower -> {"event_count": N, "last_iter": M}

    # M7.A.5.47c: Track pool addresses seen in hot events — used to:
    # 1) Build hot_seen_pool_histogram_top for rollup diagnosis
    # 2) Feed back into bridge ranking (hot-seen pools are likely active)
    _hot_active_pools: dict = {}  # pool_address_lower -> {"event_count": N, "last_iter": M}

    # M7.A.5.47d: Track cumulative resolved-from-hot-seen count
    _resolved_from_hot_seen_total: int = 0

    # M7.A.5.47g: TTL-pinned stale-positive pools — kept in hot bridge filter
    # for consecutive windows to maximize chance of catching same-block event.
    # {pool_address_lower: {"ttl": int, "pair": str}}
    _stale_pin_ttl: dict = {}
    _STALE_PIN_TTL_INIT = 4  # pin for 4 hot windows after detection

    # M7.A.5.47h: TTL-pinned hot-seen resolved pools — when a pool that was
    # seen in hot events gets resolved (added to PTT), it's pinned into the
    # focused bridge for 3 iterations to maximize its chance of scoring.
    # {pool_address_lower: {"ttl": int, "last_iter": int}}
    _hot_seen_pin: dict = {}
    _HOT_SEEN_PIN_TTL_INIT = 3  # pin for 3 hot windows after resolution

    # M7.A.5.37: Persistent cold registry — survives across cold iterations
    # Passed via warm_registry to avoid hot-mode trigger. Caches pool data
    # so registry_preload_ms drops to near-zero for already-queried pairs.
    _cold_registry = None  # lazy-init on first cold iteration

    iteration = 0
    logger.info(
        "M7 %s loop starting: chain=%s profile=%s ws_blocks=%d timeout=%ds max_events=%d "
        "iterations=%s pause=%ds seed_pairs=%d",
        lane.upper(), cli_args.chain, profile, cli_args.ws_blocks, cli_args.ws_timeout,
        cli_args.max_events, "infinite" if infinite else iterations, pause,
        len(_seed_pairs),
    )

    while infinite or iteration < iterations:
        iteration += 1
        window_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "=== M7 %s loop iteration %d started at %s ===",
            lane.upper(), iteration, window_started_at,
        )

        try:
            # M7.A.5.39: Lane-specific registry init + prewarm
            _ext_registry = None
            if lane == "hot":
                if _hot_registry is None:
                    from m7.orderflow.pool_registry import PoolRegistry
                    _hot_registry = PoolRegistry()
                _ext_registry = _hot_registry

                # M7.A.5.43: Bridge-first hot prewarm.
                # 1. Read cold→hot bridge (pool_token_transport + candidates)
                # 2. Populate _pool_token_cache from bridge (cross-process cache fix)
                # 3. Prewarm registry from bridge token addresses (pool-address-first)
                # 4. Fall back to symbol-pair prewarm for seeds / accumulated pairs
                _bridge = _read_cold_hot_bridge()
                _bridge_cache_count = _populate_pool_token_cache_from_bridge(_bridge)
                _bridge_prewarm_count = 0

                # M7.A.5.45: Build execution queue — cold_executable pool addresses
                # get priority prewarm so hot lane scores them first.
                _cold_exec_pools: set = set()
                for _ce in _bridge.get("cold_executable", []):
                    _pa = _ce.get("pool_address", "") if isinstance(_ce, dict) else ""
                    if _pa:
                        _cold_exec_pools.add(_pa.lower())
                for _ne in _bridge.get("near_executable", []):
                    _pa = _ne.get("pool_address", "") if isinstance(_ne, dict) else ""
                    if _pa:
                        _cold_exec_pools.add(_pa.lower())

                _hot_pairs_to_prewarm: dict = {}
                # 1. Seed defaults on first iteration (profile-aware)
                if iteration == 1:
                    for sym_a, sym_b in _seed_pairs:
                        pk = f"{sym_a}/{sym_b}"
                        _hot_pairs_to_prewarm[pk] = {"pair": pk, "seen_count": 0}
                # 2. Add accumulated hot pairs from prior hot iterations
                for pk, info in _accumulated_pairs.items():
                    if pk not in _hot_pairs_to_prewarm:
                        _hot_pairs_to_prewarm[pk] = info
                # 3. Read candidate-promoted pairs from cold lane (cross-process)
                _cross_promoted = _read_promoted_pairs()
                for ppair in _cross_promoted.get("candidate", []):
                    if ppair not in _hot_pairs_to_prewarm:
                        _hot_pairs_to_prewarm[ppair] = {"pair": ppair, "seen_count": 0}
                # M7.A.5.40: Update _promoted_pairs for hot artifact reporting
                if _cross_promoted.get("candidate") or _cross_promoted.get("execution"):
                    _promoted_pairs = _cross_promoted

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

                        # M7.A.5.45: Bridge-first prewarm with cold_executable priority
                        if _bridge.get("pool_token_transport"):
                            _bridge_prewarm_count = _prewarm_registry_from_bridge(
                                _hot_registry, _bridge, _dex_cfg, _rpc, _block,
                                priority_pools=_cold_exec_pools,
                            )

                        # Legacy symbol-pair prewarm for seeds and accumulated pairs
                        if _hot_pairs_to_prewarm:
                            _pw = _prewarm_registry_from_pairs(
                                _hot_registry, _hot_pairs_to_prewarm,
                                _token_addr, _dex_cfg, _rpc, _block,
                            )
                        else:
                            _pw = 0
                        logger.info(
                            "Hot prewarm: bridge_cache=%d bridge_registry=%d "
                            "symbol_pairs=%d/%d (iter %d, cross=%d)",
                            _bridge_cache_count, _bridge_prewarm_count,
                            _pw, len(_hot_pairs_to_prewarm), iteration,
                            len(_cross_promoted.get("candidate", [])),
                        )
                except Exception as _pw_exc:
                    logger.debug("Hot prewarm failed: %s", str(_pw_exc)[:120])
            elif lane == "cold":
                # M7.A.5.38: Lazy-init persistent cold registry with wide stale
                # threshold (5000 blocks ≈ 20 min). Cold lane is diagnostic, not
                # execution — stale pool state is acceptable and avoids
                # per-event AND per-iteration RPC refresh that dominated
                # registry_preload_ms (~300ms).
                if _cold_registry is None:
                    from m7.orderflow.pool_registry import PoolRegistry
                    _cold_registry = PoolRegistry(stale_threshold_blocks=5000)
                # M7.A.5.39: Cold lane must NOT trigger hot mode.
                # external_registry=None → _hot_mode=False in run_ws_live.
                # Cold lane uses warm_registry param instead.
                _ext_registry = None

                # M7.A.5.35: Prewarm from promoted watchlist (cold→hot promotion)
                # + accumulated session pairs + seed HOT_WATCHLIST_PAIRS on iter 1
                _pairs_to_prewarm = dict(_accumulated_pairs) if _accumulated_pairs else {}

                # M7.A.5.39: Add candidate-promoted pairs (wider set) for prewarm
                for ppair in _promoted_pairs.get("candidate", []):
                    if ppair not in _pairs_to_prewarm:
                        _pairs_to_prewarm[ppair] = {"pair": ppair, "seen_count": 0}

                # Seed defaults on first iteration only (profile-aware)
                if iteration == 1:
                    for sym_a, sym_b in _seed_pairs:
                        pk = f"{sym_a}/{sym_b}"
                        if pk not in _pairs_to_prewarm:
                            _pairs_to_prewarm[pk] = {"pair": pk, "seen_count": 0}

                if _pairs_to_prewarm:
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
                                _cold_registry, _pairs_to_prewarm,
                                _token_addr, _dex_cfg, _rpc, _block,
                            )
                            logger.info(
                                "Cold prewarm: %d pairs from %d candidates (iter %d)",
                                _pw, len(_pairs_to_prewarm), iteration,
                            )
                    except Exception as _pw_exc:
                        logger.debug("Hot prewarm failed: %s", str(_pw_exc)[:120])

                # M7.A.5.47d: Priority resolve hot-seen unresolved pools.
                # Hot lane discovers active pools via broad fallback but can't
                # score them because they're not in _pool_token_cache. Cold lane
                # reads that backlog from the bridge and also from the hot rollup
                # artifact (cross-process file), then resolves them so they
                # appear in the next bridge write's pool_token_transport.
                _hot_resolved_count = 0
                try:
                    _cold_bridge = _read_cold_hot_bridge()
                    _hu_pools = _cold_bridge.get("hot_seen_unresolved_pools", [])
                    _unresolved_addrs = [
                        p["pool_address"] for p in _hu_pools
                        if isinstance(p, dict) and not p.get("resolved", False)
                    ][:20]  # cap at 20 to limit RPC cost
                    # Also source hot-seen pools directly from hot rollup
                    # (cross-process) to avoid 1-iteration delay via bridge
                    if not _unresolved_addrs:
                        try:
                            if os.path.exists(_HOT_ROLLUP_PATH):
                                from m7.orderflow.resolve import _pool_token_cache as _ptc_check
                                with open(_HOT_ROLLUP_PATH, "r", encoding="utf-8") as _rrf:
                                    _rollup_check = json.load(_rrf)
                                for _rp in _rollup_check.get("hot_seen_pool_histogram_top", []):
                                    _rp_addr = (_rp.get("pool") or "").lower()
                                    if _rp_addr and _rp_addr not in _ptc_check:
                                        _unresolved_addrs.append(_rp_addr)
                                _unresolved_addrs = _unresolved_addrs[:20]
                        except Exception:
                            pass
                    if _unresolved_addrs:
                        from config import get_all_token_addresses
                        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
                        from m7.orderflow.resolve import (
                            batch_pre_resolve_pools,
                            _build_address_to_symbol,
                        )
                        _chain_id = _CHAIN_KEY_TO_ID.get(cli_args.chain.lower())
                        _rpc_hr, _, _ = resolve_rpc_http(
                            chain_id=_chain_id, network=cli_args.chain,
                            env=dict(os.environ),
                        )
                        if _rpc_hr:
                            from web3 import Web3 as _W3_hr
                            _block_hr = _W3_hr(_W3_hr.HTTPProvider(_rpc_hr)).eth.block_number
                            _ta_hr = get_all_token_addresses(cli_args.chain)
                            _ats_hr = _build_address_to_symbol(_ta_hr)
                            _pre = batch_pre_resolve_pools(
                                _unresolved_addrs, _rpc_hr, _block_hr, _ats_hr,
                            )
                            _hot_resolved_count = len(_pre)
                            if _hot_resolved_count > 0:
                                logger.info(
                                    "Cold hot-seen resolve: %d/%d pools resolved (iter %d)",
                                    _hot_resolved_count, len(_unresolved_addrs), iteration,
                                )
                                # M7.A.5.47h: Auto-pin resolved hot-seen pools
                                # into focused bridge for next 3 iterations.
                                for _resolved_pa in _pre:
                                    _rpa_low = _resolved_pa.lower()
                                    _hot_seen_pin[_rpa_low] = {
                                        "ttl": _HOT_SEEN_PIN_TTL_INIT,
                                        "last_iter": iteration,
                                    }
                except Exception as _hr_exc:
                    logger.debug("Cold hot-seen resolve failed: %s", str(_hr_exc)[:120])
                _resolved_from_hot_seen_total += _hot_resolved_count

            # M7.A.5.47d: Build focused bridge pool address set for hot lane.
            # 2-bucket policy:
            #   Bucket A: cold_executable + near_executable (always included)
            #   Bucket B: hot-seen pools (recently active on-chain) ranked by
            #             combined activity score, with auto-injection for
            #             resolved hot-seen pools
            # Remaining PTT pools fill up to the cap, ranked by activity.
            _bridge_pool_addrs: set | None = None
            # M7.E1.7: Initialize rollup counters before bridge try block
            # so they're always defined even if bridge assembly raises NameError.
            _rollup_wwe = 0
            _rollup_wwbh = 0
            if lane == "hot":
                try:
                    _ptt = _bridge.get("pool_token_transport", {})
                    if _ptt:
                        # Bucket A: cold_exec + near_exec (always included)
                        _bucket_a = set(_cold_exec_pools)  # already lowered

                        # Bucket B: hot-seen pools that are resolved (in PTT or _pool_token_cache)
                        _bucket_b: set = set()
                        _hot_injected = 0
                        try:
                            from m7.orderflow.resolve import _pool_token_cache as _ptc_inject
                            for _hpa in _hot_active_pools:
                                if _hpa in _ptc_inject or _hpa in _ptt:
                                    _bucket_b.add(_hpa)
                                    if _hpa not in _ptt:
                                        _hot_injected += 1
                        except Exception:
                            pass

                        # Also add hot-seen unresolved pools from bridge backlog
                        # that have since been resolved by cold lane
                        for _hu in _bridge.get("hot_seen_unresolved_pools", []):
                            _hu_pa = (_hu.get("pool_address") or "").lower()
                            if _hu_pa and _hu_pa in _ptt:
                                _bucket_b.add(_hu_pa)

                        # M7.A.5.47h: Include hot-seen-pin pools (auto-promoted
                        # from resolved hot-seen, TTL > 0) into bucket B.
                        for _hsp_pa, _hsp_info in _hot_seen_pin.items():
                            if _hsp_info.get("ttl", 0) > 0 and _hsp_pa in _ptt:
                                _bucket_b.add(_hsp_pa)

                        # Remaining: all PTT pools not yet in A or B
                        _remaining = set()
                        for _ptt_key in _ptt:
                            _pk = _ptt_key.lower()
                            if _pk not in _bucket_a and _pk not in _bucket_b:
                                _remaining.add(_pk)

                        # Rank remaining by combined activity score
                        def _activity_score(pa):
                            _ca = _cold_active_pools.get(pa, {}).get("event_count", 0)
                            _ha = _hot_active_pools.get(pa, {}).get("event_count", 0)
                            return _ca + _ha * 3

                        # M7.A.5.47d: Adaptive cap — expand to 100 when we have
                        # events but zero bridge hits (coverage gap)
                        _rollup_wwe = 0
                        _rollup_wwbh = 0
                        try:
                            if os.path.exists(_HOT_ROLLUP_PATH):
                                with open(_HOT_ROLLUP_PATH, "r", encoding="utf-8") as _rf:
                                    _rl = json.load(_rf)
                                _rollup_wwe = _rl.get("windows_with_events", 0)
                                _rollup_wwbh = _rl.get("windows_with_bridge_hits", 0)
                        except Exception:
                            pass
                        _pool_cap = 100 if (_rollup_wwe > 0 and _rollup_wwbh == 0) else 50
                        _remaining_ranked = sorted(
                            _remaining, key=_activity_score, reverse=True,
                        )

                        # M7.A.5.47k: C1 (stale_recovery): ONLY recoverable stale
                        #   with route_viable=true. Pools that are stale due to
                        #   pipeline abort (route_viable=false) go to diagnostic only.
                        #   Uses cold_recoverable_stale_route_viable (strict from artifacts.py).
                        #   + TTL-pinned pools from prior iterations.
                        # C2 (gas_near_survivor): near_executable with
                        #   GAS_EXCEEDS_GROSS AND positive gross. Gross-negative excluded.
                        # C3 (activity_fill): remaining PTT by activity score.
                        _ANOMALY_REJECTS = {"PRICING_ANOMALY", "TOKEN_PAIR_UNRESOLVED"}
                        _bucket_c1_stale: set = set()
                        for _sp in _bridge.get("cold_recoverable_stale_route_viable", []):
                            _sp_pa = (_sp.get("pool_address") or "").lower()
                            _sp_rr = _sp.get("reject_reason", "")
                            # Defense-in-depth: skip anomalies even if artifacts leaked them
                            if _sp_rr in _ANOMALY_REJECTS:
                                continue
                            # M7.A.5.47l: Skip stale candidates whose sub-reason
                            # is block_lag — these are not recoverable in current
                            # mode (lag 3..8). Only pipeline_abort / state_recheck
                            # (lag ≤ 2) are genuine recovery candidates.
                            if _sp.get("stale_sub_reason") == "block_lag":
                                continue
                            if _sp_pa and _sp_pa in _ptt and _sp_pa not in _bucket_a and _sp_pa not in _bucket_b:
                                _bucket_c1_stale.add(_sp_pa)
                                # Refresh TTL for freshly-seen recoverable stale pools
                                _stale_pin_ttl[_sp_pa] = {
                                    "ttl": _STALE_PIN_TTL_INIT,
                                    "pair": _sp.get("actual_pair", ""),
                                }
                        # Also include TTL-pinned stale pools from prior iterations
                        for _pin_pa, _pin_info in _stale_pin_ttl.items():
                            if _pin_pa in _ptt and _pin_pa not in _bucket_a and _pin_pa not in _bucket_b:
                                _bucket_c1_stale.add(_pin_pa)

                        _bucket_c2_gas_near: set = set()
                        # M7.A.5.47j: Tighten C2 — only near_executable pools
                        # whose family has positive verified_net OR gas_floor_gap
                        # within a very small tolerance. Families further away
                        # cannot cross zero at realistic sizes.
                        _C2_GAS_GAP_TOLERANCE_BPS = -5  # tightened from -10 in 47i
                        _gas_viable_families: set = set()
                        for _mr in _bridge.get("micro_refinement", []):
                            # Primary: verified net > 0 (definitely profitable family)
                            _v_net = _mr.get("verified_net_bps_after_refinement") or 0
                            if _v_net > 0:
                                _ap = (_mr.get("actual_pair") or "")
                                _parts = _ap.split("/")
                                if len(_parts) == 2:
                                    _gas_viable_families.add(
                                        tuple(sorted((_parts[0].lower(), _parts[1].lower())))
                                    )
                                continue
                            # Secondary: gas_floor_gap_bps within tolerance
                            # (slightly negative but close to breakeven)
                            _gfg = _mr.get("gas_floor_gap_bps")
                            if _gfg is not None and _gfg >= _C2_GAS_GAP_TOLERANCE_BPS:
                                _ap = (_mr.get("actual_pair") or "")
                                _parts = _ap.split("/")
                                if len(_parts) == 2:
                                    _gas_viable_families.add(
                                        tuple(sorted((_parts[0].lower(), _parts[1].lower())))
                                    )
                        for _ne in _bridge.get("near_executable", []):
                            _ne_pa = (_ne.get("pool_address") or "").lower()
                            _ne_rr = _ne.get("reject_reason", "")
                            if not (_ne_pa and _ne_rr == "GAS_EXCEEDS_GROSS"):
                                continue
                            if _ne_pa not in _ptt:
                                continue
                            if _ne_pa in _bucket_a or _ne_pa in _bucket_b or _ne_pa in _bucket_c1_stale:
                                continue
                            # Check gas-viable via pool family
                            _ne_info = _ptt.get(_ne_pa) or _ptt.get(_ne_pa.lower())
                            if _ne_info and len(_ne_info) >= 2:
                                _ne_fam = tuple(sorted((_ne_info[0].lower(), _ne_info[1].lower())))
                                if _ne_fam not in _gas_viable_families:
                                    continue  # gas-hopeless family → skip
                            else:
                                continue  # M7.A.5.47k: unknown family → skip (safe default)
                            _bucket_c2_gas_near.add(_ne_pa)

                        # Bucket C3: activity fill from remaining (exclude C1/C2)
                        _committed = _bucket_a | _bucket_b | _bucket_c1_stale | _bucket_c2_gas_near
                        _remaining_for_fill = [
                            pa for pa in _remaining_ranked
                            if pa not in _committed
                        ]

                        # M7.A.5.47o: Build gas-hopeless family set — families where
                        # ALL cold candidates are GAS_EXCEEDS_GROSS and mean_gas_gap
                        # below -5 bps. These families waste hot attention slots.
                        _C3_GAS_HOPELESS_BPS = -5
                        _family_gas_stats: dict = {}  # family -> {"gas_killed": int, "total": int, "worst_gap": float}
                        for _cand in _bridge.get("candidates", []):
                            _c_pa = (_cand.get("pool_address") or "").lower()
                            _c_fam = _pool_family(_c_pa) if _c_pa in _ptt else None
                            if _c_fam is None:
                                continue
                            _fgs = _family_gas_stats.setdefault(_c_fam, {"gas_killed": 0, "total": 0, "worst_gap": 0.0})
                            _fgs["total"] += 1
                            if _cand.get("reject_reason") == "GAS_EXCEEDS_GROSS":
                                _fgs["gas_killed"] += 1
                                _gfg = _cand.get("gas_floor_gap_bps")
                                if _gfg is not None:
                                    _fgs["worst_gap"] = min(_fgs["worst_gap"], _gfg)
                        _gas_hopeless_families: set = set()
                        for _ghf, _ghs in _family_gas_stats.items():
                            if (_ghs["total"] > 0
                                    and _ghs["gas_killed"] == _ghs["total"]
                                    and _ghs["worst_gap"] < _C3_GAS_HOPELESS_BPS
                                    and _ghf not in _gas_viable_families):
                                _gas_hopeless_families.add(_ghf)

                        # M7.A.5.47f: Diversity-aware fill — max _FAMILY_CAP pools
                        # per token-pair family to prevent one family from monopolizing
                        # the focused filter and cementing concentration.
                        _FAMILY_CAP = 8
                        def _pool_family(pa):
                            """Return normalized pair family for a pool (sorted tokens)."""
                            _info = _ptt.get(pa) or _ptt.get(pa.lower())
                            if _info and len(_info) >= 2:
                                return tuple(sorted((_info[0].lower(), _info[1].lower())))
                            return (pa,)  # unknown family → unique bucket

                        # Count families already committed (A + B + C1 + C2)
                        _family_counts: dict = {}
                        for _committed_pa in _committed:
                            _fam = _pool_family(_committed_pa)
                            _family_counts[_fam] = _family_counts.get(_fam, 0) + 1

                        _slots_for_fill = max(0, _pool_cap - len(_committed))
                        _diverse_fill: list = []
                        _c3_gas_hopeless_skipped = 0
                        for _rpa in _remaining_for_fill:
                            if len(_diverse_fill) >= _slots_for_fill:
                                break
                            _fam = _pool_family(_rpa)
                            # M7.A.5.47r: exclude family_unresolved from bridge entirely —
                            # unresolved pools have singleton family (pa,) which bypasses
                            # the family cap. They must not enter bridge at all.
                            if len(_fam) < 2:
                                continue
                            if _family_counts.get(_fam, 0) >= _FAMILY_CAP:
                                continue
                            # M7.A.5.47o: skip gas-hopeless families in C3 fill
                            if _fam in _gas_hopeless_families:
                                _c3_gas_hopeless_skipped += 1
                                continue
                            _diverse_fill.append(_rpa)
                            _family_counts[_fam] = _family_counts.get(_fam, 0) + 1

                        # Assemble: A + B + C1 + C2 + C3 (diverse fill)
                        # M7.A.5.47r: exclude family_unresolved from committed too
                        _resolved_committed = {pa for pa in _committed if len(_pool_family(pa)) >= 2}
                        _bridge_pool_addrs = _resolved_committed | set(_diverse_fill)

                        # M7.A.5.47l: Hard-pin — cold-exec pools MUST survive
                        # regardless of family cap, floor, or any other pressure.
                        # This is defense-in-depth: bucket_a already includes them,
                        # but if any downstream logic accidentally evicts them,
                        # force re-add here.
                        # M7.A.5.47r: Only hard-pin resolved-family pools.
                        _bridge_pool_addrs |= {pa for pa in _bucket_a if len(_pool_family(pa)) >= 2}

                        # M7.A.5.47j: Bridge minimum floor — if we have PTT
                        # pools discovered, the focused filter should never
                        # collapse below a reasonable fraction of them.
                        # This prevents the bridge from being starved when
                        # A/B/C1/C2 are all empty but C3 fill is limited
                        # by the family cap.
                        _BRIDGE_MIN_FLOOR = 20
                        if len(_bridge_pool_addrs) < _BRIDGE_MIN_FLOOR and len(_ptt) >= _BRIDGE_MIN_FLOOR:
                            _deficit = _BRIDGE_MIN_FLOOR - len(_bridge_pool_addrs)
                            _floor_fill = [
                                pa for pa in _remaining_ranked
                                if pa not in _bridge_pool_addrs
                                and len(_pool_family(pa)) >= 2  # M7.A.5.47r: skip unresolved
                            ][:_deficit]
                            _bridge_pool_addrs |= set(_floor_fill)

                        # M7.A.5.47k: Bridge rejection reasons — track why each
                        # PTT pool was excluded from the focused bridge.
                        _bridge_excluded: list = []
                        for _bxr_pa in list(_ptt.keys())[:200]:
                            _bxr_pa_low = _bxr_pa.lower()
                            if _bxr_pa_low in _bridge_pool_addrs:
                                continue
                            _reason = "unknown"
                            _ne_info_bx = _ptt.get(_bxr_pa_low) or _ptt.get(_bxr_pa)
                            _bx_fam = None
                            if _ne_info_bx and len(_ne_info_bx) >= 2:
                                _bx_fam = tuple(sorted((_ne_info_bx[0].lower(), _ne_info_bx[1].lower())))
                            # Check family cap first (most common exclusion)
                            if _bx_fam and _family_counts.get(_bx_fam, 0) >= _FAMILY_CAP:
                                _reason = "family_cap"
                            elif _bxr_pa_low not in set(pa for pa in _remaining_ranked):
                                _reason = "not_recently_active"
                            elif _bx_fam and _bx_fam not in _gas_viable_families:
                                _reason = "gas_too_negative"
                            else:
                                _reason = "capacity_limit"
                            _bridge_excluded.append({
                                "pool_address": _bxr_pa_low,
                                "exclude_reason": _reason,
                            })
                        _bridge_excluded_top = _bridge_excluded[:10]

                        # M7.A.5.47m: Build bridge_selected_pools_top at assembly
                        # time. Prioritize A-bucket (cold-exec) first so they
                        # are never truncated by the [:30] reporting cap.
                        _ordered_for_selected: list = (
                            sorted(_bucket_a) +
                            sorted(_bucket_b - _bucket_a) +
                            sorted((_bucket_c1_stale | _bucket_c2_gas_near) - _bucket_a - _bucket_b) +
                            [pa for pa in _bridge_pool_addrs
                             if pa not in _bucket_a and pa not in _bucket_b
                             and pa not in _bucket_c1_stale and pa not in _bucket_c2_gas_near]
                        )
                        _bridge_selected_at_assembly: list = []
                        for _bsa_pa in _ordered_for_selected[:30]:
                            _bsa_bucket = "C3_activity_fill"
                            if _bsa_pa in _bucket_a:
                                _bsa_bucket = "A_cold_exec"
                            elif _bsa_pa in _bucket_b:
                                _bsa_bucket = "B_hot_seen"
                            elif _bsa_pa in _bucket_c1_stale:
                                _bsa_bucket = "C1_stale_recovery"
                            elif _bsa_pa in _bucket_c2_gas_near:
                                _bsa_bucket = "C2_gas_near"
                            _bsa_info = _ptt.get(_bsa_pa) or _ptt.get(_bsa_pa.lower())
                            _bsa_fam = "family_unresolved"
                            if _bsa_info and len(_bsa_info) >= 2:
                                _bsa_fam = f"{_bsa_info[0]}/{_bsa_info[1]}"
                            # M7.A.5.47q: Downgrade family_unresolved pools
                            # from A_cold_exec — unresolved provenance should
                            # not occupy a high-priority bridge slot.
                            if _bsa_fam == "family_unresolved" and _bsa_bucket == "A_cold_exec":
                                _bsa_bucket = "C3_activity_fill"
                            _bridge_selected_at_assembly.append({
                                "pool_address": _bsa_pa,
                                "bucket": _bsa_bucket,
                                "family": _bsa_fam,
                                "selected": True,
                            })

                        _active_in_filter = sum(
                            1 for pa in _bridge_pool_addrs
                            if pa in _cold_active_pools or pa in _hot_active_pools
                        )
                        logger.info(
                            "Hot focused intake: %d bridge pools "
                            "(A=%d cold_exec, B=%d hot-seen, "
                            "C1=%d stale_recovery, C2=%d gas_near, "
                            "C3=%d activity_fill/%d remaining, "
                            "active=%d, hot-injected=%d, families=%d, cap=%d)",
                            len(_bridge_pool_addrs), len(_bucket_a),
                            len(_bucket_b), len(_bucket_c1_stale),
                            len(_bucket_c2_gas_near), len(_diverse_fill),
                            len(_remaining), _active_in_filter, _hot_injected,
                            len(_family_counts), _FAMILY_CAP,
                        )
                except NameError:
                    pass  # _bridge not yet available (first iteration, no cold run yet)

            # M7.A.5.47e: Pass bridge-hit deficit flag so ws_live broadens
            # scan when rollup shows events exist but zero bridge hits.
            # M7.A.5.47g: Escalate severity — sustained deficit (3+ windows
            # with events but zero hits) goes fully broad (interval=1).
            _bhd = lane == "hot" and _rollup_wwe > 0 and _rollup_wwbh == 0
            _bhd_severe = _bhd and _rollup_wwe >= 3
            artifact = run_ws_live(ws_args, external_registry=_ext_registry,
                                   warm_registry=_cold_registry if lane == "cold" else None,
                                   bridge_pool_addresses=_bridge_pool_addrs,
                                   bridge_hit_deficit=_bhd,
                                   bridge_hit_deficit_severe=_bhd_severe)
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
            fast_results = None
            if lane == "hot":
                # M7.A.5.46: Use _raw_results for profit guard (compact mode).
                guard_results = _run_profit_guard_on_results(
                    artifact.get("_raw_results", artifact.get("results", [])),
                    chain=cli_args.chain,
                )

                # M7.A.5.34: Extract fast-path results directly from artifact.
                # In hot mode, run_ws_live() scores events via score_backrun_fast()
                # inline (no fallback to parallel). Results with scoring_path=
                # "registry_fast" are already first-class — no re-scoring needed.
                # Use _raw_results (BackrunResult objects) for attribute access.
                _raw_results = artifact.get("_raw_results", [])
                fast_results = [
                    r for r in _raw_results
                    if getattr(r, "scoring_path", None) == "registry_fast"
                ]
                if fast_results:
                    logger.info(
                        "Hot fast-path: %d/%d events scored, %d positive",
                        len(fast_results),
                        events_count,
                        sum(1 for r in fast_results
                            if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0),
                    )

            if lane == "cold":
                # Cold lane: full diagnostic rolling artifact
                _write_rolling_m7(artifact)

                # M7.A.5.39: Two-level promotion from cold results
                _promoted_pairs = _promote_pairs_from_cold(artifact, _cold_pair_stats)
                _n_cand = len(_promoted_pairs.get("candidate", []))
                _n_exec = len(_promoted_pairs.get("execution", []))
                if _n_cand > 0 or _n_exec > 0:
                    logger.info(
                        "Cold→hot promotion: %d candidate, %d execution %s",
                        _n_cand, _n_exec,
                        _promoted_pairs.get("candidate", [])[:5],
                    )
                    # M7.A.5.39: Write to shared file for hot lane cross-read
                    _write_promoted_pairs(_promoted_pairs)

                # M7.A.5.42: Write cold→hot bridge with per-candidate detail
                _write_cold_hot_bridge(
                    artifact,
                    cold_active_pools=_cold_active_pools,
                    hot_active_pools=_hot_active_pools,
                )

                # M7.E1.9: Update discovery scoreboard (only in discovery profile)
                if profile == "discovery":
                    _disc_sb = _read_discovery_scoreboard()
                    _disc_sb = _update_discovery_scoreboard(
                        _disc_sb, artifact, iteration
                    )
                    _write_discovery_scoreboard(_disc_sb)
                    logger.info(
                        "Discovery scoreboard updated: %d families tracked",
                        len(_disc_sb.get("families", {})),
                    )

                # M7.A.5.47: Track pool addresses seen in cold events for
                # activity-based ranking. Hot lane uses this to prioritize
                # bridge pools that actually receive swap events.
                for _cr in artifact.get("_raw_results", []):
                    _cpa = getattr(_cr, "pool_address", None) or (
                        getattr(getattr(_cr, "_source_event", None), "pool_address", None)
                    )
                    if _cpa:
                        _cpa_low = _cpa.lower()
                        if _cpa_low in _cold_active_pools:
                            _cold_active_pools[_cpa_low]["event_count"] += 1
                            _cold_active_pools[_cpa_low]["last_iter"] = iteration
                        else:
                            _cold_active_pools[_cpa_low] = {
                                "event_count": 1, "last_iter": iteration,
                            }

                # M7.A.5.37: Log cold registry persistence stats
                if _cold_registry is not None:
                    logger.info(
                        "Cold registry: preload_calls=%d cache_hits=%d pools_active=%d queried=%d",
                        _cold_registry.preload_calls,
                        _cold_registry.cache_hits,
                        _cold_registry.pools_active,
                        len(getattr(_cold_registry, "_queried", set())),
                    )
            else:
                # Hot lane: minimal artifact with profit guard
                # M7.A.5.43: Compute 3 hot-miss counters from raw results
                _hot_bridge_diag = {
                    "bridge_cache_populated": _bridge_cache_count,
                    "bridge_registry_prewarmed": _bridge_prewarm_count,
                    "pool_address_match_count": 0,
                    "canonical_pair_match_count": 0,
                    "registry_has_pair_but_not_pool_count": 0,
                    # M7.A.5.44: Explicit bridge-hit counters
                    "bridge_pool_address_hit_count": 0,
                    "bridge_pair_hit_count": 0,
                    # M7.A.5.47j: Focused bridge pool count — the actual number
                    # of pools in _bridge_pool_addrs (distinct from
                    # bridge_loaded_candidate_count which is just A-bucket).
                    "bridge_focused_pool_count": len(_bridge_pool_addrs) if _bridge_pool_addrs else 0,
                    "bridge_loaded_candidate_count": 0,
                    # M7.A.5.47k: Bridge exclusion reasons (why pools were left out)
                    "bridge_excluded_top": _bridge_excluded_top if '_bridge_excluded_top' in dir() else [],
                    # M7.A.5.47l: Bridge selected pools at assembly time
                    "bridge_selected_at_assembly": _bridge_selected_at_assembly if '_bridge_selected_at_assembly' in dir() else [],
                    # M7.A.5.47m: Full bridge pool set for accurate in_bridge checks
                    # (the assembly list is truncated to 30; this is the truth set).
                    "_bridge_pool_addrs_set": _bridge_pool_addrs if '_bridge_pool_addrs' in dir() and _bridge_pool_addrs is not None else set(),
                    # M7.A.5.47m: Bucket membership for bridge_hit_trace_top
                    "_bucket_a": _bucket_a if '_bucket_a' in dir() else set(),
                    # M7.A.5.46: Carry bridge cold_executable for headline_level computation.
                    "_bridge_cold_executable": _bridge.get("cold_executable", []),
                    # M7.A.5.47o: Carry PTT reference for family lookup in other_live_pool_trace.
                    "_ptt": _ptt if '_ptt' in dir() else {},
                    # M7.A.5.47o: Gas-hopeless family stats from C3 bridge tightening.
                    "c3_gas_hopeless_skipped": _c3_gas_hopeless_skipped if '_c3_gas_hopeless_skipped' in dir() else 0,
                    "c3_gas_hopeless_families": sorted(str(f) for f in _gas_hopeless_families) if '_gas_hopeless_families' in dir() and _gas_hopeless_families else [],
                }
                # M7.A.5.47i: Split bridge diagnostics into independent blocks
                # so one failure doesn't kill the bridge hit counter.
                _ptc = None
                try:
                    from m7.orderflow.resolve import _pool_token_cache as _ptc
                except Exception:
                    pass

                # Block 1: pool_address_match via registry (may raise on registry ops)
                try:
                    if _ptc is not None:
                        for _r in artifact.get("_raw_results", []):
                            if getattr(_r, "scoring_path", None) != "hot_skip":
                                continue
                            _evt = getattr(_r, "_source_event", None)
                            if not _evt or not getattr(_evt, "pool_address", None):
                                continue
                            _ck = _evt.pool_address.lower()
                            _cached = _ptc.get(_ck)
                            if _cached:
                                _hot_bridge_diag["pool_address_match_count"] += 1
                                _t0, _t1, _ = _cached
                                if _hot_registry:
                                    _entries = _hot_registry.lookup_pair(_t0, _t1)
                                    if _entries:
                                        _hot_bridge_diag["canonical_pair_match_count"] += 1
                                        _active = [e for e in _entries if e.is_active()]
                                        if not _active:
                                            _hot_bridge_diag["registry_has_pair_but_not_pool_count"] += 1
                except Exception as _exc_b1:
                    logger.debug("Bridge diag block-1 (registry match) failed: %s", str(_exc_b1)[:120])

                # Block 2: Bridge-hit counters — across ALL events (not just hot_skip)
                # M7.A.5.44: This is the critical bridge hit counter.
                try:
                    _bridge_ptt = _bridge.get("pool_token_transport", {})
                    _bridge_ptt_lower = {k.lower() for k in _bridge_ptt}
                    _raw_results_for_bridge = artifact.get("_raw_results", [])
                    for _r in _raw_results_for_bridge:
                        _evt = getattr(_r, "_source_event", None)
                        if not _evt or not getattr(_evt, "pool_address", None):
                            continue
                        _ck_all = _evt.pool_address.lower()
                        if _ck_all in _bridge_ptt_lower:
                            _hot_bridge_diag["bridge_pool_address_hit_count"] += 1
                            if _ptc is not None:
                                _cached_all = _ptc.get(_ck_all)
                                if _cached_all and _hot_registry:
                                    _t0a, _t1a, _ = _cached_all
                                    _ent_all = _hot_registry.lookup_pair(_t0a, _t1a)
                                    if _ent_all:
                                        _hot_bridge_diag["bridge_pair_hit_count"] += 1
                    # Log diagnostic for bridge hit investigation
                    if _raw_results_for_bridge and _bridge_ptt_lower:
                        _sample_evt_pools = []
                        for _sr in _raw_results_for_bridge[:5]:
                            _se = getattr(_sr, "_source_event", None)
                            if _se and getattr(_se, "pool_address", None):
                                _sample_evt_pools.append(_se.pool_address.lower()[:10])
                        _sample_ptt = list(_bridge_ptt_lower)[:5]
                        logger.info(
                            "Bridge hit diag: raw_results=%d ptt_size=%d hits=%d "
                            "evt_pools_sample=%s ptt_sample=%s",
                            len(_raw_results_for_bridge), len(_bridge_ptt_lower),
                            _hot_bridge_diag["bridge_pool_address_hit_count"],
                            _sample_evt_pools, [p[:10] for p in _sample_ptt],
                        )
                    elif not _bridge_ptt_lower:
                        logger.debug("Bridge hit diag: PTT empty (bridge not yet written?)")
                except Exception as _exc_b2:
                    logger.debug("Bridge diag block-2 (ptt hit) failed: %s", str(_exc_b2)[:120])

                # Block 3: Loaded count + pair-fallback
                try:
                    _hot_bridge_diag["bridge_loaded_candidate_count"] = len(
                        _bridge.get("cold_executable", [])
                    ) + len(_bridge.get("near_executable", []))

                    # M7.A.5.46: Bridge pair-fallback counter
                    _bridge_pairs: set = set()
                    for _cand in (_bridge.get("cold_executable", []) + _bridge.get("near_executable", [])):
                        _cp = _cand.get("actual_pair", "") if isinstance(_cand, dict) else ""
                        if _cp:
                            _bridge_pairs.add(_cp)
                    _pair_fallback = 0
                    for _r in artifact.get("_raw_results", []):
                        if getattr(_r, "scoring_path", None) != "hot_skip":
                            continue
                        _ap = getattr(_r, "actual_pair", None)
                        if _ap and _ap in _bridge_pairs:
                            _pair_fallback += 1
                    _hot_bridge_diag["bridge_pair_fallback_count"] = _pair_fallback
                except Exception as _exc_b3:
                    logger.debug("Bridge diag block-3 (loaded/fallback) failed: %s", str(_exc_b3)[:120])

                # M7.A.5.47c: Track hot-seen pool addresses for cross-iteration ranking
                _wls_h = artifact.get("ws_live_stats", {})
                _hot_hist = _wls_h.get("hot_event_pool_histogram", [])
                for _ph in _hot_hist:
                    _ph_addr = (_ph.get("pool") or "").lower()
                    _ph_ct = _ph.get("count", 0)
                    if _ph_addr:
                        if _ph_addr in _hot_active_pools:
                            _hot_active_pools[_ph_addr]["event_count"] += _ph_ct
                            _hot_active_pools[_ph_addr]["last_iter"] = iteration
                        else:
                            _hot_active_pools[_ph_addr] = {
                                "event_count": _ph_ct, "last_iter": iteration,
                            }

                # M7.A.5.47g: Decrement stale-pin TTLs after each hot window.
                # Expired entries are removed — they'll be re-pinned if stale
                # positive reappears in the next cold cycle.
                _expired_pins = [
                    pa for pa, info in _stale_pin_ttl.items()
                    if info.get("ttl", 0) <= 1
                ]
                for _ep in _expired_pins:
                    del _stale_pin_ttl[_ep]
                for _sp_pa in _stale_pin_ttl:
                    _stale_pin_ttl[_sp_pa]["ttl"] -= 1

                # M7.A.5.47h: Decrement hot-seen-pin TTLs after each hot window.
                _expired_hot_pins = [
                    pa for pa, info in _hot_seen_pin.items()
                    if info.get("ttl", 0) <= 1
                ]
                for _ehp in _expired_hot_pins:
                    del _hot_seen_pin[_ehp]
                for _hsp_pa in _hot_seen_pin:
                    _hot_seen_pin[_hsp_pa]["ttl"] -= 1

                # M7.A.5.47c: Build bridge_miss_sample_top — pools seen in hot
                # events but NOT in the bridge pool set. Shows which pools to add.
                _bridge_miss_sample = []
                if _hot_hist and _bridge_pool_addrs:
                    for _ph in _hot_hist[:10]:
                        _ph_addr = (_ph.get("pool") or "").lower()
                        if _ph_addr and _ph_addr not in _bridge_pool_addrs:
                            _bridge_miss_sample.append({
                                "event_pool": _ph_addr,
                                "seen_count": _ph.get("count", 0),
                                "not_in_bridge": True,
                            })
                _hot_bridge_diag["bridge_miss_sample_top"] = _bridge_miss_sample[:5]

                # M7.A.5.47k: Auto-promote ALL bridge-miss pools into
                # _hot_seen_pin for next hot windows — not just those in
                # recent_active_pools.  Every pool that generates a hot event
                # but is missing from the bridge must be pinned so it gets
                # scored in subsequent windows.
                _active_pool_set: set = set()
                for _rap in _bridge.get("recent_active_pools_top", []):
                    _rap_pa = (_rap.get("pool_address") or "").lower()
                    if _rap_pa:
                        _active_pool_set.add(_rap_pa)
                _auto_promoted = 0
                for _bms in _bridge_miss_sample[:10]:
                    _bms_pa = (_bms.get("event_pool") or "").lower()
                    if not _bms_pa:
                        continue
                    if _bms_pa not in _hot_seen_pin or _hot_seen_pin[_bms_pa].get("ttl", 0) <= 1:
                        _src = ("bridge_miss_active_promote"
                                if _bms_pa in _active_pool_set
                                else "bridge_miss_direct_pin")
                        _hot_seen_pin[_bms_pa] = {
                            "ttl": _HOT_SEEN_PIN_TTL_INIT,
                            "last_iter": iteration,
                            "source": _src,
                        }
                        _auto_promoted += 1
                if _auto_promoted > 0:
                    logger.info(
                        "Hot bridge-miss auto-promote: %d pools pinned (iter %d)",
                        _auto_promoted, iteration,
                    )

                # M7.A.5.47i: hot_seen_vs_bridge_overlap diagnostic — shows
                # which hot-seen pools are in the focused bridge and which aren't,
                # and what bucket they landed in (or why absent).
                # Always produces a list (even if empty) — never None.
                _overlap_diag: list = []
                if _hot_hist and _bridge_pool_addrs is not None:
                    # Guard: bucket variables may not exist if bridge assembly failed
                    _ba = _bucket_a if '_bucket_a' in dir() else set()
                    _bb = _bucket_b if '_bucket_b' in dir() else set()
                    _bc1 = _bucket_c1_stale if '_bucket_c1_stale' in dir() else set()
                    _bc2 = _bucket_c2_gas_near if '_bucket_c2_gas_near' in dir() else set()
                    _ptt_diag = _ptt if '_ptt' in dir() else {}
                    for _oh in _hot_hist[:10]:
                        _oh_addr = (_oh.get("pool") or "").lower()
                        if not _oh_addr:
                            continue
                        _in_bridge = _oh_addr in _bridge_pool_addrs
                        _bucket_label = "absent"
                        if _oh_addr in _ba:
                            _bucket_label = "A_cold_exec"
                        elif _oh_addr in _bb:
                            _bucket_label = "B_hot_seen"
                        elif _oh_addr in _bc1:
                            _bucket_label = "C1_stale_recovery"
                        elif _oh_addr in _bc2:
                            _bucket_label = "C2_gas_near"
                        elif _in_bridge:
                            _bucket_label = "C3_activity_fill"
                        _reason = ""
                        if not _in_bridge:
                            if _oh_addr not in _ptt_diag:
                                _reason = "not_in_ptt"
                            elif _oh_addr in _hot_seen_pin:
                                _reason = "pinned_but_ttl_expired_or_not_in_ptt"
                            else:
                                _reason = "no_bucket_qualified"
                        _overlap_diag.append({
                            "event_pool": _oh_addr,
                            "seen_count": _oh.get("count", 0),
                            "in_bridge": _in_bridge,
                            "bucket": _bucket_label,
                            "reason_if_absent": _reason,
                        })
                _hot_bridge_diag["hot_seen_vs_bridge_overlap_top"] = _overlap_diag[:5]

                # M7.A.5.47c: Refined miss counter — bridge pool hit but registry miss
                _hot_bridge_diag["bridge_pool_hit_but_registry_miss"] = max(0,
                    _hot_bridge_diag.get("bridge_pool_address_hit_count", 0)
                    - _hot_bridge_diag.get("canonical_pair_match_count", 0)
                )

                # M7.A.5.47n: Capture bridge_hit_trace for merge into bridge file.
                # M7.A.5.47p: Also capture other_live_pool_trace for live-miss auto-pin.
                # M7.A.5.47r: Also capture _fam_diff_data for bridge file contract.
                # M7.E1.6: Also capture _family_unresolved_count for bridge contract.
                _bridge_hit_trace_data, _other_live_trace, _fam_diff_data, _family_unresolved_count = _write_hot_artifact(
                    artifact, iteration, guard_results,
                    fast_results=fast_results,
                    promoted_pairs=_promoted_pairs.get("execution", []),
                    candidate_pairs=_promoted_pairs.get("candidate", []),
                    bridge_diagnostics=_hot_bridge_diag,
                    chain=cli_args.chain,
                    profile=profile,
                )

                # M7.A.5.47p: Auto-pin live-miss pools from other_live_pool_trace.
                # Pools that had hot events but are not in bridge get pinned so
                # bridge assembly includes them in bucket B next iteration.
                _live_miss_pinned = 0
                for _lmt in (_other_live_trace or []):
                    if _lmt.get("reason_if_not_hit") == "not_in_bridge":
                        _lm_pa = (_lmt.get("pool_address") or "").lower()
                        if _lm_pa and (_lm_pa not in _hot_seen_pin
                                       or _hot_seen_pin[_lm_pa].get("ttl", 0) <= 1):
                            _hot_seen_pin[_lm_pa] = {
                                "ttl": _HOT_SEEN_PIN_TTL_INIT,
                                "last_iter": iteration,
                                "source": "live_miss_trace_pin",
                            }
                            _live_miss_pinned += 1
                if _live_miss_pinned > 0:
                    logger.info(
                        "Live-miss trace auto-pin: %d pools pinned (iter %d)",
                        _live_miss_pinned, iteration,
                    )

                # M7.A.5.47q: Sibling-pool auto-pin — for surviving/stale-positive
                # families, pin 1-3 sibling pools of the same family that are in
                # PTT but not already in bridge. This tests whether the blocker
                # is pool-specific or family-wide.
                _sibling_pinned = 0
                _ptt_for_sibling = _ptt if '_ptt' in dir() else {}
                if _ptt_for_sibling and _bridge_hit_trace_data:
                    # Collect families from cold-exec trace
                    _cold_families: dict = {}  # family_key -> list of pool addresses
                    for _bht in _bridge_hit_trace_data:
                        _bht_pa = (_bht.get("pool_address") or "").lower()
                        _bht_info = _ptt_for_sibling.get(_bht_pa)
                        if _bht_info and len(_bht_info) >= 2:
                            _bht_fam = tuple(sorted((_bht_info[0].lower(), _bht_info[1].lower())))
                            _cold_families.setdefault(_bht_fam, []).append(_bht_pa)
                    # For each cold-exec family, find siblings in PTT not in bridge
                    _bridge_set_for_sibling = _bridge_pool_addrs if _bridge_pool_addrs else set()
                    for _sib_fam, _sib_exec_pools in _cold_families.items():
                        _sib_candidates = []
                        for _sib_pa, _sib_info in _ptt_for_sibling.items():
                            if not _sib_info or len(_sib_info) < 2:
                                continue
                            _sib_pa_low = _sib_pa.lower()
                            _sib_fam_check = tuple(sorted((_sib_info[0].lower(), _sib_info[1].lower())))
                            if (_sib_fam_check == _sib_fam
                                    and _sib_pa_low not in _bridge_set_for_sibling
                                    and _sib_pa_low not in _hot_seen_pin):
                                _sib_candidates.append(_sib_pa_low)
                        for _sib_c in _sib_candidates[:3]:
                            _hot_seen_pin[_sib_c] = {
                                "ttl": _HOT_SEEN_PIN_TTL_INIT,
                                "last_iter": iteration,
                                "source": "family_sibling_pin",
                            }
                            _sibling_pinned += 1
                if _sibling_pinned > 0:
                    logger.info(
                        "Family sibling auto-pin: %d pools pinned (iter %d)",
                        _sibling_pinned, iteration,
                    )

                # M7.A.5.47k: Write hot-side diagnostics back into bridge file.
                # Always merge overlap + selected as lists (never null).
                # Bridge file is cold-written with [] defaults; hot lane updates.
                try:
                    if os.path.exists(_COLD_HOT_BRIDGE_PATH):
                        with open(_COLD_HOT_BRIDGE_PATH, "r", encoding="utf-8") as _bf:
                            _bridge_update = json.load(_bf)
                        _bridge_update["hot_seen_vs_bridge_overlap_top"] = _overlap_diag[:5]
                        # M7.A.5.47m: Use assembly-time ordered list (A-bucket first)
                        # instead of arbitrary set iteration.
                        _bridge_update["bridge_selected_pools_top"] = (
                            _bridge_selected_at_assembly[:20]
                            if '_bridge_selected_at_assembly' in dir()
                            else []
                        )
                        # M7.A.5.47l: Also persist bridge_excluded_top into bridge file
                        _bridge_update["bridge_excluded_top"] = (
                            _bridge_excluded_top if '_bridge_excluded_top' in dir() else []
                        )
                        # M7.A.5.47n: Persist bridge_hit_trace_top + cold_exec_pool_trace
                        # into bridge file so cross-artifact truth is always consistent.
                        # M7.A.5.47p: Always write trace — if empty, explicitly clear stale data.
                        _bridge_update["bridge_hit_trace_top"] = _bridge_hit_trace_data or []
                        _bridge_update["cold_exec_pool_trace"] = _bridge_hit_trace_data or []
                        # M7.A.5.47q: Persist c3_gas_hopeless into bridge file
                        # so it's visible before the hot pass.
                        _bridge_update["c3_gas_hopeless_skipped"] = (
                            _hot_bridge_diag.get("c3_gas_hopeless_skipped") or 0
                        )
                        _bridge_update["c3_gas_hopeless_families"] = (
                            _hot_bridge_diag.get("c3_gas_hopeless_families") or []
                        )
                        # M7.A.5.47r: Persist bridge_selected_family_diff_top
                        # into bridge file — cross-artifact contract: if hot has
                        # the field, bridge must too (non-null).
                        _bridge_update["bridge_selected_family_diff_top"] = (
                            _fam_diff_data if '_fam_diff_data' in dir() and _fam_diff_data else []
                        )
                        # M7.E1.6: Persist family_unresolved_pool_count into bridge.
                        _bridge_update["family_unresolved_pool_count"] = (
                            _family_unresolved_count if '_family_unresolved_count' in dir() else 0
                        )
                        # M7.A.5.47m: Persist cut_stage_top from cold lane artifact
                        # (already written to bridge by cold lane; refresh here
                        # to keep it consistent after hot merge).
                        if "cut_stage_top" not in _bridge_update or _bridge_update["cut_stage_top"] is None:
                            _bridge_update["cut_stage_top"] = {}
                        _atomic_json_write(_COLD_HOT_BRIDGE_PATH, _bridge_update, indent=2)
                except Exception as _exc_bu:
                    logger.debug("Bridge file update failed: %s", str(_exc_bu)[:120])

                # M7.A.5.45: Write hot execution intents artifact
                _write_hot_intents(
                    fast_results=fast_results,
                    guard_results=guard_results,
                    iteration=iteration,
                    bridge=_bridge,
                    chain=cli_args.chain,
                )

                # M7.A.5.47: Update cumulative hot rollup
                _update_hot_rollup(
                    events_count=artifact.get("events_count", 0),
                    fast_results=fast_results,
                    guard_results=guard_results,
                    bridge_diagnostics=_hot_bridge_diag,
                    ws_live_stats=artifact.get("ws_live_stats"),
                    hot_active_pools=_hot_active_pools,
                    bridge=_bridge,
                    chain=cli_args.chain,
                )

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
            # M7.E1.7: Write heartbeat artifacts even on failure so hot
            # artifacts stay fresh and reviewers see the loop is alive.
            if lane == "hot":
                _write_hot_heartbeat_on_error(
                    iteration, window_started_at, window_ended_at,
                    str(exc)[:200],
                    chain=cli_args.chain,
                )
                # Also update rollup with a zero-event heartbeat window
                try:
                    _update_hot_rollup(
                        events_count=0,
                        fast_results=None,
                        guard_results=None,
                        bridge_diagnostics=None,
                        chain=cli_args.chain,
                    )
                except Exception as _exc_rollup:
                    logger.debug(
                        "Hot rollup heartbeat failed: %s",
                        str(_exc_rollup)[:120],
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
