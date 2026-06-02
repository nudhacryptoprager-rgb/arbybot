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
import time
from typing import Any, Optional

import httpx

from core.provider_throttle import provider_throttle
from core.rpc_rate_limiter import rpc_throttle
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m8_1.stable_anchor.quote_probe import (
    QuoteResult,
    _decode_algebra_response,
    _decode_quote_response,
    _decode_v4_response,
    _encode_algebra_call,
    _encode_slipstream_call,
    _encode_v3_call,
    _encode_v4_call,
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


def _eth_call_raw(
    url: str,
    to: str,
    data: str,
    client: httpx.Client,
    *,
    max_retries: int = 3,
    base_retry_delay_s: float = 1.0,
) -> str:
    """Send a single eth_call JSON-RPC request. Returns hex result string.

    Retries HTTP 429 with exponential backoff (same policy as pool_verifier).

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
    last_exc: httpx.HTTPStatusError | None = None
    for attempt in range(max_retries):
        resp = client.post(url, content=json.dumps(payload))
        if resp.status_code == 429:
            if attempt + 1 < max_retries:
                time.sleep(base_retry_delay_s * (2**attempt))
                continue
            resp.raise_for_status()
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if (
                exc.response is not None
                and exc.response.status_code == 429
                and attempt + 1 < max_retries
            ):
                time.sleep(base_retry_delay_s * (2**attempt))
                continue
            raise
        break
    else:
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("eth_call retry loop exhausted")
    body = resp.json()
    if "error" in body:
        err = body["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise ValueError(f"eth_call error: {msg}")
    result = body.get("result") or "0x"

    # Guard: detect ABI-encoded revert data masquerading as a successful result.
    # Standard revert selectors: Error(string)=0x08c379a0, Panic(uint256)=0x4e487b71.
    # Any valid return value for our adapters is ≥ 32 bytes (64 hex chars after "0x").
    result_hex = result[2:] if result.startswith("0x") else result
    if len(result_hex) < 64:
        raise ValueError(f"eth_call empty/short result: {result!r}")
    if result_hex[:8].lower() in {"08c379a0", "4e487b71"}:
        raise ValueError(f"eth_call ABI-revert detected: {result[:20]}")

    return result


def _v2_reserves_for_direction(
    reserve0: int,
    reserve1: int,
    token_in: TokenInfo,
    token_out: TokenInfo,
) -> tuple[int, int]:
    """Map V2 reserves to the requested swap direction.

    UniswapV2-like pairs store reserves as token0/token1, where token0 is the
    lower token address. Graph edges may be quoted in either direction, so the
    raw reserve order cannot be used blindly.
    """
    addr_in = (token_in.address or "").lower()
    addr_out = (token_out.address or "").lower()
    if not addr_in or not addr_out or addr_in == addr_out:
        raise ValueError("invalid V2 token direction")
    return (reserve0, reserve1) if addr_in < addr_out else (reserve1, reserve0)


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

        elif route.adapter_type == "algebra":
            # Algebra dynamic-fee quoter (Camelot V3 / QuickSwap V3): no fee-tier input.
            # route.quoter is the Algebra QuoterV2 address (set by builder.py from dexes.yaml).
            calldata = _encode_algebra_call(token_in.address, token_out.address, amount_in)
            hex_result = _eth_call_raw(rpc_url, route.quoter, calldata, client)
            amount_out = _decode_algebra_response(hex_result)
            gas_est = None

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
            # get_dy(i,j,dx) — indices MUST come from adapter_metadata.yaml via route.
            # If indices are missing, we must NOT fall back to 0/1: wrong indices cause
            # phantom gains (ABI-revert data decoded as amount_out).
            if route.token_in_index is None or route.token_out_index is None:
                raise ValueError(
                    f"curve_stable pool {route.quoter} has no coin indices in "
                    "adapter_metadata.yaml — add it before enabling this pool"
                )
            idx_in = route.token_in_index
            idx_out = route.token_out_index
            # Curve has TWO incompatible get_dy ABIs:
            #   stable/plain pools: get_dy(int128,int128,uint256)  selector 5e0d443f
            #   crypto/tricrypto pools: get_dy(uint256,uint256,uint256) selector 556d6e9f
            # Using the int128 selector on a crypto pool (or vice-versa) reverts.
            # Select by declared pool_kind; unknown/None defaults to the stable ABI
            # (a wrong selector reverts — it never produces a phantom amount_out).
            if route.pool_kind == "crypto":
                _curve_selector = "556d6e9f"
            else:
                _curve_selector = "5e0d443f"
            calldata = (
                "0x"
                + _curve_selector
                + idx_in.to_bytes(32, "big").hex()
                + idx_out.to_bytes(32, "big").hex()
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
            reserve_in, reserve_out = _v2_reserves_for_direction(r0, r1, token_in, token_out)
            if reserve_in == 0 or reserve_out == 0:
                raise ValueError("zero reserves")
            amount_out = (amount_in * 997 * reserve_out) // (reserve_in * 1000 + amount_in * 997)
            gas_est = None

        elif route.adapter_type in ("balancer_stable", "balancer_weighted"):
            # Balancer queryBatchSwap — requires pool_id from config/adapter_metadata.yaml.
            from dex.adapters.balancer_vault import BALANCER_VAULT_ADDRESS
            _vault = route.vault_address or BALANCER_VAULT_ADDRESS
            _pool_id = route.pool_id
            if not _pool_id:
                return QuoteResult(
                    route_id=route_id,
                    size_usd=0.0,
                    amount_in=amount_in,
                    amount_out=0,
                    ok=False,
                    reject_reason="QUOTE_CONFIG_MISSING__BALANCER_POOL_ID",
                    gas_estimate=None,
                    raw_error="route.pool_id is None; add to config/adapter_metadata.yaml",
                )
            from dex.adapters.balancer_vault import _encode_query_batch_swap, _decode_query_batch_swap
            _vault_addr = _vault if _vault.startswith("0x") else "0x" + _vault
            _calldata_bytes = _encode_query_batch_swap(_pool_id, token_in.address, token_out.address, amount_in)
            _calldata_hex = "0x" + _calldata_bytes.hex()
            hex_result = _eth_call_raw(rpc_url, _vault_addr, _calldata_hex, client)
            _, amount_out = _decode_query_batch_swap(hex_result)
            gas_est = None

        elif route.adapter_type == "uniswap_v4":
            if route.tick_spacing is None:
                raise ValueError("missing tick_spacing on V4 route")
            hooks = getattr(route, "hooks", None)
            calldata, zero_for_one = _encode_v4_call(
                token_in.address, token_out.address, route.fee, route.tick_spacing,
                hooks, amount_in
            )
            hex_result = _eth_call_raw(rpc_url, route.quoter, calldata, client)
            amount_out, gas_est = _decode_v4_response(hex_result, zero_for_one)

        elif route.adapter_type == "maverick_v2":
            # PoolInformation.calculateSwap(pool, amount, tokenAIn, exactOutput, sqrtPriceLimit)
            # Selector: 0x2764cd0b  (keccak256("calculateSwap(address,uint128,bool,bool,uint256)")[:4])
            # route.quoter is set to pool_address by builder.py for maverick_v2.
            # route.token_in_index is repurposed as token_a_in flag (1=True, 0=False)
            # when set by bridge_builder from adapter_metadata.yaml token_a field.
            from dex.adapters.maverick_v2 import (
                MAVERICK_V2_POOL_INFO_ADDRESS,
                _encode_calculate_swap,
                _decode_calculate_swap,
                _SELECTOR_TOKEN_A,
            )
            pool_lc = route.quoter.lower()
            token_in_lc = token_in.address.lower()

            # Determine tokenAIn direction.
            # If token_in_index is explicitly set (0=False, 1=True), use it directly.
            # Otherwise, fetch tokenA() from the pool to determine direction.
            token_a_in: bool
            if route.token_in_index is not None:
                token_a_in = bool(route.token_in_index)
            else:
                # Live tokenA() lookup: GET tokenA address from pool contract
                _ta_calldata = "0x" + _SELECTOR_TOKEN_A.hex()
                try:
                    _ta_result = _eth_call_raw(rpc_url, pool_lc, _ta_calldata, client)
                    _ta_raw = _ta_result[2:] if _ta_result.startswith("0x") else _ta_result
                    _token_a_addr = "0x" + _ta_raw[24:64]
                    token_a_in = token_in_lc == _token_a_addr.lower()
                except Exception as _ta_exc:
                    raise ValueError(
                        f"Maverick V2 tokenA() lookup failed for pool {pool_lc}: {_ta_exc}"
                    ) from _ta_exc

            calldata = _encode_calculate_swap(
                pool_address=pool_lc,
                amount_in=amount_in,
                token_a_in=token_a_in,
            )
            hex_result = _eth_call_raw(rpc_url, MAVERICK_V2_POOL_INFO_ADDRESS, calldata, client)
            amount_out, _ = _decode_calculate_swap(hex_result)
            gas_est = None

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
