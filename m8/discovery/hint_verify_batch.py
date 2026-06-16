"""Batch / async / WS-pinned helpers for M8.2 hint on-chain verify."""
from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from m8.discovery.pool_hints import PoolHint, verify_hint_onchain

_log = logging.getLogger(__name__)


def pin_block_from_ws(chain: str = "base", *, timeout_s: float = 8.0) -> Optional[int]:
    """Subscribe to newHeads once; return block number for verify pinning."""
    try:
        from websocket import create_connection  # type: ignore
    except ImportError:
        _log.warning("websocket-client not installed; WS head pin skipped")
        return None
    try:
        from core.rpc_urls import resolve_rpc_ws, _CHAIN_KEY_TO_ID

        chain_id = _CHAIN_KEY_TO_ID.get(chain.lower())
        wss, _prov, _diag = resolve_rpc_ws(chain_id=chain_id, network=chain)
        if not wss:
            return None
        ws = create_connection(wss, timeout=timeout_s)
        ws.send(
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]}
            )
        )
        ws.recv()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            raw = ws.recv()
            msg = json.loads(raw)
            params = (msg.get("params") or {}).get("result") or {}
            num = params.get("number")
            if num:
                ws.close()
                return int(num, 16) if isinstance(num, str) else int(num)
        ws.close()
    except Exception as exc:
        _log.warning("WS head pin failed: %s", exc)
    return None


def _bytecode_ok(rpc_url: str, address: str) -> bool:
    from m8.discovery.hint_verifier import _eth_get_code

    return _eth_get_code(rpc_url, address)


def batch_bytecode_multicall(
    hints: List[PoolHint],
    *,
    rpc_url: str,
    block_num: Optional[int] = None,
) -> Dict[str, bool]:
    """Parallel bytecode probe; uses thread pool (RPC-bound, not aggregate3 getCode)."""
    addrs = []
    for h in hints:
        addr = (h.pool_id or h.pool_address or "").lower()
        if addr.startswith("0x") and len(addr) in (42, 66):
            addrs.append(addr)
    if not addrs:
        return {}
    workers = min(8, max(2, int(os.environ.get("ARBY_HINT_VERIFY_ASYNC_WORKERS", "4"))))
    out: Dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_bytecode_ok, rpc_url, a): a for a in addrs}
        for fut in as_completed(futs):
            addr = futs[fut]
            try:
                out[addr] = bool(fut.result())
            except Exception:
                out[addr] = False
    if block_num is not None:
        _log.debug("bytecode batch pinned block=%s addrs=%d", block_num, len(addrs))
    return out


def verify_hints_async(
    hints: List[PoolHint],
    *,
    chain: str,
    verify_mode: str,
    metrics: Optional[Dict[str, Any]] = None,
    workers: int = 4,
    use_multicall: bool = False,
    rpc_url: Optional[str] = None,
    block_num: Optional[int] = None,
) -> List[PoolHint]:
    """Verify hints concurrently; optional bytecode pre-pass when use_multicall."""
    if not hints:
        return []
    if rpc_url is None:
        from m8.discovery.hint_verifier import _rpc_url

        rpc_url = _rpc_url(chain)
    bytecode_map: Dict[str, bool] = {}
    if use_multicall and rpc_url and verify_mode != "none":
        bytecode_map = batch_bytecode_multicall(
            hints, rpc_url=rpc_url, block_num=block_num
        )

    def _one(h: PoolHint) -> PoolHint:
        addr = (h.pool_id or h.pool_address or "").lower()
        if bytecode_map and addr and not bytecode_map.get(addr, True):
            h.hint_status = "HINT_ONLY"
            return h
        return verify_hint_onchain(
            h,
            chain=chain,
            verify_mode=verify_mode,
            metrics=metrics,
        )

    w = max(1, min(workers, len(hints)))
    if w == 1:
        return [_one(h) for h in hints]
    out: List[PoolHint] = [hints[0]] * len(hints)  # placeholder
    with ThreadPoolExecutor(max_workers=w) as pool:
        futs = {pool.submit(_one, h): i for i, h in enumerate(hints)}
        for fut in as_completed(futs):
            idx = futs[fut]
            out[idx] = fut.result()
    return out
