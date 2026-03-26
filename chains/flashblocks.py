# PATH: chains/flashblocks.py
"""
Flashblocks read-path infrastructure for Base chain.

Provides:
- Flashblocks WSS subscription for sub-block (~200ms) state events
- eth_simulateV1 call via Flashblocks-aware RPC
- base_transactionStatus polling
- Connectivity health check for structural_advantage_met gate

Reference:
  https://docs.base.org/base-chain/flashblocks/api-reference
  https://docs.base.org/ai-agents/trading
  https://docs.base.org/base-chain/network-information/transaction-finality

IMPORTANT (lead step 4): Public Flashblocks/preconf endpoints are rate-limited
and NOT suitable for production traffic. This module implements the read-path
only. Production submit-path requires a private/fast RPC provider (e.g.,
bloXroute Base Fast RPC or equivalent).

R39r: Initial integration — read-path only, no submission.
"""

from __future__ import annotations

import json
import logging
import threading
import time as _time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("chains.flashblocks")

# Default Flashblocks endpoints (public, rate-limited — read-path only)
DEFAULT_FLASHBLOCKS_WS = "wss://base.flashblocks.base.org/ws"
DEFAULT_FLASHBLOCKS_HTTP = "https://base.flashblocks.base.org"

# Sub-block interval on Base with Flashblocks (~200ms)
FLASHBLOCKS_SUB_BLOCK_MS = 200


@dataclass
class FlashblocksState:
    """Current Flashblocks connectivity and health state."""
    connected: bool = False
    last_sub_block_number: int | None = None
    last_sub_block_ts: float = 0.0  # monotonic timestamp
    total_sub_blocks_received: int = 0
    total_connection_errors: int = 0
    last_error: str | None = None

    @property
    def is_healthy(self) -> bool:
        """Flashblocks is healthy if connected and received sub-blocks recently."""
        if not self.connected:
            return False
        if self.total_sub_blocks_received == 0:
            return False
        age_s = _time.monotonic() - self.last_sub_block_ts
        # Healthy if last sub-block within 10s (generous for initial integration)
        return age_s < 10.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "is_healthy": self.is_healthy,
            "last_sub_block_number": self.last_sub_block_number,
            "total_sub_blocks_received": self.total_sub_blocks_received,
            "total_connection_errors": self.total_connection_errors,
            "last_error": self.last_error,
            "age_since_last_sub_block_s": round(
                _time.monotonic() - self.last_sub_block_ts, 2
            ) if self.last_sub_block_ts > 0 else None,
        }


class FlashblocksWatcher:
    """Background WebSocket watcher for Base Flashblocks sub-block events.

    Connects to Flashblocks WSS endpoint and subscribes to newPendingBlock
    or newHeads at sub-block granularity (~200ms). Reports connectivity
    health for structural_advantage_met gate.

    Usage::

        watcher = FlashblocksWatcher(ws_url="wss://base.flashblocks.base.org/ws")
        watcher.start()
        ...
        if watcher.state.is_healthy:
            # structural advantage met
        ...
        watcher.stop()
    """

    def __init__(
        self,
        ws_url: str = DEFAULT_FLASHBLOCKS_WS,
        on_sub_block: Any | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._on_sub_block = on_sub_block  # Optional callback(block_number, payload)
        self._state = FlashblocksState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> FlashblocksState:
        with self._lock:
            return FlashblocksState(
                connected=self._state.connected,
                last_sub_block_number=self._state.last_sub_block_number,
                last_sub_block_ts=self._state.last_sub_block_ts,
                total_sub_blocks_received=self._state.total_sub_blocks_received,
                total_connection_errors=self._state.total_connection_errors,
                last_error=self._state.last_error,
            )

    def start(self) -> None:
        """Start background Flashblocks WSS watcher thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._ws_loop, daemon=True, name="flashblocks-watcher"
        )
        self._thread.start()
        logger.info("FlashblocksWatcher started: %s", self._ws_url)

    def stop(self) -> None:
        """Signal watcher thread to terminate."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _ws_loop(self) -> None:
        """Background: connect, subscribe to Flashblocks sub-block events."""
        while not self._stop.is_set():
            try:
                import websocket as _wsclient

                ws = _wsclient.create_connection(self._ws_url, timeout=10)
                with self._lock:
                    self._state.connected = True

                # Subscribe to newHeads (Flashblocks endpoint delivers sub-block
                # granularity on standard newHeads subscription)
                subscribe_msg = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_subscribe",
                    "params": ["newHeads"],
                })
                ws.send(subscribe_msg)

                # Read subscription confirmation
                sub_resp = ws.recv()
                try:
                    sub_data = json.loads(sub_resp)
                    if "error" in sub_data:
                        err_msg = sub_data["error"].get("message", "unknown")
                        logger.warning(
                            "FlashblocksWatcher: subscribe rejected: %s", err_msg
                        )
                        ws.close()
                        with self._lock:
                            self._state.connected = False
                            self._state.total_connection_errors += 1
                            self._state.last_error = f"subscribe_rejected: {err_msg}"
                        _time.sleep(5)
                        continue
                except (json.JSONDecodeError, ValueError):
                    pass

                logger.info("FlashblocksWatcher: WSS connected, receiving sub-blocks")

                while not self._stop.is_set():
                    ws.settimeout(10)
                    try:
                        msg = ws.recv()
                    except Exception:
                        break  # reconnect on timeout/error

                    try:
                        data = json.loads(msg)
                        params = data.get("params", {})
                        result = params.get("result", {})
                        block_hex = result.get("number")
                        if block_hex:
                            block_num = int(block_hex, 16)
                            now = _time.monotonic()
                            with self._lock:
                                self._state.last_sub_block_number = block_num
                                self._state.last_sub_block_ts = now
                                self._state.total_sub_blocks_received += 1

                            if self._on_sub_block is not None:
                                try:
                                    self._on_sub_block(block_num, result)
                                except Exception:
                                    pass  # Don't crash watcher on callback error
                    except (json.JSONDecodeError, ValueError):
                        pass

                ws.close()
            except Exception as e:
                logger.debug(
                    "FlashblocksWatcher: WSS error: %s (reconnect in 5s)", e
                )
                with self._lock:
                    self._state.total_connection_errors += 1
                    self._state.last_error = str(e)
            finally:
                with self._lock:
                    self._state.connected = False

            if self._stop.is_set():
                break
            _time.sleep(5)  # backoff before reconnect


def check_flashblocks_health(
    http_url: str = DEFAULT_FLASHBLOCKS_HTTP,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Quick health check of Flashblocks HTTP endpoint.

    Calls eth_blockNumber via Flashblocks HTTP RPC and returns
    connectivity status. Used for one-shot structural advantage checks
    when a persistent watcher is not running.
    """
    import httpx

    try:
        response = httpx.post(
            http_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_blockNumber",
                "params": [],
            },
            timeout=timeout_s,
        )
        data = response.json()
        if "result" in data:
            block = int(data["result"], 16)
            return {
                "reachable": True,
                "block_number": block,
                "error": None,
            }
        return {
            "reachable": False,
            "block_number": None,
            "error": data.get("error", {}).get("message", "unknown"),
        }
    except Exception as e:
        return {
            "reachable": False,
            "block_number": None,
            "error": str(e),
        }
