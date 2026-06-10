"""Distinct-pricing DEX lane — Curve / Balancer / Maverick acceptance metrics."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

BLOCKER_DISTINCT_PRICING_LANE_NOT_READY = "DISTINCT_PRICING_DEX_LANE_NOT_READY"
BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY = (
    "DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY"
)

CURVE_DEX_IDS: Set[str] = {"curve_stable", "curve"}
BALANCER_DEX_IDS: Set[str] = {"balancer_vault", "balancer_stable", "balancer_weighted"}
MAVERICK_DEX_IDS: Set[str] = {"maverick_v2"}

CURVE_ADAPTER_TYPES: Set[str] = {"curve_stable", "curve_stableswap"}
BALANCER_ADAPTER_TYPES: Set[str] = {
    "balancer_vault",
    "balancer_stable",
    "balancer_weighted",
}
MAVERICK_ADAPTER_TYPES: Set[str] = {"maverick_v2"}

DISTINCT_PRICING_DEX_IDS: Set[str] = CURVE_DEX_IDS | BALANCER_DEX_IDS | MAVERICK_DEX_IDS

_QUOTE_OK_PREFIXES = ("QUOTE_OK", "OK", "PASS", "SUCCESS")


def _lane_for_route(route: Dict[str, Any]) -> Optional[str]:
    dex = str(route.get("dex_id") or "")
    adapter = str(route.get("adapter_type") or "")
    if dex in CURVE_DEX_IDS or adapter in CURVE_ADAPTER_TYPES:
        return "curve"
    if dex in BALANCER_DEX_IDS or adapter in BALANCER_ADAPTER_TYPES:
        return "balancer"
    if dex in MAVERICK_DEX_IDS or adapter in MAVERICK_ADAPTER_TYPES:
        return "maverick"
    return None


def _status_quoteable(status: Any) -> bool:
    qss = str(status or "")
    if not qss or qss in ("not_run", "skipped_registry", ""):
        return False
    upper = qss.upper()
    return any(upper.startswith(p) for p in _QUOTE_OK_PREFIXES)


def _is_quoteable(route: Dict[str, Any]) -> bool:
    return _status_quoteable(route.get("quote_smoke_status") or route.get("quote_smoke"))


def _is_productive_quoteable(route: Dict[str, Any]) -> bool:
    return _status_quoteable(route.get("productive_quote_status"))


def count_distinct_pricing_routes(routes: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count active/admitted routes per distinct-pricing lane."""
    curve = balancer = maverick = 0
    balancer_quoteable = maverick_quoteable = 0
    productive_balancer = productive_maverick = productive_curve = 0
    for route in routes:
        lane = _lane_for_route(route)
        if lane == "curve":
            curve += 1
            if _is_productive_quoteable(route):
                productive_curve += 1
        elif lane == "balancer":
            balancer += 1
            if _is_quoteable(route):
                balancer_quoteable += 1
            if _is_productive_quoteable(route):
                productive_balancer += 1
        elif lane == "maverick":
            maverick += 1
            if _is_quoteable(route):
                maverick_quoteable += 1
            if _is_productive_quoteable(route):
                productive_maverick += 1
    return {
        "curve_routes_ready": curve,
        "balancer_routes_ready": balancer,
        "maverick_routes_ready": maverick,
        "balancer_quoteable_routes": balancer_quoteable,
        "maverick_quoteable_routes": maverick_quoteable,
        "discovery_balancer_quoteable_routes": balancer_quoteable,
        "discovery_maverick_quoteable_routes": maverick_quoteable,
        "productive_balancer_quoteable_routes": productive_balancer,
        "productive_maverick_quoteable_routes": productive_maverick,
        "productive_curve_quoteable_routes": productive_curve,
        "distinct_pricing_routes_ready": curve + balancer + maverick,
    }


def quote_success_rates_by_lane(
    routes: Iterable[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    """Per-lane quote smoke success rate when quote_smoke fields are present."""
    lanes: Dict[str, List[bool]] = {"curve": [], "balancer": [], "maverick": []}
    for route in routes:
        lane = _lane_for_route(route)
        if not lane:
            continue
        qss = route.get("quote_smoke_status") or route.get("quote_smoke")
        if qss is None or str(qss) in ("not_run", "skipped_registry", ""):
            continue
        lanes[lane].append(_is_quoteable(route))
    out: Dict[str, Optional[float]] = {}
    for lane, key in (
        ("curve", "curve_route_qsr"),
        ("balancer", "balancer_route_qsr"),
        ("maverick", "maverick_route_qsr"),
    ):
        vals = lanes[lane]
        out[key] = round(sum(vals) / len(vals), 4) if vals else None
    return out


def evaluate_distinct_pricing_lane(
    routes: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate per-lane shadow readiness (Curve / Balancer / Maverick separate)."""
    counts = count_distinct_pricing_routes(routes)
    qsr = quote_success_rates_by_lane(routes)
    curve_ready = counts["curve_routes_ready"] > 0
    balancer_ready = counts["balancer_routes_ready"] > 0
    maverick_ready = counts["maverick_routes_ready"] > 0
    all_lanes_ready = curve_ready and balancer_ready and maverick_ready
    discovery_bm_quoteable = (
        counts["balancer_quoteable_routes"] + counts["maverick_quoteable_routes"]
    ) > 0
    productive_bm_quoteable = (
        counts["productive_balancer_quoteable_routes"]
        + counts["productive_maverick_quoteable_routes"]
    ) > 0
    productive_curve_quoteable = counts["productive_curve_quoteable_routes"] > 0

    missing_lanes: List[str] = []
    if not curve_ready:
        missing_lanes.append("curve")
    if not balancer_ready:
        missing_lanes.append("balancer")
    if not maverick_ready:
        missing_lanes.append("maverick")

    quote_lanes_not_ready: List[str] = []
    if balancer_ready and counts["balancer_quoteable_routes"] == 0:
        quote_lanes_not_ready.append("balancer")
    if maverick_ready and counts["maverick_quoteable_routes"] == 0:
        quote_lanes_not_ready.append("maverick")
    if curve_ready and counts["curve_routes_ready"] > 0:
        curve_q = sum(1 for r in routes if _lane_for_route(r) == "curve" and _is_quoteable(r))
        if curve_q == 0:
            quote_lanes_not_ready.append("curve")

    blocker = None
    if not balancer_ready or not maverick_ready:
        blocker = BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY
    elif not curve_ready:
        blocker = BLOCKER_DISTINCT_PRICING_LANE_NOT_READY

    return {
        **counts,
        **qsr,
        "curve_lane_ready": curve_ready,
        "balancer_lane_ready": balancer_ready,
        "maverick_lane_ready": maverick_ready,
        "missing_distinct_pricing_lanes": missing_lanes,
        "quote_lanes_not_ready": quote_lanes_not_ready,
        "distinct_pricing_all_lanes_ready": all_lanes_ready,
        "distinct_pricing_lane_ready": all_lanes_ready,
        "distinct_pricing_shadow_quote_ready": discovery_bm_quoteable,
        "distinct_pricing_productive_quote_ready": (
            productive_bm_quoteable and productive_curve_quoteable
        ),
        "existence_blocker": blocker,
    }


def build_per_adapter_lane_report(
    *,
    routes_admitted: List[Dict[str, Any]],
    reject_rows: List[Dict[str, str]],
    pools_found_by_dex: Optional[Dict[str, int]] = None,
) -> Dict[str, Dict[str, int]]:
    """Hard per-adapter report: discovered / verified / admitted / quoteable / rejected."""
    lanes = ("curve_stable", "balancer_vault", "maverick_v2")
    report: Dict[str, Dict[str, int]] = {
        dex: {
            "discovered": 0,
            "verified": 0,
            "admitted": 0,
            "quoteable": 0,
            "rejected": 0,
        }
        for dex in lanes
    }

    dex_to_lane = {
        "curve_stable": "curve_stable",
        "curve": "curve_stable",
        "balancer_vault": "balancer_vault",
        "balancer_stable": "balancer_vault",
        "balancer_weighted": "balancer_vault",
        "maverick_v2": "maverick_v2",
    }

    if pools_found_by_dex:
        for dex, count in pools_found_by_dex.items():
            key = dex_to_lane.get(dex)
            if key:
                report[key]["discovered"] += int(count)

    for route in routes_admitted:
        dex = str(route.get("dex_id") or "")
        key = dex_to_lane.get(dex) or (
            "curve_stable"
            if str(route.get("adapter_type") or "") in CURVE_ADAPTER_TYPES
            else "balancer_vault"
            if str(route.get("adapter_type") or "") in BALANCER_ADAPTER_TYPES
            else "maverick_v2"
            if str(route.get("adapter_type") or "") in MAVERICK_ADAPTER_TYPES
            else None
        )
        if not key:
            continue
        report[key]["admitted"] += 1
        if route.get("factory_verified") or route.get("hint_status") in (
            "HINT_ONCHAIN_VERIFIED",
            "HINT_POOLID_VERIFIED",
            "HINT_FACTORY_VERIFIED",
        ):
            report[key]["verified"] += 1
        if _is_quoteable(route):
            report[key]["quoteable"] += 1

    reject_by_dex: Counter[str] = Counter()
    for row in reject_rows:
        dex = str(row.get("dex_id") or "")
        key = dex_to_lane.get(dex)
        if key:
            reject_by_dex[key] += 1
    for key, count in reject_by_dex.items():
        report[key]["rejected"] += int(count)

    return report


def _route_productive_key(route: Dict[str, Any]) -> str:
    dex = str(route.get("dex_id") or "")
    pool = str(route.get("pool_address") or route.get("pool_id") or "")
    return f"{dex}:{pool.lower()}"


def _productive_keys_for_route(route: Dict[str, Any]) -> List[str]:
    """Lookup keys for productive diagnostic maps (address + pool_id variants)."""
    dex = str(route.get("dex_id") or "")
    keys: List[str] = []
    for field in ("pool_address", "pool_id"):
        val = str(route.get(field) or "").strip().lower()
        if val:
            keys.append(f"{dex}:{val}")
    return keys


def enrich_balancer_routes_from_index(
    routes: List[Dict[str, Any]],
    *,
    chain: str = "base",
    repo_root: Optional[Path] = None,
) -> Dict[str, int]:
    """Fill Balancer ``pool_id``, ``balancer_assets``, ``balances`` from rolling index."""
    root = repo_root or Path(__file__).resolve().parents[2]
    index_path = root / "data/runs/_rolling/m8_balancer_pool_index_latest.json"
    if not index_path.exists():
        return {"balancer_metadata_enriched": 0}
    try:
        index_doc = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"balancer_metadata_enriched": 0}

    by_addr: Dict[str, Dict[str, Any]] = {}
    by_pool_id: Dict[str, Dict[str, Any]] = {}
    for row in index_doc.get("pools") or []:
        if not isinstance(row, dict):
            continue
        addr = str(row.get("pool_address") or "").lower()
        pid = str(row.get("pool_id") or "").lower()
        if addr:
            by_addr[addr] = row
        if pid:
            by_pool_id[pid] = row

    enriched = 0
    for route in routes:
        lane = _lane_for_route(route)
        if lane != "balancer":
            continue
        addr = str(route.get("pool_address") or "").lower()
        pid = str(route.get("pool_id") or "").lower()
        row = by_addr.get(addr) or by_pool_id.get(pid) or by_pool_id.get(addr)
        if not row:
            continue
        if not route.get("pool_id") and row.get("pool_id"):
            route["pool_id"] = str(row["pool_id"]).lower()
        assets = row.get("assets") or row.get("tokens_list")
        if assets and not route.get("balancer_assets"):
            route["balancer_assets"] = [str(a).lower() for a in assets]
        balances = row.get("balances")
        if balances is not None and route.get("balancer_balances") is None:
            route["balancer_balances"] = list(balances)
        if row.get("token_a") and not route.get("token_a"):
            route["token_a"] = str(row["token_a"]).lower()
        enriched += 1
    return {"balancer_metadata_enriched": enriched}


def _load_productive_counts_from_diagnostics(
    root: Path,
) -> Dict[str, str]:
    productive_counts: Dict[str, str] = {}
    for diag_name in (
        "m9_productive_quote_diagnostic_latest.json",
        "m9_productive_maverick_diagnostic_latest.json",
        "m9_productive_balancer_diagnostic_latest.json",
    ):
        diag_path = root / "data/tmp" / diag_name
        if not diag_path.exists():
            continue
        try:
            productive_counts.update(
                dict(
                    json.loads(diag_path.read_text(encoding="utf-8")).get(
                        "productive_quote_counts"
                    )
                    or {}
                )
            )
        except (json.JSONDecodeError, OSError):
            continue

    for diag_name, dex_id in (
        ("m9_balancer_pool_lane_rca_latest.json", "balancer_vault"),
        ("m9_maverick_pool_lane_rca_latest.json", "maverick_v2"),
    ):
        diag_path = root / "data/tmp" / diag_name
        if not diag_path.exists():
            continue
        try:
            doc = json.loads(diag_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for row in doc.get("sample_pools") or []:
            if not isinstance(row, dict):
                continue
            status = str(row.get("quote_smoke_status") or row.get("probe_status") or "")
            if not status:
                continue
            pool = str(
                row.get("pool_address") or row.get("pool_id") or ""
            ).lower()
            if pool:
                productive_counts[f"{dex_id}:{pool}"] = status
    return productive_counts


def quoteable_by_dex(
    routes: Iterable[Dict[str, Any]],
    *,
    field: str = "quote_smoke_status",
) -> Dict[str, int]:
    """Per-dex quoteable route counts from discovery or productive status fields."""
    counts: Counter[str] = Counter()
    for route in routes:
        dex = str(route.get("dex_id") or "unknown")
        status = route.get(field) or route.get("quote_smoke")
        if _status_quoteable(status):
            counts[dex] += 1
    return dict(counts)


def stamp_maverick_quote_amounts_from_debug(
    routes: List[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
) -> Dict[str, int]:
    """Stamp per-pool Maverick probe amounts from quote_debug artifact."""
    from m9.graph_arb.productive_distinct_quote import MAVERICK_POOL_LANE_PROBE_LADDER

    root = repo_root or Path(__file__).resolve().parents[2]
    debug_path = root / "data/tmp/m9_maverick_quote_debug_latest.json"
    if not debug_path.exists():
        return {"maverick_quote_amounts_stamped": 0}
    try:
        rows = json.loads(debug_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"maverick_quote_amounts_stamped": 0}
    if not isinstance(rows, list):
        return {"maverick_quote_amounts_stamped": 0}

    by_pool_token: Dict[str, Dict[str, Dict[str, Any]]] = {}
    ladder_max = max(MAVERICK_POOL_LANE_PROBE_LADDER)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") != "QUOTE_OK_MAVERICK":
            continue
        pool = str(row.get("pool_address") or "").lower()
        token_in = str(row.get("token_in") or "").lower()
        amount = row.get("amount_in")
        if not pool or not token_in or amount is None:
            continue
        amt = int(amount)
        pool_map = by_pool_token.setdefault(pool, {})
        prev = pool_map.get(token_in)
        if prev and amt >= int(prev.get("maverick_min_quoteable_amount_raw") or amt):
            continue
        pool_map[token_in] = {
            "maverick_pool_lane_probe_amount": amt,
            "maverick_min_quoteable_amount_raw": amt,
            "maverick_max_quoteable_amount_raw": ladder_max,
            "maverick_token_a_in_probe": row.get("token_a_in"),
            "maverick_pool_lane_token_in": token_in,
        }

    stamped = 0
    for route in routes:
        if _lane_for_route(route) != "maverick":
            continue
        pool = str(route.get("pool_address") or "").lower()
        probes = by_pool_token.get(pool)
        if not probes:
            continue
        route["maverick_probe_by_token_in"] = probes
        stamped += 1
    return {"maverick_quote_amounts_stamped": stamped}


def stamp_productive_quote_status_from_artifacts(
    routes: List[Dict[str, Any]],
    *,
    repo_root: Optional[Path] = None,
) -> Dict[str, int]:
    """Stamp ``productive_quote_status`` from rolling diagnostic / curve indices."""
    root = repo_root or Path(__file__).resolve().parents[2]
    stamped = 0

    productive_counts = _load_productive_counts_from_diagnostics(root)

    curve_by_pool: Dict[str, str] = {}
    curve_path = root / "data/runs/_rolling/m9_curve_pool_indices_latest.json"
    if curve_path.exists():
        try:
            curve_doc = json.loads(curve_path.read_text(encoding="utf-8"))
            pools = curve_doc.get("pools") or {}
            if isinstance(pools, dict):
                for pool_addr, row in pools.items():
                    probe = str((row or {}).get("probe_status") or "")
                    if probe:
                        curve_by_pool[str(pool_addr).lower()] = probe
        except (json.JSONDecodeError, OSError):
            curve_by_pool = {}

    for route in routes:
        lane = _lane_for_route(route)
        if lane == "curve":
            pool = str(route.get("pool_address") or "").lower()
            probe = curve_by_pool.get(pool)
            if probe and _status_quoteable(probe):
                route["productive_quote_status"] = probe
                if not route.get("quote_smoke_status"):
                    route["quote_smoke_status"] = probe
                stamped += 1
            continue
        if lane not in ("balancer", "maverick"):
            continue
        status = None
        for key in _productive_keys_for_route(route):
            status = productive_counts.get(key)
            if status:
                break
        if status:
            route["productive_quote_status"] = status
            if _status_quoteable(status) and not route.get("quote_smoke_status"):
                route["quote_smoke_status"] = status
            stamped += 1

    return {"productive_status_stamped": stamped}


def merge_distinct_pricing_into_acceptance(
    acceptance: Dict[str, Any],
    *,
    routes: Iterable[Dict[str, Any]],
    productive_counts: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Augment hot-path bridge-shadow acceptance with per-lane distinct-pricing gate."""
    routes_list = list(routes)
    if productive_counts:
        for route in routes_list:
            key = _route_productive_key(route)
            status = productive_counts.get(key)
            if status:
                route["productive_quote_status"] = status
    lane = evaluate_distinct_pricing_lane(routes_list)
    out = {**acceptance, **lane}
    topology = bool(acceptance.get("subgraph_ready"))
    lane_eligible = acceptance.get("bridge_shadow_lane_eligible", True)
    all_lanes = bool(lane.get("distinct_pricing_all_lanes_ready"))
    discovery_quote_ok = bool(lane.get("distinct_pricing_shadow_quote_ready"))
    productive_quote_ok = bool(lane.get("distinct_pricing_productive_quote_ready"))
    out["ready_for_bridge_shadow"] = bool(
        topology
        and lane_eligible
        and all_lanes
        and discovery_quote_ok
        and productive_quote_ok
    )
    if lane.get("existence_blocker"):
        out["existence_blocker"] = lane["existence_blocker"]
    return out
