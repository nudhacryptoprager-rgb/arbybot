"""M8.3 token metadata registry builder and resolver."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

SCHEMA_VERSION = "m8_3_token_metadata_registry_v2"
SCHEMA_VERSION_LEGACY = "m8_3_token_metadata_registry_v1"
DEFAULT_REGISTRY_PATH = "data/runs/_rolling/m8_3_token_metadata_registry_latest.json"

SOURCE_CORE_CONFIG = "core_config"
SOURCE_KNOWN_ADDRESS = "known_address"
SOURCE_M8_SNIPER = "m8_sniper_erc20"
SOURCE_M8_1 = "m8_1_artifact"
SOURCE_M8_2 = "m8_2_artifact"
SOURCE_REGISTRY_CACHE = "registry_cache"
SOURCE_ERC20 = "erc20_call"
SOURCE_EXTERNAL_HINT = "external_hint"
SOURCE_UNRESOLVED = "unresolved"

ECONOMICS_GRADE_CONFIG = "config_verified"
ECONOMICS_GRADE_ONCHAIN = "verified_onchain"
ECONOMICS_GRADE_HINT = "hint_only"
ECONOMICS_GRADE_UNRESOLVED = "unresolved"

ERROR_DECIMALS_UNRESOLVED = "DECIMALS_UNRESOLVED"
ERROR_ERC20_DECIMALS_REVERT = "ERC20_DECIMALS_REVERT"
ERROR_DECIMALS_CONFLICT = "DECIMALS_CONFLICT"
ERROR_NO_CODE = "NO_CODE"
ERROR_NON_ERC20 = "NON_ERC20"
ERROR_PROBE_CAP_EXHAUSTED = "PROBE_CAP_EXHAUSTED"

_ECONOMICS_SOURCES = frozenset(
    {
        SOURCE_CORE_CONFIG,
        SOURCE_KNOWN_ADDRESS,
        SOURCE_M8_SNIPER,
        SOURCE_M8_1,
        SOURCE_M8_2,
        SOURCE_REGISTRY_CACHE,
        SOURCE_ERC20,
    }
)
_HINT_SOURCES = frozenset({SOURCE_EXTERNAL_HINT})

M8_3_DECIMALS_SOURCE_PREFIX = "m8_3_"
SOURCE_CACHE_UNVERIFIED = "cache_unverified"

_VERIFIED_ROUTE_DECIMALS_SOURCES = frozenset(
    {
        "erc20_call",
        "core_config",
        "known_address",
        "route_override",
        "m8_sniper_erc20",
    }
)


def is_m8_3_provenance_locked(route: Dict[str, Any], leg: str = "token0") -> bool:
    src = str(route.get(f"{leg}_decimals_source") or "")
    return src.startswith(M8_3_DECIMALS_SOURCE_PREFIX)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_eth_address(addr: object) -> bool:
    if not isinstance(addr, str):
        return False
    a = addr.strip().lower()
    if not a.startswith("0x") or len(a) != 42 or a == "0x" + "0" * 40:
        return False
    try:
        int(a[2:], 16)
    except ValueError:
        return False
    return True


def economics_grade_for_source(source: str) -> str:
    if source in (SOURCE_ERC20, SOURCE_M8_SNIPER):
        return ECONOMICS_GRADE_ONCHAIN
    if source in (SOURCE_CORE_CONFIG, SOURCE_KNOWN_ADDRESS, SOURCE_REGISTRY_CACHE):
        return ECONOMICS_GRADE_CONFIG
    if source in (SOURCE_M8_1, SOURCE_M8_2, SOURCE_CACHE_UNVERIFIED):
        return ECONOMICS_GRADE_UNRESOLVED
    if source in _HINT_SOURCES:
        return ECONOMICS_GRADE_HINT
    return ECONOMICS_GRADE_UNRESOLVED


def is_economics_grade_entry(entry: Dict[str, Any]) -> bool:
    grade = str(entry.get("economics_grade") or "")
    if grade in (ECONOMICS_GRADE_ONCHAIN, ECONOMICS_GRADE_CONFIG):
        return entry.get("decimals") is not None and not entry.get("error_code")
    return False


def _candidate(
    *,
    decimals: Optional[int],
    source: str,
    symbol: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if decimals is None:
        return None
    try:
        dec = int(decimals)
    except (TypeError, ValueError):
        return None
    return {
        "decimals": dec,
        "source": source,
        "symbol": symbol,
        "name": name,
        "economics_grade": economics_grade_for_source(source),
        "error_code": None,
    }


def _merge_candidates(
    address: str,
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    addr = address.lower()
    base: Dict[str, Any] = {
        "address": addr,
        "symbol": None,
        "name": None,
        "decimals": None,
        "source": SOURCE_UNRESOLVED,
        "economics_grade": ECONOMICS_GRADE_UNRESOLVED,
        "error_code": ERROR_DECIMALS_UNRESOLVED,
    }
    if not candidates:
        return base

    econ = [c for c in candidates if c["source"] in _ECONOMICS_SOURCES]
    chosen = econ[0] if econ else candidates[0]
    econ_decimals = {c["decimals"] for c in econ}
    if len(econ_decimals) > 1:
        base.update(
            {
                "decimals": None,
                "source": SOURCE_UNRESOLVED,
                "economics_grade": ECONOMICS_GRADE_UNRESOLVED,
                "error_code": ERROR_DECIMALS_CONFLICT,
            }
        )
        return base

    base.update(
        {
            "decimals": chosen["decimals"],
            "source": chosen["source"],
            "economics_grade": chosen["economics_grade"],
            "error_code": None,
            "symbol": chosen.get("symbol"),
            "name": chosen.get("name"),
        }
    )
    return base


def resolve_token_entry(
    address: str,
    *,
    cfg: Any = None,
    sniper_hints: Optional[Dict[str, Dict[str, Any]]] = None,
    m81_hints: Optional[Dict[str, Dict[str, Any]]] = None,
    m82_hints: Optional[Dict[str, Dict[str, Any]]] = None,
    registry_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    external_hints: Optional[Dict[str, Dict[str, Any]]] = None,
    w3: Any = None,
) -> Dict[str, Any]:
    """Resolve one token with M8.3 precedence."""
    if not is_valid_eth_address(address):
        return {
            "address": str(address or "").lower(),
            "symbol": None,
            "name": None,
            "decimals": None,
            "source": SOURCE_UNRESOLVED,
            "economics_grade": ECONOMICS_GRADE_UNRESOLVED,
            "error_code": ERROR_DECIMALS_UNRESOLVED,
        }

    addr = address.lower()
    candidates: List[Dict[str, Any]] = []

    if cfg is not None:
        for tc in cfg.tokens.values():
            if (tc.address or "").lower() == addr:
                c = _candidate(
                    decimals=int(tc.decimals),
                    source=SOURCE_CORE_CONFIG,
                    symbol=getattr(tc, "symbol", None) or tc.name,
                    name=getattr(tc, "name", None),
                )
                if c:
                    candidates.append(c)

    from m9.graph_arb.core_tokens_loader import address_decimals_map, address_symbol_map

    known_dec = address_decimals_map("base").get(addr)
    if known_dec is not None:
        sym_map = address_symbol_map("base")
        c = _candidate(
            decimals=known_dec,
            source=SOURCE_KNOWN_ADDRESS,
            symbol=sym_map.get(addr),
        )
        if c:
            candidates.append(c)

    for bucket, source_tag in (
        (sniper_hints or {}, SOURCE_M8_SNIPER),
        (m81_hints or {}, SOURCE_M8_1),
        (m82_hints or {}, SOURCE_M8_2),
        (registry_cache or {}, SOURCE_REGISTRY_CACHE),
    ):
        row = bucket.get(addr) or {}
        c = _candidate(
            decimals=row.get("decimals"),
            source=source_tag,
            symbol=row.get("symbol"),
            name=row.get("name"),
        )
        if c:
            candidates.append(c)

    ext = (external_hints or {}).get(addr) or {}
    c = _candidate(
        decimals=ext.get("decimals"),
        source=SOURCE_EXTERNAL_HINT,
        symbol=ext.get("symbol"),
        name=ext.get("name"),
    )
    if c:
        candidates.append(c)

    if w3 is not None:
        from m9.graph_arb.token_decimals import fetch_on_chain_decimals

        dec = fetch_on_chain_decimals(w3, addr)
        if dec is not None:
            candidates.append(
                _candidate(decimals=dec, source=SOURCE_ERC20) or {}
            )
        elif not any(c["source"] in _ECONOMICS_SOURCES for c in candidates):
            return {
                "address": addr,
                "symbol": None,
                "name": None,
                "decimals": None,
                "source": SOURCE_UNRESOLVED,
                "economics_grade": ECONOMICS_GRADE_UNRESOLVED,
                "error_code": ERROR_ERC20_DECIMALS_REVERT,
            }

    return _merge_candidates(addr, [c for c in candidates if c])


def _route_token_addrs(route: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for key in ("token0_addr", "token1_addr", "token0", "token1", "token_a", "token_b"):
        val = route.get(key)
        if is_valid_eth_address(val):
            out.add(str(val).lower())
    return out


def collect_token_addresses(
    *,
    bridge: Optional[Dict[str, Any]] = None,
    expansion: Optional[Dict[str, Any]] = None,
    sniper: Optional[Dict[str, Any]] = None,
    anchor: Optional[Dict[str, Any]] = None,
    external_hints: Optional[Dict[str, Any]] = None,
) -> Set[str]:
    addrs: Set[str] = set()
    for route in (bridge or {}).get("active_routes") or []:
        addrs |= _route_token_addrs(route)
    for route in (bridge or {}).get("exploration_routes") or []:
        addrs |= _route_token_addrs(route)
    for route in (expansion or {}).get("routes_admitted") or []:
        addrs |= _route_token_addrs(route)
    from m8.discovery.origin_source import collect_m8_token_addrs

    addrs |= collect_m8_token_addrs(sniper=sniper)
    for row in (anchor or {}).get("routes") or []:
        addrs |= _route_token_addrs(row)
    for tok, row in ((external_hints or {}).get("tokens") or {}).items():
        if is_valid_eth_address(tok):
            addrs.add(str(tok).lower())
        elif isinstance(row, dict):
            addr = row.get("address") or row.get("token_address")
            if is_valid_eth_address(addr):
                addrs.add(str(addr).lower())
    return {a for a in addrs if is_valid_eth_address(a)}


def _route_decimals_source_verified(route: Dict[str, Any], dec_key: str) -> bool:
    src_key = dec_key.replace("_decimals", "_decimals_source")
    raw = str(route.get(src_key) or "")
    if raw.startswith(M8_3_DECIMALS_SOURCE_PREFIX):
        inner = raw[len(M8_3_DECIMALS_SOURCE_PREFIX) :]
        return inner in _VERIFIED_ROUTE_DECIMALS_SOURCES or inner in (
            SOURCE_ERC20,
            SOURCE_CORE_CONFIG,
            SOURCE_KNOWN_ADDRESS,
            SOURCE_M8_SNIPER,
        )
    return raw in _VERIFIED_ROUTE_DECIMALS_SOURCES


def _hint_map_from_routes(
    routes: Iterable[Dict[str, Any]],
    *,
    source: str,
) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        for _leg, addr_key, dec_key, sym_key in (
            ("t0", "token0_addr", "token0_decimals", "token0"),
            ("t1", "token1_addr", "token1_decimals", "token1"),
        ):
            addr = route.get(addr_key) or route.get(sym_key)
            if not is_valid_eth_address(addr):
                continue
            if source in (SOURCE_M8_1, SOURCE_M8_2) and not _route_decimals_source_verified(
                route, dec_key
            ):
                continue
            addr_l = str(addr).lower()
            dec = route.get(dec_key)
            if dec is None:
                continue
            out[addr_l] = {
                "decimals": int(dec),
                "symbol": route.get(sym_key),
                "source": source,
            }
    return out


def _verified_registry_cache_row(row: Dict[str, Any]) -> bool:
    if row.get("schema_version") == SCHEMA_VERSION:
        return is_economics_grade_entry(row)
    if row.get("source_provenance") == "m8_3":
        return is_economics_grade_entry(row)
    return is_economics_grade_entry(row) and str(row.get("source") or "") in (
        SOURCE_ERC20,
        SOURCE_CORE_CONFIG,
        SOURCE_KNOWN_ADDRESS,
        SOURCE_M8_SNIPER,
        SOURCE_REGISTRY_CACHE,
    )


def _external_hint_map(doc: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not doc:
        return out
    for tok, row in (doc.get("tokens") or {}).items():
        if not isinstance(row, dict):
            continue
        addr = str(row.get("address") or tok or "").lower()
        if not is_valid_eth_address(addr):
            continue
        dec = row.get("decimals") or row.get("decimals_hint")
        if dec is None:
            continue
        out[addr] = {
            "decimals": dec,
            "symbol": row.get("symbol"),
            "name": row.get("name"),
        }
    return out


def _route_scope_ids(
    bridge: Optional[Dict[str, Any]],
    *,
    capacity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Set[str]]:
    active = bridge or {}
    all_routes = list(active.get("active_routes") or []) + list(
        active.get("exploration_routes") or []
    )
    active_only = list(active.get("active_routes") or [])
    enrich_ids = set(
        (capacity or {}).get("enrichment_targets", {}).get("route_ids") or []
    )
    rca = (capacity or {}).get("productive_four_leg_rca") or {}
    lost_ids = set(rca.get("route_ids_lost_in_productive") or [])
    cycle_ids = enrich_ids | lost_ids
    cap_samples = (capacity or {}).get("sample_cycles_at_econ_floor") or []
    cap_route_ids: Set[str] = set()
    for row in cap_samples:
        for leg in row.get("legs") or []:
            rid = leg.get("route_id")
            if rid:
                cap_route_ids.add(str(rid))

    def _ids(routes: List[Dict[str, Any]]) -> Set[str]:
        return {str(r.get("route_id") or "") for r in routes if r.get("route_id")}

    return {
        "all_routes": _ids(all_routes),
        "active_routes": _ids(active_only),
        "cycle_participating_routes": cycle_ids,
        "econ_capacity_routes": cap_route_ids or cycle_ids,
    }


def _route_coverage_metrics(
    routes: List[Dict[str, Any]],
    registry: Dict[str, Dict[str, Any]],
    *,
    route_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    scoped = routes
    if route_ids is not None:
        scoped = [r for r in routes if str(r.get("route_id") or "") in route_ids]
    total = len(scoped)
    if total == 0:
        return {
            "routes_count": 0,
            "legs_total": 0,
            "legs_economics_grade_known": 0,
            "decimals_known_rate": 0.0,
            "economics_grade_known_rate": 0.0,
        }
    legs_total = 0
    legs_known = 0
    legs_econ = 0
    for route in scoped:
        for addr_key in ("token0_addr", "token1_addr"):
            addr = route.get(addr_key)
            if not is_valid_eth_address(addr):
                continue
            legs_total += 1
            entry = registry.get(str(addr).lower()) or {}
            if entry.get("decimals") is not None:
                legs_known += 1
            if is_economics_grade_entry(entry):
                legs_econ += 1
    return {
        "routes_count": total,
        "legs_total": legs_total,
        "legs_decimals_known": legs_known,
        "legs_economics_grade_known": legs_econ,
        "decimals_known_rate": round(legs_known / legs_total, 4) if legs_total else 0.0,
        "economics_grade_known_rate": round(legs_econ / legs_total, 4) if legs_total else 0.0,
    }


def build_token_metadata_registry(
    *,
    chain: str = "base",
    bridge: Optional[Dict[str, Any]] = None,
    expansion: Optional[Dict[str, Any]] = None,
    sniper: Optional[Dict[str, Any]] = None,
    anchor: Optional[Dict[str, Any]] = None,
    external_hints: Optional[Dict[str, Any]] = None,
    prior_registry: Optional[Dict[str, Any]] = None,
    capacity: Optional[Dict[str, Any]] = None,
    cfg: Any = None,
    w3: Any = None,
    onchain_unresolved_only: bool = True,
    max_onchain_probes: Optional[int] = None,
    with_dex_workers: bool = False,
    task_mode: str = "legacy",
) -> Dict[str, Any]:
    """Build rolling M8.3 registry artifact."""
    if task_mode == "aggregated" or with_dex_workers:
        from m8.metadata.aggregator import build_aggregated_registry

        return build_aggregated_registry(
            chain=chain,
            bridge=bridge,
            expansion=expansion,
            sniper=sniper,
            anchor=anchor,
            external_hints=external_hints,
            prior_registry=prior_registry,
            capacity=capacity,
            cfg=cfg,
            w3=w3,
            onchain_unresolved_only=onchain_unresolved_only,
            max_onchain_probes=max_onchain_probes,
            with_dex_workers=True,
        )
    addrs = collect_token_addresses(
        bridge=bridge,
        expansion=expansion,
        sniper=sniper,
        anchor=anchor,
        external_hints=external_hints,
    )
    registry_cache: Dict[str, Dict[str, Any]] = {}
    if prior_registry:
        prior_rows = (prior_registry.get("token_registry") or prior_registry.get("tokens") or {})
        for addr, row in prior_rows.items():
            if isinstance(row, dict) and row.get("decimals") is not None:
                if _verified_registry_cache_row(row):
                    registry_cache[str(addr).lower()] = row

    sniper_hints = _hint_map_from_routes(
        (sniper or {}).get("recent_events") or [], source=SOURCE_M8_SNIPER
    )
    m81_hints = _hint_map_from_routes(
        (anchor or {}).get("routes") or [], source=SOURCE_M8_1
    )
    m82_hints = _hint_map_from_routes(
        (expansion or {}).get("routes_admitted") or [], source=SOURCE_M8_2
    )
    ext_hints = _external_hint_map(external_hints)

    tokens: Dict[str, Dict[str, Any]] = {}
    conflict_count = 0
    unresolved_count = 0
    econ_verified = 0

    sorted_addrs = sorted(addrs)
    onchain_used = 0
    for addr in sorted_addrs:
        prior = registry_cache.get(addr)
        use_w3 = w3
        if max_onchain_probes is not None and onchain_used >= max_onchain_probes:
            use_w3 = None
        if onchain_unresolved_only and prior and is_economics_grade_entry(prior):
            entry = dict(prior)
            entry.setdefault("address", addr)
            entry["source_provenance"] = "m8_3"
            tokens[addr] = entry
            if is_economics_grade_entry(entry):
                econ_verified += 1
            continue

        had_w3 = use_w3 is not None
        entry = resolve_token_entry(
            addr,
            cfg=cfg,
            sniper_hints=sniper_hints,
            m81_hints=m81_hints,
            m82_hints=m82_hints,
            registry_cache=registry_cache,
            external_hints=ext_hints,
            w3=use_w3,
        )
        if had_w3 and use_w3 is not None:
            onchain_used += 1
        entry["source_provenance"] = "m8_3"
        tokens[addr] = entry
        if entry.get("error_code") == ERROR_DECIMALS_CONFLICT:
            conflict_count += 1
        if entry.get("error_code") in (ERROR_DECIMALS_UNRESOLVED, ERROR_ERC20_DECIMALS_REVERT):
            unresolved_count += 1
        if is_economics_grade_entry(entry):
            econ_verified += 1

    all_routes = list((bridge or {}).get("active_routes") or []) + list(
        (bridge or {}).get("exploration_routes") or []
    )
    scopes = _route_scope_ids(bridge, capacity=capacity)
    route_coverage = {
        scope: {
            **_route_coverage_metrics(all_routes, tokens, route_ids=ids if ids else None),
            "route_ids": sorted(ids) if ids else [],
        }
        for scope, ids in scopes.items()
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "chain": chain,
        "generated_at_utc": _utc_now(),
        "scope": "M8.3_token_metadata_registry",
        "truth_boundary": "on_chain_verified_required_for_economics_grade",
        "authority_contract": "m8_3_single_source_after_handoff",
        "token_registry": tokens,
        "tokens": tokens,
        "coverage": {
            "all_tokens_count": len(tokens),
            "resolved_decimals_count": sum(1 for t in tokens.values() if t.get("decimals") is not None),
            "economics_grade_verified_count": econ_verified,
            "decimals_conflict_count": conflict_count,
            "unresolved_count": unresolved_count,
            "onchain_probes_used": onchain_used,
            "onchain_probes_cap": max_onchain_probes,
        },
        "route_coverage": route_coverage,
    }


def load_registry(path: str = DEFAULT_REGISTRY_PATH) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("registry load failed: %s", exc)
        return None


def save_registry(doc: Dict[str, Any], path: str = DEFAULT_REGISTRY_PATH) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


def apply_registry_to_route(
    route: Dict[str, Any],
    registry: Dict[str, Any],
    *,
    economics_only: bool = False,
) -> Dict[str, Any]:
    """Apply M8.3 registry decimals to one bridge route."""
    from m8.metadata.aggregator import get_token_registry

    tokens = get_token_registry(registry)
    for addr_key, dec_key, src_key, sym_key in (
        ("token0_addr", "token0_decimals", "token0_decimals_source", "token0"),
        ("token1_addr", "token1_decimals", "token1_decimals_source", "token1"),
    ):
        addr = route.get(addr_key)
        if not is_valid_eth_address(addr):
            continue
        entry = tokens.get(str(addr).lower()) or {}
        if economics_only and not is_economics_grade_entry(entry):
            continue
        dec = entry.get("decimals")
        if dec is None:
            continue
        route[dec_key] = int(dec)
        route[src_key] = f"{M8_3_DECIMALS_SOURCE_PREFIX}{entry.get('source') or 'registry'}"
        route[f"{sym_key}_metadata_source"] = entry.get("source")
        route[f"{sym_key}_economics_grade"] = entry.get("economics_grade")
        route["m8_3_metadata_applied"] = True
        if entry.get("symbol") and not route.get(sym_key):
            route[f"{sym_key}_symbol"] = entry.get("symbol")
    if route.get("token0_decimals") is not None and route.get("token1_decimals") is not None:
        t0_grade = route.get("token0_economics_grade")
        t1_grade = route.get("token1_economics_grade")
        if t0_grade in (ECONOMICS_GRADE_ONCHAIN, ECONOMICS_GRADE_CONFIG) and t1_grade in (
            ECONOMICS_GRADE_ONCHAIN,
            ECONOMICS_GRADE_CONFIG,
        ):
            route["decimals_status"] = "m8_3_economics_grade"
        else:
            route["decimals_status"] = "resolved"
    return route


def apply_registry_to_routes(
    routes: List[Dict[str, Any]],
    registry: Dict[str, Any],
    *,
    economics_only: bool = False,
) -> Dict[str, int]:
    hist: Dict[str, int] = {"applied_legs": 0, "economics_grade_legs": 0}
    for route in routes:
        before = (route.get("token0_decimals"), route.get("token1_decimals"))
        apply_registry_to_route(route, registry, economics_only=economics_only)
        after = (route.get("token0_decimals"), route.get("token1_decimals"))
        if after != before:
            hist["applied_legs"] += sum(
                1 for b, a in zip(before, after, strict=False) if b != a and a is not None
            )
        for leg in ("token0", "token1"):
            if route.get(f"{leg}_economics_grade") in (
                ECONOMICS_GRADE_ONCHAIN,
                ECONOMICS_GRADE_CONFIG,
            ):
                hist["economics_grade_legs"] += 1
    return hist
