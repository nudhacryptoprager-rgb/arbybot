"""DexScreener token → pool hints (hint-only, no on-chain truth)."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from m8.discovery.dexscreener_cache import get_cached_pairs, set_cached_pairs
from m8.discovery.pool_hints import PoolHint, normalize_dex_id
from m8.discovery.radar_layer import stamp_radar_reason

DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex/tokens"
DEXSCREENER_BATCH_BASE = "https://api.dexscreener.com/tokens/v1"
DEXSCREENER_BATCH_MAX = 30
_DEFAULT_TIMEOUT_S = 12.0
# DexScreener free tier ~300 req/min → cap at 5 req/s globally.
_DS_MIN_INTERVAL_S = 0.2
_ds_rate_lock = threading.Lock()
_ds_next_allowed = 0.0
_last_fetch_timing: Dict[str, float] = {}


def _acquire_dexscreener_rate_limit() -> None:
    global _ds_next_allowed
    with _ds_rate_lock:
        now = time.monotonic()
        wait_s = _ds_next_allowed - now
        if wait_s > 0:
            time.sleep(wait_s)
            now = time.monotonic()
        _ds_next_allowed = now + _DS_MIN_INTERVAL_S


def last_fetch_timing() -> Dict[str, float]:
    return dict(_last_fetch_timing)


def _get_json(url: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "arby-m8-hints/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_token_hints(
    token_address: str,
    *,
    chain: str = "base",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    use_cache: bool = True,
    cache_hot: bool = True,
    cache_lane: Optional[str] = None,
    max_recall: bool = False,
    dex_config: Optional[Dict[str, Any]] = None,
) -> List[PoolHint]:
    """Fetch pairs for *token_address* from DexScreener API."""
    batch = fetch_token_hints_batch(
        [token_address],
        chain=chain,
        timeout_s=timeout_s,
        use_cache=use_cache,
        cache_hot=cache_hot,
        cache_lane=cache_lane,
        max_recall=max_recall,
        dex_config=dex_config,
    )
    return batch.get((token_address or "").lower(), [])


def fetch_token_hints_batch(
    token_addresses: List[str],
    *,
    chain: str = "base",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    use_cache: bool = True,
    cache_hot: bool = True,
    cache_lane: Optional[str] = None,
    max_recall: bool = False,
    dex_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, List[PoolHint]]:
    """Batch fetch up to 30 token addresses per DexScreener /tokens/v1 request."""
    global _last_fetch_timing
    normalized = [
        (a or "").lower().strip()
        for a in token_addresses
        if str(a or "").lower().startswith("0x")
    ]
    out: Dict[str, List[PoolHint]] = {a: [] for a in normalized}
    if not normalized:
        return out

    t0 = time.monotonic()
    uncached: List[str] = []
    if use_cache:
        for addr in normalized:
            cached = get_cached_pairs(addr, hot=cache_hot, lane=cache_lane)
            if cached is not None:
                for pair in cached:
                    hint = _pair_to_hint(
                        pair,
                        chain=chain,
                        focus_token=addr,
                        max_recall=max_recall,
                        dex_config=dex_config,
                    )
                    if hint:
                        out[addr].append(hint)
            else:
                uncached.append(addr)
    else:
        uncached = list(normalized)

    chain_slug = "base" if chain.lower() in ("base", "8453") else chain.lower()
    for i in range(0, len(uncached), DEXSCREENER_BATCH_MAX):
        chunk = uncached[i : i + DEXSCREENER_BATCH_MAX]
        url = f"{DEXSCREENER_BATCH_BASE}/{chain_slug}/{','.join(chunk)}"
        try:
            _acquire_dexscreener_rate_limit()
            data = _get_json(url, timeout_s=timeout_s)
            pairs_list = data if isinstance(data, list) else data.get("pairs") or []
            by_token: Dict[str, List[Dict[str, Any]]] = {a: [] for a in chunk}
            for pair in pairs_list:
                if not isinstance(pair, dict):
                    continue
                base = pair.get("baseToken") or {}
                quote = pair.get("quoteToken") or {}
                for tok_addr in (
                    str(base.get("address") or "").lower(),
                    str(quote.get("address") or "").lower(),
                ):
                    if tok_addr in by_token:
                        by_token[tok_addr].append(pair)
            for addr, pairs in by_token.items():
                if use_cache:
                    set_cached_pairs(addr, pairs)
                for pair in pairs:
                    hint = _pair_to_hint(
                        pair,
                        chain=chain,
                        focus_token=addr,
                        max_recall=max_recall,
                        dex_config=dex_config,
                    )
                    if hint:
                        out[addr].append(hint)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
            for addr in chunk:
                single_url = f"{DEXSCREENER_BASE}/{addr}"
                try:
                    _acquire_dexscreener_rate_limit()
                    data = _get_json(single_url, timeout_s=timeout_s)
                    pairs = [p for p in (data.get("pairs") or []) if isinstance(p, dict)]
                    if use_cache:
                        set_cached_pairs(addr, pairs)
                    for pair in pairs:
                        hint = _pair_to_hint(
                            pair,
                            chain=chain,
                            focus_token=addr,
                            max_recall=max_recall,
                            dex_config=dex_config,
                        )
                        if hint:
                            out[addr].append(hint)
                except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
                    continue

    _last_fetch_timing = {
        "latency_s": round(time.monotonic() - t0, 4),
        "cache_hit": float(len(uncached) == 0),
        "batch_tokens": float(len(normalized)),
        "uncached_tokens": float(len(uncached)),
    }
    return out


def _pair_to_hint(
    pair: Dict[str, Any],
    *,
    chain: str,
    focus_token: str,
    max_recall: bool = False,
    dex_config: Optional[Dict[str, Any]] = None,
) -> Optional[PoolHint]:
    chain_id = str(pair.get("chainId") or "").lower()
    if chain_id not in ("base", "8453"):
        return None
    raw_dex = str(pair.get("dexId") or "")
    normalized_dex_id = ""
    support_status = "supported"
    uniswap_resolve_reason: Optional[str] = None
    aero_resolve_reason: Optional[str] = None
    if max_recall:
        from m8.discovery.dex_coverage_gate import (
            classify_dex_support_status,
            validate_dex_package,
        )
        from m8.discovery.dexscreener_uniswap_resolver import resolve_uniswap_dex_variant
        from m8.discovery.dexscreener_aerodrome_resolver import resolve_aerodrome_dex_variant

        cfg = dex_config if dex_config is not None else _default_dex_config()
        mapped_id, support_status = classify_dex_support_status(
            source="dexscreener",
            raw_dex_id=raw_dex,
            config=cfg,
        )
        normalized_dex_id = mapped_id
        dex_id, uniswap_resolve_reason = resolve_uniswap_dex_variant(
            pair,
            raw_dex_id=raw_dex,
            normalized_default=mapped_id,
        )
        aero_id, aero_resolve_reason = resolve_aerodrome_dex_variant(
            pair,
            raw_dex_id=raw_dex,
            normalized_default=dex_id,
        )
        if aero_resolve_reason:
            dex_id = aero_id
        dexes = cfg.get("dexes") or {}
        verdict = validate_dex_package(dex_id, cfg)
        if verdict.get("package_complete"):
            support_status = "supported"
        elif dex_id in dexes:
            support_status = "unsupported"
        else:
            support_status = "unknown_alias"
        if not dex_id:
            return None
        factory_address = ""
        factory_addr_source = ""
        dex_entry = dexes.get(dex_id) or {}
        fac = str(dex_entry.get("factory") or "")
        if fac:
            factory_address = fac.lower()
            factory_addr_source = "config_dexes"
    else:
        dex_id = normalize_dex_id("dexscreener", raw_dex)
        normalized_dex_id = dex_id or ""
        uniswap_resolve_reason = None
        aero_resolve_reason = None
        factory_address = ""
        factory_addr_source = ""
        if not dex_id:
            return None
    pool_addr = str(pair.get("pairAddress") or "").lower()
    if not pool_addr:
        return None
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}
    t0 = str(base.get("address") or "").lower()
    t1 = str(quote.get("address") or "").lower()
    if not t0 or not t1:
        return None
    liq = pair.get("liquidity") or {}
    vol = pair.get("volume") or {}
    created_ms = pair.get("pairCreatedAt")
    created_at: Optional[str] = None
    if created_ms:
        try:
            from datetime import datetime, timezone

            created_at = datetime.fromtimestamp(
                int(created_ms) / 1000.0, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, OSError):
            created_at = None
    liq_usd = _safe_float(liq.get("usd"))
    vol_h24 = _safe_float(vol.get("h24"))
    txns = pair.get("txns") or {}
    txns_h24 = txns.get("h24") if isinstance(txns, dict) else {}
    txn_count = 0
    if isinstance(txns_h24, dict):
        txn_count = int(txns_h24.get("buys") or 0) + int(txns_h24.get("sells") or 0)
    confidence = 0.55
    if liq_usd and liq_usd > 1000:
        confidence += 0.1
    if vol_h24 and vol_h24 > 100:
        confidence += 0.05
    if txn_count >= 10:
        confidence += 0.05
    hint = PoolHint(
        source="dexscreener",
        chain=chain,
        dex_id=dex_id,
        pool_address=pool_addr,
        token0_addr=t0,
        token1_addr=t1,
        factory_address=factory_address,
        created_at=created_at,
        liquidity_usd=liq_usd,
        volume_24h=vol_h24,
        confidence=min(1.0, confidence),
        raw={
            "dexId": raw_dex,
            "pair": pair,
            "txns_h24": txn_count,
            "support_status": support_status,
            "raw_dex_id": raw_dex,
            "normalized_dex_id": normalized_dex_id,
            "uniswap_resolve_reason": uniswap_resolve_reason,
            "aerodrome_resolve_reason": aero_resolve_reason,
            "factory_address_source": factory_addr_source,
        },
        focus_token=focus_token,
    )
    return stamp_radar_reason(hint)


def _default_dex_config() -> Dict[str, Any]:
    try:
        import yaml
        from pathlib import Path

        p = Path("config/exotic_base_anchor.yaml")
        if p.is_file():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
