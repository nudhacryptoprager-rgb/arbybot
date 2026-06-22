"""M8.3 token contract risk preflight (warning-only flags, no economics)."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Set

from m8.metadata.registry import (
    ERROR_ERC20_DECIMALS_REVERT,
    ERROR_NO_CODE,
    ERROR_NON_ERC20,
    is_valid_eth_address,
)

# Common selector prefixes found in bytecode (risk hints only, not verdicts).
_BEHAVIOR_SELECTOR_HINTS: Dict[str, tuple[str, ...]] = {
    "pausable_like_selectors": ("5c975abb", "8456cb59"),  # paused(), unpause
    "blacklist_like_selectors": ("fe575a87", "e47cbca3", "5342acb4"),
    "mintable_like_selectors": ("40c10f19", "1249c58b"),  # mint variants
    "fee_on_transfer_suspected": ("a9059cbb", "23b872dd"),  # transfer hooks heuristics
    "rebasing_suspected": ("1a906524", "0b295529"),  # rebase/shares hints
}

_EIP1167_PREFIX = "363d3d373d3d3d363d73"


def _fetch_code(w3: Any, addr: str) -> bytes:
    try:
        raw = w3.eth.get_code(w3.to_checksum_address(addr))
        return bytes(raw) if raw else b""
    except Exception:
        return b""


def _code_hash(code: bytes) -> Optional[str]:
    if not code or len(code) <= 2:
        return None
    return "0x" + hashlib.sha256(code).hexdigest()


def _detect_proxy(code: bytes) -> tuple[bool, Optional[str]]:
    if not code:
        return False, None
    hex_code = code.hex().lower()
    if _EIP1167_PREFIX in hex_code and len(hex_code) >= 90:
        impl = "0x" + hex_code[hex_code.find(_EIP1167_PREFIX) + 20 : hex_code.find(_EIP1167_PREFIX) + 60]
        if is_valid_eth_address(impl):
            return True, impl.lower()
    return False, None


def _scan_behavior_flags(code: bytes) -> Dict[str, bool]:
    if not code or len(code) <= 2:
        return {k: False for k in _BEHAVIOR_SELECTOR_HINTS}
    hex_code = code.hex().lower()
    out: Dict[str, bool] = {}
    for flag, selectors in _BEHAVIOR_SELECTOR_HINTS.items():
        out[flag] = any(sel in hex_code for sel in selectors)
    return out


def build_token_risk_metadata(
    address: str,
    *,
    w3: Any = None,
    code_length: Optional[int] = None,
    error_code: Optional[str] = None,
    decimals_resolved: bool = False,
) -> Dict[str, Any]:
    """Static/semi-static token risk preflight for one address."""
    addr = str(address or "").lower()
    code = _fetch_code(w3, addr) if w3 is not None else b""
    if code_length is None:
        code_length = len(code) if code and len(code) > 2 else 0

    is_contract = code_length > 0
    proxy_detected, implementation = _detect_proxy(code)
    behavior = _scan_behavior_flags(code)

    non_erc20_reason: Optional[str] = None
    if error_code in (ERROR_NO_CODE,):
        non_erc20_reason = "NO_CODE"
    elif error_code in (ERROR_NON_ERC20, ERROR_ERC20_DECIMALS_REVERT):
        non_erc20_reason = str(error_code)
    elif not is_contract:
        non_erc20_reason = "NO_CODE"

    erc20_methods_ok = bool(decimals_resolved and is_contract and not non_erc20_reason)

    return {
        "address": addr,
        "code_hash": _code_hash(code) if is_contract else None,
        "code_length": code_length,
        "is_contract": is_contract,
        "proxy_detected": proxy_detected,
        "implementation": implementation,
        "erc20_methods_ok": erc20_methods_ok,
        "non_erc20_reason": non_erc20_reason,
        "token_behavior_flags": behavior,
    }


def risk_warnings_for_token(risk: Dict[str, Any]) -> List[str]:
    """Non-blocking risk warnings for acceptance diagnostics."""
    warnings: List[str] = []
    if risk.get("non_erc20_reason"):
        warnings.append(str(risk["non_erc20_reason"]))
    if risk.get("proxy_detected"):
        warnings.append("PROXY_DETECTED")
    flags = risk.get("token_behavior_flags") or {}
    for flag, active in flags.items():
        if active:
            warnings.append(str(flag).upper())
    return warnings
