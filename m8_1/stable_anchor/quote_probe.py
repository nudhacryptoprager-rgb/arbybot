"""Exact-quote probing for stable-anchor routes.

Calls ``QuoterV2.quoteExactInputSingle`` (or equivalent) via ``eth_call``
and returns a :class:`QuoteResult`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from web3 import Web3
from core.rpc_rate_limiter import rpc_throttle
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute

# Function selectors
_V3_SELECTOR = bytes.fromhex("c6a5026a")
_SLIP_SELECTOR = bytes.fromhex("9e7defe6")  # quoteExactInputSingle((address,address,uint256,int24,uint160))
# V4 Quoter: quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))
# keccak256 computed: aa9d21cb
_V4_SELECTOR = bytes.fromhex("aa9d21cb")
_V4_ZERO_HOOKS = "0x" + "0" * 40  # zero address = vanilla pool
# Algebra dynamic-fee Quoter (Camelot V3, QuickSwap V3, ...):
# quoteExactInputSingle(address tokenIn, address tokenOut, uint256 amountIn, uint160 limitSqrtPrice)
#   returns (uint256 amountOut, uint16 fee)   ← fee is dynamic OUTPUT, never an input
# keccak256("quoteExactInputSingle(address,address,uint256,uint160)")[:4] = 2d9ebd1d
_ALGEBRA_SELECTOR = bytes.fromhex("2d9ebd1d")

_DEFAULT_RPC_CALL_TIMEOUT_S = float(os.environ.get("ARBY_M81_RPC_CALL_TIMEOUT_S", "12"))


def rpc_call_timeout_s() -> float:
    return _DEFAULT_RPC_CALL_TIMEOUT_S


def _eth_call(w3: Any, call_dict: dict) -> Any:
    """eth_call via Web3 HTTP provider request timeout (no thread-per-call)."""
    return w3.eth.call(call_dict)


@dataclass(frozen=True)
class QuoteResult:
    """Outcome of a single quote probe.

    On success: ``ok=True`` and ``amount_out > 0``.
    On failure: ``ok=False`` and ``reject_reason`` is set.
    """

    route_id: str
    size_usd: float
    amount_in: int
    amount_out: int
    ok: bool
    reject_reason: Optional[str]
    gas_estimate: Optional[int]
    raw_error: Optional[str]
    quote_target: Optional[str] = None
    quote_selector: Optional[str] = None
    quote_abi_path: Optional[str] = None
    quote_pool_id: Optional[str] = None


def size_usd_to_amount_in(token: TokenInfo, size_usd: float) -> int:
    """Convert a USD-denominated size to a raw ``amount_in`` for the token."""
    if size_usd <= 0:
        raise ValueError(f"size_usd must be positive: {size_usd}")
    # Assumes token price ≈ $1 for stablecoins; callers pass real price if needed
    return int(size_usd * (10 ** token.decimals))


def _encode_v3_call(token_in: str, token_out: str, amount_in: int, fee: int) -> str:
    """Encode QuoterV2.quoteExactInputSingle struct call."""
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    fee_bytes = fee.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    # QuoterV2 struct: (tokenIn, tokenOut, amountIn, fee, sqrtPriceLimitX96)
    payload = addr_in + addr_out + amount_bytes + fee_bytes + sqrt_limit
    return "0x" + _V3_SELECTOR.hex() + payload.hex()


def _encode_algebra_call(token_in: str, token_out: str, amount_in: int) -> str:
    """Encode Algebra dynamic-fee Quoter.quoteExactInputSingle call.

    Algebra (Camelot V3, QuickSwap V3) uses dynamic fees, so the quoter takes
    NO fee-tier argument: (tokenIn, tokenOut, amountIn, limitSqrtPrice).
    Returns (uint256 amountOut, uint16 fee); fee is an output, not an input.
    """
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    limit_sqrt = (0).to_bytes(32, "big")  # 0 = no price limit (full traversal)
    payload = addr_in + addr_out + amount_bytes + limit_sqrt
    return "0x" + _ALGEBRA_SELECTOR.hex() + payload.hex()


def _decode_algebra_response(hex_result: str) -> int:
    """Decode Algebra quoter response (uint256 amountOut, uint16 fee) → amount_out."""
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64:
        raise ValueError(f"algebra response too short: {len(raw)} hex chars")
    return int(raw[:64], 16)


def _encode_slipstream_call(
    token_in: str, token_out: str, amount_in: int, tick_spacing: int
) -> str:
    """Encode Slipstream Quoter.quoteExactInputSingle struct call."""
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    ts_bytes = tick_spacing.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    # Slipstream struct: (tokenIn, tokenOut, amountIn, tickSpacing, sqrtPriceLimitX96)
    payload = addr_in + addr_out + amount_bytes + ts_bytes + sqrt_limit
    return "0x" + _SLIP_SELECTOR.hex() + payload.hex()


def _decode_quote_response(hex_result: str) -> "tuple[int, Optional[int]]":
    """Decode the QuoterV2 / Slipstream Quoter response.

    Returns ``(amount_out, gas_estimate_or_None)``.
    """
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64:
        raise ValueError(f"response too short: {len(raw) // 2} bytes")
    amount_out = int(raw[:64], 16)
    gas_est: Optional[int] = None
    if len(raw) >= 128:
        gas_est = int(raw[64:128], 16)
    return amount_out, gas_est


def _v2_reserves_for_direction(
    reserve0: int,
    reserve1: int,
    token_in: TokenInfo,
    token_out: TokenInfo,
) -> tuple[int, int]:
    """Map V2 reserves from token0/token1 order to the requested quote direction."""
    addr_in = (token_in.address or "").lower()
    addr_out = (token_out.address or "").lower()
    if not addr_in or not addr_out or addr_in == addr_out:
        raise ValueError("invalid V2 token direction")
    return (reserve0, reserve1) if addr_in < addr_out else (reserve1, reserve0)


def _encode_v4_call(
    token_in: str, token_out: str, fee: int, tick_spacing: int,
    hooks: Optional[str], exact_amount: int
) -> str:
    """Encode V4 Quoter.quoteExactInputSingle call.

    V4 PoolKey = (currency0, currency1, fee, tickSpacing, hooks) — always sorted by address.
    zeroForOne = token_in < token_out (by address int value).
    """
    addr_in_int = int(token_in, 16)
    addr_out_int = int(token_out, 16)
    if addr_in_int < addr_out_int:
        currency0, currency1 = token_in, token_out
        zero_for_one = True
    else:
        currency0, currency1 = token_out, token_in
        zero_for_one = False
    hooks_addr = hooks if hooks else _V4_ZERO_HOOKS
    c0 = int(currency0, 16).to_bytes(32, "big")
    c1 = int(currency1, 16).to_bytes(32, "big")
    fee_b = fee.to_bytes(32, "big")
    ts_b = tick_spacing.to_bytes(32, "big", signed=True)
    hooks_b = int(hooks_addr, 16).to_bytes(32, "big")
    zfo_b = (1 if zero_for_one else 0).to_bytes(32, "big")
    amount_b = exact_amount.to_bytes(32, "big")
    # quoteExactInputSingle takes one QuoteExactSingleParams struct. Because
    # hookData is dynamic bytes, ABI encoding starts with a top-level offset to
    # the struct body; hookData offset is relative to that struct body.
    params_offset = (32).to_bytes(32, "big")
    # hookData offset = 8 * 32 = 256 (head: 8 static words before hookData length)
    hookdata_offset = (8 * 32).to_bytes(32, "big")
    hookdata_len = (0).to_bytes(32, "big")
    payload = c0 + c1 + fee_b + ts_b + hooks_b + zfo_b + amount_b + hookdata_offset + hookdata_len
    return "0x" + _V4_SELECTOR.hex() + (params_offset + payload).hex(), zero_for_one


def _decode_v4_response(hex_result: str, zero_for_one: bool) -> "tuple[int, Optional[int]]":
    """Decode V4 Quoter response: ``(uint256 amountOut, uint256 gasEstimate)``."""
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64:
        raise ValueError(f"V4 response too short: {len(raw) // 2} bytes")
    amount_out = int(raw[:64], 16)
    gas_estimate = int(raw[64:128], 16) if len(raw) >= 128 else None
    return amount_out, gas_estimate


def probe_quote(w3: Any, route: "DexRoute", token_in: "TokenInfo", token_out: "TokenInfo", amount_in: int) -> "QuoteResult":
    """Run a single quote via ``eth_call`` against ``route.quoter``."""
    route_id = f"{route.dex_id}:{token_in.symbol}-{token_out.symbol}@{route.fee}"
    try:
        # web3.py v6 requires checksum addresses for eth_call 'to' field
        quoter_addr = Web3.to_checksum_address(route.quoter)
        rpc_throttle.acquire(n=2)  # rate-limit: 2 tokens for eth_chainId + eth_call (web3 v6 pattern)
        if route.adapter_type in ("uniswap_v3",):
            calldata = _encode_v3_call(token_in.address, token_out.address, amount_in, route.fee)
            result = _eth_call(w3, {"to": quoter_addr, "data": calldata})
            amount_out, gas_est = _decode_quote_response(result.hex() if isinstance(result, bytes) else result)
        elif route.adapter_type == "algebra":
            # Algebra dynamic-fee quoter (Camelot V3 / QuickSwap V3): no fee-tier input.
            calldata = _encode_algebra_call(token_in.address, token_out.address, amount_in)
            result = _eth_call(w3, {"to": quoter_addr, "data": calldata})
            amount_out = _decode_algebra_response(result.hex() if isinstance(result, bytes) else result)
            gas_est = None
        elif route.adapter_type == "aerodrome_slipstream":
            if route.tick_spacing is None:
                raise ValueError("missing tick_spacing on slipstream route")
            calldata = _encode_slipstream_call(
                token_in.address, token_out.address, amount_in, route.tick_spacing
            )
            result = _eth_call(w3, {"to": quoter_addr, "data": calldata})
            amount_out, gas_est = _decode_quote_response(result.hex() if isinstance(result, bytes) else result)
        elif route.adapter_type == "aerodrome_v2_stable":
            # getAmountOut(uint amountIn, address tokenIn) selector: f140a35a
            addr_in_padded = int(token_in.address, 16).to_bytes(32, "big")
            amount_bytes = amount_in.to_bytes(32, "big")
            calldata = "0x" + "f140a35a" + amount_bytes.hex() + addr_in_padded.hex()
            result = _eth_call(w3, {"to": quoter_addr, "data": calldata})
            raw = result.hex() if isinstance(result, bytes) else result[2:]
            amount_out = int(raw[:64], 16)
            gas_est = None
        elif route.adapter_type == "curve_stable":
            # get_dy(i,j,dx) — indices come from config/adapter_metadata.yaml via route.
            # Fallback 0/1 is only safe for 2-pool USDC/USDT when no metadata loaded.
            idx_in = route.token_in_index if route.token_in_index is not None else 0
            idx_out = route.token_out_index if route.token_out_index is not None else 1
            # Curve has two incompatible get_dy ABIs: stable/plain uses
            # int128 indices (selector 5e0d443f), crypto/tricrypto uses uint256
            # indices (selector 556d6e9f). The wrong selector reverts (never
            # phantom). Select by declared pool_kind; unknown defaults to stable.
            _curve_selector = "556d6e9f" if route.pool_kind == "crypto" else "5e0d443f"
            calldata = "0x" + _curve_selector + idx_in.to_bytes(32, "big").hex() + idx_out.to_bytes(32, "big").hex() + amount_in.to_bytes(32, "big").hex()
            result = _eth_call(w3, {"to": quoter_addr, "data": calldata})
            raw = result.hex() if isinstance(result, bytes) else result[2:]
            amount_out = int(raw[:64], 16)
            gas_est = None
        elif route.adapter_type in ("balancer_stable", "balancer_weighted"):
            from dex.adapters.balancer_vault import BalancerVaultAdapter, BALANCER_VAULT_ADDRESS
            _vault = route.vault_address or BALANCER_VAULT_ADDRESS
            _pool_id = route.pool_id
            if not _pool_id:
                raise ValueError(
                    f"balancer route missing pool_id: {route_id}; "
                    "add pool_id to config/adapter_metadata.yaml"
                )
            _bv_adapter = BalancerVaultAdapter(w3, vault_address=_vault)
            _bv_result = _bv_adapter.get_quote(
                pool_id=_pool_id,
                token_in=token_in.address,
                token_out=token_out.address,
                amount_in=amount_in,
            )
            amount_out = _bv_result["amount_out"]
            gas_est = _bv_result.get("gas_estimate")
        elif route.adapter_type == "uniswap_v4":
            if route.tick_spacing is None:
                raise ValueError("missing tick_spacing on V4 route")
            hooks = getattr(route, "hooks", None)
            calldata, zero_for_one = _encode_v4_call(
                token_in.address, token_out.address, route.fee, route.tick_spacing,
                hooks, amount_in
            )
            result = _eth_call(w3, {"to": quoter_addr, "data": calldata})
            hex_res = result.hex() if isinstance(result, bytes) else result
            amount_out, gas_est = _decode_v4_response(hex_res, zero_for_one)
        elif route.adapter_type == "uniswap_v2":
            # getReserves() selector: 0902f1ac
            calldata = "0x0902f1ac"
            result = _eth_call(w3, {"to": quoter_addr, "data": calldata})
            raw = result.hex() if isinstance(result, bytes) else result
            if raw.startswith("0x"):
                raw = raw[2:]
            if len(raw) < 128:
                raise ValueError(f"getReserves too short: {len(raw)} hex chars")
            r0 = int(raw[:64], 16)
            r1 = int(raw[64:128], 16)
            reserve_in, reserve_out = _v2_reserves_for_direction(r0, r1, token_in, token_out)
            if reserve_in == 0 or reserve_out == 0:
                raise ValueError("zero reserves")
            # constant product formula
            amount_out = (amount_in * 997 * reserve_out) // (reserve_in * 1000 + amount_in * 997)
            gas_est = None
        elif route.adapter_type == "maverick_v2":
            # Maverick V2 directional bins: PoolInformation.calculateSwap(pool, amount,
            # tokenAIn, exactOutput, sqrtPriceLimit). route.quoter is the pool address
            # (set by builder.py). Direction (tokenAIn) is resolved via route.token_in_index
            # (0/1 when seeded from adapter_metadata.yaml token_a) or a live tokenA() lookup.
            from dex.adapters.maverick_v2 import MaverickV2Adapter
            _mv = MaverickV2Adapter(w3, enabled=True, dex_id=route.dex_id)
            _token_a_override: Optional[str] = None
            if route.token_in_index is not None:
                # token_in_index encodes tokenAIn flag: 1 ⇒ token_in IS tokenA.
                _token_a_override = token_in.address if route.token_in_index == 1 else token_out.address
            _mv_res = _mv.get_quote(
                pool_address=route.quoter,
                token_in=token_in.address,
                token_out=token_out.address,
                amount_in=amount_in,
                token_a_address=_token_a_override,
            )
            amount_out = _mv_res["amount_out"]
            gas_est = _mv_res.get("gas_estimate")
        else:
            raise ValueError(f"unsupported adapter_type: {route.adapter_type!r}")

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

    except Exception as exc:
        err_str = str(exc)
        if "execution reverted" in err_str or "revert" in err_str.lower():
            reject = "QUOTE_REVERT"
        elif "response too short" in err_str:
            reject = "QUOTE_DECODE"
        else:
            reject = "QUOTE_RPC_ERROR"
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
