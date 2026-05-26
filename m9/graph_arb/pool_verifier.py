"""On-chain factory verification for M9 inventory routes.

For each (dex_id, pair, fee_tier) candidate derived from config, queries the DEX
factory contract via raw JSON-RPC to determine whether a pool exists on-chain.

This eliminates QUOTE_REVERT caused by non-existent pools (wrong fee tiers,
undeployed pair+fee combinations) BEFORE they enter the M9 graph as cycle edges.

The config (exotic_base_anchor.yaml) remains the trust-anchor layer:
  - chain, token anchors, factory addresses, quoter addresses, adapter types
  - candidate fee-tier universe (these are *candidates*, not guaranteed deployed)

All pool truth (which pools actually exist) comes from on-chain factory queries here.

Canonical active-route contract (Step 2 / GPT directive M9_INVENTORY_PURITY):
  pool_address       — non-zero address returned by factory.getPool
  factory_address    — factory contract queried
  dex_id             — key from config.dexes
  adapter_type       — from config.dexes[dex_id].adapter_type
  token0             — symbol of first token
  token1             — symbol of second token
  token0_addr        — on-chain address of token0
  token1_addr        — on-chain address of token1
  fee                — fee uint24 (or tick_spacing int24 for Slipstream)
  tick_spacing       — int24 tick spacing (Slipstream only, else None)
  factory_address    — factory contract that was queried
  verified_at_block  — block tag used for verification ("latest")
  factory_verified   — True iff factory returned non-zero pool address AND liquidity_ok is not False
  factory_match      — True (factory_address always matches config here)
  token_match        — None (P3: not yet verified via pool.token0/token1 calls)
  fee_match          — None (P3: not yet verified via pool.fee call)
  liquidity_ok       — True/False/None: True iff pool.liquidity() > 0; None if RPC error
  status             — "active" | "quarantined" | "unverified"
  quarantine_reason  — None | "FACTORY_NO_POOL" | "FACTORY_RPC_ERROR" | "POOL_ZERO_LIQUIDITY"

Public API:
  verify_candidates_from_config(config, rpc_url, *, max_workers=4) -> List[dict]
      Queries factory for every enabled (dex, pair, fee) combo in config.

  verify_inventory_routes(routes, rpc_url, *, max_workers=4) -> List[dict]
      Re-verifies existing inventory routes (adds/refreshes factory_verified field).

  write_verified_inventory(routes, output_path) -> None
      Writes verified routes to a JSON inventory file.
"""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ABI selectors — keccak256(function_signature)[:4]
# ---------------------------------------------------------------------------
# getPool(address,address,uint24) — UniswapV3 / PancakeSwap V3 / SushiSwap V3 factory
# keccak256("getPool(address,address,uint24)")[:4] = 0x1698ee82  (well-known constant)
_GETPOOL_V3_SEL: str = "1698ee82"

# getPool(address,address,int24) — Aerodrome Slipstream CLFactory
# Computed lazily via web3.Web3.keccak (web3 is a hard project dependency)
_GETPOOL_SLIP_SEL: Optional[str] = None

# getPair(address,address) — UniswapV2 / SushiSwap V2 / BaseSwap V2 factory (no fee parameter)
# keccak256("getPair(address,address)")[:4] = 0xe6a43905  (well-known constant)
_GETPAIR_V2_SEL: str = "e6a43905"

# getPool(address,address,bool) — Aerodrome ve33 PoolFactory (stable flag)
# Computed lazily via web3.Web3.keccak (web3 is a hard project dependency)
_GETPOOL_VE33_SEL: Optional[str] = None

# Adapter types with recognised on-chain pools but no M9 quote adapter yet.
# Routes for these adapters are explicitly quarantined (not silently dropped).
# V4 is now active — pools are discovered via M8 sniper, not static enumeration.
_PENDING_QUOTE_ADAPTERS: frozenset = frozenset()

_ZERO_ADDR = "0x" + "0" * 40
_OUTPUT_PATH = "data/tmp/m9_verified_inventory.json"

# ABI selectors for pool-level reads (used by liquidity_ok check)
# keccak256("liquidity()")[:4] — UniswapV3 / Slipstream pool.liquidity()
_LIQUIDITY_SEL: str = "1a686502"

# Configurable inter-request delay (seconds) to respect RPC rate limits.
# CLI --delay-ms and verify_candidates_from_config(request_delay_s=...) override this.
_DEFAULT_REQUEST_DELAY_S: float = 0.0


def _get_slip_selector() -> str:
    """Return 4-byte hex selector for Slipstream getPool(address,address,int24)."""
    global _GETPOOL_SLIP_SEL
    if _GETPOOL_SLIP_SEL is None:
        try:
            from web3 import Web3  # web3 is a hard project dep
            _GETPOOL_SLIP_SEL = Web3.keccak(
                text="getPool(address,address,int24)"
            )[:4].hex()
        except Exception as exc:
            logger.warning("Cannot compute Slipstream selector via web3: %s", exc)
            # Fallback: pre-computed value (Aerodrome CLFactory ABI)
            # keccak256("getPool(address,address,int24)")[:4] = 0x28af8d0b
            # Computed offline (differs from V3 uint24 selector 0x1698ee82).
            _GETPOOL_SLIP_SEL = "28af8d0b"
    return _GETPOOL_SLIP_SEL


def _get_ve33_selector() -> str:
    """Return 4-byte hex selector for Aerodrome ve33 getPool(address,address,bool)."""
    global _GETPOOL_VE33_SEL
    if _GETPOOL_VE33_SEL is None:
        try:
            from web3 import Web3
            _GETPOOL_VE33_SEL = Web3.keccak(
                text="getPool(address,address,bool)"
            )[:4].hex()
        except Exception as exc:
            logger.warning("Cannot compute ve33 selector via web3: %s", exc)
            # Fallback: pre-computed value (Aerodrome PoolFactory ABI)
            # keccak256("getPool(address,address,bool)")[:4]
            _GETPOOL_VE33_SEL = "a2886e8b"
    return _GETPOOL_VE33_SEL


# ---------------------------------------------------------------------------
# ABI encoding helpers
# ---------------------------------------------------------------------------

def _encode_addr(addr: str) -> str:
    """ABI-encode a single address as 32 bytes (left-padded to 64 hex chars)."""
    return addr.lower().replace("0x", "").zfill(64)


def _encode_int_32(value: int) -> str:
    """ABI-encode a uint24 / int24 as 32 bytes.

    For non-negative values uint24 and int24 encoding are identical.
    Negative tick_spacings are technically possible but all real spacings are positive.
    """
    if value < 0:
        # Two's complement representation for signed negative values
        return format(value % (2 ** 256), "064x")
    return format(value, "064x")


def _build_getpool_calldata(
    token_a: str,
    token_b: str,
    fee_or_spacing: int,
    adapter_type: str,
) -> str:
    """Build eth_call data for factory.getPool(tokenA, tokenB, fee/tick)."""
    sel = _get_slip_selector() if adapter_type == "aerodrome_slipstream" else _GETPOOL_V3_SEL
    return (
        "0x"
        + sel
        + _encode_addr(token_a)
        + _encode_addr(token_b)
        + _encode_int_32(fee_or_spacing)
    )


def _build_getpair_v2_calldata(token_a: str, token_b: str) -> str:
    """Build eth_call data for V2 factory.getPair(tokenA, tokenB) — no fee parameter."""
    return "0x" + _GETPAIR_V2_SEL + _encode_addr(token_a) + _encode_addr(token_b)


def _build_getpool_ve33_calldata(token_a: str, token_b: str, stable: bool) -> str:
    """Build eth_call data for Aerodrome ve33 factory.getPool(tokenA, tokenB, stable)."""
    stable_encoded = _encode_int_32(1 if stable else 0)
    return (
        "0x"
        + _get_ve33_selector()
        + _encode_addr(token_a)
        + _encode_addr(token_b)
        + stable_encoded
    )


def _build_factory_calldata(
    token_a: str,
    token_b: str,
    fee_or_spacing: int,
    adapter_type: str,
) -> str:
    """Dispatch to the correct factory ABI encoding for the given adapter_type.

    - uniswap_v2:           getPair(address,address)           — no fee/tick
    - ve33:                  getPool(address,address,bool=False) — volatile
    - aerodrome_v2_stable:   getPool(address,address,bool=True)  — stable
    - aerodrome_slipstream:  getPool(address,address,int24)      — tickSpacing
    - uniswap_v3 (and forks): getPool(address,address,uint24)   — fee
    """
    if adapter_type == "uniswap_v2":
        return _build_getpair_v2_calldata(token_a, token_b)
    elif adapter_type == "ve33":
        return _build_getpool_ve33_calldata(token_a, token_b, stable=False)
    elif adapter_type == "aerodrome_v2_stable":
        return _build_getpool_ve33_calldata(token_a, token_b, stable=True)
    else:
        return _build_getpool_calldata(token_a, token_b, fee_or_spacing, adapter_type)


def _decode_addr_result(result: str) -> str:
    """Decode ABI-encoded address return value (32 bytes → 0x-prefixed address)."""
    clean = result.replace("0x", "").lower()
    if len(clean) < 40:
        return _ZERO_ADDR
    return "0x" + clean[-40:]


# ---------------------------------------------------------------------------
# Raw JSON-RPC eth_call
# ---------------------------------------------------------------------------

def _eth_call(
    rpc_url: str,
    to: str,
    calldata: str,
    *,
    request_delay_s: float = 0.0,
    max_retries: int = 3,
    base_retry_delay_s: float = 1.0,
) -> Optional[str]:
    """Send a single eth_call with optional throttle delay and 429 retry backoff.

    Args:
        rpc_url:          HTTP RPC endpoint.
        to:               Contract address.
        calldata:         ABI-encoded call data (hex string, 0x-prefixed).
        request_delay_s:  Sleep this many seconds before the request (rate limiting).
        max_retries:      Max retry attempts on HTTP 429 responses.
        base_retry_delay_s: Initial backoff delay; doubled on each retry.

    Returns:
        Hex result string or None on any error.
    """
    if request_delay_s > 0:
        time.sleep(request_delay_s)

    payload = {
        "jsonrpc": "2.0",
        "method": "eth_call",
        "params": [{"to": to, "data": calldata}, "latest"],
        "id": 1,
    }
    for attempt in range(max_retries):
        try:
            resp = httpx.post(rpc_url, json=payload, timeout=10.0)
            if resp.status_code == 429:
                wait = base_retry_delay_s * (2 ** attempt)
                logger.debug(
                    "eth_call HTTP 429 for %s (attempt %d/%d), backing off %.1fs",
                    to, attempt + 1, max_retries, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                logger.debug("eth_call RPC error for %s: %s", to, body["error"])
                return None
            result: str = body.get("result", "")
            if not result or result == "0x":
                return None
            return result
        except httpx.HTTPStatusError as exc:
            logger.debug("eth_call HTTP error for %s: %s", to, exc)
            return None
        except Exception as exc:
            logger.debug("eth_call error for %s: %s", to, exc)
            return None
    logger.debug("eth_call exhausted retries for %s", to)
    return None


# ---------------------------------------------------------------------------
# Single-candidate verification
# ---------------------------------------------------------------------------

def _check_liquidity_ok(rpc_url: str, pool_address: str, request_delay_s: float = 0.0) -> Optional[bool]:
    """Call pool.liquidity() and return True iff liquidity > 0.

    Returns None on any RPC error (cannot determine).
    """
    calldata = "0x" + _LIQUIDITY_SEL
    result = _eth_call(rpc_url, pool_address, calldata, request_delay_s=request_delay_s)
    if result is None:
        return None
    clean = result.replace("0x", "").lower().zfill(64)
    try:
        liquidity = int(clean, 16)
        return liquidity > 0
    except ValueError:
        return None


def _verify_one(
    *,
    factory_addr: str,
    token_a_addr: str,
    token_b_addr: str,
    fee_or_spacing: int,
    adapter_type: str,
    rpc_url: str,
    dex_id: str,
    pair_sym: str,
    token_a_sym: str,
    token_b_sym: str,
    request_delay_s: float = 0.0,
    check_liquidity: bool = True,
) -> Dict[str, Any]:
    """Query factory.getPool for one (factory, tokenA, tokenB, fee) combo.

    Returns a canonical route dict with factory_verified / quarantine_reason set.
    When check_liquidity=True, also calls pool.liquidity() on verified pools.
    """
    calldata = _build_factory_calldata(
        token_a_addr, token_b_addr, fee_or_spacing, adapter_type
    )
    result = _eth_call(rpc_url, factory_addr, calldata, request_delay_s=request_delay_s)

    liquidity_ok: Optional[bool] = None

    if result is None:
        pool_address = _ZERO_ADDR
        factory_verified = False
        quarantine_reason: Optional[str] = "FACTORY_RPC_ERROR"
        status = "unverified"
    else:
        pool_address = _decode_addr_result(result)
        if pool_address == _ZERO_ADDR:
            factory_verified = False
            quarantine_reason = "FACTORY_NO_POOL"
            status = "quarantined"
        else:
            factory_verified = True
            quarantine_reason = None
            # P2: check pool.liquidity() to confirm pool is active
            # Note: V2 pairs and ve33 pools also expose liquidity() — skip for V2/ve33 for now
            if check_liquidity and adapter_type not in {"uniswap_v2", "ve33", "aerodrome_v2_stable"}:
                liquidity_ok = _check_liquidity_ok(rpc_url, pool_address, request_delay_s)
                if liquidity_ok is False:
                    # Pool exists but has zero liquidity — quarantine
                    factory_verified = False
                    quarantine_reason = "POOL_ZERO_LIQUIDITY"
                    status = "quarantined"
                else:
                    status = "active"  # liquidity_ok=True or None (RPC error → optimistic)
            else:
                status = "active"

    # Build canonical route_id matching builder.py convention
    if adapter_type == "aerodrome_slipstream":
        fee_label = f"ts{fee_or_spacing}"
    elif adapter_type == "uniswap_v2":
        fee_label = "v2pair"
    elif adapter_type == "ve33":
        fee_label = "volatile"
    elif adapter_type == "aerodrome_v2_stable":
        fee_label = "stable"
    else:
        fee_label = f"f{fee_or_spacing}"
    route_id = f"{dex_id}:{fee_label}"

    return {
        "route_id": route_id,
        "pair_id": pair_sym,
        "dex_id": dex_id,
        "adapter_type": adapter_type,
        "token0": token_a_sym,
        "token1": token_b_sym,
        "token0_addr": token_a_addr,
        "token1_addr": token_b_addr,
        "fee": fee_or_spacing,
        "tick_spacing": fee_or_spacing if adapter_type == "aerodrome_slipstream" else None,
        "factory_address": factory_addr,
        "pool_address": pool_address,
        "verified_at_block": "latest",
        "factory_verified": factory_verified,
        "factory_match": True,
        "token_match": None,   # P3: not yet verified via pool.token0/token1 slot reads
        "fee_match": None,     # P3: not yet verified via pool.fee slot read
        "liquidity_ok": liquidity_ok,
        "status": status,
        "quarantine_reason": quarantine_reason,
    }


# ---------------------------------------------------------------------------
# Public API: verify from config
# ---------------------------------------------------------------------------

def verify_candidates_from_config(
    config: "Any",  # M8_1Config — typed loosely to avoid circular import at top level
    rpc_url: str,
    *,
    max_workers: int = 4,
    request_delay_s: float = 0.0,
    check_liquidity: bool = True,
) -> List[Dict[str, Any]]:
    """Verify all (dex, pair, fee_tier) candidates from config against on-chain factories.

    Enumerates every enabled DEX × all token pairs × all candidate fee tiers (or
    tick_spacings for Slipstream), then queries factory.getPool() to determine which
    pools actually exist on-chain.  When check_liquidity=True (default), also calls
    pool.liquidity() on factory-verified pools to confirm they have active liquidity.

    Only routes where ``factory_verified=True`` are safe to use as graph edges.

    Args:
        config:           Loaded M8_1Config (from m8_1.stable_anchor.config_loader).
        rpc_url:          HTTP RPC endpoint URL.
        max_workers:      Thread-pool size for parallel eth_call requests.
        request_delay_s:  Per-request sleep (seconds) to respect RPC rate limits.
        check_liquidity:  When True (default), call pool.liquidity() on verified pools.

    Returns:
        List of route dicts, one per (dex, pair, fee) candidate.
        ``factory_verified=True`` → pool exists with liquidity; ``False`` → quarantined.
    """
    # Build token symbol → address / decimals maps
    token_map: Dict[str, str] = {sym: tc.address for sym, tc in config.tokens.items()}
    token_syms = sorted(token_map.keys())

    # Build candidate list: one entry per (dex, pair, fee_or_spacing) combo
    # Each entry is a kwargs dict for _verify_one
    candidates: List[Dict[str, Any]] = []

    # Step 9 (GPT): collect quarantine records for unsupported adapter_types
    # so they appear explicitly in the reject histogram with UNSUPPORTED_DEX_TYPE.
    unsupported_routes: List[Dict[str, Any]] = []

    for dex_id, dex_cfg in config.dexes.items():
        if not dex_cfg.enabled:
            continue
        factory_addr = dex_cfg.factory
        adapter_type = dex_cfg.adapter_type
        zero = "0x" + "0" * 40

        if not factory_addr or factory_addr == zero:
            logger.debug("Skipping dex %s: no factory address configured", dex_id)
            continue

        # Adapter types with on-chain factory queries implemented
        supported = {
            "uniswap_v3",
            "aerodrome_slipstream",
            "uniswap_v2",          # Step 5: getPair(address,address) — no fee
            "ve33",                # Step 6: getPool(address,address,bool=False)
            "aerodrome_v2_stable", # Step 6: getPool(address,address,bool=True)
        }
        # V4: pools are discovered dynamically via M8 sniper Initialize events.
        # Skip static fee-tier enumeration — factory_verified is set by bridge_builder.
        if adapter_type == "uniswap_v4":
            logger.info(
                "dex %s: uniswap_v4 pools discovered dynamically via M8 sniper; "
                "skipping static enumeration",
                dex_id,
            )
            continue
        if adapter_type not in supported:
            # Determine specific quarantine reason (V4 pending vs truly unknown)
            if adapter_type in _PENDING_QUOTE_ADAPTERS:
                qr = "NO_V4_QUOTE_ADAPTER_PENDING_P3"
                log_msg = (
                    "dex %s adapter_type=%s: V4 quote adapter pending (P3); "
                    "tagging all pairs as NO_V4_QUOTE_ADAPTER_PENDING_P3"
                )
            else:
                qr = "UNSUPPORTED_DEX_TYPE"
                log_msg = (
                    "dex %s adapter_type=%s: factory query not supported; "
                    "tagging all pairs as UNSUPPORTED_DEX_TYPE"
                )
            logger.warning(log_msg, dex_id, adapter_type)
            # Emit explicit quarantine records instead of silently skipping
            for i, sym_a in enumerate(token_syms):
                for sym_b in token_syms[i + 1:]:
                    pair_sym = f"{sym_a}_{sym_b}"
                    unsupported_routes.append({
                        "route_id": f"{dex_id}:UNSUPPORTED",
                        "pair_id": pair_sym,
                        "dex_id": dex_id,
                        "adapter_type": adapter_type,
                        "token0": sym_a,
                        "token1": sym_b,
                        "token0_addr": token_map.get(sym_a, _ZERO_ADDR),
                        "token1_addr": token_map.get(sym_b, _ZERO_ADDR),
                        "fee": None,
                        "tick_spacing": None,
                        "factory_address": factory_addr,
                        "pool_address": _ZERO_ADDR,
                        "verified_at_block": "latest",
                        "factory_verified": False,
                        "factory_match": None,
                        "token_match": None,
                        "fee_match": None,
                        "liquidity_ok": None,
                        "status": "quarantined",
                        "quarantine_reason": qr,
                    })
            continue

        # Fee tiers or tick spacings to probe
        if adapter_type == "aerodrome_slipstream":
            fee_or_spacing_list = list(dex_cfg.tick_spacings) or [1, 50, 100, 200]
        elif adapter_type in {"uniswap_v2", "ve33", "aerodrome_v2_stable"}:
            # Single candidate per pair: V2/ve33 do not have multiple fee tiers
            fee_or_spacing_list = [0]
        else:
            fee_or_spacing_list = list(dex_cfg.fee_tiers) or [100, 500, 3000, 10000]

        # Generate all sorted token pairs (no self-pairs)
        for i, sym_a in enumerate(token_syms):
            for sym_b in token_syms[i + 1:]:
                pair_sym = f"{sym_a}_{sym_b}"
                addr_a = token_map[sym_a]
                addr_b = token_map[sym_b]
                for fee_or_spacing in fee_or_spacing_list:
                    candidates.append(
                        dict(
                            factory_addr=factory_addr,
                            token_a_addr=addr_a,
                            token_b_addr=addr_b,
                            fee_or_spacing=int(fee_or_spacing),
                            adapter_type=adapter_type,
                            rpc_url=rpc_url,
                            dex_id=dex_id,
                            pair_sym=pair_sym,
                            token_a_sym=sym_a,
                            token_b_sym=sym_b,
                            request_delay_s=request_delay_s,
                            check_liquidity=check_liquidity,
                        )
                    )

    logger.info(
        "pool_verifier: probing %d (dex, pair, fee) candidates "
        "via factory eth_call (workers=%d)",
        len(candidates), max_workers,
    )

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_key = {
            executor.submit(_verify_one, **kw): (kw["dex_id"], kw["pair_sym"], kw["fee_or_spacing"])
            for kw in candidates
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.error("Verifier error for %s: %s", key, exc)

    verified_count = sum(1 for r in results if r.get("factory_verified"))
    quarantined_count = len(results) - verified_count
    # Step 9 (GPT): append UNSUPPORTED_DEX_TYPE quarantine records
    results.extend(unsupported_routes)
    if unsupported_routes:
        logger.info(
            "pool_verifier: %d routes tagged UNSUPPORTED_DEX_TYPE (V2/ve33 or unknown adapter)",
            len(unsupported_routes),
        )
    logger.info(
        "pool_verifier: %d verified (pool exists), %d quarantined, %d total candidates "
        "(%d UNSUPPORTED_DEX_TYPE)",
        verified_count, quarantined_count, len(results), len(unsupported_routes),
    )
    return results


# ---------------------------------------------------------------------------
# Public API: re-verify existing inventory routes
# ---------------------------------------------------------------------------

def verify_inventory_routes(
    routes: List[Dict[str, Any]],
    rpc_url: str,
    *,
    max_workers: int = 4,
    request_delay_s: float = 0.0,
    check_liquidity: bool = True,
) -> List[Dict[str, Any]]:
    """Re-verify existing inventory routes against their factory contracts.

    For routes that carry ``factory_address``, ``token0_addr``, and ``token1_addr``,
    calls factory.getPool() and sets ``factory_verified`` accordingly.
    When check_liquidity=True (default), also calls pool.liquidity() on verified pools.
    Routes missing these fields are marked with ``quarantine_reason=MISSING_FACTORY_ADDRESS``
    or ``MISSING_TOKEN_ADDRESS``.

    Returns updated route dicts (original dicts are not mutated).
    """

    def _verify_route(idx: int, route: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        route = dict(route)  # shallow copy — do not mutate caller's dict

        factory_addr = route.get("factory_address")
        token0_addr = route.get("token0_addr")
        token1_addr = route.get("token1_addr")
        adapter_type = route.get("adapter_type", "uniswap_v3")
        fee = int(route.get("fee", 0))
        tick_spacing = route.get("tick_spacing")
        fee_or_spacing = (
            int(tick_spacing)
            if adapter_type == "aerodrome_slipstream" and tick_spacing is not None
            else fee
        )

        zero = "0x" + "0" * 40

        if not factory_addr or factory_addr == zero:
            route["factory_verified"] = False
            route["quarantine_reason"] = "MISSING_FACTORY_ADDRESS"
            route.setdefault("status", "unverified")
            route["verified_at_block"] = None
            return idx, route

        if not token0_addr or not token1_addr:
            route["factory_verified"] = False
            route["quarantine_reason"] = "MISSING_TOKEN_ADDRESS"
            route.setdefault("status", "unverified")
            route["verified_at_block"] = None
            return idx, route

        calldata = _build_factory_calldata(
            token0_addr, token1_addr, fee_or_spacing, adapter_type
        )
        result = _eth_call(rpc_url, factory_addr, calldata, request_delay_s=request_delay_s)

        if result is None:
            route["factory_verified"] = False
            route["quarantine_reason"] = "FACTORY_RPC_ERROR"
            route.setdefault("status", "unverified")
        else:
            returned_pool = _decode_addr_result(result)
            if returned_pool == zero:
                route["factory_verified"] = False
                route["quarantine_reason"] = "FACTORY_NO_POOL"
                route["status"] = "quarantined"
            else:
                route["pool_address"] = returned_pool
                route["verified_at_block"] = "latest"
                # P2: check liquidity
                if check_liquidity:
                    liq_ok = _check_liquidity_ok(rpc_url, returned_pool, request_delay_s)
                    route["liquidity_ok"] = liq_ok
                    if liq_ok is False:
                        route["factory_verified"] = False
                        route["quarantine_reason"] = "POOL_ZERO_LIQUIDITY"
                        route["status"] = "quarantined"
                    else:
                        route["factory_verified"] = True
                        route["quarantine_reason"] = None
                        route["status"] = "active"
                else:
                    route["factory_verified"] = True
                    route["quarantine_reason"] = None
                    route["status"] = "active"

        route["verified_at_block"] = "latest"
        return idx, route

    results_by_idx: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(_verify_route, i, r): i
            for i, r in enumerate(routes)
        }
        for future in as_completed(future_to_idx):
            i = future_to_idx[future]
            try:
                _, updated = future.result()
                results_by_idx[i] = updated
            except Exception as exc:
                logger.error("Route re-verify error idx=%d: %s", i, exc)
                fallback = dict(routes[i])
                fallback["factory_verified"] = False
                fallback["quarantine_reason"] = "VERIFIER_EXCEPTION"
                results_by_idx[i] = fallback

    return [results_by_idx[i] for i in range(len(routes))]


# ---------------------------------------------------------------------------
# Write verified inventory to disk
# ---------------------------------------------------------------------------

def write_verified_inventory(
    routes: List[Dict[str, Any]],
    output_path: str = _OUTPUT_PATH,
    source_inventory_path: Optional[str] = None,
) -> None:
    """Write verified routes to a JSON inventory file.

    Active routes (factory_verified=True) go into ``active_routes``.
    Quarantined / unverified routes go into ``quarantined_routes``.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    active = [r for r in routes if r.get("factory_verified")]
    quarantined = [r for r in routes if not r.get("factory_verified")]

    inventory = {
        "schema_version": "m9_verified_inventory.1",
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "source_inventory": source_inventory_path,
        "total_candidates": len(routes),
        "active_routes": active,
        "quarantined_routes": quarantined,
        "summary": {
            "active_count": len(active),
            "quarantined_count": len(quarantined),
            "quarantine_reasons": _count_quarantine_reasons(quarantined),
        },
    }

    tmp = str(path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(inventory, fh, indent=2)
        os.replace(tmp, str(path))
    except PermissionError:
        import time as _t
        _t.sleep(0.5)
        os.replace(tmp, str(path))

    # Write separate reject histogram for quick CI and monitoring access
    _write_reject_histogram(quarantined, output_path)

    logger.info(
        "pool_verifier: verified inventory written to %s "
        "(%d active, %d quarantined)",
        output_path, len(active), len(quarantined),
    )


def _write_reject_histogram(
    quarantined: List[Dict[str, Any]],
    output_path: str,
) -> None:
    """Write a reject histogram JSON alongside the verified inventory.

    Maps canonical reason names (FACTORY_RPC_ERROR etc.) and normalized aliases
    (rpc_error, pool_not_found, low_liquidity, missing_factory, token_mismatch)
    into a standalone file for CI and monitoring.
    """
    _REASON_ALIASES: Dict[str, str] = {
        "FACTORY_RPC_ERROR": "rpc_error",
        "FACTORY_NO_POOL": "pool_not_found",
        "POOL_ZERO_LIQUIDITY": "low_liquidity",
        "MISSING_FACTORY_ADDRESS": "missing_factory",
        "MISSING_TOKEN_ADDRESS": "token_mismatch",
        "FEE_MISMATCH": "fee_mismatch",
        "UNSUPPORTED_DEX_TYPE": "unsupported_dex_type",  # Step 9 (GPT)
        "NO_V4_QUOTE_ADAPTER_PENDING_P3": "v4_pending_p3",  # Step 4 (GPT)
    }
    histogram = _count_quarantine_reasons(quarantined)
    normalized: Dict[str, int] = {}
    for raw_reason, count in histogram.items():
        key = _REASON_ALIASES.get(raw_reason, raw_reason.lower())
        normalized[key] = normalized.get(key, 0) + count

    payload = {
        "schema_version": "m9_verifier_reject_histogram.1",
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "quarantined_count": len(quarantined),
        "histogram": histogram,
        "histogram_normalized": normalized,
    }

    hist_path = Path(output_path).parent / "m9_verifier_reject_histogram.json"
    tmp = str(hist_path) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp, str(hist_path))
        logger.info("pool_verifier: reject histogram written to %s", hist_path)
    except Exception as exc:
        logger.warning("pool_verifier: failed to write reject histogram: %s", exc)


def _count_quarantine_reasons(quarantined: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in quarantined:
        reason = str(r.get("quarantine_reason") or "UNKNOWN")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main(argv: "list[str] | None" = None) -> int:
    """CLI entry-point: py -3.11 -m m9.graph_arb.pool_verifier [args]

    Loads config, resolves RPC, and runs on-chain factory verification for every
    (dex, pair, fee) candidate derived from the config.  Writes a
    ``m9_verified_inventory.json`` artifact that can be consumed by the M9 runner
    via ``--inventory data/tmp/m9_verified_inventory.json``.
    """
    import argparse
    import sys

    from core.env import load_root_dotenv

    load_root_dotenv()

    parser = argparse.ArgumentParser(
        description="M9 on-chain pool verifier: queries factory.getPool() for each candidate.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--chain", default="base", help="Chain identifier (used for RPC lookup)")
    parser.add_argument(
        "--config",
        default="config/exotic_base_anchor.yaml",
        help="M8_1 config YAML (defines DEXes, tokens, fee tiers)",
    )
    parser.add_argument(
        "--output",
        default=_OUTPUT_PATH,
        help="Path to write verified inventory JSON",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Thread-pool size for parallel eth_call requests",
    )
    parser.add_argument(
        "--delay-ms",
        type=float,
        default=0.0,
        help=(
            "Inter-request sleep in milliseconds (rate limiting). "
            "Use 200-500ms on dRPC free tier to avoid HTTP 429."
        ),
    )
    parser.add_argument(
        "--no-liquidity-check",
        action="store_true",
        default=False,
        help="Skip pool.liquidity() check; accept any non-zero factory pool address.",
    )
    parser.add_argument(
        "--require-premium-rpc",
        action="store_true",
        default=bool(os.environ.get("ARBY_REQUIRE_PREMIUM_RPC")),
        help=(
            "Hard-fail if the resolved RPC provider is 'public_fallback' or 'public'. "
            "Also enabled by env ARBY_REQUIRE_PREMIUM_RPC=1."
        ),
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args(argv)

    import logging as _logging
    _logging.basicConfig(
        level=_logging.DEBUG if args.verbose else _logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    log = _logging.getLogger(__name__)

    # Resolve RPC
    rpc_url: Optional[str] = None
    try:
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID

        _chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, rpc_provider, rpc_diag = resolve_rpc_http(
            chain_id=_chain_id,
            network=args.chain,
            env=dict(os.environ),
        )
        log.info(
            "RPC resolved: provider=%s source=%s url=%s",
            rpc_provider,
            rpc_diag.get("source"),
            (rpc_url or "")[:60],
        )
        public_fallback = rpc_provider in ("public", "public_fallback")
        if args.require_premium_rpc and public_fallback:
            log.error(
                "PREMIUM_RPC_REQUIRED: resolved '%s' is a public fallback. "
                "Set BASE_RPC in .env or unset ARBY_REQUIRE_PREMIUM_RPC.",
                rpc_provider,
            )
            return 2
    except Exception as exc:
        log.error("Failed to resolve RPC for chain %s: %s", args.chain, exc)
        return 2

    if not rpc_url:
        log.error("No RPC URL resolved for chain %s", args.chain)
        return 2

    # Load config
    try:
        from m8_1.stable_anchor.config_loader import load_config

        config = load_config(args.config)
        log.info("Config loaded: %s", args.config)
    except Exception as exc:
        log.error("Failed to load config %s: %s", args.config, exc)
        return 2

    # Run verification
    request_delay_s = args.delay_ms / 1000.0
    check_liquidity = not args.no_liquidity_check
    log.info(
        "Starting verification: max_workers=%d delay_ms=%.0f check_liquidity=%s",
        args.max_workers,
        args.delay_ms,
        check_liquidity,
    )
    try:
        routes = verify_candidates_from_config(
            config,
            rpc_url,
            max_workers=args.max_workers,
            request_delay_s=request_delay_s,
            check_liquidity=check_liquidity,
        )
    except Exception as exc:
        log.error("Verification failed: %s", exc)
        return 1

    # Write output
    write_verified_inventory(routes, args.output, source_inventory_path=args.config)
    active = sum(1 for r in routes if r.get("factory_verified"))
    quarantined = len(routes) - active
    log.info(
        "Done: %d active, %d quarantined → %s",
        active,
        quarantined,
        args.output,
    )
    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())
