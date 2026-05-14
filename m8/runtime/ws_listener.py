"""M8 Phase 1.3 -- WebSocket listener skeleton for new-pool factory events.

Goal
====
Provide a sync ``WSPoolEventListener`` that subscribes to ``eth_subscribe logs``
on a WS endpoint and yields raw log dicts shaped exactly like those returned
by ``eth_getLogs``. The HTTP polling loop in :mod:`m8.runtime.smoke_run`
stays as the canonical fallback. This module is intentionally minimal:

* It uses ``websockets.sync.client.connect`` (already a transitive dep of
  web3 v6) -- no new requirements.
* It subscribes to a separate filter per factory (one ``eth_subscribe`` call
  per ``FactoryConfig``), with ``topics[0]=cfg.topic0`` when verified.
* Per-message JSON parsing is shielded; malformed messages are logged and
  skipped, never crashing the loop.
* Reconnect uses bounded exponential backoff (1s -> 2s -> 4s -> 8s -> 16s).
* A ``heartbeat_interval_s`` watchdog calls ``last_event_seen_ts`` so the
  caller (smoke_run loop) can detect a silent socket.
* Caller-supplied ``on_event`` callback receives ``(cfg, raw_log)``.

Phase 1.3 integration
=====================
The HTTP polling loop in ``m8.runtime.smoke_run`` is the canonical primary
path through M8 Phase 1.2. ``--prefer-ws`` enables WS as a parallel feed;
on any WS error the HTTP poll keeps the run alive. No deduplication
problem because both feeds funnel into ``FunnelTracker`` via
``parse_raw_log()`` + ``event_id`` dedup.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from discovery.new_pool_listener import FactoryConfig

logger = logging.getLogger(__name__)

# Bounded backoff schedule.
_BACKOFF_S: tuple = (1.0, 2.0, 4.0, 8.0, 16.0)


@dataclass
class WSListenerStats:
    """Lightweight stats for observability + tests."""
    subscriptions_attempted: int = 0
    subscriptions_succeeded: int = 0
    messages_received: int = 0
    log_events_emitted: int = 0
    parse_errors: int = 0
    disconnects: int = 0
    reconnect_attempts: int = 0
    last_event_seen_ts: Optional[float] = None
    last_disconnect_ts: Optional[float] = None
    # Map subscription_id -> FactoryConfig.dex
    sub_id_to_dex: Dict[str, str] = field(default_factory=dict)


class WSPoolEventListener:
    """Sync WebSocket listener for factory PoolCreated/PairCreated events.

    The listener runs a single read loop (``run()``) that should be invoked
    on a worker thread by the caller. Use ``stop()`` to request shutdown.

    Notes
    -----
    * No async/asyncio. Sync ``websockets.sync.client`` chosen so callers
      can integrate via a simple thread.
    * Reconnect is opt-in via ``auto_reconnect=True`` (default).
    """

    def __init__(
        self,
        ws_url: str,
        configs: List[FactoryConfig],
        on_event: Callable[[FactoryConfig, Dict[str, Any]], None],
        *,
        heartbeat_interval_s: float = 30.0,
        auto_reconnect: bool = True,
        recv_timeout_s: float = 30.0,
    ) -> None:
        if not ws_url:
            raise ValueError("ws_url must be a non-empty WebSocket URL")
        if not configs:
            raise ValueError("at least one FactoryConfig required")
        self.ws_url = ws_url
        self.configs = list(configs)
        self.on_event = on_event
        self.heartbeat_interval_s = float(heartbeat_interval_s)
        self.auto_reconnect = bool(auto_reconnect)
        self.recv_timeout_s = float(recv_timeout_s)
        self.stats = WSListenerStats()
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -- Public control -------------------------------------------------

    def stop(self) -> None:
        """Request graceful shutdown of the read loop."""
        self._stop.set()

    def is_stopped(self) -> bool:
        return self._stop.is_set()

    # -- Internals ------------------------------------------------------

    def _build_subscribe_payload(
        self, cfg: FactoryConfig, request_id: int,
    ) -> Dict[str, Any]:
        """Build a single ``eth_subscribe logs`` payload for *cfg*."""
        params: Dict[str, Any] = {"address": cfg.factory}
        if cfg.topic0:
            params["topics"] = [cfg.topic0]
        return {
            "jsonrpc": "2.0",
            "id": int(request_id),
            "method": "eth_subscribe",
            "params": ["logs", params],
        }

    def _handle_message(self, msg_text: str, pending: Dict[int, FactoryConfig]) -> None:
        """Process one inbound WS frame.

        Three frame shapes are recognised:

        1. Subscription ACK -- ``{"id":N,"result":"0xsubid"}``
        2. Subscription notification -- ``{"method":"eth_subscription",
           "params":{"subscription":"0xsubid","result":{...log...}}}``
        3. Anything else -- ignored (counted as parse_error if json invalid).
        """
        self.stats.messages_received += 1
        try:
            obj = json.loads(msg_text)
        except Exception:
            self.stats.parse_errors += 1
            return

        # ACK shape
        if isinstance(obj, dict) and "result" in obj and "id" in obj:
            sub_id = obj.get("result")
            req_id = obj.get("id")
            if isinstance(sub_id, str) and isinstance(req_id, int):
                cfg = pending.pop(req_id, None)
                if cfg is not None:
                    self.stats.sub_id_to_dex[sub_id] = cfg.dex
                    self.stats.subscriptions_succeeded += 1
            return

        # Notification shape
        if isinstance(obj, dict) and obj.get("method") == "eth_subscription":
            params = obj.get("params") or {}
            sub_id = params.get("subscription")
            raw_log = params.get("result")
            if not isinstance(raw_log, dict):
                return
            dex = self.stats.sub_id_to_dex.get(sub_id)
            if not dex:
                return
            cfg = next((c for c in self.configs if c.dex == dex), None)
            if cfg is None:
                return
            self.stats.log_events_emitted += 1
            self.stats.last_event_seen_ts = time.time()
            try:
                self.on_event(cfg, raw_log)
            except Exception as exc:  # callback failure must not kill loop
                logger.warning("ws_on_event_callback_failed: %s", str(exc)[:120])

    def run(self) -> None:
        """Main read loop. Blocking. Call from a worker thread.

        Exits when ``stop()`` is called or ``auto_reconnect=False`` and
        the socket dies once.
        """
        try:
            from websockets.sync.client import connect as ws_connect
        except Exception as exc:  # pragma: no cover - import guard
            logger.error("websockets.sync.client not available: %s", exc)
            return

        backoff_idx = 0
        while not self._stop.is_set():
            try:
                with ws_connect(self.ws_url, open_timeout=15) as conn:
                    backoff_idx = 0
                    pending: Dict[int, FactoryConfig] = {}
                    # Subscribe per factory.
                    for i, cfg in enumerate(self.configs, start=1):
                        payload = self._build_subscribe_payload(cfg, request_id=i)
                        conn.send(json.dumps(payload))
                        pending[i] = cfg
                        self.stats.subscriptions_attempted += 1

                    # Read loop.
                    while not self._stop.is_set():
                        try:
                            msg = conn.recv(timeout=self.recv_timeout_s)
                        except TimeoutError:
                            # No frames within timeout -- not necessarily fatal.
                            continue
                        if msg is None:
                            break
                        if isinstance(msg, (bytes, bytearray)):
                            try:
                                msg = msg.decode("utf-8", errors="replace")
                            except Exception:
                                self.stats.parse_errors += 1
                                continue
                        self._handle_message(msg, pending)
            except Exception as exc:
                self.stats.disconnects += 1
                self.stats.last_disconnect_ts = time.time()
                logger.warning(
                    "ws_disconnect (will %sretry): %s",
                    "" if self.auto_reconnect else "NOT ",
                    str(exc)[:120],
                )
                if not self.auto_reconnect or self._stop.is_set():
                    break
                self.stats.reconnect_attempts += 1
                sleep_s = _BACKOFF_S[min(backoff_idx, len(_BACKOFF_S) - 1)]
                backoff_idx += 1
                # Honor stop during backoff.
                end = time.monotonic() + sleep_s
                while time.monotonic() < end and not self._stop.is_set():
                    time.sleep(0.1)
