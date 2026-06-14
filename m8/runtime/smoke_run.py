"""M8 Phase 1 — Canonical smoke runner for new-pool factory event listener.

This is the canonical implementation module.  ``scripts/sniper_smoke_run.py``
is a thin wrapper that calls ``main()`` from here.

Purpose
-------
HTTP-polling loop that watches factory contracts on Base (or another EVM chain)
for PoolCreated / PairCreated log events, tracks a full event-processing funnel,
and writes a rolling artifact to ``data/runs/_rolling/new_pool_sniper_latest.json``.

Feature flag
-----------
``ARBY_SNIPER_ENABLE=1`` must be set; otherwise the script exits immediately
with a clear message (exit code 0 -- not an error, intentional gate).

RPC URL resolution order (sniper discovery lane)
------------------------------------------------
1. ``--rpc-url`` CLI argument
2. ``BASE_SNIPER_RPC_PRIMARY`` (chain-scoped sniper lane)
3. ``BASE_RPC_SECONDARY`` (often dRPC — preferred for bounded getLogs)
4. Productive ``BASE_RPC_PRIMARY`` via ``resolve_rpc_http()``
5. Failover: ``BASE_SNIPER_RPC_SECONDARY`` → ``BASE_RPC_PRIMARY``

Offline mode (``--offline`` flag or ``ARBY_SNIPER_OFFLINE=1``)
--------------------------------------------------------------
Skips all RPC calls. Simulates one empty cycle so the funnel counters
and artifact writing path are exercised without a network connection.
Useful for offline CI and unit tests.

Commands (via scripts/ wrapper)
--------------------------------
  # Enable and run for 10 minutes on Base:
  ARBY_SNIPER_ENABLE=1 BASE_RPC=https://... py -3.11 scripts/sniper_smoke_run.py

  # Offline smoke (no RPC needed):
  ARBY_SNIPER_ENABLE=1 py -3.11 scripts/sniper_smoke_run.py --offline --duration-minutes 0

Self-test
---------
If ``verification_from_block`` and ``verification_to_block`` are set in
``config/new_pool_factories.yaml`` for a factory, the runner performs a
self-test at startup: replays that block range via ``eth_getLogs`` and
checks that >=1 event is parsed. Hard-fails (exit 3) if the self-test
fails for any factory that has verification blocks configured.
"""
from __future__ import annotations

import argparse
import json
import functools
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Ensure repo root is on sys.path when this module is used directly.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.env import env_flag_enabled, load_root_dotenv
from core.logging import get_logger, setup_logging
from core.rpc_urls import (
    classify_provider,
    public_fallback_for,
    resolve_rpc_http,
    resolve_rpc_ws,
    resolve_sniper_rpc_lane,
)
from discovery.new_pool_listener import (
    FactoryConfig,
    NewPoolEvent,
    dedup_events,
    load_factory_config,
    make_event_id,
    parse_raw_log,
)
from monitoring.sniper_artifacts import (
    make_sniper_artifact,
    validate_sniper_artifact,
    write_sniper_artifact,
)
from monitoring.sniper_funnel import EventTrace, FunnelTracker

# Phase 2 paper-only — entry decision engine (optional; gracefully absent on import error)
try:
    from strategy.sniper_entry_decision import (
        EntryCandidate,
        make_default_engine,
    )
    _PHASE2_ENTRY_ENGINE_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _PHASE2_ENTRY_ENGINE_AVAILABLE = False

# Phase 2 — candidate enricher (on-chain liquidity / spread / mirror / honeypot)
try:
    from strategy.entry_candidate_enricher import EntryCandidateEnricher
    _PHASE2_ENRICHER_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _PHASE2_ENRICHER_AVAILABLE = False

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ARTIFACT_WRITE_INTERVAL_S: float = 60.0  # aligned with M8 dashboard REFRESH_MS
_MAX_BLOCKS_PER_CALL: int = 500    # bounded getLogs chunk (v4 factories 408 on 2k+)
_MIN_GETLOGS_CHUNK_BLOCKS: int = 10
_GETLOGS_TRANSIENT_RETRIES: int = 2
_GETLOGS_RETRY_DELAY_S: float = 2.0
_FAILOVER_GETLOGS_ERRORS = frozenset({
    "400_range", "408", "429", "5xx", "timeout",
})
_MAX_RECENT_EVENTS_IN_ARTIFACT: int = 500  # increased from 20: 24h lookback finds ~500 pools; bridge builder needs full set
_DEFAULT_CHAIN: str = "base"
_DEFAULT_BLOCKS_BACK: int = 50
_DEFAULT_POLL_INTERVAL_S: float = 30.0
_DEFAULT_DURATION_MIN: float = 10.0

# Minimal ERC20 ABI -- only the symbol() function
_ERC20_SYMBOL_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [{"internalType": "string", "name": "", "type": "string"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# LRU cache so each token address is resolved at most once per run
@functools.lru_cache(maxsize=512)
def _fetch_symbol_cached(token_addr: str, w3_id: int) -> Optional[str]:
    """Fetch ERC20 symbol for *token_addr* using a cached web3 instance.

    Uses ``w3_id = id(w3)`` as a cache-buster so the LRU is effectively
    per-w3 instance.  Always returns ``None`` on any failure so the pipeline
    is never blocked by a symbol lookup.
    """
    return None   # resolved at runtime via _fetch_erc20_symbol


def _fetch_erc20_symbol(token_addr: str, w3: Any) -> Optional[str]:
    """Return the ERC20 symbol string for *token_addr*, or None on any error.

    Times out gracefully: if the call raises any exception (timeout,
    revert, ABI mismatch) we return None.  Results are NOT cached here
    to keep the function pure -- caching is done by the caller.
    """
    try:
        contract = w3.eth.contract(
            address=w3.to_checksum_address(token_addr),
            abi=_ERC20_SYMBOL_ABI,
        )
        raw = contract.functions.symbol().call()
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:32]   # cap to 32 chars to avoid bloat
        return None
    except Exception:
        return None


# Per-run in-process cache (not LRU -- just a dict -- sufficient for 1 run)
_symbol_cache: Dict[str, Optional[str]] = {}
_ZERO_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"


def _native_symbol_for_addr(token_addr: str) -> Optional[str]:
    """V4 native-ETH pairs use the zero address for token0 on Base."""
    if (token_addr or "").lower() == _ZERO_TOKEN_ADDRESS:
        return "WETH"
    return None


def _get_symbol(token_addr: str, w3: Any) -> Optional[str]:
    """Symbol with per-run dict cache; never raises."""
    native = _native_symbol_for_addr(token_addr)
    if native:
        return native
    if token_addr in _symbol_cache:
        return _symbol_cache[token_addr]
    sym = _fetch_erc20_symbol(token_addr, w3)
    _symbol_cache[token_addr] = sym
    return sym


# ---------------------------------------------------------------------------
# Shared per-log pipeline: parse → dedup → funnel → recent_events
# ---------------------------------------------------------------------------

def _process_log_event(
    raw_log: Any,
    cfg: FactoryConfig,
    funnel: "FunnelTracker",
    seen_ids: Set[str],
    recent_events: List[NewPoolEvent],
    events_lock: Optional[threading.Lock] = None,
) -> Optional[NewPoolEvent]:
    """Parse one raw log through the full funnel pipeline.

    Thread-safe when *events_lock* is provided. Used by both HTTP polling
    and the WS ``on_event`` callback (``--prefer-ws`` mode).

    Returns the event if it became a candidate, ``None`` otherwise.
    """
    event = parse_raw_log(raw_log, cfg)
    if event is None:
        funnel.inc("parse_failed")
        return None
    funnel.inc("parse_ok")
    funnel.inc_dex(cfg.dex, "parse_ok")
    funnel.record_factory_poll(cfg.dex, ok=True)

    if events_lock is not None:
        events_lock.acquire()
    try:
        if event.event_id in seen_ids:
            funnel.inc("dedup_dropped")
            return None
        seen_ids.add(event.event_id)
        funnel.inc("dedup_new")
        funnel.inc("filter_passed")
        funnel.inc("candidates_queued")
        funnel.inc_dex(cfg.dex, "candidate")
        recent_events.append(event)
        if len(recent_events) > _MAX_RECENT_EVENTS_IN_ARTIFACT * 5:
            recent_events[:] = recent_events[-_MAX_RECENT_EVENTS_IN_ARTIFACT * 5:]
    finally:
        if events_lock is not None:
            events_lock.release()

    trace = EventTrace(
        event_id=event.event_id,
        chain=event.chain,
        dex=event.dex,
        factory=event.factory,
        pool=event.pool,
        token0=event.token0,
        token1=event.token1,
        block_number=event.block_number,
        received_ts=time.time(),
        filter_passed=True,
        candidate=True,
    )
    funnel.record_trace(trace)
    logger.info(
        "new_pool_event",
        extra={
            "context": {
                "event_id": event.event_id,
                "chain": event.chain,
                "dex": event.dex,
                "pool": event.pool,
                "token0": event.token0,
                "token1": event.token1,
                "block_number": event.block_number,
                "tx_hash": event.tx_hash,
            }
        },
    )
    return event


def _apply_phase2_decision(
    event: NewPoolEvent,
    engine: Any,
    decisions: Dict[str, Any],
    enricher: Any = None,
    funnel: Any = None,
    arb_trace: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Run the Phase 2 paper-only entry engine for *event* and store the result.

    When *enricher* is provided (online mode), the candidate is built with
    real on-chain data (liquidity, spread, mirror, honeypot).  Without an
    enricher the candidate is bare (identity fields only) and the engine
    will return SKIP / INSUFFICIENT_DATA, which is the correct conservative
    fallback for offline / no-RPC mode.

    Results are stored in *decisions* keyed by ``event.event_id``.  When
    *funnel* is provided, phase2 counters are updated.

    NOTE: Caller is responsible for holding ``phase2_lock`` (if any) around
    this call to protect both the enricher's ``seen_pairs`` registry and the
    shared *decisions* dict from concurrent WS + HTTP threads.
    """
    try:
        extra_fields: Dict[str, Any] = {}
        if enricher is not None:
            enrich_result = enricher.enrich(event)
            cand = enrich_result.candidate
            extra_fields = enrich_result.to_dict()
        else:
            cand = EntryCandidate(
                token0=(event.token0 or "").lower(),
                token1=(event.token1 or "").lower(),
                pool=(event.pool or "").lower(),
                dex=event.dex,
                block_number=event.block_number,
            )
        decision = engine.decide(cand)
        decisions[event.event_id] = {**decision.to_dict(), **extra_fields}
        if funnel is not None:
            reject_reason = decision.reject_reason
            liq_note = extra_fields.get("liquidity_note") or ""
            # V4 family: bucket reject reasons with finer granularity to expose
            # whether the StateView lens is actually being called:
            #   V4_SKIP             → StateView disabled / not configured (legacy)
            #   V4_ZERO_AT_CREATION → StateView called, pool has zero reserves (expected)
            #   V4_BAD_POOLID       → PoolId format unexpected
            #   V4_ZERO_PRICE       → sqrtPriceX96 == 0 after liquidity is non-zero
            #   V4_RPC_ERR:*        → StateView RPC error
            # V4_SKIP folds into the generic V4_LIQUIDITY_UNSUPPORTED bucket;
            # the StateView-specific notes get their own buckets for observability.
            if liq_note == "V4_SKIP":
                reject_reason = "V4_LIQUIDITY_UNSUPPORTED"
            elif liq_note in ("V4_ZERO_AT_CREATION", "V4_BAD_POOLID", "V4_ZERO_PRICE"):
                reject_reason = liq_note
            elif liq_note.startswith("V4_RPC_ERR"):
                reject_reason = "V4_RPC_ERR"
            # ------------------------------------------------------------------
            # DISCOVERY vs ARB split (Step 6 / 10-step fix plan).
            # reference_source captures whether a price reference was found:
            #   NONE             → discovery only (no arb economics available)
            #   MIRROR_POOL      → same pair on another DEX
            #   ANCHOR_RATIO     → both tokens are known anchors
            #   TRIANGULAR_ROUTE → non-anchor token seen in another seen pair
            # Events with reference_source=NONE are DISCOVERY candidates; their
            # reject_reason is overridden to NO_ARBITRAGE_REFERENCE so the
            # histogram clearly separates infra noise from economics failures.
            # ------------------------------------------------------------------
            ref_src = extra_fields.get("reference_source", "NONE")
            if ref_src != "NONE":
                funnel.inc_arb_candidate()
            else:
                funnel.inc_discovery_candidate()
                # Override reject_reason so histogram separates "no price reference"
                # from other reject types (INSUFFICIENT_DATA, V4_ZERO_AT_CREATION…).
                if reject_reason is None:
                    reject_reason = "NO_ARBITRAGE_REFERENCE"
                elif reject_reason not in (
                    "V4_LIQUIDITY_UNSUPPORTED", "V4_ZERO_AT_CREATION",
                    "V4_BAD_POOLID", "V4_ZERO_PRICE", "V4_RPC_ERR",
                    "INSUFFICIENT_DATA",
                ):
                    reject_reason = "NO_ARBITRAGE_REFERENCE"
            if reject_reason is not None:
                funnel.inc_phase2_reject(reject_reason)
            else:
                funnel.inc_phase2_would_enter()
            if extra_fields.get("expected_pnl_usd") is not None:
                funnel.inc_phase2_expected_pnl_non_null()
            # Append to run-wide arb trace so gate sees candidates beyond
            # the recent_events window (last 20 events in artifact).
            if arb_trace is not None and ref_src != "NONE":
                _slip = extra_fields.get("slippage_result") or {}
                arb_trace.append({
                    "event_id": event.event_id,
                    "pair": None,  # symbol resolution happens in artifact builder
                    "dex": event.dex,
                    "block_number": event.block_number,
                    "token0": event.token0,
                    "token1": event.token1,
                    "liquidity_usd": extra_fields.get("liquidity_usd"),
                    "reference_source": ref_src,
                    "spread_bps": extra_fields.get("estimated_spread_bps"),
                    "spread_note": extra_fields.get("spread_note"),
                    "gas_usd": 0.30,
                    "slippage_bps": _slip.get("predicted_bps"),
                    "expected_pnl_usd": extra_fields.get("expected_pnl_usd"),
                    "honeypot_verdict": extra_fields.get("honeypot_verdict"),
                    "route_edges": extra_fields.get("route_edges"),
                    "reject_reason": decision.reject_reason,
                    "verdict": extra_fields.get("verdict"),
                })
    except Exception as exc:
        logger.warning(
            "phase2_entry_decision_error",
            extra={"context": {"event_id": event.event_id, "error": str(exc)[:80]}},
        )


def _make_ws_on_event_callback(
    funnel: "FunnelTracker",
    seen_ids: Set[str],
    recent_events: List[NewPoolEvent],
    events_lock: threading.Lock,
    phase2_engine: Any = None,
    phase2_event_decisions: Optional[Dict[str, Any]] = None,
    phase2_enricher: Any = None,
    phase2_lock: Optional[threading.Lock] = None,
    arb_trace: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    """Return an ``on_event(cfg, raw_log)`` callback for WSPoolEventListener.

    The callback is thread-safe: it acquires *events_lock* around dedup +
    recent_events mutations.  It acquires *phase2_lock* (when provided) around
    the enricher ``seen_pairs`` update and *decisions* dict write to prevent
    data races with the concurrent HTTP polling thread.
    """
    def on_event(cfg: FactoryConfig, raw_log: Any) -> None:
        funnel.inc("raw_fetched")
        funnel.inc_dex(cfg.dex, "raw_logs")
        candidate = _process_log_event(raw_log, cfg, funnel, seen_ids, recent_events, events_lock)
        if (candidate is not None
                and phase2_engine is not None
                and phase2_event_decisions is not None):
            if phase2_lock is not None:
                phase2_lock.acquire()
            try:
                _apply_phase2_decision(
                    candidate, phase2_engine, phase2_event_decisions,
                    enricher=phase2_enricher, funnel=funnel,
                    arb_trace=arb_trace,
                )
            finally:
                if phase2_lock is not None:
                    phase2_lock.release()
    return on_event


# ---------------------------------------------------------------------------
# Raw log -> plain dict normalisation
# ---------------------------------------------------------------------------

def _log_to_dict(raw: Any) -> Dict[str, Any]:
    """Convert a web3 AttributeDict (or any Mapping) to a plain dict.

    ``eth.get_logs`` returns ``AttributeDict`` objects; ``parse_raw_log``
    expects plain dicts or Mapping-compatible objects.  AttributeDict is a
    Mapping, so parsing works without normalisation -- but we normalise for
    clean serialisation in debug logs.
    """
    try:
        d: Dict[str, Any] = {}
        for k in raw:
            v = raw[k]
            try:
                d[str(k)] = hex(v) if isinstance(v, int) and str(k) in ("blockNumber",) else v
            except Exception:
                d[str(k)] = str(v)
        return d
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# RPC helpers
# ---------------------------------------------------------------------------

def _chain_id_for(chain: str) -> Optional[int]:
    return {"base": 8453, "arbitrum": 42161, "optimism": 10, "ethereum": 1}.get(
        chain.lower()
    )


def _build_sniper_rpc_lane(
    chain: str,
    override: Optional[str],
    funnel: FunnelTracker,
) -> "SniperRpcLane":
    """Resolve sniper discovery lane and build a getLogs client with failover."""
    chain_key = chain.lower()
    chain_id = _chain_id_for(chain_key)
    primary_url, primary_prov, secondary_url, secondary_prov, diag = resolve_sniper_rpc_lane(
        chain_id=chain_id,
        network=chain_key,
        env=dict(os.environ),
        override=override,
    )
    logger.info(
        "rpc_resolved_sniper_http",
        extra={"context": {
            "chain": chain_key,
            "primary_provider": primary_prov,
            "secondary_provider": secondary_prov or "none",
            "primary_source": diag.get("primary_source"),
            "secondary_source": diag.get("secondary_source"),
        }},
    )
    funnel.set_sniper_rpc_lane(
        primary_provider=primary_prov,
        secondary_provider=secondary_prov or "none",
    )

    from web3 import Web3

    w3_primary = Web3(Web3.HTTPProvider(primary_url))
    w3_secondary = (
        Web3(Web3.HTTPProvider(secondary_url)) if secondary_url else None
    )
    return SniperRpcLane(
        w3_primary=w3_primary,
        w3_secondary=w3_secondary,
        primary_provider=primary_prov,
        secondary_provider=secondary_prov,
        funnel=funnel,
    )


def _resolve_rpc_url(chain: str, override: Optional[str]) -> str:
    """Return sniper-lane primary HTTP URL (backward-compatible helper)."""
    chain_key = chain.lower()
    chain_id = _chain_id_for(chain_key)
    primary_url, _prov, _sec, _sec_prov, _diag = resolve_sniper_rpc_lane(
        chain_id=chain_id,
        network=chain_key,
        env=dict(os.environ),
        override=override,
    )
    return primary_url


def _resolve_ws_url(chain: str, override: Optional[str]) -> Optional[str]:
    """Return a WebSocket RPC URL (or None if not configured).

    Resolution uses ``core.rpc_urls.resolve_rpc_ws`` (centralized M5/M7
    resolver). Returns ``None`` if no WS endpoint is available.
    """
    if override:
        return override
    chain_key = chain.lower()
    chain_id_map = {"base": 8453, "arbitrum": 42161, "optimism": 10, "ethereum": 1}
    chain_id = chain_id_map.get(chain_key)
    try:
        url, provider, diag = resolve_rpc_ws(
            chain_id=chain_id, network=chain_key, env=dict(os.environ)
        )
        if url:
            logger.info(
                "rpc_resolved_ws",
                extra={"context": {
                    "chain": chain_key,
                    "provider": provider,
                    "source": diag.get("source"),
                }},
            )
            return url
    except Exception as exc:
        logger.warning(
            "resolve_rpc_ws_failed",
            extra={"context": {"chain": chain_key, "error": str(exc)[:120]}},
        )
    return None


def _get_block_number(w3: Any) -> Optional[int]:
    try:
        return int(w3.eth.block_number)
    except Exception as exc:
        logger.warning(
            "eth_blockNumber failed",
            extra={"context": {"error": str(exc)[:120]}},
        )
        return None


def _parse_block_num(val: Any) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        return int(val, 16) if val.lower().startswith("0x") else int(val)
    return int(val)


def _getlogs_block_span(params: Dict[str, Any]) -> int:
    from_b = _parse_block_num(params.get("fromBlock", 0))
    to_b = _parse_block_num(params.get("toBlock", from_b))
    return max(1, to_b - from_b + 1)


def _classify_getlogs_error(err_str: str) -> str:
    s = err_str.lower()
    if "400" in s or any(
        p in s for p in ("block range", "range exceeded", "range limit", "-32600")
    ):
        return "400_range"
    if "429" in s or "too many requests" in s or "rate limit" in s:
        return "429"
    if "408" in s:
        return "408"
    if any(code in s for code in ("500", "502", "503", "504", "server error")):
        return "5xx"
    if "timeout" in s or "timed out" in s:
        return "timeout"
    return "other"


def _single_get_logs(
    w3: Any,
    params: Dict[str, Any],
    *,
    retries: int = 1,
    retry_delay_s: float = _GETLOGS_RETRY_DELAY_S,
) -> tuple[List[Any], Optional[str]]:
    """Single-provider eth_getLogs; returns (logs, error_str_or_none)."""
    last_err: Optional[str] = None
    for attempt in range(1, retries + 1):
        try:
            return list(w3.eth.get_logs(params)), None
        except Exception as exc:
            err_str = str(exc)
            err_type = _classify_getlogs_error(err_str)
            if (
                err_type in ("408", "429", "5xx", "timeout")
                and attempt < retries
            ):
                logger.warning(
                    "eth_getLogs_transient_retry",
                    extra={"context": {
                        "attempt": attempt,
                        "retries": retries,
                        "error_type": err_type,
                        "error": err_str[:120],
                    }},
                )
                time.sleep(retry_delay_s)
                last_err = err_str
                continue
            return [], err_str
    return [], last_err or "eth_getLogs failed"


@dataclass
class SniperRpcLane:
    """M8 sniper discovery HTTP lane with getLogs chunk-split + failover."""

    w3_primary: Any
    w3_secondary: Optional[Any]
    primary_provider: str
    secondary_provider: Optional[str]
    funnel: FunnelTracker

    @property
    def w3(self) -> Any:
        """Primary web3 handle (block number, checksum, enricher)."""
        return self.w3_primary

    def get_logs(self, params: Dict[str, Any]) -> tuple[List[Any], bool, str]:
        logs, had_err, err = self._get_logs_lane(params, use_secondary=False)
        if had_err:
            logger.warning(
                "eth_getLogs failed",
                extra={"context": {
                    "params": str(params)[:200],
                    "error": err[:120],
                }},
            )
        return logs, had_err, err

    def _get_logs_lane(
        self,
        params: Dict[str, Any],
        *,
        use_secondary: bool,
    ) -> tuple[List[Any], bool, str]:
        w3 = self.w3_secondary if use_secondary else self.w3_primary
        provider = (
            self.secondary_provider if use_secondary else self.primary_provider
        )
        if w3 is None:
            return [], True, "no secondary sniper RPC configured"

        logs, err = _single_get_logs(
            w3,
            params,
            retries=_GETLOGS_TRANSIENT_RETRIES,
        )
        if err is None:
            self.funnel.set_getlogs_chunk_size(_getlogs_block_span(params))
            return logs, False, ""

        err_type = _classify_getlogs_error(err)
        if err_type == "400_range":
            self.funnel.inc_getlogs_400()
        elif err_type == "429":
            self.funnel.inc_getlogs_429()

        if err_type not in _FAILOVER_GETLOGS_ERRORS:
            return [], True, err

        if not use_secondary and err_type == "400_range":
            split_logs, split_err, split_str = self._split_range_get_logs(params)
            if not split_err:
                return split_logs, False, ""

        if not use_secondary and self.w3_secondary is not None:
            self.funnel.inc_sniper_rpc_failover()
            logger.info(
                "sniper_rpc_failover",
                extra={"context": {
                    "from_provider": self.primary_provider,
                    "to_provider": self.secondary_provider,
                    "error_type": err_type,
                    "provider": provider,
                }},
            )
            return self._get_logs_lane(params, use_secondary=True)

        if use_secondary and err_type == "400_range":
            split_logs, split_err, split_str = self._split_range_get_logs(
                params, use_secondary=True
            )
            if not split_err:
                return split_logs, False, ""
            return [], True, split_str

        return [], True, err

    def _split_range_get_logs(
        self,
        params: Dict[str, Any],
        *,
        use_secondary: bool = False,
    ) -> tuple[List[Any], bool, str]:
        from_b = _parse_block_num(params.get("fromBlock", 0))
        to_b = _parse_block_num(params.get("toBlock", from_b))
        span = to_b - from_b + 1
        if span <= _MIN_GETLOGS_CHUNK_BLOCKS:
            return [], True, "block range split exhausted"

        mid = from_b + span // 2 - 1
        left = dict(params)
        left["fromBlock"] = from_b
        left["toBlock"] = mid
        right = dict(params)
        right["fromBlock"] = mid + 1
        right["toBlock"] = to_b

        left_logs, left_err, left_str = self._get_logs_lane(
            left, use_secondary=use_secondary
        )
        if left_err:
            return [], True, left_str
        right_logs, right_err, right_str = self._get_logs_lane(
            right, use_secondary=use_secondary
        )
        if right_err:
            return [], True, right_str
        return left_logs + right_logs, False, ""


def _get_logs_safe(
    rpc_lane: SniperRpcLane,
    params: Dict[str, Any],
) -> tuple[List[Any], bool, str]:
    """Call sniper-lane ``eth_getLogs`` with chunk-split and provider failover."""
    return rpc_lane.get_logs(params)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _run_self_test(
    rpc_lane: SniperRpcLane,
    configs: List[FactoryConfig],
    chain: str,
) -> tuple[bool, Dict[str, Any]]:
    """Replay verification block ranges for each factory that has them set.

    Returns (all_pass, results_by_dex) where results_by_dex maps dex name to
    a dict with keys: raw, parse_ok, parse_failed, range, status.

    Returns (True, {}) when no factories have verification blocks (nothing to test).
    """
    testable = [
        cfg for cfg in configs
        if cfg.verification_from_block is not None and cfg.verification_to_block is not None
    ]
    if not testable:
        logger.info(
            "self_test skipped -- no verification blocks configured",
            extra={"context": {"chain": chain, "factories_total": len(configs)}},
        )
        return True, {}

    all_pass = True
    results_by_dex: Dict[str, Any] = {}
    w3 = rpc_lane.w3
    for cfg in testable:
        assert cfg.verification_from_block is not None
        assert cfg.verification_to_block is not None
        params: Dict[str, Any] = {
            "fromBlock": cfg.verification_from_block,
            "toBlock": cfg.verification_to_block,
            "address": w3.to_checksum_address(cfg.factory),
        }
        if cfg.topic0:
            params["topics"] = [cfg.topic0]

        logs, had_err, _ = _get_logs_safe(rpc_lane, params)
        if had_err:
            logger.error(
                "self_test rpc_error",
                extra={"context": {"dex": cfg.dex, "factory": cfg.factory}},
            )
            all_pass = False
            results_by_dex[cfg.dex] = {
                "raw": 0,
                "parse_ok": 0,
                "parse_failed": 0,
                "range": [cfg.verification_from_block, cfg.verification_to_block],
                "status": "RPC_ERROR",
            }
            continue

        parsed = [parse_raw_log(lg, cfg) for lg in logs]
        ok_count = sum(1 for e in parsed if e is not None)
        fail_count = len(logs) - ok_count
        if ok_count == 0:
            if cfg.discovery_only and len(logs) == 0:
                logger.info(
                    "self_test PASS (market window — discovery_only, zero logs in range)",
                    extra={
                        "context": {
                            "dex": cfg.dex,
                            "factory": cfg.factory,
                            "from_block": cfg.verification_from_block,
                            "to_block": cfg.verification_to_block,
                        }
                    },
                )
                results_by_dex[cfg.dex] = {
                    "raw": 0,
                    "parse_ok": 0,
                    "parse_failed": 0,
                    "range": [cfg.verification_from_block, cfg.verification_to_block],
                    "status": "PASS",
                    "note": "MARKET_WINDOW_NO_POOL_CREATED",
                }
                continue
            logger.error(
                "self_test FAIL -- no events parsed in verification range",
                extra={
                    "context": {
                        "dex": cfg.dex,
                        "factory": cfg.factory,
                        "from_block": cfg.verification_from_block,
                        "to_block": cfg.verification_to_block,
                        "raw_logs": len(logs),
                    }
                },
            )
            all_pass = False
            results_by_dex[cfg.dex] = {
                "raw": len(logs),
                "parse_ok": 0,
                "parse_failed": fail_count,
                "range": [cfg.verification_from_block, cfg.verification_to_block],
                "status": "FAIL",
            }
        else:
            logger.info(
                "self_test PASS",
                extra={
                    "context": {
                        "dex": cfg.dex,
                        "factory": cfg.factory,
                        "events_parsed": ok_count,
                        "from_block": cfg.verification_from_block,
                        "to_block": cfg.verification_to_block,
                    }
                },
            )
            results_by_dex[cfg.dex] = {
                "raw": len(logs),
                "parse_ok": ok_count,
                "parse_failed": fail_count,
                "range": [cfg.verification_from_block, cfg.verification_to_block],
                "status": "PASS",
            }
    return all_pass, results_by_dex


# ---------------------------------------------------------------------------
# Per-factory getLogs params builder
# ---------------------------------------------------------------------------

def _build_filter_params(
    w3: Any,
    cfg: FactoryConfig,
    from_block: int,
    to_block: int,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": w3.to_checksum_address(cfg.factory),
    }
    if cfg.topic0:
        params["topics"] = [cfg.topic0]
    return params


# ---------------------------------------------------------------------------
# Build rolling artifact from funnel + recent events
# ---------------------------------------------------------------------------

_ROLLING_SNIPER_ARTIFACT = Path("data/runs/_rolling/new_pool_sniper_latest.json")


def _load_preserved_recent_events_dicts(
    status: str,
    recent_events: List[NewPoolEvent],
) -> Optional[List[Dict[str, Any]]]:
    """Keep prior recent_events when a failed run would otherwise wipe the rolling window."""
    if status != "RPC_ERROR" or recent_events:
        return None
    if not _ROLLING_SNIPER_ARTIFACT.exists():
        return None
    try:
        prev = json.loads(_ROLLING_SNIPER_ARTIFACT.read_text(encoding="utf-8"))
    except Exception:
        return None
    if prev.get("status") == "RPC_ERROR":
        return None
    preserved = list(prev.get("recent_events") or [])
    if not preserved:
        return None
    return preserved[-_MAX_RECENT_EVENTS_IN_ARTIFACT:]


def _build_and_write_artifact(
    funnel: FunnelTracker,
    recent_events: List[NewPoolEvent],
    started_at: str,
    elapsed_s: float,
    source: str,
    status: str,
    reasons: List[str],
    w3: Optional[Any] = None,
    phase2_event_decisions: Optional[Dict[str, Any]] = None,
    enricher_config: Optional[Dict[str, Any]] = None,
    arb_trace: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build, validate, and atomically write the rolling artifact."""
    metrics = funnel.snapshot()
    recent_window = recent_events[-_MAX_RECENT_EVENTS_IN_ARTIFACT:]
    preserved_recent = _load_preserved_recent_events_dicts(status, recent_events)
    if preserved_recent:
        metrics["recent_events_preserved_from_prior"] = len(preserved_recent)
        metrics["preserve_reason"] = "RPC_ERROR_EMPTY_WINDOW"

    # ------------------------------------------------------------------
    # Step 7: Batch ERC20 symbol() via core.multicall.
    # Per-token individual calls replaced with one multicall round-trip
    # for tokens in the current artifact window. Falls back to the
    # legacy per-token call on any multicall error.
    # ------------------------------------------------------------------
    symbol_map: Dict[str, Optional[str]] = {}
    decimals_map: Dict[str, Optional[int]] = {}
    if w3 is not None and (recent_window or recent_events):
        unique_tokens: List[str] = []
        seen: Set[str] = set()
        # Extend batch to ALL recent_events so per-dex window gets symbols too
        for e in recent_events:
            for tok in (e.token0, e.token1):
                if tok and tok not in seen:
                    seen.add(tok)
                    unique_tokens.append(tok)
        try:
            from core.multicall import get_multicall_batcher
            rpc_url_for_mc: Optional[str] = None
            try:
                rpc_url_for_mc = getattr(w3.provider, "endpoint_uri", None)
            except Exception:
                rpc_url_for_mc = None
            if rpc_url_for_mc:
                block_num = _get_block_number(w3) or 0
                batcher = get_multicall_batcher(rpc_url_for_mc, block_num)
                symbol_map = batcher.batch_symbol(unique_tokens) or {}
                decimals_map = batcher.batch_decimals(unique_tokens) or {}
        except Exception as exc:
            logger.warning(
                "multicall_symbol_batch_failed_falling_back",
                extra={"context": {"error": str(exc)[:120]}},
            )
            symbol_map = {}
            decimals_map = {}

    recent_list: List[Dict[str, Any]] = []
    if preserved_recent:
        recent_list = list(preserved_recent)
    for e in recent_window:
        # Prefer batched result; fall back to legacy cached single-call.
        token0_sym: Optional[str] = symbol_map.get(e.token0) if symbol_map else None
        token1_sym: Optional[str] = symbol_map.get(e.token1) if symbol_map else None
        if w3 is not None and token0_sym is None:
            token0_sym = _get_symbol(e.token0, w3)
        if w3 is not None and token1_sym is None:
            token1_sym = _get_symbol(e.token1, w3)
        pair = (
            f"{token0_sym}/{token1_sym}"
            if token0_sym and token1_sym
            else None
        )
        recent_list.append({
            "event_id": e.event_id,
            "chain": e.chain,
            "dex": e.dex,
            "factory": e.factory,
            "pool": e.pool,
            "token0": e.token0,
            "token1": e.token1,
            "token0_symbol": token0_sym,
            "token1_symbol": token1_sym,
            "token0_decimals": decimals_map.get(e.token0) if decimals_map else None,
            "token1_decimals": decimals_map.get(e.token1) if decimals_map else None,
            "token0_decimals_source": (
                "erc20_call" if decimals_map.get(e.token0) is not None else None
            ),
            "token1_decimals_source": (
                "erc20_call" if decimals_map.get(e.token1) is not None else None
            ),
            "pair": pair,
            "fee": e.fee,
            "tick_spacing": e.tick_spacing,
            "stable": e.stable,
            "hooks": e.hooks,
            "block_number": e.block_number,
            "source_event_block": e.block_number,
            "pool_first_seen_block": e.block_number,
            "tx_hash": e.tx_hash,
            # Phase 2: per-event entry decision (None when engine not wired / not called)
            "phase2_decision": (
                phase2_event_decisions.get(e.event_id)
                if phase2_event_decisions else None
            ),
        })

    # Phase 2 top-level summary: prefer the most informative event, not just the
    # chronologically last one. Priority:
    #   1. Any WOULD_ENTER decision (always interesting).
    #   2. Any SKIP with a populated liquidity_usd (real on-chain data).
    #   3. The last decision overall (legacy behaviour).
    # This keeps the dashboard / gate from being dominated by V4_LIQUIDITY_UNSUPPORTED
    # noise when ~90% of Base events are V4 with zero reserves at creation.
    def _summarise(dec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "honeypot_result": dec.get("honeypot_verdict"),
            "simulation_result": None,
            "realisability_reason": dec.get("spread_note") or dec.get("liquidity_note"),
            "dry_run_decision": dec.get("verdict"),
            "reject_reason": dec.get("reject_reason"),
            "expected_pnl_usd": dec.get("expected_pnl_usd"),
        }

    phase2_summary: Optional[Dict[str, Any]] = None
    if phase2_event_decisions:
        window_decs: List[Dict[str, Any]] = []
        for e in recent_window:
            d = phase2_event_decisions.get(e.event_id)
            if d is not None:
                window_decs.append(d)
        # 1. Prefer WOULD_ENTER if any.
        for d in reversed(window_decs):
            if d.get("verdict") == "WOULD_ENTER":
                phase2_summary = _summarise(d)
                break
        # 2. Prefer a SKIP that still had real liquidity data.
        if phase2_summary is None:
            for d in reversed(window_decs):
                if d.get("liquidity_usd") is not None:
                    phase2_summary = _summarise(d)
                    break
        # 3. Fallback: last in window.
        if phase2_summary is None and window_decs:
            phase2_summary = _summarise(window_decs[-1])
        # 4. Decisions exist but none in recent window: use latest overall.
        if phase2_summary is None:
            last_eid = next(reversed(list(phase2_event_decisions.keys())), None)
            if last_eid:
                phase2_summary = _summarise(phase2_event_decisions[last_eid])

    # Build per-dex recent events (last _MAX_PER_DEX_EVENTS per dex) from the
    # full recent_events buffer.  This prevents V4-dominance from pushing V2/V3
    # events out of the artifact window (fixes bridge M8→M9 graph_ready_from_m8=0).
    _MAX_PER_DEX_EVENTS: int = 100  # increased from 5: ensure minority DEX events (V2/V3/ve33) survive
    _per_dex_build: Dict[str, List[Dict[str, Any]]] = {}
    for e in recent_events:
        tok0_sym: Optional[str] = symbol_map.get(e.token0) if symbol_map else None
        tok1_sym: Optional[str] = symbol_map.get(e.token1) if symbol_map else None
        if tok0_sym is None:
            tok0_sym = _native_symbol_for_addr(e.token0)
        if tok1_sym is None:
            tok1_sym = _native_symbol_for_addr(e.token1)
        if w3 is not None and tok0_sym is None:
            tok0_sym = _get_symbol(e.token0, w3)
        if w3 is not None and tok1_sym is None:
            tok1_sym = _get_symbol(e.token1, w3)
        # Only include events that have symbols (needed by bridge token_verified stage)
        if tok0_sym and tok1_sym:
            dex_key = e.dex or "unknown"
            _per_dex_build.setdefault(dex_key, []).append({
                "event_id": e.event_id,
                "chain": e.chain,
                "dex": e.dex,
                "factory": e.factory,
                "pool": e.pool,
                "token0": e.token0,
                "token1": e.token1,
                "token0_symbol": tok0_sym,
                "token1_symbol": tok1_sym,
                "pair": f"{tok0_sym}/{tok1_sym}",
                "fee": e.fee,
                "tick_spacing": e.tick_spacing,
                "stable": e.stable,
                "hooks": e.hooks,
                "block_number": e.block_number,
                "source_event_block": e.block_number,
                "pool_first_seen_block": e.block_number,
                "tx_hash": e.tx_hash,
            })
    recent_events_by_dex: Dict[str, List[Dict[str, Any]]] = {
        dex: evs[-_MAX_PER_DEX_EVENTS:]
        for dex, evs in _per_dex_build.items()
    }

    pending_stats = _sync_pending_registry_from_events(recent_events_by_dex, recent_list)
    funnel.set_pending_registry_sync(pending_stats)
    metrics = funnel.snapshot()

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    from m8.discovery.origin_source import build_sniper_provenance_from_events

    _sniper_provenance = build_sniper_provenance_from_events(recent_list)
    artifact = make_sniper_artifact(
        metrics=metrics,
        status=status,
        reasons=reasons,
        source=source,
        freshness_s=round(elapsed_s, 1),
        generated_at_utc=now_utc,
        recent_events=recent_list,
        recent_events_by_dex=recent_events_by_dex,
        self_test_by_dex=metrics.get("self_test_by_dex"),
        run_scope=metrics.get("run_scope", "all"),
        dex_filter=metrics.get("dex_filter"),
        phase2_decision=phase2_summary,
        enricher_config=enricher_config,
        provenance=_sniper_provenance,
    )

    # Per-candidate economics trace for events with a known price reference.
    # Use the run-wide arb_trace when available (covers all candidates, not
    # just the last 20 in the artifact window).  Fall back to recent_list for
    # offline / test scenarios where arb_trace is not threaded through.
    _MAX_ARB_TRACE = 50
    if arb_trace is not None:
        # arb_trace already contains compact dicts; cap to most recent _MAX_ARB_TRACE
        top_arb_candidates: List[Dict[str, Any]] = arb_trace[-_MAX_ARB_TRACE:]
    else:
        top_arb_candidates = []
        for entry in recent_list:
            dec = entry.get("phase2_decision") or {}
            if dec.get("reference_source", "NONE") != "NONE":
                _slip = dec.get("slippage_result") or {}
                top_arb_candidates.append({
                    "event_id": entry.get("event_id"),
                    "pair": entry.get("pair"),
                    "dex": entry.get("dex"),
                    "block_number": entry.get("block_number"),
                    "liquidity_usd": dec.get("liquidity_usd"),
                    "reference_source": dec.get("reference_source"),
                    "spread_bps": dec.get("estimated_spread_bps"),
                    "spread_note": dec.get("spread_note"),
                    "gas_usd": 0.30,
                    "slippage_bps": _slip.get("predicted_bps"),
                    "expected_pnl_usd": dec.get("expected_pnl_usd"),
                    "honeypot_verdict": dec.get("honeypot_verdict"),
                    "route_edges": dec.get("route_edges"),
                    "reject_reason": dec.get("reject_reason"),
                    "verdict": dec.get("verdict"),
                })
    artifact["top_arb_candidates"] = top_arb_candidates

    from monitoring.sniper_health import evaluate_m8_sniper_health

    artifact["m8_health"] = evaluate_m8_sniper_health(artifact)
    if artifact["m8_health"].get("blockers"):
        if status == "ACTIVE":
            status = "DEGRADED"
        elif status == "EMPTY" and "M8_RPC_ERROR_RATE_HIGH" in artifact["m8_health"]["blockers"]:
            status = "RPC_ERROR"
    artifact["status"] = status

    violations = validate_sniper_artifact(artifact)
    if violations:
        logger.warning(
            "artifact_validation_violations",
            extra={"context": {"violations": violations}},
        )

    # Step 8: When an isolated --dex run is active, write to data/tmp/ (NOT _rolling/)
    # to avoid polluting the canonical rolling artifact set.  The canonical
    # new_pool_sniper_latest.json in _rolling is only written for full all-factory runs.
    dex_filter_val = metrics.get("dex_filter")
    if dex_filter_val:
        tmp_dir = Path("data/tmp")
        tmp_dir.mkdir(parents=True, exist_ok=True)
        isolated_path = tmp_dir / f"new_pool_sniper_{dex_filter_val}_latest.json"
        path = write_sniper_artifact(artifact, path=isolated_path)
    else:
        path = write_sniper_artifact(artifact)
    logger.info(
        "artifact_written",
        extra={
            "context": {
                "path": str(path),
                "status": status,
                "run_scope": metrics.get("run_scope", "all"),
                "candidates_total": metrics["snipe_candidates_total"],
                "elapsed_s": round(elapsed_s, 1),
                "m8_health_goal": artifact.get("m8_health", {}).get("goal_status"),
                "m8_health_blockers": artifact.get("m8_health", {}).get("blockers"),
            }
        },
    )
    return artifact


def _sync_pending_registry_from_events(
    recent_events_by_dex: Dict[str, List[Dict[str, Any]]],
    recent_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Persist anchor-connected sniper events into m8_pending_pairs rolling registry."""
    from m8.discovery.pending_pair_registry import (
        load_registry,
        save_registry,
        split_token_anchor,
        update_registry,
    )

    events: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for bucket in (recent_events_by_dex or {}).values():
        for ev in bucket or []:
            eid = str(ev.get("event_id") or "")
            if eid and eid in seen_ids:
                continue
            if eid:
                seen_ids.add(eid)
            events.append(ev)
    for ev in recent_list or []:
        eid = str(ev.get("event_id") or "")
        if eid and eid in seen_ids:
            continue
        if eid:
            seen_ids.add(eid)
        events.append(ev)

    registry = load_registry()
    before_tokens = set((registry.get("tokens") or {}).keys())
    stats = update_registry(registry, events, now_ts=time.time())
    save_registry(registry)
    after_tokens = set((registry.get("tokens") or {}).keys())

    missing_anchor_events = 0
    for ev in events:
        split = split_token_anchor(ev)
        if split is None:
            continue
        addr, _, _ = split
        if addr not in after_tokens:
            missing_anchor_events += 1

    stats["registry_out_of_sync"] = missing_anchor_events > 0
    stats["tokens_before"] = len(before_tokens)
    stats["tokens_after"] = len(after_tokens)
    return stats


def _run_offline_cycle(
    funnel: FunnelTracker,
    configs: List[FactoryConfig],
    chain: str,
    cycle_n: int,
) -> None:
    """Simulate a single poll cycle with zero real logs."""
    # We 'simulate' one RPC call per factory in the counter for visibility.
    for _cfg in configs:
        funnel.inc_rpc_call()
    funnel.complete_cycle()
    logger.info(
        "poll_cycle_offline",
        extra={
            "context": {
                "cycle": cycle_n,
                "chain": chain,
                "new_events": 0,
                "raw_logs": 0,
                "note": "offline mode -- no real RPC",
            }
        },
    )


# ---------------------------------------------------------------------------
# Main polling loop (online)
# ---------------------------------------------------------------------------

def _run_online_loop(
    *,
    rpc_lane: SniperRpcLane,
    configs: List[FactoryConfig],
    chain: str,
    funnel: FunnelTracker,
    recent_events: List[NewPoolEvent],
    seen_ids: Set[str],
    poll_interval_s: float,
    blocks_back: int,
    duration_s: float,
    source: str,
    events_lock: Optional[threading.Lock] = None,
    http_fallback_mode: bool = False,
    phase2_engine: Any = None,
    phase2_event_decisions: Optional[Dict[str, Any]] = None,
    phase2_enricher: Any = None,
    phase2_lock: Optional[threading.Lock] = None,
    arb_trace: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Main online HTTP polling loop.

    When ``http_fallback_mode=True`` (``--prefer-ws`` active): polling interval
    is multiplied by 10 (capped at 300 s) to act as a reconciliation pass,
    and ``funnel.inc_http_fallback_poll()`` is called each cycle.
    """
    if http_fallback_mode:
        # Long interval: reconciliation/catch-up only
        poll_interval_s = min(poll_interval_s * 10, 300.0)
        logger.info(
            "http_polling_in_fallback_mode",
            extra={"context": {"reconciliation_interval_s": poll_interval_s}},
        )
    deadline = time.monotonic() + duration_s
    last_artifact_ts = time.monotonic()
    cycle_n = 0
    last_processed_block: Optional[int] = None

    while time.monotonic() < deadline:
        cycle_start = time.monotonic()
        cycle_n += 1

        current_block = _get_block_number(rpc_lane.w3)
        if current_block is None:
            funnel.inc_rpc_error()
            logger.warning(
                "poll_cycle_skip -- block_number unavailable",
                extra={"context": {"cycle": cycle_n}},
            )
            time.sleep(min(poll_interval_s, 5.0))
            continue

        if last_processed_block is None:
            from_block = max(0, current_block - blocks_back)
        else:
            from_block = last_processed_block + 1

        # Guard against going backwards (e.g. RPC jitter / re-org)
        from_block = min(from_block, current_block)
        # Chunk to max allowed range
        to_block = min(current_block, from_block + _MAX_BLOCKS_PER_CALL - 1)

        cycle_raw = 0
        cycle_new = 0
        cycle_rpc_calls = 0
        per_factory_latency_ms: Dict[str, float] = {}

        # ------------------------------------------------------------------
        # Step 6: Concurrent factory polling (bounded thread pool).
        # Each factory eth_getLogs runs in parallel; per-factory latency
        # is recorded for the artifact (Step 8).
        # ------------------------------------------------------------------
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _poll_factory(cfg: FactoryConfig) -> tuple[FactoryConfig, list, bool, str, float]:
            params = _build_filter_params(rpc_lane.w3, cfg, from_block, to_block)
            t_start = time.monotonic()
            logs, had_err, err_str = _get_logs_safe(rpc_lane, params)
            return cfg, logs, had_err, err_str, (time.monotonic() - t_start) * 1000.0

        max_workers = min(len(configs), 2 if len(configs) >= 8 else 4) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = []
            for i, cfg in enumerate(configs):
                if i > 0 and max_workers < len(configs):
                    time.sleep(0.15)
                futures.append(pool.submit(_poll_factory, cfg))
            for fut in as_completed(futures):
                cfg, logs, had_err, err_str, lat_ms = fut.result()
                cycle_rpc_calls += 1
                funnel.inc_rpc_call()
                per_factory_latency_ms[cfg.dex] = round(lat_ms, 1)
                err_code = ""
                if had_err and err_str:
                    from monitoring.sniper_funnel import _classify_rpc_error
                    err_code = _classify_rpc_error(err_str)
                funnel.record_factory_poll(cfg.dex, ok=not had_err, error_code=err_code)
                if had_err:
                    funnel.inc_rpc_error(err_str)
                    funnel.inc_dex(cfg.dex, "error")
                    continue
                funnel.inc("raw_fetched", len(logs))
                funnel.inc_dex(cfg.dex, "polls_ok")
                funnel.inc_dex(cfg.dex, "raw_logs", len(logs))
                cycle_raw += len(logs)

                for raw_log in logs:
                    candidate = _process_log_event(
                        raw_log, cfg, funnel, seen_ids, recent_events, events_lock,
                    )
                    if candidate is not None:
                        cycle_new += 1
                        if (phase2_engine is not None
                                and phase2_event_decisions is not None):
                            if phase2_lock is not None:
                                phase2_lock.acquire()
                            try:
                                _apply_phase2_decision(
                                    candidate, phase2_engine, phase2_event_decisions,
                                    enricher=phase2_enricher, funnel=funnel,
                                    arb_trace=arb_trace,
                                )
                            finally:
                                if phase2_lock is not None:
                                    phase2_lock.release()

        cycle_duration_ms = (time.monotonic() - cycle_start) * 1000.0
        last_processed_block = to_block
        funnel.complete_cycle()
        funnel.record_cycle_latency(cycle_duration_ms, per_factory_latency_ms)
        if http_fallback_mode:
            funnel.inc_http_fallback_poll()

        elapsed_since_artifact = time.monotonic() - last_artifact_ts
        if elapsed_since_artifact >= _ARTIFACT_WRITE_INTERVAL_S:
            snap = funnel.snapshot()
            elapsed_total = snap["elapsed_s"]
            if snap["snipe_candidates_total"] > 0:
                status = "ACTIVE"
                reasons = []
            elif (snap["rpc_errors"] > 0 and snap["raw_fetched"] == 0
                  and snap.get("ws_subscriptions", 0) == 0):
                status = "RPC_ERROR"
                reasons = ["RPC_UNAVAILABLE"]
            else:
                status = "EMPTY"
                reasons = ["NO_EVENTS_YET"]
            # Step 3: snapshot under lock to prevent concurrent WS mutation.
            if phase2_lock is not None:
                with phase2_lock:
                    decisions_snap = dict(phase2_event_decisions) if phase2_event_decisions else {}
            else:
                decisions_snap = dict(phase2_event_decisions) if phase2_event_decisions else {}
            _build_and_write_artifact(
                funnel=funnel,
                recent_events=recent_events,
                started_at="",
                elapsed_s=elapsed_total,
                source=source,
                status=status,
                reasons=reasons,
                w3=rpc_lane.w3,
                phase2_event_decisions=decisions_snap,
                arb_trace=list(arb_trace) if arb_trace is not None else None,
            )
            last_artifact_ts = time.monotonic()

        logger.info(
            "poll_cycle",
            extra={
                "context": {
                    "cycle": cycle_n,
                    "chain": chain,
                    "block_range": f"{from_block}-{to_block}",
                    "raw_logs": cycle_raw,
                    "new_events": cycle_new,
                    "total_candidates": funnel.snapshot()["snipe_candidates_total"],
                    "cycle_duration_ms": round(cycle_duration_ms, 1),
                    "rpc_calls": cycle_rpc_calls,
                    "factory_latency_ms": per_factory_latency_ms,
                }
            },
        )

        # Sleep the remainder of the poll interval
        cycle_elapsed = time.monotonic() - cycle_start
        sleep_s = max(0.0, poll_interval_s - cycle_elapsed)
        if sleep_s > 0:
            time.sleep(sleep_s)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point.  Returns OS exit code (0=ok, 1=error, 3=self-test fail)."""
    load_root_dotenv()

    # ------------------------------------------------------------------
    # Feature flag gate -- intentional early exit (not an error)
    # ------------------------------------------------------------------
    if not env_flag_enabled("ARBY_SNIPER_ENABLE"):
        print(
            "[sniper_smoke_run] ARBY_SNIPER_ENABLE is not set or is '0'. "
            "Set ARBY_SNIPER_ENABLE=1 to run the sniper listener. Exiting."
        )
        return 0

    # ------------------------------------------------------------------
    # Parse args
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="M8 Phase 1 -- New-pool factory event smoke runner.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--chain", default=_DEFAULT_CHAIN,
        help="Chain to listen on (e.g. 'base').",
    )
    parser.add_argument(
        "--duration-minutes", type=float, default=_DEFAULT_DURATION_MIN,
        metavar="N",
        help="How long to run (minutes). 0 = single cycle then exit.",
    )
    parser.add_argument(
        "--poll-interval-s", type=float, default=_DEFAULT_POLL_INTERVAL_S,
        metavar="S",
        help="Seconds between eth_getLogs polls.",
    )
    parser.add_argument(
        "--blocks-back", type=int, default=_DEFAULT_BLOCKS_BACK,
        metavar="N",
        help="How many historical blocks to fetch on first cycle.",
    )
    parser.add_argument(
        "--rpc-url", default=None,
        help="Override RPC URL (ignores env vars).",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Offline mode: skip real RPC, simulate empty cycles.",
    )
    parser.add_argument(
        "--log-json", action="store_true",
        help="Emit JSON-formatted log lines (for file capture).",
    )
    parser.add_argument(
        "--skip-self-test", action="store_true",
        help="Skip startup self-test (verification block replay).",
    )
    parser.add_argument(
        "--skip-preflight", action="store_true",
        help="Skip RPC preflight (chain_id + archive + newHeads).",
    )
    parser.add_argument(
        "--prefer-ws", action="store_true",
        help="(Phase 1.3+) Prefer WS endpoint when resolvable; HTTP polling stays "
             "as fallback (heartbeat + reconnect implemented elsewhere).",
    )
    parser.add_argument(
        "--acceptance-run", action="store_true",
        help="M8 acceptance gate: require self-test, prefer WS, and write health blockers.",
    )
    parser.add_argument(
        "--strict-health", action="store_true",
        help="Exit non-zero when m8_health.blockers is non-empty after final artifact write.",
    )
    parser.add_argument(
        "--dex", default=None, metavar="DEX",
        help="If set, only listen to this DEX (e.g. 'pancakeswap_v3'). "
             "Useful for isolated single-DEX WS gates.",
    )
    args = parser.parse_args(argv)

    # Offline via ENV as well
    offline = args.offline or env_flag_enabled("ARBY_SNIPER_OFFLINE")

    # ------------------------------------------------------------------
    # Logging setup
    # ------------------------------------------------------------------
    setup_logging(json_format=args.log_json)

    if args.acceptance_run:
        if args.skip_self_test:
            logger.error(
                "acceptance_run_forbids_skip_self_test",
                extra={"context": {"flag": "--skip-self-test"}},
            )
            return 2
        if not args.prefer_ws:
            args.prefer_ws = True
            logger.warning(
                "acceptance_run_auto_prefer_ws",
                extra={"context": {"reason": "--acceptance-run requires WS-first lane"}},
            )

    logger.info(
        "sniper_startup",
        extra={
            "context": {
                "chain": args.chain,
                "duration_minutes": args.duration_minutes,
                "poll_interval_s": args.poll_interval_s,
                "blocks_back": args.blocks_back,
                "offline": offline,
            }
        },
    )

    # ------------------------------------------------------------------
    # Load factory configs
    # ------------------------------------------------------------------
    try:
        configs = load_factory_config(chain_filter=args.chain, dex_filter=args.dex)
    except Exception as exc:
        logger.error(
            "factory_config_load_failed",
            extra={"context": {"error": str(exc)}},
        )
        return 1

    if not configs:
        logger.error(
            "factory_config_empty",
            extra={"context": {"chain": args.chain}},
        )
        return 1

    logger.info(
        "factory_config_loaded",
        extra={
            "context": {
                "chain": args.chain,
                "factories": [c.factory for c in configs],
                "dexes": [c.dex for c in configs],
            }
        },
    )

    # ------------------------------------------------------------------
    # Warn about factories with unverified topic0 (topic0_verified=False)
    # ------------------------------------------------------------------
    unverified_topic_factories = [
        c.dex for c in configs
        if c.topic0 is not None and not c.topic0_verified
    ]
    null_topic_factories = [
        c.dex for c in configs if c.topic0 is None
    ]
    if unverified_topic_factories:
        logger.warning(
            "topic0_unverified -- topic0 computed but not confirmed from contract ABI; "
            "online filtering may miss events or filter wrong logs",
            extra={"context": {"unverified_dexes": unverified_topic_factories}},
        )
    if null_topic_factories:
        logger.warning(
            "topic0_null -- these factories will fetch all events (no topic0 filter); "
            "expect higher RPC load",
            extra={"context": {"null_topic_dexes": null_topic_factories}},
        )

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    funnel = FunnelTracker()
    recent_events: List[NewPoolEvent] = []
    seen_ids: Set[str] = set()
    source = f"sniper_smoke_run/{args.chain}"
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t0 = time.monotonic()

    # Record run scope so artifact reflects whether this is a full or isolated run.
    _dex_filter = getattr(args, "dex", None)
    funnel.set_run_scope(run_scope="all" if not _dex_filter else _dex_filter, dex_filter=_dex_filter)

    # ------------------------------------------------------------------
    # Phase 2 paper-only engine setup
    # ------------------------------------------------------------------
    _paper_mode = env_flag_enabled("ARBY_SNIPER_PAPER")
    _execute_mode = env_flag_enabled("ARBY_SNIPER_EXECUTE")
    if _execute_mode:
        logger.error(
            "phase2_execute_blocked",
            extra={"context": {
                "reason": "ARBY_SNIPER_EXECUTE=1 is NOT permitted in Phase 2 paper-only mode",
                "policy": "kill_switch_active=true, execution_enabled=false",
            }},
        )
        return 1

    phase2_engine: Any = None
    phase2_event_decisions: Dict[str, Any] = {}
    phase2_enricher: Any = None
    if _paper_mode:
        if _PHASE2_ENTRY_ENGINE_AVAILABLE:
            phase2_engine = make_default_engine()
            logger.info(
                "phase2_entry_engine_loaded",
                extra={"context": {"paper_mode": True, "execute_mode": False}},
            )
        else:  # pragma: no cover
            logger.warning(
                "phase2_paper_mode_requested_but_engine_unavailable",
                extra={"context": {"hint": "strategy.sniper_entry_decision import failed"}},
            )

    # ------------------------------------------------------------------
    # Online-only: build web3 + self-test
    # ------------------------------------------------------------------
    rpc_lane: Optional[SniperRpcLane] = None
    w3: Any = None
    if not offline:
        try:
            rpc_lane = _build_sniper_rpc_lane(args.chain, args.rpc_url, funnel)
        except RuntimeError as exc:
            logger.error(str(exc))
            return 1
        except Exception as exc:
            logger.error(
                "sniper_rpc_lane_init_failed",
                extra={"context": {"error": str(exc)}},
            )
            return 1

        w3 = rpc_lane.w3
        rpc_url = _resolve_rpc_url(args.chain, args.rpc_url)

        # --------------------------------------------------------------
        # RPC preflight (Step 3) -- chain_id + archive depth + WS newHeads.
        # Skippable with --skip-preflight. Hard-fails only on chain_id mismatch.
        # --------------------------------------------------------------
        if not args.skip_preflight:
            try:
                from scripts.check_rpc_endpoints import (
                    check_chain_id, check_http_archive, check_ws_newheads,
                )
                chain_id_map = {"base": 8453, "arbitrum": 42161, "optimism": 10, "ethereum": 1}
                expected_chain_id = chain_id_map.get(args.chain.lower(), 0)
                if expected_chain_id:
                    ok, msg = check_chain_id(rpc_url, expected_chain_id)
                    if ok:
                        logger.info("preflight_chain_id_ok", extra={"context": {"msg": msg}})
                    else:
                        logger.error("preflight_chain_id_FAIL", extra={"context": {"msg": msg}})
                        return 4

                ok, msg = check_http_archive(rpc_url, archive_depth=2000)
                logger.info(
                    "preflight_archive",
                    extra={"context": {"ok": ok, "msg": msg[:120]}},
                )

                # WS newHeads is informational only; HTTP-polling can still run.
                ws_url = _resolve_ws_url(args.chain, None)
                if ws_url:
                    ok, msg = check_ws_newheads(ws_url, timeout=15.0)
                    logger.info(
                        "preflight_ws_newheads",
                        extra={"context": {"ok": ok, "msg": msg[:120], "ws_resolved": True}},
                    )
                else:
                    logger.info(
                        "preflight_ws_newheads_skipped",
                        extra={"context": {"reason": "no WS URL resolved for chain"}},
                    )
            except Exception as exc:
                logger.warning(
                    "preflight_exception",
                    extra={"context": {"error": str(exc)[:120]}},
                )

        if not args.skip_self_test:
            self_test_ok, self_test_results = _run_self_test(
                rpc_lane, configs, args.chain
            )
            if not self_test_ok:
                logger.error("self_test_FAILED -- aborting run (use --skip-self-test to bypass)")
                return 3
        else:
            self_test_results: Dict[str, Any] = {}
            logger.warning(
                "self_test_skipped_via_flag",
                extra={"context": {"reason": "--skip-self-test is set; historical parser check bypassed"}},
            )

        # Store self-test results in the funnel for artifact inclusion.
        funnel.set_self_test_results(self_test_results)

    # ------------------------------------------------------------------
    # Phase 2 enricher setup (online-only: requires w3)
    # ------------------------------------------------------------------
    enricher_config: Optional[Dict[str, Any]] = None
    if _paper_mode and not offline and w3 is not None and _PHASE2_ENRICHER_AVAILABLE:
        try:
            phase2_enricher = EntryCandidateEnricher(w3)
            enricher_config = phase2_enricher.config_snapshot()
            logger.info(
                "phase2_enricher_loaded",
                extra={"context": {"paper_mode": True, "chain": args.chain,
                                   "enricher_config": enricher_config}},
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "phase2_enricher_init_failed",
                extra={"context": {"error": str(exc)[:120]}},
            )

    # Step 8: seed mirror data via historical probes before the live gate.
    if phase2_enricher is not None:
        try:
            from strategy.mirror_seeder import seed_mirror_data
            seed_result = seed_mirror_data(phase2_enricher, w3, configs)
            logger.info(
                "mirror_seeder_complete",
                extra={"context": seed_result},
            )
        except Exception as exc:
            logger.warning(
                "mirror_seeder_failed",
                extra={"context": {"error": str(exc)[:120]}},
            )
    # ------------------------------------------------------------------
    duration_s = args.duration_minutes * 60.0
    # Treat 0 duration as "one cycle then exit"; use a small positive value.
    if duration_s <= 0:
        duration_s = 0.001

    # ------------------------------------------------------------------
    # --prefer-ws: start WSPoolEventListener on a background thread.
    # HTTP polling runs as a slower reconciliation fallback.
    # ------------------------------------------------------------------
    events_lock = threading.Lock()
    # Step 2: separate lock protecting the Phase 2 enricher's seen_pairs registry
    # and the phase2_event_decisions dict from concurrent WS + HTTP mutations.
    phase2_lock = threading.Lock()
    # Run-wide list of all arb candidates (reference_source != NONE).
    # Unlike recent_events (capped at last 20), this persists the full run.
    arb_trace: List[Dict[str, Any]] = []
    ws_listener = None
    ws_thread = None
    http_fallback_mode = False

    if args.prefer_ws and not offline:
        ws_url = _resolve_ws_url(args.chain, None)
        if ws_url:
            ws_provider = classify_provider(ws_url)
            http_fallback_provider = (
                rpc_lane.primary_provider if rpc_lane is not None else "unknown"
            )
            funnel.set_prefer_ws_rpc_providers(
                ws_provider=ws_provider,
                http_fallback_provider=http_fallback_provider,
            )
            logger.info(
                "prefer_ws_rpc_lane",
                extra={"context": {
                    "ws_provider": ws_provider,
                    "http_fallback_provider": http_fallback_provider,
                }},
            )
            try:
                from m8.runtime.ws_listener import WSPoolEventListener
                ws_on_event = _make_ws_on_event_callback(
                    funnel, seen_ids, recent_events, events_lock,
                    phase2_engine=phase2_engine,
                    phase2_event_decisions=phase2_event_decisions,
                    phase2_enricher=phase2_enricher,
                    phase2_lock=phase2_lock,
                    arb_trace=arb_trace,
                )
                ws_listener = WSPoolEventListener(
                    ws_url=ws_url,
                    configs=configs,
                    on_event=ws_on_event,
                )
                funnel.set_listener_mode("ws+http_fallback")
                ws_thread = threading.Thread(
                    target=ws_listener.run,
                    daemon=True,
                    name="ws-listener",
                )
                ws_thread.start()
                http_fallback_mode = True
                logger.info(
                    "ws_listener_started",
                    extra={"context": {
                        "ws_url": ws_url[:60],
                        "factories": len(configs),
                        "http_fallback_interval_s": min(args.poll_interval_s * 10, 300.0),
                    }},
                )
            except Exception as exc:
                logger.warning(
                    "ws_listener_start_failed -- HTTP polling continues as primary",
                    extra={"context": {"error": str(exc)[:120]}},
                )
                ws_listener = None
                ws_thread = None
        else:
            logger.warning(
                "prefer_ws_set_but_no_ws_url -- HTTP polling continues as primary",
                extra={"context": {"chain": args.chain}},
            )

    try:
        if offline:
            # Single offline cycle (enough for smoke / CI)
            _run_offline_cycle(funnel, configs, args.chain, cycle_n=1)
            # Extra cycles if duration > poll_interval
            extra_cycles = max(0, int(duration_s / max(args.poll_interval_s, 1.0)) - 1)
            for n in range(2, extra_cycles + 2):
                _run_offline_cycle(funnel, configs, args.chain, cycle_n=n)
        else:
            assert rpc_lane is not None
            _run_online_loop(
                rpc_lane=rpc_lane,
                configs=configs,
                chain=args.chain,
                funnel=funnel,
                recent_events=recent_events,
                seen_ids=seen_ids,
                poll_interval_s=args.poll_interval_s,
                blocks_back=args.blocks_back,
                duration_s=duration_s,
                source=source,
                events_lock=events_lock,
                http_fallback_mode=http_fallback_mode,
                phase2_engine=phase2_engine,
                phase2_event_decisions=phase2_event_decisions,
                phase2_enricher=phase2_enricher,
                phase2_lock=phase2_lock,
                arb_trace=arb_trace,
            )
    except KeyboardInterrupt:
        logger.info("sniper interrupted by user (KeyboardInterrupt)")

    # ------------------------------------------------------------------
    # Stop WS listener thread (if running) and sync stats into funnel.
    # ------------------------------------------------------------------
    if ws_listener is not None:
        ws_listener.stop()
        if ws_thread is not None:
            ws_thread.join(timeout=3.0)
        stats = ws_listener.stats
        funnel.update_ws_stats(
            connected=(stats.subscriptions_succeeded > 0),
            subscriptions=stats.subscriptions_succeeded,
            events_seen=stats.log_events_emitted,
            reconnects=stats.reconnect_attempts,
            last_event_seen_ts=stats.last_event_seen_ts,
            events_by_dex=stats.events_by_dex,
            callbacks_ok_by_dex=stats.callbacks_ok_by_dex,
        )
        logger.info(
            "ws_listener_stopped",
            extra={"context": {
                "subscriptions": stats.subscriptions_succeeded,
                "events_emitted": stats.log_events_emitted,
                "reconnects": stats.reconnect_attempts,
                "disconnects": stats.disconnects,
            }},
        )

    # ------------------------------------------------------------------
    # Final artifact write
    # ------------------------------------------------------------------
    snap = funnel.snapshot()
    elapsed_s = snap["elapsed_s"]
    if snap["snipe_candidates_total"] > 0:
        status = "ACTIVE"
        reasons: List[str] = []
    elif (snap["rpc_errors"] > 0 and snap["raw_fetched"] == 0
          and snap.get("ws_subscriptions", 0) == 0):
        status = "RPC_ERROR"
        reasons = ["RPC_UNAVAILABLE"]
    else:
        status = "EMPTY"
        reasons = ["NO_EVENTS_YET"]

    # Append topic-quality warnings to reasons so they appear in artifact.
    for dex_name in unverified_topic_factories:
        reasons.append(f"TOPIC_UNVERIFIED:{dex_name}")
    for dex_name in null_topic_factories:
        reasons.append(f"TOPIC_NULL:{dex_name}")
    if args.skip_self_test:
        reasons.append("SELF_TEST_SKIPPED")

    # Step 3: snapshot decisions under lock before final artifact write.
    with phase2_lock:
        final_decisions = dict(phase2_event_decisions) if phase2_event_decisions else {}

    artifact = _build_and_write_artifact(
        funnel=funnel,
        recent_events=recent_events,
        started_at=started_at,
        elapsed_s=elapsed_s,
        source=source,
        status=status,
        reasons=reasons,
        w3=w3 if not offline else None,
        phase2_event_decisions=final_decisions,
        enricher_config=enricher_config,
        arb_trace=list(arb_trace),
    )

    health_blockers = (artifact.get("m8_health") or {}).get("blockers") or []
    if (args.strict_health or args.acceptance_run) and health_blockers:
        logger.error(
            "m8_health_gate_failed",
            extra={"context": {"blockers": health_blockers}},
        )
        return 5

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------
    for line in funnel.funnel_table_lines():
        print(line)

    logger.info(
        "sniper_shutdown",
        extra={
            "context": {
                "status": status,
                "elapsed_s": elapsed_s,
                "candidates_total": snap["snipe_candidates_total"],
                "cycles_completed": snap["cycles_completed"],
            }
        },
    )
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
