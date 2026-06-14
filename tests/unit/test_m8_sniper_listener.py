"""Unit tests for discovery.new_pool_listener — M8 Phase 1.

Covers:
  - make_event_id: determinism, uniqueness, canonicalisation
  - parse_raw_log + per-layout parsers: valid paths, missing fields, short data
  - dedup_events: preserves first-seen, drops duplicates
  - load_factory_config: YAML round-trip (offline, no network)
  - Module importability without web3 installed
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Import target (must succeed without web3)
# ---------------------------------------------------------------------------
from discovery.new_pool_listener import (
    LAYOUT_ALGEBRA_POOL_CREATED,
    LAYOUT_SLIPSTREAM_POOL_CREATED,
    LAYOUT_VE33_POOL_CREATED,
    LAYOUT_V2_PAIR_CREATED,
    LAYOUT_V3_POOL_CREATED,
    LAYOUT_VE33_PAIR_CREATED,
    LAYOUT_V4_INITIALIZE,
    FactoryConfig,
    NewPoolEvent,
    dedup_events,
    load_factory_config,
    make_event_id,
    parse_raw_log,
)

# ---------------------------------------------------------------------------
# Fixtures / test helpers
# ---------------------------------------------------------------------------

CHAIN = "base"
DEX_V3 = "uniswap_v3"
DEX_SLIPSTREAM = "aerodrome_slipstream"
DEX_VE33 = "aerodrome"
DEX_V2 = "sushiswap_v2"

TOKEN0 = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"  # USDC
TOKEN1 = "0x4200000000000000000000000000000000000006"  # WETH
POOL = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
TX_HASH = "0x" + "aa" * 32
LOG_INDEX = 7
BLOCK_HEX = "0x127a3c0"   # 19578816
FACTORY_V3 = "0x33128a8fc17869897dce68ed026d694621f6fdfd"


def _to_topic_address(addr: str) -> str:
    """Encode a 20-byte address as a 32-byte left-zero-padded topic."""
    raw = addr.lower().lstrip("0x")
    return "0x" + "0" * (64 - len(raw)) + raw


def _to_topic_uint(value: int, bits: int = 256) -> str:
    """Encode an unsigned integer as a 32-byte hex topic."""
    return "0x" + hex(value)[2:].zfill(64)


def _to_data_word(value: int | str) -> str:
    """Encode a single 32-byte data word (no 0x prefix)."""
    if isinstance(value, str):
        raw = value.lower().lstrip("0x")
        return raw.zfill(64)
    return hex(value)[2:].zfill(64)


def _make_v3_log(
    token0: str = TOKEN0,
    token1: str = TOKEN1,
    fee: int = 500,
    tick_spacing: int = 10,
    pool: str = POOL,
    tx_hash: str = TX_HASH,
    log_index: int = LOG_INDEX,
    block_number: str = BLOCK_HEX,
    factory: str = FACTORY_V3,
    topic0: str = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118",
) -> Dict[str, Any]:
    tick_spacing_encoded = tick_spacing & 0xFFFFFF  # two's complement in 24 bits
    data = "0x" + _to_data_word(tick_spacing_encoded) + _to_data_word(pool)
    return {
        "address": factory,
        "topics": [
            topic0,
            _to_topic_address(token0),
            _to_topic_address(token1),
            _to_topic_uint(fee),
        ],
        "data": data,
        "blockNumber": block_number,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
    }


def _make_slipstream_log(
    token0: str = TOKEN0,
    token1: str = TOKEN1,
    tick_spacing: int = 200,
    pool: str = POOL,
    tx_hash: str = TX_HASH,
    log_index: int = LOG_INDEX,
    block_number: str = BLOCK_HEX,
    factory: str = "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
) -> Dict[str, Any]:
    ts_encoded = tick_spacing & 0xFFFFFF
    data = "0x" + _to_data_word(pool)
    return {
        "address": factory,
        "topics": [
            "0x0000000000000000000000000000000000000000000000000000000000000001",  # dummy topic0
            _to_topic_address(token0),
            _to_topic_address(token1),
            _to_topic_uint(ts_encoded),
        ],
        "data": data,
        "blockNumber": block_number,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
    }


def _make_ve33_log(
    token0: str = TOKEN0,
    token1: str = TOKEN1,
    stable: bool = False,
    pool: str = POOL,
    all_pairs: int = 42,
    tx_hash: str = TX_HASH,
    log_index: int = LOG_INDEX,
    block_number: str = BLOCK_HEX,
    factory: str = "0x420dd381b31aef6683db6b902084cb0ffece40da",
) -> Dict[str, Any]:
    stable_word = _to_data_word(1 if stable else 0)
    pool_word = _to_data_word(pool)
    all_pairs_word = _to_data_word(all_pairs)
    data = "0x" + stable_word + pool_word + all_pairs_word
    return {
        "address": factory,
        "topics": [
            "0xc4805696c66d7cf352fc1d6bb633ad5ee82f6cb577c453024b6e0eb8306c6fc9",
            _to_topic_address(token0),
            _to_topic_address(token1),
        ],
        "data": data,
        "blockNumber": block_number,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
    }


def _make_ve33_pool_log(
    token0: str = TOKEN0,
    token1: str = TOKEN1,
    stable: bool = False,
    pool: str = POOL,
    all_pools: int = 42,
    tx_hash: str = TX_HASH,
    log_index: int = LOG_INDEX,
    block_number: str = BLOCK_HEX,
    factory: str = "0x420dd381b31aef6683db6b902084cb0ffece40da",
) -> Dict[str, Any]:
    pool_word = _to_data_word(pool)
    all_pools_word = _to_data_word(all_pools)
    data = "0x" + pool_word + all_pools_word
    return {
        "address": factory,
        "topics": [
            "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e",
            _to_topic_address(token0),
            _to_topic_address(token1),
            _to_topic_uint(1 if stable else 0),
        ],
        "data": data,
        "blockNumber": block_number,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
    }


def _make_v2_log(
    token0: str = TOKEN0,
    token1: str = TOKEN1,
    pool: str = POOL,
    all_pairs: int = 99,
    tx_hash: str = TX_HASH,
    log_index: int = LOG_INDEX,
    block_number: str = BLOCK_HEX,
    factory: str = "0x71524b4f93c58fcbf659783284e38825f0622859",
) -> Dict[str, Any]:
    pool_word = _to_data_word(pool)
    all_pairs_word = _to_data_word(all_pairs)
    data = "0x" + pool_word + all_pairs_word
    return {
        "address": factory,
        "topics": [
            "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9",
            _to_topic_address(token0),
            _to_topic_address(token1),
        ],
        "data": data,
        "blockNumber": block_number,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
    }


def _cfg(
    dex: str = DEX_V3,
    adapter_type: str = "uniswap_v3",
    factory: str = FACTORY_V3,
    layout: str = LAYOUT_V3_POOL_CREATED,
    chain: str = CHAIN,
) -> FactoryConfig:
    return FactoryConfig(
        chain=chain,
        dex=dex,
        adapter_type=adapter_type,
        factory=factory.lower(),
        event_name="PoolCreated",
        event_signature="",
        log_layout=layout,
        topic0=None,
        topic0_verified=True,
        verification_from_block=None,
        verification_to_block=None,
    )


# ---------------------------------------------------------------------------
# make_event_id
# ---------------------------------------------------------------------------

class TestMakeEventId:
    def test_deterministic(self):
        a = make_event_id("base", FACTORY_V3, TX_HASH, 7)
        b = make_event_id("base", FACTORY_V3, TX_HASH, 7)
        assert a == b

    def test_case_insensitive_factory(self):
        a = make_event_id("base", FACTORY_V3.upper(), TX_HASH, 0)
        b = make_event_id("base", FACTORY_V3.lower(), TX_HASH, 0)
        assert a == b

    def test_case_insensitive_tx_hash(self):
        a = make_event_id("base", FACTORY_V3, TX_HASH.upper(), 0)
        b = make_event_id("base", FACTORY_V3, TX_HASH.lower(), 0)
        assert a == b

    def test_unique_by_log_index(self):
        a = make_event_id("base", FACTORY_V3, TX_HASH, 0)
        b = make_event_id("base", FACTORY_V3, TX_HASH, 1)
        assert a != b

    def test_unique_by_tx_hash(self):
        a = make_event_id("base", FACTORY_V3, "0x" + "aa" * 32, 0)
        b = make_event_id("base", FACTORY_V3, "0x" + "bb" * 32, 0)
        assert a != b

    def test_unique_by_factory(self):
        a = make_event_id("base", FACTORY_V3, TX_HASH, 0)
        b = make_event_id("base", "0x1234" + "0" * 36, TX_HASH, 0)
        assert a != b

    def test_format_contains_all_parts(self):
        eid = make_event_id("base", FACTORY_V3, TX_HASH, 3)
        assert "base" in eid
        assert FACTORY_V3.lower() in eid
        assert TX_HASH.lower() in eid
        assert ":3" in eid


# ---------------------------------------------------------------------------
# V3 PoolCreated parser
# ---------------------------------------------------------------------------

class TestParseV3PoolCreated:
    def test_valid_log_parses(self):
        log = _make_v3_log(fee=3000, tick_spacing=60, pool=POOL)
        cfg = _cfg()
        ev = parse_raw_log(log, cfg)
        assert ev is not None
        assert ev.token0 == TOKEN0
        assert ev.token1 == TOKEN1
        assert ev.fee == 3000
        assert ev.tick_spacing == 60
        assert ev.pool == POOL.lower()
        assert ev.adapter_type == "uniswap_v3"
        assert ev.dex == DEX_V3
        assert ev.chain == CHAIN
        assert ev.block_number == 0x127A3C0
        assert ev.log_index == LOG_INDEX

    def test_fee_100(self):
        log = _make_v3_log(fee=100, tick_spacing=1)
        ev = parse_raw_log(log, _cfg())
        assert ev is not None
        assert ev.fee == 100
        assert ev.tick_spacing == 1

    def test_negative_tick_spacing_decoded(self):
        """Negative tick spacings (int24) should round-trip correctly."""
        log = _make_v3_log(fee=500, tick_spacing=-1)
        ev = parse_raw_log(log, _cfg())
        assert ev is not None
        assert ev.tick_spacing == -1

    def test_too_few_topics_returns_none(self):
        log = _make_v3_log()
        log["topics"] = log["topics"][:3]  # remove fee topic
        ev = parse_raw_log(log, _cfg())
        assert ev is None

    def test_short_data_returns_none(self):
        log = _make_v3_log()
        log["data"] = "0x" + "aa" * 10  # too short (need at least 64 bytes = 128 hex chars)
        ev = parse_raw_log(log, _cfg())
        assert ev is None

    def test_missing_topics_key_returns_none(self):
        log = _make_v3_log()
        del log["topics"]
        ev = parse_raw_log(log, _cfg())
        assert ev is None

    def test_event_id_is_deterministic(self):
        log = _make_v3_log()
        ev1 = parse_raw_log(log, _cfg())
        ev2 = parse_raw_log(log, _cfg())
        assert ev1 is not None and ev2 is not None
        assert ev1.event_id == ev2.event_id

    def test_stable_is_none_for_v3(self):
        ev = parse_raw_log(_make_v3_log(), _cfg())
        assert ev is not None
        assert ev.stable is None

    def test_block_number_hex_string(self):
        log = _make_v3_log(block_number="0x100")
        ev = parse_raw_log(log, _cfg())
        assert ev is not None
        assert ev.block_number == 256

    def test_block_number_int(self):
        log = _make_v3_log()
        log["blockNumber"] = 12345
        ev = parse_raw_log(log, _cfg())
        assert ev is not None
        assert ev.block_number == 12345


# ---------------------------------------------------------------------------
# Slipstream PoolCreated parser
# ---------------------------------------------------------------------------

class TestParseSlipstreamPoolCreated:
    def _scfg(self) -> FactoryConfig:
        return _cfg(
            dex=DEX_SLIPSTREAM,
            adapter_type="aerodrome_slipstream",
            factory="0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
            layout=LAYOUT_SLIPSTREAM_POOL_CREATED,
        )

    def test_valid_log_parses(self):
        log = _make_slipstream_log(tick_spacing=200)
        ev = parse_raw_log(log, self._scfg())
        assert ev is not None
        assert ev.token0 == TOKEN0
        assert ev.token1 == TOKEN1
        assert ev.tick_spacing == 200
        assert ev.fee is None
        assert ev.stable is None
        assert ev.pool == POOL.lower()
        assert ev.adapter_type == "aerodrome_slipstream"

    def test_tick_spacing_1(self):
        log = _make_slipstream_log(tick_spacing=1)
        ev = parse_raw_log(log, self._scfg())
        assert ev is not None
        assert ev.tick_spacing == 1

    def test_too_few_topics_returns_none(self):
        log = _make_slipstream_log()
        log["topics"] = log["topics"][:3]  # remove tickSpacing topic
        ev = parse_raw_log(log, self._scfg())
        assert ev is None

    def test_short_data_returns_none(self):
        log = _make_slipstream_log()
        log["data"] = "0x" + "aa" * 5
        ev = parse_raw_log(log, self._scfg())
        assert ev is None

    def test_negative_tick_spacing(self):
        log = _make_slipstream_log(tick_spacing=-50)
        ev = parse_raw_log(log, self._scfg())
        assert ev is not None
        assert ev.tick_spacing == -50


# ---------------------------------------------------------------------------
# ve33 PoolCreated parser (Aerodrome / Velodrome)
# ---------------------------------------------------------------------------

class TestParseVe33PoolCreated:
    def _vcfg(self) -> FactoryConfig:
        return _cfg(
            dex=DEX_VE33,
            adapter_type="ve33",
            factory="0x420dd381b31aef6683db6b902084cb0ffece40da",
            layout=LAYOUT_VE33_POOL_CREATED,
        )

    def test_volatile_pool(self):
        log = _make_ve33_pool_log(stable=False)
        ev = parse_raw_log(log, self._vcfg())
        assert ev is not None
        assert ev.event_name == "PoolCreated"
        assert ev.stable is False
        assert ev.fee is None
        assert ev.tick_spacing is None
        assert ev.pool == POOL.lower()
        assert ev.adapter_type == "ve33"

    def test_stable_pool(self):
        log = _make_ve33_pool_log(stable=True)
        ev = parse_raw_log(log, self._vcfg())
        assert ev is not None
        assert ev.stable is True

    def test_too_few_topics_returns_none(self):
        log = _make_ve33_pool_log()
        log["topics"] = log["topics"][:3]  # remove indexed stable topic
        ev = parse_raw_log(log, self._vcfg())
        assert ev is None

    def test_short_data_returns_none(self):
        log = _make_ve33_pool_log()
        log["data"] = "0x" + "00" * 30  # less than 2 words
        ev = parse_raw_log(log, self._vcfg())
        assert ev is None


# ---------------------------------------------------------------------------
# ve33 PairCreated parser (legacy Solidly-style forks)
# ---------------------------------------------------------------------------

class TestParseVe33PairCreated:
    def _vcfg(self) -> FactoryConfig:
        return _cfg(
            dex=DEX_VE33,
            adapter_type="ve33",
            factory="0x420dd381b31aef6683db6b902084cb0ffece40da",
            layout=LAYOUT_VE33_PAIR_CREATED,
        )

    def test_volatile_pool(self):
        log = _make_ve33_log(stable=False)
        ev = parse_raw_log(log, self._vcfg())
        assert ev is not None
        assert ev.stable is False
        assert ev.fee is None
        assert ev.tick_spacing is None
        assert ev.pool == POOL.lower()
        assert ev.adapter_type == "ve33"

    def test_stable_pool(self):
        log = _make_ve33_log(stable=True)
        ev = parse_raw_log(log, self._vcfg())
        assert ev is not None
        assert ev.stable is True

    def test_too_few_topics_returns_none(self):
        log = _make_ve33_log()
        log["topics"] = log["topics"][:2]  # remove token1 topic
        ev = parse_raw_log(log, self._vcfg())
        assert ev is None

    def test_short_data_returns_none(self):
        log = _make_ve33_log()
        log["data"] = "0x" + "00" * 30  # less than 3 words
        ev = parse_raw_log(log, self._vcfg())
        assert ev is None


# ---------------------------------------------------------------------------
# V2 PairCreated parser
# ---------------------------------------------------------------------------

class TestParseV2PairCreated:
    def _v2cfg(self) -> FactoryConfig:
        return _cfg(
            dex=DEX_V2,
            adapter_type="uniswap_v2",
            factory="0x71524b4f93c58fcbf659783284e38825f0622859",
            layout=LAYOUT_V2_PAIR_CREATED,
        )

    def test_valid_log_parses(self):
        log = _make_v2_log()
        ev = parse_raw_log(log, self._v2cfg())
        assert ev is not None
        assert ev.token0 == TOKEN0
        assert ev.token1 == TOKEN1
        assert ev.pool == POOL.lower()
        assert ev.fee is None
        assert ev.tick_spacing is None
        assert ev.stable is None
        assert ev.adapter_type == "uniswap_v2"

    def test_short_data_returns_none(self):
        log = _make_v2_log()
        log["data"] = "0x"
        ev = parse_raw_log(log, self._v2cfg())
        assert ev is None


# ---------------------------------------------------------------------------
# parse_raw_log dispatch
# ---------------------------------------------------------------------------

class TestParseRawLogDispatch:
    def test_unknown_layout_returns_none(self):
        cfg = _cfg(layout="unknown_layout")
        log = _make_v3_log()
        ev = parse_raw_log(log, cfg)
        assert ev is None

    def test_dispatch_v3(self):
        ev = parse_raw_log(_make_v3_log(), _cfg(layout=LAYOUT_V3_POOL_CREATED))
        assert ev is not None
        assert ev.adapter_type == "uniswap_v3"

    def test_dispatch_slipstream(self):
        cfg = _cfg(
            dex=DEX_SLIPSTREAM,
            adapter_type="aerodrome_slipstream",
            factory="0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
            layout=LAYOUT_SLIPSTREAM_POOL_CREATED,
        )
        ev = parse_raw_log(_make_slipstream_log(), cfg)
        assert ev is not None
        assert ev.adapter_type == "aerodrome_slipstream"

    def test_dispatch_ve33(self):
        cfg = _cfg(
            dex=DEX_VE33,
            adapter_type="ve33",
            factory="0x420dd381b31aef6683db6b902084cb0ffece40da",
            layout=LAYOUT_VE33_POOL_CREATED,
        )
        ev = parse_raw_log(_make_ve33_pool_log(), cfg)
        assert ev is not None
        assert ev.adapter_type == "ve33"
        assert ev.event_name == "PoolCreated"

    def test_dispatch_legacy_ve33_pair_created(self):
        cfg = _cfg(
            dex=DEX_VE33,
            adapter_type="ve33",
            factory="0x420dd381b31aef6683db6b902084cb0ffece40da",
            layout=LAYOUT_VE33_PAIR_CREATED,
        )
        ev = parse_raw_log(_make_ve33_log(), cfg)
        assert ev is not None
        assert ev.adapter_type == "ve33"

    def test_dispatch_v2(self):
        cfg = _cfg(
            dex=DEX_V2,
            adapter_type="uniswap_v2",
            factory="0x71524b4f93c58fcbf659783284e38825f0622859",
            layout=LAYOUT_V2_PAIR_CREATED,
        )
        ev = parse_raw_log(_make_v2_log(), cfg)
        assert ev is not None
        assert ev.adapter_type == "uniswap_v2"

    def test_raises_never_on_corrupted_input(self):
        """parse_raw_log must never raise, even on garbage."""
        cfg = _cfg()
        assert parse_raw_log({}, cfg) is None
        assert parse_raw_log({"topics": []}, cfg) is None
        assert parse_raw_log({"topics": [None, None, None, None]}, cfg) is None


# ---------------------------------------------------------------------------
# dedup_events
# ---------------------------------------------------------------------------

class TestDedupEvents:
    def _make_event(self, log_index: int = 0, tx: str = TX_HASH) -> NewPoolEvent:
        log = _make_v3_log(log_index=log_index, tx_hash=tx)
        ev = parse_raw_log(log, _cfg())
        assert ev is not None
        return ev

    def test_no_duplicates_unchanged(self):
        events = [self._make_event(0), self._make_event(1), self._make_event(2)]
        result = dedup_events(events)
        assert len(result) == 3

    def test_duplicate_removed(self):
        ev = self._make_event(0)
        result = dedup_events([ev, ev])
        assert len(result) == 1

    def test_preserves_first_seen_order(self):
        e0 = self._make_event(0)
        e1 = self._make_event(1)
        e2 = self._make_event(2)
        result = dedup_events([e0, e1, e2, e1, e0])
        assert result == [e0, e1, e2]

    def test_empty_input(self):
        assert dedup_events([]) == []

    def test_single_event(self):
        ev = self._make_event(0)
        assert dedup_events([ev]) == [ev]

    def test_different_log_index_not_deduped(self):
        """Same tx, different log_index = different events."""
        e0 = self._make_event(0)
        e1 = self._make_event(1)
        result = dedup_events([e0, e1])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# load_factory_config (offline — loads config/new_pool_factories.yaml)
# ---------------------------------------------------------------------------

class TestLoadFactoryConfig:
    """These tests load the actual config file; they are offline (no RPC)."""

    def test_loads_without_error(self):
        configs = load_factory_config()
        assert isinstance(configs, list)
        assert len(configs) >= 1

    def test_all_entries_have_required_fields(self):
        configs = load_factory_config()
        for cfg in configs:
            assert cfg.chain, f"Empty chain in config: {cfg}"
            assert cfg.dex, f"Empty dex: {cfg}"
            assert cfg.adapter_type, f"Empty adapter_type: {cfg}"
            assert cfg.factory.startswith("0x"), f"Invalid factory address: {cfg.factory}"
            assert cfg.log_layout in (
                LAYOUT_V3_POOL_CREATED,
                LAYOUT_SLIPSTREAM_POOL_CREATED,
                LAYOUT_VE33_POOL_CREATED,
                LAYOUT_VE33_PAIR_CREATED,
                LAYOUT_V2_PAIR_CREATED,
                LAYOUT_V4_INITIALIZE,
                LAYOUT_ALGEBRA_POOL_CREATED,
            ), f"Unknown layout: {cfg.log_layout}"

    def test_aerodrome_uses_pool_created_topic(self):
        configs = load_factory_config()
        aero = next(c for c in configs if c.dex == "aerodrome")
        assert aero.event_name == "PoolCreated"
        assert aero.event_signature == "PoolCreated(address,address,bool,address,uint256)"
        assert aero.topic0 == "0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e"
        assert aero.log_layout == LAYOUT_VE33_POOL_CREATED
        assert aero.verification_from_block == 45925000
        assert aero.verification_to_block == 45926000

    def test_uniswap_v3_present(self):
        configs = load_factory_config()
        dex_names = {c.dex for c in configs}
        assert "uniswap_v3" in dex_names

    def test_aerodrome_ve33_present(self):
        configs = load_factory_config()
        dex_names = {c.dex for c in configs}
        assert "aerodrome" in dex_names

    def test_factory_addresses_lowercase(self):
        """Loader must lowercase all factory addresses."""
        configs = load_factory_config()
        for cfg in configs:
            assert cfg.factory == cfg.factory.lower(), (
                f"Factory address not lowercased: {cfg.factory}"
            )

    def test_file_not_found_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_factory_config(tmp_path / "nonexistent.yaml")

    def test_chain_filter(self):
        configs_base = load_factory_config(chain_filter="base")
        for cfg in configs_base:
            assert cfg.chain == "base"

    def test_chain_filter_unknown_returns_empty(self):
        configs = load_factory_config(chain_filter="fantom_ghost_chain")
        assert configs == []

    def test_topic0_preserved_as_lowercase_or_none(self):
        configs = load_factory_config()
        for cfg in configs:
            if cfg.topic0 is not None:
                assert cfg.topic0 == cfg.topic0.lower()
                assert cfg.topic0.startswith("0x")

    def test_verification_ranges_are_int_or_none(self):
        configs = load_factory_config()
        for cfg in configs:
            assert cfg.verification_from_block is None or isinstance(
                cfg.verification_from_block, int
            ), f"{cfg.dex}.verification_from_block must be int or None"
            assert cfg.verification_to_block is None or isinstance(
                cfg.verification_to_block, int
            ), f"{cfg.dex}.verification_to_block must be int or None"


# ---------------------------------------------------------------------------
# Module importability (no web3 required at module level)
# ---------------------------------------------------------------------------

class TestModuleImportability:
    def test_import_does_not_require_web3(self):
        """Module must be importable even if web3 is not installed."""
        # Remove from sys.modules to force re-import evaluation (not reload)
        # We just assert the already-imported module has no web3 at top-level
        import discovery.new_pool_listener as mod
        # If web3 were imported at top-level, it would have already failed.
        # Just verify no attribute exists that would indicate eager web3 init.
        assert not hasattr(mod, "_web3"), "web3 must not be eagerly initialised"

    def test_newpoolevent_is_dataclass(self):
        from dataclasses import fields
        flds = {f.name for f in fields(NewPoolEvent)}
        assert "event_id" in flds
        assert "pool" in flds
        assert "token0" in flds
        assert "token1" in flds
        assert "fee" in flds
        assert "tick_spacing" in flds


# ---------------------------------------------------------------------------
# HexBytes compatibility (web3 v6 returns bytes for topics/data)
# ---------------------------------------------------------------------------

class TestParseRawLogHexBytesCompat:
    """parse_raw_log must succeed when topics/data/transactionHash are bytes.

    web3 v6 ``eth.get_logs()`` returns ``AttributeDict`` with HexBytes values.
    The parser must normalise them before processing (fix for silent parse_failed
    regression found during M8 Phase 1 online smoke on 2026-05-13).
    """

    @staticmethod
    def _make_v3_log_bytes() -> Dict[str, Any]:
        """Build a V3 PoolCreated log with bytes (not str) for topics/data."""
        import struct

        def addr_topic(addr: str) -> bytes:
            return bytes.fromhex(("0" * 24 + addr.lower().replace("0x", "")))

        def uint_topic(v: int) -> bytes:
            return v.to_bytes(32, "big")

        def encode_word(v: Any) -> bytes:
            if isinstance(v, str):
                s = v.lower().replace("0x", "").zfill(64)
                return bytes.fromhex(s)
            return v.to_bytes(32, "big") if isinstance(v, int) else v

        tick_spacing = 60
        pool_addr = TOKEN1  # reuse as dummy pool address
        data = encode_word(tick_spacing) + encode_word(pool_addr)

        return {
            "address": bytes.fromhex(FACTORY_V3.replace("0x", "")),
            "topics": [
                bytes.fromhex("783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"),  # topic0
                bytes.fromhex(("0" * 24 + TOKEN0.replace("0x", ""))),   # token0
                bytes.fromhex(("0" * 24 + TOKEN1.replace("0x", ""))),   # token1
                uint_topic(3000),                                          # fee
            ],
            "data": data,
            "blockNumber": 0x1000,
            "transactionHash": bytes.fromhex(TX_HASH.replace("0x", "")),
            "logIndex": 0,
        }

    def test_v3_log_with_bytes_topics_parses(self):
        """V3 log with bytes topics/data must parse successfully."""
        log = self._make_v3_log_bytes()
        ev = parse_raw_log(log, _cfg())
        assert ev is not None, "parse_raw_log must handle bytes topics from web3"
        assert ev.token0 == TOKEN0.lower()
        assert ev.token1 == TOKEN1.lower()
        assert ev.fee == 3000
        assert ev.tick_spacing == 60

    def test_v3_log_with_bytes_tx_hash_parses(self):
        """transactionHash as bytes must be normalised to hex string."""
        log = self._make_v3_log_bytes()
        ev = parse_raw_log(log, _cfg())
        assert ev is not None
        assert ev.tx_hash == TX_HASH.lower()

    def test_v3_log_with_bytes_block_number_int_parses(self):
        """blockNumber as int (not hex str) must parse correctly."""
        log = self._make_v3_log_bytes()
        ev = parse_raw_log(log, _cfg())
        assert ev is not None
        assert ev.block_number == 0x1000

    def test_strip_0x_handles_bytes(self):
        """Internal _strip_0x must return hex str when given bytes input."""
        from discovery.new_pool_listener import _strip_0x
        result = _strip_0x(bytes.fromhex("783cca1c"))
        assert result == "783cca1c"
        assert isinstance(result, str)

    def test_normalize_raw_log_converts_topics(self):
        """_normalize_raw_log converts bytes topics to 0x-prefixed strings."""
        from discovery.new_pool_listener import _normalize_raw_log
        raw = {
            "topics": [b"\x78\x3c", b"\xde\xad"],
            "data": b"\x00\x01",
            "transactionHash": b"\xbe\xef",
            "blockNumber": 100,
        }
        norm = _normalize_raw_log(raw)
        assert norm["topics"][0] == "0x783c"
        assert norm["topics"][1] == "0xdead"
        assert norm["data"] == "0x0001"
        assert norm["transactionHash"] == "0xbeef"
        assert norm["blockNumber"] == 100  # int unchanged

    def test_factoryconfig_is_dataclass(self):
        from dataclasses import fields
        flds = {f.name for f in fields(FactoryConfig)}
        assert "chain" in flds
        assert "dex" in flds
        assert "factory" in flds
        assert "log_layout" in flds
        assert "topic0" in flds


# ---------------------------------------------------------------------------
# Uniswap V4 Initialize parser tests (R8 new)
# ---------------------------------------------------------------------------

V4_POOL_MANAGER = "0x498581ff718922c3f8e6a244956af099b2652b2b"
V4_TOPIC0 = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
POOL_ID = "0xff0a2c69f2f8ba342e49ce3edf818b6bc53cf5db0af7629f8df2ce7abb3a541f"


def _make_v4_init_log(
    pool_id: str = POOL_ID,
    currency0: str = TOKEN0,
    currency1: str = TOKEN1,
    fee: int = 0x800000,      # dynamic fee flag
    tick_spacing: int = 200,
    hooks: str = "0xd60d6b218116cfd801e28f78d011a203d2b068cc",
    tx_hash: str = TX_HASH,
    log_index: int = LOG_INDEX,
    block_number: str = BLOCK_HEX,
    factory: str = V4_POOL_MANAGER,
) -> Dict[str, Any]:
    """Build a synthetic Uniswap V4 Initialize log."""
    fee_word = _to_data_word(fee)
    ts_encoded = tick_spacing & 0xFFFFFF
    tick_word = _to_data_word(ts_encoded)
    hooks_word = _to_data_word(hooks)
    # sqrtPriceX96 and tick (words 3 and 4) can be anything
    sqrt_word = _to_data_word(0x1eb4151a40562b0e7)
    init_tick_word = _to_data_word(0)
    data = "0x" + fee_word + tick_word + hooks_word + sqrt_word + init_tick_word
    return {
        "address": factory,
        "topics": [
            V4_TOPIC0,
            pool_id,
            _to_topic_address(currency0),
            _to_topic_address(currency1),
        ],
        "data": data,
        "blockNumber": block_number,
        "transactionHash": tx_hash,
        "logIndex": hex(log_index),
    }


def _v4_cfg(
    dex: str = "uniswap_v4",
    factory: str = V4_POOL_MANAGER,
) -> FactoryConfig:
    return FactoryConfig(
        chain=CHAIN,
        dex=dex,
        adapter_type="uniswap_v4",
        factory=factory.lower(),
        event_name="Initialize",
        event_signature="Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)",
        log_layout=LAYOUT_V4_INITIALIZE,
        topic0=V4_TOPIC0,
        topic0_verified=True,
        verification_from_block=None,
        verification_to_block=None,
    )


class TestV4InitializeParsing:
    """parse_raw_log with v4_initialize layout."""

    def test_basic_parse_returns_event(self):
        log = _make_v4_init_log()
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert isinstance(event, NewPoolEvent)

    def test_pool_is_pool_id_bytes32(self):
        log = _make_v4_init_log(pool_id=POOL_ID)
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        # pool field must be the full 32-byte PoolId (0x + 64 hex chars)
        assert event.pool.startswith("0x")
        assert len(event.pool) == 66  # 0x + 64 hex

    def test_token0_token1_extracted_correctly(self):
        log = _make_v4_init_log(currency0=TOKEN0, currency1=TOKEN1)
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert event.token0 == TOKEN0
        assert event.token1 == TOKEN1

    def test_fee_extracted(self):
        log = _make_v4_init_log(fee=3000)
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert event.fee == 3000

    def test_tick_spacing_extracted(self):
        log = _make_v4_init_log(tick_spacing=60)
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert event.tick_spacing == 60

    def test_dynamic_fee_flag_parsed(self):
        """0x800000 is the Uniswap V4 DYNAMIC_FEE_FLAG (Clanker pools)."""
        log = _make_v4_init_log(fee=0x800000)
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert event.fee == 0x800000

    def test_stable_is_none(self):
        log = _make_v4_init_log()
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert event.stable is None

    def test_dex_name_preserved(self):
        log = _make_v4_init_log()
        event = parse_raw_log(log, _v4_cfg(dex="uniswap_v4"))
        assert event is not None
        assert event.dex == "uniswap_v4"

    def test_too_few_topics_returns_none(self):
        log = _make_v4_init_log()
        log["topics"] = log["topics"][:2]  # only 2 topics
        event = parse_raw_log(log, _v4_cfg())
        assert event is None

    def test_short_data_returns_none(self):
        log = _make_v4_init_log()
        log["data"] = "0x00112233"  # only 4 bytes, needs >=32
        event = parse_raw_log(log, _v4_cfg())
        assert event is None

    def test_event_id_deterministic(self):
        log = _make_v4_init_log()
        cfg = _v4_cfg()
        event1 = parse_raw_log(log, cfg)
        event2 = parse_raw_log(log, cfg)
        assert event1 is not None and event2 is not None
        assert event1.event_id == event2.event_id

    def test_block_number_parsed(self):
        log = _make_v4_init_log(block_number="0x127a3c0")
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert event.block_number == 0x127a3c0  # 19375040

    def test_pool_id_length_is_66_chars(self):
        """V4 pool field is a 32-byte PoolId (0x + 64 hex chars = 66 chars total)."""
        log = _make_v4_init_log(pool_id=POOL_ID)
        event = parse_raw_log(log, _v4_cfg())
        assert event is not None
        assert len(event.pool) == 66
        assert event.pool.startswith("0x")

    def test_exactly_one_data_word_returns_none(self):
        """data with only 1 word (64 hex chars) must return None — full Initialize needs 5 words."""
        log = _make_v4_init_log()
        # Replace data with exactly 1 word (32 bytes = 64 hex chars, no 0x)
        log["data"] = "0x" + "ab" * 32  # 64 hex chars = 1 word
        event = parse_raw_log(log, _v4_cfg())
        assert event is None


# ---------------------------------------------------------------------------
# Config loading: verify V4 and V2 entries present in YAML (R8 new)
# ---------------------------------------------------------------------------


class TestFactoryConfigR8Extensions:
    """load_factory_config includes the new V4 and V2 entries."""

    def test_uniswap_v4_present(self):
        configs = load_factory_config()
        dex_names = [c.dex for c in configs]
        assert "uniswap_v4" in dex_names

    def test_uniswap_v2_present(self):
        configs = load_factory_config()
        dex_names = [c.dex for c in configs]
        assert "uniswap_v2" in dex_names

    def test_uniswap_v4_layout_is_v4_initialize(self):
        configs = {c.dex: c for c in load_factory_config()}
        assert configs["uniswap_v4"].log_layout == LAYOUT_V4_INITIALIZE

    def test_uniswap_v2_layout_is_v2_pair_created(self):
        configs = {c.dex: c for c in load_factory_config()}
        assert configs["uniswap_v2"].log_layout == LAYOUT_V2_PAIR_CREATED

    def test_uniswap_v4_topic0_verified(self):
        configs = {c.dex: c for c in load_factory_config()}
        v4 = configs["uniswap_v4"]
        assert v4.topic0 is not None
        assert v4.topic0_verified is True
        assert v4.topic0 == "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"

    def test_uniswap_v4_factory_address(self):
        configs = {c.dex: c for c in load_factory_config()}
        # Factory is PoolManager — must match official Base deployment
        assert configs["uniswap_v4"].factory.lower() == "0x498581ff718922c3f8e6a244956af099b2652b2b"

    def test_uniswap_v2_factory_address(self):
        configs = {c.dex: c for c in load_factory_config()}
        assert configs["uniswap_v2"].factory.lower() == "0x8909dc15e40173ff4699343b6eb8132c65e18ec6"

    _EXPECTED_BASE_DEXES = frozenset({
        "uniswap_v3",
        "aerodrome_slipstream",
        "aerodrome",
        "pancakeswap_v3",
        "uniswap_v4",
        "uniswap_v2",
        "sushiswap_v2",
        "baseswap_v2",
        "sushiswap_v3",
        "alien_base_v2",
        "alien_area51",
        "quickswap_algebra",
    })

    def test_base_factory_dex_set(self):
        """Regression: explicit DEX set — avoids brittle exact-count drift."""
        configs = load_factory_config(chain_filter="base")
        dex_names = {c.dex for c in configs}
        assert dex_names == self._EXPECTED_BASE_DEXES
        assert len(configs) == len(self._EXPECTED_BASE_DEXES)

    def test_quickswap_algebra_discovery_lane_contract(self):
        configs = {c.dex: c for c in load_factory_config()}
        algebra = configs["quickswap_algebra"]
        assert algebra.adapter_type == "algebra"
        assert algebra.log_layout == LAYOUT_ALGEBRA_POOL_CREATED
        assert algebra.topic0_verified is True
        assert algebra.discovery_only is True
        assert algebra.verification_from_block is None
        assert algebra.verification_to_block is None
        assert algebra.topic0 == (
            "0x26f6a048ee9138f2c0cea2666dd3c363216d48e9db92aef21ef7e1dd9e9e4da2"
        )

    def test_total_factory_count_is_six(self):
        """Deprecated alias — kept for grep stability; see test_base_factory_dex_set."""
        configs = load_factory_config(chain_filter="base")
        assert len(configs) == 12

    def test_all_new_configs_have_verification_blocks(self):
        configs = {c.dex: c for c in load_factory_config()}
        for dex in ("uniswap_v4", "uniswap_v2"):
            cfg = configs[dex]
            assert cfg.verification_from_block is not None, f"{dex} missing from_block"
            assert cfg.verification_to_block is not None, f"{dex} missing to_block"

    def test_uniswap_v4_is_discovery_only(self):
        """V4 PoolManager must be flagged discovery_only — execution path not yet approved."""
        configs = {c.dex: c for c in load_factory_config()}
        assert configs["uniswap_v4"].discovery_only is True

    def test_uniswap_v2_is_discovery_only(self):
        """V2 experimental lane must be flagged discovery_only — requires downstream filters."""
        configs = {c.dex: c for c in load_factory_config()}
        assert configs["uniswap_v2"].discovery_only is True

    def test_legacy_factories_not_discovery_only(self):
        """Pre-R8 factories (V3, Slipstream, ve33, Pancake) must have discovery_only=False (default)."""
        configs = {c.dex: c for c in load_factory_config()}
        for dex in ("uniswap_v3", "aerodrome_slipstream", "aerodrome", "pancakeswap_v3"):
            if dex in configs:
                assert configs[dex].discovery_only is False, f"{dex} should not be discovery_only"




class TestClankerDiscoverySource:
    """Unit tests for m8.discovery.clanker_source (pure / offline)."""

    def test_import(self):
        from m8.discovery.clanker_source import (
            ClankerDiscoverySource,
            ClankerPool,
            ClankerSourceError,
            CLANKER_DEX_ID,
        )
        assert ClankerDiscoverySource is not None

    def test_clanker_pool_from_gecko_data(self):
        from m8.discovery.clanker_source import ClankerPool
        item = {
            "attributes": {
                "address": "0xABCDEF1234",
                "name": "PEPE / USDC",
                "pool_created_at": "2026-05-14T12:00:00Z",
                "fdv_usd": "1234.56",
                "volume_usd": {"h24": "5678.9"},
            },
            "relationships": {
                "dex": {"data": {"id": "uniswap-v4-base"}},
                "base_token": {"data": {"id": "base_0xtoken0address"}},
                "quote_token": {"data": {"id": "base_0xtoken1address"}},
            },
        }
        pool = ClankerPool.from_gecko_data(item, network="base")
        assert pool.pool_address == "0xabcdef1234"
        assert pool.dex_id == "uniswap-v4-base"
        assert pool.name == "PEPE / USDC"
        assert pool.token0_address == "0xtoken0address"
        assert pool.token1_address == "0xtoken1address"
        assert pool.fdv_usd == pytest.approx(1234.56)
        assert pool.volume_usd_24h == pytest.approx(5678.9)

    def test_clanker_pool_from_gecko_data_minimal(self):
        """Empty/missing attributes don't crash."""
        from m8.discovery.clanker_source import ClankerPool
        pool = ClankerPool.from_gecko_data({}, network="base")
        assert pool.pool_address == ""
        assert pool.dex_id == ""

    def test_dex_filter_default_is_v4(self):
        from m8.discovery.clanker_source import ClankerDiscoverySource, CLANKER_DEX_ID
        src = ClankerDiscoverySource()
        assert src.dex_filter == CLANKER_DEX_ID

    def test_dex_filter_none_accepts_all(self):
        from m8.discovery.clanker_source import ClankerDiscoverySource
        src = ClankerDiscoverySource(dex_filter=None)
        assert src.dex_filter is None

    def test_fetch_new_pools_returns_empty_list_on_network_error(self, monkeypatch):
        """fetch_new_pools swallows OSError (no network) and returns []."""
        from m8.discovery.clanker_source import ClankerDiscoverySource
        import urllib.request

        def _fail(*args, **kwargs):
            raise OSError("no network")

        monkeypatch.setattr(urllib.request, "urlopen", _fail)
        src = ClankerDiscoverySource()
        result = src.fetch_new_pools(page=1)
        assert result == []

    def test_fetch_new_pools_raises_on_4xx(self, monkeypatch):
        """4xx HTTP errors surface as ClankerSourceError."""
        from m8.discovery.clanker_source import ClankerDiscoverySource, ClankerSourceError
        import urllib.error
        import urllib.request

        def _fail(*args, **kwargs):
            raise urllib.error.HTTPError(
                url="https://test", code=429, msg="Too Many Requests",
                hdrs=None, fp=None,
            )

        monkeypatch.setattr(urllib.request, "urlopen", _fail)
        src = ClankerDiscoverySource()
        with pytest.raises(ClankerSourceError):
            src.fetch_new_pools(page=1)


class TestParseAlgebraPoolCreated:
    def test_valid_algebra_pool_log_parses(self):
        log = {
            "address": "0xc5396866754799b9720125b104ae01d935ab9c7b",
            "topics": [
                "0x26f6a048ee9138f2c0cea2666dd3c363216d48e9db92aef21ef7e1dd9e9e4da2",
                _to_topic_address(TOKEN0),
                _to_topic_address(TOKEN1),
            ],
            "data": "0x" + _to_data_word(POOL),
            "blockNumber": BLOCK_HEX,
            "transactionHash": TX_HASH,
            "logIndex": hex(LOG_INDEX),
        }
        cfg = _cfg(
            dex="quickswap_algebra",
            adapter_type="algebra",
            factory="0xc5396866754799b9720125b104ae01d935ab9c7b",
            layout=LAYOUT_ALGEBRA_POOL_CREATED,
        )
        ev = parse_raw_log(log, cfg)
        assert ev is not None
        assert ev.pool == POOL.lower()
        assert ev.token0 == TOKEN0
        assert ev.token1 == TOKEN1
        assert ev.dex == "quickswap_algebra"
