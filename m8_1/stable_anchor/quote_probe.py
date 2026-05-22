"""Exact-quote probing for stable-anchor routes.

Calls ``QuoterV2.quoteExactInputSingle`` (or equivalent) via ``eth_call``
and returns a :class:`QuoteResult`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute

# Function selectors
_V3_SELECTOR = bytes.fromhex("c6a5026a")
_SLIP_SELECTOR = bytes.fromhex("f6c1b3d3")


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
    fee_bytes = fee.to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    payload = addr_in + addr_out + fee_bytes + (0).to_bytes(32, "big") + amount_bytes + sqrt_limit
    return "0x" + _V3_SELECTOR.hex() + (len(payload).to_bytes(32, "big")).hex() + payload.hex()


def _encode_slipstream_call(
    token_in: str, token_out: str, amount_in: int, tick_spacing: int
) -> str:
    """Encode Slipstream Quoter.quoteExactInputSingle struct call."""
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    ts_bytes = tick_spacing.to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    payload = addr_in + addr_out + ts_bytes + (0).to_bytes(32, "big") + amount_bytes + sqrt_limit
    return "0x" + _SLIP_SELECTOR.hex() + (len(payload).to_bytes(32, "big")).hex() + payload.hex()


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


def probe_quote(w3: Any, route: DexRoute, token_in: TokenInfo, token_out: TokenInfo, amount_in: int) -> QuoteResult:
    """Run a single quote via ``eth_call`` against ``route.quoter``."""
    route_id = f"{route.dex_id}:{token_in.symbol}-{token_out.symbol}@{route.fee}"
    try:
        if route.adapter_type in ("uniswap_v3",):
            calldata = _encode_v3_call(token_in.address, token_out.address, amount_in, route.fee)
            result = w3.eth.call({"to": route.quoter, "data": calldata})
            amount_out, gas_est = _decode_quote_response(result.hex() if isinstance(result, bytes) else result)
        elif route.adapter_type == "aerodrome_slipstream":
            if route.tick_spacing is None:
                raise ValueError("missing tick_spacing on slipstream route")
            calldata = _encode_slipstream_call(
                token_in.address, token_out.address, amount_in, route.tick_spacing
            )
            result = w3.eth.call({"to": route.quoter, "data": calldata})
            amount_out, gas_est = _decode_quote_response(result.hex() if isinstance(result, bytes) else result)
        elif route.adapter_type == "aerodrome_v2_stable":
            # getAmountOut(uint amountIn, address tokenIn) selector: f140a35a
            addr_in_padded = int(token_in.address, 16).to_bytes(32, "big")
            amount_bytes = amount_in.to_bytes(32, "big")
            calldata = "0x" + "f140a35a" + amount_bytes.hex() + addr_in_padded.hex()
            result = w3.eth.call({"to": route.quoter, "data": calldata})
            raw = result.hex() if isinstance(result, bytes) else result[2:]
            amount_out = int(raw[:64], 16)
            gas_est = None
        elif route.adapter_type == "curve_stable":
            # get_dy(i,j,dx) selector: 5e0d443f
            calldata = "0x" + "5e0d443f" + (0).to_bytes(32, "big").hex() + (1).to_bytes(32, "big").hex() + amount_in.to_bytes(32, "big").hex()
            result = w3.eth.call({"to": route.quoter, "data": calldata})
            raw = result.hex() if isinstance(result, bytes) else result[2:]
            amount_out = int(raw[:64], 16)
            gas_est = None
        elif route.adapter_type == "balancer_stable":
            raise NotImplementedError("balancer_stable quoter not yet implemented")
        elif route.adapter_type == "uniswap_v2":
            # getReserves() selector: 0902f1ac
            calldata = "0x0902f1ac"
            result = w3.eth.call({"to": route.quoter, "data": calldata})
            raw = result.hex() if isinstance(result, bytes) else result
            if raw.startswith("0x"):
                raw = raw[2:]
            if len(raw) < 128:
                raise ValueError(f"getReserves too short: {len(raw)} hex chars")
            r0 = int(raw[:64], 16)
            r1 = int(raw[64:128], 16)
            if r0 == 0 or r1 == 0:
                raise ValueError("zero reserves")
            # constant product formula
            amount_out = (amount_in * 997 * r1) // (r0 * 1000 + amount_in * 997)
            gas_est = None
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
