"""Batch ERC-20 decimals/symbol reads via Multicall3 for M8.3 hot-path metadata."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


def prefetch_erc20_metadata(
    w3: Any,
    addresses: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Return ``{addr: {decimals, symbol}}`` for addresses needing on-chain probes."""
    if w3 is None or not addresses:
        return {}

    uniq = sorted({str(a).lower() for a in addresses if a})
    if not uniq:
        return {}

    try:
        endpoint = getattr(getattr(w3, "provider", None), "endpoint_uri", None)
        if not endpoint:
            return {}
        from core.multicall import MulticallBatcher

        batcher = MulticallBatcher(str(endpoint), block_num=None)
        dec_map = batcher.batch_decimals(uniq)
        sym_map = batcher.batch_symbol(uniq)
    except Exception as exc:
        log.debug("erc20 multicall prefetch skipped: %s", exc)
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for addr in uniq:
        dec = dec_map.get(addr)
        if dec is None:
            continue
        row: Dict[str, Any] = {"decimals": int(dec)}
        sym = sym_map.get(addr)
        if sym:
            row["symbol"] = sym
        out[addr] = row
    return out
