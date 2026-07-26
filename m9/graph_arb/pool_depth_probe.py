"""Pool depth probe \u2014 measures effective on-chain depth for inventory routes (Step 1).

Writes ``effective_depth_usd`` and ``price_impact_at_100usd`` fields into each
active_route entry in the inventory. These fields enable the M9 productive lane
filter (``--productive-lane --min-effective-depth-usd <N>``) in the runner.

Algorithm per pool:
  1. Fetch slot0 (sqrtPriceX96) via Multicall snapshot \u2192 compute spot price.
  2. Call QuoterV2.quoteExactInputSingle at $100 USD equivalent amount.
  3. Compare actual output vs expected spot output.
  4. price_impact_at_100usd = 1 - (actual_out / expected_out)
  5. effective_depth_usd = $100 if impact < IMPACT_THRESHOLD else lower estimate.

Usage::

    py -3.11 -m m9.graph_arb.pool_depth_probe \\
        --chain base \\
        --inventory data/tmp/m9_verified_inventory.json \\
        --output data/tmp/m9_depth_enriched_inventory.json

    # Optionally write results to quarantine for thin pools:
    py -3.11 -m m9.graph_arb.pool_depth_probe \\
        --chain base \\
        --inventory data/tmp/m9_verified_inventory.json \\
        --update-quarantine data/quarantine/m9_pool_depth_quarantine.json \\
        --impact-threshold 0.50
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_DEPTH_PROBE_CACHE = None


def _depth_probe_cache():
    global _DEPTH_PROBE_CACHE
    if _DEPTH_PROBE_CACHE is None:
        from m9.graph_arb.depth_cache import DepthProbeCache

        _DEPTH_PROBE_CACHE = DepthProbeCache(ttl_s=90.0)
    return _DEPTH_PROBE_CACHE

# Default first rung of the iterative depth ladder (see depth_capacity_probe).
_PROBE_SIZE_USD = 100.0
# Impact threshold above which a pool is considered TOXIC
_IMPACT_THRESHOLD_TOXIC = 0.50
# Impact threshold above which a pool is LOW_EFFECTIVE_DEPTH
_IMPACT_THRESHOLD_LOW = 0.10

# V3 QuoterV2 selector: quoteExactInputSingle((address,address,uint256,uint24,uint160))
_V3_SELECTOR = bytes.fromhex("c6a5026a")
# Slipstream Quoter selector: quoteExactInputSingle((address,address,uint256,int24,uint160))
_SLIP_SELECTOR = bytes.fromhex("9e7defe6")
# ve33 pool selector: getAmountOut(uint256 amountIn, address tokenIn) -> uint256
_VE33_GET_AMOUNT_OUT_SELECTOR = bytes.fromhex("f140a35a")
# UniswapV2 pool selector: getReserves() -> (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast)
_V2_GET_RESERVES_SELECTOR = bytes.fromhex("0902f1ac")
# V4 Quoter selector: quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))
# keccak256("quoteExactInputSingle((PoolKey,bool,uint128,bytes))") = aa9d21cb
_V4_SELECTOR = bytes.fromhex("aa9d21cb")
# V4 zero-hooks address (vanilla pool with no hooks)
_V4_ZERO_HOOKS: str = "0x" + "0" * 40
# Adapter type sets for routing
_VE33_ADAPTER_TYPES = frozenset({
    "ve33",
    "ve33_stable",
    "ve33_volatile",
    "solidly_stable",
    "solidly_volatile",
    "aerodrome_stable",
    "aerodrome_v2_stable",
})
_V2_FORK_ADAPTER_TYPES = frozenset({"uniswap_v2", "sushiswap_v2", "baseswap_v2"})
_DEFAULT_V2_FEE_BPS = 30
# Per-adapter-type default fee map for V2 forks.
# Used when neither `fee` nor `fee_bps` field is present in the route metadata.
# Keeps probe math independent of field presence without a hard 30 bps fallback for all.
_V2_FORK_FEE_BPS_MAP: Dict[str, int] = {
    "uniswap_v2": 30,
    "sushiswap_v2": 30,
    "baseswap_v2": 30,
}
_FEE_DENOMINATOR_BPS = 10_000

_V3_LIQUIDITY_SELECTOR = "0x1a686502"
_V3_SLOT0_SELECTOR = "0x3850c7bd"


def _resolve_probe_price(
    sym: str,
    addr: str = "",
    price_map: Optional[Dict[str, float]] = None,
) -> tuple[float, str]:
    """Config baseline → price_map → $1 fallback; records source for artifacts."""
    from m9.graph_arb.token_price_fetcher import resolve_token_price_usd

    if price_map:
        px = resolve_token_price_usd(addr, sym, price_map)
        if px is not None and float(px) > 0:
            return float(px), "price_map"
    from m9.graph_arb.token_price_fetcher import _baseline_prices

    baseline = _baseline_prices()
    if sym in baseline and float(baseline[sym]) > 0:
        return float(baseline[sym]), "config_baseline"
    return 1.0, "unit_fallback"


def _encode_ve33_amount_out(amount_in: int, token_in: str) -> str:
    """Encode getAmountOut(uint256 amountIn, address tokenIn) calldata for ve33 pools."""
    amount_bytes = amount_in.to_bytes(32, "big")
    token_bytes = int(token_in, 16).to_bytes(32, "big")
    return "0x" + _VE33_GET_AMOUNT_OUT_SELECTOR.hex() + amount_bytes.hex() + token_bytes.hex()


def _v2_amount_out_from_reserves(
    pool_address: str,
    addr_in: str,
    addr_out: str,
    amount_in: int,
    rpc_url: str,
    fee_bps: int = _DEFAULT_V2_FEE_BPS,
) -> Optional[int]:
    """Compute V2-fork amountOut from getReserves() via xy=k formula."""
    if fee_bps < 0 or fee_bps >= _FEE_DENOMINATOR_BPS:
        return None
    calldata = "0x" + _V2_GET_RESERVES_SELECTOR.hex()
    hex_result = _raw_eth_call(rpc_url, pool_address, calldata)
    if not hex_result or hex_result == "0x":
        return None
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 192:  # 3 x 32 bytes
        return None
    r0 = int(raw[:64], 16)
    r1 = int(raw[64:128], 16)
    if r0 == 0 or r1 == 0:
        return None
    # UniV2 sorts tokens: token0 is lower address
    if int(addr_in, 16) < int(addr_out, 16):
        reserve_in, reserve_out = r0, r1
    else:
        reserve_in, reserve_out = r1, r0
    fee_multiplier = _FEE_DENOMINATOR_BPS - int(fee_bps)
    numerator = amount_in * fee_multiplier * reserve_out
    denominator = reserve_in * _FEE_DENOMINATOR_BPS + amount_in * fee_multiplier
    if denominator == 0:
        return None
    return numerator // denominator


def _route_v2_fee_bps(route: Dict[str, Any]) -> int:
    """Resolve V2-fork fee bps from route metadata.

    Priority: route['fee'] > route['fee_bps'] > per-adapter map > global default.
    """
    fee = int(route.get("fee") or 0)
    if fee > 0:
        return fee
    fee_bps = route.get("fee_bps")
    if fee_bps is not None:
        return int(float(fee_bps))
    adapter_type = route.get("adapter_type", "")
    return _V2_FORK_FEE_BPS_MAP.get(adapter_type, _DEFAULT_V2_FEE_BPS)


def _encode_v3_call(token_in: str, token_out: str, amount_in: int, fee: int) -> str:
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    fee_bytes = fee.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    payload = addr_in + addr_out + amount_bytes + fee_bytes + sqrt_limit
    return "0x" + _V3_SELECTOR.hex() + payload.hex()


def _encode_v4_call_depth(
    token_in: str, token_out: str, fee: int, tick_spacing: int,
    hooks: Optional[str], exact_amount: int
) -> "tuple[str, bool]":
    """Encode V4 Quoter.quoteExactInputSingle call for depth probe.

    V4 PoolKey = (currency0, currency1, fee, tickSpacing, hooks) — sorted by address.
    Returns (calldata_hex, zero_for_one).
    """
    addr_in_int = int(token_in, 16)
    addr_out_int = int(token_out, 16)
    if addr_in_int < addr_out_int:
        currency0, currency1 = token_in, token_out
        zero_for_one = True
    else:
        currency0, currency1 = token_out, token_in
        zero_for_one = False
    hooks_addr = hooks if (hooks and hooks != _V4_ZERO_HOOKS) else _V4_ZERO_HOOKS
    c0 = int(currency0, 16).to_bytes(32, "big")
    c1 = int(currency1, 16).to_bytes(32, "big")
    fee_b = fee.to_bytes(32, "big")
    ts_b = tick_spacing.to_bytes(32, "big", signed=True)
    hooks_b = int(hooks_addr, 16).to_bytes(32, "big")
    zfo_b = (1 if zero_for_one else 0).to_bytes(32, "big")
    amount_b = exact_amount.to_bytes(32, "big")
    # quoteExactInputSingle takes one QuoteExactSingleParams struct. Because
    # that struct contains dynamic bytes, ABI encoding starts with a top-level
    # offset to the struct body; hookData offset is relative to the struct body.
    params_offset = (32).to_bytes(32, "big")
    hookdata_offset = (8 * 32).to_bytes(32, "big")  # offset to hookData ABI field
    hookdata_len = (0).to_bytes(32, "big")            # empty hookData
    payload = c0 + c1 + fee_b + ts_b + hooks_b + zfo_b + amount_b + hookdata_offset + hookdata_len
    return "0x" + _V4_SELECTOR.hex() + (params_offset + payload).hex(), zero_for_one


def _decode_v4_response_depth(hex_result: str, zero_for_one: bool) -> int:
    """Decode V4 Quoter response ``(uint256 amountOut, uint256 gasEstimate)``."""
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64:
        raise ValueError(f"V4 response too short: {len(raw) // 2} bytes")
    return int(raw[:64], 16)


def _encode_slipstream_call(
    token_in: str, token_out: str, amount_in: int, tick_spacing: int
) -> str:
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    ts_bytes = tick_spacing.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    payload = addr_in + addr_out + amount_bytes + ts_bytes + sqrt_limit
    return "0x" + _SLIP_SELECTOR.hex() + payload.hex()


def _decode_quote_response(hex_result: str) -> int:
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64:
        raise ValueError(f"response too short: {len(raw) // 2} bytes")
    return int(raw[:64], 16)


def _raw_eth_call(rpc_url: str, to: str, data: str) -> Optional[str]:
    """Send raw eth_call via httpx (no web3 dependency)."""
    try:
        import httpx
    except ImportError:
        import urllib.request
        import urllib.error

        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": to, "data": data}, "latest"],
                "id": 1,
            }
        ).encode()
        req = urllib.request.Request(
            rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                return body.get("result")
        except Exception as exc:
            log.debug("urllib eth_call failed: %s", exc)
            return None

    try:
        body = httpx.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": to, "data": data}, "latest"],
                "id": 1,
            },
            timeout=10,
        ).json()
        return body.get("result")
    except Exception as exc:
        log.debug("httpx eth_call failed: %s", exc)
        return None


def probe_pool_depth(
    route: Dict[str, Any],
    config_tokens: Dict[str, Any],
    rpc_url: str,
    probe_size_usd: float = _PROBE_SIZE_USD,
    spot_price_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    """Measure effective depth for a single inventory route.

    Returns a dict with:
    - effective_depth_usd: USD amount tradeable at < IMPACT_THRESHOLD_LOW impact
    - price_impact_at_100usd: fraction 0-1 (0 = no impact, 1 = total loss)
    - probe_ok: True if quote succeeded
    - probe_error: error string if failed
    - probe_amount_in: raw amount_in used
    - probe_amount_out: raw amount_out received
    - depth_reject_reason: null | LOW_EFFECTIVE_DEPTH | TOXIC_PRICE_IMPACT
    """
    pair_id = route.get("pair_id", "")
    dex_id = route.get("dex_id", "")
    fee = int(route.get("fee") or 0)
    adapter_type = route.get("adapter_type", "uniswap_v3")
    tick_spacing = route.get("tick_spacing")
    quoter = route.get("quoter_addr", "") or ""
    pool_address = route.get("pool_address", "")

    result: Dict[str, Any] = {
        "effective_depth_usd": None,
        "price_impact_at_100usd": None,
        "probe_ok": False,
        "probe_error": None,
        "probe_amount_in": None,
        "probe_amount_out": None,
        "depth_reject_reason": None,
    }

    # For ve33 and v2 forks, the pool itself is the quoter; fall back to pool_address
    if adapter_type in _VE33_ADAPTER_TYPES or adapter_type in _V2_FORK_ADAPTER_TYPES:
        if not quoter or quoter == "0x" + "0" * 40:
            quoter = pool_address
    if adapter_type == "maverick_v2" and pool_address:
        quoter = pool_address

    if (
        adapter_type
        not in ("maverick_v2", "balancer_vault", "balancer_stable", "balancer_weighted")
        and (not quoter or quoter == "0x" + "0" * 40)
    ):
        result["probe_error"] = "NO_QUOTER"
        return result

    # Parse pair symbols
    parts = pair_id.split("_")
    if len(parts) != 2:
        result["probe_error"] = f"BAD_PAIR_ID:{pair_id}"
        return result
    sym0, sym1 = parts[0], parts[1]

    t0 = config_tokens.get(sym0)
    t1 = config_tokens.get(sym1)
    if not t0 or not t1:
        result["probe_error"] = f"UNKNOWN_TOKEN:{sym0}|{sym1}"
        return result

    dec0 = t0.get("decimals", 18)
    dec1 = t1.get("decimals", 18)
    addr0 = t0.get("address", "")
    addr1 = t1.get("address", "")

    price0, price0_source = _resolve_probe_price(sym0, addr0)
    amount_in = int(probe_size_usd / price0 * (10 ** dec0))

    if amount_in <= 0:
        result["probe_error"] = "ZERO_AMOUNT_IN"
        return result

    result["probe_amount_in"] = amount_in

    # Encode calldata or compute amount_out directly (for v2 forks via getReserves)
    amount_out_precomputed: Optional[int] = None
    calldata: Optional[str] = None
    _v4_zero_for_one: Optional[bool] = None
    try:
        if adapter_type in _VE33_ADAPTER_TYPES:
            calldata = _encode_ve33_amount_out(amount_in, addr0)
        elif adapter_type in _V2_FORK_ADAPTER_TYPES:
            pool_addr_for_probe = pool_address or quoter
            amount_out_precomputed = _v2_amount_out_from_reserves(
                pool_addr_for_probe,
                addr0,
                addr1,
                amount_in,
                rpc_url,
                fee_bps=_route_v2_fee_bps(route),
            )
            if amount_out_precomputed is None:
                result["probe_error"] = "V2_RESERVES_FAILED"
                return result
            if amount_out_precomputed == 0:
                result["probe_error"] = "ZERO_AMOUNT_OUT"
                return result
        elif adapter_type == "aerodrome_slipstream" and tick_spacing:
            calldata = _encode_slipstream_call(addr0, addr1, amount_in, int(tick_spacing))
        elif adapter_type == "uniswap_v4":
            if not tick_spacing:
                result["probe_error"] = "V4_MISSING_TICK_SPACING"
                return result
            hooks = route.get("hooks")
            calldata, _v4_zero_for_one = _encode_v4_call_depth(
                addr0, addr1, fee, int(tick_spacing), hooks, amount_in
            )
        else:
            calldata = _encode_v3_call(addr0, addr1, amount_in, fee)
    except Exception as exc:
        result["probe_error"] = f"ENCODE_ERROR:{exc}"
        return result

    if amount_out_precomputed is not None:
        # v2 forks: reserves-based computation, no RPC quoter call needed
        amount_out = amount_out_precomputed
    else:
        # Call quoter (v3, slipstream, ve33, v4)
        if not calldata:
            result["probe_error"] = "NO_CALLDATA"
            return result
        hex_result = _raw_eth_call(rpc_url, quoter, calldata)
        if not hex_result or hex_result == "0x":
            result["probe_error"] = "QUOTE_FAILED_OR_REVERT"
            return result
        try:
            if _v4_zero_for_one is not None:
                # V4: use dedicated decoder that handles int128[] deltaAmounts
                amount_out = _decode_v4_response_depth(hex_result, _v4_zero_for_one)
            else:
                amount_out = _decode_quote_response(hex_result)
        except Exception as exc:
            result["probe_error"] = f"DECODE_ERROR:{exc}"
            return result
        if amount_out == 0:
            result["probe_error"] = "ZERO_AMOUNT_OUT"
            return result

    result["probe_amount_out"] = amount_out
    result["probe_ok"] = True

    # V2 forks: analytical reserve depth (supplements single-rung probe).
    if adapter_type in _V2_FORK_ADAPTER_TYPES:
        try:
            from m9.graph_arb.depth_capacity_probe import (
                DEPTH_PROBE_MEASURED_CAPACITY,
                merge_depth_with_analytical,
                v2_analytical_depth_usd,
            )

            calldata = "0x" + _V2_GET_RESERVES_SELECTOR.hex()
            hex_result = route.get("_v2_reserves_cached") or _raw_eth_call(
                rpc_url, pool_address or quoter, calldata
            )
            if hex_result and hex_result != "0x":
                raw = hex_result[2:] if str(hex_result).startswith("0x") else hex_result
                if len(raw) >= 128:
                    r0, r1 = int(raw[:64], 16), int(raw[64:128], 16)
                    if int(addr0, 16) < int(addr1, 16):
                        rin = r0
                    else:
                        rin = r1
                    analytical = v2_analytical_depth_usd(
                        rin, dec0, price0, fee_bps=_route_v2_fee_bps(route)
                    )
                    if analytical > 0:
                        result["probe_ok"] = True
                        result["effective_depth_usd"] = analytical
                        result["depth_probe_status"] = DEPTH_PROBE_MEASURED_CAPACITY
                        result["depth_method"] = "v2_reserves_analytical"
                        result["depth_price_source"] = price0_source
                        result["price_impact_at_100usd"] = 0.0
                        return result
        except Exception:
            pass

    # Compute impact: compare actual output to expected from spot
    price1, _ = _resolve_probe_price(sym1, addr1)
    expected_out_units = probe_size_usd / price1
    expected_out_raw = expected_out_units * (10 ** dec1)
    if expected_out_raw > 0:
        actual_ratio = amount_out / expected_out_raw
        impact = max(1.0 - actual_ratio, 0.0)
        from m9.graph_arb.depth_capacity_probe import finalize_marginal_depth

        finalized = finalize_marginal_depth(
            impact, probe_size_usd, at_max_ladder_rung=True
        )
        result.update(finalized)
        result["depth_price_source"] = price0_source
    else:
        result["probe_error"] = "ZERO_EXPECTED_OUT"

    return result


# ---------------------------------------------------------------------------
# M8 long-tail depth enrichment (package #8)
#
# M8-sniped routes carry their own on-chain token addresses (token0_addr /
# token1_addr) but the *exotic* leg has no entry in config tokens and no known
# USD price, so probe_pool_depth() cannot enrich them. Instead we measure depth
# with a price-agnostic two-point marginal probe: quote a tiny reference size and
# a probe size FROM THE ANCHOR SIDE, then compare the realised marginal rates.
# The exotic token's USD price and decimals cancel in the rate ratio, so we only
# need the anchor's price/decimals (always known) plus the exotic token address.
# ---------------------------------------------------------------------------

# Anchor token decimals (Base). Used to size the anchor-side probe amount.
_ANCHOR_DECIMALS: Dict[str, int] = {
    "WETH": 18,
    "WETH_BASE": 18,
    "USDC": 6,
    "EURC": 6,
    "DAI": 18,
    "USDT": 6,
    "cbBTC": 8,
}

# Default reference size (USD) for the near-spot marginal rate.
_REF_SIZE_USD = 2.0


def compute_marginal_depth(
    ref_in: int,
    ref_out: int,
    probe_in: int,
    probe_out: int,
    probe_size_usd: float,
    impact_threshold_low: float = _IMPACT_THRESHOLD_LOW,
    impact_threshold_toxic: float = _IMPACT_THRESHOLD_TOXIC,
    *,
    at_max_ladder_rung: bool = True,
) -> Dict[str, Any]:
    """Price-agnostic depth from a two-point marginal quote.

    A tiny reference quote (``ref``) establishes the near-spot marginal rate, and
    the probe-size quote measures the realised rate. Price impact at probe size is
    the relative degradation of the marginal rate::

        rate_ref   = ref_out  / ref_in
        rate_probe = probe_out / probe_in
        impact     = 1 - rate_probe / rate_ref   (clamped to >= 0)

    Both the exotic token's USD price and its decimals cancel in the rate ratio,
    so this needs neither for the output token. Returns the same field shape as
    ``probe_pool_depth`` so it can be written directly onto a route entry.
    """
    from m9.graph_arb.depth_capacity_probe import finalize_marginal_depth, marginal_impact

    result: Dict[str, Any] = {
        "effective_depth_usd": None,
        "price_impact_at_100usd": None,
        "probe_ok": False,
        "probe_error": None,
        "depth_reject_reason": None,
        "depth_method": "marginal_anchor",
        "depth_probe_status": None,
    }
    if ref_in <= 0 or probe_in <= 0:
        result["probe_error"] = "ZERO_AMOUNT_IN"
        return result
    if ref_out <= 0 or probe_out <= 0:
        result["probe_error"] = "ZERO_AMOUNT_OUT"
        return result

    impact = marginal_impact(ref_in, ref_out, probe_in, probe_out)
    if impact is None:
        result["probe_error"] = "ZERO_SPOT_RATE"
        return result

    finalized = finalize_marginal_depth(
        impact,
        probe_size_usd,
        at_max_ladder_rung=at_max_ladder_rung,
        impact_threshold_low=impact_threshold_low,
        impact_threshold_toxic=impact_threshold_toxic,
    )
    result.update(finalized)
    return result


def _anchor_leg(route: Dict[str, Any]) -> Optional[tuple]:
    """Return (anchor_sym, anchor_addr, exotic_addr) or None if no anchor leg."""
    sym0 = route.get("token0") or ""
    sym1 = route.get("token1") or ""
    addr0 = route.get("token0_addr") or ""
    addr1 = route.get("token1_addr") or ""
    if sym0 in _ANCHOR_DECIMALS:
        return (sym0, addr0, addr1)
    if sym1 in _ANCHOR_DECIMALS:
        return (sym1, addr1, addr0)
    return None


def probe_route_marginal_depth(
    route: Dict[str, Any],
    rpc_url: str,
    dex_quoters: Optional[Dict[str, str]] = None,
    probe_size_usd: float = _PROBE_SIZE_USD,
    ref_size_usd: float = _REF_SIZE_USD,
    price_map: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Measure depth for one M8 long-tail route via anchor-side marginal probe.

    Walks an ascending USD ladder ($100→$50k) with optional binary refinement.
    Uses the route's embedded token addresses so exotic tokens absent from config
    still probe correctly. Returns the same field shape as ``probe_pool_depth``.
    """
    from m9.graph_arb.depth_capacity_probe import (
        PROBE_LADDER_USD,
        binary_refine_capacity_usd,
        finalize_marginal_depth,
        marginal_impact,
        merge_depth_with_analytical,
        merge_ladder_results,
        probe_ladder_usd_for_impact,
        v2_analytical_depth_usd,
        v3_liquidity_depth_lower_bound_usd,
    )

    dex_quoters = dex_quoters or {}
    result: Dict[str, Any] = {
        "effective_depth_usd": None,
        "price_impact_at_100usd": None,
        "probe_ok": False,
        "probe_error": None,
        "depth_reject_reason": None,
        "depth_method": "marginal_anchor_ladder",
        "depth_probe_status": None,
    }

    adapter_type = route.get("adapter_type", "uniswap_v3")

    leg = _anchor_leg(route)
    if leg is None:
        result["probe_error"] = "NO_ANCHOR_FOR_DEPTH"
        return result
    anchor_sym, anchor_addr, exotic_addr = leg
    if not anchor_addr or not exotic_addr:
        result["probe_error"] = "MISSING_TOKEN_ADDR"
        return result

    anchor_dec = _ANCHOR_DECIMALS[anchor_sym]
    anchor_price, price_source = _resolve_probe_price(anchor_sym, anchor_addr, price_map)
    pool_address = route.get("pool_address", "") or ""
    from m9.graph_arb.depth_cache import depth_cache_key

    cache_key = depth_cache_key(
        chain=str(route.get("chain") or "base"),
        dex_id=str(route.get("dex_id") or ""),
        pool_address=pool_address,
        token_in=anchor_addr,
        token_out=exotic_addr,
        block_number=route.get("block_number") or route.get("depth_block_number"),
    )
    cached = _depth_probe_cache().get(cache_key)
    if cached is not None:
        return dict(cached)

    ref_in = int(ref_size_usd / anchor_price * (10 ** anchor_dec))
    if ref_in <= 0:
        result["probe_error"] = "ZERO_AMOUNT_IN"
        return result

    pool_address = route.get("pool_address", "") or ""
    quoter = route.get("quoter_addr", "") or dex_quoters.get(route.get("dex_id", ""), "")
    fee = int(route.get("fee") or 0)
    tick_spacing = route.get("tick_spacing")

    def _quote(amount_in: int) -> Optional[int]:
        try:
            if adapter_type == "maverick_v2":
                if not pool_address:
                    return None
                from m9.graph_arb.productive_distinct_quote import quote_maverick_productive

                token_a = str(
                    route.get("token_a") or route.get("token_a_address") or ""
                ).lower()
                token_in = anchor_addr.lower()
                token_a_in = bool(token_a and token_in == token_a)

                def _eth_call_mav(to: str, data: str) -> str:
                    return _raw_eth_call(rpc_url, to, data)

                amount_out, _gas, _dbg = quote_maverick_productive(
                    _eth_call_mav,
                    pool_address=pool_address,
                    amount_in=int(amount_in),
                    token_a_in=token_a_in,
                    token_in=token_in,
                    token_a=token_a or None,
                )
                if not amount_out:
                    amount_out, _gas, _dbg = quote_maverick_productive(
                        _eth_call_mav,
                        pool_address=pool_address,
                        amount_in=int(amount_in),
                        token_a_in=not token_a_in,
                        token_in=token_in,
                        token_a=token_a or None,
                    )
                return int(amount_out) if amount_out else None
            if adapter_type == "curve_stable":
                idx_in = route.get("token_in_index")
                idx_out = route.get("token_out_index")
                pool = pool_address or quoter
                if idx_in is None or idx_out is None or not pool:
                    return None
                pool_kind = route.get("pool_kind") or route.get("curve_pool_kind")
                selector = "556d6e9f" if pool_kind == "crypto" else "5e0d443f"
                calldata = (
                    "0x"
                    + selector
                    + int(idx_in).to_bytes(32, "big").hex()
                    + int(idx_out).to_bytes(32, "big").hex()
                    + int(amount_in).to_bytes(32, "big").hex()
                )
                hexr = _raw_eth_call(rpc_url, pool, calldata)
                if not hexr or hexr == "0x":
                    return None
                raw = hexr[2:] if hexr.startswith("0x") else hexr
                return int(raw[:64], 16)
            if adapter_type in (
                "balancer_vault",
                "balancer_stable",
                "balancer_weighted",
            ):
                pool_id = route.get("pool_id")
                assets = route.get("balancer_assets")
                if not pool_id or not assets:
                    return None
                from m9.graph_arb.productive_distinct_quote import quote_balancer_productive

                def _eth_call_bal(to: str, data: str) -> str:
                    return _raw_eth_call(rpc_url, to, data)

                amount_out, _dbg = quote_balancer_productive(
                    _eth_call_bal,
                    pool_id=str(pool_id),
                    token_in=anchor_addr,
                    token_out=exotic_addr,
                    amount_in=int(amount_in),
                    all_assets=list(assets),
                    balances=list(route.get("balancer_balances") or []),
                    rpc_url=rpc_url,
                )
                return int(amount_out) if amount_out else None
            if adapter_type in _VE33_ADAPTER_TYPES:
                target = quoter or pool_address
                if not target:
                    return None
                calldata = _encode_ve33_amount_out(amount_in, anchor_addr)
                hexr = _raw_eth_call(rpc_url, target, calldata)
                if not hexr or hexr == "0x":
                    return None
                return _decode_quote_response(hexr)
            if adapter_type in _V2_FORK_ADAPTER_TYPES:
                target = pool_address or quoter
                if not target:
                    return None
                return _v2_amount_out_from_reserves(
                    target, anchor_addr, exotic_addr, amount_in, rpc_url,
                    fee_bps=_route_v2_fee_bps(route),
                )
            if adapter_type == "aerodrome_slipstream" and tick_spacing:
                if not quoter:
                    return None
                calldata = _encode_slipstream_call(
                    anchor_addr, exotic_addr, amount_in, int(tick_spacing)
                )
                hexr = _raw_eth_call(rpc_url, quoter, calldata)
                if not hexr or hexr == "0x":
                    return None
                return _decode_quote_response(hexr)
            if adapter_type == "uniswap_v4":
                if not quoter or not tick_spacing:
                    return None
                hooks = route.get("hooks")
                v4_calldata, v4_zfo = _encode_v4_call_depth(
                    anchor_addr, exotic_addr, fee, int(tick_spacing), hooks, amount_in
                )
                hexr = _raw_eth_call(rpc_url, quoter, v4_calldata)
                if not hexr or hexr == "0x":
                    return None
                return _decode_v4_response_depth(hexr, v4_zfo)
            # default: v3-family quoter
            if not quoter:
                return None
            calldata = _encode_v3_call(anchor_addr, exotic_addr, amount_in, fee)
            hexr = _raw_eth_call(rpc_url, quoter, calldata)
            if not hexr or hexr == "0x":
                return None
            return _decode_quote_response(hexr)
        except Exception as exc:  # noqa: BLE001 - normalise to probe error
            log.debug("marginal quote failed: %s", exc)
            return None

    if (
        adapter_type not in _VE33_ADAPTER_TYPES
        and adapter_type not in _V2_FORK_ADAPTER_TYPES
        and adapter_type != "uniswap_v4"
        and adapter_type != "maverick_v2"
        and adapter_type
        not in ("balancer_vault", "balancer_stable", "balancer_weighted")
        and not quoter
    ):
        result["probe_error"] = "NO_QUOTER"
        return result

    ref_out = _quote(ref_in)
    if ref_out is None:
        result["probe_error"] = "REF_QUOTE_FAILED"
        return result

    def _amount_in_for_usd(usd: float) -> int:
        return int(usd / anchor_price * (10 ** anchor_dec))

    def _quote_usd(usd: float) -> Optional[Tuple[int, int]]:
        amt_in = _amount_in_for_usd(usd)
        if amt_in <= 0:
            return None
        out = _quote(amt_in)
        if out is None:
            return None
        return amt_in, out

    first_probe = _quote_usd(float(PROBE_LADDER_USD[0]))
    first_impact: Optional[float] = None
    if first_probe is not None:
        probe_in, probe_out = first_probe
        first_impact = marginal_impact(ref_in, ref_out, probe_in, probe_out)

    ladder = list(
        probe_ladder_usd_for_impact(
            first_impact,
            thin_candidate=bool(route.get("thin_liquidity_candidate")),
        )
    )
    if probe_size_usd not in ladder:
        ladder = sorted(set(ladder + [float(probe_size_usd)]))

    rung_results: List[Dict[str, Any]] = []
    prev_low_usd: Optional[float] = None
    for idx, rung_usd in enumerate(ladder):
        quoted = _quote_usd(rung_usd)
        if quoted is None:
            if idx == 0:
                result["probe_error"] = "PROBE_QUOTE_FAILED"
                return result
            break
        probe_in, probe_out = quoted
        impact = marginal_impact(ref_in, ref_out, probe_in, probe_out)
        if impact is None:
            if idx == 0:
                result["probe_error"] = "PROBE_QUOTE_FAILED"
                return result
            break
        at_max = idx == len(ladder) - 1
        rung = finalize_marginal_depth(impact, rung_usd, at_max_ladder_rung=at_max)
        rung["probe_amount_in"] = probe_in
        rung["probe_amount_out"] = probe_out
        rung_results.append(rung)
        if impact > _IMPACT_THRESHOLD_LOW and prev_low_usd is not None:
            refined = binary_refine_capacity_usd(
                prev_low_usd,
                rung_usd,
                lambda u: _quote_usd(u),
                ref_in,
                ref_out,
            )
            rung["effective_depth_usd"] = refined
            rung["depth_method"] = "marginal_anchor_ladder_bsearch"
        if impact > _IMPACT_THRESHOLD_LOW:
            break
        prev_low_usd = rung_usd

    depth = merge_ladder_results(rung_results)
    depth["depth_price_source"] = price_source
    if rung_results:
        last = rung_results[-1]
        depth["probe_amount_in"] = last.get("probe_amount_in")
        depth["probe_amount_out"] = last.get("probe_amount_out")

    # V2 analytical depth from reserves (anchor-side input).
    if adapter_type in _V2_FORK_ADAPTER_TYPES:
        try:
            calldata = "0x" + _V2_GET_RESERVES_SELECTOR.hex()
            hex_result = route.get("_v2_reserves_cached") or _raw_eth_call(
                rpc_url, pool_address or quoter, calldata
            )
            if hex_result and hex_result != "0x":
                raw = hex_result[2:] if str(hex_result).startswith("0x") else hex_result
                if len(raw) >= 128:
                    r0, r1 = int(raw[:64], 16), int(raw[64:128], 16)
                    if int(anchor_addr, 16) < int(exotic_addr, 16):
                        rin = r0
                    else:
                        rin = r1
                    analytical = v2_analytical_depth_usd(
                        rin, anchor_dec, anchor_price, fee_bps=_route_v2_fee_bps(route)
                    )
                    depth = merge_depth_with_analytical(
                        depth, analytical, analytical_method="v2_reserves"
                    )
        except Exception:
            pass

    # V3 / Slipstream / V4: conservative liquidity lower bound (quote ladder validates).
    if adapter_type in ("uniswap_v3", "aerodrome_slipstream") and pool_address:
        try:
            liq_hex = _raw_eth_call(rpc_url, pool_address, _V3_LIQUIDITY_SELECTOR)
            slot_hex = _raw_eth_call(rpc_url, pool_address, _V3_SLOT0_SELECTOR)
            if liq_hex and slot_hex and liq_hex != "0x" and slot_hex != "0x":
                liq_raw = int(liq_hex, 16)
                slot_raw = slot_hex[2:] if slot_hex.startswith("0x") else slot_hex
                sqrt_x96 = int(slot_raw[:64], 16)
                cl_bound = v3_liquidity_depth_lower_bound_usd(
                    liq_raw, sqrt_x96, anchor_dec, anchor_price
                )
                depth = merge_depth_with_analytical(
                    depth, cl_bound, analytical_method="v3_liquidity_bound"
                )
        except Exception:
            pass

    from m9.graph_arb.depth_capacity_probe import mark_analytical_depth_suspect

    depth = mark_analytical_depth_suspect(depth)
    _depth_probe_cache().set(cache_key, depth)
    return depth


def select_false_positive_reprobe_routes(
    routes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Routes needing prioritized ladder reprobe (false-positive depth cap band)."""
    from m9.graph_arb.quarantine_depth_rca import is_false_positive_toxic_depth

    selected: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for route in routes:
        rid = str(route.get("route_id") or "")
        if not rid or rid in seen:
            continue
        if route.get("depth_reprobe_required"):
            selected.append(route)
            seen.add(rid)
            continue
        if is_false_positive_toxic_depth(route):
            selected.append(route)
            seen.add(rid)
    return selected


def enrich_routes_missing_depth(
    routes: List[Dict[str, Any]],
    rpc_url: str,
    dex_quoters: Optional[Dict[str, str]] = None,
    probe_size_usd: float = _PROBE_SIZE_USD,
    ref_size_usd: float = _REF_SIZE_USD,
    sleep_s: float = 0.1,
    force_reprobe: bool = False,
    prioritized_reprobe_only: bool = False,
) -> Dict[str, int]:
    """Fill ``effective_depth_usd`` for routes that still lack it (M8 long-tail).

    Only routes where ``effective_depth_usd`` is None and a ``pool_address`` is
    present are probed; already-enriched base routes are left untouched. Mutates
    each probed route in place and returns funnel counts.

    When ``force_reprobe`` is enabled, legacy rows are also re-probed if they
    have an existing depth value but no ``depth_probe_status``. Rows with
    explicit post-ladder depth status stay untouched, even if the measured
    value happens to equal the first ladder rung.

    When ``prioritized_reprobe_only`` is set, only false-positive / reprobe-required
    routes are walked with ``force_reprobe``.
    """
    if prioritized_reprobe_only:
        routes = select_false_positive_reprobe_routes(routes)
        force_reprobe = True
    counts = {
        "candidates": 0,
        "force_reprobe_candidates": 0,
        "probed_ok": 0,
        "probe_failed": 0,
        "no_anchor": 0,
        "toxic": 0,
        "low_depth": 0,
        "skipped_v4": 0,
        "v4_depth_candidates": 0,
        "v4_depth_probe_ok": 0,
        "v4_depth_probe_failed": 0,
        "multicall_saved_calls_estimate": 0,
    }
    if os.environ.get("ARBY_DEPTH_USE_MULTICALL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    ):
        counts["multicall_saved_calls_estimate"] = _multicall_prefetch_v2_reserves(
            routes, rpc_url, include_existing=force_reprobe
        )
    _w3_distinct = None
    _prices_distinct: Dict[str, float] = {}
    try:
        from web3 import Web3

        from m9.graph_arb.token_price_fetcher import build_dual_key_price_map

        _w3_distinct = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))
        _prices_distinct = build_dual_key_price_map({})
    except Exception:
        pass
    counts["distinct_depth_ok"] = 0
    for route in routes:
        existing_depth = route.get("effective_depth_usd")
        legacy_depth_row = (
            existing_depth is not None
            and route.get("depth_probe_status") is None
        )
        should_force_reprobe = bool(
            force_reprobe
            and (legacy_depth_row or route.get("depth_reprobe_required"))
        )
        if existing_depth is not None and not should_force_reprobe:
            continue
        pool_addr = route.get("pool_address") or ""
        if not pool_addr or pool_addr == "0x" + "0" * 40:
            continue
        counts["candidates"] += 1
        if should_force_reprobe:
            counts["force_reprobe_candidates"] += 1
        is_v4_route = route.get("adapter_type") == "uniswap_v4"
        if is_v4_route:
            counts["v4_depth_candidates"] += 1

        probe = probe_route_marginal_depth(
            route,
            rpc_url=rpc_url,
            dex_quoters=dex_quoters,
            probe_size_usd=probe_size_usd,
            ref_size_usd=ref_size_usd,
            price_map=_prices_distinct or None,
        )

        route["effective_depth_usd"] = probe["effective_depth_usd"]
        route["price_impact_at_100usd"] = probe["price_impact_at_100usd"]
        route["depth_reject_reason"] = probe["depth_reject_reason"]
        route["depth_probe_ok"] = probe["probe_ok"]
        route["depth_probe_error"] = probe.get("probe_error")
        route["depth_method"] = probe.get("depth_method", "marginal_anchor")
        if probe.get("depth_probe_status") is not None:
            route["depth_probe_status"] = probe["depth_probe_status"]
        if probe.get("depth_price_source"):
            route["depth_price_source"] = probe["depth_price_source"]

        if route.get("effective_depth_usd") is None and _w3_distinct is not None:
            try:
                from m9.graph_arb.distinct_depth_probe import enrich_route_depth_if_missing

                if enrich_route_depth_if_missing(
                    route, _w3_distinct, _prices_distinct, decimals_cache=None
                ):
                    counts["distinct_depth_ok"] += 1
            except Exception:
                pass

        if route.get("effective_depth_usd") is not None:
            counts["probed_ok"] += 1
            if is_v4_route:
                counts["v4_depth_probe_ok"] += 1
            reject = probe.get("depth_reject_reason") or route.get("depth_reject_reason")
            if reject == "TOXIC_PRICE_IMPACT":
                counts["toxic"] += 1
            elif reject == "LOW_EFFECTIVE_DEPTH":
                counts["low_depth"] += 1
        else:
            if is_v4_route:
                counts["v4_depth_probe_failed"] += 1
            err = probe.get("probe_error")
            if err == "NO_ANCHOR_FOR_DEPTH":
                counts["no_anchor"] += 1
            elif err == "V4_DEPTH_UNSUPPORTED":
                counts["skipped_v4"] += 1
            else:
                counts["probe_failed"] += 1

        try:
            from m9.graph_arb.expansion_admission import measured_depth_productive_override
            from m9.graph_arb.pool_quality import annotate_route_pool_quality

            if measured_depth_productive_override(route):
                route["expansion_productive_admit"] = True
                route["expansion_productive_admit_source"] = "measured_depth_override"
            annotate_route_pool_quality(route)
        except Exception:
            pass

        from m9.graph_arb.depth_contract import normalize_route_depth_contract

        normalize_route_depth_contract(route)

        if sleep_s:
            time.sleep(sleep_s)

    for route in routes:
        from m9.graph_arb.depth_contract import normalize_route_depth_contract

        normalize_route_depth_contract(route)

    return counts


def _multicall_prefetch_v2_reserves(
    routes: List[Dict[str, Any]],
    rpc_url: str,
    *,
    include_existing: bool = False,
) -> int:
    """Batch V2 getReserves via Multicall3; cache on route dict. Returns RPC calls saved."""
    v2_addrs: List[str] = []
    v2_routes: List[Dict[str, Any]] = []
    for route in routes:
        if route.get("effective_depth_usd") is not None and not include_existing:
            continue
        if route.get("adapter_type") not in _V2_FORK_ADAPTER_TYPES:
            continue
        pool = (route.get("pool_address") or "").lower()
        if pool and pool != "0x" + "0" * 40:
            v2_addrs.append(pool)
            v2_routes.append(route)
    if len(v2_addrs) < 2:
        return 0
    try:
        from core.multicall import MulticallBatcher

        batcher = MulticallBatcher(rpc_url)
        if not batcher.initialize():
            return 0
        chunk_size = 40
        saved = 0
        for i in range(0, len(v2_addrs), chunk_size):
            chunk_addrs = v2_addrs[i : i + chunk_size]
            chunk_routes = v2_routes[i : i + chunk_size]
            calls = batcher._encode_calls(chunk_addrs, "0x0902f1ac")
            results = batcher._try_chunk_adaptive(calls, limiter=None)
            for route, res in zip(chunk_routes, results):
                ok, data = res[0], res[1]
                if ok and data:
                    route["_v2_reserves_cached"] = data.hex() if isinstance(data, bytes) else data
            saved += max(len(chunk_addrs) - 1, 0)
        batcher.stats["multicall_saved_calls_estimate"] = saved
        return saved
    except Exception as exc:
        log.debug("V2 multicall prefetch skipped: %s", exc)
        return 0


# Default quarantine TTL: 7 days.  Entries older than this are considered expired
# and pool_depth_filter will skip them (transient quarantine policy).
_QUARANTINE_TTL_SECONDS = 7 * 24 * 3600  # 604800


def _update_quarantine(
    quarantine_path: Path,
    results_by_pool: Dict[str, Dict[str, Any]],
    active_routes: List[Dict[str, Any]],
    impact_threshold: float,
    rpc_url: str,
) -> None:
    """Append newly confirmed toxic/thin pools to the quarantine JSON.

    Skips pools already present in the file (matched on pool_address lowercase).
    Only adds entries where depth_reject_reason is TOXIC_PRICE_IMPACT or
    LOW_EFFECTIVE_DEPTH and probe_ok=True.
    """
    import datetime

    # Load existing quarantine
    if quarantine_path.exists():
        with quarantine_path.open("r", encoding="utf-8") as fh:
            quarantine = json.load(fh)
    else:
        quarantine = {
            "schema_version": "m9_pool_depth_quarantine.1",
            "generated_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "description": (
                "Evidence-based pool quarantine: specific pool/fee-tier routes excluded "
                "from M9 productive graph due to on-chain confirmed insufficient depth."
            ),
            "quarantined_pools": [],
        }

    existing_addrs: set[str] = {
        (e.get("pool_address") or "").lower()
        for e in quarantine.get("quarantined_pools", [])
    }

    today = datetime.date.today().isoformat()
    rpc_label = "publicnode.com" if "publicnode" in rpc_url else rpc_url.split("/")[2] if "//" in rpc_url else rpc_url
    new_count = 0

    for pool_addr, probe in results_by_pool.items():
        reject = probe.get("depth_reject_reason")
        if reject not in ("TOXIC_PRICE_IMPACT", "LOW_EFFECTIVE_DEPTH"):
            continue
        if not probe.get("probe_ok"):
            continue
        if pool_addr in existing_addrs:
            continue

        # Find matching route for pair/dex/fee metadata
        route = next(
            (r for r in active_routes if (r.get("pool_address") or "").lower() == pool_addr),
            {},
        )
        impact = probe.get("price_impact_at_100usd") or 0
        depth_usd = probe.get("effective_depth_usd") or 0

        # Compute retry_after_utc (quarantine expires after TTL, pool is re-probed)
        retry_dt = datetime.datetime.utcnow() + datetime.timedelta(seconds=_QUARANTINE_TTL_SECONDS)
        retry_after_utc = retry_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        entry: Dict[str, Any] = {
            "pool_address": pool_addr,
            "pair_id": route.get("pair_id", "UNKNOWN"),
            "dex_id": route.get("dex_id", "unknown"),
            "fee": int(route.get("fee", 0)),
            "reject_reason": reject,
            "quarantine_ttl_seconds": _QUARANTINE_TTL_SECONDS,
            "quarantined_at_utc": today,
            "retry_after_utc": retry_after_utc,
            "activation_path": (
                "Re-probe via pool_depth_probe --update-quarantine after retry_after_utc. "
                "If probe passes (impact < LOW_EFFECTIVE_DEPTH threshold), remove entry to re-activate."
            ),
            "evidence": {
                "price_impact_at_100usd": round(impact, 4),
                "effective_depth_usd": round(depth_usd, 2),
                "probe_size_usd": 100.0,
                "impact_threshold_used": impact_threshold,
                "measured_at": today,
                "rpc": rpc_label,
            },
            "note": (
                f"Auto-added by pool_depth_probe on {today}. "
                f"price_impact={impact * 100:.1f}%, effective_depth_usd={depth_usd:.2f}. "
                f"Expires (retry_after): {retry_after_utc}."
            ),
        }
        quarantine["quarantined_pools"].append(entry)
        existing_addrs.add(pool_addr)
        new_count += 1
        log.info(
            "Quarantine: added %s pair=%s reason=%s impact=%.1f%% retry_after=%s",
            pool_addr[:14],
            entry["pair_id"],
            reject,
            impact * 100,
            retry_after_utc,
        )

    if new_count > 0:
        quarantine["generated_at_utc"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with quarantine_path.open("w", encoding="utf-8") as fh:
            json.dump(quarantine, fh, indent=2, ensure_ascii=False)
        log.info("Quarantine updated: %d new entries → %s", new_count, quarantine_path)
    else:
        log.info("Quarantine: no new entries to add (all probed pools already listed or clean)")


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Measure on-chain effective depth for M9 inventory routes."
    )
    parser.add_argument(
        "--chain",
        default="base",
        help="Chain identifier (used to resolve RPC URL)",
    )
    parser.add_argument(
        "--inventory",
        default="data/tmp/m9_verified_inventory.json",
        help="Path to M9 verified inventory JSON",
    )
    parser.add_argument(
        "--config",
        default="config/exotic_base_anchor.yaml",
        help="M8_1 config YAML (for token addresses/decimals)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for enriched inventory (default: overwrites --inventory)",
    )
    parser.add_argument(
        "--probe-size-usd",
        type=float,
        default=100.0,
        help="Quote size in USD for depth probe (default: 100)",
    )
    parser.add_argument(
        "--impact-threshold",
        type=float,
        default=0.50,
        help="Price impact threshold for TOXIC_PRICE_IMPACT classification (default: 0.50)",
    )
    parser.add_argument(
        "--update-quarantine",
        default=None,
        help="Quarantine JSON to update with newly confirmed toxic pools",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without writing files",
    )
    args = parser.parse_args(argv)

    # Resolve RPC URL
    rpc_url: Optional[str] = os.environ.get(
        "BASE_RPC", "https://mainnet.base.org"
    )
    try:
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
        chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, _, _ = resolve_rpc_http(chain_id=chain_id, network=args.chain, env=dict(os.environ))
    except Exception as exc:
        log.warning("Could not resolve RPC via core.rpc_urls: %s — using BASE_RPC env", exc)

    if not rpc_url:
        log.error("No RPC URL available. Set BASE_RPC env var.")
        return 1

    # Load inventory
    inv_path = Path(args.inventory)
    if not inv_path.exists():
        log.error("Inventory not found: %s", inv_path)
        return 1

    with inv_path.open("r", encoding="utf-8") as fh:
        inventory = json.load(fh)

    # Load config for token addresses and dex quoter addresses
    config_tokens: Dict[str, Any] = {}
    dex_quoters: Dict[str, str] = {}
    try:
        import yaml
        with open(args.config, encoding="utf-8") as fh:
            cfg_raw = yaml.safe_load(fh) or {}
        config_tokens = cfg_raw.get("tokens", {})
        # Build dex_id -> quoter_addr map from config dexes block
        for dex_id, dex_cfg in (cfg_raw.get("dexes") or {}).items():
            q = dex_cfg.get("quoter_v2") or dex_cfg.get("quoter")
            if q:
                dex_quoters[dex_id] = q
    except Exception as exc:
        log.warning("Could not load config %s: %s — using token price table only", args.config, exc)

    active_routes = inventory.get("active_routes", [])
    # Inject quoter_addr into routes that don't have it (from dex config fallback)
    injected = 0
    for route in active_routes:
        if not route.get("quoter_addr"):
            dex_id = route.get("dex_id", "")
            q = dex_quoters.get(dex_id)
            if q:
                route["quoter_addr"] = q
                injected += 1
    if injected:
        log.info("Injected quoter_addr for %d routes from dex config", injected)
    log.info("Probing %d active routes at $%.0f...", len(active_routes), args.probe_size_usd)

    results_by_pool: Dict[str, Dict[str, Any]] = {}
    ok_count = 0
    fail_count = 0
    toxic_count = 0
    low_depth_count = 0

    for route in active_routes:
        pool_addr = route.get("pool_address", "")
        if not pool_addr or pool_addr == "0x" + "0" * 40:
            continue

        probe = probe_pool_depth(
            route=route,
            config_tokens=config_tokens,
            rpc_url=rpc_url,
            probe_size_usd=args.probe_size_usd,
        )

        # Enrich route entry in-place
        route["effective_depth_usd"] = probe["effective_depth_usd"]
        route["price_impact_at_100usd"] = probe["price_impact_at_100usd"]
        route["depth_reject_reason"] = probe["depth_reject_reason"]
        route["depth_probe_ok"] = probe["probe_ok"]

        results_by_pool[pool_addr.lower()] = probe

        if probe["probe_ok"]:
            ok_count += 1
            impact = probe.get("price_impact_at_100usd") or 0
            reject = probe.get("depth_reject_reason")
            if reject == "TOXIC_PRICE_IMPACT":
                toxic_count += 1
                log.warning(
                    "TOXIC_PRICE_IMPACT: pool=%s pair=%s impact=%.1f%%",
                    pool_addr[:10],
                    route.get("pair_id"),
                    impact * 100,
                )
            elif reject == "LOW_EFFECTIVE_DEPTH":
                low_depth_count += 1
                log.info(
                    "LOW_EFFECTIVE_DEPTH: pool=%s pair=%s impact=%.1f%% depth_usd=%.2f",
                    pool_addr[:10],
                    route.get("pair_id"),
                    impact * 100,
                    probe.get("effective_depth_usd") or 0,
                )
        else:
            fail_count += 1
            log.debug("Probe failed: pool=%s error=%s", pool_addr[:10], probe.get("probe_error"))

        time.sleep(0.1)  # conservative rate limit for free-tier RPC

    log.info(
        "Probe complete: ok=%d fail=%d toxic=%d low_depth=%d",
        ok_count, fail_count, toxic_count, low_depth_count,
    )

    if not args.dry_run:
        output_path = Path(args.output or args.inventory)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(inventory, fh, indent=2)
        log.info("Enriched inventory written to %s", output_path)

    # Update quarantine file with newly confirmed toxic/thin pools
    if args.update_quarantine and not args.dry_run:
        _update_quarantine(
            quarantine_path=Path(args.update_quarantine),
            results_by_pool=results_by_pool,
            active_routes=active_routes,
            impact_threshold=args.impact_threshold,
            rpc_url=rpc_url or "",
        )

    # Print summary table
    print("\n=== Pool Depth Probe Results ===")
    print(f"{'pool_address':<44} {'pair_id':<20} {'impact%':>8} {'depth_usd':>10} {'reason':<25}")
    print("-" * 115)
    for pool_addr, probe in sorted(results_by_pool.items(), key=lambda x: -(x[1].get("price_impact_at_100usd") or 0)):
        if not probe["probe_ok"]:
            continue
        route_entry = next(
            (r for r in active_routes if (r.get("pool_address") or "").lower() == pool_addr),
            {},
        )
        impact = probe.get("price_impact_at_100usd") or 0
        depth = probe.get("effective_depth_usd") or 0
        reason = probe.get("depth_reject_reason") or "OK"
        pair = route_entry.get("pair_id", "?")
        print(f"{pool_addr:<44} {pair:<20} {impact * 100:>7.1f}% {depth:>10.2f} {reason:<25}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
