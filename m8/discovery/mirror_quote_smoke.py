"""Quote-smoke for M8.2 same-pair mirror routes (2-leg lane economics admission)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set, Tuple

_ANCHOR_SYMS = frozenset({"WETH", "USDC", "USDbC", "DAI"})
_SKIP_STATUSES = frozenset({"", "NOT_RUN", "SKIPPED_REGISTRY"})
_V3_ADAPTERS = frozenset(
    {"uniswap_v3", "pancakeswap_v3", "sushiswap_v3", "aerodrome_slipstream"}
)


def _status_quoteable(status: str) -> bool:
    upper = str(status or "").upper()
    return any(upper.startswith(p) for p in ("QUOTE_OK", "OK", "PASS", "SUCCESS", "INDEXED"))


def is_same_pair_mirror_route(route: Dict[str, Any]) -> bool:
    focus_sym = str(route.get("focus_token_symbol") or "")
    if not focus_sym:
        return False
    t0 = str(route.get("token0") or "")
    t1 = str(route.get("token1") or "")
    anchor = t1 if t0 == focus_sym else t0 if t1 == focus_sym else ""
    return anchor in _ANCHOR_SYMS


def _needs_smoke(route: Dict[str, Any]) -> bool:
    if _status_quoteable(str(route.get("quote_smoke_status") or route.get("quote_smoke") or "")):
        return False
    status = str(route.get("quote_smoke_status") or route.get("quote_smoke") or "").upper()
    return status in _SKIP_STATUSES or status == "NOT_RUN"


def _dex_quoter(config: Dict[str, Any], dex_id: str) -> str:
    dex = ((config or {}).get("dexes") or {}).get(dex_id) or {}
    return str(dex.get("quoter") or "")


def _smoke_v3_route(
    route: Dict[str, Any],
    *,
    rpc_url: str,
    quoter: str,
) -> str:
    from strategy.quote_rpc import read_quoter_v2

    focus_addr = str(
        route.get("focus_token_address") or route.get("exotic_address") or ""
    ).lower()
    t0a = str(route.get("token0_addr") or "").lower()
    t1a = str(route.get("token1_addr") or "").lower()
    if focus_addr == t0a:
        token_in, token_out = t0a, t1a
    elif focus_addr == t1a:
        token_in, token_out = t1a, t0a
    else:
        return "QUOTE_FAIL_TOKEN_DIRECTION"
    fee = int(route.get("fee") or 3000)
    amount_in = 10**15
    result = read_quoter_v2(
        quoter,
        token_in,
        token_out,
        amount_in,
        fee,
        rpc_url,
        "latest",
    )
    if result is None:
        return "QUOTE_FAIL_NO_RPC"
    if isinstance(result, dict) and int(result.get("amount_out") or 0) > 0:
        return "QUOTE_OK_MIRROR_SMOKE"
    return "QUOTE_FAIL_ZERO_OUT"


def _smoke_v2_route(route: Dict[str, Any], *, rpc_url: str) -> str:
    from web3 import Web3

    pool = str(route.get("pool_address") or "")
    if not pool:
        return "QUOTE_FAIL_NO_POOL"
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
    data = w3.eth.call({"to": Web3.to_checksum_address(pool), "data": "0x0902f1ac"})
    raw = data.hex()[2:] if hasattr(data, "hex") else str(data)[2:]
    if len(raw) < 128:
        return "QUOTE_FAIL_RESERVES"
    r0 = int(raw[:64], 16)
    r1 = int(raw[64:128], 16)
    if r0 <= 0 or r1 <= 0:
        return "QUOTE_FAIL_ZERO_RESERVES"
    return "QUOTE_OK_MIRROR_SMOKE"


def smoke_mirror_same_pair_routes(
    routes: List[Dict[str, Any]],
    *,
    chain: str,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run lightweight quoter smoke on same-pair mirror routes; mutates routes in place."""
    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        return {
            "attempted": 0,
            "quote_ok": 0,
            "skipped": len(routes),
            "reason": "SKIPPED_DRY_RUN",
        }

    from core.rpc_urls import get_rpc_url

    rpc_url = get_rpc_url(chain)
    if not rpc_url:
        return {"attempted": 0, "quote_ok": 0, "skipped": 0, "reason": "NO_RPC"}

    attempted = 0
    quote_ok = 0
    by_status: Dict[str, int] = {}
    for route in routes:
        if not is_same_pair_mirror_route(route) or not _needs_smoke(route):
            continue
        attempted += 1
        adapter = str(route.get("adapter_type") or "")
        dex_id = str(route.get("dex_id") or "")
        try:
            if adapter in _V3_ADAPTERS:
                quoter = _dex_quoter(config or {}, dex_id)
                status = (
                    _smoke_v3_route(route, rpc_url=rpc_url, quoter=quoter)
                    if quoter
                    else "QUOTE_FAIL_NO_QUOTER"
                )
            elif adapter in ("uniswap_v2", "ve33", "aerodrome_v2_stable"):
                status = _smoke_v2_route(route, rpc_url=rpc_url)
            else:
                status = "QUOTE_SKIP_UNSUPPORTED_ADAPTER"
        except Exception as exc:
            status = f"QUOTE_FAIL_{type(exc).__name__}"
        route["quote_smoke_status"] = status
        route["quote_smoke"] = status
        by_status[status] = by_status.get(status, 0) + 1
        if _status_quoteable(status):
            quote_ok += 1

    return {
        "attempted": attempted,
        "quote_ok": quote_ok,
        "by_status": by_status,
        "reason": "OK",
    }


def aggregate_mirror_readiness_from_routes(
    routes: List[Dict[str, Any]],
) -> Tuple[int, int, int, List[Dict[str, Any]]]:
    """Recompute mirror token counts from admitted routes after quote smoke."""
    from m8.discovery.cross_dex_expand import (
        _same_pair_route_quoteable,
        evaluate_mirror_readiness,
    )

    by_focus: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        if not is_same_pair_mirror_route(route):
            continue
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if not focus.startswith("0x"):
            continue
        bucket = by_focus.setdefault(
            focus,
            {"dexes": set(), "same_pair": [], "symbol": route.get("focus_token_symbol")},
        )
        dex = str(route.get("dex_id") or "")
        if dex:
            bucket["dexes"].add(dex)
        bucket["same_pair"].append(route)

    topology = quote = same_pair = 0
    debug: List[Dict[str, Any]] = []
    for focus, info in by_focus.items():
        same = info["same_pair"]
        dexes: Set[str] = {str(r.get("dex_id") or "") for r in same if r.get("dex_id")}
        quoteable = sum(1 for r in same if _same_pair_route_quoteable(r))
        mr = evaluate_mirror_readiness(
            token_seen_on_dexes=len(info["dexes"]),
            same_pair_routes=len(same),
            same_pair_dexes=len(dexes),
            quoteable_same_pair_routes=quoteable,
        )
        if mr["same_pair_mirror_token"]:
            same_pair += 1
        if mr["mirror_topology_ready"]:
            topology += 1
        if mr["mirror_quote_ready"]:
            quote += 1
        if mr["same_pair_mirror_token"] and len(debug) < 64:
            debug.append(
                {
                    "token_address": focus,
                    "token_symbol": info.get("symbol"),
                    "token_seen_on_dexes": mr["token_seen_on_dexes"],
                    "same_pair_routes": mr["same_pair_routes"],
                    "same_pair_dexes": mr["same_pair_dexes"],
                    "quoteable_same_pair_routes": quoteable,
                    "mirror_topology_ready": mr["mirror_topology_ready"],
                    "mirror_quote_ready": mr["mirror_quote_ready"],
                    "missing_reason": mr["missing_reason"],
                    "quote_statuses": sorted(
                        {
                            str(r.get("quote_smoke_status") or r.get("quote_smoke") or "")
                            for r in same
                        }
                    ),
                }
            )
    return topology, quote, same_pair, debug
