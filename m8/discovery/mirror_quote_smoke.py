"""Quote-smoke for M8.2 same-pair mirror routes (2-leg lane economics admission)."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MIRROR_CHECKPOINT_PATH = "data/tmp/m8_mirror_quote_smoke_progress.json"
_INFRA_RPC_REASONS = frozenset(
    {
        "NO_RPC",
        "RPC_CONFIG_MISSING",
        "RPC_CONFIG_PUBLIC_BLOCKED",
        "RPC_CONFIG_ERROR",
    }
)

def _anchor_syms() -> frozenset:
    """Mirror anchors: generic stable/WETH plus launchpad lane (VIRTUAL)."""
    from m8.discovery.mirror_anchors import ALL_MIRROR_ANCHOR_SYMS

    try:
        from m8.discovery.pending_pair_registry import _ANCHOR_TOKENS

        return frozenset(set(_ANCHOR_TOKENS) | set(ALL_MIRROR_ANCHOR_SYMS) | {"USDbC"})
    except Exception:
        return frozenset(set(ALL_MIRROR_ANCHOR_SYMS) | {"USDbC"})


_ANCHOR_SYMS = _anchor_syms()
_SKIP_STATUSES = frozenset({"", "NOT_RUN", "SKIPPED_REGISTRY"})
_V3_ADAPTERS = frozenset(
    {"uniswap_v3", "pancakeswap_v3", "sushiswap_v3", "aerodrome_slipstream"}
)


def _native_eth_addr() -> str:
    return "0x" + ("0" * 40)


def _base_anchor_addrs() -> Dict[str, str]:
    from core.token_identity import address_symbol_map

    out: Dict[str, str] = {}
    for addr, sym in address_symbol_map("base").items():
        if sym in _ANCHOR_SYMS:
            out[sym] = addr
    return out


_NATIVE_ETH = _native_eth_addr()
# Backward-compat module constant: external callers (cross_dex_expand) import
# this name directly. Kept in sync with the config-sourced loader.
_BASE_ANCHOR_ADDRS = _base_anchor_addrs()


def _status_quoteable(status: str) -> bool:
    upper = str(status or "").upper()
    return any(upper.startswith(p) for p in ("QUOTE_OK", "OK", "PASS", "SUCCESS", "INDEXED"))


def _is_anchor_address(addr: str) -> bool:
    low = str(addr or "").lower()
    if not low.startswith("0x") or len(low) != 42:
        return False
    return low in set(_base_anchor_addrs().values())


def is_same_pair_mirror_route(route: Dict[str, Any]) -> bool:
    """Same focus token paired with any approved anchor (same or cross-anchor)."""
    return is_cross_anchor_mirror_route(route)


def is_cross_anchor_mirror_route(route: Dict[str, Any]) -> bool:
    focus_sym = str(route.get("focus_token_symbol") or "")
    focus_addr = str(
        route.get("focus_token_address") or route.get("exotic_address") or ""
    ).lower()
    t0 = str(route.get("token0") or "")
    t1 = str(route.get("token1") or "")
    t0a = _normalize_eth_alias(str(route.get("token0_addr") or ""), t0)
    t1a = _normalize_eth_alias(str(route.get("token1_addr") or ""), t1)

    if focus_sym and not focus_sym.lower().startswith("0x"):
        anchor = t1 if t0 == focus_sym else t0 if t1 == focus_sym else ""
        if anchor in _ANCHOR_SYMS:
            return True

    if focus_addr.startswith("0x"):
        if not t0a or not t1a:
            t0a, t1a = resolve_route_token_addrs(route)
        other = ""
        if t0a == focus_addr:
            other = t1a
        elif t1a == focus_addr:
            other = t0a
        if other and _is_anchor_address(other):
            return True
    return False


def _normalize_eth_alias(addr: str, symbol: str) -> str:
    low = str(addr or "").lower()
    if low in ("", _native_eth_addr()) and symbol.upper() == "WETH":
        return _base_anchor_addrs().get("WETH", low)
    return low


def resolve_route_token_addrs(
    route: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Backfill token0/token1 addresses for mirror quote smoke."""
    t0s = str(route.get("token0") or "")
    t1s = str(route.get("token1") or "")
    t0a = _normalize_eth_alias(str(route.get("token0_addr") or ""), t0s)
    t1a = _normalize_eth_alias(str(route.get("token1_addr") or ""), t1s)

    tokens = ((config or {}).get("tokens") or {})
    focus = str(
        route.get("focus_token_address") or route.get("exotic_address") or ""
    ).lower()
    focus_sym = str(route.get("focus_token_symbol") or "")

    def _sym_addr(sym: str) -> str:
        row = tokens.get(sym) or {}
        return str(row.get("address") or _base_anchor_addrs().get(sym, "")).lower()

    if not t0a:
        if t0s == focus_sym and focus:
            t0a = focus
        elif t0s in _base_anchor_addrs():
            t0a = _base_anchor_addrs()[t0s]
        else:
            t0a = _sym_addr(t0s)
    if not t1a:
        if t1s == focus_sym and focus:
            t1a = focus
        elif t1s in _base_anchor_addrs():
            t1a = _base_anchor_addrs()[t1s]
        else:
            t1a = _sym_addr(t1s)

    t0a = _normalize_eth_alias(t0a, t0s)
    t1a = _normalize_eth_alias(t1a, t1s)
    return t0a, t1a


def _needs_smoke(route: Dict[str, Any], *, force_retry: bool = False) -> bool:
    status = str(route.get("quote_smoke_status") or route.get("quote_smoke") or "")
    if _status_quoteable(status):
        return False
    if force_retry:
        upper = status.upper()
        if not upper or upper in _SKIP_STATUSES:
            return True
        return upper.startswith("QUOTE_FAIL") or upper == "QUOTE_SKIP_UNSUPPORTED_ADAPTER"
    return status.upper() in _SKIP_STATUSES or status.upper() == "NOT_RUN"


def _dex_quoter(config: Dict[str, Any], dex_id: str) -> str:
    dex = ((config or {}).get("dexes") or {}).get(dex_id) or {}
    return str(dex.get("quoter") or "")


def _smoke_v3_liquidity_fallback(route: Dict[str, Any], *, rpc_url: str) -> Optional[str]:
    """When quoter returns empty, accept pools with on-chain liquidity > 0."""
    from web3 import Web3

    pool = str(route.get("pool_address") or "")
    if not pool or len(pool) != 42:
        return None
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
    pool_cs = Web3.to_checksum_address(pool)
    try:
        slot0 = w3.eth.call({"to": pool_cs, "data": "0x3850c7bd"})
        liq = w3.eth.call({"to": pool_cs, "data": "0x1a686502"})
        sqrt_raw = int(slot0.hex()[2:66], 16) if hasattr(slot0, "hex") else 0
        liq_raw = int(liq.hex()[2:66], 16) if hasattr(liq, "hex") else 0
        if sqrt_raw > 0 and liq_raw > 0:
            return "QUOTE_OK_MIRROR_LIQUIDITY"
    except Exception:
        return None
    return None


def _smoke_v3_route(
    route: Dict[str, Any],
    *,
    rpc_url: str,
    quoter: str,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    from strategy.quote_rpc import read_quoter_v2

    focus_addr = str(
        route.get("focus_token_address") or route.get("exotic_address") or ""
    ).lower()
    t0a, t1a = resolve_route_token_addrs(route, config)
    if focus_addr == t0a:
        token_in, token_out = t0a, t1a
    elif focus_addr == t1a:
        token_in, token_out = t1a, t0a
    else:
        return "QUOTE_FAIL_TOKEN_DIRECTION"
    if not token_in or not token_out:
        return "QUOTE_FAIL_TOKEN_DIRECTION"
    fee_raw = route.get("fee")
    if fee_raw is not None and int(fee_raw) > 0:
        fees_to_try = [int(fee_raw)]
    else:
        from discovery.index_factories import get_dex_fee_tiers

        dex_id = str(route.get("dex_id") or "uniswap_v3")
        fees_to_try = list(get_dex_fee_tiers("base", dex_id)[:4]) or [3000, 10000, 500, 100]
    amount_in = 10**15
    last_result = None
    for fee in fees_to_try:
        result = read_quoter_v2(
            quoter,
            token_in,
            token_out,
            amount_in,
            fee,
            rpc_url,
            "latest",
        )
        last_result = result
        if isinstance(result, dict) and int(result.get("amount_out") or 0) > 0:
            route["fee"] = fee
            return "QUOTE_OK_MIRROR_SMOKE"
    fallback = _smoke_v3_liquidity_fallback(route, rpc_url=rpc_url)
    if fallback:
        if fees_to_try:
            route["fee"] = fees_to_try[0]
        return fallback
    if last_result is None:
        return "QUOTE_FAIL_ZERO_OUT"
    return "QUOTE_FAIL_ZERO_OUT"


def _smoke_v4_liquidity_fallback(route: Dict[str, Any], *, rpc_url: str) -> Optional[str]:
    from m8.discovery.hint_verifier import (
        _SEL_V4_GET_LIQUIDITY,
        _V4_STATEVIEW_BASE,
        _eth_call,
        is_bytes32_hex,
    )

    pool_id = str(route.get("pool_id") or route.get("pool_address") or "").lower()
    if not is_bytes32_hex(pool_id):
        return None
    data = "0x" + _SEL_V4_GET_LIQUIDITY + pool_id[2:].zfill(64)
    result = _eth_call(rpc_url, _V4_STATEVIEW_BASE, data)
    if result and int(result, 16) > 0:
        return "QUOTE_OK_MIRROR_LIQUIDITY"
    return None


def _smoke_v4_route(
    route: Dict[str, Any],
    *,
    rpc_url: str,
    quoter: str,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    from web3 import Web3
    from m8_1.stable_anchor.quote_probe import _decode_v4_response, _encode_v4_call

    focus_addr = str(
        route.get("focus_token_address") or route.get("exotic_address") or ""
    ).lower()
    t0a, t1a = resolve_route_token_addrs(route, config)
    if focus_addr == t0a:
        token_in, token_out = t0a, t1a
    elif focus_addr == t1a:
        token_in, token_out = t1a, t0a
    else:
        return "QUOTE_FAIL_TOKEN_DIRECTION"
    if not token_in or not token_out:
        return "QUOTE_FAIL_TOKEN_DIRECTION"
    fee = int(route.get("fee") or 3000)
    tick_spacing = int(route.get("tick_spacing") or 60)
    hooks = route.get("hooks")
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
    for amount_in in (10**15, 10**12, 10**9):
        try:
            calldata, _zfo = _encode_v4_call(
                token_in, token_out, fee, tick_spacing, hooks, amount_in
            )
            result = w3.eth.call(
                {"to": Web3.to_checksum_address(quoter), "data": calldata}
            )
            raw = result.hex() if hasattr(result, "hex") else str(result)
            amount_out, _gas = _decode_v4_response(
                raw if raw.startswith("0x") else "0x" + raw, True
            )
            if amount_out > 0:
                return "QUOTE_OK_MIRROR_SMOKE"
        except Exception:
            continue
    fallback = _smoke_v4_liquidity_fallback(route, rpc_url=rpc_url)
    if fallback:
        return fallback
    return "QUOTE_FAIL_REVERT"


def _smoke_v2_route(route: Dict[str, Any], *, rpc_url: str) -> str:
    from web3 import Web3

    pool = str(route.get("pool_address") or "")
    if not pool or len(pool) > 66:
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


def resolve_mirror_smoke_rpc_url(
    chain: str,
    *,
    pipeline_mode: bool = False,
) -> Tuple[Optional[str], str]:
    """Resolve RPC for mirror smoke. Pipeline mode requires productive non-public RPC."""
    pipeline = pipeline_mode or os.environ.get("ARBY_MIRROR_SMOKE_PIPELINE", "").strip() in (
        "1",
        "true",
        "yes",
    )
    if pipeline:
        try:
            from core.rpc_urls import (
                apply_productive_rpc_env,
                is_public_rpc_url,
                resolve_productive_http_rpc,
            )

            env = apply_productive_rpc_env(chain)
            url = resolve_productive_http_rpc(chain, env=env)
            if not url:
                return None, "RPC_CONFIG_MISSING"
            if is_public_rpc_url(url):
                return None, "RPC_CONFIG_PUBLIC_BLOCKED"
            return url, "OK"
        except Exception as exc:
            return None, f"RPC_CONFIG_ERROR_{type(exc).__name__}"

    from core.rpc_urls import get_rpc_url

    url = get_rpc_url(chain)
    if not url:
        return None, "NO_RPC"
    return url, "OK"


def write_mirror_checkpoint(path: str | Path, payload: Dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload.setdefault("schema_version", "m8_mirror_quote_smoke_progress_v1")
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def classify_mirror_smoke_exit(*, quote_ok: int, reason: str) -> Tuple[int, str]:
    """0=quote_ready, 2=no_quote_ready_market, 1=infra_or_code_fail."""
    upper = str(reason or "").upper()
    if any(upper.startswith(r) for r in _INFRA_RPC_REASONS) or "RPC_CONFIG" in upper:
        return 1, "infra"
    if int(quote_ok) > 0:
        return 0, "quote_ready"
    return 2, "no_quote_ready"


def _focus_token_lc(route: Dict[str, Any]) -> str:
    return str(
        route.get("focus_token_address") or route.get("exotic_address") or ""
    ).lower()


def filter_routes_for_token_subset(
    routes: List[Dict[str, Any]],
    *,
    token_subset: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    if not token_subset:
        return routes
    return [r for r in routes if _focus_token_lc(r) in token_subset]


def load_token_subset_from_path(path: str | Path) -> Optional[set[str]]:
    from m8.discovery.token_subset import load_token_subset_file

    return load_token_subset_file(path)


def smoke_mirror_same_pair_routes(
    routes: List[Dict[str, Any]],
    *,
    chain: str,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    force_retry: bool = False,
    pipeline_mode: bool = False,
    checkpoint_path: Optional[str] = None,
    progress_every: int = 5,
    token_subset: Optional[set[str]] = None,
    quote_workers: int = 4,
) -> Dict[str, Any]:
    """Run lightweight quoter smoke on same-pair mirror routes; mutates routes in place."""
    routes = filter_routes_for_token_subset(routes, token_subset=token_subset)
    ckpt_path = checkpoint_path or DEFAULT_MIRROR_CHECKPOINT_PATH
    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        return {
            "attempted": 0,
            "quote_ok": 0,
            "skipped": len(routes),
            "reason": "SKIPPED_DRY_RUN",
            "exit_class": "skipped",
        }

    rpc_url, rpc_reason = resolve_mirror_smoke_rpc_url(chain, pipeline_mode=pipeline_mode)
    if not rpc_url:
        write_mirror_checkpoint(
            ckpt_path,
            {
                "status": "failed",
                "reason": rpc_reason,
                "processed_routes": 0,
                "quote_ok": 0,
                "quote_fail": 0,
                "last_route_id": None,
                "last_rpc_error": rpc_reason,
            },
        )
        return {
            "attempted": 0,
            "quote_ok": 0,
            "skipped": 0,
            "reason": rpc_reason,
            "exit_class": "infra",
        }

    attempted = 0
    quote_ok = 0
    quote_fail = 0
    by_status: Dict[str, int] = {}
    last_route_id: Optional[str] = None
    last_rpc_error: Optional[str] = None
    eligible = [
        r
        for r in routes
        if is_same_pair_mirror_route(r) and _needs_smoke(r, force_retry=force_retry)
    ]
    total_eligible = len(eligible)

    write_mirror_checkpoint(
        ckpt_path,
        {
            "status": "running",
            "reason": "OK",
            "processed_routes": 0,
            "routes_total": total_eligible,
            "quote_ok": 0,
            "quote_fail": 0,
            "last_route_id": None,
            "last_rpc_error": None,
            "rpc_url_class": "productive" if pipeline_mode else "default",
        },
    )

    from m8.discovery.mirror_quote_cache import (
        PersistentMirrorQuoteCache,
        mirror_quote_cache_key,
    )
    from m8_1.stable_anchor.quote_negative_cache import block_bucket
    from core.quote_lane_limiter import QuoteLaneLimiter

    quote_cache = PersistentMirrorQuoteCache()
    workers = max(1, int(quote_workers or 1))
    lane_limiter = QuoteLaneLimiter(max_concurrent=max(1, min(workers, 2)))
    head_block = None
    try:
        from web3 import Web3

        w3_head = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 12}))
        head_block = int(w3_head.eth.block_number)
    except Exception:
        head_block = None
    head_bucket = block_bucket(head_block)
    default_amount_wei = 10**15

    def _smoke_route(route: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        adapter = str(route.get("adapter_type") or "")
        dex_id = str(route.get("dex_id") or "")
        route_id = str(route.get("route_id") or route.get("pool_address") or "")
        t0a, t1a = resolve_route_token_addrs(route, config)
        focus_addr = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if focus_addr and focus_addr == t0a:
            direction = f"{t0a}->{t1a}"
        elif focus_addr and focus_addr == t1a:
            direction = f"{t1a}->{t0a}"
        else:
            direction = f"{t0a}->{t1a}"
        cache_key = mirror_quote_cache_key(
            route_id=route_id,
            direction=direction,
            amount_wei=default_amount_wei,
            block_bucket=head_bucket,
        )
        cached = quote_cache.get(cache_key)
        if cached and not force_retry:
            route["quote_smoke_status"] = cached
            route["quote_smoke"] = cached
            return route, cached

        def _execute_smoke() -> str:
            if adapter in _V3_ADAPTERS:
                quoter = _dex_quoter(config or {}, dex_id)
                return (
                    _smoke_v3_route(
                        route, rpc_url=rpc_url, quoter=quoter, config=config
                    )
                    if quoter
                    else "QUOTE_FAIL_NO_QUOTER"
                )
            if adapter == "uniswap_v4":
                quoter = _dex_quoter(config or {}, dex_id)
                return (
                    _smoke_v4_route(
                        route, rpc_url=rpc_url, quoter=quoter, config=config
                    )
                    if quoter
                    else "QUOTE_FAIL_NO_QUOTER"
                )
            if adapter in ("uniswap_v2", "ve33", "aerodrome_v2_stable"):
                return _smoke_v2_route(route, rpc_url=rpc_url)
            return "QUOTE_SKIP_UNSUPPORTED_ADAPTER"

        try:
            status = lane_limiter.call(rpc_url, _execute_smoke)
        except Exception as exc:
            status = f"QUOTE_FAIL_{type(exc).__name__}"
        route["quote_smoke_status"] = status
        route["quote_smoke"] = status
        quote_cache.put(cache_key, status)
        if t0a:
            route["token0_addr"] = t0a
        if t1a:
            route["token1_addr"] = t1a
        return route, status

    if workers <= 1:
        route_iter = eligible
    else:
        route_iter = None

    if route_iter is not None:
        for route in route_iter:
            attempted += 1
            route, status = _smoke_route(route)
            last_route_id = str(route.get("route_id") or route.get("pool_address") or "")
            by_status[status] = by_status.get(status, 0) + 1
            if _status_quoteable(status):
                quote_ok += 1
            else:
                quote_fail += 1
                if "429" in status.upper() or "RATE" in status.upper():
                    last_rpc_error = status
            if progress_every > 0 and (
                attempted % progress_every == 0 or attempted == total_eligible
            ):
                ckpt = {
                    "status": "running",
                    "reason": "OK",
                    "processed_routes": attempted,
                    "routes_total": total_eligible,
                    "quote_ok": quote_ok,
                    "quote_fail": quote_fail,
                    "last_route_id": last_route_id,
                    "last_rpc_error": last_rpc_error,
                }
                write_mirror_checkpoint(ckpt_path, ckpt)
                print(
                    "MIRROR_SMOKE_PROGRESS: "
                    + json.dumps(
                        {
                            "processed": attempted,
                            "total": total_eligible,
                            "quote_ok": quote_ok,
                            "quote_fail": quote_fail,
                            "last_route_id": last_route_id,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_smoke_route, route): route for route in eligible}
            for fut in as_completed(futures):
                attempted += 1
                route, status = fut.result()
                last_route_id = str(route.get("route_id") or route.get("pool_address") or "")
                by_status[status] = by_status.get(status, 0) + 1
                if _status_quoteable(status):
                    quote_ok += 1
                else:
                    quote_fail += 1
                    if "429" in status.upper() or "RATE" in status.upper():
                        last_rpc_error = status
                if progress_every > 0 and (
                    attempted % progress_every == 0 or attempted == total_eligible
                ):
                    ckpt = {
                        "status": "running",
                        "reason": "OK",
                        "processed_routes": attempted,
                        "routes_total": total_eligible,
                        "quote_ok": quote_ok,
                        "quote_fail": quote_fail,
                        "last_route_id": last_route_id,
                        "last_rpc_error": last_rpc_error,
                    }
                    write_mirror_checkpoint(ckpt_path, ckpt)
                    print(
                        "MIRROR_SMOKE_PROGRESS: "
                        + json.dumps(
                            {
                                "processed": attempted,
                                "total": total_eligible,
                                "quote_ok": quote_ok,
                                "quote_fail": quote_fail,
                                "last_route_id": last_route_id,
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
    exit_code, exit_class = classify_mirror_smoke_exit(
        quote_ok=quote_ok, reason="OK"
    )
    write_mirror_checkpoint(
        ckpt_path,
        {
            "status": "finished",
            "reason": "OK",
            "processed_routes": attempted,
            "routes_total": total_eligible,
            "quote_ok": quote_ok,
            "quote_fail": quote_fail,
            "last_route_id": last_route_id,
            "last_rpc_error": last_rpc_error,
            "exit_code": exit_code,
            "exit_class": exit_class,
        },
    )
    quote_cache.flush()
    return {
        "attempted": attempted,
        "quote_ok": quote_ok,
        "quote_fail": quote_fail,
        "by_status": by_status,
        "reason": "OK",
        "force_retry": force_retry,
        "exit_code": exit_code,
        "exit_class": exit_class,
        "mirror_quote_cache": quote_cache.stats(),
        "quote_lane_limiter": lane_limiter.stats(),
        "checkpoint_path": str(ckpt_path),
        "quote_cache": quote_cache.stats(),
        "quote_workers": workers,
    }


def build_mirror_token_details(
    routes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Explicit per-token mirror handoff rows for acceptance dashboards."""
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
            {"symbol": route.get("focus_token_symbol"), "routes": []},
        )
        bucket["routes"].append(route)

    details: List[Dict[str, Any]] = []
    for focus, info in sorted(by_focus.items()):
        same = info["routes"]
        dexes = sorted({str(r.get("dex_id") or "") for r in same if r.get("dex_id")})
        quoteable = sum(1 for r in same if _same_pair_route_quoteable(r))
        mr = evaluate_mirror_readiness(
            token_seen_on_dexes=len(dexes),
            same_pair_routes=len(same),
            same_pair_dexes=len(dexes),
            quoteable_same_pair_routes=quoteable,
        )
        legs = []
        for r in sorted(same, key=lambda x: str(x.get("dex_id") or "")):
            legs.append(
                {
                    "dex": r.get("dex_id"),
                    "pool": r.get("pool_address"),
                    "adapter_type": r.get("adapter_type"),
                    "quote_status": str(
                        r.get("quote_smoke_status") or r.get("quote_smoke") or ""
                    ),
                    "token0_addr": r.get("token0_addr"),
                    "token1_addr": r.get("token1_addr"),
                }
            )
        dex_a = dexes[0] if dexes else ""
        dex_b = dexes[1] if len(dexes) > 1 else ""
        pool_a = next(
            (lg["pool"] for lg in legs if lg.get("dex") == dex_a), None
        )
        pool_b = next(
            (lg["pool"] for lg in legs if lg.get("dex") == dex_b), None
        )
        details.append(
            {
                "token": focus,
                "token_symbol": info.get("symbol"),
                "dex_a": dex_a,
                "dex_b": dex_b,
                "pool_a": pool_a,
                "pool_b": pool_b,
                "quote_status": mr.get("missing_reason"),
                "mirror_topology_ready": mr.get("mirror_topology_ready"),
                "mirror_quote_ready": mr.get("mirror_quote_ready"),
                "quoteable_legs": quoteable,
                "legs": legs,
            }
        )
    return [row for row in details if row.get("mirror_topology_ready")]


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
