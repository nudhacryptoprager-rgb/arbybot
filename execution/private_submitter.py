"""E1.58 fix step #5: Private submission lane (Flashbots / MEV-Share / Blink).

This module provides a *dry-run-by-default* scaffold for submitting
signed transactions to private relays.  It deliberately performs **no
network IO** unless explicitly enabled by the operator with both:

  * ``ARBY_PRIVATE_SUBMIT_DRY_RUN=0`` (default ``1``) — disables dry-run
  * a non-empty relay endpoint configured per relay

The default behavior — used by tests, CI, and offline soaks — returns
a synthetic bundle hash derived from the signed transaction so that
downstream pipelines can be exercised end-to-end without ever touching
a real relay.  Real submissions are out-of-scope for this iteration
and require explicit operator authorization.

Public contract:

  * ``SUPPORTED_RELAYS`` — frozenset of accepted relay names.
  * ``submit_private(signed_tx_hex, *, relay, chain, dry_run=True) -> dict``
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Dict


SUPPORTED_RELAYS: frozenset = frozenset({"flashbots", "mev_share", "blink"})


def _dry_run_default() -> bool:
    return os.environ.get("ARBY_PRIVATE_SUBMIT_DRY_RUN", "1").strip() != "0"


def _synthetic_bundle_hash(signed_tx_hex: str) -> str:
    payload = (signed_tx_hex or "").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return "0x" + digest[:64]


def submit_private(
    signed_tx_hex: str,
    *,
    relay: str,
    chain: str,
    dry_run: bool | None = None,
) -> Dict[str, Any]:
    """Submit ``signed_tx_hex`` to a private relay (or simulate doing so).

    Returns a dict with at minimum:
      * ``status``: one of ``"dry_run_submitted"``, ``"rejected"``,
        ``"submitted"`` (the latter only on real submission, not yet
        wired up).
      * ``relay``: echoed relay name.
      * ``chain``: echoed chain.
      * ``bundle_hash``: synthetic hash on dry_run, real hash on submit.
      * ``dry_run``: bool.

    Failure modes (dry_run still returns a synthetic bundle but with
    ``status="rejected"``):
      * unsupported relay
      * empty signed_tx_hex
    """
    effective_dry_run = _dry_run_default() if dry_run is None else bool(dry_run)

    base: Dict[str, Any] = {
        "relay": relay,
        "chain": chain,
        "dry_run": effective_dry_run,
        "bundle_hash": None,
        "status": "rejected",
        "error": None,
    }

    if not signed_tx_hex:
        base["error"] = "EMPTY_SIGNED_TX"
        return base

    if relay not in SUPPORTED_RELAYS:
        base["error"] = f"UNSUPPORTED_RELAY:{relay}"
        return base

    bundle_hash = _synthetic_bundle_hash(signed_tx_hex)
    base["bundle_hash"] = bundle_hash

    if effective_dry_run:
        base["status"] = "dry_run_submitted"
        return base

    # Real submission path is intentionally NOT implemented yet.
    # Operators must extend this branch with relay-specific HTTP calls
    # and supply credentials via environment variables.  Until then,
    # the module refuses to perform real submissions.
    base["status"] = "rejected"
    base["error"] = "REAL_SUBMIT_NOT_IMPLEMENTED"
    return base
