"""Raw HTTP probe for M9 graph-arb — direct JSON-RPC eth_call, no web3 overhead.

Eliminates the eth_chainId prefetch that web3 v7 injects before every eth_call,
cutting HTTP calls per probe from 2 to 1.  Uses per-thread httpx.Client for
connection reuse across parallel workers.

Public API:
    probe_quote_raw_http(rpc_url, route, token_in, token_out, amount_in) -> QuoteResult
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

import httpx

from core.provider_throttle import provider_throttle
from core.rpc_rate_limiter import rpc_throttle
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m8_1.stable_anchor.quote_probe import (
    QuoteResult,
    _decode_quote_response,
    _encode_slipstream_call,
    _encode_v3_call,
)

log = logging.getLogger(__name__)

# Thread-local httpx.Client for connection reuse per worker thread
_local = threading.local()

# Timeout for a single eth_call request (seconds)
_HTTP_TIMEOUT = 10.0


def _get_client() -> httpx.Client:
    """Return a thread-local httpx.Client, creating one if needed."""
    if not hasattr(_local, "client"):
        _local.client = httpx.Client(
            timeout=httpx.Timeout(_HTTP_TIMEOUT),
            headers={"Content-Type": "application/json"},
        )
    return _local.client


def _eth_call_raw(url: str, to: str, data: str, client: httpx.Client) -> str:
    """Send a single eth_call JSON-RPC request. Returns hex result string.

    Raises:
        httpx.HTTPStatusError: on HTTP 4xx/5xx (caller checks .response.status_code)
        ValueError: if JSON-RPC error returned in response body
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    resp = client.post(url, content=json.dumps(payload))
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        err = body["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise ValueError(f"eth_call error: {msg}")
    result = body.get("result") or "0x"
    return result


def probe_quote_raw_http(
    rpc_url: str,
    route: DexRoute,
    token_in: TokenInfo,
    token_out: TokenInfo,
    amount_in: int,
) -> QuoteResult:
    """Quote a single leg via direct JSON-RPC POST.

    Differences from ``probe_quote`` (web3 path):
    - Only 1 HTTP call per probe (no eth_chainId prefetch) → acquire(n=1)
    - 429 responses trigger provider_throttle breaker
    - Cooldown check via provider_throttle.acquire("calls") before sending
    """
    route_id = f"{route.dex_id}:{token_in.symbol}-{token_out.symbol}@{route.fee}"

    # Respect provider_throttle circuit-breaker (no-op when ARBY_PROVIDER_THROTTLE=0)
    if not provider_throttle.acquire("calls"):
        # Breaker is open: sleep for the cooldown duration instead of instantly
        # returning an error.  Without this, the sweep loop drains thousands of
        # queued calls as QUOTE_RPC_ERROR in milliseconds, producing misleading
        # metrics (e.g. "6000 errors" when only 8 HTTP 429s were received).
        _snap = provider_throttle.snapshot().get("calls", {})
        _cooldown_s = float(_snap.get("cooldown_remaining_s", 0.0))
        if _cooldown_s > 0.0:
            import time as _time
            _time.sleep(min(_cooldown_s, 60.0))  # cap at 60s per sleep call
        return QuoteResult(
            route_id=route_id,
            size_usd=0.0,
            amount_in=amount_in,
            amount_out=0,
            ok=False,
            reject_reason="QUOTE_RPC_ERROR",
            gas_estimate=None,
            raw_error="provider_throttle_cooldown",
        )

    try:
        rpc_throttle.acquire(n=1)  # 1 HTTP call per probe (no eth_chainId)
        client = _get_client()

        if route.adapter_type in ("uniswap_v3",):
            calldata = _encode_v3_call(
                token_in.address, token_out.address, amount_in, route.fee
            )
            hex_result = _eth_call_raw(rpc_url, route.quoter, calldata, client)
            amount_out, gas_est = _decode_quote_response(hex_result)

        elif route.adapter_type == "aerodrome_slipstream":
            if route.tick_spacing is None:
                raise ValueError("missing tick_spacing on slipstream route")
            calldata = _encode_slipstream_call(
                token_in.address, token_out.address, amount_in, route.tick_spacing
            )
            hex_result = _eth_call_raw(rpc_url, route.quoter, calldata, client)
            amount_out, gas_est = _decode_quote_response(hex_result)

        elif route.adapter_type in ("aerodrome_v2_stable", "ve33"):
            # getAmountOut(uint amountIn, address tokenIn) selector: f140a35a
            # ve33 / Solidly-style pools (aerodrome, stratum, etc.) use the same call.
            # route.quoter is set to pool_address by builder.py for these adapter types.
            addr_in_padded = int(token_in.address, 16).to_bytes(32, "big")
            amount_bytes = amount_in.to_bytes(32, "big")
            calldata = "0x" + "f140a35a" + amount_bytes.hex() + addr_in_padded.hex()
            hex_result = _eth_call_raw(rpc_url, route.quoter, calldata, client)
            raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
            amount_out = int(raw[:64], 16)
            gas_est = None

        elif route.adapter_type == "curve_stable":
            # get_dy(i,j,dx) selector: 5e0d443f
            calldata = (
                "0x"
                + "5e0d443f"
                + (0).to_bytes(32, "big").hex()
                + (1).to_bytes(32, "big").hex()
                + amount_in.to_bytes(32, "big").hex()
            )
            hex_result = _eth_call_raw(rpc_url, route.quoter, calldata, client)
            raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
            amount_out = int(raw[:64], 16)
            gas_est = None

        elif route.adapter_type == "uniswap_v2":
            # getReserves() selector: 0902f1ac
            hex_result = _eth_call_raw(rpc_url, route.quoter, "0x0902f1ac", client)
            raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
            if len(raw) < 128:
                raise ValueError(f"getReserves too short: {len(raw)} hex chars")
            r0 = int(raw[:64], 16)
            r1 = int(raw[64:128], 16)
            if r0 == 0 or r1 == 0:
                raise ValueError("zero reserves")
            amount_out = (amount_in * 997 * r1) // (r0 * 1000 + amount_in * 997)
            gas_est = None

        elif route.adapter_type == "balancer_stable":
            raise NotImplementedError("balancer_stable quoter not yet implemented")

        else:
            raise ValueError(f"unsupported adapter_type: {route.adapter_type!r}")

        # Success feedback to provider_throttle
        provider_throttle.record_response("calls", ok=True)

        if amount_out == 0:
            return QuoteResult(
                route_id=route_id,
                size_usd=0.0,
                amount_in=amount_in,
                amount_out=0,
                ok=False,
                reject_reason="QUOTE_ZERO_OUTPUT",
                gas_estimate=None,
                raw_error=None,
            )
        return QuoteResult(
            route_id=route_id,
            size_usd=0.0,
            amount_in=amount_in,
            amount_out=amount_out,
            ok=True,
            reject_reason=None,
            gas_estimate=gas_est,
            raw_error=None,
        )

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        provider_throttle.record_response("calls", status_code=status_code, ok=False)
        reject = "QUOTE_RPC_ERROR"
        return QuoteResult(
            route_id=route_id,
            size_usd=0.0,
            amount_in=amount_in,
            amount_out=0,
            ok=False,
            reject_reason=reject,
            gas_estimate=None,
            raw_error=f"HTTP {status_code}: {str(exc)[:180]}",
        )

    except Exception as exc:
        err_str = str(exc)
        if "execution reverted" in err_str or "revert" in err_str.lower():
            reject = "QUOTE_REVERT"
        elif "response too short" in err_str or "too short" in err_str.lower():
            reject = "QUOTE_DECODE"
        else:
            reject = "QUOTE_RPC_ERROR"
        # Only trigger circuit-breaker for actual network-level failures.
        # ValueError (execution revert, decode error, bad ABI) and NotImplementedError
        # (unsupported adapter type) are code/data errors — not HTTP errors — and
        # must NOT increment the consecutive-failure counter.  Doing so causes the
        # breaker to open prematurely and block all subsequent calls.
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError)):
            provider_throttle.record_response("calls", ok=False)
        return QuoteResult(
            route_id=route_id,
            size_usd=0.0,
            amount_in=amount_in,
            amount_out=0,
            ok=False,
            reject_reason=reject,
            gas_estimate=None,
            raw_error=err_str[:200],
        )
