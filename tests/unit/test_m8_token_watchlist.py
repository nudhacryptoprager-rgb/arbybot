"""Unit tests for Phase 1.5 token watch-list and factory token scan."""
from __future__ import annotations

from unittest.mock import MagicMock

from discovery.new_pool_listener import FactoryConfig, LAYOUT_V3_POOL_CREATED
from m8.discovery.anchor_registry import build_anchor_maps, is_anchor_address
from m8.discovery.factory_token_scan import (
    address_to_topic,
    find_recent_pools_containing_token,
)
from m8.discovery.token_watchlist import (
    SCAN_BACKOFF_STAGES_S,
    _record_second_pool,
    metrics_summary,
    scan_due,
    upsert_watch_entry_from_event,
)

_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_WETH = "0x4200000000000000000000000000000000000006"
_TOKEN = "0xtttt000000000000000000000000000000000001"


def _strategy_config() -> dict:
    return {
        "chain": "base",
        "tokens": {
            "USDC": {"address": _USDC},
            "WETH": {"address": _WETH},
        },
        "dexes": {
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
            "aerodrome": {"adapter_type": "ve33", "enabled": True},
        },
    }


class TestAnchorRegistry:
    def test_build_anchor_maps_from_strategy_config(self):
        addr_to_sym, syms = build_anchor_maps(_strategy_config())
        assert is_anchor_address(_USDC, addr_to_sym)
        assert is_anchor_address(_WETH, addr_to_sym)
        assert "USDC" in syms
        assert "WETH" in syms


class TestFactoryTokenScan:
    def test_address_to_topic_pads_20_bytes(self):
        addr = "0x" + "a" * 40
        topic = address_to_topic(addr)
        assert topic.startswith("0x")
        assert len(topic) == 66
        assert topic.endswith("a" * 40)

    def test_find_recent_pools_uses_injected_get_logs(self):
        cfg = FactoryConfig(
            chain="base",
            dex="uniswap_v3",
            adapter_type="uniswap_v3",
            factory="0x33128a8fc17869897dcE68Ed026d694621f6FDfD",
            event_name="PoolCreated",
            event_signature="PoolCreated(address,address,uint24,int24,address)",
            log_layout=LAYOUT_V3_POOL_CREATED,
            topic0="0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
            topic0_verified=True,
            verification_from_block=None,
            verification_to_block=None,
        )
        token = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        pool = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        raw_log = {
            "address": cfg.factory,
            "blockNumber": 100,
            "transactionHash": "0x" + "cc" * 32,
            "logIndex": 0,
            "topics": [
                cfg.topic0,
                address_to_topic(token),
                address_to_topic(_WETH),
                "0x" + "0" * 62 + "01",
            ],
            "data": "0x" + ("0" * 64) + ("0" * 24) + pool[2:].lower(),
        }

        w3 = MagicMock()
        w3.to_checksum_address.side_effect = lambda x: x

        def fake_get_logs(params):
            topics = params.get("topics") or []
            if topics[1] == address_to_topic(token):
                return [raw_log]
            return []

        events = find_recent_pools_containing_token(
            token,
            from_block=90,
            to_block=110,
            chain="base",
            w3=w3,
            get_logs=fake_get_logs,
            factory_configs=[cfg],
            max_blocks_per_call=500,
        )
        assert len(events) == 1
        assert events[0].pool.lower() == pool.lower()
        assert events[0].token0.lower() == token.lower()


class TestTokenWatchlist:
    def test_scan_due_respects_backoff(self):
        entry = {"scan_backoff_stage": 0, "last_scan_ts": 1000.0}
        assert scan_due(entry, 1000.0 + SCAN_BACKOFF_STAGES_S[0] - 1) is False
        assert scan_due(entry, 1000.0 + SCAN_BACKOFF_STAGES_S[0]) is True

    def test_upsert_creates_first_pool_seed(self):
        wl = {"tokens": {}, "metrics": {}}
        ev = {
            "dex": "uniswap_v4",
            "pool": "0xpool",
            "block_number": 42,
            "tx_hash": "0xabc",
        }
        entry = upsert_watch_entry_from_event(
            wl,
            ev,
            exotic_address=_TOKEN,
            exotic_symbol="LONG",
            now_ts=100.0,
            config=_strategy_config(),
        )
        assert entry["first_dex"] == "uniswap_v4"
        assert entry["first_block"] == 42
        assert entry["seen_on_dexes"] == ["uniswap_v4"]
        assert "prior_pool_count" in entry
        assert "token_class" in entry

    def test_record_second_pool_transition_metrics(self):
        entry = {
            "first_seen_ts": 100.0,
            "first_tx_hash": "0xaaa",
            "first_block": 10,
            "seen_on_dexes": ["uniswap_v4"],
            "second_pool_verified": False,
        }
        metrics = {
            "time_to_second_pool_s": [],
            "same_tx_second_pool_count": 0,
            "same_block_second_pool_count": 0,
            "cross_mechanic_transition_count": 0,
            "transitions_1_to_2": 0,
        }
        dex_adapter = {"uniswap_v4": "uniswap_v4", "aerodrome": "ve33"}
        ok = _record_second_pool(
            entry,
            event_dict={
                "dex": "aerodrome",
                "pool": "0xpool2",
                "block_number": 11,
                "tx_hash": "0xbbb",
            },
            dex_adapter=dex_adapter,
            now_ts=160.0,
            metrics=metrics,
        )
        assert ok is True
        assert entry["second_pool_verified"] is True
        assert entry["time_to_second_pool_s"] == 60.0
        assert metrics["transitions_1_to_2"] == 1
        assert metrics["cross_mechanic_transition_count"] == 1

    def test_metrics_summary_no_second_pool_note(self):
        wl = {
            "tokens": {"0x1": {"second_pool_verified": False}},
            "metrics": {"time_to_second_pool_s": []},
        }
        summary = metrics_summary(wl)
        assert summary["existence_note"] == "NO_SECOND_POOL_IN_WINDOW"
