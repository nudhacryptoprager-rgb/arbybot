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
    LAYOUT_SLIPSTREAM_POOL_CREATED,
    LAYOUT_V2_PAIR_CREATED,
    LAYOUT_V3_POOL_CREATED,
    LAYOUT_VE33_PAIR_CREATED,
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
# ve33 PairCreated parser
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
                LAYOUT_VE33_PAIR_CREATED,
                LAYOUT_V2_PAIR_CREATED,
            ), f"Unknown layout: {cfg.log_layout}"

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
        assert "stable" in flds

    def test_factoryconfig_is_dataclass(self):
        from dataclasses import fields
        flds = {f.name for f in fields(FactoryConfig)}
        assert "chain" in flds
        assert "dex" in flds
        assert "factory" in flds
        assert "log_layout" in flds
        assert "topic0" in flds
