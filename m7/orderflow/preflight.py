"""E1.58 fix step #2: Execution preflight checks.

Pure read-only on-chain checks that produce additional submit blockers
when an arbitrage candidate is otherwise simulation-ready but lacks
the operational prerequisites needed for a real submit:

  * router contract exists at the configured address (eth_getCode != 0x)
  * owner wallet has sufficient input-token balance
  * owner wallet has sufficient ERC-20 allowance for the router

This module is strictly opt-in via ``ARBY_EXECUTION_PREFLIGHT=1``.  It
is **read-only** — no transactions are signed or submitted.  All checks
return ``(ok: bool, reason: str)`` tuples.  The single integration
point is :func:`run_preflight`, which produces a list of blockers
suitable for appending to ``ExecutionGateResult.submit_blockers``.

Design contract (frozen for downstream tests):

  * ``check_router_exists(w3, router) -> (bool, reason)``
  * ``check_balance(w3, token, owner, min_amount_wei) -> (bool, reason)``
  * ``check_allowance(w3, token, owner, spender, min_amount_wei) -> (bool, reason)``
  * ``run_preflight(w3, *, router, token_in, owner, amount_wei) -> List[str]``

Reason strings use the prefix ``PREFLIGHT_`` so reviewers can grep them
out of submit_blockers histograms.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

# Minimal ERC-20 ABI fragments needed for balanceOf + allowance calls.
_ERC20_BALANCE_OF_ABI = {
    "constant": True,
    "inputs": [{"name": "_owner", "type": "address"}],
    "name": "balanceOf",
    "outputs": [{"name": "balance", "type": "uint256"}],
    "type": "function",
}
_ERC20_ALLOWANCE_ABI = {
    "constant": True,
    "inputs": [
        {"name": "_owner", "type": "address"},
        {"name": "_spender", "type": "address"},
    ],
    "name": "allowance",
    "outputs": [{"name": "remaining", "type": "uint256"}],
    "type": "function",
}
_ERC20_ABI = [_ERC20_BALANCE_OF_ABI, _ERC20_ALLOWANCE_ABI]


def is_enabled() -> bool:
    """Return True when ARBY_EXECUTION_PREFLIGHT=1 in the environment."""
    return os.environ.get("ARBY_EXECUTION_PREFLIGHT", "0").strip() == "1"


def check_router_exists(w3, router: str) -> Tuple[bool, str]:
    """Return (True, '') if there is contract bytecode at *router*.

    Failure modes return ``(False, "PREFLIGHT_ROUTER_*")`` so reviewers
    can distinguish "router address is an EOA" from "RPC failed".
    """
    if not router:
        return False, "PREFLIGHT_ROUTER_MISSING"
    try:
        code = w3.eth.get_code(router)
    except Exception as exc:  # pragma: no cover - depends on RPC failure mode
        return False, f"PREFLIGHT_ROUTER_RPC_ERROR:{type(exc).__name__}"
    # web3 v6 returns HexBytes; "0x" or empty bytes both mean no contract.
    raw = bytes(code) if code is not None else b""
    if not raw or raw == b"\x00" * len(raw):
        return False, "PREFLIGHT_ROUTER_NO_CODE"
    # treat 0x (length 0 or only "0x" prefix) as no code
    try:
        hex_form = code.hex() if hasattr(code, "hex") else str(code)
    except Exception:
        hex_form = ""
    if hex_form in ("", "0x", "0x0"):
        return False, "PREFLIGHT_ROUTER_NO_CODE"
    return True, ""


def check_balance(
    w3,
    token: str,
    owner: str,
    min_amount_wei: int,
) -> Tuple[bool, str]:
    """Return (True, '') if *owner* holds >= min_amount_wei of *token*.

    For native-coin spend (token is None / zero address), uses
    ``eth.get_balance``.  Otherwise calls ``balanceOf(owner)`` via
    web3 ``eth_call`` (read-only).
    """
    if min_amount_wei <= 0:
        # nothing to check — treat as pass to avoid false-negatives
        return True, ""
    if not owner:
        return False, "PREFLIGHT_OWNER_MISSING"
    try:
        is_native = token is None or token == "" or int(str(token), 16) == 0
    except (TypeError, ValueError):
        is_native = False
    try:
        if is_native:
            bal = int(w3.eth.get_balance(owner))
        else:
            contract = w3.eth.contract(address=token, abi=_ERC20_ABI)
            bal = int(contract.functions.balanceOf(owner).call())
    except Exception as exc:  # pragma: no cover - RPC dependent
        return False, f"PREFLIGHT_BALANCE_RPC_ERROR:{type(exc).__name__}"
    if bal < min_amount_wei:
        return False, f"PREFLIGHT_BALANCE_INSUFFICIENT:{bal}<{min_amount_wei}"
    return True, ""


def check_allowance(
    w3,
    token: str,
    owner: str,
    spender: str,
    min_amount_wei: int,
) -> Tuple[bool, str]:
    """Return (True, '') if *owner* has >= min_amount_wei allowance for *spender*.

    Skipped automatically for native-coin spends (no ERC-20 allowance
    concept).  Failure modes use ``PREFLIGHT_ALLOWANCE_*`` reasons.
    """
    if min_amount_wei <= 0:
        return True, ""
    if not owner or not spender:
        return False, "PREFLIGHT_ALLOWANCE_MISSING_PARTY"
    try:
        is_native = token is None or token == "" or int(str(token), 16) == 0
    except (TypeError, ValueError):
        is_native = False
    if is_native:
        # native-coin spend doesn't need allowance
        return True, ""
    try:
        contract = w3.eth.contract(address=token, abi=_ERC20_ABI)
        allowed = int(contract.functions.allowance(owner, spender).call())
    except Exception as exc:  # pragma: no cover - RPC dependent
        return False, f"PREFLIGHT_ALLOWANCE_RPC_ERROR:{type(exc).__name__}"
    if allowed < min_amount_wei:
        return False, f"PREFLIGHT_ALLOWANCE_INSUFFICIENT:{allowed}<{min_amount_wei}"
    return True, ""


def run_preflight(
    w3,
    *,
    router: Optional[str],
    token_in: Optional[str],
    owner: Optional[str],
    amount_wei: int,
) -> List[str]:
    """Run all preflight checks and return a list of blocker reasons.

    Empty list means all checks passed (or were skipped because
    inputs were absent).  Order is stable: router, balance, allowance.

    The function never raises — it converts every failure into a
    ``PREFLIGHT_*`` blocker string so the caller can simply extend
    its existing ``submit_blockers`` list.
    """
    blockers: List[str] = []
    if w3 is None:
        return ["PREFLIGHT_W3_UNAVAILABLE"]

    # 1. router existence
    if router:
        ok, reason = check_router_exists(w3, router)
        if not ok:
            blockers.append(reason)
    else:
        blockers.append("PREFLIGHT_ROUTER_MISSING")

    # 2. balance
    if owner and amount_wei > 0:
        ok, reason = check_balance(w3, token_in or "", owner, int(amount_wei))
        if not ok:
            blockers.append(reason)
    elif amount_wei <= 0:
        # zero-amount swap is invalid input — flag for visibility
        blockers.append("PREFLIGHT_AMOUNT_ZERO")

    # 3. allowance (only meaningful when router + owner known + ERC-20)
    if router and owner and amount_wei > 0:
        ok, reason = check_allowance(
            w3, token_in or "", owner, router, int(amount_wei)
        )
        if not ok:
            blockers.append(reason)

    return blockers
