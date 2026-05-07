"""
E1.12.2 Phase 2 — Loop runner: main M7 orderflow iteration loop.

Extracted from scripts/m7a_orderflow_loop.py.  Contains:
  - LoopState         — dataclass holding cross-iteration persistent state
  - _apply_lane_defaults / _build_ws_args — CLI helpers
  - run_loop()        — continuous ws-live loop dispatcher
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from core.logging import get_logger
import m7.orderflow.runtime_io as _rio
from m7.orderflow.runtime_io import (
    _atomic_json_write,
    _read_promoted_pairs,
    _write_promoted_pairs,
    _read_discovery_scoreboard,
    _update_discovery_scoreboard,
    _write_discovery_scoreboard,
)
from m7.orderflow.mode_ws_live import run_ws_live, _write_rolling_m7
from m7.orderflow.bridge_runtime import (
    _write_cold_hot_bridge,
    _read_cold_hot_bridge,
    _populate_pool_token_cache_from_bridge,
    _prewarm_registry_from_bridge,
    _prewarm_registry_from_pairs,
    _promote_pairs_from_cold,
)
from m7.orderflow.execution_gate import run_execution_gate
from m7.orderflow.hot_runtime_artifacts import (
    _write_hot_heartbeat_on_error,
    _write_hot_artifact,
    _write_hot_intents,
    _update_hot_rollup,
)
from m7.shared.constants import get_prewarm_pairs

logger = get_logger("m7.orderflow.loop_runner")


# ---------------------------------------------------------------------------
# LoopState: cross-iteration persistent state
# ---------------------------------------------------------------------------
@dataclass
class LoopState:
    """Persistent state that survives across hot/cold iterations.

    Future: run_hot_iteration() and run_cold_iteration() will accept
    LoopState as their primary mutable argument.
    """

    accumulated_pairs: dict = field(default_factory=dict)
    hot_registry: Any = None
    cold_registry: Any = None
    cold_pair_stats: dict = field(default_factory=dict)
    promoted_pairs: dict = field(default_factory=lambda: {"candidate": [], "execution": []})
    cold_active_pools: dict = field(default_factory=dict)
    hot_active_pools: dict = field(default_factory=dict)
    resolved_from_hot_seen_total: int = 0
    stale_pin_ttl: dict = field(default_factory=dict)
    hot_seen_pin: dict = field(default_factory=dict)
    iteration: int = 0
    seed_pairs: list = field(default_factory=list)

    # TTL constants
    STALE_PIN_TTL_INIT: int = 4
    HOT_SEEN_PIN_TTL_INIT: int = 3


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



def run_loop(cli_args) -> None:
    """Run the continuous ws-live loop."""
    _apply_lane_defaults(cli_args)
    ws_args = _build_ws_args(cli_args)
    iterations = cli_args.iterations
    pause = cli_args.pause
    lane = cli_args.lane
    profile = getattr(cli_args, "profile", "production")
    _rio._init_artifact_paths(profile)  # M7.E1.9.1: namespace isolation
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

    # E1.19a: Track whether hot registry has been warmed successfully.
    # After first successful bridge prewarm, skip RPC-heavy prewarm on
    # subsequent iterations — registry cache + stale_threshold handles
    # state refresh internally, avoiding dRPC 429 from repeated block_number calls.
    _registry_warmed = False
    # E1.22: Track bridge PTT size at last prewarm to detect new bridge data
    # arriving after cold lane runs (chicken-and-egg: hot iter 1 has empty bridge,
    # cold writes bridge after iter 1, hot iter 2+ needs re-prewarm).
    _bridge_prewarmed_ptt_count = 0
    # E1.26b: Cache RPC URL from prewarm for periodic zero-liq refresh
    _hot_rpc: str = ""

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

        # E1.49: stamp cycle_window_started_at on hot iteration start so
        # mid-cycle heartbeats anchor elapsed-seconds against the right
        # boundary (per reviewer 30m soak verdict 2026-04-30).
        if lane == "hot":
            try:
                from m7.orderflow.hot_runtime_artifacts import (
                    reset_cycle_window_marker as _reset_marker,
                )
                _reset_marker(chain=cli_args.chain)
            except Exception as _exc_marker:
                logger.debug(
                    "cycle marker reset skipped: %s", str(_exc_marker)[:80]
                )

        # E1.49 canary fix: also bump periodic_heartbeats_total at iteration
        # boundary. The mid-cycle heartbeat in mode_ws_live only runs after
        # successful WS subscribe — under drpc 429 storms the subscribe
        # itself never completes, so the reviewer cadence guard would never
        # see heartbeat deltas. Stamping at iteration start guarantees
        # cadence visibility regardless of WS health.
        if lane == "hot":
            try:
                import time as _t_iter
                from m7.orderflow.hot_runtime_artifacts import (
                    heartbeat_hot_rollup_cycle as _hb_iter,
                )
                _hb_iter(
                    cycle_started_monotonic=_t_iter.monotonic(),
                    chain=cli_args.chain,
                )
            except Exception as _exc_hb_iter:
                logger.debug(
                    "iteration-boundary heartbeat skipped: %s",
                    str(_exc_hb_iter)[:80],
                )

        try:
            # M7.A.5.39: Lane-specific registry init + prewarm
            _ext_registry = None
            if lane == "hot":
                logger.info("hot-phase: enter lane=hot iter=%d", iteration)
                if _hot_registry is None:
                    from m7.orderflow.pool_registry import PoolRegistry
                    # E1.19: Hot registry uses 150-block stale threshold (~37s
                    # on Base 2s blocks). Default 10 blocks was causing 600+ RPC
                    # calls per iteration as every pool refreshed on each cycle.
                    # ENV override: ARBY_HOT_STALE_BLOCKS (default 150).
                    _hot_stale = int(os.environ.get("ARBY_HOT_STALE_BLOCKS", "150"))
                    _hot_registry = PoolRegistry(stale_threshold_blocks=_hot_stale)
                _ext_registry = _hot_registry

                # M7.A.5.43: Bridge-first hot prewarm.
                # 1. Read cold→hot bridge (pool_token_transport + candidates)
                # 2. Populate _pool_token_cache from bridge (cross-process cache fix)
                # 3. Prewarm registry from bridge token addresses (pool-address-first)
                # 4. Fall back to symbol-pair prewarm for seeds / accumulated pairs
                logger.info("hot-phase: reading cold->hot bridge")
                _bridge = _read_cold_hot_bridge()
                _bridge_ptt_raw = _bridge.get("pool_token_transport", {})
                logger.info("hot-phase: populating pool_token_cache (ptt=%d)",
                             len(_bridge_ptt_raw))
                _bridge_cache_count = _populate_pool_token_cache_from_bridge(_bridge)
                _bridge_prewarm_count = 0
                logger.info("hot-phase: bridge_cache_count=%d", _bridge_cache_count)

                # E1.55: When bridge PTT is empty (cold lane not yet written its
                # first window), force-reload the persistent pool-token cache from
                # disk.  Cold writes _pool_token_cache.json earlier than it writes
                # the full bridge, so a late-joining hot process can recover token
                # resolution even before the first cold→hot bridge appears.
                _persistent_force_reload_count = 0
                if _bridge_cache_count == 0:
                    try:
                        from m7.orderflow.resolve import (
                            force_reload_persistent_pool_token_cache as _frl,
                            _pool_token_cache as _ptc_check,
                        )
                        if not _ptc_check:
                            _persistent_force_reload_count = _frl()
                            if _persistent_force_reload_count > 0:
                                logger.info(
                                    "hot: E1.55 force-reloaded persistent cache: %d entries",
                                    _persistent_force_reload_count,
                                )
                            else:
                                logger.info(
                                    "hot: E1.55 persistent cache also empty "
                                    "(cold lane first run still in progress)"
                                )
                    except Exception as _frl_exc:
                        logger.debug(
                            "hot: E1.55 persistent cache force-reload skipped: %s",
                            str(_frl_exc)[:80],
                        )

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

                # M7.E1.47/P1b: Hot consumer of tier_map. Hot-tier pools (seen in
                # current cold cycle) are merged into priority prewarm queue
                # alongside cold_executable + near_executable. This widens the
                # net beyond profit-thresholded executables to also catch
                # active pools that haven't yet crossed the executable bar.
                # Pure additive — does not change WS subscription topology.
                _tier_hot_count = 0
                _tier_hot_in_ptt = 0
                _tier_hot_added = 0
                try:
                    from discovery.tier_classifier import read_tier_map_artifact
                    _tm = read_tier_map_artifact(chain=cli_args.chain)
                    _tier_hot_list = _tm.get("hot", []) or []
                    _tier_hot_count = len(_tier_hot_list)
                    _ptt_keys = {
                        k.lower() for k in _bridge.get("pool_token_transport", {}).keys()
                    }
                    for _addr in _tier_hot_list:
                        _addr_low = (_addr or "").lower()
                        if not _addr_low:
                            continue
                        if _addr_low in _ptt_keys:
                            _tier_hot_in_ptt += 1
                        if _addr_low not in _cold_exec_pools:
                            _cold_exec_pools.add(_addr_low)
                            _tier_hot_added += 1
                    if _tier_hot_count > 0:
                        logger.info(
                            "tier_map consumed: hot=%d in_ptt=%d added_priority=%d",
                            _tier_hot_count, _tier_hot_in_ptt, _tier_hot_added,
                        )
                except Exception as _tm_exc:
                    logger.debug("tier_map read failed: %s", str(_tm_exc)[:120])

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

                # M7.E1.47/P2: DISC -> PROD promotion. PROD hot lane reads
                # DISC-side rolling artifacts (scoreboard + promoted_pairs)
                # and merges qualifying pair_keys into the prewarm queue.
                # Pure additive read; controlled by ARBY_DISC_TO_PROD=1
                # (default ON) for backward compatibility.
                if os.environ.get("ARBY_DISC_TO_PROD", "1") != "0":
                    try:
                        import json as _json_p2
                        from m7.orderflow.disc_to_prod_promotion import (
                            select_pairs_to_promote,
                        )
                        _disc_root = os.path.join(
                            "data", "runs", "_rolling"
                        )
                        _disc_sb_path = os.path.join(
                            _disc_root, "m7_discovery_scoreboard_discovery.json"
                        )
                        _disc_pp_path = os.path.join(
                            _disc_root, "m7_promoted_pairs_discovery.json"
                        )
                        _disc_sb: dict = {}
                        _disc_pp: dict = {}
                        if os.path.exists(_disc_sb_path):
                            with open(_disc_sb_path, "r", encoding="utf-8") as _fh:
                                _disc_sb = _json_p2.load(_fh) or {}
                        if os.path.exists(_disc_pp_path):
                            with open(_disc_pp_path, "r", encoding="utf-8") as _fh:
                                _disc_pp = _json_p2.load(_fh) or {}
                        # Use intent + accumulated pairs as candidate pool so
                        # family-tier promotions only emit pairs we already
                        # know about (no synthesised universes).
                        _pool = list(_hot_pairs_to_prewarm.keys())
                        _disc_promoted = select_pairs_to_promote(
                            _disc_sb, _disc_pp, candidate_pool=_pool,
                        )
                        _disc_added = 0
                        for _dp in _disc_promoted:
                            if _dp not in _hot_pairs_to_prewarm:
                                _hot_pairs_to_prewarm[_dp] = {
                                    "pair": _dp, "seen_count": 0,
                                    "source": "disc_to_prod",
                                }
                                _disc_added += 1
                        if _disc_promoted:
                            logger.info(
                                "DISC->PROD promotion: qualified=%d added=%d",
                                len(_disc_promoted), _disc_added,
                            )
                    except Exception as _p2_exc:
                        logger.debug(
                            "DISC->PROD promotion failed: %s",
                            str(_p2_exc)[:120],
                        )

                # E1.19a: Only run RPC-heavy prewarm on first iteration (cold
                # cache) or when registry hasn't been warmed yet.  After the
                # first successful prewarm, the registry handles staleness
                # internally via stale_threshold_blocks.  Skipping avoids a
                # fresh eth.block_number HTTP call to dRPC every iteration,
                # which was hanging on 429 after iter-1 exhausted the rate limit.
                # E1.22: Re-prewarm when bridge has NEW PTT entries (cold lane
                # writes bridge after hot iter 1; hot iter 2+ needs those pools).
                _current_ptt_count = len(_bridge.get("pool_token_transport", {}))
                _need_prewarm = (
                    not _registry_warmed
                    or (_current_ptt_count > _bridge_prewarmed_ptt_count)
                )
                if _need_prewarm:
                    logger.info("hot-phase: entering prewarm block")
                    try:
                        from config import load_dexes, get_all_token_addresses
                        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
                        _chain_id = _CHAIN_KEY_TO_ID.get(cli_args.chain.lower())
                        _rpc, _, _ = resolve_rpc_http(
                            chain_id=_chain_id, network=cli_args.chain,
                            env=dict(os.environ),
                        )
                        logger.info("hot-phase: rpc resolved=%s", bool(_rpc))
                        if _rpc:
                            from web3 import Web3 as _W3
                            # E1.19a: 10s timeout prevents hanging on dRPC 429
                            _block = _W3(_W3.HTTPProvider(
                                _rpc, request_kwargs={"timeout": 10},
                            )).eth.block_number
                            logger.info("hot-phase: block=%d", _block)
                            _hot_rpc = _rpc  # E1.26b: cache for zero-liq refresh
                            _all_dexes = load_dexes()
                            _dex_cfg = _all_dexes.get(cli_args.chain, {})
                            _token_addr = get_all_token_addresses(cli_args.chain)

                            # M7.A.5.45: Bridge-first prewarm with cold_executable priority
                            if _bridge.get("pool_token_transport"):
                                logger.info("hot-phase: starting bridge prewarm (ptt=%d)",
                                            len(_bridge.get("pool_token_transport", {})))
                                _bridge_prewarm_count = _prewarm_registry_from_bridge(
                                    _hot_registry, _bridge, _dex_cfg, _rpc, _block,
                                    priority_pools=_cold_exec_pools,
                                )
                                logger.info("hot-phase: bridge prewarm done=%d", _bridge_prewarm_count)

                            # P2 (2026-04-20): rehydrate token0/token1 for hot-seen
                            # pools missing from PTT (family_unresolved). Controlled by
                            # ARBY_HOT_REHYDRATE=1 (default on).
                            if os.environ.get("ARBY_HOT_REHYDRATE", "1") != "0":
                                try:
                                    from m7.orderflow.bridge_runtime import (
                                        _rehydrate_hot_unresolved_pools,
                                    )
                                    _rh = _rehydrate_hot_unresolved_pools(
                                        _bridge, _rpc, _block,
                                    )
                                    if _rh:
                                        logger.info(
                                            "hot-phase: rehydrated %d unresolved pools",
                                            _rh,
                                        )
                                except Exception as _rh_exc:
                                    logger.debug(
                                        "hot-phase: rehydrate failed: %s",
                                        str(_rh_exc)[:120],
                                    )

                            # Legacy symbol-pair prewarm for seeds and accumulated pairs
                            if _hot_pairs_to_prewarm:
                                logger.info("hot-phase: starting pair prewarm (n=%d)",
                                            len(_hot_pairs_to_prewarm))
                                _pw = _prewarm_registry_from_pairs(
                                    _hot_registry, _hot_pairs_to_prewarm,
                                    _token_addr, _dex_cfg, _rpc, _block,
                                )
                                logger.info("hot-phase: pair prewarm done=%d", _pw)
                            else:
                                _pw = 0
                            logger.info(
                                "Hot prewarm: bridge_cache=%d bridge_registry=%d "
                                "symbol_pairs=%d/%d (iter %d, cross=%d, ptt=%d)",
                                _bridge_cache_count, _bridge_prewarm_count,
                                _pw, len(_hot_pairs_to_prewarm), iteration,
                                len(_cross_promoted.get("candidate", [])),
                                _current_ptt_count,
                            )
                            _registry_warmed = True
                            _bridge_prewarmed_ptt_count = _current_ptt_count
                    except Exception as _pw_exc:
                        # E1.34i: elevate hot prewarm failure to warning so
                        # soak artifacts surface the root cause of 0 prewarms.
                        logger.warning(
                            "Hot prewarm failed iter=%d err=%s",
                            iteration, str(_pw_exc)[:200],
                        )
                else:
                    logger.info(
                        "Hot prewarm skipped (registry warm, iter %d, "
                        "bridge_cache=%d)",
                        iteration, _bridge_cache_count,
                    )

                # E1.26b / E1.53: Periodic refresh of zero-liquidity CL pools
                # AND fully-unread PTT-injected pools (sqrt_price_x96=0).
                # E1.50 / TD-003: throttle to every Nth iteration.
                # Default reduced to 1 (every iteration) so that the 526 PTT
                # direct-inject pools whose state reads failed at prewarm time
                # get recovered quickly. Once recovered their liquidity>0 and
                # ZLR skips them, so the cost quickly drops to near-zero.
                # Operators can set ARBY_HOT_ZLR_EVERY_N_ITERS=3 to restore
                # original throttling after a warm run.
                _zlr_every_n = max(
                    1,
                    int(os.environ.get("ARBY_HOT_ZLR_EVERY_N_ITERS", "1") or 1),
                )
                if _hot_registry is not None and _hot_rpc and (iteration % _zlr_every_n == 0 or iteration == 1):
                    try:
                        from web3 import Web3 as _W3_zlr
                        _zlr_block = _W3_zlr(_W3_zlr.HTTPProvider(
                            _hot_rpc, request_kwargs={"timeout": 10},
                        )).eth.block_number
                        from m7.orderflow.bridge_runtime import (
                            _refresh_zero_liquidity_entries,
                        )
                        _zlr_count = _refresh_zero_liquidity_entries(
                            _hot_registry, _hot_rpc, _zlr_block,
                        )
                        if _zlr_count > 0:
                            logger.info(
                                "hot-phase: refreshed %d zero-liq CL pools (iter %d)",
                                _zlr_count, iteration,
                            )
                    except Exception as _zlr_exc:
                        logger.debug(
                            "hot-phase: zero-liq refresh error: %s",
                            str(_zlr_exc)[:80],
                        )
                elif _hot_registry is not None and _hot_rpc:
                    logger.debug(
                        "hot-phase: zero-liq refresh throttled (iter %d, every_n=%d)",
                        iteration, _zlr_every_n,
                    )
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
                            _block = _W3(_W3.HTTPProvider(
                                _rpc, request_kwargs={"timeout": 10},
                            )).eth.block_number
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
                    ][:40]  # E1.25: raised from 20→40 to cover more hot-seen pools
                    # Also source hot-seen pools directly from hot rollup
                    # (cross-process) to avoid 1-iteration delay via bridge
                    if not _unresolved_addrs:
                        try:
                            if os.path.exists(_rio._HOT_ROLLUP_PATH):
                                from m7.orderflow.resolve import _pool_token_cache as _ptc_check
                                with open(_rio._HOT_ROLLUP_PATH, "r", encoding="utf-8") as _rrf:
                                    _rollup_check = json.load(_rrf)
                                for _rp in _rollup_check.get("hot_seen_pool_histogram_top", []):
                                    _rp_addr = (_rp.get("pool") or "").lower()
                                    if _rp_addr and _rp_addr not in _ptc_check:
                                        _unresolved_addrs.append(_rp_addr)
                                _unresolved_addrs = _unresolved_addrs[:40]
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
                            _block_hr = _W3_hr(_W3_hr.HTTPProvider(
                                _rpc_hr, request_kwargs={"timeout": 10},
                            )).eth.block_number
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
                        # E1.53 (2026-05-02): cap is env-configurable via
                        # ARBY_BRIDGE_POOL_CAP / ARBY_BRIDGE_POOL_CAP_GAP so
                        # operators can lift the artificial 50-pool ceiling
                        # when the broader funnel can absorb more attention.
                        _rollup_wwe = 0
                        _rollup_wwbh = 0
                        try:
                            if os.path.exists(_rio._HOT_ROLLUP_PATH):
                                with open(_rio._HOT_ROLLUP_PATH, "r", encoding="utf-8") as _rf:
                                    _rl = json.load(_rf)
                                _rollup_wwe = _rl.get("windows_with_events", 0)
                                _rollup_wwbh = _rl.get("windows_with_bridge_hits", 0)
                        except Exception:
                            pass
                        _cap_default = max(1, int(os.environ.get(
                            "ARBY_BRIDGE_POOL_CAP", "200") or 200))
                        _cap_gap = max(1, int(os.environ.get(
                            "ARBY_BRIDGE_POOL_CAP_GAP", "300") or 300))
                        _pool_cap = _cap_gap if (_rollup_wwe > 0 and _rollup_wwbh == 0) else _cap_default
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

                        # E1.56 Step 7: pool-level gas-hopeless quarantine.
                        # Family-level (above) is conservative — one bad pool in
                        # a family can spare the others. Pool-level tracks
                        # consecutive `GAS_EXCEEDS_GROSS` per pool address and
                        # quarantines the pool after `_POOL_GAS_HOPELESS_STREAK`
                        # consecutive windows. Backward-compatible: default
                        # streak=3, set 0 to disable entirely.
                        _POOL_GAS_HOPELESS_STREAK = max(0, int(os.environ.get(
                            "ARBY_POOL_GAS_HOPELESS_STREAK", "3") or 3))
                        _pool_gas_kills_now: dict = {}
                        _pool_gas_pos_now: set = set()
                        for _cand in _bridge.get("candidates", []):
                            _pgp_pa = (_cand.get("pool_address") or "").lower()
                            if not _pgp_pa:
                                continue
                            if _cand.get("reject_reason") == "GAS_EXCEEDS_GROSS":
                                _gfg2 = _cand.get("gas_floor_gap_bps")
                                _pool_gas_kills_now[_pgp_pa] = (
                                    float(_gfg2) if _gfg2 is not None else 0.0
                                )
                            elif (_cand.get("net_bps") or 0) > 0:
                                _pool_gas_pos_now.add(_pgp_pa)
                        _prev_streak = dict(_bridge.get("pool_gas_hopeless_streak", {}) or {})
                        _new_streak: dict = {}
                        # Pools currently gas-killed: streak += 1 (or start at 1)
                        for _pgp_pa, _gap in _pool_gas_kills_now.items():
                            _new_streak[_pgp_pa] = int(_prev_streak.get(_pgp_pa, 0)) + 1
                        # Pools currently positive: explicit reset to 0 (cleared)
                        for _pgp_pa in _pool_gas_pos_now:
                            _new_streak[_pgp_pa] = 0
                        # Pools previously tracked but absent this window: keep streak
                        # but cap age to avoid unbounded growth.
                        for _old_pa, _old_streak in _prev_streak.items():
                            if _old_pa in _new_streak:
                                continue
                            _kept = int(_old_streak)
                            if _kept > 0 and _kept < 100:
                                _new_streak[_old_pa] = _kept
                        _pool_gas_hopeless: set = set()
                        if _POOL_GAS_HOPELESS_STREAK > 0:
                            for _pgp_pa, _streak_v in _new_streak.items():
                                if int(_streak_v) >= _POOL_GAS_HOPELESS_STREAK:
                                    _pool_gas_hopeless.add(_pgp_pa)

                        # M7.A.5.47f: Diversity-aware fill — max _FAMILY_CAP pools
                        # per token-pair family to prevent one family from monopolizing
                        # the focused filter and cementing concentration.
                        # E1.53: cap is env-configurable via ARBY_BRIDGE_FAMILY_CAP
                        # (default raised 8 -> 16 to widen surface area).
                        _FAMILY_CAP = max(1, int(os.environ.get(
                            "ARBY_BRIDGE_FAMILY_CAP", "16") or 16))
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
                        _c3_pool_gas_hopeless_skipped = 0
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
                            # E1.56 Step 7: skip pool-level gas-hopeless even if
                            # family is still viable — a single recurrent loser
                            # pool in an otherwise viable family.
                            if _rpa in _pool_gas_hopeless:
                                _c3_pool_gas_hopeless_skipped += 1
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
            logger.info("hot-phase: invoking run_ws_live (lane=%s iter=%d)", lane, iteration)
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
            # Fix 8 (E1.60): add scan timing + coverage counts so reviewers
            # can see per-window cold scan duration and universe coverage.
            _reg_stats = artifact.get("registry_session_stats") or {}
            _duration_s: float = 0.0
            try:
                from datetime import datetime as _dt, timezone as _tz
                _ts_a = _dt.strptime(window_started_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
                _ts_b = _dt.strptime(window_ended_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_tz.utc)
                _duration_s = round((_ts_b - _ts_a).total_seconds(), 1)
            except Exception:
                pass
            artifact["m7_loop_context"] = {
                "lane": lane,
                "loop_iteration": iteration,
                "window_started_at": window_started_at,
                "window_ended_at": window_ended_at,
                "window_empty": window_empty,
                # Fix 8: scan coverage/timing fields (meaningful for cold lane)
                "full_universe_scan_started_at": window_started_at if lane == "cold" else None,
                "full_universe_scan_ended_at": window_ended_at if lane == "cold" else None,
                "full_universe_scan_duration_s": _duration_s if lane == "cold" else None,
                "pairs_scanned": _reg_stats.get("unique_pairs_queried") if lane == "cold" else None,
                "pools_scanned": _reg_stats.get("pools_active") if lane == "cold" else None,
            }

            # M7.A.5.31: Run profit guard on hot lane results
            guard_results = None
            fast_results = None
            _gate_result = None  # E1.12.2: execution gate result
            if lane == "hot":
                # E1.12.2: Run full execution gate (profit_guard → sim → submit)
                # E1.53: pass profile so discovery lane uses ARBY_SIM_BACKEND_DISC
                _gate_result = run_execution_gate(
                    artifact.get("_raw_results", artifact.get("results", [])),
                    chain=cli_args.chain,
                    profile=profile,
                )
                guard_results = _gate_result.guard_passed

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

                # E1.56 Step 1: cold-positive immediate sim queue.
                # When hot WS stream is dominated by thin-spread pools and
                # never delivers cold-positive pools, we never call sim. The
                # cold-immediate lane converts bridge `cold_executable`
                # entries into synthetic candidates and runs them through
                # the SAME execution_gate. Strictly opt-in via
                # ARBY_COLD_IMMEDIATE_SIM=1 (default OFF, full back-compat).
                _cold_immediate_counters = {
                    "cold_immediate_sim_input_count": 0,
                    "cold_immediate_sim_attempted": 0,
                    "cold_immediate_sim_passed": 0,
                    "cold_immediate_sim_profitable": 0,
                    # E1.57 fix steps #1/#2: roundtrip canonicalization counters.
                    # When a cold_immediate candidate passes the full buy+sell
                    # round-trip simulation, it is canonical evidence of
                    # profitability and should contribute to roundtrip_profitable_total.
                    "cold_immediate_roundtrip_attempted": 0,
                    "cold_immediate_roundtrip_profitable": 0,
                }
                try:
                    # E1.59 bridge-refresh: re-read bridge each iteration so
                    # cold_immediate_sim sees candidates written AFTER hot lane
                    # initialized (cold lane typically writes bridge ~15 min after
                    # hot lane starts, so the init-time snapshot is always empty).
                    try:
                        _bridge = _read_cold_hot_bridge()
                    except Exception:
                        pass
                    from m7.orderflow.cold_immediate_sim import (
                        is_enabled as _ci_enabled,
                        queue_cold_executable_for_sim,
                    )
                    if _ci_enabled():
                        _ci_gate, _cold_immediate_counters = queue_cold_executable_for_sim(
                            _bridge if '_bridge' in dir() else {},
                            chain=cli_args.chain,
                            profile=profile,
                        )
                        if _ci_gate is not None:
                            # E1.57 fix steps #1/#2: extract roundtrip counters
                            # from the cold_immediate gate result so that the
                            # hot_runtime_artifacts rollup can canonicalize them.
                            _cold_immediate_counters["cold_immediate_roundtrip_attempted"] = (
                                int(getattr(_ci_gate, "roundtrip_attempted", 0) or 0)
                            )
                            _cold_immediate_counters["cold_immediate_roundtrip_profitable"] = (
                                int(getattr(_ci_gate, "roundtrip_profitable_count", 0) or 0)
                            )
                            # E1.58 fix step #8: surface CI roundtrip bps so the
                            # rollup buffer (_roundtrip_profit_bps_all) gets samples
                            # from the cold_immediate path. Without this the
                            # best/worst/median values stay null even when the
                            # CI roundtrip path produces profitable canonical results.
                            _ci_rt_bps = list(
                                getattr(_ci_gate, "roundtrip_profit_bps_values", []) or []
                            )
                            if _ci_rt_bps:
                                _cold_immediate_counters[
                                    "cold_immediate_roundtrip_profit_bps_values"
                                ] = _ci_rt_bps
                            # E1.58 fix step #1 (runtime): CI gate's submit_ready
                            # was previously computed but ignored — main rollup
                            # only consumed gate_result.submit_ready from the
                            # main hot path. Surface CI submit_ready here so
                            # ARBY_PAPER_SIGNING=1 actually drives
                            # submit_ready_total > 0 when the CI roundtrip path
                            # is the canonical producer of profitable, sim-passed
                            # candidates.
                            _cold_immediate_counters["cold_immediate_submit_ready"] = (
                                int(getattr(_ci_gate, "submit_ready", 0) or 0)
                            )
                            logger.info(
                                "cold_immediate_sim: input=%d attempted=%d passed=%d profitable=%d rt_att=%d rt_prof=%d",
                                _cold_immediate_counters["cold_immediate_sim_input_count"],
                                _cold_immediate_counters["cold_immediate_sim_attempted"],
                                _cold_immediate_counters["cold_immediate_sim_passed"],
                                _cold_immediate_counters["cold_immediate_sim_profitable"],
                                _cold_immediate_counters["cold_immediate_roundtrip_attempted"],
                                _cold_immediate_counters["cold_immediate_roundtrip_profitable"],
                            )
                            # Surface counts in the hot artifact's signal_counts
                            # so the rolling rollup can aggregate over windows.
                            _sc_ci = artifact.get("signal_counts", {})
                            _sc_ci.update(_cold_immediate_counters)
                            artifact["signal_counts"] = _sc_ci
                except Exception as _ci_exc:
                    logger.debug(
                        "cold_immediate_sim: skipped (%s)",
                        type(_ci_exc).__name__,
                    )

            if lane == "cold":
                # E1.22: Run full execution gate on cold lane results
                # (profit guard already annotated in mode_ws_live; gate adds sim + submit)
                # E1.53: pass profile so discovery lane uses ARBY_SIM_BACKEND_DISC
                _raw = artifact.get("_raw_results", [])
                if _raw:
                    _gate_result = run_execution_gate(_raw, chain=cli_args.chain, profile=profile)
                    guard_results = _gate_result.guard_passed
                    # Post-patch signal_counts with sim/submit from gate
                    _sc = artifact.get("signal_counts", {})
                    _sc["sim_passed"] = _gate_result.sim_passed
                    _sc["submit_ready"] = _gate_result.submit_ready
                    if _gate_result.guard_passed:
                        logger.info(
                            "Cold execution gate: %d guard_passed, %d sim_passed, %d submit_ready",
                            len(_gate_result.guard_passed),
                            _gate_result.sim_passed,
                            _gate_result.submit_ready,
                        )

                    # Live execution: only when ARBY_PAPER_SIGNING=0 AND
                    # ARBY_LIVE_EXECUTION_ACK=YES AND submit_ready > 0.
                    # All further kill-switch / key checks are inside signer.
                    _live_enabled = (
                        os.environ.get("ARBY_PAPER_SIGNING", "1").strip() == "0"
                        and os.environ.get("ARBY_LIVE_EXECUTION_ACK", "").strip() == "YES"
                        and _gate_result.submit_ready > 0
                    )
                    if not _live_enabled and _gate_result.submit_ready > 0:
                        # Surface the block reason in rollup so dashboard can show it
                        _sc["live_exec_blocked_reason"] = (
                            "ARBY_PAPER_SIGNING=1"
                            if os.environ.get("ARBY_PAPER_SIGNING", "1") != "0"
                            else "ARBY_LIVE_EXECUTION_ACK_NOT_SET"
                        )
                    if _live_enabled:
                        _submit_candidates = [
                            r for r, _g in _gate_result.guard_passed
                            if getattr(r, "submit_ready", False)
                        ]
                        if _submit_candidates:
                            import asyncio as _asyncio  # noqa: PLC0415
                            from execution.signer import make_sign_and_send, get_signer_address  # noqa: PLC0415
                            from execution.dex_dex_executor import DexDexExecutor  # noqa: PLC0415
                            from chains.providers import RPCProvider  # noqa: PLC0415
                            _executor = DexDexExecutor()
                            _rpc_url = os.environ.get("ARBY_RPC_URL_HTTP", "")
                            _provider = RPCProvider(_rpc_url) if _rpc_url else None

                            # Bounded live mode guards (Step 8 — reviewer requirement)
                            _max_trades = int(os.environ.get("ARBY_MAX_TRADES_PER_DAY", "1"))
                            _max_loss_usd = float(os.environ.get("ARBY_MAX_LOSS_USD", "5.0"))
                            _max_gas_usd = float(os.environ.get("ARBY_MAX_GAS_USD", "2.0"))
                            _canary_only = os.environ.get("ARBY_LIVE_CANARY_ONLY", "1").strip() != "0"
                            _trades_today = _sc.get("live_executions_total", 0)

                            if _trades_today >= _max_trades:
                                logger.warning(
                                    "Live exec capped: %d/%d trades today (ARBY_MAX_TRADES_PER_DAY=%d)",
                                    _trades_today, _max_trades, _max_trades,
                                    extra={"context": {"live_exec_capped": True}},
                                )
                                _sc["live_exec_blocked_reason"] = f"MAX_TRADES_PER_DAY:{_max_trades}"
                            elif _provider is not None:
                                _signer_addr = get_signer_address()
                                for _sr in _submit_candidates[:1]:  # one trade per cold cycle
                                    _chain_id_map = {"base": 8453, "arbitrum": 42161, "linea": 59144}
                                    _chain_id = _chain_id_map.get(cli_args.chain, 1)
                                    _sign_fn = make_sign_and_send(_provider, chain_id=_chain_id)
                                    _opp = {
                                        "spread_id": getattr(_sr, "spread_id", None) or getattr(_sr, "event_id", "live_unknown"),
                                        "router_address": getattr(_sr, "router_address", None) or getattr(_sr, "sim_router_address", ""),
                                        "swap_calldata": getattr(_sr, "sim_calldata_hex", ""),
                                        "expected_pnl_usd": float(getattr(_sr, "best_backrun_net_bps", 0) or 0),
                                        "gas_estimate": int(getattr(_sr, "gas_estimate", 300_000) or 300_000),
                                        "simulation_passed": True,
                                        "canary_only": _canary_only,
                                        "max_loss_usd": _max_loss_usd,
                                        "max_gas_usd": _max_gas_usd,
                                    }
                                    try:
                                        _exec_result = _asyncio.run(
                                            _executor.execute_live(_opp, _provider, _signer_addr, _sign_fn)
                                        )
                                        _tx_hash = getattr(_exec_result, "tx_hash", None)
                                        logger.info(
                                            "Live execution result: spread_id=%s state=%s tx_hash=%s canary=%s",
                                            _opp["spread_id"],
                                            getattr(_exec_result, "state", "?"),
                                            _tx_hash,
                                            _canary_only,
                                            extra={"context": {"live_exec": True, "canary_only": _canary_only}},
                                        )
                                        _sc["live_executions_total"] = _sc.get("live_executions_total", 0) + 1
                                        # Write live submit artifact (Step 3)
                                        try:
                                            from m7.orderflow.live_submit_artifact import write_live_submit_artifact  # noqa: PLC0415
                                            write_live_submit_artifact(
                                                spread_id=_opp["spread_id"],
                                                tx_hash=_tx_hash,
                                                exec_result=_exec_result,
                                                canary_only=_canary_only,
                                            )
                                        except Exception:
                                            pass  # artifact write must never crash the loop
                                    except Exception as _exc:
                                        logger.warning(
                                            "Live execution failed: %s", _exc,
                                            extra={"context": {"live_exec_error": str(_exc)}},
                                        )
                            else:
                                logger.warning("Live exec skipped: ARBY_RPC_URL_HTTP not set")

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

                # M7.E1.47/P1a: Persist tier_map artifact from cold-side pool
                # activity. Pure read (no RPC). HOT = seen in this iteration;
                # WARM = seen previously but not now; COLD = unseen since
                # bootstrap. Provides discovery telemetry for hot-lane
                # consumer (P1b) without changing today's hot subscription.
                try:
                    from discovery.tier_classifier import (
                        PoolActivitySnapshot,
                        TierThresholds,
                        classify_pools_to_tiers,
                        write_tier_map_artifact,
                    )
                    import time as _time_tier

                    _now_ts = _time_tier.time()
                    _snapshots: list = []
                    _seen_in_iter = {
                        addr for addr, meta in _cold_active_pools.items()
                        if meta.get("last_iter") == iteration
                    }
                    for _addr, _meta in _cold_active_pools.items():
                        # Approximate last_swap_ts from iteration recency.
                        _li = _meta.get("last_iter", iteration)
                        if _li == iteration:
                            _last_ts = _now_ts
                        else:
                            # Stale by ~ (iteration - _li) cycles. Cold cycle
                            # cadence ~50s gives a coarse but useful tier hint.
                            _last_ts = _now_ts - max(0, iteration - _li) * 50.0
                        _snapshots.append(
                            PoolActivitySnapshot(
                                pool_address=_addr,
                                last_swap_ts=_last_ts,
                                swap_count_window=int(_meta.get("event_count", 0)),
                                chain=cli_args.chain,
                            )
                        )
                    if _snapshots:
                        _tier_map = classify_pools_to_tiers(
                            _snapshots,
                            now_ts=_now_ts,
                            thresholds=TierThresholds(
                                hot_max_age_s=120.0, warm_max_age_s=1800.0
                            ),
                        )
                        _path_out = write_tier_map_artifact(
                            _tier_map, chain=cli_args.chain
                        )
                        logger.info(
                            "tier_map written: HOT=%d WARM=%d COLD=%d path=%s",
                            len(_tier_map.get("hot", [])),
                            len(_tier_map.get("warm", [])),
                            len(_tier_map.get("cold", [])),
                            _path_out,
                        )
                except Exception as _tier_exc:
                    logger.debug("tier_map write failed: %s", str(_tier_exc)[:120])

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
                # E1.55: Bridge file diagnostic fields
                _bridge_file_exists = os.path.exists(_rio._COLD_HOT_BRIDGE_PATH)
                _bridge_mtime_age_s = None
                try:
                    if _bridge_file_exists:
                        import time as _time_diag
                        _bridge_mtime_age_s = round(
                            _time_diag.time() - os.path.getmtime(_rio._COLD_HOT_BRIDGE_PATH), 1
                        )
                except Exception:
                    pass
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
                    # E1.55: Bridge file existence diagnostic
                    "bridge_file_exists": _bridge_file_exists,
                    "bridge_ptt_raw_count": len(_bridge_ptt_raw) if '_bridge_ptt_raw' in dir() else 0,
                    "bridge_mtime_age_s": _bridge_mtime_age_s,
                    "persistent_cache_forced_reload_count": _persistent_force_reload_count if '_persistent_force_reload_count' in dir() else 0,
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
                    # E1.56 Step 7: pool-level gas-hopeless quarantine.
                    "c3_pool_gas_hopeless_skipped": _c3_pool_gas_hopeless_skipped if '_c3_pool_gas_hopeless_skipped' in dir() else 0,
                    "pool_gas_hopeless": sorted(_pool_gas_hopeless) if '_pool_gas_hopeless' in dir() and _pool_gas_hopeless else [],
                    "pool_gas_hopeless_streak": dict(_new_streak) if '_new_streak' in dir() else {},
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
                            # M7.E1.34g fix #2: classify WHY this bridge hit
                            # did not become a fast-scored candidate. Kept as
                            # first-seen reason per window; histogram is
                            # aggregated in the rollup layer. Only set when
                            # scoring_path != "registry_fast" so successful
                            # scores never overwrite a null.
                            _sp_r = getattr(_r, "scoring_path", None)
                            if _sp_r != "registry_fast" and "bridge_hit_not_scored_reason" not in _hot_bridge_diag:
                                # M7.E1.34n (soak8) fix #5: classify by
                                # concrete reason buckets reviewer gates on,
                                # not by scoring_path. Reject_reason + token
                                # presence + registry hit give us enough
                                # signal to attribute the drop.
                                _rej = getattr(_r, "reject_reason", None) or ""
                                _rej_u = str(_rej).upper()
                                _tok_in_addr = getattr(_r, "backrun_token_in_address", None)
                                _tok_out_addr = getattr(_r, "backrun_token_out_address", None)
                                _pair_str = getattr(_r, "actual_pair", None)
                                # M7.E1.47 fix: when result lacks token
                                # addresses but the bridge pool IS in the
                                # PTT cache, use cached tokens as fallback
                                # — TOKEN_ADDRESS_UNKNOWN should fire only
                                # when we genuinely don't know the pool's
                                # tokens, not when the scorer early-returns
                                # via _reject() before populating them.
                                if (not _tok_in_addr or not _tok_out_addr) and _cached_all:
                                    try:
                                        _t0c, _t1c, _ = _cached_all
                                        if not _tok_in_addr:
                                            _tok_in_addr = _t0c
                                        if not _tok_out_addr:
                                            _tok_out_addr = _t1c
                                    except Exception:
                                        pass
                                if not _tok_in_addr or not _tok_out_addr:
                                    _reason_code = "TOKEN_ADDRESS_UNKNOWN"
                                elif _sp_r == "triangular_pending" or "TRIANGULAR_CANDIDATE_DEFERRED" in _rej_u:
                                    # M7.E1.47/P0: bridge event with no direct
                                    # registry pair but triangular intermediates
                                    # exist via intent-token graph. Distinct from
                                    # REGISTRY_MISS so reviewer can target the
                                    # follow-up triangle scoring iteration.
                                    _reason_code = "TRIANGULAR_AVAILABLE"
                                elif "PAIR_FILTER" in _rej_u or "FILTER_DROPPED" in _rej_u:
                                    _reason_code = "PAIR_FILTER_DROPPED"
                                elif "REGISTRY" in _rej_u or _sp_r == "hot_skip":
                                    _reason_code = "REGISTRY_MISS"
                                elif "FAMILY" in _rej_u or "UNRESOLVED" in _rej_u:
                                    _reason_code = "FAMILY_UNRESOLVED"
                                elif not _pair_str:
                                    _reason_code = "NO_PAIR_MATCH"
                                elif _sp_r is None:
                                    _reason_code = "NOT_SCORED"
                                else:
                                    _reason_code = f"SCORING_PATH_{str(_sp_r).upper()}"
                                _hot_bridge_diag["bridge_hit_not_scored_reason"] = _reason_code
                                # M7.E1.34h fix #3: enrich reason with raw pair
                                # context so reviewer can route HOT_SKIP_UNKNOWN_PAIR
                                # drops to the canonical pair registry.
                                try:
                                    _sample = {
                                        "pool_address": _ck_all,
                                        "scoring_path": _sp_r,
                                        "reason": _reason_code,
                                        "actual_pair": getattr(_r, "actual_pair", None),
                                        "token_in": getattr(_r, "backrun_token_in_address", None),
                                        "token_out": getattr(_r, "backrun_token_out_address", None),
                                        "fee_tier": getattr(_r, "best_buy_fee", None),
                                        "venue": getattr(_r, "best_buy_venue", None),
                                        "adapter_type": getattr(_r, "adapter_type_used", None),
                                    }
                                    _hot_bridge_diag["bridge_hit_not_scored_sample"] = _sample
                                except Exception:
                                    pass
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
                    gate_result=_gate_result,
                )

                # E1.55: SCORING_BLACKHOLE guard — reviewer hard-fail warning.
                # If we saw events but scored zero fast-path candidates, the
                # hot pipeline is in a black-hole state (registry/bridge not
                # populated). Log a prominent WARNING so logs are searchable.
                _sb_events = artifact.get("events_count", 0)
                _sb_scored = _hot_bridge_diag.get("fast_score_scored", 0)
                if _sb_events > 0 and _sb_scored == 0:
                    logger.warning(
                        "E1.55 SCORING_BLACKHOLE detected: events_seen=%d "
                        "fast_path_scored=0 bridge_ptt=%d persistent_cache_loaded=%d "
                        "bridge_file_exists=%s — hot lane is NOT scoring any events. "
                        "Likely cause: bridge/cache empty (cold first window in progress).",
                        _sb_events,
                        len(_bridge_ptt_raw) if '_bridge_ptt_raw' in dir() else 0,
                        _persistent_force_reload_count if '_persistent_force_reload_count' in dir() else 0,
                        _bridge_file_exists if '_bridge_file_exists' in dir() else None,
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
                    if os.path.exists(_rio._COLD_HOT_BRIDGE_PATH):
                        with open(_rio._COLD_HOT_BRIDGE_PATH, "r", encoding="utf-8") as _bf:
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
                        # E1.56 Step 7: persist pool-level gas-hopeless tracking
                        # so streak survives across windows.
                        _bridge_update["c3_pool_gas_hopeless_skipped"] = (
                            _hot_bridge_diag.get("c3_pool_gas_hopeless_skipped") or 0
                        )
                        _bridge_update["pool_gas_hopeless"] = (
                            _hot_bridge_diag.get("pool_gas_hopeless") or []
                        )
                        _bridge_update["pool_gas_hopeless_streak"] = (
                            _hot_bridge_diag.get("pool_gas_hopeless_streak") or {}
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
                        _atomic_json_write(_rio._COLD_HOT_BRIDGE_PATH, _bridge_update, indent=2)
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

                # E1.59 step #3/#4: pool_state HTTP feed — poll pending logs
                # for the bounded target pool set from the current bridge PTT
                # so pool_price_state.updates_total becomes non-zero.
                try:
                    from m7.orderflow.pool_state_http_feed import (
                        is_enabled as _pshf_en, poll_and_feed as _pshf_poll,
                    )
                    if _pshf_en():
                        import aiohttp, asyncio
                        _pshf_ptt = (_bridge or {}).get("pool_token_transport", {})
                        _pshf_addrs = list({k.lower() for k in _pshf_ptt})[: 50]
                        if _pshf_addrs:
                            _rpc_url = os.environ.get(
                                "ARBY_RPC_URL_HTTP",
                                os.environ.get("ARBY_RPC_URL", ""),
                            )
                            if _rpc_url:
                                async def _do_poll():
                                    async with aiohttp.ClientSession() as _sess_http:
                                        return await _pshf_poll(
                                            rpc_url=_rpc_url,
                                            chain=cli_args.chain,
                                            addresses=_pshf_addrs,
                                            http_post=_sess_http.post,
                                        )
                                try:
                                    _pshf_r = asyncio.get_event_loop().run_until_complete(_do_poll())
                                    logger.debug(
                                        "pool_state_http_feed: v3=%s v2=%s skipped=%s fetched=%s",
                                        _pshf_r.get("v3_updates"),
                                        _pshf_r.get("v2_updates"),
                                        _pshf_r.get("skipped"),
                                        _pshf_r.get("fetched"),
                                    )
                                except Exception as _pshf_e:
                                    logger.debug("pool_state_http_feed poll: %s", str(_pshf_e)[:80])
                except Exception:
                    pass

                # E1.59 step #7: DISC→PROD pool promotion — observe profitable
                # cold-immediate DISC candidates and record in promotion module.
                try:
                    from m7.orderflow.disc_to_prod_pool_promotion import (
                        is_enabled as _pp_en, observe_profitable as _pp_obs,
                    )
                    if _pp_en() and profile == "discovery":
                        # Read DISC cold bridge for profitable candidates.
                        _disc_bridge_path = _rio._COLD_HOT_BRIDGE_PATH.replace(
                            "m7_cold_hot_bridge", "m7_cold_hot_bridge_discovery"
                        )
                        if os.path.exists(_disc_bridge_path):
                            try:
                                with open(_disc_bridge_path, "r", encoding="utf-8") as _dbf:
                                    _disc_bridge = json.load(_dbf)
                                for _dc in (_disc_bridge.get("cold_executable") or []):
                                    if float(_dc.get("net_bps") or 0) > 0:
                                        _pp_obs(
                                            pool=(_dc.get("pool_address") or ""),
                                            pair=_dc.get("actual_pair"),
                                            router=_dc.get("router"),
                                            fee_tier=_dc.get("buy_fee"),
                                            token_in=_dc.get("token_in"),
                                            token_out=_dc.get("token_out"),
                                            chain=cli_args.chain,
                                            profit_bps=float(_dc.get("net_bps") or 0),
                                        )
                            except Exception as _pp_e:
                                logger.debug("pool_promotion disc read: %s", str(_pp_e)[:80])
                except Exception:
                    pass

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
                    gate_result=_gate_result,
                    extra_signal_counts=_cold_immediate_counters,
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
    # M7.E1.34h fix #6: explicit shutdown flush so rollup carries a fresh
    # last_heartbeat_utc at supervisor end. Without this, per-process
    # clean-exits leave the rollup stamped with the last mid-cycle ts,
    # and reviewer's staleness gate retro-fails a valid soak.
    if lane == "hot":
        try:
            from m7.orderflow.hot_runtime_artifacts import flush_rollup_shutdown
            flush_rollup_shutdown(chain=cli_args.chain)
        except Exception as _exc_flush:
            logger.debug("Hot rollup shutdown flush failed: %s", str(_exc_flush)[:120])


