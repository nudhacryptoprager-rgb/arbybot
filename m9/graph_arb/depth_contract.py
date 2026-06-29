"""Route-level depth probe contract for M9 inventories."""
from __future__ import annotations

from typing import Any, Dict, Optional

DEPTH_CONTRACT_KEYS = (
    "effective_depth_usd",
    "usable_depth_usd",
    "depth_probe_status",
    "depth_method",
    "depth_source",
    "depth_block_number",
    "depth_confidence",
    "depth_error_code",
)

_PROBE_ERROR_TO_CODE = {
    "NO_QUOTER": "UNSUPPORTED",
    "NO_ANCHOR_FOR_DEPTH": "NO_ANCHOR_PRICE",
    "V2_RESERVES_FAILED": "NO_LIQUIDITY",
    "V2_ZERO_RESERVES": "NO_LIQUIDITY",
    "ZERO_AMOUNT_IN": "NO_LIQUIDITY",
    "QUOTE_REVERT": "REVERT",
    "QUOTE_FAIL": "REVERT",
    "V4_DEPTH_UNSUPPORTED": "UNSUPPORTED",
    "MISSING_TOKEN_ADDR": "UNSUPPORTED",
    "UNKNOWN_TOKEN": "UNSUPPORTED",
}


def depth_error_code_from_probe(
    *,
    probe_error: Optional[str],
    depth_probe_status: Optional[str],
    effective_depth_usd: Optional[float],
) -> Optional[str]:
    if effective_depth_usd is not None:
        return None
    if probe_error:
        upper = str(probe_error).upper()
        for prefix, code in _PROBE_ERROR_TO_CODE.items():
            if upper.startswith(prefix) or prefix in upper:
                return code
        return "PROBE_FAIL"
    status = str(depth_probe_status or "").upper()
    if status in {"DEPTH_PROBE_TOO_THIN", "DEPTH_PROBE_UNKNOWN"}:
        return "NO_LIQUIDITY"
    if status == "DEPTH_PROBE_ANALYTICAL_SUSPECT":
        return "UNSUPPORTED"
    return None


def normalize_route_depth_contract(
    route: Dict[str, Any],
    *,
    block_number: Optional[int] = None,
    depth_source: Optional[str] = None,
    depth_confidence: Optional[str] = None,
) -> None:
    """Ensure canonical depth fields exist on a bridge route row."""
    for key in DEPTH_CONTRACT_KEYS:
        route.setdefault(key, None)

    if depth_source is not None:
        route["depth_source"] = depth_source
    elif route.get("depth_price_source"):
        route["depth_source"] = str(route["depth_price_source"])
    elif route.get("depth_method"):
        route["depth_source"] = str(route["depth_method"])

    if block_number is not None:
        route["depth_block_number"] = int(block_number)
    elif route.get("depth_block_number") is None and route.get("block_number") is not None:
        route["depth_block_number"] = route.get("block_number")

    if depth_confidence is not None:
        route["depth_confidence"] = depth_confidence
    elif route.get("depth_confidence") is None:
        status = str(route.get("depth_probe_status") or "")
        if status == "MEASURED_CAPACITY":
            route["depth_confidence"] = "measured"
        elif status in {"LOWER_BOUND_AT_MAX", "LOWER_BOUND_AT_MAX_PROBE"}:
            route["depth_confidence"] = "lower_bound"
        elif route.get("effective_depth_usd") is not None:
            route["depth_confidence"] = "inferred"

    depth = route.get("effective_depth_usd")
    if route.get("usable_depth_usd") is None and depth is not None:
        try:
            route["usable_depth_usd"] = round(float(depth), 2)
        except (TypeError, ValueError):
            pass

    route["depth_error_code"] = depth_error_code_from_probe(
        probe_error=route.get("depth_probe_error") or route.get("probe_error"),
        depth_probe_status=route.get("depth_probe_status"),
        effective_depth_usd=route.get("effective_depth_usd"),
    )
