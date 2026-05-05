"""E1.58 fix step #3: Canary live-submit (1-wei self-transfer scaffold).

A *dry-run-by-default* helper that emulates submitting a 1-wei native
self-transfer as a smoke test before unlocking real arb submission.
The dry-run path produces a synthetic receipt and never makes RPC
calls; the live path is intentionally not implemented in this
iteration and is gated on operator opt-in via
``ARBY_CANARY_DRY_RUN=0``.

Public contract:

  * ``submit_canary(w3, *, owner, chain, amount_wei=1, dry_run=None) -> dict``
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Dict


def _dry_run_default() -> bool:
    return os.environ.get("ARBY_CANARY_DRY_RUN", "1").strip() != "0"


def _synthetic_tx_hash(owner: str, chain: str, amount_wei: int) -> str:
    payload = f"{owner}|{chain}|{amount_wei}|{time.time_ns()}".encode("utf-8")
    return "0x" + hashlib.sha256(payload).hexdigest()


def submit_canary(
    w3,
    *,
    owner: str,
    chain: str,
    amount_wei: int = 1,
    dry_run: bool | None = None,
) -> Dict[str, Any]:
    """Submit (or simulate submitting) a 1-wei self-transfer.

    Returns a dict with at minimum:
      * ``status``: ``"dry_run_submitted"`` | ``"rejected"`` |
        ``"submitted"`` (last reserved for future live impl).
      * ``tx_hash``: synthetic on dry_run, real on submit.
      * ``chain``, ``owner``, ``amount_wei``, ``dry_run``.
    """
    effective_dry = _dry_run_default() if dry_run is None else bool(dry_run)
    base: Dict[str, Any] = {
        "status": "rejected",
        "tx_hash": None,
        "chain": chain,
        "owner": owner,
        "amount_wei": int(amount_wei),
        "dry_run": effective_dry,
        "error": None,
    }

    if not owner:
        base["error"] = "OWNER_MISSING"
        return base
    if amount_wei <= 0:
        base["error"] = "AMOUNT_NON_POSITIVE"
        return base

    if effective_dry:
        base["status"] = "dry_run_submitted"
        base["tx_hash"] = _synthetic_tx_hash(owner, chain, int(amount_wei))
        return base

    # Live submission path is intentionally not implemented.  The
    # operator must wire up signing + sendRawTransaction here and
    # provide the necessary credentials.  Until then, refuse.
    base["error"] = "LIVE_CANARY_NOT_IMPLEMENTED"
    return base
