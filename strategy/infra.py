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
    
    # Prefer resolved_http if available
    resolved_http_env = os.environ.get("ARBY_RPC_HTTP_PRIMARY")
    if resolved_http_env:
        if rpc_urls and rpc_urls[0] != resolved_http_env:
            rpc_urls = [resolved_http_env] + [u for u in rpc_urls if u != resolved_http_env]
        elif not rpc_urls:
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


def read_slot0_v3(pool_address: str, rpc_url: Optional[str], block_num: int) -> Tuple[Optional[int], Optional[int]]:
    """
    Read slot0() from a Uniswap V3 pool contract.
    
    Args:
        pool_address: Pool contract address
        rpc_url: RPC URL to use
        block_num: Block number to query at
        
    Returns:
        (tick, sqrtPriceX96) or (None, None) on failure
    """
    if not pool_address or not rpc_url:
        return None, None
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None, None
    
    try:
        from web3 import Web3
    except ImportError:
        logger.debug("slot0() skipped: web3 not installed")
        return None, None
    
    try:
        abi_path = Path(__file__).parent.parent / "dex" / "abi" / "uniswap_v3_pool.json"
        if not abi_path.exists():
            logger.debug("slot0() skipped: ABI not found at %s", abi_path)
            return None, None
        
        abi = json.loads(abi_path.read_text(encoding="utf8"))
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 5}))
        pool = w3.eth.contract(address=Web3.to_checksum_address(pool_address), abi=abi)
        slot0 = pool.functions.slot0().call(block_identifier=block_num)
        
        # slot0 returns: (sqrtPriceX96, tick, ...)
        sqrt_price_x96 = int(slot0[0])
        tick = int(slot0[1])
        logger.debug("slot0() success for %s: tick=%s, sqrtPriceX96=%s", pool_address, tick, sqrt_price_x96)
        return tick, sqrt_price_x96
    except Exception as e:
        logger.debug("slot0() read failed for %s: %s", pool_address, e)
        return None, None


def resolve_rpc_endpoints(config: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], str, str]:
    """
    Resolve HTTP and WS RPC endpoints.
    
    Args:
        config: Config with chain_id and network
        
    Returns:
        (http_url, ws_url, http_provider, ws_provider)
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
    
    if resolve_rpc_http:
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
                os.environ.setdefault("ARBY_RPC_WS_PRIMARY", resolved_ws)
                os.environ.setdefault("ARBY_RPC_WS_PROVIDER", provider_ws)
                os.environ.setdefault("ARBY_RPC_WS_HOST", urlparse(resolved_ws).netloc)
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
    try:
        from strategy.dynamic_anchors import get_anchor_manager
        am = get_anchor_manager()
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
