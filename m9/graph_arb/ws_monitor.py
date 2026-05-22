"""Lightweight WebSocket freshness monitor for M9 quote gate.

Subscribes to ``eth_subscribe("newHeads")`` via WS and tracks the age of
the latest block.  Used to reject sweeps where the node is stale (i.e. the
block we're quoting against is too old to be actionable).

Default OFF — set ``BASE_WSS`` (or chain-specific WS URL) in .env to enable.
If the WS connection fails, the monitor fails gracefully and
``ws_freshness_snapshot()`` returns ``{"connected": false, "error": "<msg>"}``.

Public API:
    start_ws_monitor(ws_url: str) -> WsMonitor
    WsMonitor.snapshot() -> dict
    WsMonitor.stop()
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_STALE_BLOCK_AGE_S = 60.0  # blocks older than this trigger freshness warning


class WsMonitor:
    """Background thread that tracks newHead freshness via WebSocket."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connected = False
        self._latest_block: Optional[int] = None
        self._latest_ts: Optional[float] = None  # monotonic time of last newHead
        self._block_number_hex: Optional[str] = None
        self._error: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, ws_url: str) -> None:
        """Start background WS thread.  Returns immediately."""
        self._thread = threading.Thread(
            target=self._run,
            args=(ws_url,),
            daemon=True,
            name="m9-ws-monitor",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            connected = self._connected
            latest_block = self._latest_block
            block_number_hex = self._block_number_hex
            last_seen = self._latest_ts
            error = self._error

        block_age_s: Optional[float] = None
        if last_seen is not None:
            block_age_s = round(time.monotonic() - last_seen, 1)

        stale = (block_age_s is not None and block_age_s > _STALE_BLOCK_AGE_S)
        return {
            "connected": connected,
            "latest_block": latest_block,
            "block_number_hex": block_number_hex,
            "block_age_s": block_age_s,
            "stale": stale,
            "error": error,
        }

    def _run(self, ws_url: str) -> None:
        try:
            import websockets
            import asyncio

            asyncio.run(self._async_run(ws_url))
        except ImportError:
            # websockets not installed — use web3 WS provider as fallback
            self._run_web3_ws(ws_url)
        except Exception as exc:
            with self._lock:
                self._error = str(exc)[:200]
            log.debug("WsMonitor thread error: %s", exc)

    async def _async_run(self, ws_url: str) -> None:
        import websockets
        import json as _json

        sub_msg = _json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newHeads"],
        })
        try:
            async with websockets.connect(ws_url, ping_interval=20) as ws:
                await ws.send(sub_msg)
                with self._lock:
                    self._connected = True
                    self._error = None
                while not self._stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        msg = _json.loads(raw)
                        if "params" in msg:
                            header = msg["params"].get("result", {})
                            block_hex = header.get("number")
                            if block_hex:
                                block_num = int(block_hex, 16)
                                with self._lock:
                                    self._latest_block = block_num
                                    self._block_number_hex = block_hex
                                    self._latest_ts = time.monotonic()
                    except asyncio.TimeoutError:
                        continue
        except Exception as exc:
            with self._lock:
                self._connected = False
                self._error = str(exc)[:200]

    def _run_web3_ws(self, ws_url: str) -> None:
        """Fallback: use web3 WebsocketProvider to poll block number."""
        try:
            from web3 import Web3

            w3 = Web3(Web3.WebsocketProvider(ws_url))
            if not w3.is_connected():
                with self._lock:
                    self._error = "web3 WS not connected"
                return
            with self._lock:
                self._connected = True
                self._error = None
            while not self._stop_event.is_set():
                try:
                    block_num = w3.eth.block_number
                    with self._lock:
                        self._latest_block = block_num
                        self._latest_ts = time.monotonic()
                except Exception:
                    pass
                time.sleep(2.0)
        except Exception as exc:
            with self._lock:
                self._connected = False
                self._error = str(exc)[:200]


# Module-level factory
def start_ws_monitor(ws_url: str) -> WsMonitor:
    """Start and return a WsMonitor for the given WS URL."""
    monitor = WsMonitor()
    monitor.start(ws_url)
    return monitor
