"""Token-scoped pool universe for M8.2 recall (not chain-wide anchor brute force)."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from m8.discovery.dex_coverage_gate import validate_dex_package
from m8.discovery.mirror_anchors import GENERIC_ANCHOR_SYMS, is_approved_anchor_symbol
from m8.discovery.pool_hints import PoolHint, QUOTE_SMOKE_OK, hint_is_stale

FRESH_TOKEN_POOL = "fresh_token_pool"
CONNECTOR_CLOSURE_POOL = "connector_closure_pool"
ANCHOR_CLOSURE_POOL = "anchor_closure_pool"
RECALL_CANDIDATE = "recall_candidate"
ADMISSION_CANDIDATE = "admission_candidate"

_DEFAULT_SCAN_PATH = "data/tmp/m8_onchain_factory_scan_latest.json"
_FACTORY_SOURCES = frozenset({"onchain_factory", "factory_log"})


def _norm(addr: str) -> str:
    a = str(addr or "").lower().strip()
    return a if a.startswith("0x") else ""


def fresh_token_addresses(tokens: List[str]) -> Set[str]:
    return {_norm(t) for t in tokens if _norm(t)}


def anchor_addresses_from_config(config: Dict[str, Any]) -> Set[str]:
    from m8.discovery.cross_dex_expand import _token_address_from_config

    out: Set[str] = set()
    for sym in GENERIC_ANCHOR_SYMS:
        addr = _token_address_from_config(config, sym)
        if addr:
            out.add(_norm(addr))
    for sym in config.get("anchor_tokens") or []:
        addr = _token_address_from_config(config, str(sym))
        if addr:
            out.add(_norm(addr))
    return out


def build_closure_graph(
    hints: Iterable[PoolHint],
    *,
    fresh_tokens: Set[str],
) -> Set[str]:
    """Tokens reachable from fresh via any recalled pool edge."""
    graph = set(fresh_tokens)
    for h in hints:
        t0, t1 = _norm(h.token0_addr), _norm(h.token1_addr)
        focus = _norm(h.focus_token)
        if focus in fresh_tokens or t0 in fresh_tokens or t1 in fresh_tokens:
            if t0:
                graph.add(t0)
            if t1:
                graph.add(t1)
        if focus:
            graph.add(focus)
    return graph


def classify_pool_universe_type(
    hint: PoolHint,
    *,
    fresh_tokens: Set[str],
    closure_graph: Set[str],
    anchor_addrs: Set[str],
) -> str:
    """Classify hint pool into fresh / connector / anchor closure universe."""
    focus = _norm(hint.focus_token)
    t0, t1 = _norm(hint.token0_addr), _norm(hint.token1_addr)
    if focus in fresh_tokens:
        return FRESH_TOKEN_POOL
    if focus in closure_graph and focus not in anchor_addrs:
        return CONNECTOR_CLOSURE_POOL
    tokens = {t0, t1} - {""}
    if tokens & anchor_addrs and tokens & closure_graph:
        return ANCHOR_CLOSURE_POOL
    if focus in closure_graph:
        return CONNECTOR_CLOSURE_POOL
    return RECALL_CANDIDATE


def stamp_universe_type(
    hint: PoolHint,
    *,
    fresh_tokens: Set[str],
    closure_graph: Set[str],
    anchor_addrs: Set[str],
) -> PoolHint:
    raw = dict(hint.raw or {})
    universe = classify_pool_universe_type(
        hint,
        fresh_tokens=fresh_tokens,
        closure_graph=closure_graph,
        anchor_addrs=anchor_addrs,
    )
    raw["pool_universe_type"] = universe
    raw["admission_class"] = (
        ADMISSION_CANDIDATE
        if raw.get("selection_verified_fresh")
        else RECALL_CANDIDATE
    )
    hint.raw = raw
    return hint


def score_hint_verify_priority(hint: PoolHint) -> float:
    """Scored on-chain verify: fresh + second-venue potential + liquidity + supported."""
    raw = hint.raw or {}
    score = 0.0
    if not hint_is_stale(hint):
        score += 100.0
    if not raw.get("is_stale_hint", hint_is_stale(hint)):
        score += 50.0
    if str(raw.get("support_status") or "") == "supported":
        score += 30.0
    liq = hint.liquidity_usd
    if liq is not None:
        try:
            score += min(float(liq) / 1000.0, 50.0)
        except (TypeError, ValueError):
            pass
    if str(hint.source or "") in _FACTORY_SOURCES:
        score += 20.0
    if str(raw.get("pool_universe_type") or "") == FRESH_TOKEN_POOL:
        score += 15.0
    return score


def sort_hints_for_verify(hints: List[PoolHint]) -> List[PoolHint]:
    return sorted(hints, key=score_hint_verify_priority, reverse=True)


def load_factory_recall_hints(
    fresh_tokens: Set[str],
    *,
    scan_path: str = _DEFAULT_SCAN_PATH,
    hints_path: str = "data/runs/_rolling/m8_external_pool_hints_latest.json",
) -> List[PoolHint]:
    """Merge factory-log / on-chain factory hints for fresh token subset."""
    import json
    from pathlib import Path

    from m8.discovery.dex_coverage_gate import stamp_hint_support_status
    from m8.discovery.pool_hints import load_hints_artifact

    out: List[PoolHint] = []
    cfg: Dict[str, Any] = {}
    try:
        import yaml
        from pathlib import Path as _Path

        cp = _Path("config/exotic_base_anchor.yaml")
        if cp.is_file():
            cfg = yaml.safe_load(cp.read_text(encoding="utf-8")) or {}
    except Exception:
        cfg = {}
    doc = load_hints_artifact(hints_path)
    for row in doc.get("hints") or []:
        if not isinstance(row, dict):
            continue
        h = PoolHint.from_dict(row)
        if str(h.source or "") not in _FACTORY_SOURCES:
            continue
        focus = _norm(h.focus_token)
        if focus and focus in fresh_tokens:
            out.append(stamp_hint_support_status(h, cfg))
    sp = Path(scan_path)
    if sp.is_file():
        try:
            scan = json.loads(sp.read_text(encoding="utf-8"))
            for row in scan.get("verified_pools") or []:
                if not isinstance(row, dict):
                    continue
                focus = _norm(row.get("focus_token"))
                if not focus or focus not in fresh_tokens:
                    continue
                out.append(
                    stamp_hint_support_status(
                        PoolHint(
                            source=str(row.get("source") or "factory_log"),
                            chain=str(scan.get("chain") or "base"),
                            dex_id=str(row.get("dex_id") or ""),
                            pool_address=str(row.get("pool_address") or "").lower(),
                            focus_token=focus,
                            token0_addr=str(row.get("token0_addr") or "").lower(),
                            token1_addr=str(row.get("token1_addr") or "").lower(),
                            fee=row.get("fee") if isinstance(row.get("fee"), int) else None,
                            factory_address=str(row.get("factory_address") or "").lower(),
                            created_at=row.get("created_at") or None,
                            hint_status=str(row.get("hint_status") or "HINT_FACTORY_VERIFIED"),
                            raw={
                                "pool_universe_type": FRESH_TOKEN_POOL,
                                "from_scan_artifact": True,
                                "raw_dex_id": str(row.get("dex_id") or ""),
                                "created_at_source": row.get("created_at_source"),
                                "first_seen_block": row.get("first_seen_block"),
                            },
                        ),
                        cfg,
                    )
                )
        except (json.JSONDecodeError, OSError):
            pass
    return out


def build_unsupported_dex_backlog(
    mirrors: List[Dict[str, Any]],
    *,
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Unsupported / unknown dexId backlog with adapter/factory needs."""
    by_dex: Dict[str, Dict[str, Any]] = {}
    for row in mirrors:
        status = str(row.get("support_status") or "")
        if status == "supported":
            continue
        raw_id = str(row.get("raw_dex_id") or row.get("dex_id") or "").lower()
        if not raw_id:
            continue
        bucket = by_dex.setdefault(
            raw_id,
            {
                "raw_dex_id": raw_id,
                "count": 0,
                "liquidity_sum": 0.0,
                "tokens": set(),
                "support_status": status,
            },
        )
        bucket["count"] += 1
        liq = row.get("liquidity_usd")
        if liq is not None:
            try:
                bucket["liquidity_sum"] += float(liq)
            except (TypeError, ValueError):
                pass
        tok = _norm(row.get("token") or "")
        if tok:
            bucket["tokens"].add(tok)
    rows: List[Dict[str, Any]] = []
    for raw_id, bucket in by_dex.items():
        normalized = raw_id.replace("-", "_")
        verdict = validate_dex_package(normalized, config)
        missing = list(verdict.get("missing") or [])
        priority = int(bucket["count"]) * 10 + int(bucket["liquidity_sum"] // 1000)
        rows.append(
            {
                "raw_dex_id": raw_id,
                "count": int(bucket["count"]),
                "liquidity_sum": round(float(bucket["liquidity_sum"]), 2),
                "tokens_count": len(bucket["tokens"]),
                "support_status": bucket["support_status"],
                "needed_adapter": verdict.get("adapter_type") or normalized,
                "needed_factory": "factory" if "factory" in missing else None,
                "missing_package": missing,
                "priority": priority,
            }
        )
    return sorted(rows, key=lambda r: -int(r.get("priority") or 0))


def build_pool_universe_width(
    hints: List[PoolHint],
    mirrors: List[Dict[str, Any]],
    *,
    fresh_tokens: Set[str],
) -> Dict[str, Any]:
    """Width metrics for token-scoped pool universe."""
    universe_counts = Counter(
        str((h.raw or {}).get("pool_universe_type") or "unknown") for h in hints
    )
    dex_aliases = Counter(
        str(m.get("raw_dex_id") or m.get("dex_id") or "").lower() for m in mirrors
    )
    pool_exists = sum(1 for m in mirrors if m.get("recall_verified_pool_exists"))
    fresh_exists = sum(
        1
        for m in mirrors
        if m.get("recall_verified_pool_exists") and not m.get("is_stale_hint")
    )
    quote_ready = sum(
        1
        for m in mirrors
        if str(m.get("hint_status") or "").upper().startswith("QUOTE")
        or m.get("hint_status") == QUOTE_SMOKE_OK
    )
    return {
        "fresh_tokens_scanned": len(fresh_tokens),
        "raw_pools_seen": len(mirrors),
        "dex_aliases_seen": len([d for d in dex_aliases if d]),
        "pool_exists_verified": pool_exists,
        "fresh_pool_exists": fresh_exists,
        "quote_ready": quote_ready,
        "universe_type_counts": dict(universe_counts),
        "dex_alias_counts": dict(dex_aliases),
    }


def filter_hot_path_hints(
    hints: List[PoolHint],
    *,
    fresh_tokens: Set[str],
    anchor_addrs: Set[str],
    graph_closure_only: bool = True,
) -> List[PoolHint]:
    """Drop global anchor-only pools from hot mirror_recall path."""
    if not graph_closure_only:
        return hints
    graph = build_closure_graph(hints, fresh_tokens=fresh_tokens)
    out: List[PoolHint] = []
    for h in hints:
        t0, t1 = _norm(h.token0_addr), _norm(h.token1_addr)
        focus = _norm(h.focus_token)
        if focus in fresh_tokens:
            out.append(h)
            continue
        if focus and focus not in graph and focus not in fresh_tokens:
            continue
        if t0 in anchor_addrs and t1 in anchor_addrs:
            continue
        if (t0 in anchor_addrs or t1 in anchor_addrs) and not (
            (t0 in graph or t1 in graph) or focus in fresh_tokens
        ):
            continue
        out.append(h)
    return out
