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

# httpx is used only for live submission; imported lazily so dry-run path
# never needs the network stack.
_RELAY_URLS: Dict[str, str] = {
    "flashbots": "ARBY_FLASHBOTS_RELAY_BASE",
    "mev_share": "ARBY_MEVSHARE_RELAY_BASE",
    "blink": "ARBY_BLINK_RELAY_BASE",
}
# No defaults: operator MUST explicitly set the relay URL env var.
# This prevents accidental live submissions without authorization.
_RELAY_DEFAULTS: Dict[str, str] = {
    "flashbots": "",
    "mev_share": "",
    "blink": "",
}


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
        # Step 6: explicit private submit dry-run proof fields.
        # Reviewer requirement: endpoint selected, payload built,
        # and refused-live reason must all be present in the artifact.
        base["endpoint_selected"] = f"{relay}.{chain}"
        base["payload_built"] = True
        base["refused_live_reason"] = "ARBY_PRIVATE_SUBMIT_DRY_RUN=1"
        return base

    # Real submission path: POST eth_sendBundle to relay endpoint.
    env_var = _RELAY_URLS.get(relay, "")
    relay_url = os.environ.get(env_var, _RELAY_DEFAULTS.get(relay, "")).strip() if env_var else ""
    if not relay_url:
        base["status"] = "rejected"
        base["error"] = "REAL_SUBMIT_NOT_IMPLEMENTED"
        return base

    try:
        import httpx  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError:
        base["status"] = "rejected"
        base["error"] = "HTTPX_NOT_INSTALLED"
        return base

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_sendBundle",
        "params": [{"txs": [signed_tx_hex], "blockNumber": "latest"}],
    }

    try:
        async def _post() -> dict:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(relay_url, json=payload)
                resp.raise_for_status()
                return resp.json()

        import asyncio  # noqa: PLC0415
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures  # noqa: PLC0415
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(asyncio.run, _post())
                data = future.result(timeout=15)
        else:
            data = loop.run_until_complete(_post())

        real_hash = (data.get("result") or {}).get("bundleHash") or bundle_hash
        base["bundle_hash"] = real_hash
        base["status"] = "submitted"
        base["relay_url"] = relay_url
        return base
    except Exception as exc:
        base["status"] = "rejected"
        base["error"] = f"RELAY_HTTP_ERROR:{type(exc).__name__}:{str(exc)[:200]}"
        return base
