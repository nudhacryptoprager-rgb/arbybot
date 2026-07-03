"""Specialized on-chain verification for M8.2 external pool hints."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, Optional, Set, Tuple

from m8.discovery.pool_hints import PoolHint

# Uniswap V4 StateView on Base (lens contract)
_V4_STATEVIEW_BASE = "0xa3c0c9b65bad0b08107aa264b0f3db444b867a71"
_V4_POOL_MANAGER_BASE = "0x498581ff718922c3f8e6a244956af099b2652b2b"
_BALANCER_VAULT = "0xba12222222228d8ba445958a75a0704d566bf2c8"

_SEL_V4_GET_SLOT0 = "c815641c"  # getSlot0(bytes32)
_SEL_V4_GET_LIQUIDITY = "fa6793d5"  # getLiquidity(bytes32)
_SEL_BALANCER_GET_POOL_TOKENS = "f94d4668"  # getPoolTokens(bytes32)
_SEL_CURVE_COINS = "c6610657"  # coins(uint256)
_SEL_MAV_TOKEN_A = "0fc63d10"  # tokenA()
_SEL_MAV_TOKEN_B = "5f64b55b"  # tokenB()

VERIFY_BYTECODE = "bytecode"
VERIFY_V4_STATEVIEW = "v4_stateview"
VERIFY_FACTORY_GET_POOL = "factory_getPool"
VERIFY_BALANCER_POOL_TOKENS = "balancer_getPoolTokens"
VERIFY_CURVE_COINS = "curve_coins"
VERIFY_MAVERICK_TOKEN_PAIR = "maverick_tokenAB"
VERIFY_NONE = "none"


def is_bytes32_hex(value: str) -> bool:
    v = (value or "").lower().strip()
    return v.startswith("0x") and len(v) == 66


def resolve_pool_id(hint: PoolHint) -> str:
    if hint.pool_id and is_bytes32_hex(hint.pool_id):
        return hint.pool_id.lower()
    if is_bytes32_hex(hint.pool_address):
        return hint.pool_address.lower()
    return ""


def _rpc_url(chain: str, override: Optional[str] = None) -> Optional[str]:
    if override:
        return override
    from core.rpc_urls import get_rpc_url

    return get_rpc_url(chain)


def _eth_call(rpc_url: str, to: str, data: str) -> Optional[str]:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("error"):
            return None
        result = body.get("result")
        if not result or result in ("0x", "0x0"):
            return None
        return str(result)
    except Exception:
        return None


def _eth_get_code(rpc_url: str, address: str) -> str:
    """Return deployed bytecode hex string, or empty string if empty/error."""
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getCode",
            "params": [address, "latest"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        code = str((body.get("result") or "0x")).strip().lower()
        return code if code not in ("0x", "") else ""
    except Exception:
        return ""


def _pool_has_bytecode_from_code(code: str) -> bool:
    return bool(code and code != "0x")


def _encode_bytes32_arg(pool_id: str) -> str:
    raw = pool_id.lower().replace("0x", "").zfill(64)
    return raw


def verify_v4_pool_id(
    pool_id: str,
    *,
    chain: str = "base",
    rpc_url: Optional[str] = None,
    token0: str = "",
    token1: str = "",
) -> Tuple[bool, str]:
    """Verify V4 poolId via StateView getSlot0 + getLiquidity."""
    if not is_bytes32_hex(pool_id):
        return False, "V4_INVALID_POOL_ID"
    url = _rpc_url(chain, rpc_url)
    if not url:
        return False, "RPC_UNAVAILABLE"
    stateview = _V4_STATEVIEW_BASE
    arg = _encode_bytes32_arg(pool_id)
    slot0 = _eth_call(url, stateview, "0x" + _SEL_V4_GET_SLOT0 + arg)
    if not slot0 or len(slot0) < 66:
        return False, "V4_SLOT0_EMPTY"
    liq = _eth_call(url, stateview, "0x" + _SEL_V4_GET_LIQUIDITY + arg)
    if not liq:
        return False, "V4_LIQUIDITY_CALL_FAILED"
    try:
        liq_val = int(liq, 16)
    except ValueError:
        return False, "V4_LIQUIDITY_DECODE_FAILED"
    if liq_val <= 0:
        return False, "V4_ZERO_LIQUIDITY"
    return True, VERIFY_V4_STATEVIEW


def verify_v4_pool_id_exists(
    pool_id: str,
    *,
    chain: str = "base",
    rpc_url: Optional[str] = None,
) -> Tuple[bool, str]:
    """Existence-only V4 check: initialized poolId (slot0), no liquidity floor."""
    if not is_bytes32_hex(pool_id):
        return False, "V4_INVALID_POOL_ID"
    url = _rpc_url(chain, rpc_url)
    if not url:
        return False, "RPC_UNAVAILABLE"
    arg = _encode_bytes32_arg(pool_id)
    slot0 = _eth_call(url, _V4_STATEVIEW_BASE, "0x" + _SEL_V4_GET_SLOT0 + arg)
    if slot0 and len(slot0) >= 66:
        return True, VERIFY_V4_STATEVIEW
    return False, "V4_SLOT0_EMPTY"


def verify_balancer_pool_id(
    pool_id: str,
    *,
    chain: str = "base",
    rpc_url: Optional[str] = None,
    token0: str = "",
    token1: str = "",
) -> Tuple[bool, str]:
    if not is_bytes32_hex(pool_id):
        return False, "BALANCER_INVALID_POOL_ID"
    url = _rpc_url(chain, rpc_url)
    if not url:
        return False, "RPC_UNAVAILABLE"
    arg = _encode_bytes32_arg(pool_id)
    result = _eth_call(url, _BALANCER_VAULT, "0x" + _SEL_BALANCER_GET_POOL_TOKENS + arg)
    if not result or len(result) < 130:
        return False, "BALANCER_GET_POOL_TOKENS_FAILED"
    raw = result[2:] if result.startswith("0x") else result
    if len(raw) < 192:
        return False, "BALANCER_DECODE_TOO_SHORT"
    want = {token0.lower(), token1.lower()} - {"", "0x"}
    if want:
        tokens_found = set()
        for i in range(0, len(raw), 64):
            chunk = raw[i : i + 64]
            if len(chunk) == 64 and chunk[:24] == "0" * 24:
                tokens_found.add("0x" + chunk[24:].lower())
        if not want <= tokens_found:
            return False, "BALANCER_TOKEN_MISMATCH"
    return True, VERIFY_BALANCER_POOL_TOKENS


def verify_curve_pool(
    pool_address: str,
    *,
    chain: str = "base",
    rpc_url: Optional[str] = None,
    token0: str = "",
    token1: str = "",
) -> Tuple[bool, str]:
    addr = (pool_address or "").lower()
    if not addr.startswith("0x") or len(addr) != 42:
        return False, "CURVE_INVALID_ADDRESS"
    url = _rpc_url(chain, rpc_url)
    if not url:
        return False, "RPC_UNAVAILABLE"
    want = {token0.lower(), token1.lower()} - {"", "0x"}
    found: set = set()
    for idx in range(4):
        data = "0x" + _SEL_CURVE_COINS + format(idx, "064x")
        result = _eth_call(url, addr, data)
        if not result or result == "0x":
            break
        raw = result[2:] if result.startswith("0x") else result
        if len(raw) < 64:
            break
        coin = "0x" + raw[-40:].lower()
        if coin == "0x" + "0" * 40:
            break
        found.add(coin)
    if not found:
        return False, "CURVE_COINS_EMPTY"
    if want and not want <= found:
        return False, "CURVE_TOKEN_MISMATCH"
    return True, VERIFY_CURVE_COINS


def verify_maverick_pool(
    pool_address: str,
    *,
    chain: str = "base",
    rpc_url: Optional[str] = None,
    token0: str = "",
    token1: str = "",
) -> Tuple[bool, str]:
    addr = (pool_address or "").lower()
    if not addr.startswith("0x") or len(addr) != 42:
        return False, "MAVERICK_INVALID_ADDRESS"
    url = _rpc_url(chain, rpc_url)
    if not url:
        return False, "RPC_UNAVAILABLE"
    ta = _eth_call(url, addr, "0x" + _SEL_MAV_TOKEN_A)
    tb = _eth_call(url, addr, "0x" + _SEL_MAV_TOKEN_B)
    if not ta or not tb:
        return False, "MAVERICK_TOKEN_CALL_FAILED"
    def _decode_addr(hex_result: str) -> str:
        raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
        return "0x" + raw[-40:].lower()

    pair = {_decode_addr(ta), _decode_addr(tb)}
    want = {token0.lower(), token1.lower()} - {"", "0x"}
    if want and not want <= pair:
        return False, "MAVERICK_TOKEN_MISMATCH"
    return True, VERIFY_MAVERICK_TOKEN_PAIR


def verify_factory_pool(
    hint: PoolHint,
    *,
    chain: str,
    rpc_url: Optional[str] = None,
) -> Tuple[bool, str]:
    from discovery.index_factories import verify_pool_exists

    dex = hint.dex_id
    t0, t1 = hint.token0_addr, hint.token1_addr
    if not t0 or not t1:
        return False, "FACTORY_MISSING_TOKENS"
    fee = hint.fee
    pool = verify_pool_exists(
        chain,
        dex,
        t0,
        t1,
        fee_tier=fee,
        rpc_url=rpc_url,
    )
    if pool:
        return True, VERIFY_FACTORY_GET_POOL
    return False, "FACTORY_NO_POOL"


def _try_aerodrome_slipstream_fallback(
    hint: PoolHint,
    *,
    chain: str,
    rpc_url: Optional[str] = None,
) -> Tuple[bool, str, Optional[int]]:
    """When ve33 factory.getPool returns no pool, try Slipstream factory.

    Aerodrome Slipstream uses V3-style getPool(token0, token1, fee) but
    verify_pool_exists routes it to V2 getPair because "v3" is not in
    the dex_key. This fallback queries the slipstream factory directly
    with common fee tiers.

    Returns (found, factory_address, fee_tier) or (False, "", None).
    """
    from discovery.index_factories import get_factory_address, query_v3_pool, V3_FEE_TIERS

    url = _rpc_url(chain, rpc_url)
    if not url:
        return False, "", None

    slip_factory = get_factory_address(chain, "aerodrome_slipstream")
    if not slip_factory:
        return False, "", None

    t0, t1 = hint.token0_addr, hint.token1_addr
    if not t0 or not t1:
        return False, "", None

    for fee in V3_FEE_TIERS:
        pool_addr = query_v3_pool(url, slip_factory, t0, t1, fee)
        if pool_addr:
            return True, slip_factory, fee

    return False, "", None


def verify_hint_specialized(
    hint: PoolHint,
    *,
    chain: str,
    allowed_dex_ids: Optional[Set[str]] = None,
    rpc_url: Optional[str] = None,
    verify_mode: str = "specialized",
) -> Tuple[PoolHint, str]:
    """Verify hint; returns (hint, reject_reason_or_ok)."""
    h = PoolHint.from_dict(hint.to_dict())
    if verify_mode == "none":
        h.verify_method = VERIFY_NONE
        return h, "SKIPPED"

    if allowed_dex_ids is not None and h.dex_id not in allowed_dex_ids:
        return h, "HINT_DEX_UNSUPPORTED"

    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return h, "RPC_SKIPPED"

    dex = h.dex_id
    pool_id = resolve_pool_id(h)

    if dex == "uniswap_v4" or pool_id:
        ok, method = verify_v4_pool_id(
            pool_id or h.pool_address,
            chain=chain,
            rpc_url=rpc_url,
            token0=h.token0_addr,
            token1=h.token1_addr,
        )
        if ok:
            h.pool_id = pool_id or h.pool_address
            h.pool_manager = h.pool_manager or _V4_POOL_MANAGER_BASE
            h.verify_method = method
            return h, "OK"
        if h.token0_addr and h.token1_addr:
            v3 = PoolHint.from_dict(h.to_dict())
            v3.dex_id = "uniswap_v3"
            pair = (h.raw or {}).get("pair") if isinstance((h.raw or {}).get("pair"), dict) else {}
            fee_raw = pair.get("feeTier") or pair.get("fee")
            if fee_raw is not None:
                try:
                    v3.fee = int(fee_raw)
                except (TypeError, ValueError):
                    pass
            f_ok, f_method = verify_factory_pool(v3, chain=chain, rpc_url=rpc_url)
            if f_ok:
                h.dex_id = "uniswap_v3"
                h.verify_method = f_method
                return h, "OK"
        return h, method

    if dex in ("balancer_vault", "balancer_stable"):
        pid = h.pool_id or h.pool_address
        ok, method = verify_balancer_pool_id(
            pid,
            chain=chain,
            rpc_url=rpc_url,
            token0=h.token0_addr,
            token1=h.token1_addr,
        )
        if ok:
            h.pool_id = pid
            h.vault_address = h.factory_address or _BALANCER_VAULT
            h.verify_method = method
            return h, "OK"
        return h, method

    if dex == "curve_stable":
        ok, method = verify_curve_pool(
            h.pool_address,
            chain=chain,
            rpc_url=rpc_url,
            token0=h.token0_addr,
            token1=h.token1_addr,
        )
        if ok:
            h.verify_method = method
            return h, "OK"
        return h, method

    if dex == "maverick_v2":
        ok, method = verify_maverick_pool(
            h.pool_address,
            chain=chain,
            rpc_url=rpc_url,
            token0=h.token0_addr,
            token1=h.token1_addr,
        )
        if ok:
            h.verify_method = method
            return h, "OK"
        return h, method

    addr = (h.pool_address or "").lower()
    if verify_mode == "light" and addr.startswith("0x") and len(addr) == 42:
        url = _rpc_url(chain, rpc_url)
        if url and _eth_get_code(url, addr):
            h.verify_method = VERIFY_BYTECODE
            return h, "OK"
        return h, "BYTECODE_EMPTY"

    if dex in ("uniswap_v3", "uniswap_v2", "aerodrome", "aerodrome_slipstream",
               "aerodrome_v2_stable", "sushiswap_v3", "pancakeswap_v3", "baseswap_v2",
               "sushiswap_v2"):
        ok, method = verify_factory_pool(h, chain=chain, rpc_url=rpc_url)
        if ok:
            h.verify_method = method
            return h, "OK"

        if dex == "aerodrome" and method == "FACTORY_NO_POOL":
            slip_ok, slip_method, slip_fee = _try_aerodrome_slipstream_fallback(
                h, chain=chain, rpc_url=rpc_url
            )
            if slip_ok:
                h.dex_id = "aerodrome_slipstream"
                h.fee = slip_fee
                h.factory_address = slip_method
                h.verify_method = VERIFY_FACTORY_GET_POOL
                raw = dict(h.raw or {})
                raw["aerodrome_variant_fallback"] = "ve33_to_slipstream"
                h.raw = raw
                return h, "OK"

        if verify_mode == "specialized" and addr.startswith("0x") and len(addr) == 42:
            url = _rpc_url(chain, rpc_url)
            if url and _eth_get_code(url, addr):
                h.verify_method = VERIFY_BYTECODE
                return h, "OK"
        return h, method

    if addr.startswith("0x") and len(addr) == 42:
        url = _rpc_url(chain, rpc_url)
        if url and _eth_get_code(url, addr):
            h.verify_method = VERIFY_BYTECODE
            return h, "OK"
    return h, "UNSUPPORTED_VERIFY_PATH"


def empty_verification_metrics() -> Dict[str, Any]:
    return {
        "verified_by_method": {},
        "verification_reject_histogram": {},
        "v4_poolid_hints_seen": 0,
        "v4_poolid_verified": 0,
    }


def record_verification_metrics(
    metrics: Dict[str, Any],
    hint: PoolHint,
    *,
    verified: bool,
    reject_reason: str,
) -> None:
    if is_bytes32_hex(hint.pool_id or hint.pool_address) or hint.dex_id == "uniswap_v4":
        metrics["v4_poolid_hints_seen"] = int(metrics.get("v4_poolid_hints_seen", 0)) + 1
        if verified and hint.verify_method == VERIFY_V4_STATEVIEW:
            metrics["v4_poolid_verified"] = int(metrics.get("v4_poolid_verified", 0)) + 1
    if verified and hint.verify_method:
        by_method = dict(metrics.get("verified_by_method") or {})
        by_method[hint.verify_method] = int(by_method.get(hint.verify_method, 0)) + 1
        metrics["verified_by_method"] = by_method
    elif reject_reason and reject_reason not in ("OK", "SKIPPED"):
        hist = dict(metrics.get("verification_reject_histogram") or {})
        hist[reject_reason] = int(hist.get(reject_reason, 0)) + 1
        metrics["verification_reject_histogram"] = hist
