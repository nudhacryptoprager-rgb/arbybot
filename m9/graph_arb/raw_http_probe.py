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
from core.rpc_dispatch_hooks import notify_rpc_dispatch
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
        notify_rpc_dispatch()
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
    *,
    leg_index: int = 0,
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

    quote_target: Optional[str] = None
    quote_selector: Optional[str] = None
    quote_abi_path: Optional[str] = None
    quote_pool_id: Optional[str] = None
    reported_amount_in = amount_in

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
            from dex.adapters.balancer_vault import BALANCER_VAULT_ADDRESS
            from m9.graph_arb.productive_distinct_quote import quote_balancer_productive

            _vault = route.vault_address or BALANCER_VAULT_ADDRESS
            _pool_id = route.pool_id
            _bal_assets = getattr(route, "balancer_assets", None)
            if not _pool_id or not _bal_assets:
                return QuoteResult(
                    route_id=route_id,
                    size_usd=0.0,
                    amount_in=amount_in,
                    amount_out=0,
                    ok=False,
                    reject_reason="BALANCER_METADATA_INCOMPLETE",
                    gas_estimate=None,
                    raw_error=(
                        "missing pool_id or balancer_assets; "
                        f"pool_id={_pool_id!r} assets={bool(_bal_assets)}"
                    ),
                )

            def _bal_call(to: str, data: str) -> str:
                return _eth_call_raw(rpc_url, to, data, client)

            _bal_balances = getattr(route, "balancer_balances", None)
            amount_out, _bal_debug = quote_balancer_productive(
                _bal_call,
                pool_id=_pool_id,
                token_in=token_in.address,
                token_out=token_out.address,
                amount_in=amount_in,
                vault=_vault,
                all_assets=_bal_assets,
                balances=_bal_balances,
                rpc_url=rpc_url,
            )
            gas_est = None
            quote_target = _bal_debug.get("quote_target")
            quote_selector = _bal_debug.get("quote_selector")
            quote_abi_path = _bal_debug.get("quote_abi_path")
            quote_pool_id = _bal_debug.get("quote_pool_id")

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
            from dex.adapters.maverick_v2 import _SELECTOR_TOKEN_A
            from m9.graph_arb.productive_distinct_quote import quote_maverick_productive

            pool_lc = route.quoter.lower()
            token_in_lc = token_in.address.lower()
            _token_a_addr: Optional[str] = None
            _ta_calldata = "0x" + _SELECTOR_TOKEN_A.hex()
            try:
                _ta_result = _eth_call_raw(rpc_url, pool_lc, _ta_calldata, client)
                _ta_raw = _ta_result[2:] if _ta_result.startswith("0x") else _ta_result
                _token_a_addr = ("0x" + _ta_raw[24:64]).lower()
            except Exception as _ta_exc:
                if route.token_in_index is None:
                    raise ValueError(
                        f"Maverick V2 tokenA() lookup failed for pool {pool_lc}: {_ta_exc}"
                    ) from _ta_exc

            _probe_tin = getattr(route, "maverick_pool_lane_token_in", None)
            _probe_tai = getattr(route, "maverick_token_a_in_probe", None)
            _min_raw = getattr(route, "maverick_min_quoteable_amount_raw", None)
            _pool_lane_probe = getattr(route, "maverick_pool_lane_probe_amount", None)
            _by_tin = getattr(route, "maverick_probe_by_token_in", None)
            if isinstance(_by_tin, dict) and token_in_lc not in _by_tin:
                from m9.graph_arb.quote_reject_classify import classify_maverick_no_probe_for_token_in

                reject, _detail = classify_maverick_no_probe_for_token_in(token_in_lc)
                return QuoteResult(
                    route_id=route_id,
                    size_usd=0.0,
                    amount_in=amount_in,
                    amount_out=0,
                    ok=False,
                    reject_reason=reject,
                    gas_estimate=None,
                    raw_error=str(_detail),
                )
            if isinstance(_by_tin, dict) and token_in_lc in _by_tin:
                row = _by_tin[token_in_lc] or {}
                _probe_tin = token_in_lc
                _probe_tai = row.get("maverick_token_a_in_probe")
                if _probe_tai is None:
                    _probe_tai = row.get("token_a_in")
                _min_raw = row.get("maverick_min_quoteable_amount_raw")
                _pool_lane_probe = row.get("maverick_pool_lane_probe_amount") or row.get(
                    "probe_amount"
                )
            elif _probe_tin and str(_probe_tin).lower() != token_in_lc:
                from m9.graph_arb.quote_reject_classify import classify_maverick_no_probe_for_token_in

                reject, _detail = classify_maverick_no_probe_for_token_in(token_in_lc)
                return QuoteResult(
                    route_id=route_id,
                    size_usd=0.0,
                    amount_in=amount_in,
                    amount_out=0,
                    ok=False,
                    reject_reason=reject,
                    gas_estimate=None,
                    raw_error=str(_detail),
                )
            if (
                _probe_tin
                and _probe_tai is not None
                and str(_probe_tin).lower() == token_in_lc
            ):
                token_a_in = bool(_probe_tai)
            elif route.token_in_index is not None:
                token_a_in = bool(route.token_in_index)
            elif _token_a_addr:
                token_a_in = token_in_lc == _token_a_addr
            else:
                token_a_in = True

            from m9.graph_arb.productive_distinct_quote import maverick_cycle_amount_in

            # Continuity-invariant: leg>0 amount was already resolved in quoter._probe_leg.
            if leg_index > 0:
                _effective_in = int(amount_in)
            else:
                _effective_in = maverick_cycle_amount_in(
                    amount_in,
                    pool_lane_probe_amount=_pool_lane_probe,
                    min_quoteable=_min_raw,
                    max_quoteable=getattr(route, "maverick_max_quoteable_amount_raw", None),
                    leg_index=0,
                    size_usd=getattr(route, "_cycle_size_usd", None),
                    token_in_decimals=token_in.decimals,
                )
            reported_amount_in = _effective_in

            def _mv_call(to: str, data: str) -> str:
                return _eth_call_raw(rpc_url, to, data, client)

            amount_out, gas_est, _mv_debug = quote_maverick_productive(
                _mv_call,
                pool_address=pool_lc,
                amount_in=_effective_in,
                token_a_in=token_a_in,
                chain="base",
                token_in=token_in_lc,
                token_a=_token_a_addr,
                pool_lane_probe_amount=_pool_lane_probe,
            )
            quote_target = _mv_debug.get("quote_target")
            quote_selector = _mv_debug.get("quote_selector")
            quote_abi_path = _mv_debug.get("quote_abi_path")
            quote_pool_id = _mv_debug.get("quote_pool_id")

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
                quote_target=quote_target,
                quote_selector=quote_selector,
                quote_abi_path=quote_abi_path,
                quote_pool_id=quote_pool_id,
            )

        from m9.graph_arb.stable_quote_guard import reject_toxic_stable_quote

        _toxic = reject_toxic_stable_quote(
            amount_in=int(reported_amount_in),
            amount_out=int(amount_out),
            token_in_decimals=token_in.decimals,
            token_out_decimals=token_out.decimals,
            token_in_sym=token_in.symbol,
            token_out_sym=token_out.symbol,
        )
        if _toxic:
            return QuoteResult(
                route_id=route_id,
                size_usd=0.0,
                amount_in=reported_amount_in,
                amount_out=0,
                ok=False,
                reject_reason=_toxic,
                gas_estimate=gas_est,
                raw_error=f"stable_ratio_outlier pool={route.quoter}",
                quote_target=quote_target,
                quote_selector=quote_selector,
                quote_abi_path=quote_abi_path,
                quote_pool_id=quote_pool_id,
            )

        return QuoteResult(
            route_id=route_id,
            size_usd=0.0,
            amount_in=reported_amount_in,
            amount_out=amount_out,
            ok=True,
            reject_reason=None,
            gas_estimate=gas_est,
            raw_error=None,
            quote_target=quote_target,
            quote_selector=quote_selector,
            quote_abi_path=quote_abi_path,
            quote_pool_id=quote_pool_id,
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
        from m9.graph_arb.quote_reject_classify import classify_quote_failure

        _bal_meta = bool(
            getattr(route, "pool_id", None)
            and getattr(route, "balancer_assets", None)
        )
        reject, _detail = classify_quote_failure(
            route.adapter_type,
            err_str,
            has_balancer_metadata=_bal_meta,
        )
        if reject == "QUOTE_RPC_ERROR" and "MAVERICK_ZERO_OUT" in err_str:
            reject = "QUOTE_ZERO_OUTPUT"
        elif reject == "QUOTE_RPC_ERROR" and (
            err_str.strip() in ("0x", "0x0")
            or err_str.strip().lower() == "empty eth_call result"
            or "empty/short result" in err_str.lower()
        ):
            if route.adapter_type == "maverick_v2":
                _max_raw = getattr(route, "maverick_max_quoteable_amount_raw", None)
                if _max_raw and int(amount_in) > int(_max_raw):
                    reject = "MAVERICK_PROBE_AMOUNT_OUT_OF_RANGE"
                else:
                    reject = "MAVERICK_NO_LIQUIDITY"
            else:
                reject = "QUOTE_REVERT"
        elif reject == "QUOTE_RPC_ERROR" and (
            "response too short" in err_str or "too short" in err_str.lower()
        ):
            reject = "QUOTE_DECODE"
        elif reject == "QUOTE_RPC_ERROR" and (
            "invalid v2 token direction" in err_str.lower()
            or "coin indices" in err_str.lower()
        ):
            reject = "QUOTE_CONFIG_MISSING"
        elif reject == "QUOTE_RPC_ERROR" and "zero reserves" in err_str.lower():
            reject = "QUOTE_REVERT"
        if _detail.get("balancer_code"):
            err_str = f"{err_str} [{_detail.get('balancer_reason', _detail['balancer_code'])}]"
        elif _detail.get("maverick_reason"):
            err_str = f"{err_str} [{_detail['maverick_reason']}]"
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
