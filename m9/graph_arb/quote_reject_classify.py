"""Classify adapter-specific quote failures into actionable reject reasons."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

# Balancer V2 error codes (subset used in Base shadow RCA).
_BALANCER_CODES: Dict[str, Tuple[str, str]] = {
    "BAL#304": ("BALANCER_MAX_IN_RATIO", "Swap amount exceeds pool max in-ratio"),
    "BAL#305": ("BALANCER_MAX_OUT_RATIO", "Swap would exceed pool max out-ratio"),
    "BAL#309": ("BALANCER_INVALID_TOKEN", "Token not registered in pool"),
    "BAL#327": ("BALANCER_SWAPS_DISABLED", "Pool swaps disabled"),
    "BAL#402": ("BALANCER_PAUSED", "Vault or pool paused"),
    "BAL#406": ("BALANCER_INSUFFICIENT_BALANCE", "Insufficient pool balance for swap"),
    "BAL#521": ("BALANCER_POOL_NOT_REGISTERED", "Pool not registered in vault"),
}

_BAL_CODE_RE = re.compile(r"BAL#\d+", re.IGNORECASE)


def extract_balancer_code(err: str) -> Optional[str]:
    m = _BAL_CODE_RE.search(err or "")
    if not m:
        return None
    return m.group(0).upper()


def balancer_reason_for_code(code: str) -> Optional[str]:
    entry = _BALANCER_CODES.get((code or "").upper())
    return entry[1] if entry else None


def classify_balancer_revert(
    err: str,
    *,
    has_metadata: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Return (reject_reason, detail) for a Balancer quote failure."""
    code = extract_balancer_code(err)
    if code and code in _BALANCER_CODES:
        reason, desc = _BALANCER_CODES[code]
        return reason, {"balancer_code": code, "balancer_reason": desc}
    if code:
        return "BALANCER_QUOTE_REVERT", {"balancer_code": code, "balancer_reason": "unknown_balancer_code"}
    if "token pair not in all_assets" in (err or "").lower():
        return "QUOTE_CONFIG_MISSING__BALANCER_ASSETS", {"balancer_reason": "token_pair_not_in_assets"}
    if "balancer_metadata_incomplete" in (err or "").lower() or (
        "missing pool_id or balancer_assets" in (err or "").lower()
    ):
        return "BALANCER_METADATA_INCOMPLETE", {"balancer_reason": "metadata_incomplete"}
    if has_metadata:
        return "BALANCER_UNKNOWN_REVERT_WITH_METADATA", {
            "balancer_reason": "revert_with_complete_metadata",
        }
    return "QUOTE_REVERT", {}


def _maverick_detail_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    detail: Dict[str, Any] = {}
    for key in (
        "quote_contour",
        "quote_target",
        "quote_selector",
        "token_a_in",
        "token_in",
        "token_a",
        "pool_address",
        "probe_amount_in",
    ):
        if payload.get(key) is not None:
            detail[key] = payload[key]
    if payload.get("raw_error") is not None:
        detail["raw_error"] = payload["raw_error"]
    return detail


def _maverick_contour_reason(contour: str, raw_err: str) -> str:
    low = (raw_err or "").lower()
    if "maverick_zero_out" in low or "zero out" in low:
        return "MAVERICK_NO_LIQUIDITY"
    if "empty/short result" in low or low.strip() in ("0x", "0x0"):
        return "MAVERICK_NO_LIQUIDITY"
    contour_lc = (contour or "").lower()
    if contour_lc == "pool_direct":
        return "MAVERICK_POOL_DIRECT_REVERT"
    if contour_lc in ("maverick_quoter", "pool_information"):
        return "MAVERICK_QUOTER_REVERT"
    if "execution reverted" in low or "revert" in low:
        return "MAVERICK_QUOTE_REVERT"
    return "MAVERICK_QUOTE_REVERT"


def classify_maverick_no_probe_for_token_in(token_in: str) -> Tuple[str, Dict[str, Any]]:
    return "NO_ACTIVE_LIQUIDITY_FOR_TOKEN_IN", {
        "maverick_reason": "no_probe_for_token_in",
        "token_in": (token_in or "").lower(),
    }


def classify_maverick_revert(err: str) -> Tuple[str, Dict[str, Any]]:
    """Return (reject_reason, detail) for a Maverick quote failure."""
    stripped = (err or "").strip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                detail = _maverick_detail_from_payload(payload)
                status = str(payload.get("status") or "")
                raw = str(payload.get("raw_error") or "")
                contour = str(payload.get("quote_contour") or "")
                if status == "MAVERICK_ZERO_OUT":
                    return "MAVERICK_NO_LIQUIDITY", {**detail, "maverick_reason": "zero_output"}
                reason = _maverick_contour_reason(contour, raw or stripped)
                return reason, {**detail, "maverick_reason": reason.lower()}
        except json.JSONDecodeError:
            pass

    low = stripped.lower()
    if "maverick_zero_out" in low or "zero out" in low:
        return "MAVERICK_NO_LIQUIDITY", {"maverick_reason": "zero_output"}
    if "tokena() lookup failed" in low or ("token_a" in low and "lookup failed" in low):
        return "MAVERICK_BAD_POOL_CONFIG", {"maverick_reason": "token_a_lookup_failed"}
    if "bad direction" in low:
        return "MAVERICK_BAD_DIRECTION", {"maverick_reason": "bad_swap_direction"}
    if "pool_direct" in low and ("empty/short" in low or "revert" in low):
        return "MAVERICK_POOL_DIRECT_REVERT", {"maverick_reason": "pool_direct_revert"}
    if "maverick_quoter" in low and ("empty/short" in low or "revert" in low):
        return "MAVERICK_QUOTER_REVERT", {"maverick_reason": "quoter_revert"}
    if "empty/short result" in low or low.strip() in ("0x", "0x0"):
        return "MAVERICK_NO_LIQUIDITY", {"maverick_reason": "empty_call_result"}
    if "encode" in low or "calldata" in low:
        return "MAVERICK_ADAPTER_ENCODE_ERROR", {"maverick_reason": "encode_error"}
    if "execution reverted" in low or "revert" in low:
        return "MAVERICK_QUOTE_REVERT", {"maverick_reason": "execution_reverted"}
    return "MAVERICK_QUOTE_REVERT", {"maverick_reason": "unclassified_maverick_failure"}


def classify_quote_failure(
    adapter_type: str,
    err: str,
    *,
    has_balancer_metadata: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Map raw exception text to a specific reject_reason + detail dict."""
    at = (adapter_type or "").lower()
    if at.startswith("balancer"):
        return classify_balancer_revert(err, has_metadata=has_balancer_metadata)
    if at == "maverick_v2":
        return classify_maverick_revert(err)
    if "execution reverted" in (err or "").lower() or "revert" in (err or "").lower():
        return "QUOTE_REVERT", {}
    return "QUOTE_RPC_ERROR", {}


# Permanent quarantine on first sight — pool/vault cannot quote.
BALANCER_PERMANENT_QUARANTINE_CODES = frozenset({"BAL#402", "BAL#327", "BAL#521"})

# Depth/sizing signals — quarantine after repeats once decimals/price truth is correct.
BALANCER_AUTO_QUARANTINE_CODES = frozenset({"BAL#304", "BAL#305"})

# Reject reasons treated as hard structural failures (quarantine / pre-admission).
HARD_QUOTE_REJECTS = frozenset(
    {
        "QUOTE_REVERT",
        "QUOTE_RPC_ERROR",
        "QUOTE_ZERO_OUTPUT",
        "QUOTE_CONFIG_MISSING",
        "QUOTE_CONFIG_MISSING__BALANCER_POOL_ID",
        "QUOTE_CONFIG_MISSING__BALANCER_ASSETS",
        "BALANCER_MAX_IN_RATIO",
        "BALANCER_MAX_OUT_RATIO",
        "BALANCER_PAUSED",
        "BALANCER_SWAPS_DISABLED",
        "BALANCER_INVALID_TOKEN",
        "BALANCER_INSUFFICIENT_BALANCE",
        "BALANCER_POOL_NOT_REGISTERED",
        "BALANCER_QUOTE_REVERT",
        "BALANCER_METADATA_INCOMPLETE",
        "BALANCER_UNKNOWN_REVERT_WITH_METADATA",
        "MAVERICK_BAD_DIRECTION",
        "MAVERICK_BAD_POOL_CONFIG",
        "MAVERICK_ADAPTER_ENCODE_ERROR",
        "MAVERICK_PROBE_AMOUNT_OUT_OF_RANGE",
        "LEG_AMOUNT_EXCEEDS_POOL_CAPACITY",
        "ONE_DIRECTION_ONLY",
        "NO_ACTIVE_LIQUIDITY_FOR_TOKEN_IN",
        "MAVERICK_QUOTE_REVERT",
        "MAVERICK_QUOTER_REVERT",
        "MAVERICK_POOL_DIRECT_REVERT",
        "UNKNOWN_PRICE_ADMISSION_REJECT",
        "TOKEN_DECIMALS_UNKNOWN",
        "UNKNOWN_PRICE",
    }
)
