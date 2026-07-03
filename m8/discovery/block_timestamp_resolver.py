"""Shared block timestamp resolver for M8 discovery enrichment.

Converts block numbers to ISO-8601 timestamps via eth_getBlockByNumber RPC calls.
Used by factory scan enrichment to populate created_at proxy for hints that
lack pool creation time (factory.getPool() doesn't return timestamps).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Set

__all__ = ["resolve_block_timestamps"]


def resolve_block_timestamps(
    block_numbers: Set[int],
    *,
    chain: str = "base",
) -> Dict[int, str]:
    """Batch-resolve block numbers to ISO-8601 timestamps via eth_getBlockByNumber.

    Returns a mapping {block_number: "YYYY-MM-DDTHH:MM:SSZ"}.
    Failed lookups are silently dropped (caller treats missing as stale).
    """
    if not block_numbers:
        return {}
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return {}

    from core.env import load_root_dotenv
    from core.rpc_urls import get_rpc_url

    load_root_dotenv()
    rpc_url = get_rpc_url(chain)
    if not rpc_url:
        return {}

    result: Dict[int, str] = {}
    for block_num in block_numbers:
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_getBlockByNumber",
                "params": [hex(block_num), False],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            blk = body.get("result") or {}
            ts_hex = blk.get("timestamp")
            if ts_hex:
                ts = int(ts_hex, 16)
                result[block_num] = datetime.fromtimestamp(
                    ts, tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
    return result
