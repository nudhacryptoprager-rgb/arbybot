"""Classify Base launchpad-origin tokens for mirror lane expectations."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_LAUNCHPAD_PROFILES: Dict[str, Dict[str, Any]] = {    "clanker": {
        "expected_first_dex": ("uniswap_v3", "uniswap_v4"),
        "expected_anchor": ("WETH",),
        "second_venue_probability": 0.35,
        "patient_ttl_h": 72,
        "single_venue_common": True,
    },
    "virtuals": {
        "expected_first_dex": ("uniswap_v3", "aerodrome_slipstream"),
        "expected_anchor": ("VIRTUAL", "WETH"),
        "second_venue_probability": 0.45,
        "patient_ttl_h": 48,
        "single_venue_common": True,
    },
    "bankr": {
        "expected_first_dex": ("uniswap_v3",),
        "expected_anchor": ("WETH", "USDC"),
        "second_venue_probability": 0.25,
        "patient_ttl_h": 96,
        "single_venue_common": True,
    },
    "generic_launchpad": {
        "expected_first_dex": (),
        "expected_anchor": ("WETH", "USDC"),
        "second_venue_probability": 0.2,
        "patient_ttl_h": 48,
        "single_venue_common": True,
    },
}


def classify_launchpad(
    token_addr: str,
    *,
    entry: Optional[Dict[str, Any]] = None,
    hints: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return launchpad lane metadata for a focus token (diagnostic only)."""
    addr = str(token_addr or "").lower()
    entry = entry or {}
    hints = hints or []
    launchpad = "unknown"
    first_dex = str(entry.get("first_dex") or "").lower()
    raw = entry.get("raw") or {}

    dex_ids = {
        str(h.get("dex_id") or h.get("dex") or "").lower()
        for h in hints
        if isinstance(h, dict)
    }
    if not dex_ids and first_dex:
        dex_ids.add(first_dex)

    symbol = str(entry.get("symbol") or raw.get("symbol") or "").upper()
    factory = str(entry.get("factory") or raw.get("factory") or "").lower()

    if symbol.endswith("CLANKER") or "clanker" in str(entry.get("source") or "").lower():
        launchpad = "clanker"
    elif any(
        sym.upper() == "VIRTUAL"
        for h in hints
        if isinstance(h, dict)
        for sym in (str(h.get("token0") or ""), str(h.get("token1") or ""))
    ):
        launchpad = "virtuals"
    elif "bankr" in symbol.lower() or "bankr" in factory:
        launchpad = "bankr"
    elif entry.get("token_class") == "fresh_long_tail" and len(dex_ids) <= 1:
        launchpad = "generic_launchpad"

    profile = dict(_LAUNCHPAD_PROFILES.get(launchpad, _LAUNCHPAD_PROFILES["generic_launchpad"]))
    profile["launchpad"] = launchpad
    profile["token"] = addr
    profile["observed_dex_ids"] = sorted(dex_ids)
    return profile
