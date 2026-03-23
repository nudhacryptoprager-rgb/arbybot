# PATH: strategy/infra.py
"""
Infrastructure helpers for scan jobs.

Extracted from run_scan_real.py for modularity.
Contains RPC, WebSocket, Tenderly, and slot0 helpers.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("strategy.infra")


def get_current_block_via_rpc(config: Dict[str, Any]) -> Tuple[int, int]:
    """
    Get current block number via RPC.
    
    Args:
        config: Config with rpc_endpoints and chain_id
        
    Returns:
        (block_number, latency_ms)
        
    Raises:
        BlockPinError: If RPC fails
    """
    import asyncio
    from core.exceptions import BlockPinError
    from chains.providers import register_provider
    
    rpc_urls = config.get("rpc_endpoints") or []
    
    # If Require-Alchemy is set, prefer Alchemy endpoints for non-Base chains
    # (do NOT embed keys in configs; use ALCHEMY_API_KEY env).
    require_alchemy = os.environ.get("ARBY_REQUIRE_ALCHEMY") == "1" or os.environ.get("REQUIRE_ALCHEMY") == "1"
    try:
        chain_id = int(config.get("chain_id", 42161))
    except Exception:
        chain_id = 42161
    if require_alchemy and chain_id != 8453:
        try:
            from core.rpc_urls import resolve_rpc_http
            url, provider, _diag = resolve_rpc_http(chain_id=chain_id, network=os.environ.get("NETWORK"), env=os.environ)
            if url and provider == "alchemy":
                rpc_urls = [url]
        except Exception:
            pass
    
    # v3.2.32: Config rpc_endpoints take priority by default (multi-chain safety)
    # Only add env var if config doesn't have endpoints
    if not rpc_urls:
        resolved_http_env = os.environ.get("ARBY_RPC_HTTP_PRIMARY")
        if resolved_http_env:
            rpc_urls = [resolved_http_env]
    
    provider = register_provider(
        config.get("chain_id", 42161), 
        rpc_urls, 
        timeout_seconds=config.get("rpc_timeout_seconds", 10)
    )
    
    try:
        block, lat = asyncio.run(provider.get_block_number())
        return int(block), int(lat or 0)
    except Exception as e:
        raise BlockPinError(f"Failed to pin current block via RPC: {e}")


# read_slot0_v3 removed in R28.29 (dead code). Canonical version lives in
# strategy.quotes.read_slot0_v3 (with multicall cache support).


def resolve_rpc_endpoints(config: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], str, str]:
    """
    Resolve HTTP and WS RPC endpoints.
    
    Args:
        config: Config with chain_id and network
        
    Returns:
        (http_url, ws_url, http_provider, ws_provider)
        
    v3.2.32: Config rpc_endpoints take highest priority over env vars.
    This ensures multi-chain configs are self-contained and reproducible.
    """
    try:
        from core.rpc_urls import resolve_rpc_http, resolve_rpc_ws
    except Exception:
        return None, None, "unknown", "unknown"
    
    resolved_http = None
    resolved_ws = None
    provider_http = "unknown"
    provider_ws = "unknown"
    
    chain_id = config.get("chain_id")
    network = os.environ.get("NETWORK")
    
    # If Require-Alchemy is set, prefer Alchemy endpoints for non-Base chains.
    # This keeps configs key-free while honoring infra policy.
    require_alchemy = os.environ.get("ARBY_REQUIRE_ALCHEMY") == "1" or os.environ.get("REQUIRE_ALCHEMY") == "1"
    try:
        chain_id_int = int(chain_id) if chain_id is not None else None
    except Exception:
        chain_id_int = None
    if require_alchemy and chain_id_int is not None and chain_id_int != 8453 and resolve_rpc_http:
        try:
            url, prov, _diag = resolve_rpc_http(chain_id=chain_id_int, network=network, env=os.environ)
            if url and prov == "alchemy":
                resolved_http = url
                provider_http = "alchemy"
                from urllib.parse import urlparse
                os.environ["ARBY_RPC_HTTP_PRIMARY"] = resolved_http
                os.environ["ARBY_RPC_PROVIDER"] = provider_http
                os.environ["ARBY_RPC_HTTP_HOST"] = urlparse(resolved_http).netloc
                return resolved_http, resolved_ws, provider_http, provider_ws
        except Exception:
            pass
    
    # v3.2.32: Config rpc_endpoints take HIGHEST priority (for multi-chain bring-up)
    # v3.2.33: OVERWRITE env vars to prevent env pollution from prior runs
    # v3.2.54: Continue to resolve WS even when HTTP comes from config (don't return early)
    config_rpc_endpoints = config.get("rpc_endpoints") or []
    if config_rpc_endpoints:
        # Use first config endpoint as HTTP
        resolved_http = config_rpc_endpoints[0]
        provider_http = "config"
        if resolved_http:
            from urllib.parse import urlparse
            # v3.2.33: OVERWRITE (not setdefault) to ensure config wins
            os.environ["ARBY_RPC_HTTP_PRIMARY"] = resolved_http
            os.environ["ARBY_RPC_PROVIDER"] = "config"
            os.environ["ARBY_RPC_HTTP_HOST"] = urlparse(resolved_http).netloc
        # v3.2.54: Clear stale WS env vars before resolving chain-specific WS
        for key in ["ARBY_RPC_WS_PRIMARY", "ARBY_RPC_WS_PROVIDER", "ARBY_RPC_WS_HOST"]:
            os.environ.pop(key, None)
        # v3.2.54: Fall through to WS resolution below (don't return early)
    
    if resolve_rpc_http and not resolved_http:
        try:
            url, provider_http, diag = resolve_rpc_http(chain_id=chain_id, network=network, env=os.environ)
            resolved_http = url
            if resolved_http:
                from urllib.parse import urlparse
                os.environ.setdefault("ARBY_RPC_HTTP_PRIMARY", resolved_http)
                os.environ.setdefault("ARBY_RPC_PROVIDER", provider_http)
                os.environ.setdefault("ARBY_RPC_HTTP_HOST", urlparse(resolved_http).netloc)
        except Exception:
            resolved_http = None
    
    if resolve_rpc_ws:
        try:
            urlw, provider_ws, diagw = resolve_rpc_ws(chain_id=chain_id, network=network, env=os.environ)
            resolved_ws = urlw
            if resolved_ws:
                from urllib.parse import urlparse
                # v3.2.54: OVERWRITE (not setdefault) to prevent WS pollution from prior runs
                os.environ["ARBY_RPC_WS_PRIMARY"] = resolved_ws
                os.environ["ARBY_RPC_WS_PROVIDER"] = provider_ws
                os.environ["ARBY_RPC_WS_HOST"] = urlparse(resolved_ws).netloc
        except Exception:
            resolved_ws = None
    
    return resolved_http, resolved_ws, provider_http, provider_ws


def check_ws_connection(ws_url: str) -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Check WebSocket connection with handshake.
    
    Args:
        ws_url: WebSocket URL to check
        
    Returns:
        (connected, handshake_ms, error)
    """
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return False, None, "skipped"
    
    try:
        import websocket as _wsclient
        import time as _time
        
        start = _time.monotonic()
        conn = _wsclient.create_connection(ws_url, timeout=5)
        conn.close()
        end = _time.monotonic()
        handshake_ms = int((end - start) * 1000)
        return True, handshake_ms, None
    except Exception as e:
        return False, None, str(e)


def check_tenderly_connection() -> Tuple[bool, Optional[bool], Optional[str]]:
    """
    Check Tenderly API connection (optional).
    
    Returns:
        (enabled, ok, error)
    """
    tenderly_configured = bool(os.environ.get("TENDERLY_ACCESS_KEY"))
    
    if not tenderly_configured or os.environ.get("ARBY_SKIP_RPC") == "1":
        return False, None, "disabled"
    
    try:
        import httpx
        headers = {"X-Access-Key": os.environ.get("TENDERLY_ACCESS_KEY")}
        account = os.environ.get("TENDERLY_ACCOUNT")
        project = os.environ.get("TENDERLY_PROJECT")
        
        if account and project:
            url = f"https://api.tenderly.co/api/v1/account/{account}/project/{project}"
        else:
            url = "https://api.tenderly.co/api/v1/account"
        
        resp = httpx.get(url, headers=headers, timeout=5.0)
        if resp.status_code == 200:
            return True, True, None
        else:
            return False, False, "disabled"
    except Exception:
        return False, False, "disabled"


# Forward declaration for singleton (defined at end of file)
_provider_router = None


def build_infra_payload(
    resolved_http: Optional[str],
    resolved_ws: Optional[str],
    ws_connected: bool,
    ws_handshake_ms: Optional[int],
    ws_error: Optional[str],
    tenderly_enabled: bool,
    tenderly_ok: Optional[bool],
    tenderly_error: Optional[str],
    *,
    provider_http: str = "unknown",
    provider_ws: str = "unknown",
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build infra payload for artifacts.
    
    Args:
        provider_http: Provider ID for HTTP endpoint (from resolve_rpc_endpoints)
        provider_ws: Provider ID for WS endpoint (from resolve_rpc_endpoints)
    
    Returns:
        Dict with infra diagnostics
    """
    from urllib.parse import urlparse
    
    # v2.2.0 Fix Step 4: Use actually resolved provider, not from primary URL
    rpc_provider = provider_http if provider_http != "unknown" else "public"
    transport = "http"
    ws_enabled = False
    rpc_http_host = None
    rpc_ws_host = None
    
    if resolved_http:
        rpc_http_host = urlparse(resolved_http).netloc
        if "alchemy" in (resolved_http or ""):
            rpc_provider = "alchemy"
    
    if resolved_ws:
        ws_enabled = True
        rpc_ws_host = urlparse(resolved_ws).netloc
        transport = "ws+http"
        # v3.2.55: Extract provider from URL if not already set
        if provider_ws == "unknown" and rpc_ws_host:
            if "alchemy" in rpc_ws_host:
                provider_ws = "alchemy"
            elif "infura" in rpc_ws_host:
                provider_ws = "infura"
            elif "quicknode" in rpc_ws_host:
                provider_ws = "quicknode"
            else:
                provider_ws = "public"
    
    payload = {
        "rpc_provider": rpc_provider,
        "transport": transport,
        "ws_enabled": ws_enabled,
        "ws_attempted": bool(resolved_ws),
        "ws_connected": ws_connected,
        "ws_fallback_to_http": False if ws_connected else bool(resolved_http),
        "ws_error": ws_error,
        "tenderly_enabled": tenderly_enabled,
        "tenderly_ok": tenderly_ok,
        "tenderly_error": tenderly_error,
    }
    
    # v2.2.0: Add ws_lag_ms (alias for ws_handshake_ms for Roadmap M5_0)
    if ws_handshake_ms is not None:
        payload["ws_lag_ms"] = ws_handshake_ms
    
    if rpc_http_host:
        payload["rpc_http_host"] = rpc_http_host
    if rpc_ws_host:
        payload["rpc_ws_host"] = rpc_ws_host
    if ws_handshake_ms is not None:
        payload["ws_handshake_ms"] = ws_handshake_ms
    
    # v2.2.0 Fix Step 4: Set provider_id to actually used provider (not from config/registry)
    # Roadmap M5_0 requires "який провайдер реально використано"
    payload["provider_id"] = provider_http if provider_http != "unknown" else None
    if provider_http != "unknown" or provider_ws != "unknown":
        payload["provider_id_http"] = provider_http
        payload["provider_id_ws"] = provider_ws
    
    # v2.2.0: Add provider stats from chains/providers.py (canonical source)
    # Replaces the duplicate MultiProviderRouter scaffolding
    try:
        from chains.providers import get_global_provider_stats, extract_provider_name
        provider_stats = get_global_provider_stats()
        if provider_stats.get("providers_count", 0) > 0:
            # v2.2.0 Fix Step 5: Clarify router metrics
            provider_names = provider_stats.get("provider_names", [])
            endpoints_count = 0
            chains_count = 0
            for chain_data in provider_stats.get("providers", {}).values():
                chains_count += 1
                endpoints_count += len(chain_data)  # Each chain has dict of URL -> stats
            
            # v2.2.0 Fix Step 4: Count distinct endpoints actually used (requests > 0)
            # v2.2.0 Fix Step 3: Use extract_provider_name() for canonical provider_id
            # v2.3.0: Add per-endpoint breakdown for failover evidence
            endpoints_used_count = 0
            endpoints_used_ids: List[str] = []
            requests_by_endpoint: Dict[str, int] = {}
            errors_by_endpoint: Dict[str, int] = {}
            endpoint_details: List[Dict[str, Any]] = []
            
            for chain_id, chain_data in provider_stats.get("providers", {}).items():
                for url, url_stats in chain_data.items():
                    endpoint_id = url_stats.get("endpoint_id", "unknown")
                    total_req = url_stats.get("total_requests", 0)
                    failed_req = url_stats.get("failed_requests", 0)
                    
                    if total_req > 0:
                        endpoints_used_count += 1
                        # Use canonical extract_provider_name for proper provider_id
                        pname = extract_provider_name(url)
                        if pname and pname != "unknown" and pname not in endpoints_used_ids:
                            endpoints_used_ids.append(pname)
                        
                        # v2.3.0: Per-endpoint metrics
                        requests_by_endpoint[endpoint_id] = total_req
                        if failed_req > 0:
                            errors_by_endpoint[endpoint_id] = failed_req
                        
                        # v2.3.0: Detailed endpoint info for debugging
                        endpoint_details.append({
                            "endpoint_id": endpoint_id,
                            "provider": pname,
                            "requests": total_req,
                            "success_rate": url_stats.get("success_rate", 0.0),
                            "failed": failed_req,
                            "avg_latency_ms": url_stats.get("avg_latency_ms", 0),
                            "quarantined": url_stats.get("quarantined", False),
                            "stress_test_fails": url_stats.get("stress_test_fails", 0),
                        })
            
            payload["provider_router"] = {
                "chains_count": chains_count,  # v2.2.0 Fix Step 5: Number of chains configured
                "endpoints_configured_count": endpoints_count,  # v2.2.0: Number of RPC URLs configured
                "endpoints_used_count": endpoints_used_count,  # v2.2.0: Distinct endpoints with requests > 0
                "endpoints_used": endpoints_used_ids,  # v2.2.0: Canonical provider IDs (alchemy, infura, etc.)
                "provider_names": provider_names,  # v2.2.0: List of all configured provider names
                "total_requests": provider_stats.get("total_requests", 0),
                "global_success_rate": provider_stats.get("global_success_rate", 1.0),
                "requests_by_endpoint": requests_by_endpoint,  # v2.3.0: Per-endpoint request counts
                "errors_by_endpoint": errors_by_endpoint,  # v2.3.0: Per-endpoint error counts
                "endpoints_details": endpoint_details,  # v2.3.0: Full endpoint breakdown
                "failover_stress_active": int(os.environ.get("ARBY_FAILOVER_STRESS_N", "0")) > 0,  # v2.3.0
                "source": "chains/providers.py",  # v2.2.0: Canonical source
            }
    except Exception as e:
        logger.debug("Provider stats unavailable: %s", e)
    
    # v2.2.0: Add dynamic anchor stats
    # v3.2.11: chain_key from config for chain-scoped anchor stats
    try:
        from strategy.dynamic_anchors import get_anchor_manager
        chain_key = config.get("chain") if config else None
        am = get_anchor_manager(chain_key=chain_key)
        anchor_stats = am.get_stats()
        if anchor_stats.get("total_pairs", 0) > 0:
            payload["dynamic_anchors"] = anchor_stats
    except Exception as e:
        logger.debug("Dynamic anchor stats unavailable: %s", e)
    
    # v2.2.0: Add multicall stats
    try:
        from core.multicall import get_aggregate_multicall_stats
        multicall_stats = get_aggregate_multicall_stats()
        if multicall_stats.get("calls_batched", 0) > 0:
            payload["multicall"] = multicall_stats
    except Exception:
        pass  # multicall not used yet
    
    return payload


# =============================================================================
# MULTI-PROVIDER ROUTER (v2.2.0)
# =============================================================================

class ProviderHealth:
    """Health tracking for a single RPC provider."""
    
    def __init__(self, provider_id: str, url: str):
        self.provider_id = provider_id
        self.url = url
        self.success_count = 0
        self.failure_count = 0
        self.consecutive_failures = 0
        self.total_latency_ms = 0
        self.last_success_time = 0.0
        self.last_failure_time = 0.0
        self.quarantined_until = 0.0
    
    @property
    def avg_latency_ms(self) -> float:
        if self.success_count == 0:
            return 0.0
        return self.total_latency_ms / self.success_count
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total
    
    @property
    def health_score(self) -> float:
        """Health score 0-1 (higher is better)."""
        import time
        
        # Check if quarantined
        if self.quarantined_until > time.time():
            return 0.0
        
        # Base score from success rate
        score = self.success_rate
        
        # Penalty for consecutive failures
        if self.consecutive_failures > 0:
            score *= 0.5 ** min(self.consecutive_failures, 3)
        
        return score


class MultiProviderRouter:
    """
    Routes RPC requests across multiple providers with health tracking.
    
    Features:
    - Health-based provider selection
    - Automatic failover
    - Quarantine for failing providers
    - Latency tracking
    """
    
    QUARANTINE_THRESHOLD = 3  # Consecutive failures before quarantine
    QUARANTINE_DURATION_SECONDS = 60
    
    def __init__(self):
        self._providers: Dict[str, ProviderHealth] = {}
        self._primary: Optional[str] = None
    
    def register_provider(self, provider_id: str, url: str, is_primary: bool = False) -> None:
        """Register an RPC provider."""
        self._providers[provider_id] = ProviderHealth(provider_id, url)
        if is_primary or self._primary is None:
            self._primary = provider_id
    
    def record_success(self, provider_id: str, latency_ms: int) -> None:
        """Record a successful request."""
        import time
        
        if provider_id not in self._providers:
            return
        
        p = self._providers[provider_id]
        p.success_count += 1
        p.total_latency_ms += latency_ms
        p.consecutive_failures = 0
        p.last_success_time = time.time()
    
    def record_failure(self, provider_id: str) -> None:
        """Record a failed request."""
        import time
        
        if provider_id not in self._providers:
            return
        
        p = self._providers[provider_id]
        p.failure_count += 1
        p.consecutive_failures += 1
        p.last_failure_time = time.time()
        
        # Auto-quarantine after threshold
        if p.consecutive_failures >= self.QUARANTINE_THRESHOLD:
            p.quarantined_until = time.time() + self.QUARANTINE_DURATION_SECONDS
            logger.warning(
                "Provider %s quarantined for %ds (consecutive failures: %d)",
                provider_id, self.QUARANTINE_DURATION_SECONDS, p.consecutive_failures
            )
    
    def get_best_provider(self) -> Optional[Tuple[str, str]]:
        """
        Get the best available provider.
        
        Returns:
            (provider_id, url) or None if no healthy providers
        """
        import time
        
        candidates = [
            (p.provider_id, p.url, p.health_score)
            for p in self._providers.values()
            if p.quarantined_until <= time.time()
        ]
        
        if not candidates:
            return None
        
        # Sort by health score (descending)
        candidates.sort(key=lambda x: x[2], reverse=True)
        return (candidates[0][0], candidates[0][1])
    
    def get_stats(self) -> Dict[str, Any]:
        """Get router statistics."""
        import time
        
        now = time.time()
        return {
            "providers_count": len(self._providers),
            "primary": self._primary,
            "providers": {
                p_id: {
                    "success_count": p.success_count,
                    "failure_count": p.failure_count,
                    "consecutive_failures": p.consecutive_failures,
                    "avg_latency_ms": round(p.avg_latency_ms, 1),
                    "success_rate": round(p.success_rate, 3),
                    "health_score": round(p.health_score, 3),
                    "quarantined": p.quarantined_until > now,
                }
                for p_id, p in self._providers.items()
            },
        }


# Singleton router
_provider_router: Optional[MultiProviderRouter] = None


def get_provider_router() -> MultiProviderRouter:
    """Get the singleton provider router."""
    global _provider_router
    if _provider_router is None:
        _provider_router = MultiProviderRouter()
    return _provider_router


def reset_provider_router() -> None:
    """Reset the singleton (for testing)."""
    global _provider_router
    _provider_router = None


# -- R28.11: WebSocket dirty-set block watcher --------------------------------


class DirtySetTracker:
    """Track which chains have new blocks via WebSocket subscription.

    Each chain gets a background thread that connects to its WSS endpoint
    and subscribes to ``newHeads``.  When a new block arrives the chain is
    marked *dirty* and the block event is enqueued.  The orchestrator can:

    * ``is_dirty(chain)``       — check if chain needs re-scan
    * ``pending_chains()``      — get all dirty chains ordered by arrival
    * ``drain_event(chain)``    — pop the latest block event for a chain
    * ``mark_clean(chain)``     — called after scan

    Chains without a WSS endpoint are always dirty (time-based fallback).

    R28.12: Upgraded from boolean dirty-flag to event queue with
    (chain, block_number, timestamp) events for immediate hot re-quote.
    """

    def __init__(self) -> None:
        import threading
        import collections
        self._lock = threading.Lock()
        # chain -> True if new block arrived since last mark_clean
        self._dirty: dict[str, bool] = {}
        # chain -> latest block number from WSS
        self._last_block: dict[str, int | None] = {}
        # chain -> deque of (block_number, timestamp) events since last mark_clean
        self._event_queue: dict[str, collections.deque] = {}
        # chain -> monotonic time of latest event (for priority ordering)
        self._last_event_time: dict[str, float] = {}
        # chain -> background thread
        self._threads: dict[str, threading.Thread] = {}
        # chain -> True if WSS is connected
        self._connected: dict[str, bool] = {}
        self._stop = threading.Event()
        # R38: Event for wait_for_dirty() — set when ANY chain becomes dirty
        self._dirty_event = threading.Event()

    # -- public API -----------------------------------------------------------

    def start_watching(self, chain: str, ws_url: str | None) -> None:
        """Begin watching a chain.  If *ws_url* is ``None`` the chain stays
        permanently dirty (no WebSocket available)."""
        import threading
        import collections
        with self._lock:
            self._dirty[chain] = True  # dirty until first scan
            self._connected[chain] = False
            self._last_block[chain] = None
            self._event_queue[chain] = collections.deque(maxlen=32)
            self._last_event_time[chain] = 0.0

        if not ws_url:
            return  # no WSS -> always dirty

        def _watch() -> None:
            self._ws_loop(chain, ws_url)

        t = threading.Thread(target=_watch, daemon=True, name=f"ws-{chain}")
        t.start()
        with self._lock:
            self._threads[chain] = t

    def is_dirty(self, chain: str) -> bool:
        """Return ``True`` if the chain should be scanned (new block or no WSS)."""
        with self._lock:
            # If WSS never connected, always dirty (can't track blocks)
            if not self._connected.get(chain, False):
                return True
            return self._dirty.get(chain, True)

    def pending_chains(self) -> list[str]:
        """Return dirty chains ordered by event arrival time (earliest first)."""
        with self._lock:
            dirty = [
                c for c, d in self._dirty.items()
                if d or not self._connected.get(c, False)
            ]
            # Sort by last_event_time so oldest-dirty chains get scanned first
            dirty.sort(key=lambda c: self._last_event_time.get(c, 0.0))
            return dirty

    def drain_event(self, chain: str) -> dict[str, Any] | None:
        """Pop the latest block event for a chain (for hot re-quote context)."""
        with self._lock:
            q = self._event_queue.get(chain)
            if q:
                block_num, ts = q[-1]  # latest event
                return {"block_number": block_num, "timestamp": ts}
            return None

    def mark_clean(self, chain: str) -> None:
        """Called after scanning — reset dirty flag and drain events."""
        with self._lock:
            self._dirty[chain] = False
            q = self._event_queue.get(chain)
            if q:
                q.clear()

    def wait_for_dirty(self, timeout: float | None = None) -> bool:
        """Block until at least one chain is dirty or *timeout* seconds elapse.

        R38: Event-driven replacement for ``time.sleep(sleep_seconds)`` in the
        orchestrator loop.  Returns ``True`` if a chain became dirty, ``False``
        on timeout.  If any chain is already dirty the call returns immediately.
        """
        # Fast path: already dirty
        with self._lock:
            if any(d for d in self._dirty.values()):
                return True
            # Also return True if any chain has no WS (always-dirty fallback)
            if any(not self._connected.get(c, False) for c in self._dirty):
                return True
        # Slow path: wait for _dirty_event from WS threads
        self._dirty_event.clear()
        return self._dirty_event.wait(timeout=timeout)

    def stop(self) -> None:
        """Signal all watcher threads to terminate."""
        self._stop.set()
        self._dirty_event.set()  # unblock any wait_for_dirty() caller

    def status(self) -> dict[str, Any]:
        """Return a snapshot of dirty-set state for observability."""
        with self._lock:
            return {
                "chains_watched": len(self._dirty),
                "chains_dirty": sum(1 for v in self._dirty.values() if v),
                "chains_ws_connected": sum(1 for v in self._connected.values() if v),
                "event_driven": True,  # R38: orchestrator uses wait_for_dirty()
                "per_chain": {
                    c: {
                        "dirty": self._dirty.get(c, True),
                        "ws_connected": self._connected.get(c, False),
                        "last_block": self._last_block.get(c),
                        "pending_events": len(self._event_queue.get(c, [])),
                    }
                    for c in self._dirty
                },
            }

    # -- internal WebSocket loop -----------------------------------------------

    def _ws_loop(self, chain: str, ws_url: str) -> None:
        """Background: connect to WSS, subscribe to newHeads, enqueue events."""
        import time as _time

        while not self._stop.is_set():
            try:
                import websocket as _wsclient
                ws = _wsclient.create_connection(ws_url, timeout=10)
                with self._lock:
                    self._connected[chain] = True

                # eth_subscribe newHeads
                subscribe_msg = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": ["newHeads"],
                })
                ws.send(subscribe_msg)
                # Read subscription confirmation
                ws.recv()

                logger.info("DirtySet: WSS connected for %s", chain)

                while not self._stop.is_set():
                    ws.settimeout(30)
                    try:
                        msg = ws.recv()
                    except Exception:
                        break  # reconnect on timeout/error
                    try:
                        data = json.loads(msg)
                        params = data.get("params", {})
                        result = params.get("result", {})
                        block_hex = result.get("number")
                        if block_hex:
                            block_num = int(block_hex, 16)
                            now = _time.monotonic()
                            with self._lock:
                                self._dirty[chain] = True
                                self._last_block[chain] = block_num
                                q = self._event_queue.get(chain)
                                if q is not None:
                                    q.append((block_num, now))
                                self._last_event_time[chain] = now
                            # R38: Wake orchestrator immediately on new block
                            self._dirty_event.set()
                    except (json.JSONDecodeError, ValueError):
                        pass

                ws.close()
            except Exception as e:
                logger.debug("DirtySet: WSS error for %s: %s (reconnect in 5s)", chain, e)
                # Connection lost — assume dirty (can't track blocks)
                with self._lock:
                    self._dirty[chain] = True
            finally:
                with self._lock:
                    self._connected[chain] = False

            if self._stop.is_set():
                break
            _time.sleep(5)  # backoff before reconnect


# -- R28.13: Per-pair hot queue (Step 7) ------------------------------------


class PairHotQueue:
    """Per-pair re-quote queue driven by block events from DirtySetTracker.

    When a chain gets a new block, all cached hot pairs for that chain are
    enqueued for immediate re-quote.  The orchestrator drains pairs and
    re-quotes them via the shared TPE without running a full child process.

    This is the architectural bridge between *batch-hot* (DirtySetTracker
    marks chain dirty → run full child) and *instant-hot* (per-pair re-quote
    on every block).

    Usage::

        pq = PairHotQueue()
        pq.load_pairs_for_chain("linea", pairs_list)
        pq.enqueue_chain("linea", block_number=12345)
        batch = pq.drain(max_items=10)
        # re-quote each (chain, pair, block) in batch
    """

    def __init__(self) -> None:
        import threading
        import collections
        self._lock = threading.Lock()
        # chain -> list of pair dicts (from hot_pairs_*.json)
        self._chain_pairs: dict[str, list[dict[str, Any]]] = {}
        # queue of (chain, pair_tag, block_number, enqueue_time) tuples
        self._queue: collections.deque = collections.deque(maxlen=500)
        # chain -> latest enqueued block (dedup)
        self._last_enqueued_block: dict[str, int] = {}

    def load_pairs_for_chain(self, chain: str, pairs: list[dict[str, Any]]) -> None:
        """Register hot pairs for a chain (from hot_pairs_{chain}.json)."""
        with self._lock:
            self._chain_pairs[chain] = list(pairs)

    def enqueue_chain(self, chain: str, block_number: int) -> int:
        """Enqueue all hot pairs for re-quote at given block.

        Returns number of pairs enqueued.  Deduplicates if same block
        already enqueued.
        """
        import time as _time
        with self._lock:
            if self._last_enqueued_block.get(chain) == block_number:
                return 0  # already enqueued for this block
            self._last_enqueued_block[chain] = block_number
            pairs = self._chain_pairs.get(chain, [])
            now = _time.monotonic()
            for p in pairs:
                tag = p.get("pair_tag") or p.get("display_name") or "?"
                self._queue.append((chain, tag, block_number, now))
            return len(pairs)

    def drain(self, max_items: int = 20) -> list[tuple[str, str, int]]:
        """Pop up to *max_items* (chain, pair_tag, block_number) from queue."""
        result = []
        with self._lock:
            while self._queue and len(result) < max_items:
                chain, tag, block, _ts = self._queue.popleft()
                result.append((chain, tag, block))
        return result

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    def get_pair_dicts(self, chain: str, pair_tags: set[str]) -> list[dict[str, Any]]:
        """Return full pair dicts for given tags from the loaded cache."""
        with self._lock:
            pairs = self._chain_pairs.get(chain, [])
            return [
                p for p in pairs
                if (p.get("pair_tag") or p.get("display_name") or "?") in pair_tags
            ]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "chains_loaded": len(self._chain_pairs),
                "total_pairs_loaded": sum(len(v) for v in self._chain_pairs.values()),
                "queue_depth": len(self._queue),
                "per_chain_pairs": {c: len(v) for c, v in self._chain_pairs.items()},
            }
