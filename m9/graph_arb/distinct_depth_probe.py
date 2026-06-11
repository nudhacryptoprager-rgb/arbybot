"""Lightweight depth estimates for distinct-pricing routes (Balancer/Maverick/Curve).

Used when ``effective_depth_usd`` is missing from bridge inventory so productive
lane sizing and OVERSIZED_VS_DEPTH gates can operate on real capacity hints.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

from m9.graph_arb.token_decimals import is_valid_eth_address, resolve_decimals_for_address
from m9.graph_arb.token_price_fetcher import resolve_token_price_usd

log = logging.getLogger(__name__)

_DISTINCT_DEX_IDS = frozenset({"balancer_vault", "balancer_stable", "balancer_weighted", "maverick_v2", "curve_stable"})
_BALANCER_VAULT = "0xba12222222228d8ba445958a75a0704d566bf2c8"
_GET_POOL_TOKENS_SELECTOR = "0xf94d4668"
# Balancer max in-ratio ≈ 30% of pool balance
_BALANCER_MAX_IN_FRACTION = 0.30


def needs_distinct_depth_probe(route: Dict[str, Any]) -> bool:
    dex = str(route.get("dex_id") or route.get("adapter_type") or "")
    if dex not in _DISTINCT_DEX_IDS and not dex.startswith("balancer"):
        return False
    depth = route.get("effective_depth_usd")
    return depth is None


def _decode_uint256_array(raw_hex: str, offset_words: int) -> list:
    raw = raw_hex[2:] if raw_hex.startswith("0x") else raw_hex
    words = [raw[i : i + 64] for i in range(0, len(raw), 64)]
    if len(words) <= offset_words:
        return []
    n = int(words[offset_words], 16)
    base = offset_words + 1
    return [int(words[base + i], 16) for i in range(n)]


def estimate_balancer_depth_usd(
    w3: Any,
    pool_id: str,
    assets: Sequence[str],
    token_prices: Dict[str, float],
    *,
    vault_address: str = _BALANCER_VAULT,
    cfg=None,
    decimals_cache: Optional[Dict[str, int]] = None,
) -> Optional[float]:
    if w3 is None or not pool_id or not assets:
        return None
    try:
        pid = pool_id.lower()
        if not pid.startswith("0x"):
            pid = "0x" + pid
        data = _GET_POOL_TOKENS_SELECTOR + pid[2:].rjust(64, "0")
        from web3 import Web3

        vault = Web3.to_checksum_address(vault_address or _BALANCER_VAULT)
        result = w3.eth.call({"to": vault, "data": data})
        if isinstance(result, bytes):
            hex_res = "0x" + result.hex()
        else:
            hex_res = result if str(result).startswith("0x") else "0x" + str(result)
        balances = _decode_uint256_array(hex_res, 1)
        if not balances:
            return None
        asset_list = [str(a).lower() for a in assets]
        if len(balances) != len(asset_list):
            asset_list = asset_list[: len(balances)]
        usd_caps = []
        for addr, bal_raw in zip(asset_list, balances):
            dec = resolve_decimals_for_address(
                addr, cfg=cfg, cache=decimals_cache, w3=None,
            ) or 18
            price = resolve_token_price_usd(addr, "", token_prices)
            if price is None or price <= 0:
                continue
            human = bal_raw / (10 ** dec)
            usd_caps.append(human * price * _BALANCER_MAX_IN_FRACTION)
        if not usd_caps:
            return None
        return round(min(usd_caps), 4)
    except Exception as exc:
        log.debug("balancer depth probe failed pool_id=%s: %s", (pool_id or "")[:18], exc)
        return None


def enrich_route_depth_if_missing(
    route: Dict[str, Any],
    w3: Any,
    token_prices: Dict[str, float],
    *,
    cfg=None,
    decimals_cache: Optional[Dict[str, int]] = None,
) -> Optional[float]:
    """Probe and set ``effective_depth_usd`` when absent; return depth or None."""
    if not needs_distinct_depth_probe(route):
        existing = route.get("effective_depth_usd")
        return float(existing) if existing is not None else None

    dex = str(route.get("dex_id") or "")
    adapter = str(route.get("adapter_type") or "")
    depth: Optional[float] = None

    if dex in ("balancer_vault", "balancer_stable", "balancer_weighted") or adapter.startswith("balancer"):
        assets = route.get("balancer_assets") or []
        if not assets:
            a0, a1 = route.get("token0_addr"), route.get("token1_addr")
            assets = [x for x in (a0, a1) if is_valid_eth_address(x)]
        depth = estimate_balancer_depth_usd(
            w3,
            str(route.get("pool_id") or ""),
            assets,
            token_prices,
            vault_address=str(route.get("vault_address") or _BALANCER_VAULT),
            cfg=cfg,
            decimals_cache=decimals_cache,
        )

    if depth is None and dex == "maverick_v2":
        depth = estimate_maverick_depth_usd(
            route, token_prices, cfg=cfg, decimals_cache=decimals_cache
        )

    if depth is None and dex == "curve_stable":
        depth = None

    if depth is not None and depth > 0:
        route["effective_depth_usd"] = depth
        route["depth_probe_ok"] = True
        route["depth_probe_source"] = "distinct_depth_probe"
        route["depth_status"] = "MEASURED"
    elif needs_distinct_depth_probe(route):
        route["depth_status"] = "UNKNOWN"
        route["depth_probe_ok"] = False
    return depth


def estimate_maverick_depth_usd(
    route: Dict[str, Any],
    token_prices: Dict[str, float],
    *,
    cfg=None,
    decimals_cache: Optional[Dict[str, int]] = None,
) -> Optional[float]:
    """Direction-aware Maverick depth from pool-lane verified quote range."""
    max_raw = route.get("maverick_max_quoteable_amount_raw") or route.get(
        "maverick_pool_lane_probe_amount"
    )
    token_in = (
        route.get("maverick_pool_lane_token_in")
        or route.get("token_a")
        or route.get("token0_addr")
    )
    if not max_raw or not is_valid_eth_address(str(token_in or "")):
        return None
    dec = (
        resolve_decimals_for_address(
            str(token_in), cfg=cfg, cache=decimals_cache, w3=None
        )
        or 18
    )
    price = resolve_token_price_usd(str(token_in), "", token_prices)
    if price is None or price <= 0:
        return None
    human = int(max_raw) / (10 ** int(dec))
    return round(human * float(price), 4)
