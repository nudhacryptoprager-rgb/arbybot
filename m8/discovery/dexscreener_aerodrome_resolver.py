"""Resolve ambiguous DexScreener dexId='aerodrome' into internal Aerodrome variants."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

_AERODROME_RAW = frozenset(
    {
        "aerodrome",
        "aerodrome-base",
        "aerodrome_base",
        "aerodrome-slipstream",
        "aerodrome_slipstream",
    }
)


def resolve_aerodrome_dex_variant(
    pair: Dict[str, Any],
    *,
    raw_dex_id: str,
    normalized_default: str,
) -> Tuple[str, Optional[str]]:
    """Return (resolved_dex_id, resolver_reason)."""
    raw = str(raw_dex_id or "").strip().lower()
    if raw not in _AERODROME_RAW:
        return normalized_default, None

    if raw in ("aerodrome-slipstream", "aerodrome_slipstream"):
        return "aerodrome_slipstream", "raw_dex_slipstream"

    labels = pair.get("labels") or []
    label_blob = " ".join(str(x).lower() for x in labels if x is not None)
    pair_type = str(pair.get("type") or pair.get("poolType") or "").lower()

    if "slipstream" in label_blob or "slipstream" in pair_type:
        return "aerodrome_slipstream", "labels_slipstream"
    if "stable" in label_blob or "stable" in pair_type:
        return "aerodrome_v2_stable", "labels_stable"
    if pair.get("feeTier") is not None or pair.get("tickSpacing") is not None:
        return "aerodrome_slipstream", "fee_or_tick_slipstream"

    return normalized_default or "aerodrome", "default_aerodrome_ve33"
