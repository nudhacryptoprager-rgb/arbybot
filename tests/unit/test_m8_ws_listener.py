"""Unit tests for m8.runtime.ws_listener (Phase 1.3 skeleton).

These tests cover the message-handling logic and configuration paths
without opening a real WebSocket connection. The actual `.run()` loop
is exercised only by mock-driven tests.
"""
from __future__ import annotations

import json
import threading
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


# ---------------------------------------------------------------------------
# Integration: WS callback feeds the full funnel pipeline
# ---------------------------------------------------------------------------

def _make_v3_raw_log(cfg: FactoryConfig, tx_hash_suffix: str = "ab") -> Dict[str, Any]:
    """Minimal valid PoolCreated (v3) raw log dict for *cfg*."""
    token0 = "0x" + "00" * 12 + "11" * 20
    token1 = "0x" + "00" * 12 + "22" * 20
    fee = "0x" + "00" * 29 + "01f4"        # 500
    pool_word = "00" * 12 + "33" * 20       # pool address as 32-byte word
    tick_word = "00" * 32                   # tickSpacing = 0
    return {
        "address": cfg.factory,
        "topics": [cfg.topic0, token0, token1, fee],
        "data": "0x" + tick_word + pool_word,
        "blockNumber": "0x1",
        "transactionHash": "0x" + tx_hash_suffix * 32,
        "logIndex": "0x0",
    }


class TestWSFunnelIntegration:
    """Integration tests for the WS on_event callback → funnel pipeline.

    These tests call ``_make_ws_on_event_callback`` directly with a fake raw
    log and assert the funnel counters are correct — without any real socket.
    """

    def setup_method(self):
        from monitoring.sniper_funnel import FunnelTracker
        self.funnel = FunnelTracker()
        self.seen_ids: set = set()
        self.recent_events: list = []
        self.events_lock = threading.Lock()
        self.cfg = _cfg()  # uniswap_v3

    def _make_callback(self):
        from m8.runtime.smoke_run import _make_ws_on_event_callback
        return _make_ws_on_event_callback(
            self.funnel, self.seen_ids, self.recent_events, self.events_lock,
        )

    def test_valid_log_increments_full_funnel(self):
        """One valid WS log → raw_fetched=1, parse_ok=1, dedup_new=1, candidates_queued=1."""
        cb = self._make_callback()
        cb(self.cfg, _make_v3_raw_log(self.cfg))
        snap = self.funnel.snapshot()
        assert snap["raw_fetched"] == 1
        assert snap["parse_ok"] == 1
        assert snap["parse_failed"] == 0
        assert snap["dedup_new"] == 1
        assert snap["dedup_dropped"] == 0
        assert snap["candidates_queued"] == 1
        assert snap["snipe_candidates_total"] == 1

    def test_duplicate_log_is_deduped(self):
        """Sending the same log twice → second call increments dedup_dropped."""
        cb = self._make_callback()
        raw = _make_v3_raw_log(self.cfg)
        cb(self.cfg, raw)
        cb(self.cfg, raw)
        snap = self.funnel.snapshot()
        assert snap["raw_fetched"] == 2
        assert snap["parse_ok"] == 2
        assert snap["dedup_new"] == 1
        assert snap["dedup_dropped"] == 1
        assert snap["candidates_queued"] == 1

    def test_valid_log_appears_in_recent_events(self):
        """A passed event is appended to recent_events."""
        cb = self._make_callback()
        cb(self.cfg, _make_v3_raw_log(self.cfg))
        assert len(self.recent_events) == 1
        assert self.recent_events[0].dex == "uniswap_v3"

    def test_unparseable_log_increments_parse_failed(self):
        """A log with too few topics gives parse_failed=1, no candidate."""
        cb = self._make_callback()
        bad_log = {
            "address": self.cfg.factory,
            "topics": [self.cfg.topic0],   # only 1 topic, v3 needs 4
            "data": "0x",
            "blockNumber": "0x1",
            "transactionHash": "0x" + "cc" * 32,
            "logIndex": "0x0",
        }
        cb(self.cfg, bad_log)
        snap = self.funnel.snapshot()
        assert snap["raw_fetched"] == 1
        assert snap["parse_failed"] == 1
        assert snap["parse_ok"] == 0
        assert snap["candidates_queued"] == 0

    def test_funnel_listener_mode_set(self):
        """After set_listener_mode, snapshot() reflects 'ws+http_fallback'."""
        self.funnel.set_listener_mode("ws+http_fallback")
        snap = self.funnel.snapshot()
        assert snap["listener_mode"] == "ws+http_fallback"
        assert snap["ws_connected"] is False   # not set yet
        assert snap["ws_events_seen"] == 0

    def test_update_ws_stats_reflected_in_snapshot(self):
        """update_ws_stats() values appear in snapshot()."""
        self.funnel.update_ws_stats(
            connected=True,
            subscriptions=4,
            events_seen=7,
            reconnects=1,
            last_event_seen_ts=1234567890.0,
        )
        snap = self.funnel.snapshot()
        assert snap["ws_connected"] is True
        assert snap["ws_subscriptions"] == 4
        assert snap["ws_events_seen"] == 7
        assert snap["ws_reconnects"] == 1
        assert snap["ws_last_event_seen_ts"] == 1234567890.0

    def test_http_fallback_polls_counter(self):
        """inc_http_fallback_poll() increments counter in snapshot."""
        self.funnel.inc_http_fallback_poll()
        self.funnel.inc_http_fallback_poll()
        snap = self.funnel.snapshot()
        assert snap["http_fallback_polls"] == 2

    def test_update_ws_stats_per_dex_in_snapshot(self):
        """update_ws_stats(events_by_dex, callbacks_ok_by_dex) appears in snapshot."""
        self.funnel.update_ws_stats(
            connected=True,
            subscriptions=2,
            events_seen=3,
            reconnects=0,
            last_event_seen_ts=None,
            events_by_dex={"uniswap_v3": 2, "pancakeswap_v3": 1},
            callbacks_ok_by_dex={"uniswap_v3": 2, "pancakeswap_v3": 1},
        )
        snap = self.funnel.snapshot()
        assert snap["ws_events_by_dex"]["uniswap_v3"] == 2
        assert snap["ws_events_by_dex"]["pancakeswap_v3"] == 1
        assert snap["ws_callbacks_ok_by_dex"]["uniswap_v3"] == 2
        assert snap["ws_callbacks_ok_by_dex"]["pancakeswap_v3"] == 1

    def test_ws_stats_per_dex_empty_by_default(self):
        """snapshot() returns empty dicts for per-DEX WS stats if not set."""
        snap = self.funnel.snapshot()
        assert snap["ws_events_by_dex"] == {}
        assert snap["ws_callbacks_ok_by_dex"] == {}


# ---------------------------------------------------------------------------
# WSListenerStats per-DEX counters
# ---------------------------------------------------------------------------

class TestWSListenerStatsPerDex:
    """Tests for events_by_dex / callbacks_ok_by_dex tracking in WSListenerStats."""

    def test_events_by_dex_incremented_on_dispatch(self):
        """Simulated ACK + notification increments events_by_dex for the right DEX."""
        cfg_u = _cfg("uniswap_v3")
        cfg_p = _cfg("pancakeswap_v3")
        received: List[str] = []

        def on_event(cfg, raw_log):
            received.append(cfg.dex)

        lst = WSPoolEventListener("wss://x/", [cfg_u, cfg_p], on_event=on_event)
        # Simulate ACK for uniswap_v3 subscription
        ack_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "sub-u1"})
        lst._handle_message(ack_msg, {1: cfg_u})
        assert lst.stats.sub_id_to_dex["sub-u1"] == "uniswap_v3"

        # Simulate log notification for uniswap_v3
        notif = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_subscription",
            "params": {
                "subscription": "sub-u1",
                "result": _make_v3_raw_log(cfg_u),
            },
        })
        lst._handle_message(notif, {})
        assert lst.stats.events_by_dex.get("uniswap_v3") == 1
        assert lst.stats.callbacks_ok_by_dex.get("uniswap_v3") == 1
        assert len(received) == 1

    def test_events_by_dex_empty_on_new_instance(self):
        """Fresh WSListenerStats has empty per-DEX dicts."""
        stats = WSListenerStats()
        assert stats.events_by_dex == {}
        assert stats.callbacks_ok_by_dex == {}


# ---------------------------------------------------------------------------
# load_factory_config dex_filter
# ---------------------------------------------------------------------------

class TestLoadFactoryConfigDexFilter:
    """Tests for dex_filter parameter in load_factory_config."""

    def test_dex_filter_returns_only_matching(self):
        from discovery.new_pool_listener import load_factory_config
        configs = load_factory_config(chain_filter="base", dex_filter="uniswap_v3")
        assert all(c.dex == "uniswap_v3" for c in configs)
        assert len(configs) >= 1

    def test_dex_filter_unknown_returns_empty(self):
        from discovery.new_pool_listener import load_factory_config
        configs = load_factory_config(chain_filter="base", dex_filter="does_not_exist_xyz")
        assert configs == []

    def test_no_dex_filter_returns_all(self):
        from discovery.new_pool_listener import load_factory_config
        all_cfgs = load_factory_config(chain_filter="base")
        filtered = load_factory_config(chain_filter="base", dex_filter="uniswap_v3")
        assert len(all_cfgs) > len(filtered)

