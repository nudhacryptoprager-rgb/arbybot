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
from m7.orderflow.scoring_parallel import score_backrun_fast
from m7.shared.constants import (
    HOT_WATCHLIST_PAIRS,
    PROMOTED_CANDIDATE_MAX_PAIRS,
    PROMOTED_MAX_PAIRS,
    PROMOTED_MIN_COLD_APPEARANCES,
    PROMOTED_MIN_NET_BPS,
)

logger = get_logger("m7.orderflow.loop")

_HOT_ARTIFACT_PATH = os.path.join("data", "runs", "_rolling", "m7_hot_latest.json")
# M7.A.5.39: Cross-lane promoted pairs file — cold writes, hot reads.
_PROMOTED_PAIRS_PATH = os.path.join("data", "runs", "_rolling", "m7_promoted_pairs.json")
# M7.A.5.42: Cold→hot bridge queue — top executable candidates with TTL for hot lane consumption.
_COLD_HOT_BRIDGE_PATH = os.path.join("data", "runs", "_rolling", "m7_cold_hot_bridge.json")
# M7.A.5.45: Hot execution intents — compact rows for hot-scored + profit-guard-checked candidates.
_HOT_INTENTS_PATH = os.path.join("data", "runs", "_rolling", "m7_hot_intents_latest.json")
# M7.A.5.47: Cumulative hot rollup — survives across windows so progress is visible.
_HOT_ROLLUP_PATH = os.path.join("data", "runs", "_rolling", "m7_hot_rollup_latest.json")


def _write_promoted_pairs(promoted: dict) -> None:
    """Write promoted pairs to rolling artifact for cross-lane communication."""
    try:
        os.makedirs(os.path.dirname(_PROMOTED_PAIRS_PATH), exist_ok=True)
        payload = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "candidate": promoted.get("candidate", []),
            "execution": promoted.get("execution", []),
        }
        with open(_PROMOTED_PAIRS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
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


def _write_cold_hot_bridge(artifact: dict) -> None:
    """Write cold→hot bridge with per-candidate preload detail and pool→token transport.

    M7.A.5.43: Bridge now carries:
      - cold_executable / cold_stale_positive / near_executable with pool_address
      - pool_token_transport: full _pool_token_cache dump for hot lane to populate
        its own process-local cache (keys are pool addresses, values are
        [token0_addr, token1_addr, fee] tuples).
    """
    try:
        candidates = artifact.get("top_executable_candidates", [])
        stale_pos = artifact.get("top_stale_positive_candidates", [])
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
        payload = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cold_executable": candidates,
            "cold_stale_positive": stale_pos,
            "near_executable": near_exec,
            "signal_classification": artifact.get("signal_classification", {}),
            "pool_token_transport": _ptt,
        }
        with open(_COLD_HOT_BRIDGE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
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
            pipeline_latency_ms=pipeline_ms,
        )
        if guard.passed:
            passed.append((r, guard))
    return passed


def _write_hot_artifact(artifact: dict, iteration: int, guard_results: list = None,
                        fast_results: list = None, promoted_pairs: list = None,
                        candidate_pairs: list = None,
                        bridge_diagnostics: dict = None) -> None:
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
        hot["promoted_watchlist"] = {
            "count": 0,
            "pairs": [f"{a}/{b}" for a, b in HOT_WATCHLIST_PAIRS],
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
    _fast_attempted = sum(
        1 for r in _raw_results
        if getattr(r, "scoring_path", None) == "registry_fast"
    )
    # M7.A.5.43: 3 hot-miss counters from bridge diagnostics
    _bd = bridge_diagnostics or {}
    hot["hot_gap_debug"] = {
        "total_events": len(_raw_results),
        "fast_path_attempted_count": _fast_attempted,
        "not_in_hot_registry_count": _hot_skip_count,
        "watchlist_match_count": _fast_attempted,  # events that matched promoted watchlist
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
        # M7.A.5.46: Pair-level fallback counter
        "bridge_pair_fallback_count": _bd.get("bridge_pair_fallback_count", 0),
        # M7.A.5.47: 6 canonical hot miss counters (per-window)
        "fast_score_attempted": _fast_attempted,
        "fast_score_rejected_economics": sum(
            1 for r in _raw_results
            if getattr(r, "scoring_path", None) == "registry_fast"
            and getattr(r, "reject_reason", None) in (
                "REJECT_GAS_EXCEEDS_GROSS", "REJECT_STALE_POSITIVE",
            )
        ),
    }

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
        os.makedirs(os.path.dirname(_HOT_ARTIFACT_PATH), exist_ok=True)
        with open(_HOT_ARTIFACT_PATH, "w", encoding="utf-8") as f:
            json.dump(hot, f, indent=2, default=str)
        logger.info("Hot lane artifact written to %s", _HOT_ARTIFACT_PATH)
    except Exception as exc:
        logger.warning("Failed to write hot artifact: %s", str(exc)[:120])


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

    for r in _fast:
        eid = getattr(r, "event_id", None)
        net = getattr(r, "best_backrun_net_bps", None) or 0
        rows.append({
            "event_id": eid,
            "actual_pair": getattr(r, "actual_pair", None),
            "net_bps": round(net, 4) if net else 0,
            "profit_guard_passed": getattr(r, "profit_guard_passed", False),
            "guard_passed_in_hot": eid in _guard_event_ids,
            "scoring_path": getattr(r, "scoring_path", None),
            "pipeline_latency_ms": getattr(r, "quote_pipeline_latency_ms", None),
            "route_viable": getattr(r, "route_viable", False),
        })

    # Sort by net_bps descending
    rows.sort(key=lambda x: x.get("net_bps", 0), reverse=True)

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
        "loop_iteration": iteration,
        "headline_level": headline_level,
        "hot_scored_count": _hot_scored,
        "hot_positive_count": _hot_positive,
        "profit_guard_passed_count": _guard_passed,
        "cold_executable_pool_count": len(bridge.get("cold_executable", [])) if bridge else 0,
        "intents": rows[:20],  # Cap at 20 rows
    }

    try:
        os.makedirs(os.path.dirname(_HOT_INTENTS_PATH), exist_ok=True)
        with open(_HOT_INTENTS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
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
    rollup["windows_seen"] = rollup.get("windows_seen", 0) + 1
    rollup["events_seen_total"] = rollup.get("events_seen_total", 0) + events_count
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
    rollup["profit_guard_passed_total"] = (
        rollup.get("profit_guard_passed_total", 0) + len(_guard)
    )
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
    rollup["fast_score_attempted_total"] = (
        rollup.get("fast_score_attempted_total", 0) + len(_fast)
    )
    rollup["fast_score_rejected_economics_total"] = (
        rollup.get("fast_score_rejected_economics_total", 0)
        + sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) <= 0)
    )
    # Derive dominant hot miss reason from cumulative counters
    _miss_counts = {
        "no_events_in_window": max(0,
            rollup.get("windows_seen", 0)
            - max(1, rollup.get("events_seen_total", 0))
        ),
        "bridge_pool_not_hit": max(0,
            rollup.get("bridge_candidate_loaded_total", 0)
            - rollup.get("bridge_pool_hit_total", 0)
        ),
        "pool_not_in_registry": max(0,
            rollup.get("bridge_pool_hit_total", 0)
            - rollup.get("registry_hit_for_event_pool_total", 0)
        ),
        "fast_score_rejected": rollup.get("fast_score_rejected_economics_total", 0),
    }
    rollup["dominant_hot_miss_reason"] = max(_miss_counts, key=_miss_counts.get) if any(
        v > 0 for v in _miss_counts.values()
    ) else "none"

    try:
        os.makedirs(os.path.dirname(_HOT_ROLLUP_PATH), exist_ok=True)
        with open(_HOT_ROLLUP_PATH, "w", encoding="utf-8") as f:
            json.dump(rollup, f, indent=2, default=str)
    except Exception as exc:
        logger.debug("Failed to write hot rollup: %s", str(exc)[:80])


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

    # M7.A.5.35/M7.A.5.39: Cross-iteration cold stats for two-level promotion
    _cold_pair_stats: dict = {}   # pair_key -> promotion stats from cold results
    _promoted_pairs: dict = {"candidate": [], "execution": []}  # two-level promotion

    # M7.A.5.37: Persistent cold registry — survives across cold iterations
    # Passed via warm_registry to avoid hot-mode trigger. Caches pool data
    # so registry_preload_ms drops to near-zero for already-queried pairs.
    _cold_registry = None  # lazy-init on first cold iteration

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
                # 1. Seed defaults on first iteration
                if iteration == 1:
                    for sym_a, sym_b in HOT_WATCHLIST_PAIRS:
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

                # Seed defaults on first iteration only
                if iteration == 1:
                    for sym_a, sym_b in HOT_WATCHLIST_PAIRS:
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

            # M7.A.5.47: Build focused bridge pool address set for hot lane.
            # Combines cold_executable pool addresses with all pool_token_transport
            # keys from bridge. Passed to run_ws_live for targeted eth_getLogs.
            _bridge_pool_addrs: set | None = None
            if lane == "hot":
                try:
                    _ptt = _bridge.get("pool_token_transport", {})
                    if _ptt:
                        _bridge_pool_addrs = set(_cold_exec_pools)  # already lowered
                        for _ptt_key in _ptt:
                            _bridge_pool_addrs.add(_ptt_key.lower())
                        logger.info(
                            "Hot focused intake: %d bridge pool addresses (%d cold_exec)",
                            len(_bridge_pool_addrs), len(_cold_exec_pools),
                        )
                except NameError:
                    pass  # _bridge not yet available (first iteration, no cold run yet)

            artifact = run_ws_live(ws_args, external_registry=_ext_registry,
                                   warm_registry=_cold_registry if lane == "cold" else None,
                                   bridge_pool_addresses=_bridge_pool_addrs)
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
                    artifact.get("_raw_results", artifact.get("results", []))
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
                _write_cold_hot_bridge(artifact)

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
                    "bridge_loaded_candidate_count": 0,
                    # M7.A.5.46: Carry bridge cold_executable for headline_level computation.
                    "_bridge_cold_executable": _bridge.get("cold_executable", []),
                }
                try:
                    from m7.orderflow.resolve import _pool_token_cache as _ptc
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

                    # M7.A.5.44: Bridge-hit counters — across ALL events (not just hot_skip)
                    _bridge_ptt = _bridge.get("pool_token_transport", {})
                    _bridge_ptt_lower = {k.lower() for k in _bridge_ptt}
                    for _r in artifact.get("_raw_results", []):
                        _evt = getattr(_r, "_source_event", None)
                        if not _evt or not getattr(_evt, "pool_address", None):
                            continue
                        _ck_all = _evt.pool_address.lower()
                        if _ck_all in _bridge_ptt_lower:
                            _hot_bridge_diag["bridge_pool_address_hit_count"] += 1
                            _cached_all = _ptc.get(_ck_all)
                            if _cached_all and _hot_registry:
                                _t0a, _t1a, _ = _cached_all
                                _ent_all = _hot_registry.lookup_pair(_t0a, _t1a)
                                if _ent_all:
                                    _hot_bridge_diag["bridge_pair_hit_count"] += 1
                    # bridge_loaded_candidate_count = entries loaded from bridge
                    _hot_bridge_diag["bridge_loaded_candidate_count"] = len(
                        _bridge.get("cold_executable", [])
                    ) + len(_bridge.get("near_executable", []))

                    # M7.A.5.46: Bridge pair-fallback counter — hot_skip events
                    # whose actual_pair matches a bridge candidate's pair (even
                    # though pool_address didn't match). Diagnoses whether pair-
                    # level matching could improve conversion.
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
                except Exception:
                    pass

                _write_hot_artifact(
                    artifact, iteration, guard_results,
                    fast_results=fast_results,
                    promoted_pairs=_promoted_pairs.get("execution", []),
                    candidate_pairs=_promoted_pairs.get("candidate", []),
                    bridge_diagnostics=_hot_bridge_diag,
                )

                # M7.A.5.45: Write hot execution intents artifact
                _write_hot_intents(
                    fast_results=fast_results,
                    guard_results=guard_results,
                    iteration=iteration,
                    bridge=_bridge,
                )

                # M7.A.5.47: Update cumulative hot rollup
                _update_hot_rollup(
                    events_count=artifact.get("events_count", 0),
                    fast_results=fast_results,
                    guard_results=guard_results,
                    bridge_diagnostics=_hot_bridge_diag,
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
