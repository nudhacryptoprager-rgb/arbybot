"""E1.59 step #3: HTTP-only Flashblocks pending-logs lane.

Reviewer 3h-soak finding: WS Flashblocks endpoint shows 405 + 41/37 (PROD/DISC)
``session_ws_failed_429_windows``. The Base docs split Flashblocks into:

  * WSS lane: ``pendingLogs`` / ``newFlashblocks`` — paid/private providers.
  * HTTP lane: ``eth_getLogs`` with ``fromBlock=toBlock="pending"`` — works
    against public + dRPC if the call surface is narrow (pool addresses +
    topic0 filters) so we don't trigger free-tier guard rails.

This module implements the HTTP lane only. It is intentionally minimal:

  * ``fetch_pending_pool_logs(...)`` — single ``eth_getLogs`` call with
    ``fromBlock=toBlock="pending"``, scoped to specific addresses + topics.
  * Token bucket via ``core.provider_throttle.provider_throttle`` ("logs"
    bucket) so we honour the per-method circuit breaker on 408/429.
  * Returns the parsed log list (or [] on error). All errors are reported
    back through ``provider_throttle.record_response`` so the breaker
    learns.

Default OFF — opt-in via ``ARBY_FLASHBLOCKS_HTTP_LANE=1``.

Reference:
  https://docs.base.org/base-chain/api-reference/flashblocks-api/pendingLogs
  https://docs.base.org/base-chain/api-reference/ethereum-json-rpc-api/eth_getLogs
"""
from __future__ import annotations

import json
import logging
import os
from typing import Callable, List, Optional, Sequence

from core.provider_throttle import provider_throttle

logger = logging.getLogger("chains.flashblocks_http")

# Sentinel block tag for the pending Flashblock state.
PENDING_BLOCK_TAG = "pending"

# Public stats counters; surfaced by the rollup writer.
_STATS = {
    "calls_attempted": 0,
    "calls_ok": 0,
    "calls_blocked_by_breaker": 0,
    "calls_408": 0,
    "calls_429": 0,
    "calls_other_error": 0,
    "logs_returned_total": 0,
    "last_error": None,
}


def is_enabled() -> bool:
    return os.environ.get("ARBY_FLASHBLOCKS_HTTP_LANE", "0") == "1"


def reset_stats() -> None:
    for k in (
        "calls_attempted",
        "calls_ok",
        "calls_blocked_by_breaker",
        "calls_408",
        "calls_429",
        "calls_other_error",
        "logs_returned_total",
    ):
        _STATS[k] = 0
    _STATS["last_error"] = None


def stats() -> dict:
    return dict(_STATS)


def _build_payload(
    addresses: Sequence[str],
    topics: Optional[Sequence[Optional[str]]] = None,
) -> dict:
    """Construct the eth_getLogs JSON-RPC payload."""
    # E1.70 fix 8: ARBY_FLASHBLOCKS_USE_LATEST=1 falls back to "latest"
    # when the RPC does not support the "pending" block tag (most Alchemy /
    # dRPC endpoints).  This allows flashblocks_http_calls_ok > 0 at the
    # cost of slightly stale logs (still useful for pool-state updates).
    _block_tag = (
        "latest"
        if os.environ.get("ARBY_FLASHBLOCKS_USE_LATEST", "0") == "1"
        else PENDING_BLOCK_TAG
    )
    params = {
        "fromBlock": _block_tag,
        "toBlock": _block_tag,
        "address": list(addresses) if len(addresses) > 1 else addresses[0],
    }
    if topics:
        params["topics"] = list(topics)
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getLogs",
        "params": [params],
    }


def fetch_pending_pool_logs(
    *,
    rpc_url: str,
    addresses: Sequence[str],
    topics: Optional[Sequence[Optional[str]]] = None,
    http_post: Callable[[str, dict, float], dict],
    timeout_s: float = 5.0,
) -> List[dict]:
    """Fetch pending logs for a narrow set of pool addresses.

    Args:
      rpc_url: HTTP RPC endpoint that supports ``eth_getLogs`` with
        ``fromBlock=toBlock="pending"``.
      addresses: Pool addresses to scope the query (REQUIRED — empty
        addresses are rejected to avoid wide scans).
      topics: Optional topic filter (typically ``[swap_topic0]``).
      http_post: Caller-supplied transport returning the parsed JSON-RPC
        response dict. Must raise on transport error and accept a
        timeout in seconds. Inject in tests.
      timeout_s: Per-request timeout passed to ``http_post``.

    Returns:
      List of log entries (possibly empty). Empty when:
        * lane is disabled,
        * breaker is OPEN (cooldown),
        * transport / RPC reported error.
    """
    if not is_enabled():
        return []
    if not addresses:
        logger.debug("flashblocks_http: empty addresses — rejecting wide scan")
        return []

    if not provider_throttle.acquire("logs", blocking=False):
        _STATS["calls_blocked_by_breaker"] += 1
        return []

    payload = _build_payload(addresses, topics)
    _STATS["calls_attempted"] += 1
    try:
        resp = http_post(rpc_url, payload, timeout_s)
    except TimeoutError as exc:  # transport timeout maps to 408 semantically
        _STATS["calls_408"] += 1
        _STATS["last_error"] = f"timeout: {str(exc)[:120]}"
        provider_throttle.record_response("logs", status_code=408)
        return []
    except Exception as exc:
        _STATS["calls_other_error"] += 1
        _STATS["last_error"] = str(exc)[:200]
        provider_throttle.record_response("logs", ok=False)
        return []

    if not isinstance(resp, dict):
        _STATS["calls_other_error"] += 1
        _STATS["last_error"] = "non-dict RPC response"
        provider_throttle.record_response("logs", ok=False)
        return []

    if "error" in resp and resp["error"]:
        err = resp["error"]
        # Detect 429-equivalent in JSON-RPC error envelopes.
        msg = (err.get("message") if isinstance(err, dict) else str(err)) or ""
        msg_lower = msg.lower()
        if "rate limit" in msg_lower or "too many" in msg_lower or "429" in msg:
            _STATS["calls_429"] += 1
            provider_throttle.record_response("logs", status_code=429)
        else:
            _STATS["calls_other_error"] += 1
            provider_throttle.record_response("logs", ok=False)
        _STATS["last_error"] = str(err)[:200]
        return []

    result = resp.get("result")
    if not isinstance(result, list):
        _STATS["calls_other_error"] += 1
        _STATS["last_error"] = "result not a list"
        provider_throttle.record_response("logs", ok=False)
        return []

    _STATS["calls_ok"] += 1
    _STATS["logs_returned_total"] += len(result)
    provider_throttle.record_response("logs", ok=True)
    return result


def pending_sim_enabled() -> bool:
    """E1.77 step 9: pending-state simulation switch.

    Two ENV gates must be ON:
      * ``ARBY_FLASHBLOCKS_HTTP_LANE=1``  — log lane available,
      * ``ARBY_PENDING_SIM_ENABLE=1``     — caller opts in to pending sim.

    Optional ``ARBY_FLASHBLOCKS_USE_LATEST=1`` falls the underlying tag
    back to ``latest`` when the RPC does not support ``pending``.  Pure
    feature flag — no network IO.
    """
    return is_enabled() and os.environ.get("ARBY_PENDING_SIM_ENABLE", "0") == "1"


def pending_eth_call(
    *,
    rpc_url: str,
    to: str,
    data: str,
    http_post: Callable[[str, dict, float], dict],
    timeout_s: float = 5.0,
) -> Optional[str]:
    """E1.77 step 9: minimal ``eth_call`` against the pending block tag.

    Returns the hex result string on success, ``None`` otherwise.
    Honours the same throttle bucket / breaker as :func:`fetch_pending_pool_logs`.
    Caller must inject ``http_post`` (same contract as that function) so this
    helper stays unit-testable without a real RPC.

    The function is intentionally narrow: a single contract call against a
    pending state.  Higher-level flow (e.g. building the call data for a
    Uniswap quote) is the caller's responsibility.
    """
    if not pending_sim_enabled():
        return None
    if not provider_throttle.acquire("logs", blocking=False):
        _STATS["calls_blocked_by_breaker"] += 1
        return None
    _block_tag = (
        "latest"
        if os.environ.get("ARBY_FLASHBLOCKS_USE_LATEST", "0") == "1"
        else PENDING_BLOCK_TAG
    )
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, _block_tag],
    }
    _STATS["calls_attempted"] += 1
    try:
        resp = http_post(rpc_url, payload, timeout_s)
    except TimeoutError as exc:
        _STATS["calls_408"] += 1
        _STATS["last_error"] = f"timeout: {str(exc)[:120]}"
        provider_throttle.record_response("logs", status_code=408)
        return None
    except Exception as exc:
        _STATS["calls_other_error"] += 1
        _STATS["last_error"] = str(exc)[:200]
        provider_throttle.record_response("logs", ok=False)
        return None
    if not isinstance(resp, dict):
        _STATS["calls_other_error"] += 1
        provider_throttle.record_response("logs", ok=False)
        return None
    if "error" in resp and resp["error"]:
        _STATS["calls_other_error"] += 1
        _STATS["last_error"] = str(resp["error"])[:200]
        provider_throttle.record_response("logs", ok=False)
        return None
    result = resp.get("result")
    if not isinstance(result, str):
        _STATS["calls_other_error"] += 1
        provider_throttle.record_response("logs", ok=False)
        return None
    _STATS["calls_ok"] += 1
    provider_throttle.record_response("logs", ok=True)
    return result


__all__ = [
    "PENDING_BLOCK_TAG",
    "fetch_pending_pool_logs",
    "is_enabled",
    "pending_eth_call",
    "pending_sim_enabled",
    "reset_stats",
    "stats",
]
