"""
E1.12.2 — Bridge runtime: cold-hot bridge I/O and registry prewarming.

Extracted from scripts/m7a_orderflow_loop.py.

Provides:
  - _write_cold_hot_bridge: persist cold lane truth for hot lane consumption
  - _read_cold_hot_bridge: read bridge from disk
  - _populate_pool_token_cache_from_bridge: cross-process cache fix (M7.A.5.43)
  - _prewarm_registry_from_bridge: pool-address-first registry prewarm
  - _prewarm_registry_from_pairs: legacy symbol-pair prewarm
  - _promote_pairs_from_cold: two-level promotion rules (M7.A.5.39)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from core.logging import get_logger
from m7.orderflow.runtime_io import (
    _COLD_HOT_BRIDGE_PATH,
    _HOT_ROLLUP_PATH,
    _atomic_json_write,
)
from m7.shared.constants import (
    PROMOTED_CANDIDATE_MAX_PAIRS,
    PROMOTED_MAX_PAIRS,
    PROMOTED_MIN_COLD_APPEARANCES,
    PROMOTED_MIN_NET_BPS,
)

logger = get_logger("m7.orderflow.bridge_runtime")


def _write_cold_hot_bridge(
    artifact: dict,
    cold_active_pools: dict | None = None,
    hot_active_pools: dict | None = None,
) -> None:
    """Write cold->hot bridge with per-candidate preload detail and pool->token transport."""
    from m7.orderflow.runtime_io import _COLD_HOT_BRIDGE_PATH, _HOT_ROLLUP_PATH

    try:
        candidates = artifact.get("top_executable_candidates", [])
        stale_pos = artifact.get("top_stale_positive_candidates", [])
        recoverable_stale = artifact.get("top_recoverable_stale_candidates", [])
        recoverable_stale_viable = artifact.get("top_recoverable_stale_route_viable", [])
        recoverable_stale_not_viable = artifact.get("top_recoverable_stale_not_viable", [])
        near_exec = artifact.get("near_executable_candidates", [])

        _ptt = {}
        try:
            from m7.orderflow.resolve import _pool_token_cache
            for pa, (t0, t1, fee) in _pool_token_cache.items():
                _ptt[pa] = [t0, t1, fee]
        except Exception:
            pass

        os.makedirs(os.path.dirname(_COLD_HOT_BRIDGE_PATH), exist_ok=True)
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
            "micro_refinement": artifact.get("micro_refinement", []),
            "recent_active_pools_top": _rap_top,
            "candidate_source_breakdown": {
                "cold_exec": len(candidates),
                "near_exec": len(near_exec),
                "stale_positive": len(stale_pos),
                "recent_active": len(_rap_top),
                "hot_seen_backfill": 0,
                "ptt_total": len(_ptt),
            },
            "hot_seen_vs_bridge_overlap_top": [],
            "bridge_selected_pools_top": [],
            "family_unresolved_pool_count": 0,
            "bridge_excluded_top": [],
            "cut_stage_top": artifact.get("cut_stage_top", {}),
            "run_context": {
                "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "code_sha": None,
                "code_dirty": None,
                "code_desc": None,
                "evidence_sha": None,
            },
        }
        _hot_unresolved = []
        try:
            from m7.orderflow.resolve import _pool_token_cache as _ptc_bridge
            _hap_merged: dict = {}
            if hot_active_pools:
                for _hpa, _hinfo in hot_active_pools.items():
                    _hap_merged[_hpa.lower()] = _hinfo
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
                for _hu_pa, _hu_info in _hu_sorted[:50]:
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
        payload["candidate_source_breakdown"]["hot_seen_backfill"] = len(_hot_unresolved)
        _HOT_PRESERVE_ALWAYS = (
            "bridge_selected_pools_top", "bridge_excluded_top",
            "c3_gas_hopeless_skipped", "c3_gas_hopeless_families",
            "bridge_selected_family_diff_top",
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
                    if _existing_val is not None and _hpk not in payload:
                        payload[_hpk] = _existing_val
                if _has_cold_exec:
                    for _hpk in _HOT_PRESERVE_IF_COLD_EXEC:
                        _existing_val = _existing.get(_hpk)
                        if _existing_val and not payload.get(_hpk):
                            payload[_hpk] = _existing_val
                else:
                    for _hpk in _HOT_PRESERVE_IF_COLD_EXEC:
                        payload[_hpk] = []
        except Exception:
            pass
        _bsp = payload.get("bridge_selected_pools_top", [])
        payload["candidate_source_breakdown"]["bridge_selected_pools_count"] = len(_bsp)
        _atomic_json_write(_COLD_HOT_BRIDGE_PATH, payload, indent=2)
    except Exception as exc:
        logger.debug("Failed to write cold-hot bridge: %s", str(exc)[:80])


def _read_cold_hot_bridge() -> dict:
    """Read cold->hot bridge file written by cold lane."""
    from m7.orderflow.runtime_io import _COLD_HOT_BRIDGE_PATH

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
    max_pairs: int = 60,
) -> int:
    """Prewarm hot registry from bridge entries using token addresses.

    E1.22: ``max_pairs`` raised from 10 to 30 to cover more bridge-discovered
    pairs.  E1.25: raised from 30 to 60 to cover ~100% of typical PTT
    (49 unique pairs).  Priority pools always go first.  This prevents
    the prewarm from sending 600+ RPC calls when the full PTT has 200+
    entries, which overloads dRPC/public-RPC rate limits.

    Returns number of pairs prewarmed.
    """
    from core.rpc_rate_limiter import rpc_throttle

    ptt = bridge.get("pool_token_transport", {})
    if not ptt:
        return 0
    count = 0
    _seen_pairs: set = set()

    _priority = priority_pools or set()
    _items = sorted(
        ptt.items(),
        key=lambda kv: (0 if kv[0].lower() in _priority else 1),
    )

    for pa, triple in _items:
        if count >= max_pairs:
            break
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

    _stats = rpc_throttle.stats()
    if _stats["total_waits"] > 0:
        logger.info(
            "Bridge prewarm %d pairs — throttle: %d waits, %.0fms total delay",
            count, _stats["total_waits"], _stats["total_waited_ms"],
        )

    # E1.25: Direct PTT→registry injection for pools that factory discovery
    # missed (Algebra dynamic-fee, BaseSwap, other unconfigured DEXes).
    # This is the key fix for bridge_pool_hit_but_registry_miss.
    _ptt_registered = 0
    try:
        _ptt_registered = registry.register_ptt_pools(ptt, rpc_url, block_num)
    except Exception as exc:
        logger.debug("PTT direct register failed: %s", str(exc)[:80])
    if _ptt_registered > 0:
        logger.info("Bridge prewarm: %d extra pools via PTT direct inject", _ptt_registered)

    return count + _ptt_registered


def _prewarm_registry_from_pairs(
    registry, session_pairs: dict, token_addresses: dict,
    dex_configs: dict, rpc_url: str, block_num: int,
) -> int:
    """Prewarm registry using accumulated session_low_lag_pairs.

    Returns number of pairs prewarmed.
    """
    count = 0
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
      - reject_reason != PRICING_ANOMALY
      - registry_pools_active > 0
      - best_net_bps > PROMOTED_MIN_NET_BPS

    **Execution** (level 2) — strict; eligible for hot-path scoring:
      - All candidate rules PLUS:
      - size_valid_for_token=True in at least one scored result

    Returns dict with keys: "candidate", "execution" (lists of pair strings).
    """
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

    candidates = []
    execution = []
    for pair, stats in accumulated_cold_stats.items():
        if stats["appearances"] < PROMOTED_MIN_COLD_APPEARANCES:
            continue
        if not stats["has_active_pools"]:
            continue
        if stats["has_anomaly"]:
            continue
        if stats["best_net_bps"] is None or stats["best_net_bps"] < PROMOTED_MIN_NET_BPS:
            continue
        candidates.append(pair)
        if stats["size_valid_seen"]:
            execution.append(pair)

    _sort_key = lambda p: accumulated_cold_stats[p].get("best_net_bps") or -999
    candidates.sort(key=_sort_key, reverse=True)
    execution.sort(key=_sort_key, reverse=True)
    return {
        "candidate": candidates[:PROMOTED_CANDIDATE_MAX_PAIRS],
        "execution": execution[:PROMOTED_MAX_PAIRS],
    }
