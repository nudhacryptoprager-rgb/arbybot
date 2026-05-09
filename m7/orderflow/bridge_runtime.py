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
        # E1.69 fix step 5: dedup by pool_address so the same pool appearing
        # with different actual_pair strings (e.g. "FUN/USDC" vs
        # "0x16ee7eca/USDC" — symbol-vs-address representation drift)
        # does not occupy multiple cold_executable slots.
        _seen_pool_addrs: set = set()
        _deduped_cands = []
        for _c in candidates:
            _pa = (_c.get("pool_address") or "").lower()
            if _pa and _pa in _seen_pool_addrs:
                continue
            if _pa:
                _seen_pool_addrs.add(_pa)
            _deduped_cands.append(_c)
        candidates = _deduped_cands
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

        # soak16 P0.1: persist pool-token cache to disk so the next supervisor
        # restart picks up resolved pools immediately (avoids
        # `session_fast_path_scored=0` regressions).
        try:
            from m7.orderflow.resolve import save_persistent_pool_token_cache
            save_persistent_pool_token_cache()
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
            # E1.65 Step 5: entries excluded from cold_executable due to USD basis gate
            "cold_usd_basis_missing": artifact.get("top_cold_usd_basis_missing", []),
            # E1.65 fix step 5: diagnostic list — entries that PASSED the USD gate but
            # still have size_usd_estimate=0 AND best_buy_amount_wei=None/0.
            # These are fast-path (registry_direct) entries that lack any enrichable basis.
            # Shown separately so dashboards don't mix priced and unpriced candidates.
            "cold_executable_without_usd_basis": [
                c for c in candidates
                if not ((c.get("size_usd_estimate") or 0) > 0
                        or (c.get("best_buy_amount_wei") or 0) > 0)
            ],
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
                "cold_exec_with_usd_basis": sum(
                    1 for c in candidates
                    if (c.get("size_usd_estimate") or 0) > 0
                    or (c.get("best_buy_amount_wei") or 0) > 0
                ),
                "cold_exec_without_usd_basis": sum(
                    1 for c in candidates
                    if not ((c.get("size_usd_estimate") or 0) > 0
                            or (c.get("best_buy_amount_wei") or 0) > 0)
                ),
                # E1.69 Step 8: production-size candidate visibility.
                # production_sized: routes with amount_in_optimal_usd >= $50
                # research_sized:   routes with amount_in_optimal_usd >= $10
                # production_candidate_total exposes how many >=$50 routes
                # the scanner saw across ALL exec candidates (not just dedup
                # winners), so reviewers can distinguish "no market" from
                # "promotion gate filtered them".
                "production_sized": sum(
                    1 for c in candidates
                    if (c.get("amount_in_optimal_usd") or 0) >= 50.0
                ),
                "research_sized": sum(
                    1 for c in candidates
                    if (c.get("amount_in_optimal_usd") or 0) >= 10.0
                ),
                "near_exec": len(near_exec),
                "stale_positive": len(stale_pos),
                "recent_active": len(_rap_top),
                "hot_seen_backfill": 0,
                "ptt_total": len(_ptt),
                # E1.69 fix step 6: count unpriced candidates so reviewers
                # can see if top-bps slots are blocked by missing USD basis.
                "unpriced_exec": sum(
                    1 for c in candidates
                    if (c.get("size_usd_estimate") or 0) == 0
                    and not (c.get("best_buy_amount_wei") or 0)
                ),
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
            # E1.56 Step 7: pool-level gas-hopeless quarantine fields.
            "c3_pool_gas_hopeless_skipped",
            "pool_gas_hopeless",
            "pool_gas_hopeless_streak",
        )
        _HOT_PRESERVE_IF_COLD_EXEC = (
            "bridge_hit_trace_top", "cold_exec_pool_trace",
        )
        _has_cold_exec = bool(payload.get("cold_executable"))

        # Fix 3 (E1.60): if cold lane restarted and produced no candidates yet
        # (cold window still in PTT-accumulation phase), preserve the previous
        # bridge's cold_executable/near_executable so the hot lane doesn't lose
        # its sim targets for the duration of the warm-up window.
        # Fix 4 (E1.60): add bridge_generation_status diagnostic field.
        _bgen_status: str
        if _has_cold_exec:
            _bgen_status = "ready"
        elif _ptt:
            _bgen_status = "warming"
        else:
            _bgen_status = "empty_market"
        payload["bridge_generation_status"] = _bgen_status

        try:
            if os.path.exists(_COLD_HOT_BRIDGE_PATH):
                with open(_COLD_HOT_BRIDGE_PATH, "r", encoding="utf-8") as _epf:
                    _existing = json.load(_epf)
                for _hpk in _HOT_PRESERVE_ALWAYS:
                    _existing_val = _existing.get(_hpk)
                    if _existing_val is not None and _hpk not in payload:
                        payload[_hpk] = _existing_val
                # Fix 3: preserve previous cold_executable when current write has none.
                if not _has_cold_exec:
                    _prev_cold = _existing.get("cold_executable") or []
                    _prev_near = _existing.get("near_executable") or []
                    if _prev_cold:
                        payload["cold_executable"] = _prev_cold
                        payload["near_executable"] = _prev_near
                        payload["bridge_generation_status"] = "ready_preserved"
                        _has_cold_exec = True
                        # E1.70 fix 4: keep candidate_source_breakdown in sync with
                        # preserved cold_executable so cold_exec count is not 0 when
                        # the list has entries from the previous write.
                        _csb = payload.get("candidate_source_breakdown") or {}
                        if _csb.get("cold_exec", 0) == 0:
                            _csb["cold_exec"] = len(_prev_cold)
                            _csb["cold_exec_preserved"] = True
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
        # E1.69 reviewer fix step 2: feed TVL scout artifact into
        # bridge_selected_pools_top so production-size pools become a
        # routing input instead of just a status flag. When the bridge
        # has no own selection (cold scorer not yet wired), the scout
        # output IS the production candidate set.
        try:
            _scout_path = os.path.join(
                os.path.dirname(_COLD_HOT_BRIDGE_PATH), "m7_tvl_scout_latest.json"
            )
            if os.path.exists(_scout_path) and not _bsp:
                with open(_scout_path, "r", encoding="utf-8") as _sf:
                    _scout = json.load(_sf)
                _scout_pools = _scout.get("pools", []) or []
                # Top 20 production-grade pools as bridge selection seeds.
                _bsp = [
                    {
                        "pool_address": _p.get("pool_address"),
                        "project": _p.get("project"),
                        "symbol": _p.get("symbol"),
                        "tvl_usd": _p.get("tvl_usd"),
                        "source": "tvl_scout",
                    }
                    for _p in _scout_pools[:20]
                    if _p.get("pool_address")
                ]
                payload["bridge_selected_pools_top"] = _bsp
        except Exception:
            pass
        payload["candidate_source_breakdown"]["bridge_selected_pools_count"] = len(_bsp)
        # E1.69 Wave D: surface Flashblocks HTTP lane state + TVL scout state
        # so reviewers can audit "is the production-size scout actually
        # running?" from the rolling artifact alone.
        try:
            from chains import flashblocks_http as _fbh
            payload["candidate_source_breakdown"]["flashblocks_http_enabled"] = bool(
                _fbh.is_enabled()
            )
            _fb_stats = getattr(_fbh, "_STATS", {}) or {}
            payload["candidate_source_breakdown"]["flashblocks_http_calls_ok"] = int(
                _fb_stats.get("calls_ok") or 0
            )
            payload["candidate_source_breakdown"]["flashblocks_http_logs_total"] = int(
                _fb_stats.get("logs_returned_total") or 0
            )
        except Exception:
            payload["candidate_source_breakdown"]["flashblocks_http_enabled"] = False
        try:
            payload["candidate_source_breakdown"]["tvl_scout_enabled"] = (
                os.environ.get("ARBY_TVL_SCOUT_ENABLE", "0") == "1"
            )
        except Exception:
            payload["candidate_source_breakdown"]["tvl_scout_enabled"] = False
        # E1.69 reviewer fix step 5: route_graph dump.
        # When ARBY_ROUTE_GRAPH_ENABLE=1, build PoolEdges from the TVL scout
        # output and enumerate top USDC<->X production paths so reviewers
        # can audit which multi-hop routes the system *would* score if the
        # cold scorer were wired to call the route graph.
        try:
            payload["candidate_source_breakdown"]["route_graph_enabled"] = (
                os.environ.get("ARBY_ROUTE_GRAPH_ENABLE", "0") == "1"
            )
            if payload["candidate_source_breakdown"]["route_graph_enabled"]:
                _scout_path = os.path.join(
                    os.path.dirname(_COLD_HOT_BRIDGE_PATH),
                    "m7_tvl_scout_latest.json",
                )
                if os.path.exists(_scout_path):
                    from m7.routing.route_graph import (
                        PoolEdge as _PE,
                        enumerate_paths as _ep,
                        rank_paths as _rp,
                    )
                    with open(_scout_path, "r", encoding="utf-8") as _sf:
                        _scout = json.load(_sf)
                    _edges: list = []
                    for _p in (_scout.get("pools", []) or [])[:100]:
                        _sym = _p.get("symbol") or ""
                        if "-" not in _sym:
                            continue
                        _t0, _t1 = _sym.split("-", 1)
                        _addr = _p.get("pool_address") or ""
                        _tvl = _p.get("tvl_usd") or 0.0
                        _proj = _p.get("project") or "unknown"
                        if not _addr or not _t0 or not _t1:
                            continue
                        _edges.append(
                            _PE(
                                address=_addr,
                                token0=_t0.upper(),
                                token1=_t1.upper(),
                                dex=_proj,
                                fee_bps=None,
                                tvl_usd=float(_tvl),
                            )
                        )
                    _all_paths: list = []
                    for _dst in ("WETH", "AERO", "CBBTC", "VIRTUAL"):
                        try:
                            _ps = _ep(_edges, "USDC", _dst, max_hops=3)
                            _all_paths.extend(_ps)
                        except Exception:
                            continue
                    _ranked = _rp(_all_paths)[:10]
                    payload["route_graph_top"] = [
                        {
                            "tokens": list(_rt.tokens),
                            "hops": _rt.hops,
                            "bottleneck_tvl_usd": _rt.bottleneck_tvl_usd,
                            "pool_addresses": [_pp.address for _pp in _rt.pools],
                        }
                        for _rt in _ranked
                    ]
                    payload["candidate_source_breakdown"]["route_graph_paths_top"] = len(_ranked)
        except Exception as _rge:
            payload["candidate_source_breakdown"]["route_graph_error"] = str(_rge)[:80]
        # E1.69 fix step 6: surface STF-quarantine-eligible pairs.
        # A pair is "quarantine-eligible" when its all-time sim revert count
        # exceeds the STF_QUARANTINE_THRESHOLD (default 100). Shown in the
        # bridge so reviewers can see which pairs pollute the cold funnel.
        try:
            from m7.orderflow.runtime_io import _HOT_ROLLUP_PATH as _RLP
            _stf_eligible: list[str] = []
            if os.path.exists(_RLP):
                with open(_RLP, "r", encoding="utf-8") as _rh:
                    _rl = json.load(_rh)
                _STF_THRESHOLD = int(os.environ.get("ARBY_STF_QUARANTINE_THRESHOLD", "100"))
                _stf_samples = _rl.get("cold_immediate_sim_revert_samples_recent", []) or []
                _stf_counts: dict[str, int] = {}
                for _s in _stf_samples:
                    _spair = _s.get("pair") or ""
                    if _spair and "STF" in (_s.get("reason") or ""):
                        _stf_counts[_spair] = _stf_counts.get(_spair, 0) + 1
                # Use all-time sim_revert as proxy for absolute count per pair
                _total_revert = int(_rl.get("cold_immediate_sim_revert_total") or 0)
                if _total_revert >= _STF_THRESHOLD and _stf_counts:
                    _stf_eligible = sorted(_stf_counts, key=lambda k: -_stf_counts[k])
            payload["candidate_source_breakdown"]["stf_quarantine_eligible"] = _stf_eligible
            payload["candidate_source_breakdown"]["stf_quarantine_threshold"] = int(
                os.environ.get("ARBY_STF_QUARANTINE_THRESHOLD", "100")
            )
        except Exception:
            payload["candidate_source_breakdown"]["stf_quarantine_eligible"] = []

        # E1.63 step 5: embed E1.63 split/depth metrics from rolling rollup artifact.
        try:
            from m7.orderflow.runtime_io import _HOT_ROLLUP_PATH
            if os.path.exists(_HOT_ROLLUP_PATH):
                with open(_HOT_ROLLUP_PATH, "r", encoding="utf-8") as _rf:
                    _r = json.load(_rf)
                payload["e163_split_route_attempted"] = _r.get("e163_split_route_attempted_total", 0)
                payload["e163_split_route_wins"] = _r.get("e163_split_route_win_total", 0)
                payload["e163_depth_guard_attempted"] = _r.get("e163_depth_guard_attempted_total", 0)
                payload["e163_price_impact_populated"] = _r.get("e163_price_impact_populated_total", 0)
                payload["e163_split_route_status"] = _r.get("e163_split_route_status", "UNKNOWN")
                # E1.64-5: surface E1.64 metrics in the cold-hot bridge so
                # reviewers see depth guard / USD basis / min-profit gate
                # activity without separately opening the rollup.
                payload["e164_depth_guard_rejected"] = _r.get("e164_depth_guard_rejected_total", 0)
                payload["e164_depth_math_invalid"] = _r.get("e164_depth_math_invalid_total", 0)
                payload["e164_usd_basis_missing"] = _r.get("e164_usd_basis_missing_total", 0)
                payload["e164_min_profit_rejected"] = _r.get("e164_min_profit_rejected_total", 0)
                payload["e164_depth_guard_status"] = _r.get("e164_depth_guard_status", "UNKNOWN")
                _csd = _r.get("current_session_delta")
                if isinstance(_csd, dict):
                    payload["current_session_delta"] = _csd
        except Exception:
            pass
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


def _rehydrate_hot_unresolved_pools(
    bridge: dict,
    rpc_url: str,
    block_num: int,
    max_pools: int | None = None,
) -> int:
    """P2 (2026-04-20): Fetch token0()/token1() for pools that hot lane has
    seen in events but that are not yet in ``pool_token_transport`` / the
    cross-process ``_pool_token_cache``.

    These pools show up as ``family_unresolved`` in the bridge summary and
    ``reason_if_not_hit=not_in_bridge`` in the cold_exec trace — which
    blocks scoring for any future events landing on them.

    Uses :func:`core.multicall.batch_token_info` which fetches
    ``(token0, token1, fee)`` in a single multicall3 aggregate3 call
    (3 per pool -> 1 RPC), falling back to sequential ``eth_call`` only
    when multicall fails. The resolved triple ``(t0, t1, fee)`` is injected
    into both ``_pool_token_cache`` and the bridge's ``pool_token_transport``
    so subsequent events land on resolved families with the correct fee tier.

    Bounded by ``ARBY_HOT_REHYDRATE_MAX`` (default 10) and
    ``ARBY_HOT_REHYDRATE_BUDGET_SEC`` (default 5s) to avoid RPC overuse.

    Returns: number of pools newly resolved.
    """
    import time as _time_mod

    _limit = max_pools if max_pools is not None else int(
        os.environ.get("ARBY_HOT_REHYDRATE_MAX", "10") or "10"
    )
    _budget_sec = float(os.environ.get("ARBY_HOT_REHYDRATE_BUDGET_SEC", "5") or "5")
    if _limit <= 0:
        return 0

    _unresolved_list = bridge.get("hot_seen_unresolved_pools") or []
    # Candidate addresses: unresolved=True entries sorted by seen_count desc.
    _cands: list = []
    for _row in _unresolved_list:
        if not isinstance(_row, dict):
            continue
        if _row.get("resolved"):
            continue
        _pa = (_row.get("pool_address") or "").lower()
        if not _pa.startswith("0x") or len(_pa) != 42:
            continue
        _cands.append((_pa, int(_row.get("seen_count", 0) or 0)))
    if not _cands:
        return 0
    _cands.sort(key=lambda kv: kv[1], reverse=True)

    try:
        from web3 import Web3  # type: ignore
    except Exception:
        return 0

    try:
        _w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
    except Exception as exc:
        logger.debug("rehydrate: Web3 init failed: %s", str(exc)[:80])
        return 0

    try:
        from m7.orderflow.resolve import _pool_token_cache  # type: ignore
    except Exception:
        _pool_token_cache = {}

    _ptt = bridge.setdefault("pool_token_transport", {})
    _resolved = 0
    _start = _time_mod.monotonic()

    try:
        from core.rpc_rate_limiter import rpc_throttle  # type: ignore
    except Exception:
        rpc_throttle = None

    # Soak13: prefer batched multicall3 (1 RPC call for up to _limit pools
    # × 3 reads = token0/token1/fee). Falls back to sequential eth_call
    # when multicall3 unavailable or errors out.
    _mc_candidates = [_pa for _pa, _ in _cands[:_limit]]
    _mc_results: dict = {}
    try:
        from core.multicall import get_multicall_batcher  # type: ignore
        _batcher = get_multicall_batcher(rpc_url, block_num)
        _mc_results = _batcher.batch_token_info(_mc_candidates) or {}
    except Exception as _mc_exc:
        logger.debug("rehydrate: multicall batch_token_info failed: %s",
                     str(_mc_exc)[:80])
        _mc_results = {}

    for _pa, _seen in _cands[:_limit]:
        if _budget_sec > 0 and (_time_mod.monotonic() - _start) >= _budget_sec:
            logger.info(
                "rehydrate: budget %.0fs exceeded after %d pools",
                _budget_sec, _resolved,
            )
            break

        _t0_hex = None
        _t1_hex = None
        _fee = 0

        _mc_row = _mc_results.get(_pa)
        if _mc_row is not None:
            try:
                _t0_hex, _t1_hex, _fee = _mc_row  # (token0, token1, fee)
            except Exception:
                _t0_hex = _t1_hex = None
                _fee = 0

        if not (_t0_hex and _t1_hex):
            # Fallback: sequential eth_call for this pool only.
            try:
                _addr_cs = Web3.to_checksum_address(_pa)
            except Exception:
                continue
            try:
                if rpc_throttle is not None:
                    rpc_throttle.acquire()
                _t0_raw = _w3.eth.call({"to": _addr_cs, "data": "0x0dfe1681"}, block_num)
                if len(_t0_raw) >= 32:
                    _t0_hex = "0x" + _t0_raw[-20:].hex()
            except Exception:
                continue
            try:
                if rpc_throttle is not None:
                    rpc_throttle.acquire()
                _t1_raw = _w3.eth.call({"to": _addr_cs, "data": "0xd21220a7"}, block_num)
                if len(_t1_raw) >= 32:
                    _t1_hex = "0x" + _t1_raw[-20:].hex()
            except Exception:
                continue
            # Best-effort fee fetch (selector 0xddca3f43). V2/ve33 pools
            # revert; we tolerate and keep fee=0.
            try:
                if rpc_throttle is not None:
                    rpc_throttle.acquire()
                _fee_raw = _w3.eth.call({"to": _addr_cs, "data": "0xddca3f43"}, block_num)
                if len(_fee_raw) >= 4:
                    _fee = int.from_bytes(_fee_raw[-4:], "big")
            except Exception:
                _fee = 0

        if not (_t0_hex and _t1_hex):
            continue
        try:
            _fee_int = int(_fee) if _fee else 0
        except Exception:
            _fee_int = 0
        _triple = (_t0_hex.lower(), _t1_hex.lower(), _fee_int)
        _ptt[_pa] = _triple
        try:
            _pool_token_cache[_pa] = _triple
        except Exception:
            pass
        _resolved += 1

    if _resolved > 0:
        logger.info(
            "rehydrate: resolved token0/token1 for %d/%d hot unresolved pools",
            _resolved, min(_limit, len(_cands)),
        )
    return _resolved



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

    N6: Adds wall-clock budget (`ARBY_HOT_PREWARM_BUDGET_SEC`, default 30s).
    Sequential preload_pair costs ~2-3s per pair on public RPC; without a
    budget, 60 pairs = 180s prewarm which starves run_ws_live of its time
    budget inside a 5-minute soak window.  Priority pools always run first
    so cold_executable candidates still get covered.

    Returns number of pairs prewarmed.
    """
    import time as _time_mod

    _budget_sec = float(os.environ.get("ARBY_HOT_PREWARM_BUDGET_SEC", "30"))
    _start = _time_mod.monotonic()

    from core.rpc_rate_limiter import rpc_throttle

    ptt = bridge.get("pool_token_transport", {})
    if not ptt:
        return 0
    count = 0
    _seen_pairs: set = set()
    _budget_exceeded = False

    _priority = priority_pools or set()
    _items = sorted(
        ptt.items(),
        key=lambda kv: (0 if kv[0].lower() in _priority else 1),
    )

    for pa, triple in _items:
        if count >= max_pairs:
            break
        # N6: wall-clock budget guard — stop preloading if we've run over
        if _budget_sec > 0 and (_time_mod.monotonic() - _start) >= _budget_sec:
            _budget_exceeded = True
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
        except Exception as _pp_exc:
            logger.warning(
                "Bridge prewarm preload_pair failed pair=%s err=%s",
                pair_key, str(_pp_exc)[:120],
            )

    if _budget_exceeded:
        logger.info(
            "Bridge prewarm: budget %.0fs exceeded after %d pairs (ptt=%d)",
            _budget_sec, count, len(ptt),
        )

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


def _refresh_zero_liquidity_entries(registry, rpc_url: str, block_num: int) -> int:
    """E1.26b / E1.53: Refresh registry entries that are not active.

    Covers two cases:
    1. sqrt_price_x96>0 AND liquidity=0: CL pools temporarily out of range.
    2. sqrt_price_x96=0/None AND liquidity=0/None: PTT-injected pools whose
       initial multicall state read returned empty (Aerodrome CL, BaseSwap,
       other non-standard V3 forks). These need a second read attempt once
       the block is confirmed.

    Bounded to ARBY_ZLR_MAX_POOLS (default 150) to avoid oversized multicall
    batches. Candidate pools sorted: fully-unread (sqrt=0) first so the most
    broken get fixed first.

    Returns the number of entries updated to non-zero liquidity.
    """
    _max_pools = int(os.environ.get("ARBY_ZLR_MAX_POOLS", "150") or 150)
    zero_liq_addrs: list = []  # (priority, address)
    addr_to_entry: dict = {}
    for entries_list in registry._pools.values():
        for e in entries_list:
            _has_sqrtp = bool(e.sqrt_price_x96 and e.sqrt_price_x96 > 0)
            _has_liq = bool(e.liquidity and e.liquidity > 0)
            if not _has_liq:
                # priority 0 = completely unread (needs fix most urgently)
                # priority 1 = has sqrtPrice but no liquidity (CL out-of-range)
                prio = 1 if _has_sqrtp else 0
                zero_liq_addrs.append((prio, e.address))
                addr_to_entry[e.address] = e

    if not zero_liq_addrs:
        return 0

    # Sort: unread pools first, then sqrtP-only pools; cap to max
    zero_liq_addrs.sort(key=lambda x: x[0])
    zero_liq_addrs = zero_liq_addrs[:_max_pools]
    candidate_addrs = [a for _, a in zero_liq_addrs]
    logger.debug(
        "zero-liq refresh: %d candidates (unread=%d, out-of-range=%d), max=%d",
        len(candidate_addrs),
        sum(1 for p, _ in zero_liq_addrs if p == 0),
        sum(1 for p, _ in zero_liq_addrs if p == 1),
        _max_pools,
    )

    try:
        from core.multicall import get_multicall_batcher
        batcher = get_multicall_batcher(rpc_url, block_num)
        fresh_states = batcher.batch_full_pool_data(candidate_addrs)
        refreshed = 0
        for addr, state in fresh_states.items():
            if state and state.get("liquidity", 0) > 0:
                entry = addr_to_entry.get(addr)
                if entry:
                    entry.liquidity = state["liquidity"]
                    entry.sqrt_price_x96 = state.get("sqrt_price_x96") or entry.sqrt_price_x96
                    if state.get("tick") is not None:
                        entry.tick = state["tick"]
                    entry.last_block = block_num
                    refreshed += 1
        if refreshed > 0:
            logger.info(
                "zero-liq refresh: recovered %d/%d inactive pools",
                refreshed, len(candidate_addrs),
            )
        return refreshed
    except Exception as exc:
        logger.debug("zero-liq refresh failed: %s", str(exc)[:80])
        return 0


def _prewarm_registry_from_pairs(
    registry, session_pairs: dict, token_addresses: dict,
    dex_configs: dict, rpc_url: str, block_num: int,
) -> int:
    """Prewarm registry using accumulated session_low_lag_pairs.

    Returns number of pairs prewarmed.

    N9: wall-clock budget via ARBY_HOT_PAIR_PREWARM_BUDGET_SEC (default 20s).
    Each preload_pair can take 2-4s via public RPC — without a budget the
    loop can block the entire hot-phase for 40+ seconds on 13 pairs.

    M7.E1.34n (soak8) fix #6: we also surface rejection counters (pairs
    whose symbols are not present in token_addresses, preload failures)
    via module-global _LAST_PREWARM_STATS so the rollup writer can attribute
    "discovery registered N pairs, rejected M (TOKEN_ADDRESS_UNKNOWN)".
    """
    import time as _time_mod
    _budget_sec = float(os.environ.get("ARBY_HOT_PAIR_PREWARM_BUDGET_SEC", "20"))
    _start = _time_mod.monotonic()
    count = 0
    _skipped_missing_tokens = 0
    _skipped_malformed = 0
    _preload_failures = 0
    for pair_key, info in session_pairs.items():
        if _budget_sec > 0 and (_time_mod.monotonic() - _start) >= _budget_sec:
            logger.info(
                "Pair prewarm: budget %.0fs exceeded after %d pairs (remaining=%d)",
                _budget_sec, count, max(0, len(session_pairs) - count),
            )
            break
        if "/" not in pair_key:
            _skipped_malformed += 1
            continue
        sym_a, sym_b = pair_key.split("/", 1)
        addr_a = token_addresses.get(sym_a, "")
        addr_b = token_addresses.get(sym_b, "")
        if not addr_a or not addr_b:
            _skipped_missing_tokens += 1
            continue
        try:
            registry.preload_pair(addr_a, addr_b, dex_configs, rpc_url, block_num)
            count += 1
        except Exception:
            _preload_failures += 1
    globals()["_LAST_PREWARM_STATS"] = {
        "prewarmed": count,
        "skipped_missing_tokens": _skipped_missing_tokens,
        "skipped_malformed_pair": _skipped_malformed,
        "preload_failures": _preload_failures,
        "candidates_considered": len(session_pairs),
    }
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
