"""Patient-lane diagnostics for single-venue tokens (no profit claim)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_PATIENT_DIAGNOSTIC_PATH = Path("data/tmp/m8_patient_lane_diagnostics_latest.json")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_patient_lane_diagnostics(
    watchlist: Dict[str, Any],
    *,
    expansion: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Price/liquidity drift snapshot for single-venue watch tokens."""
    from m8.discovery.launchpad_classifier import classify_launchpad

    expansion = expansion or {}
    routes_by_token: Dict[str, List[Dict[str, Any]]] = {}
    for route in expansion.get("routes_admitted") or []:
        if not isinstance(route, dict):
            continue
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if focus.startswith("0x"):
            routes_by_token.setdefault(focus, []).append(route)

    rows: List[Dict[str, Any]] = []
    for addr, entry in (watchlist.get("tokens") or {}).items():
        if not isinstance(entry, dict):
            continue
        has_first = bool(entry.get("first_pool") or entry.get("first_dex"))
        second_verified = bool(entry.get("second_pool_verified"))
        if not has_first or second_verified:
            continue
        venue_count = int(entry.get("venue_count") or entry.get("dex_count") or 1)
        if venue_count > 1:
            continue
        routes = routes_by_token.get(str(addr).lower(), [])
        liq = entry.get("approx_liquidity_usd") or entry.get("liquidity_usd")
        launchpad = classify_launchpad(str(addr), entry=entry, hints=routes)
        rows.append(
            {
                "token": str(addr).lower(),
                "token_class": entry.get("token_class"),
                "first_dex": entry.get("first_dex"),
                "liquidity_usd": liq,
                "launchpad": launchpad.get("launchpad"),
                "patient_ttl_h": launchpad.get("patient_ttl_h"),
                "second_venue_probability": launchpad.get("second_venue_probability"),
                "diagnostic_lane": "patient_single_venue",
                "profit_claim_allowed": False,
            }
        )
    rows.sort(key=lambda r: float(r.get("second_venue_probability") or 0.0), reverse=True)
    return {
        "schema_version": "m8_patient_lane_diagnostics_v1",
        "generated_at_utc": _iso_now(),
        "single_venue_count": len(rows),
        "tokens": rows,
    }


def export_patient_lane_diagnostics(
    *,
    watchlist_path: Path = Path("data/tmp/m8_token_watchlist_latest.json"),
    expansion_path: Path = Path("data/runs/_rolling/m8_cross_dex_expansion_latest.json"),
    output_path: Path = DEFAULT_PATIENT_DIAGNOSTIC_PATH,
) -> Dict[str, Any]:
    from m8.discovery.time_to_mirror_lane import load_watchlist

    watchlist = load_watchlist(watchlist_path)
    expansion: Dict[str, Any] = {}
    if expansion_path.is_file():
        expansion = json.loads(expansion_path.read_text(encoding="utf-8"))
    payload = build_patient_lane_diagnostics(watchlist, expansion=expansion)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
