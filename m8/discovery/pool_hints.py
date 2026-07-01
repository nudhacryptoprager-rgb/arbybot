"""M8.2 external pool hints — unified schema, normalization, on-chain verify.

Hints from DexScreener / GeckoTerminal / The Graph are **not** M9 truth.
They must pass on-chain verification before bridge ingestion.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

SCHEMA_VERSION = "m8_external_pool_hints.1"
DEFAULT_HINTS_PATH = "data/runs/_rolling/m8_external_pool_hints_latest.json"

# Hint lifecycle statuses (step 7)
HINT_ONLY = "HINT_ONLY"
HINT_STALE = "HINT_STALE"
HINT_DEX_UNSUPPORTED = "HINT_DEX_UNSUPPORTED"
HINT_ONCHAIN_VERIFIED = "HINT_ONCHAIN_VERIFIED"
HINT_POOLID_VERIFIED = "HINT_POOLID_VERIFIED"
HINT_FACTORY_VERIFIED = "HINT_FACTORY_VERIFIED"
QUOTE_SMOKE_OK = "QUOTE_SMOKE_OK"
BRIDGE_SHADOW_READY = "BRIDGE_SHADOW_READY"

HINT_STATUSES = (
    HINT_ONLY,
    HINT_STALE,
    HINT_DEX_UNSUPPORTED,
    HINT_ONCHAIN_VERIFIED,
    HINT_POOLID_VERIFIED,
    HINT_FACTORY_VERIFIED,
    QUOTE_SMOKE_OK,
    BRIDGE_SHADOW_READY,
)

# Statuses safe for M9 bridge ingestion (step 9)
BRIDGE_ELIGIBLE_HINT_STATUSES = frozenset(
    {
        HINT_ONCHAIN_VERIFIED,
        HINT_POOLID_VERIFIED,
        HINT_FACTORY_VERIFIED,
        QUOTE_SMOKE_OK,
        BRIDGE_SHADOW_READY,
    }
)

VERIFY_FACTORY_GET_POOL = "factory_getPool"

_DEFAULT_STALE_HOURS = 168.0  # 7 days — audit / warm lanes
RECALL_HOT_STALE_HOURS = 48.0  # hot mirror-recall selection window

# External dex id → internal dex_id (subset; unknown → None)
_DEXSCREENER_DEX_MAP: Dict[str, str] = {
    "uniswap": "uniswap_v3",
    "uniswapv2": "uniswap_v2",
    "uniswap-v2": "uniswap_v2",
    "uniswap_v2": "uniswap_v2",
    "uniswapv3": "uniswap_v3",
    "uniswap-v3": "uniswap_v3",
    "uniswap_v3": "uniswap_v3",
    "uniswapv4": "uniswap_v4",
    "uniswap-v4": "uniswap_v4",
    "uniswap_v4": "uniswap_v4",
    "aerodrome": "aerodrome",
    "aerodrome-base": "aerodrome",
    "aerodrome-slipstream": "aerodrome_slipstream",
    "aerodrome_slipstream": "aerodrome_slipstream",
    "sushiswap": "sushiswap_v2",
    "sushiswap-v2": "sushiswap_v2",
    "sushiswap_v2": "sushiswap_v2",
    "sushiswap-v3": "sushiswap_v3",
    "sushiswap_v3": "sushiswap_v3",
    "pancakeswap": "pancakeswap_v3",
    "pancakeswap-v3": "pancakeswap_v3",
    "pancakeswap_v3": "pancakeswap_v3",
    "baseswap": "baseswap_v2",
    "baseswap-v2": "baseswap_v2",
    "baseswap_v2": "baseswap_v2",
    "curve": "curve_stable",
    "balancer": "balancer_vault",
    "maverick": "maverick_v2",
    "alienbase": "alien_base_v2",
    "alien-base": "alien_base_v2",
    "area51": "alien_area51",
    "quickswap": "quickswap_algebra",
    "quickswap-v4-base": "quickswap_algebra",
    "iziswap": "iziswap_base",
    "izumi": "iziswap_base",
    "hydrex": "hydrex",
    "pancakeswap-infinity": "pancake_infinity",
    "balancer-v3": "balancer_v3",
}

_GECKO_DEX_MAP: Dict[str, str] = {
    "uniswap-v4-base": "uniswap_v4",
    "uniswap-v3-base": "uniswap_v3",
    "uniswap-v2-base": "uniswap_v2",
    "aerodrome-base": "aerodrome",
    "aerodrome-slipstream-base": "aerodrome_slipstream",
    "sushiswap-v3-base": "sushiswap_v3",
    "pancakeswap-v3-base": "pancakeswap_v3",
    "alien-base": "alien_base_v2",
    "alienbase-area51": "alien_area51",
    "quickswap-v4-base": "quickswap_algebra",
    "iziswap-base": "iziswap_base",
    "hydrex-base": "hydrex",
}

_GRAPH_PROTOCOL_MAP: Dict[str, str] = {
    "uniswap_v3": "uniswap_v3",
    "aerodrome": "aerodrome",
}

_GRAPH_TOKEN_API_MAP: Dict[str, str] = {
    "uniswap_v2": "uniswap_v2",
    "uniswap_v3": "uniswap_v3",
    "uniswap_v4": "uniswap_v4",
    "curvefi": "curve_stable",
    "curve": "curve_stable",
    "balancer": "balancer_vault",
    "aerodrome": "aerodrome",
    "maverick": "maverick_v2",
}


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm_addr(addr: str) -> str:
    return (addr or "").lower().strip()


@dataclass
class PoolHint:
    """Unified external pool hint (step 1)."""

    source: str
    chain: str
    dex_id: str
    pool_address: str
    token0_addr: str
    token1_addr: str
    created_at: Optional[str] = None
    liquidity_usd: Optional[float] = None
    volume_24h: Optional[float] = None
    confidence: float = 0.5
    raw: Dict[str, Any] = field(default_factory=dict)
    hint_status: str = HINT_ONLY
    focus_token: str = ""
    pool_id: str = ""
    pool_manager: str = ""
    factory_address: str = ""
    vault_address: str = ""
    fee: Optional[int] = None
    tick_spacing: Optional[int] = None
    hooks: Optional[str] = None
    verify_method: str = ""
    radar_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PoolHint":
        h = cls(
            source=str(data.get("source") or ""),
            chain=str(data.get("chain") or "base"),
            dex_id=str(data.get("dex_id") or ""),
            pool_address=_norm_addr(data.get("pool_address") or ""),
            token0_addr=_norm_addr(data.get("token0_addr") or ""),
            token1_addr=_norm_addr(data.get("token1_addr") or ""),
            created_at=data.get("created_at"),
            liquidity_usd=_safe_float(data.get("liquidity_usd")),
            volume_24h=_safe_float(data.get("volume_24h")),
            confidence=float(data.get("confidence") or 0.5),
            raw=dict(data.get("raw") or {}),
            hint_status=str(data.get("hint_status") or HINT_ONLY),
            focus_token=_norm_addr(data.get("focus_token") or ""),
            pool_id=_norm_addr(data.get("pool_id") or ""),
            pool_manager=_norm_addr(data.get("pool_manager") or ""),
            factory_address=_norm_addr(data.get("factory_address") or ""),
            vault_address=_norm_addr(data.get("vault_address") or ""),
            fee=int(data["fee"]) if data.get("fee") is not None else None,
            tick_spacing=(
                int(data["tick_spacing"]) if data.get("tick_spacing") is not None else None
            ),
            hooks=data.get("hooks"),
            verify_method=str(data.get("verify_method") or ""),
            radar_reason=str(data.get("radar_reason") or ""),
        )
        return normalize_pool_identity(h)


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_dex_id(source: str, raw_dex_id: str) -> Optional[str]:
    """Map external dex identifier to internal dex_id."""
    key = (raw_dex_id or "").strip().lower()
    if not key:
        return None
    if source == "dexscreener":
        compact = key.replace("-", "_").replace(" ", "")
        mapped = (
            _DEXSCREENER_DEX_MAP.get(key)
            or _DEXSCREENER_DEX_MAP.get(compact)
            or _DEXSCREENER_DEX_MAP.get(key.replace("-", "_"))
        )
        if mapped:
            return mapped
        return compact or None
    if source == "geckoterminal":
        return _GECKO_DEX_MAP.get(key) or key.replace("-base", "").replace("-", "_")
    if source == "thegraph":
        return _GRAPH_PROTOCOL_MAP.get(key) or key
    if source == "thegraph_token_api":
        return _GRAPH_TOKEN_API_MAP.get(key) or key
    if source == "coingecko_onchain":
        return key.replace("-", "_")
    return key.replace("-", "_")


def _hint_age_hours(hint: PoolHint) -> Optional[float]:
    if not hint.created_at:
        return None
    try:
        ts = datetime.fromisoformat(hint.created_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - ts).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def hint_is_stale(hint: PoolHint, *, max_age_hours: float = _DEFAULT_STALE_HOURS) -> bool:
    """Audit/warm staleness: missing created_at is treated as not stale."""
    age_h = _hint_age_hours(hint)
    if age_h is None:
        return False
    return age_h > max_age_hours


def hint_is_stale_for_recall(
    hint: PoolHint,
    *,
    max_age_hours: float = RECALL_HOT_STALE_HOURS,
) -> bool:
    """Hot-recall staleness: missing or unparseable created_at → stale (existence-only)."""
    age_h = _hint_age_hours(hint)
    if age_h is None:
        return True
    return age_h > max_age_hours


def _hint_identity(h: PoolHint) -> str:
    if h.pool_id:
        return h.pool_id.lower()
    return h.pool_address.lower()


def normalize_pool_identity(hint: PoolHint) -> PoolHint:
    """Map V4 bytes32 pool keys onto pool_id; do not require len(pool_address)==42."""
    from m8.discovery.hint_verifier import is_bytes32_hex

    if hint.dex_id == "uniswap_v4" or is_bytes32_hex(hint.pool_address):
        if is_bytes32_hex(hint.pool_address) and not hint.pool_id:
            hint.pool_id = hint.pool_address.lower()
        if not hint.pool_manager:
            hint.pool_manager = "0x498581ff718922c3f8e6a244956af099b2652b2b"
        if not hint.factory_address:
            hint.factory_address = hint.pool_manager
    if hint.dex_id in ("balancer_vault", "balancer_stable") and is_bytes32_hex(
        hint.pool_address
    ):
        if not hint.pool_id:
            hint.pool_id = hint.pool_address.lower()
        if not hint.vault_address:
            hint.vault_address = "0xba12222222228d8ba445958a75a0704d566bf2c8"
    return hint


def dedupe_hints(hints: Iterable[PoolHint]) -> List[PoolHint]:
    seen: Set[Tuple[str, str, str]] = set()
    out: List[PoolHint] = []
    for h in hints:
        h = normalize_pool_identity(h)
        ident = _hint_identity(h)
        key = (h.chain, h.dex_id, ident)
        if not ident or key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def hints_for_token(
    artifact: Dict[str, Any],
    token_address: str,
) -> List[PoolHint]:
    """Return hints where token is focus_token, token0, or token1."""
    addr = _norm_addr(token_address)
    rows = artifact.get("hints") or []
    out: List[PoolHint] = []
    seen: Set[Tuple[str, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        h = PoolHint.from_dict(row)
        if addr not in (h.focus_token, h.token0_addr, h.token1_addr):
            continue
        key = (h.dex_id, _hint_identity(h), addr)
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def artifact_hint_summary(artifact: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate hint artifact stats for expansion diagnostics."""
    from collections import Counter

    if not artifact:
        return {
            "hint_artifact_pools": 0,
            "hint_tokens_in_artifact": 0,
            "hint_status_counts": {},
            "hint_dex_counts": {},
        }
    rows = artifact.get("hints") or []
    focus_tokens: Set[str] = set()
    status_counts: Counter = Counter()
    dex_counts: Counter = Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        h = PoolHint.from_dict(row)
        if h.focus_token:
            focus_tokens.add(h.focus_token)
        elif h.token0_addr:
            focus_tokens.add(h.token0_addr)
        status_counts[h.hint_status] += 1
        if h.dex_id:
            dex_counts[h.dex_id] += 1
    return {
        "hint_artifact_pools": len(rows),
        "hint_tokens_in_artifact": len(focus_tokens),
        "hint_status_counts": dict(status_counts),
        "hint_dex_counts": dict(dex_counts),
        "hint_artifact_verified_count": int(
            (artifact.get("metrics") or {}).get("verified_second_pool_count", 0)
        ),
    }


def hint_to_pool_entry(
    hint: PoolHint,
    *,
    focus_token: str,
    focus_symbol: str = "",
    connector_symbol: str = "",
) -> Dict[str, Any]:
    """Convert hint to cross_dex_expand pool_entry dict (pre-verify)."""
    ft = _norm_addr(focus_token)
    t0a, t1a = hint.token0_addr, hint.token1_addr
    if ft == t1a:
        t0s, t1s = focus_symbol or "T", connector_symbol or ""
    else:
        t0s, t1s = focus_symbol or "T", connector_symbol or ""
    pool_addr = hint.pool_id or hint.pool_address
    raw = hint.raw or {}
    primary_source = str(hint.source or "")
    if primary_source in ("onchain_factory", "factory_log"):
        resolve_source = primary_source
    else:
        resolve_source = f"external_hint:{primary_source}"
    return {
        "dex_id": hint.dex_id,
        "pool_address": pool_addr,
        "pool_id": hint.pool_id or None,
        "pool_manager": hint.pool_manager or None,
        "factory_address": hint.factory_address or hint.pool_manager or "",
        "vault_address": hint.vault_address or None,
        "fee": hint.fee,
        "tick_spacing": hint.tick_spacing,
        "hooks": hint.hooks,
        "token0_addr": t0a,
        "token1_addr": t1a,
        "token0_symbol": t0s if t0a == ft else connector_symbol,
        "token1_symbol": t1s if t1a == ft else connector_symbol,
        "connector_token": connector_symbol,
        "focus_token_address": ft,
        "focus_token_symbol": focus_symbol,
        "resolve_source": resolve_source,
        "discovery_source": raw.get("discovery_source") or primary_source,
        "hint_status": hint.hint_status,
        "hint_source": hint.source,
        "verify_method": hint.verify_method,
        "factory_verified": primary_source in ("onchain_factory", "factory_log"),
        "token_class": raw.get("token_class"),
        "refresh_lane": raw.get("refresh_lane"),
        "quote_smoke": "not_run",
        "liquidity_usd": hint.liquidity_usd,
        "volume_24h": hint.volume_24h,
    }


def verify_pool_address_onchain(
    chain: str,
    pool_address: str,
    *,
    rpc_url: Optional[str] = None,
) -> bool:
    """Light on-chain check: pool contract has bytecode."""
    import json
    import os
    import urllib.request

    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return False
    addr = _norm_addr(pool_address)
    if not addr or len(addr) != 42:
        return False
    try:
        from core.rpc_urls import get_rpc_url

        url = rpc_url or get_rpc_url(chain)
        if not url:
            return False
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getCode",
                "params": [addr, "latest"],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        code = str((body.get("result") or "0x")).strip().lower()
        return code not in ("0x", "")
    except Exception:
        return False


def _status_for_verify_method(method: str) -> str:
    if method == VERIFY_FACTORY_GET_POOL:
        return HINT_FACTORY_VERIFIED
    if method == "v4_stateview":
        return HINT_POOLID_VERIFIED
    return HINT_ONCHAIN_VERIFIED


def verify_hint_onchain(
    hint: PoolHint,
    *,
    chain: str,
    allowed_dex_ids: Optional[Set[str]] = None,
    rpc_url: Optional[str] = None,
    verify_mode: str = "specialized",
    metrics: Optional[Dict[str, Any]] = None,
) -> PoolHint:
    """Upgrade hint status via on-chain checks (step 6 merge tail)."""
    from m8.discovery.hint_verifier import (
        record_verification_metrics,
        verify_hint_specialized,
    )

    h = normalize_pool_identity(PoolHint.from_dict(hint.to_dict()))
    if hint_is_stale(h):
        h.hint_status = HINT_STALE
        if metrics is not None:
            record_verification_metrics(metrics, h, verified=False, reject_reason="HINT_STALE")
        return h
    if verify_mode == "none":
        return h

    verified_hint, reason = verify_hint_specialized(
        h,
        chain=chain,
        allowed_dex_ids=allowed_dex_ids,
        rpc_url=rpc_url,
        verify_mode=verify_mode,
    )
    h = verified_hint
    if reason == "OK":
        h.hint_status = _status_for_verify_method(h.verify_method or "")
        h.confidence = min(1.0, h.confidence + 0.25)
        if metrics is not None:
            record_verification_metrics(metrics, h, verified=True, reject_reason="OK")
        return h
    if reason == "HINT_DEX_UNSUPPORTED":
        h.hint_status = HINT_DEX_UNSUPPORTED
    else:
        h.hint_status = HINT_ONLY
    if metrics is not None:
        record_verification_metrics(metrics, h, verified=False, reject_reason=reason)
    return h


def load_hints_artifact(path: str = DEFAULT_HINTS_PATH) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _empty_artifact("base")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_artifact("base")


def _empty_artifact(chain: str) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": None,
        "chain": chain,
        "sources": [],
        "metrics": _empty_metrics(),
        "hints": [],
    }


def _empty_metrics() -> Dict[str, Any]:
    from m8.discovery.hint_verifier import empty_verification_metrics

    return {
        "hint_tokens_checked": 0,
        "hint_pools_seen": 0,
        "hint_to_verified_pool_rate": 0.0,
        "second_pool_hints_found": 0,
        "verified_second_pool_count": 0,
        "hint_source_latency_s": {},
        "second_venue_source": {},
        "transition_candidate_rate": 0.0,
        **empty_verification_metrics(),
    }


def write_hints_artifact(
    artifact: Dict[str, Any],
    path: str = DEFAULT_HINTS_PATH,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    artifact["schema_version"] = SCHEMA_VERSION
    artifact["generated_at_utc"] = _iso_now()
    p.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")


def build_artifact(
    *,
    chain: str,
    sources: List[str],
    hints: List[PoolHint],
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    deduped = dedupe_hints(hints)
    m = _empty_metrics()
    if metrics:
        m.update(metrics)
    m["hint_pools_seen"] = len(deduped)
    verified = sum(
        1 for h in deduped if h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES
    )
    m["verified_second_pool_count"] = verified
    method_events = sum((m.get("verified_by_method") or {}).values())
    m["verified_method_event_count"] = int(method_events)
    if method_events and method_events != verified:
        m["verified_dedupe_note"] = (
            "verified_method_event_count sums per-source verify events; "
            "verified_second_pool_count is deduped unique pools"
        )
    if deduped:
        m["hint_to_verified_pool_rate"] = round(verified / len(deduped), 4)
    tokens_checked = int(m.get("hint_tokens_checked") or 0)
    if tokens_checked:
        m["transition_candidate_rate"] = round(verified / tokens_checked, 4)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "sources": sources,
        "metrics": m,
        "hints": [h.to_dict() for h in deduped],
    }


def route_bridge_eligible(route: Dict[str, Any]) -> bool:
    """True when route may enter M9 bridge (step 9).

    Legacy expansion routes (no hint_status) pass through unchanged.
    External-hint routes require verified status beyond HINT_ONLY.
    """
    status = route.get("hint_status")
    if not status:
        return True
    if status == HINT_ONLY:
        return False
    return status in BRIDGE_ELIGIBLE_HINT_STATUSES


class TimedSource:
    """Helper to record per-source latency in metrics."""

    def __init__(self) -> None:
        self.latency_s: Dict[str, float] = {}

    def run(self, source: str, fn: Any) -> Any:
        t0 = time.monotonic()
        try:
            return fn()
        finally:
            self.latency_s[source] = round(time.monotonic() - t0, 4)
