"""Token / mechanic-pair classification for hot-path shadow lanes (config-driven)."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

TOKEN_CLASS_FRESH = "fresh_long_tail"
TOKEN_CLASS_KNOWN_MAJOR = "known_major"
TOKEN_CLASS_KNOWN_MID = "known_midtail"
TOKEN_CLASS_UNKNOWN = "unknown_unclassified"

MECHANIC_SAME = "same_mechanic"
MECHANIC_CROSS = "cross_mechanic"
MECHANIC_UNKNOWN = "unknown_mechanic"

LANE_SHADOW = "shadow_lane"
LANE_TELEMETRY = "telemetry_control"
LANE_DENY = "deny_production"


def _chain_key(config: Dict[str, Any]) -> str:
    from m8.discovery.anchor_registry import chain_key_from_config

    return chain_key_from_config(config)


def _core_token_meta(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """addr_lower -> core_tokens.yaml entry (no hardcoded addresses)."""
    try:
        from config import load_core_tokens

        chain_tokens = load_core_tokens().get(_chain_key(config), {}) or {}
    except (ImportError, FileNotFoundError):
        chain_tokens = {}
    out: Dict[str, Dict[str, Any]] = {}
    for sym, info in chain_tokens.items():
        if not isinstance(info, dict):
            continue
        addr = info.get("address")
        if addr:
            out[str(addr).lower()] = {**info, "symbol": sym}
    return out


def _exotic_config_addrs(config: Dict[str, Any]) -> Dict[str, str]:
    """Strategy config token addresses (verified exotic universe)."""
    out: Dict[str, str] = {}
    for sym, info in (config.get("tokens") or {}).items():
        if not isinstance(info, dict):
            continue
        addr = info.get("address") or info.get("addr")
        if addr:
            out[str(addr).lower()] = str(sym)
    return out


def _fresh_window_s(config: Dict[str, Any]) -> float:
    raw = config.get("m8_2_fresh_token_window_s")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return 6.0 * 3600.0


def prior_venue_stats(
    registry: Optional[Dict[str, Any]],
    token_addr: str,
) -> Tuple[int, int]:
    """Return (prior_pool_count, prior_dex_count) before ingesting current event."""
    tok = ((registry or {}).get("tokens") or {}).get(token_addr.lower()) or {}
    venues = tok.get("venues") or {}
    dexes = {str(v.get("dex") or "") for v in venues.values() if v.get("dex")}
    return len(venues), len(dexes)


def classify_token_class(
    token_addr: str,
    *,
    symbol: str = "",
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]] = None,
    now_ts: Optional[float] = None,
    prior_pool_count: int = 0,
) -> str:
    """Classify focus token: fresh long-tail vs known major/midtail."""
    addr = token_addr.lower()
    core = _core_token_meta(config)
    exotic = _exotic_config_addrs(config)

    if addr in core:
        meta = core[addr]
        if bool(meta.get("productive_default")):
            return TOKEN_CLASS_KNOWN_MAJOR
        liq = str(meta.get("liquidity_tier") or "").lower()
        cross = int(meta.get("cross_dex_expected") or 0)
        if liq == "high" and cross >= 3:
            return TOKEN_CLASS_KNOWN_MAJOR
        return TOKEN_CLASS_KNOWN_MID

    if addr in exotic:
        return TOKEN_CLASS_KNOWN_MID

    if prior_pool_count > 0:
        return TOKEN_CLASS_UNKNOWN

    reg_tok = ((registry or {}).get("tokens") or {}).get(addr) or {}
    first_ts = reg_tok.get("first_seen_ts")
    if now_ts is not None and first_ts is not None:
        age = float(now_ts) - float(first_ts)
        if age <= _fresh_window_s(config):
            return TOKEN_CLASS_FRESH

    if not reg_tok:
        return TOKEN_CLASS_FRESH

    return TOKEN_CLASS_UNKNOWN


def classify_mechanic_pair(
    *,
    cross_mechanic: Optional[bool] = None,
    mirror_score: int = 0,
    pricing_models: Optional[List[str]] = None,
) -> str:
    if cross_mechanic is True:
        return MECHANIC_CROSS
    if cross_mechanic is False:
        return MECHANIC_SAME
    models = list(pricing_models or [])
    if mirror_score >= 2 or len(set(models)) >= 2:
        return MECHANIC_CROSS
    if models:
        return MECHANIC_SAME
    return MECHANIC_UNKNOWN


def production_lane_policy(
    token_class: str,
    mechanic_pair: str,
) -> str:
    """Hard policy: known_major+same_mechanic = telemetry only."""
    if token_class == TOKEN_CLASS_KNOWN_MAJOR and mechanic_pair == MECHANIC_SAME:
        return LANE_TELEMETRY
    if token_class == TOKEN_CLASS_KNOWN_MAJOR and mechanic_pair == MECHANIC_CROSS:
        return LANE_SHADOW
    if token_class == TOKEN_CLASS_FRESH and mechanic_pair == MECHANIC_CROSS:
        return LANE_SHADOW
    if token_class == TOKEN_CLASS_FRESH:
        return LANE_SHADOW
    if token_class == TOKEN_CLASS_KNOWN_MID and mechanic_pair == MECHANIC_CROSS:
        return LANE_SHADOW
    if mechanic_pair == MECHANIC_SAME:
        return LANE_TELEMETRY
    return LANE_DENY


def bridge_shadow_lane_eligible(
    *,
    token_class: str,
    mechanic_pair: str,
    connector_tokens: int,
    cross_mechanic: bool,
) -> bool:
    """M8.2 bridge-shadow: cross_mechanic OR fresh long-tail with connector."""
    if token_class == TOKEN_CLASS_KNOWN_MAJOR and mechanic_pair == MECHANIC_SAME:
        return False
    if cross_mechanic or mechanic_pair == MECHANIC_CROSS:
        return True
    if token_class == TOKEN_CLASS_FRESH and connector_tokens >= 1:
        return True
    return False


def annotate_hot_path_row(
    row: Dict[str, Any],
    *,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    focus_token: str,
    focus_symbol: str = "",
    now_ts: Optional[float] = None,
    event_block: Optional[int] = None,
    prior_pool_count: Optional[int] = None,
    prior_dex_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Add token_class, mechanic_pair, production_lane, timing fields to a candidate row."""
    addr = focus_token.lower()
    if prior_pool_count is None:
        prior_pool_count, prior_dex_count = prior_venue_stats(registry, addr)
    else:
        prior_dex_count = prior_dex_count if prior_dex_count is not None else 0

    token_class = classify_token_class(
        addr,
        symbol=focus_symbol,
        config=config,
        registry=registry,
        now_ts=now_ts,
        prior_pool_count=int(prior_pool_count or 0),
    )
    cross = bool(row.get("cross_mechanic"))
    summary = row.get("summary") or {}
    pricing_models = summary.get("pricing_model_pairs")
    if isinstance(pricing_models, dict):
        pricing_models = list(pricing_models.keys())
    mechanic_pair = classify_mechanic_pair(
        cross_mechanic=cross,
        mirror_score=int(summary.get("cross_mechanic_tokens") or 0),
        pricing_models=pricing_models if isinstance(pricing_models, list) else None,
    )
    lane = production_lane_policy(token_class, mechanic_pair)
    connectors = int(
        summary.get("connector_token_count")
        or len(summary.get("connector_tokens") or row.get("connector_tokens") or [])
        or 0
    )
    shadow_ok = bridge_shadow_lane_eligible(
        token_class=token_class,
        mechanic_pair=mechanic_pair,
        connector_tokens=connectors,
        cross_mechanic=cross,
    )

    row["token_class"] = token_class
    row["mechanic_pair"] = mechanic_pair
    row["production_lane"] = lane
    row["bridge_shadow_lane_eligible"] = shadow_ok
    row["prior_pool_count"] = int(prior_pool_count or 0)
    row["prior_dex_count"] = int(prior_dex_count or 0)
    row["first_seen_as_new_token"] = token_class == TOKEN_CLASS_FRESH
    row["first_seen_as_known_pool"] = token_class in (
        TOKEN_CLASS_KNOWN_MAJOR,
        TOKEN_CLASS_KNOWN_MID,
    )

    fq = row.get("focused_quote") or {}
    if fq.get("cycles_found", 0) > 0 and event_block is not None:
        row.setdefault("first_quoteable_block_delta", 0)
    if row.get("event_to_quote_ms") is not None and event_block is not None:
        row.setdefault("first_quoteable_block_delta", 0)
    row.setdefault("first_swap_after_pool_block_delta", None)
    row.setdefault("price_deviation_decay_half_life_s", None)
    row.setdefault("spread_lifetime_s", None)

    if lane == LANE_TELEMETRY and not shadow_ok:
        row.setdefault("reject_reason", "REJECT_KNOWN_MAJOR_SAME_MECHANIC_TELEMETRY")

    return row


def build_token_class_histogram(candidates: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for row in candidates:
        counts[str(row.get("token_class") or TOKEN_CLASS_UNKNOWN)] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def build_spread_lifetime_histograms(
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Separate spread observations by token_class and mechanic_pair (never mixed)."""
    by_class: Dict[str, List[float]] = defaultdict(list)
    by_mechanic: Dict[str, List[float]] = defaultdict(list)
    pos_by_class: Counter[str] = Counter()
    pos_by_mechanic: Counter[str] = Counter()

    for row in candidates:
        tc = str(row.get("token_class") or TOKEN_CLASS_UNKNOWN)
        mp = str(row.get("mechanic_pair") or MECHANIC_UNKNOWN)
        sl = row.get("spread_lifetime_s")
        if sl is not None:
            try:
                by_class[tc].append(float(sl))
                by_mechanic[mp].append(float(sl))
            except (TypeError, ValueError):
                pass
        fq = row.get("focused_quote") or {}
        if int(fq.get("cycles_positive_gross") or 0) > 0:
            pos_by_class[tc] += 1
            pos_by_mechanic[mp] += 1

    def _pack(groups: Dict[str, List[float]], pos: Counter[str]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        keys = sorted(set(groups.keys()) | set(pos.keys()))
        for k in keys:
            vals = sorted(groups.get(k) or [])
            p50 = vals[len(vals) // 2] if vals else None
            out[k] = {
                "spread_lifetime_observations": len(vals),
                "spread_lifetime_p50_s": p50,
                "positive_gross_cycles": int(pos.get(k) or 0),
            }
        return out

    return {
        "spread_lifetime_by_token_class": _pack(by_class, pos_by_class),
        "spread_lifetime_by_mechanic_pair": _pack(by_mechanic, pos_by_mechanic),
    }
