"""Resolve ambiguous DexScreener dexId='uniswap' into v2/v3/v4 internal ids."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

_UNISWAP_RAW = frozenset(
    {
        "uniswap",
        "uniswap-v2",
        "uniswap-v3",
        "uniswap-v4",
        "uniswap-v4-base",
        "uniswapv2",
        "uniswapv3",
        "uniswapv4",
    }
)


def resolve_uniswap_dex_variant(
    pair: Dict[str, Any],
    *,
    raw_dex_id: str,
    normalized_default: str,
) -> Tuple[str, Optional[str]]:
    """Return (resolved_dex_id, resolver_reason)."""
    raw = str(raw_dex_id or "").strip().lower()
    if raw not in _UNISWAP_RAW:
        return normalized_default, None

    labels = pair.get("labels") or []
    label_blob = " ".join(str(x).lower() for x in labels if x is not None)
    pool = str(pair.get("pairAddress") or "").lower().strip()

    if "v4" in label_blob or raw in ("uniswap-v4", "uniswap-v4-base", "uniswapv4"):
        return "uniswap_v4", "labels_or_raw_dex_v4"
    if "v2" in label_blob or raw in ("uniswap-v2", "uniswapv2"):
        return "uniswap_v2", "labels_or_raw_dex_v2"
    if "v3" in label_blob or raw in ("uniswap-v3", "uniswapv3"):
        return "uniswap_v3", "labels_or_raw_dex_v3"

    if len(pool) == 66:
        return "uniswap_v4", "pool_bytes32"
    if pair.get("feeTier") is not None or pair.get("fee") is not None:
        return "uniswap_v3", "fee_tier_hint"

    return normalized_default or "uniswap_v3", "default_uniswap_v3"
