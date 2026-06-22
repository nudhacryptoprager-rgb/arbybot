"""M8.3 token contract risk preflight (warning-only flags, no economics)."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

from m8.metadata.registry import (
    ERROR_ERC20_DECIMALS_REVERT,
    ERROR_NO_CODE,
    ERROR_NON_ERC20,
    is_valid_eth_address,
)

_ERC20_TRANSFER_SELECTOR = "a9059cbb"
_ERC20_APPROVE_SELECTOR = "095ea7b3"
_PUSH4_OPCODE = "63"
_SELECTOR_HEX_RE = re.compile(r"^[0-9a-f]{8}$")

# Fee-on-transfer cannot be inferred from standard ERC20 transfer/transferFrom selectors.
# Bytecode-only warnings use tax-specific selectors; simulation hints are out of band.
_RISK_FLAG_SELECTORS: Dict[str, tuple[str, ...]] = {
    "fee_on_transfer_suspected": ("0d8e6e2c", "2517bc3c", "c0246668"),
    "rebasing_suspected": ("1a906524", "0b295529", "ea598cb0"),
    "blacklist_like_selectors": ("fe575a87", "e47cbca3", "5342acb4"),
    "whitelist_like_selectors": ("3af32abf", "e43252d7"),
    "pausable_like_selectors": ("5c975abb", "8456cb59"),
    "max_tx_like_selectors": ("c63d115b", "f8b2cb4f", "df8b5ed2"),
    "mintable_like_selectors": ("40c10f19", "1249c58b"),
}

_EIP1167_PREFIX = "363d3d373d3d3d363d73"


def risk_flag_selector_lengths_valid() -> bool:
    """All configured selectors must be exactly 4 bytes (8 hex chars)."""
    for selectors in _RISK_FLAG_SELECTORS.values():
        for sel in selectors:
            if not _SELECTOR_HEX_RE.match(sel.lower()):
                return False
    return True


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


def _detect_proxy(code: bytes) -> Tuple[bool, Optional[str], Optional[str]]:
    if not code:
        return False, None, None
    hex_code = code.hex().lower()
    if _EIP1167_PREFIX in hex_code and len(hex_code) >= 90:
        impl = "0x" + hex_code[hex_code.find(_EIP1167_PREFIX) + 20 : hex_code.find(_EIP1167_PREFIX) + 60]
        if is_valid_eth_address(impl):
            return True, impl.lower(), "EIP1167"
    return False, None, None


def _selector_present(code: bytes, selector: str) -> bool:
    """True when selector appears as Solidity PUSH4 dispatch entry (opcode 0x63)."""
    if not code or len(code) <= 2:
        return False
    sel = str(selector or "").lower().replace("0x", "")
    if len(sel) != 8 or not _SELECTOR_HEX_RE.match(sel):
        return False
    return f"{_PUSH4_OPCODE}{sel}" in code.hex().lower()


def _scan_risk_flags(code: bytes) -> Dict[str, bool]:
    if not code or len(code) <= 2:
        return {k: False for k in _RISK_FLAG_SELECTORS if k != "mintable_like_selectors"}
    out: Dict[str, bool] = {}
    for flag, selectors in _RISK_FLAG_SELECTORS.items():
        if flag == "mintable_like_selectors":
            continue
        out[flag] = any(_selector_present(code, sel) for sel in selectors)
    return out


def build_token_execution_preflight(
    address: str,
    *,
    w3: Any = None,
    code: Optional[bytes] = None,
    code_length: Optional[int] = None,
    error_code: Optional[str] = None,
    decimals_resolved: bool = False,
) -> Dict[str, Any]:
    addr = str(address or "").lower()
    if code is None and w3 is not None:
        code = _fetch_code(w3, addr)
    code = code or b""
    if code_length is None:
        code_length = len(code) if code and len(code) > 2 else 0
    is_contract = code_length > 0
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
        "is_contract": is_contract,
        "code_length": code_length,
        "code_hash": _code_hash(code) if is_contract else None,
        "erc20_methods_ok": erc20_methods_ok,
        "transfer_selector_present": _selector_present(code, _ERC20_TRANSFER_SELECTOR),
        "approve_selector_present": _selector_present(code, _ERC20_APPROVE_SELECTOR),
        "non_erc20_reason": non_erc20_reason,
    }


def build_proxy_metadata(
    address: str,
    *,
    w3: Any = None,
    code: Optional[bytes] = None,
) -> Dict[str, Any]:
    addr = str(address or "").lower()
    if code is None and w3 is not None:
        code = _fetch_code(w3, addr)
    code = code or b""
    proxy_detected, implementation, proxy_standard = _detect_proxy(code)
    impl_hash: Optional[str] = None
    if proxy_detected and implementation and w3 is not None:
        impl_code = _fetch_code(w3, implementation)
        impl_hash = _code_hash(impl_code)
    return {
        "address": addr,
        "proxy_detected": proxy_detected,
        "implementation_address": implementation,
        "proxy_standard": proxy_standard,
        "implementation_code_hash": impl_hash,
    }


def build_token_risk_flags(
    *,
    code: Optional[bytes] = None,
    w3: Any = None,
    address: Optional[str] = None,
) -> Dict[str, bool]:
    if code is None and w3 is not None and address:
        code = _fetch_code(w3, address)
    return _scan_risk_flags(code or b"")


def build_token_preflight_bundle(
    address: str,
    *,
    w3: Any = None,
    code_length: Optional[int] = None,
    error_code: Optional[str] = None,
    decimals_resolved: bool = False,
) -> Dict[str, Any]:
    """Full token preflight: execution + risk flags + proxy (single code fetch)."""
    addr = str(address or "").lower()
    code = _fetch_code(w3, addr) if w3 is not None else b""
    execution = build_token_execution_preflight(
        addr,
        code=code,
        code_length=code_length,
        error_code=error_code,
        decimals_resolved=decimals_resolved,
    )
    proxy = build_proxy_metadata(addr, code=code)
    flags = build_token_risk_flags(code=code)
    legacy = {
        "address": addr,
        **execution,
        "proxy_detected": proxy.get("proxy_detected"),
        "implementation": proxy.get("implementation_address"),
        "token_behavior_flags": flags,
    }
    return {
        "token_execution_preflight": execution,
        "token_risk_flags": flags,
        "proxy_metadata": proxy,
        "token_risk_metadata": legacy,
    }


def build_token_risk_metadata(
    address: str,
    *,
    w3: Any = None,
    code_length: Optional[int] = None,
    error_code: Optional[str] = None,
    decimals_resolved: bool = False,
) -> Dict[str, Any]:
    """Backward-compatible combined token risk row."""
    return build_token_preflight_bundle(
        address,
        w3=w3,
        code_length=code_length,
        error_code=error_code,
        decimals_resolved=decimals_resolved,
    )["token_risk_metadata"]


def risk_warnings_for_token(risk: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    if risk.get("non_erc20_reason"):
        warnings.append(str(risk["non_erc20_reason"]))
    if risk.get("proxy_detected"):
        warnings.append("PROXY_DETECTED")
    flags = risk.get("token_risk_flags") or risk.get("token_behavior_flags") or {}
    for flag, active in flags.items():
        if active:
            warnings.append(str(flag).upper())
    return warnings
