"""
chains/providers.py - RPC provider management with failover.

Provides reliable RPC access with:
- Multiple endpoint failover
- Request timeout handling
- Connection pooling
- Latency tracking
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

from core.logging import get_logger
from core.exceptions import InfraError, ErrorCode

logger = get_logger(__name__)

# Load environment variables
load_dotenv()


@dataclass
class RPCStats:
    """Statistics for an RPC endpoint."""
    url: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: int = 0
    last_error: str | None = None
    last_success_ts: int | None = None
    
    @property
    def avg_latency_ms(self) -> int:
        if self.successful_requests == 0:
            return 0
        return self.total_latency_ms // self.successful_requests
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests


@dataclass
class RPCResponse:
    """Response from an RPC call."""
    result: Any
    latency_ms: int
    endpoint_used: str
    block_number: int | None = None  # For calls that return block context


class RPCProvider:
    """
    RPC provider with failover support.
    
    Tries multiple endpoints in order until one succeeds.
    Tracks statistics per endpoint for monitoring.
    """
    
    def __init__(
        self,
        chain_id: int,
        rpc_urls: list[str],
        timeout_seconds: int = 10,
    ):
        self.chain_id = chain_id
        self.timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._request_id = 0
        
        # Resolve API keys in URLs
        self.rpc_urls = self._resolve_urls(rpc_urls)
        
        # Track stats per endpoint
        self.stats: dict[str, RPCStats] = {
            url: RPCStats(url=url) for url in self.rpc_urls
        }
    
    def _resolve_urls(self, urls: list[str]) -> list[str]:
        """Resolve environment variables in URLs."""
        api_key = os.getenv("ALCHEMY_API_KEY", "")
        resolved = []
        for url in urls:
            resolved_url = url.replace("${ALCHEMY_API_KEY}", api_key)
            # Only include if API key present or not needed
            if api_key or "alchemy" not in resolved_url.lower():
                resolved.append(resolved_url)
        return resolved
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                limits=httpx.Limits(max_connections=10),
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _next_request_id(self) -> int:
        """Generate next request ID."""
        self._request_id += 1
        return self._request_id
    
    async def call(
        self,
        method: str,
        params: list | None = None,
    ) -> RPCResponse:
        """
        Make an RPC call with failover.
        
        Args:
            method: RPC method name
            params: Method parameters
            
        Returns:
            RPCResponse with result and metadata
            
        Raises:
            InfraError: If all endpoints fail
        """
        if not self.rpc_urls:
            raise InfraError(
                code=ErrorCode.INFRA_RPC_ERROR,
                message="No RPC endpoints configured",
                details={"chain_id": self.chain_id},
            )
        
        client = await self._get_client()
        last_error: Exception | None = None
        
        for url in self.rpc_urls:
            stats = self.stats[url]
            stats.total_requests += 1
            
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or [],
                "id": self._next_request_id(),
            }
            
            start_ms = int(time.time() * 1000)
            
            try:
                resp = await client.post(url, json=payload)
                latency_ms = int(time.time() * 1000) - start_ms
                
                result = resp.json()
                
                if "error" in result:
                    error_msg = result["error"].get("message", str(result["error"]))
                    stats.failed_requests += 1
                    stats.last_error = error_msg
                    last_error = InfraError(
                        code=ErrorCode.INFRA_RPC_ERROR,
                        message=f"RPC error: {error_msg}",
                        details={"url": url, "method": method},
                    )
                    logger.debug(f"RPC error from {url}: {error_msg}")
                    continue
                
                # Success
                stats.successful_requests += 1
                stats.total_latency_ms += latency_ms
                stats.last_success_ts = int(time.time() * 1000)
                
                return RPCResponse(
                    result=result.get("result"),
                    latency_ms=latency_ms,
                    endpoint_used=url,
                )
                
            except httpx.TimeoutException as e:
                latency_ms = int(time.time() * 1000) - start_ms
                stats.failed_requests += 1
                stats.last_error = f"Timeout after {latency_ms}ms"
                last_error = e
                logger.debug(f"RPC timeout for {url}: {latency_ms}ms")
                continue
                
            except Exception as e:
                stats.failed_requests += 1
                stats.last_error = str(e)
                last_error = e
                logger.debug(f"RPC failed for {url}: {e}")
                continue
        
        # All endpoints failed
        raise InfraError(
            code=ErrorCode.INFRA_RPC_ERROR,
            message=f"All RPC endpoints failed for chain {self.chain_id}",
            details={
                "chain_id": self.chain_id,
                "endpoints_tried": len(self.rpc_urls),
                "last_error": str(last_error),
            },
        )
    
    async def get_chain_id(self) -> int:
        """Get chain ID from RPC."""
        response = await self.call("eth_chainId")
        return int(response.result, 16)
    
    async def get_block_number(self) -> tuple[int, int]:
        """
        Get latest block number.
        
        Returns:
            (block_number, latency_ms)
        """
        response = await self.call("eth_blockNumber")
        block_number = int(response.result, 16)
        return block_number, response.latency_ms
    
    async def eth_call(
        self,
        to: str,
        data: str,
        block: str = "latest",
    ) -> RPCResponse:
        """
        Make eth_call.
        
        Args:
            to: Contract address
            data: Encoded call data
            block: Block number or "latest"
            
        Returns:
            RPCResponse with call result
        """
        return await self.call(
            "eth_call",
            [{"to": to, "data": data}, block],
        )
    
    async def get_gas_price(self) -> tuple[int, int]:
        """
        Get current gas price in wei.
        
        Returns:
            (gas_price_wei, latency_ms)
        """
        response = await self.call("eth_gasPrice")
        gas_price_wei = int(response.result, 16)
        return gas_price_wei, response.latency_ms
    
    def get_stats_summary(self) -> dict:
        """Get statistics summary for all endpoints."""
        return {
            url: {
                "total_requests": s.total_requests,
                "success_rate": round(s.success_rate, 3),
                "avg_latency_ms": s.avg_latency_ms,
                "last_error": s.last_error,
            }
            for url, s in self.stats.items()
        }


class ProviderRegistry:
    """
    Registry of RPC providers by chain.
    
    Manages provider lifecycle and provides access by chain ID.
    """
    
    def __init__(self):
        self._providers: dict[int, RPCProvider] = {}
    
    def register(
        self,
        chain_id: int,
        rpc_urls: list[str],
        timeout_seconds: int = 10,
    ) -> RPCProvider:
        """Register a provider for a chain."""
        provider = RPCProvider(chain_id, rpc_urls, timeout_seconds)
        self._providers[chain_id] = provider
        return provider
    
    def get(self, chain_id: int) -> RPCProvider | None:
        """Get provider for a chain."""
        return self._providers.get(chain_id)
    
    async def close_all(self) -> None:
        """Close all providers."""
        for provider in self._providers.values():
            await provider.close()
        self._providers.clear()
    
    @property
    def chain_ids(self) -> list[int]:
        """List of registered chain IDs."""
        return list(self._providers.keys())


# Global registry instance
_registry = ProviderRegistry()


def get_provider(chain_id: int) -> RPCProvider | None:
    """Get provider from global registry."""
    return _registry.get(chain_id)


def register_provider(
    chain_id: int,
    rpc_urls: list[str],
    timeout_seconds: int = 10,
) -> RPCProvider:
    """Register provider in global registry."""
    return _registry.register(chain_id, rpc_urls, timeout_seconds)


async def close_all_providers() -> None:
    """Close all providers in global registry."""
    await _registry.close_all()
