"""Unit tests for m8.runtime.ws_listener (Phase 1.3 skeleton).

These tests cover the message-handling logic and configuration paths
without opening a real WebSocket connection. The actual `.run()` loop
is exercised only by mock-driven tests.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from m8.runtime.ws_listener import (
    WSPoolEventListener,
    WSListenerStats,
)
from discovery.new_pool_listener import FactoryConfig


def _cfg(dex: str = "uniswap_v3") -> FactoryConfig:
    return FactoryConfig(
        chain="base",
        dex=dex,
        adapter_type="uniswap_v3",
        factory="0x33128a8fc17869897dce68ed026d694621f6fdfd",
        event_name="PoolCreated",
        event_signature="PoolCreated(address,address,uint24,int24,address)",
        topic0="0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
        topic0_verified=True,
        log_layout="v3_pool_created",
        verification_from_block=None,
        verification_to_block=None,
    )


# ---------------------------------------------------------------------------
# Constructor + validation
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_empty_ws_url_raises(self):
        with pytest.raises(ValueError):
            WSPoolEventListener("", [_cfg()], on_event=lambda c, l: None)

    def test_empty_configs_raises(self):
        with pytest.raises(ValueError):
            WSPoolEventListener("wss://x/", [], on_event=lambda c, l: None)

    def test_defaults(self):
        lst = WSPoolEventListener(
            "wss://x/", [_cfg()], on_event=lambda c, l: None,
        )
        assert lst.heartbeat_interval_s == 30.0
        assert lst.auto_reconnect is True
        assert lst.recv_timeout_s == 30.0
        assert not lst.is_stopped()

    def test_stop_flag(self):
        lst = WSPoolEventListener(
            "wss://x/", [_cfg()], on_event=lambda c, l: None,
        )
        lst.stop()
        assert lst.is_stopped()


# ---------------------------------------------------------------------------
# Subscribe payload
# ---------------------------------------------------------------------------

class TestBuildSubscribePayload:
    def test_topic0_present_when_set(self):
        c = _cfg()
        lst = WSPoolEventListener("wss://x/", [c], on_event=lambda c, l: None)
        p = lst._build_subscribe_payload(c, request_id=7)
        assert p["jsonrpc"] == "2.0"
        assert p["method"] == "eth_subscribe"
        assert p["id"] == 7
        assert p["params"][0] == "logs"
        assert p["params"][1]["address"] == c.factory
        assert p["params"][1]["topics"] == [c.topic0]

    def test_topic0_omitted_when_null(self):
        c = _cfg()
        # Use object.__setattr__ to bypass frozen dataclass if any
        try:
            object.__setattr__(c, "topic0", None)
        except Exception:
            pytest.skip("FactoryConfig frozen")
        lst = WSPoolEventListener("wss://x/", [c], on_event=lambda c, l: None)
        p = lst._build_subscribe_payload(c, request_id=1)
        assert "topics" not in p["params"][1]


# ---------------------------------------------------------------------------
# Message handling
# ---------------------------------------------------------------------------

class TestHandleMessage:
    def setup_method(self):
        self.events: List[Dict[str, Any]] = []
        self.cfg = _cfg()
        self.lst = WSPoolEventListener(
            "wss://x/", [self.cfg],
            on_event=lambda c, l: self.events.append({"dex": c.dex, "log": l}),
        )

    def test_invalid_json_counted_as_parse_error(self):
        self.lst._handle_message("not-json{{{", pending={})
        assert self.lst.stats.parse_errors == 1
        assert self.lst.stats.messages_received == 1
        assert self.events == []

    def test_ack_registers_subscription(self):
        pending = {1: self.cfg}
        ack = json.dumps({"id": 1, "result": "0xsub_abc", "jsonrpc": "2.0"})
        self.lst._handle_message(ack, pending)
        assert self.lst.stats.subscriptions_succeeded == 1
        assert self.lst.stats.sub_id_to_dex["0xsub_abc"] == "uniswap_v3"
        assert 1 not in pending  # consumed

    def test_notification_delivered_to_callback(self):
        # First register sub_id -> dex.
        ack = json.dumps({"id": 1, "result": "0xsub_abc", "jsonrpc": "2.0"})
        self.lst._handle_message(ack, pending={1: self.cfg})
        # Now feed a notification.
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_subscription",
            "params": {
                "subscription": "0xsub_abc",
                "result": {
                    "address": self.cfg.factory,
                    "topics": [self.cfg.topic0, "0x" + "00" * 32, "0x" + "11" * 32, "0x" + "00" * 32],
                    "data": "0x" + "00" * 64,
                    "blockNumber": "0x1",
                    "transactionHash": "0x" + "ab" * 32,
                    "logIndex": "0x0",
                },
            },
        })
        self.lst._handle_message(notif, pending={})
        assert self.lst.stats.log_events_emitted == 1
        assert self.lst.stats.last_event_seen_ts is not None
        assert len(self.events) == 1
        assert self.events[0]["dex"] == "uniswap_v3"

    def test_unknown_subscription_id_ignored(self):
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_subscription",
            "params": {"subscription": "0xunknown", "result": {"x": 1}},
        })
        self.lst._handle_message(notif, pending={})
        # Counted as message but no event emitted.
        assert self.lst.stats.messages_received == 1
        assert self.lst.stats.log_events_emitted == 0
        assert self.events == []

    def test_callback_exception_does_not_propagate(self):
        bad = WSPoolEventListener(
            "wss://x/", [self.cfg],
            on_event=lambda c, l: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        ack = json.dumps({"id": 1, "result": "0xs", "jsonrpc": "2.0"})
        bad._handle_message(ack, pending={1: self.cfg})
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_subscription",
            "params": {"subscription": "0xs", "result": {"any": "log"}},
        })
        # Must not raise.
        bad._handle_message(notif, pending={})
        assert bad.stats.log_events_emitted == 1


# ---------------------------------------------------------------------------
# Stats dataclass defaults
# ---------------------------------------------------------------------------

class TestStats:
    def test_default_fields(self):
        s = WSListenerStats()
        assert s.subscriptions_attempted == 0
        assert s.subscriptions_succeeded == 0
        assert s.messages_received == 0
        assert s.log_events_emitted == 0
        assert s.parse_errors == 0
        assert s.disconnects == 0
        assert s.reconnect_attempts == 0
        assert s.last_event_seen_ts is None
        assert s.last_disconnect_ts is None
        assert s.sub_id_to_dex == {}
