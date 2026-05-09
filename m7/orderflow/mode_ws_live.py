"""
M7 orderflow ws-live mode handler.

Extracted from cli.py to keep the CLI dispatcher under 1000 lines.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from config import load_dexes, get_all_token_addresses, load_chains
from core.rpc_urls import resolve_rpc_http, resolve_rpc_ws, _CHAIN_KEY_TO_ID, classify_provider

from m7.shared.constants import (
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_SUBGRAPH_VERIFIED,
    CHAINLINK_FEEDS_ARBITRUM,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    SWAP_EVENT_TOPIC,
    UNSCORED_REJECTS,
    get_chainlink_feeds,
    get_prewarm_pairs,
)
from m7.orderflow.artifacts import build_replay_summary
from m7.orderflow.coverage import seed_tokens_from_subgraph
from m7.orderflow.events import normalize_swap_log
from m7.orderflow.pool_price_state import feed_raw_logs as _feed_pool_price_logs
from m7.orderflow.pool_registry import PoolRegistry
from m7.orderflow.profit_guard import annotate_profit_guard_results
from m7.orderflow.resolve import _build_address_to_symbol, batch_pre_resolve_pools
from m7.orderflow.scoring_parallel import score_backrun_live_parallel, score_backrun_fast
from m7.orderflow.contracts import BackrunResult

logger = logging.getLogger("m7.orderflow.cli")


# ---------------------------------------------------------------------------
# E1.65 Steps 6+8: Cross-process WS lease + 429 cooldown file.
#
# ws_cooldown.json  — written by any process that detects a WS 429 storm.
#   Format: {"cooldown_until": <unix_ts>, "chain": <str>, "set_by_pid": <int>}
#   All processes check this file before attempting a reconnect.
#
# ws_lease.json     — written by a process when it opens a WS subscription.
#   Format: {"pid": <int>, "chain": <str>, "provider": <str>, "acquired_at": <unix_ts>}
#   Lease TTL = ARBY_WS_LEASE_TTL_S (default 600s = 10 min).
#   When ARBY_WS_GLOBAL_LEASE=1, a second process SHARING the same chain
#   and provider skips WS open and polls the lease for block signals instead
#   of opening its own WS connection. Use for cold lanes only.
# ---------------------------------------------------------------------------
_ROLLING_DIR = Path("data/runs/_rolling")
_WS_COOLDOWN_PATH = _ROLLING_DIR / "ws_cooldown.json"
_WS_LEASE_PATH = _ROLLING_DIR / "ws_lease.json"
_WS_LEASE_TTL_S = int(os.getenv("ARBY_WS_LEASE_TTL_S", "600") or "600")


def _check_ws_cooldown(chain: str) -> float:
    """Return seconds remaining in cross-process WS 429 cooldown (0 = no cooldown)."""
    try:
        data = json.loads(_WS_COOLDOWN_PATH.read_text())
        if data.get("chain") == chain:
            remaining = float(data.get("cooldown_until", 0)) - time.time()
            if remaining > 0:
                return remaining
    except Exception:
        pass
    return 0.0


def _write_ws_cooldown(chain: str, cooldown_s: float) -> None:
    """Write cross-process WS 429 cooldown file (Step 8)."""
    try:
        _ROLLING_DIR.mkdir(parents=True, exist_ok=True)
        _WS_COOLDOWN_PATH.write_text(json.dumps({
            "cooldown_until": time.time() + cooldown_s,
            "chain": chain,
            "set_by_pid": os.getpid(),
        }))
    except Exception:
        pass


def _acquire_ws_lease(chain: str, provider: str) -> bool:
    """Try to acquire cross-process WS lease (Step 6).

    Returns True (lease acquired or no competition), False (another process
    already holds a fresh lease for the same chain+provider).
    Only enforced when ARBY_WS_GLOBAL_LEASE=1.
    """
    if os.getenv("ARBY_WS_GLOBAL_LEASE", "0") != "1":
        return True  # feature off by default — all processes open WS freely
    try:
        _ROLLING_DIR.mkdir(parents=True, exist_ok=True)
        if _WS_LEASE_PATH.exists():
            data = json.loads(_WS_LEASE_PATH.read_text())
            # Lease held by another process for the same (chain, provider)?
            if (
                data.get("pid") != os.getpid()
                and data.get("chain") == chain
                and data.get("provider") == provider
                and (time.time() - float(data.get("acquired_at", 0))) < _WS_LEASE_TTL_S
            ):
                return False  # another process holds it
        # Write/overwrite our own lease
        _WS_LEASE_PATH.write_text(json.dumps({
            "pid": os.getpid(),
            "chain": chain,
            "provider": provider,
            "acquired_at": time.time(),
        }))
        return True
    except Exception:
        return True  # fail open — never block WS due to I/O error


def _release_ws_lease() -> None:
    """Release WS lease on clean exit. No-op when lease file absent."""
    try:
        if _WS_LEASE_PATH.exists():
            data = json.loads(_WS_LEASE_PATH.read_text())
            if data.get("pid") == os.getpid():
                _WS_LEASE_PATH.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# E1.50 / TD-003 — In-process WS-target refresh bridge.
# Module-level cache of the last-working WS endpoint per chain. Once the
# WS escalation chain (drpc -> alchemy / public_fallback) succeeds, the next
# iteration starts directly from that proven endpoint instead of re-paying
# the drpc 429 reconnect cost on every iteration.
#
# Pure additive: prefer-only — never overrides _strict_provider_policy gates
# (refusal of public_fallback under strict policy still applies).
# Reset on process restart (no on-disk persistence by design — keeps the
# rolling artifact contract unchanged).
# ---------------------------------------------------------------------------
_LAST_WORKING_WS: Dict[str, Dict[str, str]] = {}  # chain -> {"url": str, "provider": str}


def _remember_last_working_ws(chain: str, url: str, provider: str) -> None:
    if not chain or not url:
        return
    _LAST_WORKING_WS[chain.lower()] = {"url": url, "provider": provider or "unknown"}


def _peek_last_working_ws(chain: str) -> Optional[Dict[str, str]]:
    if not chain:
        return None
    return _LAST_WORKING_WS.get(chain.lower())


def run_ws_live(
    args,
    *,
    external_registry=None,
    warm_registry=None,
    bridge_pool_addresses: Optional[Set[str]] = None,
    bridge_hit_deficit: bool = False,
    bridge_hit_deficit_severe: bool = False,
) -> dict:
    """Execute the ws-live WebSocket replay mode and return the artifact dict.

    Parameters
    ----------
    args : namespace with ws_blocks, ws_timeout, max_events, chain.
    external_registry : optional pre-warmed PoolRegistry.  When provided,
        session prewarm is skipped and this registry is used directly.
        The caller retains ownership and can accumulate state across calls.
        **Triggers hot mode** (score_backrun_fast for all events).
    warm_registry : optional pre-warmed PoolRegistry for cold mode.
        When provided, used as session_registry (skips fresh PoolRegistry
        creation + prewarm), but does NOT trigger hot mode. Cold lane
        still uses score_backrun_live_parallel, but registry_preload_ms
        drops to near-zero for already-cached pairs (M7.A.5.37).
    bridge_pool_addresses : optional set of checksummed/lowered pool addresses
        from cold→hot bridge. When provided in hot mode, eth_getLogs uses a
        targeted address filter so only events from bridge pools are fetched.
    bridge_hit_deficit : if True, the caller (loop) has detected that events
        exist but bridge_pool_hit_total == 0. Broad fallback interval is
        set to 2 (50% broad) to maximize coverage.
    bridge_hit_deficit_severe : if True, deficit is sustained (3+ windows
        with events but zero hits). Interval drops to 1 (100% broad).
        M7.A.5.47g: Escalated broad fallback for persistent conversion failure.
        M7.A.5.47: Focused event intake for bridge pools.
    """
    logger.info(
        "Running M7.A.5.3 ws-live replay (ws_blocks=%d, ws_timeout=%ds)",
        args.ws_blocks,
        args.ws_timeout,
    )

    # E1.69 reviewer fix step 8: WS 429 cooldown.  When the previous WS
    # window hit a 429, honour ARBY_WS_COOLDOWN_AFTER_429_S before
    # attempting a new subscribe so we don't pile-on rate limits.
    try:
        _cool = float(os.environ.get("ARBY_WS_COOLDOWN_AFTER_429_S", "0") or 0)
    except (TypeError, ValueError):
        _cool = 0.0
    if _cool > 0:
        _last_429 = getattr(run_ws_live, "_last_429_ts", 0.0)
        _delta = time.time() - _last_429
        if _last_429 and _delta < _cool:
            _wait = _cool - _delta
            logger.info(
                "WS cooldown active: sleeping %.1fs after recent 429 (cool=%.1fs)",
                _wait, _cool,
            )
            time.sleep(_wait)

    chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())

    # Resolve HTTP RPC for quoting
    rpc_url, rpc_provider, rpc_diag = resolve_rpc_http(
        chain_id=chain_id,
        network=args.chain,
        env=dict(os.environ),
    )
    if not rpc_url:
        raise SystemExit(f"No HTTP RPC URL found for chain: {args.chain}")
    rpc_host = urlparse(rpc_url).netloc

    # M7.E1.10: Verify HTTP RPC is reachable; fallback to public if 429'd.
    # M7.E1.12.1: Retry with exponential backoff before falling back to public.
    # Alchemy accounts can get rate-limited on both WS and HTTP simultaneously.
    _http_premium_only = os.environ.get("ARBY_RPC_PREMIUM_ONLY", "") == "1"
    # M7.E1.34d: strict provider policy implies premium-only for both HTTP
    # and WS paths. Reviewer 30m soak 2026-04-21 showed counter-only tracking
    # was insufficient — runtime still routed windows through public_fallback
    # and accumulated breaches. Now: hard-fail rather than silently count.
    _strict_provider_policy = (
        os.environ.get("ARBY_STRICT_PROVIDER_POLICY", "") == "1"
    )
    if _strict_provider_policy:
        _http_premium_only = True
    _http_429_retries = 0
    _http_429_max_retries = 3
    _http_connected = False
    for _retry_i in range(_http_429_max_retries + 1):
        try:
            from web3 import Web3 as _W3_test
            _w3_test = _W3_test(_W3_test.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
            _w3_test.eth.block_number  # simple connectivity test
            _http_connected = True
            break
        except Exception as _rpc_test_exc:
            _rpc_err = str(_rpc_test_exc)[:200]
            if "429" in _rpc_err or "Too Many Requests" in _rpc_err:
                _http_429_retries += 1
                if _retry_i < _http_429_max_retries:
                    import time as _time_mod
                    _backoff_s = 2 ** _retry_i  # 1, 2, 4 seconds
                    logger.warning(
                        "HTTP RPC 429 on %s, retry %d/%d in %ds",
                        rpc_host, _retry_i + 1, _http_429_max_retries, _backoff_s,
                    )
                    _time_mod.sleep(_backoff_s)
                    continue
                # All retries exhausted — fall back to public (unless premium-only)
                if _http_premium_only:
                    raise SystemExit(
                        f"HTTP RPC 429 on {rpc_host} after {_http_429_max_retries} retries, "
                        "ARBY_RPC_PREMIUM_ONLY=1 prevents public fallback"
                    )
                from core.rpc_urls import public_fallback_for, _normalize_network
                _pub_http = public_fallback_for(_normalize_network(args.chain))
                if _pub_http:
                    logger.warning(
                        "HTTP RPC 429 rate limit on %s after %d retries, falling back to public RPC: %s",
                        rpc_host, _http_429_max_retries, _pub_http,
                    )
                    _original_provider = rpc_provider
                    rpc_url = _pub_http
                    rpc_provider = classify_provider(_pub_http)
                    rpc_host = urlparse(rpc_url).netloc
                    rpc_diag = {"source": "public_http_fallback", "original_source": rpc_diag.get("source", "unknown"), "original_provider": _original_provider, "fallback_reason": "http_429", "retries_attempted": _http_429_retries}
                    _http_connected = True
                else:
                    logger.error("HTTP RPC 429 on %s and no public fallback available", rpc_host)
            else:
                logger.debug("HTTP RPC test failed: %s (proceeding anyway)", _rpc_err[:80])
                break

    # Resolve WebSocket for newHeads subscription
    # M7.E1: On Base, prefer Flashblocks WS for sub-block (~200ms) event delivery.
    # Flashblocks endpoint supports standard eth_subscribe newHeads but delivers
    # at sub-block granularity, giving a structural latency advantage over 2s blocks.
    #
    # M7.E1.34n-soak9: gate Flashblocks preconf behind
    # ARBY_BASE_USE_FLASHBLOCKS_WS (default OFF). Soak8 observed 100% of
    # reconnect attempts failing with JSON-RPC code 15 "Too many request"
    # on the public preconf endpoint. Default now goes through
    # resolve_rpc_ws which picks the first chains.yaml ws_endpoint
    # (dRPC) — premium-friendly and not rate-limited on newHeads.
    _flashblocks_ws = None
    _use_flashblocks_ws = (
        os.environ.get("ARBY_BASE_USE_FLASHBLOCKS_WS", "0").strip() == "1"
    )
    if args.chain == "base" and _use_flashblocks_ws:
        from config import load_chains as _load_chains_fb
        from chains.flashblocks import get_flashblocks_ws_url
        _base_cfg = _load_chains_fb().get("base", {})
        _flashblocks_ws = get_flashblocks_ws_url(
            _base_cfg.get("flashblocks_ws_endpoint")
        )

    ws_url = None
    ws_provider = None
    ws_diag = {}
    if _flashblocks_ws:
        ws_url = _flashblocks_ws
        ws_provider = "flashblocks"
        ws_diag = {"source": "flashblocks_sub_block", "flashblocks": True}
        logger.info(
            "M7.E1: Using Flashblocks WS for Base sub-block newHeads: %s",
            urlparse(ws_url).netloc,
        )

    # Verify Flashblocks WS connectivity; fall back to standard WS if unreachable
    if ws_url and ws_provider == "flashblocks":
        try:
            import websocket as _ws_test
            _test_conn = _ws_test.create_connection(ws_url, timeout=5)
            _test_conn.close()
        except Exception as _fb_err:
            logger.warning(
                "M7.E1: Flashblocks WS unreachable (%s), falling back to standard WS",
                str(_fb_err)[:80],
            )
            ws_url = None  # trigger standard resolution below

    if not ws_url:
        ws_url, ws_provider, ws_diag = resolve_rpc_ws(
            chain_id=chain_id,
            network=args.chain,
            env=dict(os.environ),
        )
    if not ws_url:
        raise SystemExit(
            f"No WebSocket RPC URL found for chain: {args.chain}. "
            "Set ALCHEMY_API_KEY or ALCHEMY_RPC_WS in .env"
        )
    # Ensure ws_diag is always a dict for downstream .get() calls
    if not isinstance(ws_diag, dict):
        ws_diag = {"source": str(ws_diag)}
    ws_host = urlparse(ws_url).netloc

    # E1.50 / TD-003: prefer last-working WS endpoint for this chain across
    # iterations. After a successful escalation (e.g. drpc 429 -> alchemy),
    # subsequent iterations should not re-pay the drpc reconnect cost.
    # Honors strict provider policy: never resurrect public_fallback when
    # ARBY_STRICT_PROVIDER_POLICY=1 (handled later in _open_ws_subscription).
    if not _flashblocks_ws and os.environ.get("ARBY_WS_REUSE_LAST_WORKING", "1") != "0":
        try:
            _last = _peek_last_working_ws(args.chain)
            if _last and _last.get("url"):
                _last_url = _last["url"]
                _last_provider = _last.get("provider") or "unknown"
                if _last_url != ws_url and _last_provider != "public_fallback":
                    logger.info(
                        "WS reuse last-working endpoint: provider=%s host=%s "
                        "(was: provider=%s host=%s)",
                        _last_provider,
                        urlparse(_last_url).netloc,
                        ws_provider,
                        ws_host,
                    )
                    ws_url = _last_url
                    ws_provider = _last_provider
                    ws_host = urlparse(ws_url).netloc
                    ws_diag = {
                        "source": "ws_reuse_last_working",
                        "original_source": ws_diag.get("source", "unknown"),
                        "reused_provider": _last_provider,
                    }
        except Exception as _reuse_exc:
            logger.debug(
                "WS reuse last-working skipped: %s", str(_reuse_exc)[:120]
            )

    logger.info(
        "RPC resolved: http=%s ws=%s ws_provider=%s",
        rpc_host,
        ws_host,
        ws_provider,
        extra={"context": {
            "rpc_provider": rpc_provider,
            "ws_provider": ws_provider,
            "rpc_host": rpc_host,
            "ws_host": ws_host,
        }},
    )

    all_dexes = load_dexes()
    dex_configs = all_dexes.get(args.chain, {})
    token_addresses = get_all_token_addresses(args.chain)
    addr_to_symbol = _build_address_to_symbol(token_addresses)

    # M7.A.5.22: Session-scoped pool registry for factory-driven discovery
    # M7.A.5.31: Accept external registry; skip prewarm if caller provided one
    # M7.A.5.37: Accept warm_registry for cold mode (persistent, no hot trigger)
    _prewarm_count = 0
    if external_registry is not None:
        session_registry = external_registry
        _prewarm_count = -1  # signal: prewarm handled by caller
    elif warm_registry is not None:
        session_registry = warm_registry
        _prewarm_count = -2  # signal: warm registry provided, cold mode
    else:
        session_registry = PoolRegistry()

    # M7.A.5.24: Session prewarm — preload high-frequency pairs from known addresses
    # M7.E1: Chain-aware prewarm pairs
    # M7.E1.9: Profile-aware — discovery profile uses wider contour
    _profile = getattr(args, "profile", "production")
    _prewarm_pairs = get_prewarm_pairs(args.chain, _profile)
    if _prewarm_count not in (-1, -2):
        _prewarm_count = 0
        try:
            from web3 import Web3 as _W3pw
            _w3pw = _W3pw(_W3pw.HTTPProvider(rpc_url))
            _pw_block = _w3pw.eth.block_number
            for _sym_a, _sym_b in _prewarm_pairs:
                _addr_a = token_addresses.get(_sym_a, "")
                _addr_b = token_addresses.get(_sym_b, "")
                if _addr_a and _addr_b:
                    try:
                        session_registry.preload_pair(
                            _addr_a, _addr_b, dex_configs, rpc_url, _pw_block,
                        )
                        _prewarm_count += 1
                    except Exception:
                        pass
            logger.info("Session prewarm: %d/%d pairs loaded", _prewarm_count, len(_prewarm_pairs))
        except Exception as _pw_exc:
            logger.debug("Session prewarm skipped: %s", str(_pw_exc)[:80])
    else:
        logger.info("Session prewarm skipped: %s registry provided",
                     "external" if _prewarm_count == -1 else "warm")

    # M7.A.5.8: Subgraph-backed bounded coverage seed
    # M7.A.5.47: Skip in hot mode — subgraph is currently 403 and hot lane
    # uses bridge pool_token_transport for token discovery, not subgraph.
    pre_seed_count = len(addr_to_symbol)
    subgraph_seed_stats = {"tokens_discovered": 0, "tokens_new": 0,
                           "tokens_verified": 0, "sources_queried": [], "errors": []}
    subgraph_seeded_addrs: set = set()
    _hot_mode_skip_subgraph = external_registry is not None
    if _hot_mode_skip_subgraph:
        logger.debug("Subgraph seed skipped: hot mode uses bridge for token discovery")
    else:
        try:
            from web3 import Web3
            w3_seed = Web3(Web3.HTTPProvider(rpc_url))
            seed_block = w3_seed.eth.block_number
            subgraph_seed_stats = seed_tokens_from_subgraph(
                addr_to_symbol, rpc_url, seed_block, chain=args.chain,
            )
            post_seed_count = len(addr_to_symbol)
            if post_seed_count > pre_seed_count:
                canonical_addrs = set(_build_address_to_symbol(token_addresses).keys())
                subgraph_seeded_addrs = set(addr_to_symbol.keys()) - canonical_addrs
            logger.info(
                "Subgraph seed: discovered=%d new=%d verified=%d sources=%s",
                subgraph_seed_stats["tokens_discovered"],
                subgraph_seed_stats["tokens_new"],
                subgraph_seed_stats["tokens_verified"],
                subgraph_seed_stats["sources_queried"],
            )
        except Exception as exc:
            logger.debug("Subgraph seed failed (best-effort): %s", str(exc)[:100])
            subgraph_seed_stats["errors"].append(f"seed_init: {str(exc)[:80]}")

    # Load block_time_ms from chains.yaml for latency budget
    chain_cfg = load_chains().get(args.chain, {})
    block_time_ms = chain_cfg.get("block_time_ms", 250)

    # Subscribe to newHeads via WebSocket and process blocks
    import websocket as ws_mod

    all_events = []
    all_results = []
    blocks_processed = 0
    raw_logs_total = 0
    # E1.12.1: Per-window cached L1 data fee (dynamic gas floor for OP-stack)
    _l1_fee_bps_cached: Optional[float] = None
    _l1_fee_source: str = "none"
    if args.chain in ("base", "optimism"):
        try:
            from web3 import Web3 as _W3_l1
            from chains.l1_cost import get_l1_fee_bps
            _w3_l1 = _W3_l1(_W3_l1.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
            _l1_fee_bps_cached = get_l1_fee_bps(w3=_w3_l1, chain=args.chain)
            _l1_fee_source = "onchain"
            logger.info("L1 data fee for %s: %.3f bps (source=%s)", args.chain, _l1_fee_bps_cached, _l1_fee_source)
        except Exception as _l1_exc:
            logger.debug("L1 fee query failed: %s (using static gas floor)", str(_l1_exc)[:100])
    # M7.E1.10: WS connection health tracking — distinguish ws_failed from market_empty
    _ws_connection_status = "not_attempted"  # not_attempted | connected | failed_429 | failed_other
    _ws_error_detail: str | None = None
    _ws_reconnect_count = 0
    _ws_recv_error_count = 0
    _ws_recv_timeout_count = 0
    _ws_subscribe_count = 0
    _ws_last_recv_error: str | None = None
    # M7.A.5.47: Hybrid intake diagnostics
    _broad_blocks = 0       # blocks scanned with broad (no address filter)
    _focused_blocks = 0     # blocks scanned with focused (address filter)
    _broad_logs = 0         # raw logs from broad blocks
    _focused_logs = 0       # raw logs from focused blocks
    # M7.A.5.47c: Track pool addresses seen in hot events (for bridge miss diagnosis)
    _hot_event_pool_counts: Dict[str, int] = {}  # pool_address_lower -> count
    # M7.E1.34k: funnel_debug — count silent drops that previously hid
    # funnel starvation causes (normalize_swap_log returning None, empty
    # block_events, broad-floor filter eating every event, etc.).
    _funnel_debug: Dict[str, int] = {
        "normalize_drops_malformed_data": 0,
        "normalize_drops_same_sign_amounts": 0,
        "normalize_drops_size_floor": 0,
        "normalize_drops_decode_exception": 0,
        "blocks_dropped_all_normalized_none": 0,
        "blocks_dropped_all_below_broad_floor": 0,
        "events_dropped_broad_floor": 0,
        # E1.51 pps sink counters (accumulated per session)
        "pps_v3_updates": 0,
        "pps_v2_updates": 0,
        "pps_skipped": 0,
    }
    ws_start_time = time.monotonic()
    # M7.E1.34m (soak7): default exit_reason so artifact always carries it
    # even if an early strict-policy SystemExit fires before the while loop.
    _exit_reason: str = "unknown"

    # M7.A.5.23: Session-persistent low-lag tracking across blocks
    _session_low_lag_pairs: Dict[str, Dict] = {}  # pair -> tracking info

    try:
        # E1.65 Step 6: Check cross-process WS lease before opening connection.
        # When ARBY_WS_GLOBAL_LEASE=1, cold lanes skip WS open if another
        # process already holds a lease for the same chain+provider.
        _chain_for_lease = getattr(args, "chain", "base")
        if not _acquire_ws_lease(_chain_for_lease, ws_provider):
            logger.info(
                "WS lease held by another process for chain=%s provider=%s; "
                "skipping WS subscription this window.",
                _chain_for_lease, ws_provider,
            )
            # Emit a minimal result dict as a "skipped" window so the
            # rolling artifact writer still runs and the bridge is refreshed.
            return {
                "window_skipped": True,
                "skip_reason": "ws_lease_held_by_other_process",
                "ws_provider": ws_provider,
            }
        # E1.65 Step 8: Check cross-process cooldown before connecting.
        _pre_cool = _check_ws_cooldown(_chain_for_lease)
        if _pre_cool > 0:
            logger.info(
                "Cross-process WS cooldown active (%.0fs remaining) for chain=%s; "
                "pausing before connect.",
                _pre_cool, _chain_for_lease,
            )
            time.sleep(min(_pre_cool, 30.0))
        # M7.E1.10: WS connection with automatic fallback on 429/connection failure
        _ws_tried_urls = [(ws_url, ws_provider)]
        # M7.E1.34d: reject the window immediately if the resolved primary
        # provider is already public_fallback under strict policy.
        if _strict_provider_policy and ws_provider == "public_fallback":
            raise SystemExit(
                f"ARBY_STRICT_PROVIDER_POLICY=1 forbids public_fallback as "
                f"primary WS provider (resolved url={ws_url})"
            )
        sub_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newHeads"],
        })
        try:
            _recv_timeout_s = int(os.environ.get("ARBY_WS_RECV_TIMEOUT_S", "30") or "30")
        except Exception:
            _recv_timeout_s = 30
        _recv_timeout_s = max(1, min(_recv_timeout_s, max(1, int(args.ws_timeout))))

        def _open_ws_subscription(connect_reason: str):
            nonlocal ws_url, ws_provider, ws_host, ws_diag
            nonlocal _ws_connection_status, _ws_error_detail, _ws_subscribe_count

            _ws_connected = False
            _conn = None
            for _try_ws_url, _try_ws_name in _ws_tried_urls:
                try:
                    _conn = ws_mod.create_connection(_try_ws_url, timeout=10)
                    _ws_connected = True
                    if _try_ws_url != ws_url:
                        _original_ws_provider = ws_provider
                        logger.info(
                            "WS fallback to %s succeeded: %s",
                            _try_ws_name, urlparse(_try_ws_url).netloc,
                        )
                        ws_url = _try_ws_url
                        ws_provider = classify_provider(_try_ws_url)
                        ws_host = urlparse(ws_url).netloc
                        ws_diag = {"source": "public_ws_fallback", "original_source": ws_diag.get("source", "unknown"), "original_provider": _original_ws_provider, "fallback_reason": "ws_429"}
                    break
                except Exception as _conn_exc:
                    _conn_err = str(_conn_exc)[:200]
                    if "429" in _conn_err:
                        logger.warning(
                            "WS 429 rate limit on %s (%s), trying fallback...",
                            _try_ws_name, urlparse(_try_ws_url).netloc,
                        )
                        # M7.E1.47/P3: Alchemy WS premium fallback on 429.
                        # If ALCHEMY_API_KEY is set and the throttled primary
                        # is NOT already Alchemy, enqueue Alchemy WS BEFORE
                        # public fallback. This keeps production-grade WS
                        # under strict_provider_policy and gives a higher
                        # quality reconnect target than publicnode.
                        # Controlled by ARBY_ALCHEMY_WS_FALLBACK=1 (default ON).
                        if os.environ.get("ARBY_ALCHEMY_WS_FALLBACK", "1") != "0":
                            try:
                                from core.rpc_urls import (
                                    build_alchemy_ws_url,
                                    _NETWORK_ALIASES as _NA_AL,
                                )
                                _api = os.environ.get("ALCHEMY_API_KEY")
                                _net_alc = _NA_AL.get(args.chain.lower())
                                if (
                                    _api and _net_alc
                                    and _try_ws_name != "alchemy"
                                ):
                                    _alc_ws = build_alchemy_ws_url(_net_alc, _api)
                                    if (
                                        _alc_ws
                                        and (_alc_ws, "alchemy") not in _ws_tried_urls
                                    ):
                                        _ws_tried_urls.append((_alc_ws, "alchemy"))
                                        logger.info(
                                            "WS fallback enqueued: alchemy (%s)",
                                            urlparse(_alc_ws).netloc,
                                        )
                            except Exception as _alc_exc:
                                logger.debug(
                                    "Alchemy WS fallback enqueue failed: %s",
                                    str(_alc_exc)[:120],
                                )
                        # Add public WS fallback if not already tried
                        from core.rpc_urls import _PUBLIC_WS_FALLBACKS, _NETWORK_ALIASES
                        _net_key = _NETWORK_ALIASES.get(args.chain.lower())
                        _pub_ws = _PUBLIC_WS_FALLBACKS.get(_net_key) if _net_key else None
                        # M7.E1.34d: under strict provider policy, refuse to
                        # enqueue the public WS fallback. This keeps runtime
                        # production-grade even when premium WS is throttled.
                        if _strict_provider_policy and _pub_ws:
                            logger.error(
                                "WS 429 on %s and ARBY_STRICT_PROVIDER_POLICY=1 "
                                "forbids public WS fallback (%s)",
                                _try_ws_name, _pub_ws,
                            )
                            _pub_ws = None
                        if _pub_ws and (_pub_ws, "public_fallback") not in _ws_tried_urls:
                            _ws_tried_urls.append((_pub_ws, "public_fallback"))
                        continue
                    else:
                        logger.warning("WS connection failed on %s: %s", _try_ws_name, _conn_err[:100])
                        continue

            if not _ws_connected or _conn is None:
                raise RuntimeError(
                    f"All WS endpoints failed. Tried: "
                    f"{', '.join(urlparse(u).netloc for u, _ in _ws_tried_urls)}"
                )

            _conn.send(sub_msg)
            sub_response = _conn.recv()
            sub_data = json.loads(sub_response)
            sub_id = sub_data.get("result")
            if not sub_id:
                raise RuntimeError(f"WebSocket subscription failed: {sub_data}")
            _conn.settimeout(_recv_timeout_s)
            _ws_connection_status = "connected"
            _ws_error_detail = None
            _ws_subscribe_count += 1
            # E1.50 / TD-003: remember last-working WS endpoint so the next
            # iteration starts from the proven target (skip re-paying drpc
            # 429 reconnect cost). Only memorize non-fallback providers to
            # respect strict provider policy.
            try:
                if ws_provider and ws_provider != "public_fallback":
                    _remember_last_working_ws(
                        getattr(args, "chain", ""), ws_url, ws_provider
                    )
            except Exception as _mem_exc:
                logger.debug(
                    "WS remember-last-working skipped: %s",
                    str(_mem_exc)[:120],
                )
            logger.info(
                "WebSocket newHeads subscribed: sub_id=%s reason=%s recv_timeout=%ds",
                sub_id,
                connect_reason,
                _recv_timeout_s,
                extra={"context": {"ws_url": ws_host, "sub_id": sub_id}},
            )
            return _conn

        # E1.65 Step 7: HTTP-only block polling mode. When ARBY_WS_HTTP_BLOCKS=1
        # (or set via supervisor for cold lanes), skip the WS subscription and
        # instead poll eth_getBlockByNumber("latest") via HTTP every 2 seconds.
        # This reduces WS connections from 4 to 2 (prod hot+cold use WS;
        # disc hot+cold use HTTP polling). Requires no WS endpoint at all.
        _http_blocks_mode = os.getenv("ARBY_WS_HTTP_BLOCKS", "0") == "1"
        _last_http_polled_block: int = 0
        _http_poll_interval_s = max(
            0.5,
            float(os.getenv("ARBY_HTTP_BLOCK_POLL_S", "2.0") or "2.0"),
        )
        if _http_blocks_mode:
            ws_conn = None  # type: ignore[assignment]
            logger.info(
                "HTTP block polling mode active (ARBY_WS_HTTP_BLOCKS=1); "
                "WS subscription skipped (poll interval=%.1fs)",
                _http_poll_interval_s,
            )
        else:
            ws_conn = _open_ws_subscription("initial")

        # M7.A.5.39: Reuse single Web3 instance for all blocks (was per-block)
        from web3 import Web3 as _W3_loop
        _w3_loop = _W3_loop(_W3_loop.HTTPProvider(rpc_url))

        # M7.E1.34m (soak7): capture the precise reason the WS loop exited
        # so reviewer diagnostics can distinguish timeout, recv-error, and
        # structural-cap exits. Previously supervisor saw a bare rc=0 with
        # no hint at why each lane kept ending after ~20s.
        _exit_reason = "loop_not_entered"

        # E1.49: periodic heartbeat — write rollup every N seconds even
        # when WS feed is silent or stuck in 429 reconnect. Reviewer
        # cadence guard checks `last_periodic_heartbeat_at`.
        _hot_hb_interval_s = max(
            5.0,
            float(os.environ.get("ARBY_HOT_HEARTBEAT_INTERVAL_S", "30") or 30),
        )
        _last_hb_monotonic = time.monotonic()
        # E1.50 / TD-003: mid-recv-loop bridge refresh. Re-reads the
        # cold->hot bridge file (no RPC) every M seconds and merges newly
        # resolved pool_token_transport entries into the in-process
        # _pool_token_cache. New pools become scoreable without restarting
        # the WS subscription, decoupling search-window cadence from
        # WS-provider reconnect bursts. Pure additive: cache writes only;
        # registry mutation is left to the iteration boundary to keep the
        # cross-process safety contract (see TD-003 risk note).
        _bridge_refresh_interval_s = max(
            10.0,
            float(
                os.environ.get("ARBY_HOT_BRIDGE_REFRESH_S", "45") or 45
            ),
        )
        _last_bridge_refresh_monotonic = time.monotonic()
        _bridge_refresh_total = 0
        _bridge_refresh_added_total = 0

        while blocks_processed < args.ws_blocks:
            elapsed = time.monotonic() - ws_start_time
            if elapsed > args.ws_timeout:
                logger.info("ws-live timeout reached (%ds)", args.ws_timeout)
                _exit_reason = "ws_timeout"
                break

            # E1.49: periodic mid-cycle heartbeat (lane=hot only — cold has
            # frequent iteration boundaries). Adds last_periodic_heartbeat_at
            # + cycle_window_elapsed_s to the rollup so reviewer can see
            # liveness even during WS 429 storms.
            if (time.monotonic() - _last_hb_monotonic) >= _hot_hb_interval_s:
                try:
                    if str(getattr(args, "lane", "") or "").lower() == "hot":
                        from m7.orderflow.hot_runtime_artifacts import (
                            heartbeat_hot_rollup_cycle as _hb_hot,
                        )
                        _hb_hot(
                            cycle_started_monotonic=ws_start_time,
                            chain=getattr(args, "chain", "arbitrum_one"),
                        )
                except Exception as _hb_exc:
                    logger.debug(
                        "periodic heartbeat skipped: %s", str(_hb_exc)[:80]
                    )
                _last_hb_monotonic = time.monotonic()

            # E1.50 / TD-003: mid-recv-loop bridge refresh. Re-read PTT and
            # warm _pool_token_cache so newly-resolved pools become
            # scoreable without an iteration restart. Hot-lane only —
            # cold lane already has frequent iteration boundaries.
            if (
                str(getattr(args, "lane", "") or "").lower() == "hot"
                and (time.monotonic() - _last_bridge_refresh_monotonic)
                >= _bridge_refresh_interval_s
            ):
                try:
                    from m7.orderflow.bridge_runtime import (
                        _read_cold_hot_bridge as _read_bridge_mid,
                        _populate_pool_token_cache_from_bridge as _populate_mid,
                    )
                    _bridge_mid = _read_bridge_mid()
                    _added_mid = _populate_mid(_bridge_mid)
                    _bridge_refresh_total += 1
                    _bridge_refresh_added_total += int(_added_mid or 0)
                    if _added_mid:
                        logger.info(
                            "mid-loop bridge refresh: +%d ptt entries "
                            "(refresh #%d, total_added=%d)",
                            _added_mid,
                            _bridge_refresh_total,
                            _bridge_refresh_added_total,
                        )
                except Exception as _br_exc:
                    logger.debug(
                        "mid-loop bridge refresh skipped: %s",
                        str(_br_exc)[:120],
                    )
                _last_bridge_refresh_monotonic = time.monotonic()

            # E1.65 Step 7: HTTP block polling alternative to WS recv.
            if _http_blocks_mode:
                # Poll latest block number via HTTP; skip if same block
                time.sleep(_http_poll_interval_s)
                try:
                    _http_cur_block = int(_w3_loop.eth.block_number)
                except Exception as _hpoll_exc:
                    logger.debug(
                        "HTTP block poll failed: %s", str(_hpoll_exc)[:80]
                    )
                    continue
                if _http_cur_block <= _last_http_polled_block:
                    continue  # no new block yet
                _last_http_polled_block = _http_cur_block
                detected_block = _http_cur_block
                blocks_processed += 1
                logger.info(
                    "HTTP-polled block #%d (processed %d/%d)",
                    detected_block, blocks_processed, args.ws_blocks,
                    extra={"context": {"block": detected_block}},
                )
            else:
                # WS recv path (existing code)
                try:
                    msg = ws_conn.recv()
                except Exception as _recv_exc:
                    _recv_err = str(_recv_exc)[:200]
                    _recv_err_l = _recv_err.lower()
                    _ws_last_recv_error = _recv_err
                    if "timed out" in _recv_err_l or isinstance(_recv_exc, TimeoutError):
                        _ws_recv_timeout_count += 1
                        _exit_reason = "recv_timeout"
                        logger.debug(
                            "WebSocket recv timeout after %d blocks; keeping session alive",
                            blocks_processed,
                        )
                        time.sleep(0.05)
                        continue

                    _ws_recv_error_count += 1
                    _ws_reconnect_count += 1
                    _exit_reason = "recv_error_reconnecting"
                    _backoff_s = min(8, 2 ** min(_ws_reconnect_count - 1, 3))
                    _remaining_s = max(0.0, args.ws_timeout - (time.monotonic() - ws_start_time))
                    if _remaining_s <= 0:
                        _exit_reason = "ws_timeout"
                        break
                    logger.warning(
                        "WebSocket recv error after %d blocks: %s; reconnecting in %.1fs",
                        blocks_processed, _recv_err[:120], min(_backoff_s, _remaining_s),
                    )
                    try:
                        ws_conn.close()
                    except Exception:
                        pass
                    time.sleep(min(_backoff_s, _remaining_s))
                    if time.monotonic() - ws_start_time > args.ws_timeout:
                        _exit_reason = "ws_timeout"
                        break
                    # M7.E1.34n (soak8): bounded reconnect-retry loop. Previously
                    # a single resubscribe failure re-raised and killed the whole
                    # child process, producing the `recv_error_reconnect_failed`
                    # clean-exit pattern the reviewer flagged. We now retry up to
                    # _MAX_RECONNECT_ATTEMPTS with exponential cooldown while the
                    # ws_timeout budget still allows; only if every attempt fails
                    # do we record `recv_error_reconnect_failed` and leave the
                    # loop — but cleanly via break, not via raise, so the outer
                    # except does not repaint exit_reason as `ws_exception`.
                    _MAX_RECONNECT_ATTEMPTS = int(
                        os.environ.get("ARBY_WS_MAX_RECONNECT_ATTEMPTS", "4") or 4
                    )
                    _reconnect_attempt = 0
                    _reconnected = False
                    while _reconnect_attempt < _MAX_RECONNECT_ATTEMPTS:
                        _reconnect_attempt += 1
                        _cool_remaining = max(
                            0.0, args.ws_timeout - (time.monotonic() - ws_start_time)
                        )
                        if _cool_remaining <= 0:
                            _exit_reason = "ws_timeout"
                            break
                        try:
                            ws_conn = _open_ws_subscription(
                                f"recv_error_retry{_reconnect_attempt}"
                            )
                            _reconnected = True
                            _exit_reason = "reconnected_after_recv_error"
                            break
                        except Exception as _reconn_exc:
                            _reconn_err = str(_reconn_exc)[:200]
                            _ws_last_recv_error = f"reconnect_fail:{_reconn_err}"
                            # M7.E1.34n-soak9: rate-limit-aware cooldown. Public
                            # Base preconf / blastapi return JSON-RPC code 15
                            # ("Too many request") or HTTP 429 inside a wide rate
                            # window. The default 1.5^n cap of 8s burns the whole
                            # reconnect budget before the window clears. When we
                            # detect a rate-limit signature we extend cooldown to
                            # ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S (default 30s)
                            # so exponential backoff meets the provider's actual
                            # reset window.
                            _rl_lower = _reconn_err.lower()
                            _is_rate_limited = (
                                "too many request" in _rl_lower
                                or "'code': 15" in _rl_lower
                                or "\"code\": 15" in _rl_lower
                                or "429" in _rl_lower
                                or "rate limit" in _rl_lower
                            )
                            if _is_rate_limited:
                                try:
                                    _rl_cool_env = float(
                                        os.environ.get(
                                            "ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S",
                                            "30",
                                        )
                                    )
                                except Exception:
                                    _rl_cool_env = 30.0
                                _cool = min(_rl_cool_env, _cool_remaining)
                                # E1.65 Step 8: write cross-process cooldown file so
                                # other WS lanes on the same chain back off too.
                                _write_ws_cooldown(
                                    getattr(args, "chain", "base"), _rl_cool_env
                                )
                            else:
                                _cool = min(8.0, 1.5 ** _reconnect_attempt)
                                _cool = min(_cool, _cool_remaining)
                            logger.warning(
                                "WS reconnect attempt %d/%d failed: %s; cooling %.1fs%s",
                                _reconnect_attempt, _MAX_RECONNECT_ATTEMPTS,
                                _reconn_err[:120], _cool,
                                " (rate-limit)" if _is_rate_limited else "",
                            )
                            if _cool > 0:
                                time.sleep(_cool)
                    if not _reconnected:
                        _exit_reason = "recv_error_reconnect_failed"
                        # E1.46 reviewer fix #4: classify rate-limit-driven
                        # reconnect storms as failed_429 so
                        # session_ws_failed_429_windows actually counts
                        # dRPC code 15 / "Too many request" / HTTP 429
                        # cascades on reconnect (previously only HTTP 429
                        # on the very first connect was tagged 429).
                        _last_err_lower = (_ws_last_recv_error or "").lower()
                        if (
                            "too many request" in _last_err_lower
                            or "'code': 15" in _last_err_lower
                            or "\"code\": 15" in _last_err_lower
                            or "code\":15" in _last_err_lower
                            or "code': 15" in _last_err_lower
                            or " 429" in _last_err_lower
                            or ":429" in _last_err_lower
                            or "rate limit" in _last_err_lower
                            or "rate-limit" in _last_err_lower
                        ):
                            _ws_connection_status = "failed_429"
                            _ws_error_detail = (
                                "WS reconnect storm rate-limited; last="
                                f"{(_ws_last_recv_error or '')[:120]}"
                            )
                        break
                    continue

                data = json.loads(msg)
                params = data.get("params", {})
                result = params.get("result", {})
                block_hex = result.get("number")
                if not block_hex:
                    continue
                detected_block = int(block_hex, 16)
                blocks_processed += 1
                logger.info(
                    "newHead #%d: block=%d (processed %d/%d)",
                    detected_block,
                    detected_block,
                    blocks_processed,
                    args.ws_blocks,
                    extra={"context": {"block": detected_block}},
                )

            # Fetch swap logs for THIS block only
            # M7.A.5.47: Hybrid hot intake — focused + periodic broad fallback.
            # Focused: address filter for bridge pools (high hit rate when active).
            # Broad: every _BROAD_FALLBACK_INTERVAL blocks, scan ALL swaps.
            #   This catches events the focused filter misses and provides
            #   diagnostics (events_at_non_bridge_pools vs no_events_at_all).
            _hot_mode_active = external_registry is not None
            # M7.A.5.47e: Adaptive broad fallback — controlled by caller's
            # bridge_hit_deficit flag (from rollup: events>0 but hits=0).
            # Within-window: also go broad early if we see broad logs but
            # no focused logs (intra-iteration learning).
            _intra_window_deficit = (
                _broad_logs > 0
                and _hot_mode_active
                and bridge_pool_addresses
                and _focused_logs == 0
            )
            _BROAD_FALLBACK_INTERVAL = (
                1 if bridge_hit_deficit_severe
                else 2 if (bridge_hit_deficit or _intra_window_deficit)
                else 3
            )
            _is_broad_block = (blocks_processed % _BROAD_FALLBACK_INTERVAL) == 0
            try:
                _log_filter: dict = {
                    "fromBlock": detected_block,
                    "toBlock": detected_block,
                    "topics": [SWAP_EVENT_TOPIC],
                }
                if _hot_mode_active and bridge_pool_addresses and not _is_broad_block:
                    # Focused: only bridge pool addresses (up to cap)
                    # M7.A.5.47d: Adaptive cap — use all bridge addresses
                    # (already capped at 50-100 by bridge ranking in loop.py)
                    _addr_list = list(bridge_pool_addresses)
                    _log_filter["address"] = _addr_list
                # else: broad scan — no address filter
                logs = _w3_loop.eth.get_logs(_log_filter)
            except Exception as exc:
                logger.debug(
                    "Failed to fetch logs for block %d: %s",
                    detected_block,
                    str(exc)[:100],
                )
                continue

            raw_logs_total += len(logs)
            # M7.A.5.47: Track broad vs focused diagnostics
            if _is_broad_block or not (_hot_mode_active and bridge_pool_addresses):
                _broad_blocks += 1
                _broad_logs += len(logs)
            else:
                _focused_blocks += 1
                _focused_logs += len(logs)
            if not logs:
                continue

            # M7.A.5.47c: Track pool addresses from raw logs (before normalization)
            if _hot_mode_active:
                for _lg in logs:
                    _lg_addr = (_lg.get("address") or "").lower()
                    if _lg_addr:
                        _hot_event_pool_counts[_lg_addr] = _hot_event_pool_counts.get(_lg_addr, 0) + 1

            # E1.51 slice-3: feed local pool price state registry from raw
            # WS logs. Passive sink; never raises. Gated by
            # ARBY_USE_LOCAL_PRICE_STATE (default on).
            if os.environ.get("ARBY_USE_LOCAL_PRICE_STATE", "1") not in ("0", "false", "False"):
                try:
                    _pps_ret = _feed_pool_price_logs(getattr(args, "chain", "base"), logs)
                    _funnel_debug["pps_v3_updates"] += _pps_ret.get("v3_updates", 0)
                    _funnel_debug["pps_v2_updates"] += _pps_ret.get("v2_updates", 0)
                    _funnel_debug["pps_skipped"] += _pps_ret.get("skipped", 0)
                except Exception:
                    pass

            # Normalize logs
            block_events = []
            _normalize_drops: Dict[str, int] = {}
            for i, log_entry in enumerate(logs):
                ev = normalize_swap_log(
                    log=log_entry,
                    addr_to_symbol=addr_to_symbol,
                    token_addresses=token_addresses,
                    dex_configs=dex_configs,
                    event_index=i,
                    drop_counter=_normalize_drops,
                )
                if ev is not None:
                    block_events.append(ev)
            # Merge per-block drops into session counter
            for _b, _n in _normalize_drops.items():
                _key = f"normalize_drops_{_b}"
                _funnel_debug[_key] = _funnel_debug.get(_key, 0) + _n

            if not block_events:
                if len(logs) > 0:
                    _funnel_debug["blocks_dropped_all_normalized_none"] += 1
                continue

            # P6 (2026-04-20): raise floor for broad_fallback blocks to cut
            # noise. Watchlist (focused bridge blocks) keeps chain floor;
            # broad fallback events require ARBY_BROAD_FALLBACK_MIN_USD
            # (default $500) to proceed.
            if _is_broad_block or not (_hot_mode_active and bridge_pool_addresses):
                try:
                    _broad_floor = float(os.environ.get(
                        "ARBY_BROAD_FALLBACK_MIN_USD", "500") or "500")
                except Exception:
                    _broad_floor = 500.0
                if _broad_floor > 0:
                    _pre_floor_count = len(block_events)
                    block_events = [
                        e for e in block_events
                        if getattr(e, "estimated_size_usd", 0) >= _broad_floor
                    ]
                    _dropped = _pre_floor_count - len(block_events)
                    if _dropped > 0:
                        _funnel_debug["events_dropped_broad_floor"] += _dropped
                if not block_events:
                    _funnel_debug["blocks_dropped_all_below_broad_floor"] += 1
                    continue

            # Sort by size, take up to max_events per block
            block_events.sort(key=lambda e: e.estimated_size_usd, reverse=True)
            events_to_score = block_events[:max(1, args.max_events // args.ws_blocks)]

            # M7.A.5.24: Two-queue priority — low-lag events first
            # Events with detection_lag <= 2 get scored before stale events
            # so they don't compete for the same scoring budget.
            _low_lag_queue = [e for e in events_to_score if (detected_block - e.block_number) <= 2]
            _stale_queue = [e for e in events_to_score if (detected_block - e.block_number) > 2]
            events_to_score = _low_lag_queue + _stale_queue

            # M7.A.5.40: Cold-lane batch pre-resolve + pre-enrich + pre-registry.
            # Moves per-event RPC calls (resolve_ms, enrichment_ms, registry_preload_ms)
            # into a single batch pass before scoring. Individual scoring calls then
            # hit module-level caches for near-zero latency.
            _hot_mode = external_registry is not None
            if not _hot_mode and events_to_score:
                _pre_pool_addrs = list(set(
                    ev.pool_address for ev in events_to_score
                    if ev.pool_address
                ))
                if _pre_pool_addrs:
                    try:
                        _pre_resolved = batch_pre_resolve_pools(
                            _pre_pool_addrs, rpc_url, detected_block, addr_to_symbol,
                        )
                        # Batch-preload discovered token pairs into registry
                        _pre_pairs_done: set = set()
                        for _pa, _pinfo in _pre_resolved.items():
                            _t0 = _pinfo["token0"]
                            _t1 = _pinfo["token1"]
                            _ppk = f"{min(_t0.lower(), _t1.lower())}/{max(_t0.lower(), _t1.lower())}"
                            if _ppk not in _pre_pairs_done:
                                _pre_pairs_done.add(_ppk)
                                try:
                                    session_registry.preload_pair(
                                        _t0, _t1, dex_configs, rpc_url, detected_block,
                                    )
                                except Exception:
                                    pass
                    except Exception as _pre_exc:
                        logger.debug("Cold pre-resolve batch failed: %s", str(_pre_exc)[:100])

            # Score with parallel pipeline
            current_block = detected_block
            for ev in events_to_score:
                r = None
                # M7.A.5.33: Hot-mode fast path — zero-RPC scoring via prewarmed registry
                if _hot_mode:
                    r = score_backrun_fast(
                        event=ev,
                        pool_registry=session_registry,
                        token_addresses=token_addresses,
                        current_block=current_block,
                        event_detected_at_block=detected_block,
                        block_time_ms=block_time_ms,
                        addr_to_symbol=addr_to_symbol,
                        chain=args.chain,  # M7.E1.6: chain-aware gas floor
                        l1_fee_bps=_l1_fee_bps_cached,  # E1.12.1: dynamic L1 data fee
                    )
                    # M7.A.5.34: Hot mode — no parallel fallback. If fast path
                    # returns None (pair not in registry / no state), create a
                    # lightweight skip result. This eliminates ~1940ms parallel
                    # pipeline latency from the hot lane entirely.
                    if r is None:
                        _pair = f"{ev.token_in}/{ev.token_out}"
                        r = BackrunResult(
                            event_id=ev.event_id,
                            event_source="live",
                            event_type=ev.event_type,
                            post_trade_state_used="live",
                            backrun_direction="skip",
                            reject_reason="REJECT_NOT_IN_HOT_REGISTRY",
                            event_block=ev.block_number,
                            quote_block=current_block,
                            block_lag=current_block - ev.block_number,
                            event_detected_at_block=detected_block,
                            actual_pair=_pair,
                            scoring_path="hot_skip",
                        )
                else:
                    # Cold lane: full pipeline
                    r = score_backrun_live_parallel(
                        event=ev,
                        rpc_url=rpc_url,
                        dex_configs=dex_configs,
                        token_addresses=token_addresses,
                        current_block=current_block,
                        ws_provider=ws_provider,
                        event_detected_at_block=detected_block,
                        fallback_rpc_urls=None,
                        block_time_ms=block_time_ms,
                        addr_to_symbol=addr_to_symbol,
                        subgraph_seeded_addrs=subgraph_seeded_addrs,
                        pool_registry=session_registry,
                        chain=args.chain,
                    )
                if r is None:
                    # Defensive guard: keep ws-live running even if scoring returns None.
                    _pair = f"{ev.token_in}/{ev.token_out}"
                    r = BackrunResult(
                        event_id=ev.event_id,
                        event_source="live",
                        event_type=ev.event_type,
                        post_trade_state_used="live",
                        backrun_direction="skip",
                        reject_reason="REJECT_SCORING_RETURNED_NONE",
                        event_block=ev.block_number,
                        quote_block=current_block,
                        block_lag=current_block - ev.block_number,
                        event_detected_at_block=detected_block,
                        actual_pair=_pair,
                        scoring_path="cold_skip",
                    )
                # Attach source event for downstream fast-path re-scoring
                r._source_event = ev
                all_results.append(r)
                all_events.append(ev)

                # M7.A.5.23: Accumulate low-lag scoring path data
                # Use detection-time lag (current_block - event.block_number)
                # not final block_lag (which includes scoring latency)
                _ev_lag = current_block - ev.block_number
                if _ev_lag <= 2:
                    _pair_key = r.actual_pair or f"{ev.token_in}/{ev.token_out}"
                    if _pair_key in _session_low_lag_pairs:
                        _slp = _session_low_lag_pairs[_pair_key]
                        _slp["seen_count"] += 1
                        _slp["last_block"] = max(_slp["last_block"], ev.block_number)
                        if r.reject_reason is None or r.reject_reason not in UNSCORED_REJECTS:
                            _slp["scored_count"] += 1
                        if getattr(r, "scoring_path", None) == "registry_direct":
                            _slp["registry_direct_count"] += 1
                    else:
                        _session_low_lag_pairs[_pair_key] = {
                            "pair": _pair_key,
                            "first_block": ev.block_number,
                            "last_block": ev.block_number,
                            "seen_count": 1,
                            "scored_count": (
                                1 if r.reject_reason is None
                                or r.reject_reason not in UNSCORED_REJECTS
                                else 0
                            ),
                            "registry_direct_count": (
                                1 if getattr(r, "scoring_path", None)
                                == "registry_direct" else 0
                            ),
                        }

                if len(all_results) >= args.max_events:
                    break

            if len(all_results) >= args.max_events:
                logger.info("max_events reached (%d), stopping", args.max_events)
                _exit_reason = "max_events_reached"
                break
        else:
            # while-loop completed naturally: ws_blocks exhausted
            _exit_reason = "ws_blocks_exhausted"
    except Exception as exc:
        _ws_err_str = str(exc)[:200]
        if "429" in _ws_err_str:
            _ws_connection_status = "failed_429"
            _ws_error_detail = "Alchemy WS rate limit (429 Too Many Requests)"
            _exit_reason = "ws_429"
            try:
                run_ws_live._last_429_ts = time.time()  # type: ignore[attr-defined]
            except Exception:
                pass
            logger.error(
                "WebSocket 429 rate limit: %s (scored %d events from %d blocks). "
                "This makes events_count=0 UNRELIABLE — it's a connection failure, not market state.",
                _ws_err_str[:100], len(all_results), blocks_processed,
            )
        else:
            if _ws_connection_status == "not_attempted":
                _ws_connection_status = "failed_other"
            _ws_error_detail = _ws_err_str
            if _exit_reason != "recv_error_reconnect_failed":
                _exit_reason = "ws_exception"
            logger.warning(
                "WebSocket error: %s (scored %d events from %d blocks)",
                _ws_err_str, len(all_results), blocks_processed,
            )
    finally:
        try:
            if ws_conn is not None:
                ws_conn.close()
        except Exception:
            pass
        # E1.65 Step 6: release WS lease on clean exit
        try:
            _release_ws_lease()
        except Exception:
            pass

    ws_elapsed = time.monotonic() - ws_start_time

    # E1.22: Annotate profit guard on all results BEFORE artifact build
    # so that gate_trace and signal_counts reflect guard decisions.
    annotate_profit_guard_results(all_results, chain=args.chain)

    # Build artifact
    # M7.A.5.46: compact=True skips full results serialization (operational path).
    # Raw BackrunResult objects are carried separately for hot lane downstream.
    artifact = build_replay_summary(all_events, all_results, mode="ws_live", compact=True, chain=args.chain)
    artifact["_raw_results"] = all_results
    artifact["ws_live_config"] = {
        "ws_blocks_requested": args.ws_blocks,
        "ws_timeout_seconds": args.ws_timeout,
        "max_events": args.max_events,
    }
    artifact["ws_live_stats"] = {
        "blocks_processed": blocks_processed,
        "raw_logs_total": raw_logs_total,
        "normalized_events": len(all_events),
        "events_scored": len(all_results),
        "ws_elapsed_seconds": round(ws_elapsed, 2),
        # M7.E1.10: WS connection health — critical for distinguishing
        # "no market events" from "couldn't connect to data source"
        "ws_connection_status": _ws_connection_status,
        "ws_error_detail": _ws_error_detail,
        # M7.E1.10: Actual provider path after fallback resolution
        "rpc_provider": rpc_provider,
        "ws_provider": ws_provider,
        # M7.A.5.47: Hybrid intake diagnostics
        "broad_blocks": _broad_blocks,
        "focused_blocks": _focused_blocks,
        "broad_logs": _broad_logs,
        "focused_logs": _focused_logs,
        # M7.A.5.47c: Pool addresses seen in hot events (top 20 by count)
        "hot_event_pool_histogram": sorted(
            [{"pool": pa, "count": ct} for pa, ct in _hot_event_pool_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )[:20],
        # M7.E1.34k: funnel_debug — non-silent counters for every drop path
        "funnel_debug": dict(_funnel_debug),
        # M7.E1.34m (soak7): why the WS scan loop ended — essential for
        # diagnosing repeated 20s-clean-exits during long soaks.
        "exit_reason": _exit_reason,
        "ws_reconnect_count": _ws_reconnect_count,
        "ws_recv_error_count": _ws_recv_error_count,
        "ws_recv_timeout_count": _ws_recv_timeout_count,
        "ws_subscribe_count": _ws_subscribe_count,
        "ws_last_recv_error": _ws_last_recv_error,
    }
    # M7.E1.10: Surface connection status at artifact top level
    artifact["ws_connection_status"] = _ws_connection_status
    # M7.A.5.22: Registry session stats
    artifact["registry_session_stats"] = {
        "preload_calls": session_registry.preload_calls,
        "cache_hits": session_registry.cache_hits,
        "pools_discovered": session_registry.pools_discovered,
        "pools_active": session_registry.pools_active,
        "unique_pairs_queried": len(session_registry._queried),
    }
    # M7.A.5.23: Session-persistent low-lag pair tracking
    artifact["session_low_lag_pairs"] = list(_session_low_lag_pairs.values())
    # Provider provenance
    artifact["rpc_provider"] = rpc_provider
    artifact["rpc_source"] = rpc_diag.get("source", "unknown")
    artifact["resolved_rpc_host"] = rpc_host
    artifact["ws_provider"] = ws_provider
    artifact["ws_source"] = ws_diag.get("source", "unknown")
    artifact["resolved_ws_host"] = ws_host
    artifact["fallback_used"] = (
        "fallback" in rpc_diag.get("source", "")
        or "fallback" in ws_diag.get("source", "")
    )
    artifact["http_fallback_used"] = "fallback" in rpc_diag.get("source", "")
    artifact["ws_fallback_used"] = "fallback" in ws_diag.get("source", "")

    # Live state metrics
    live_results = [r for r in all_results if r.event_block is not None]

    # M7.A.5.25: Detection-time lag helper for ws-live metrics
    def _det_lag(r):
        if r.event_detected_at_block is not None and r.event_block is not None:
            return r.event_detected_at_block - r.event_block
        return 999

    if live_results:
        artifact["live_state_metrics"] = {
            "events_with_block_data": len(live_results),
            "mean_block_lag": round(
                sum(r.block_lag or 0 for r in live_results) / len(live_results), 2
            ),
            # M7.A.5.25: same_block_count uses detection-time lag (not final same_state_class)
            "same_block_count": sum(
                1 for r in live_results if _det_lag(r) == 0
            ),
            "next_block_count": sum(
                1 for r in live_results if _det_lag(r) in (1, 2)
            ),
            "stale_count": sum(
                1 for r in live_results if _det_lag(r) > 2
            ),
            "venues_quoted_max": max(r.counter_venue_count for r in live_results) if live_results else 0,
            "venues_quoted_mean": round(
                sum(r.counter_venue_count for r in live_results) / len(live_results), 2
            ),
            "mean_pipeline_latency_ms": round(
                sum(r.quote_pipeline_latency_ms or 0 for r in live_results) / len(live_results), 2
            ),
            "total_venues_pruned_by_multicall": sum(
                r.venues_pruned_by_multicall for r in live_results
            ),
        }
        # M7.A.5.4: Two-stage pruning metrics
        calls_attempted = [r.quote_calls_attempted for r in live_results if r.quote_calls_attempted is not None]
        calls_after = [r.quote_calls_after_pruning for r in live_results if r.quote_calls_after_pruning is not None]
        if calls_attempted:
            artifact["live_state_metrics"]["mean_quote_calls_attempted"] = round(
                sum(calls_attempted) / len(calls_attempted), 2
            )
        if calls_after:
            artifact["live_state_metrics"]["mean_quote_calls_after_pruning"] = round(
                sum(calls_after) / len(calls_after), 2
            )
        # Aggregate prune_reason_histogram across all events
        agg_prune: Dict[str, int] = {}
        for r in live_results:
            if r.prune_reason_histogram:
                for reason, cnt in r.prune_reason_histogram.items():
                    agg_prune[reason] = agg_prune.get(reason, 0) + cnt
        if agg_prune:
            artifact["live_state_metrics"]["prune_reason_histogram"] = agg_prune
        # Aggregate stage latency
        stage_a_times = [r.pipeline_stage_latency_ms.get("stage_a_ms") for r in live_results if r.pipeline_stage_latency_ms and "stage_a_ms" in r.pipeline_stage_latency_ms]
        stage_b_times = [r.pipeline_stage_latency_ms.get("stage_b_ms") for r in live_results if r.pipeline_stage_latency_ms and "stage_b_ms" in r.pipeline_stage_latency_ms]
        if stage_a_times:
            artifact["live_state_metrics"]["mean_stage_a_ms"] = round(sum(stage_a_times) / len(stage_a_times), 2)
        if stage_b_times:
            artifact["live_state_metrics"]["mean_stage_b_ms"] = round(sum(stage_b_times) / len(stage_b_times), 2)
        live_net = [r.best_live_net_bps for r in live_results if r.best_live_net_bps is not None]
        if live_net:
            artifact["live_state_metrics"]["best_live_net_bps"] = round(max(live_net), 4)
            artifact["live_state_metrics"]["worst_live_net_bps"] = round(min(live_net), 4)
            artifact["live_state_metrics"]["mean_live_net_bps"] = round(
                sum(live_net) / len(live_net), 4
            )
        # Low-lag subset metrics (ws-specific: should have more than polling)
        # M7.A.5.25: Use detection-time lag, not final same_state_class
        low_lag = [
            r for r in live_results
            if _det_lag(r) <= 2
        ]
        low_lag_net = [
            r.best_live_net_bps for r in low_lag
            if r.best_live_net_bps is not None
        ]
        _ll_scored = [
            r for r in low_lag
            if r.reject_reason not in UNSCORED_REJECTS
        ]
        _ll_scored_net = [
            r.best_live_net_bps for r in _ll_scored
            if r.best_live_net_bps is not None
        ]
        artifact["live_state_metrics"]["events_detected_low_lag_ws"] = len(low_lag)
        artifact["live_state_metrics"]["events_scored_low_lag_ws"] = len(_ll_scored)
        artifact["live_state_metrics"]["best_live_net_bps_low_lag_ws"] = (
            round(max(_ll_scored_net), 4) if _ll_scored_net else None
        )
        artifact["live_state_metrics"]["events_detected_low_lag"] = len(low_lag)
        artifact["live_state_metrics"]["events_scored_low_lag"] = len(_ll_scored)
        artifact["live_state_metrics"]["best_live_net_bps_low_lag"] = (
            round(max(_ll_scored_net), 4) if _ll_scored_net else None
        )

        # M7.A.5.14: ws-live low-lag reject decomposition
        _ws_ll_reject_counts: Dict[str, int] = {}
        for r in low_lag:
            if r.reject_reason:
                _ws_ll_reject_counts[r.reject_reason] = (
                    _ws_ll_reject_counts.get(r.reject_reason, 0) + 1
                )
        artifact["live_state_metrics"]["low_lag_reject_histogram_ws"] = _ws_ll_reject_counts
        _ws_ll_n = len(low_lag)
        _ws_ll_pair_resolved = sum(
            1 for r in low_lag
            if r.reject_reason not in (REJECT_TOKEN_PAIR_UNRESOLVED,)
        )
        _ws_ll_pre_econ = sum(
            1 for r in low_lag if r.reject_reason in UNSCORED_REJECTS
        )
        artifact["live_state_metrics"]["low_lag_pair_resolution_rate_ws"] = (
            round(_ws_ll_pair_resolved / _ws_ll_n, 4) if _ws_ll_n else None
        )
        artifact["live_state_metrics"]["low_lag_pre_econ_reject_rate_ws"] = (
            round(_ws_ll_pre_econ / _ws_ll_n, 4) if _ws_ll_n else None
        )

        # M7.A.5.3.1 — Latency budget metrics (relative to chain block_time_ms)
        pipeline_latencies = [
            r.quote_pipeline_latency_ms for r in live_results
            if r.quote_pipeline_latency_ms is not None
        ]
        budget_hits = [
            lat for lat in pipeline_latencies if lat < block_time_ms
        ]
        artifact["live_state_metrics"]["latency_budget_ms"] = block_time_ms
        artifact["live_state_metrics"]["latency_budget_hit_rate"] = (
            round(len(budget_hits) / len(pipeline_latencies), 4)
            if pipeline_latencies else 0.0
        )
        artifact["live_state_metrics"]["sub_block_capable"] = len(budget_hits) > 0

        # M7.A.5.3.1 — Separate low-lag vs stale summaries
        # M7.A.5.25: Use detection-time lag for stale classification
        stale = [
            r for r in live_results
            if _det_lag(r) > 2
        ]
        stale_net = [
            r.best_live_net_bps for r in stale
            if r.best_live_net_bps is not None
        ]
        artifact["ws_low_lag_summary"] = {
            "count": len(low_lag),
            "best_net_bps": round(max(low_lag_net), 4) if low_lag_net else None,
            "worst_net_bps": round(min(low_lag_net), 4) if low_lag_net else None,
            "mean_net_bps": (
                round(sum(low_lag_net) / len(low_lag_net), 4)
                if low_lag_net else None
            ),
            # M7.A.5.25: same/next block counts use detection-time lag
            "same_block_count": sum(
                1 for r in low_lag if _det_lag(r) == 0
            ),
            "next_block_count": sum(
                1 for r in low_lag if _det_lag(r) in (1, 2)
            ),
            "mean_pipeline_latency_ms": (
                round(
                    sum(r.quote_pipeline_latency_ms or 0 for r in low_lag)
                    / len(low_lag), 2
                ) if low_lag else None
            ),
            "viable_count": sum(1 for r in low_lag if r.route_viable),
            "mean_quote_calls_after_pruning": (
                round(
                    sum(r.quote_calls_after_pruning or 0 for r in low_lag)
                    / len(low_lag), 2
                ) if low_lag else None
            ),
        }
        artifact["ws_stale_summary"] = {
            "count": len(stale),
            "best_net_bps": round(max(stale_net), 4) if stale_net else None,
            "worst_net_bps": round(min(stale_net), 4) if stale_net else None,
            "mean_net_bps": (
                round(sum(stale_net) / len(stale_net), 4)
                if stale_net else None
            ),
            "mean_block_lag": (
                round(
                    sum(r.block_lag or 0 for r in stale) / len(stale), 2
                ) if stale else None
            ),
            "mean_pipeline_latency_ms": (
                round(
                    sum(r.quote_pipeline_latency_ms or 0 for r in stale)
                    / len(stale), 2
                ) if stale else None
            ),
            "viable_count": sum(1 for r in stale if r.route_viable),
        }

        # M7.A.5.5: Pair resolution metrics
        resolved_results = [r for r in live_results if r.pair_resolved]
        unresolved_results = [r for r in live_results if not r.pair_resolved]
        resolved_net = [r.best_live_net_bps for r in resolved_results if r.best_live_net_bps is not None]
        unresolved_net = [r.best_live_net_bps for r in unresolved_results if r.best_live_net_bps is not None]
        actual_pairs_seen = list(set(r.actual_pair for r in resolved_results if r.actual_pair))
        size_sources = {}
        for r in live_results:
            src = r.size_source or "unknown"
            size_sources[src] = size_sources.get(src, 0) + 1
        artifact["pair_resolution_metrics"] = {
            "events_pair_resolved": len(resolved_results),
            "events_pair_unresolved": len(unresolved_results),
            "pair_resolution_rate": round(
                len(resolved_results) / len(live_results), 4
            ) if live_results else 0.0,
            "actual_pairs_seen": actual_pairs_seen,
            "resolved_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
            "resolved_mean_net_bps": (
                round(sum(resolved_net) / len(resolved_net), 4)
                if resolved_net else None
            ),
            "size_source_histogram": size_sources,
        }

        # M7.A.5.5: M4 vs M7 economics comparison block
        resolved_with_amounts = [r for r in resolved_results if r.amount_in_wei > 0]
        if resolved_with_amounts:
            mean_amount_wei = sum(r.amount_in_wei for r in resolved_with_amounts) // len(resolved_with_amounts)
            mean_gross_bps = round(
                sum(
                    (r.gross_pnl_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in resolved_with_amounts
                ) / len(resolved_with_amounts), 4
            )
            mean_gas_bps = round(
                sum(
                    (r.gas_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in resolved_with_amounts
                ) / len(resolved_with_amounts), 4
            )
        else:
            mean_amount_wei = 0
            mean_gross_bps = None
            mean_gas_bps = None

        artifact["m4_m7_comparison"] = {
            "m4_best_net_bps": -3.5062,
            "m4_frontier_pair": "WBTC/USDC",
            "m4_size_usd": 50,
            "m4_gas_bps": 2.01,
            "m7_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
            "m7_mean_gross_bps": mean_gross_bps,
            "m7_mean_gas_bps": mean_gas_bps,
            "m7_mean_size_wei": mean_amount_wei,
            "m7_latency_class": "stale" if not low_lag else "low_lag",
            "m7_pair_resolved_count": len(resolved_results),
            "note": "M4 uses pair-specific dynamic sweep; M7 uses event-driven replay with actual-pair resolution",
        }

        # ── M7.A.5.6: Coverage scan metrics ────────────────────────
        admitted_results = [r for r in live_results if r.token_admitted is True]
        not_admitted = [r for r in live_results if r.token_admitted is False]
        coverage_complete_results = [
            r for r in live_results
            if r.coverage_result and r.coverage_result.get("coverage_complete")
        ]
        coverage_blocker_hist: Dict[str, int] = {}
        for r in live_results:
            if r.coverage_result and r.coverage_result.get("coverage_blocker_reason"):
                reason = r.coverage_result["coverage_blocker_reason"]
                coverage_blocker_hist[reason] = coverage_blocker_hist.get(reason, 0) + 1

        artifact["coverage_scan_metrics"] = {
            "events_admitted": len(admitted_results),
            "events_not_admitted": len(not_admitted),
            "events_coverage_complete": len(coverage_complete_results),
            "coverage_blocker_histogram": coverage_blocker_hist,
            "admission_rate": round(
                len(admitted_results) / len(live_results), 4
            ) if live_results else 0.0,
        }

        # ── M7.A.5.6: Size sweep metrics ───────────────────────────
        sweep_events = [r for r in live_results if r.size_sweep_results]
        all_sweep_nets = []
        for r in sweep_events:
            for s in (r.size_sweep_results or []):
                if s.get("net_bps", 0) != 0.0:
                    all_sweep_nets.append(s["net_bps"])
        events_with_sweep_best = [r for r in live_results if r.best_sweep_net_bps is not None]

        artifact["size_sweep_metrics"] = {
            "events_with_sweep": len(sweep_events),
            "sweep_net_bps_all": all_sweep_nets,
            "best_sweep_net_bps": round(max(all_sweep_nets), 4) if all_sweep_nets else None,
            "mean_sweep_net_bps": (
                round(sum(all_sweep_nets) / len(all_sweep_nets), 4)
                if all_sweep_nets else None
            ),
            "events_with_positive_sweep": sum(1 for n in all_sweep_nets if n > 0),
        }

        # ── M7.A.5.6: m4_m7_comparison_v2 block ────────────────────
        v2_resolved_with_amounts = [r for r in resolved_results if r.amount_in_wei > 0]
        v2_gross_bps = None
        v2_gas_bps = None
        v2_fee_bps = None
        v2_size_usd = None
        if v2_resolved_with_amounts:
            v2_gross_bps = round(
                sum(
                    (r.gross_pnl_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in v2_resolved_with_amounts
                ) / len(v2_resolved_with_amounts), 4
            )
            v2_gas_bps = round(
                sum(
                    (r.gas_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in v2_resolved_with_amounts
                ) / len(v2_resolved_with_amounts), 4
            )
            v2_fee_bps = round(
                sum(
                    (r.fee_cost_wei / r.amount_in_wei * 10000) if r.amount_in_wei > 0 else 0
                    for r in v2_resolved_with_amounts
                ) / len(v2_resolved_with_amounts), 4
            )
            v2_size_usd = round(
                sum(r.amount_in_wei for r in v2_resolved_with_amounts)
                / len(v2_resolved_with_amounts) / 10**18 * 3000, 2
            )

        artifact["m4_m7_comparison_v2"] = {
            "m4_best_net_bps": -3.5062,
            "m4_gross_pre_cost_bps": 36.35,
            "m4_gas_bps": 2.01,
            "m4_fee_bps": 31.0,
            "m4_slippage_bps": 6.85,
            "m4_size_usd": 50,
            "m4_pair": "WBTC/USDC",
            "m7_best_net_bps": round(max(resolved_net), 4) if resolved_net else None,
            "m7_gross_pre_cost_bps": v2_gross_bps,
            "m7_gas_bps": v2_gas_bps,
            "m7_fee_bps": v2_fee_bps,
            "m7_slippage_bps": None,
            "m7_size_usd": v2_size_usd,
            "m7_pair_resolved": True,
            "m7_coverage_complete_count": len(coverage_complete_results),
            "m7_latency_class": "stale" if not low_lag else "low_lag",
            "m7_best_sweep_net_bps": (
                round(max(all_sweep_nets), 4) if all_sweep_nets else None
            ),
            "note": (
                "M4 has mature pair-specific dynamic sweep; "
                "M7 now has pair-resolved coverage + bounded event-size evaluation"
            ),
        }

        # ── M7.A.5.6: Granular reject histogram ────────────────────
        granular_hist: Dict[str, int] = {}
        for r in live_results:
            if r.reject_reason:
                granular_hist[r.reject_reason] = granular_hist.get(r.reject_reason, 0) + 1
        artifact["reject_histogram_v2"] = granular_hist

        # ── M7.A.5.7: Enrichment metrics ───────────────────────────
        adm_source_hist: Dict[str, int] = {}
        for r in live_results:
            src = r.admission_source or "unknown"
            adm_source_hist[src] = adm_source_hist.get(src, 0) + 1
        enriched_count = sum(
            1 for r in live_results
            if r.admission_source in (ADMISSION_SUBGRAPH_VERIFIED, ADMISSION_ONCHAIN_ENRICHED)
        )
        artifact["enrichment_metrics"] = {
            "admission_source_histogram": adm_source_hist,
            "events_enriched_onchain": enriched_count,
            "enrichment_admission_rate": round(
                enriched_count / len(live_results), 4
            ) if live_results else 0.0,
            "total_admitted": sum(
                1 for r in live_results if r.token_admitted is True
            ),
            "total_rejected": sum(
                1 for r in live_results if r.token_admitted is False
            ),
        }

        # ── M7.A.5.7: Oracle guard metrics ─────────────────────────
        events_with_oracle = [
            r for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_price_available")
        ]
        guard_triggered = [
            r for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_guard_triggered")
        ]
        artifact["oracle_guard_metrics"] = {
            "events_with_oracle_price": len(events_with_oracle),
            "oracle_coverage_rate": round(
                len(events_with_oracle) / len(live_results), 4
            ) if live_results else 0.0,
            "guard_triggered_count": len(guard_triggered),
            "oracle_feeds_available": list(get_chainlink_feeds(args.chain).keys()),
        }

        # ── M7.A.5.7: Local-sim readiness metrics ──────────────────
        events_with_sim = [
            r for r in live_results
            if r.local_sim_state and r.local_sim_state.get("pools_with_state", 0) > 0
        ]
        total_pools_queried = sum(
            r.local_sim_state.get("pools_queried", 0)
            for r in live_results if r.local_sim_state
        )
        total_pools_with_state = sum(
            r.local_sim_state.get("pools_with_state", 0)
            for r in live_results if r.local_sim_state
        )
        artifact["local_sim_readiness"] = {
            "events_with_pool_state": len(events_with_sim),
            "sim_readiness_rate": round(
                len(events_with_sim) / len(live_results), 4
            ) if live_results else 0.0,
            "total_pools_queried": total_pools_queried,
            "total_pools_with_state": total_pools_with_state,
            "note": "State captured for future local-sim pricing path (sqrtPriceX96 + tick + liquidity)",
        }

        # ── M7.A.5.8: Oracle summary extended ──────────────────────
        oracle_price_avail = sum(
            1 for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_price_available")
        )
        oracle_guard_trig = sum(
            1 for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_guard_triggered")
        )
        oracle_staleness_vals = [
            r.oracle_guard.get("oracle_staleness_seconds", 0)
            for r in live_results
            if r.oracle_guard and r.oracle_guard.get("oracle_staleness_seconds") is not None
        ]
        events_blocked_oracle = sum(
            1 for r in live_results
            if r.reject_reason and "ORACLE" in (r.reject_reason or "").upper()
        )
        artifact["oracle_summary_extended"] = {
            "oracle_price_available_rate": round(
                oracle_price_avail / len(live_results), 4
            ) if live_results else 0.0,
            "oracle_guard_triggered_rate": round(
                oracle_guard_trig / len(live_results), 4
            ) if live_results else 0.0,
            "oracle_staleness_max_seconds": (
                max(oracle_staleness_vals) if oracle_staleness_vals else None
            ),
            "events_blocked_by_oracle": events_blocked_oracle,
        }

        # ── M7.A.5.8: Gas decomposition metrics ────────────────────
        events_with_gas = [
            r for r in live_results
            if r.total_gas_bps is not None
        ]
        artifact["gas_decomposition_metrics"] = {
            "events_with_gas_decomp": len(events_with_gas),
            "mean_l2_gas_bps": round(
                sum(r.l2_gas_bps or 0 for r in events_with_gas)
                / len(events_with_gas), 4
            ) if events_with_gas else None,
            "mean_l1_data_bps": round(
                sum(r.l1_data_bps or 0 for r in events_with_gas)
                / len(events_with_gas), 4
            ) if events_with_gas else None,
            "mean_total_gas_bps": round(
                sum(r.total_gas_bps or 0 for r in events_with_gas)
                / len(events_with_gas), 4
            ) if events_with_gas else None,
        }

        # ── M7.A.5.8: Subgraph seed stats ──────────────────────────
        sg_used_count = sum(
            1 for r in live_results
            if r.subgraph_seed_used is True
        )
        artifact["subgraph_seed_stats"] = {
            "tokens_discovered": subgraph_seed_stats.get("tokens_discovered", 0),
            "tokens_new": subgraph_seed_stats.get("tokens_new", 0),
            "tokens_verified": subgraph_seed_stats.get("tokens_verified", 0),
            "sources_queried": subgraph_seed_stats.get("sources_queried", []),
            "errors": subgraph_seed_stats.get("errors", []),
            "addr_to_symbol_size_before": pre_seed_count,
            "addr_to_symbol_size_after": len(addr_to_symbol),
            "subgraph_seeded_events_admitted": sg_used_count,
            "subgraph_seeded_admission_rate": round(
                sg_used_count / len(live_results), 4
            ) if live_results else 0.0,
        }

        # ── M7.A.5.9: Size normalization metrics ───────────────────
        norm_source_hist: Dict[str, int] = {}
        dec_hist: Dict[str, int] = {}
        valid_size_count = 0
        usd_estimates = []
        for r in live_results:
            ns = r.size_normalization_source or "not_set"
            norm_source_hist[ns] = norm_source_hist.get(ns, 0) + 1
            if r.token_in_decimals is not None:
                dk = str(r.token_in_decimals)
                dec_hist[dk] = dec_hist.get(dk, 0) + 1
            if r.size_valid_for_token is True:
                valid_size_count += 1
            if r.size_usd_estimate is not None:
                usd_estimates.append(r.size_usd_estimate)
        artifact["size_normalization_metrics"] = {
            "normalization_source_histogram": norm_source_hist,
            "token_decimals_histogram": dec_hist,
            "events_with_valid_size": valid_size_count,
            "valid_size_rate": round(
                valid_size_count / len(live_results), 4
            ) if live_results else 0.0,
            "events_with_usd_estimate": len(usd_estimates),
            "mean_size_usd": round(
                sum(usd_estimates) / len(usd_estimates), 2
            ) if usd_estimates else None,
        }
        # M7.A.5.46: Legacy hypothesis strings removed from runtime path.
        # Historical context preserved in docs/status/Status_M7.md only.

    # M7.A.5.28: Write canonical rolling M7 artifact (dashboard-facing, no bulky results)
    # M7.A.5.35: Only cold lane writes rolling artifact here.  When hot mode
    # is active (external_registry provided), the outer loop writes a separate
    # hot artifact via _write_hot_artifact() — we must NOT overwrite the cold
    # rolling artifact with hot_skip results.
    if external_registry is None:
        _write_rolling_m7(artifact)

    return artifact


# ---------------------------------------------------------------------------
# M7.A.5.28: Rolling artifact writer
# ---------------------------------------------------------------------------

_ROLLING_M7_PATH = os.path.join("data", "runs", "_rolling", "m7_orderflow_latest.json")


def _set_rolling_m7_profile(profile: str) -> None:
    """M7.E1.9.1: Redirect the cold lane rolling path for discovery profile."""
    global _ROLLING_M7_PATH
    name = "m7_orderflow_latest.json"
    if profile == "discovery":
        name = "m7_orderflow_latest_discovery.json"
    _ROLLING_M7_PATH = os.path.join("data", "runs", "_rolling", name)

# Keys to exclude from the rolling dashboard artifact.
# M7.A.5.46: Legacy hypothesis blocks are no longer created in runtime path.
# Only _raw_results and heavy debug arrays need exclusion.
_ROLLING_EXCLUDE_KEYS = frozenset({
    "results",
    "low_lag_debug_rows",
    "low_lag_watchlist",
    "session_low_lag_pairs",
    "_raw_results",
})


def _write_rolling_m7(artifact: dict) -> None:
    """Overwrite the canonical rolling M7 artifact for dashboard consumption.

    M7.A.5.29: Anti-bad-overwrite — if the window is empty (events_count == 0),
    do NOT overwrite a previous useful snapshot. Instead, only update the
    m7_loop_context metadata in the existing file (if any).

    M7.E1.6.1: On empty-window preserve, stamp current_window_timestamp and
    snapshot_preserved=true so reviewers can distinguish "fresh runtime with
    empty window preserving old snapshot" from "stale artifact not running".
    """
    try:
        events_count = artifact.get("events_count", 0)
        rolling = {k: v for k, v in artifact.items() if k not in _ROLLING_EXCLUDE_KEYS}

        # M7.A.5.29: Anti-bad-overwrite rule
        if events_count == 0 and os.path.exists(_ROLLING_M7_PATH):
            # Preserve previous snapshot, only update loop context if present
            loop_ctx = artifact.get("m7_loop_context")
            if loop_ctx:
                try:
                    with open(_ROLLING_M7_PATH, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                    loop_ctx["window_empty"] = True
                    existing["m7_loop_context"] = loop_ctx
                    existing.setdefault("last_nonempty_timestamp",
                                        existing.get("timestamp"))
                    # M7.E1.6.1: Heartbeat — stamp fresh timestamps even on
                    # empty windows so reviewer sees the runtime is alive.
                    _now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    existing["current_window_timestamp"] = _now
                    existing["snapshot_preserved"] = True
                    # Keep snapshot_run_timestamp as the original scoring timestamp
                    existing.setdefault("snapshot_run_timestamp",
                                        existing.get("run_context", {}).get("run_timestamp"))
                    # E1.9.3: Ensure signal_counts exists even on old snapshots
                    # so dashboard A/B comparison is symmetric.
                    if "signal_counts" not in existing:
                        existing["signal_counts"] = {
                            "scored": 0, "pair_resolved": 0,
                            "size_valid_for_token": 0, "same_block": 0,
                            "positive": 0, "route_viable": 0,
                            "profit_guard_passed": 0, "sim_passed": 0,
                            "submit_ready": 0,
                        }
                    with open(_ROLLING_M7_PATH, "w", encoding="utf-8") as f:
                        json.dump(existing, f, indent=2, default=str)
                    logger.info(
                        "Rolling M7: empty window — preserved previous snapshot, "
                        "updated loop_context + heartbeat at %s", _now,
                    )
                except Exception as exc2:
                    logger.warning(
                        "Rolling M7: empty window — failed to update loop_context: %s",
                        str(exc2)[:120],
                    )
            else:
                logger.info(
                    "Rolling M7: empty window (events=0) — skipping overwrite "
                    "to preserve previous useful snapshot"
                )
            return

        # Non-empty window: track last_nonempty_timestamp
        rolling["last_nonempty_timestamp"] = artifact.get(
            "timestamp", rolling.get("timestamp")
        )
        # M7.E1.6.1: On non-empty write, clear preserved-snapshot flags
        rolling["current_window_timestamp"] = artifact.get(
            "timestamp", rolling.get("timestamp")
        )
        rolling["snapshot_preserved"] = False
        rolling["snapshot_run_timestamp"] = artifact.get(
            "run_context", {}
        ).get("run_timestamp", rolling.get("timestamp"))

        os.makedirs(os.path.dirname(_ROLLING_M7_PATH), exist_ok=True)
        with open(_ROLLING_M7_PATH, "w", encoding="utf-8") as f:
            json.dump(rolling, f, indent=2, default=str)
        logger.info("Rolling M7 artifact written to %s", _ROLLING_M7_PATH)
    except Exception as exc:
        logger.warning("Failed to write rolling M7 artifact: %s", str(exc)[:120])
