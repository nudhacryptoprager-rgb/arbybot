"""Unit tests for m7.orderflow.pool_price_state (M7.E1.51 slice-1).

Tests are pure-Python (no RPC, no asyncio) and self-contained.
"""
from __future__ import annotations

import pytest

from m7.orderflow.pool_price_state import (
    PoolPriceStateRegistry,
    V2PoolState,
    V3PoolState,
    decode_v2_sync_log_state,
    decode_v3_swap_log_state,
    get_registry,
    reset_registry_for_tests,
)


# ---------------------------------------------------------------------------
# Fixture: build a valid 320-hex Swap log payload
# ---------------------------------------------------------------------------

def _u256_hex(val: int) -> str:
    """Encode an unsigned int into 64 hex chars (32 bytes, big-endian)."""
    if val < 0:
        val += 1 << 256
    return f"{val:064x}"


def _i256_hex(val: int) -> str:
    """Encode a signed int into 64 hex chars (two's complement)."""
    if val < 0:
        val += 1 << 256
    return f"{val:064x}"


def _build_swap_log(
    *,
    pool_address: str = "0xabcDef0000000000000000000000000000001234",
    block_number: int = 12345678,
    log_index: int = 7,
    amount0: int = 1_000_000,  # 1 USDC (6 dec)
    amount1: int = -300_000_000_000_000,  # ~ -0.0003 WETH
    sqrt_price_x96: int = 79228162514264337593543950336,  # = 1.0 in Q96
    liquidity: int = 12345678901234567890,
    tick: int = -42,
) -> dict:
    data_hex = (
        _i256_hex(amount0)
        + _i256_hex(amount1)
        + _u256_hex(sqrt_price_x96)
        + _u256_hex(liquidity)
        + _i256_hex(tick)
    )
    return {
        "address": pool_address,
        "blockNumber": block_number,
        "logIndex": log_index,
        "data": "0x" + data_hex,
        "transactionHash": "0x" + "11" * 32,
    }


# ---------------------------------------------------------------------------
# decode_v3_swap_log_state
# ---------------------------------------------------------------------------

class TestDecode:
    def test_decode_well_formed_log_returns_state(self):
        log = _build_swap_log()
        state = decode_v3_swap_log_state(log, chain="base")
        assert state is not None
        assert state.pool_address == log["address"].lower()
        assert state.sqrt_price_x96 == 79228162514264337593543950336
        assert state.liquidity == 12345678901234567890
        assert state.tick == -42
        assert state.block_number == 12345678
        assert state.log_index == 7
        assert state.chain == "base"
        assert state.captured_at.endswith("Z")

    def test_decode_negative_tick_two_complement(self):
        log = _build_swap_log(tick=-887272)  # near MIN_TICK
        state = decode_v3_swap_log_state(log, chain="base")
        assert state is not None
        assert state.tick == -887272

    def test_decode_positive_tick(self):
        log = _build_swap_log(tick=887272)  # near MAX_TICK
        state = decode_v3_swap_log_state(log, chain="base")
        assert state is not None
        assert state.tick == 887272

    def test_decode_zero_sqrt_price_rejected(self):
        log = _build_swap_log(sqrt_price_x96=0)
        state = decode_v3_swap_log_state(log, chain="base")
        assert state is None

    def test_decode_short_payload_returns_none(self):
        log = {
            "address": "0xabcd",
            "blockNumber": 1,
            "logIndex": 0,
            "data": "0x" + "ab" * 16,  # only 32 hex chars
            "transactionHash": "0x" + "00" * 32,
        }
        assert decode_v3_swap_log_state(log, chain="base") is None

    def test_decode_missing_field_returns_none_no_raise(self):
        # No 'data' key at all
        log = {"address": "0xabcd", "blockNumber": 1, "logIndex": 0}
        assert decode_v3_swap_log_state(log, chain="base") is None

    def test_decode_address_lowercased(self):
        log = _build_swap_log(pool_address="0xABCDEF0000000000000000000000000000001234")
        state = decode_v3_swap_log_state(log, chain="base")
        assert state is not None
        assert state.pool_address == "0xabcdef0000000000000000000000000000001234"

    def test_uint160_mask_applied_to_sqrt_price(self):
        # sqrtPriceX96 is uint160 — the high 12 bytes (96 bits) of the 32B word
        # are spec-required-zero, but if a malformed feed sets them, we must
        # still extract only the low 160 bits.
        big = (1 << 250) | 79228162514264337593543950336
        log = _build_swap_log(sqrt_price_x96=big)
        state = decode_v3_swap_log_state(log, chain="base")
        assert state is not None
        # mask removes bits above 160
        assert state.sqrt_price_x96 == big & ((1 << 160) - 1)


# ---------------------------------------------------------------------------
# PoolPriceStateRegistry
# ---------------------------------------------------------------------------

class TestRegistry:
    def setup_method(self):
        reset_registry_for_tests()

    def test_update_from_log_stores_state(self):
        reg = PoolPriceStateRegistry()
        ok = reg.update_from_v3_log("base", _build_swap_log())
        assert ok is True
        assert reg.pools_tracked("base") == 1
        assert reg.counters()["updates_total"] == 1
        assert reg.counters()["decode_errors_total"] == 0

    def test_update_from_malformed_log_increments_error_counter(self):
        reg = PoolPriceStateRegistry()
        ok = reg.update_from_v3_log("base", {"address": "0x0", "data": "0x"})
        assert ok is False
        assert reg.counters()["decode_errors_total"] == 1
        assert reg.pools_tracked("base") == 0

    def test_get_returns_latest_state(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log("base", _build_swap_log(block_number=100, log_index=0, tick=10))
        reg.update_from_v3_log("base", _build_swap_log(block_number=101, log_index=0, tick=20))
        st = reg.get("base", "0xabcDef0000000000000000000000000000001234")
        assert st is not None
        assert st.tick == 20
        assert st.block_number == 101

    def test_stale_log_dropped(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log("base", _build_swap_log(block_number=200, log_index=5, tick=99))
        # older log arrives out of order
        ok = reg.update_from_v3_log(
            "base", _build_swap_log(block_number=199, log_index=99, tick=-1)
        )
        assert ok is False
        assert reg.counters()["stale_drops_total"] == 1
        st = reg.get("base", "0xabcDef0000000000000000000000000000001234")
        assert st is not None and st.tick == 99

    def test_same_block_higher_log_index_wins(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log("base", _build_swap_log(block_number=300, log_index=2, tick=1))
        reg.update_from_v3_log("base", _build_swap_log(block_number=300, log_index=3, tick=2))
        st = reg.get("base", "0xabcDef0000000000000000000000000000001234")
        assert st is not None and st.tick == 2

    def test_chain_scoped_state(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log("base", _build_swap_log(tick=11))
        reg.update_from_v3_log("arbitrum", _build_swap_log(tick=22))
        assert reg.get("base", "0xabcDef0000000000000000000000000000001234").tick == 11
        assert reg.get("arbitrum", "0xabcDef0000000000000000000000000000001234").tick == 22
        assert reg.pools_tracked("base") == 1
        assert reg.pools_tracked("arbitrum") == 1
        assert reg.pools_tracked() == 2

    def test_get_unknown_chain_returns_none(self):
        reg = PoolPriceStateRegistry()
        assert reg.get("optimism", "0xdeadbeef") is None

    def test_snapshot_schema(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log(
            "base", _build_swap_log(block_number=500, pool_address="0x" + "aa" * 20)
        )
        reg.update_from_v3_log(
            "base", _build_swap_log(block_number=501, pool_address="0x" + "bb" * 20)
        )
        snap = reg.snapshot()
        assert snap["schema_version"] == "m7.e1.51.slice2.pool_price_state.v2"
        assert snap["captured_at"].endswith("Z")
        assert snap["total_pools_tracked"] == 2
        assert snap["total_v3_pools_tracked"] == 2
        assert snap["total_v2_pools_tracked"] == 0
        assert "base" in snap["chains"]
        assert snap["chains"]["base"]["pools_tracked"] == 2
        assert snap["chains"]["base"]["v3_pools_tracked"] == 2
        assert snap["chains"]["base"]["v2_pools_tracked"] == 0
        assert snap["chains"]["base"]["latest_block"] == 501
        assert snap["counters"]["updates_total"] == 2
        assert snap["counters"]["decode_errors_total"] == 0

    def test_reset(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log("base", _build_swap_log())
        reg.reset()
        assert reg.pools_tracked() == 0
        assert reg.counters()["updates_total"] == 0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def setup_method(self):
        reset_registry_for_tests()

    def test_singleton_identity(self):
        a = get_registry()
        b = get_registry()
        assert a is b

    def test_reset_for_tests_yields_fresh_singleton(self):
        a = get_registry()
        a.update_from_v3_log("base", _build_swap_log())
        assert a.pools_tracked() == 1
        reset_registry_for_tests()
        b = get_registry()
        assert b is not a
        assert b.pools_tracked() == 0


# ---------------------------------------------------------------------------
# V2 Sync — slice-2
# ---------------------------------------------------------------------------

def _build_sync_log(
    *,
    pool_address: str = "0xV2pooL00000000000000000000000000000F00d1",
    block_number: int = 9_000_000,
    log_index: int = 3,
    reserve0: int = 1_000_000_000_000,  # 1e12 (6-dec stable units)
    reserve1: int = 500_000_000_000_000_000,  # 0.5e18 (18-dec)
) -> dict:
    data_hex = _u256_hex(reserve0) + _u256_hex(reserve1)
    return {
        "address": pool_address,
        "blockNumber": block_number,
        "logIndex": log_index,
        "data": "0x" + data_hex,
        "transactionHash": "0x" + "22" * 32,
    }


class TestV2Decode:
    def test_decode_well_formed_sync(self):
        log = _build_sync_log()
        state = decode_v2_sync_log_state(log, chain="base")
        assert state is not None
        assert isinstance(state, V2PoolState)
        assert state.reserve0 == 1_000_000_000_000
        assert state.reserve1 == 500_000_000_000_000_000
        assert state.block_number == 9_000_000
        assert state.log_index == 3
        assert state.chain == "base"

    def test_decode_short_payload_returns_none(self):
        log = {"address": "0xv2", "blockNumber": 1, "logIndex": 0, "data": "0x" + "ab" * 16}
        assert decode_v2_sync_log_state(log, chain="base") is None

    def test_decode_both_zero_reserves_rejected(self):
        log = _build_sync_log(reserve0=0, reserve1=0)
        assert decode_v2_sync_log_state(log, chain="base") is None

    def test_uint112_mask_applied(self):
        # Pollute the high bits of the 32B word — must be masked off.
        big0 = (1 << 200) | 12345
        big1 = (1 << 250) | 67890
        log = _build_sync_log(reserve0=big0, reserve1=big1)
        state = decode_v2_sync_log_state(log, chain="base")
        assert state is not None
        mask = (1 << 112) - 1
        assert state.reserve0 == big0 & mask
        assert state.reserve1 == big1 & mask

    def test_decode_address_lowercased(self):
        log = _build_sync_log(pool_address="0xABCDEF0000000000000000000000000000005678")
        state = decode_v2_sync_log_state(log, chain="base")
        assert state is not None
        assert state.pool_address == "0xabcdef0000000000000000000000000000005678"

    def test_decode_missing_data_returns_none(self):
        assert decode_v2_sync_log_state({"address": "0xv2"}, chain="base") is None


class TestV2Registry:
    def setup_method(self):
        reset_registry_for_tests()

    def test_update_from_v2_log_stores_state(self):
        reg = PoolPriceStateRegistry()
        ok = reg.update_from_v2_log("base", _build_sync_log())
        assert ok is True
        assert reg.pools_tracked("base") == 1
        assert reg.counters()["v2_updates_total"] == 1
        assert reg.counters()["v2_decode_errors_total"] == 0

    def test_update_from_malformed_v2_log_increments_error_counter(self):
        reg = PoolPriceStateRegistry()
        ok = reg.update_from_v2_log("base", {"address": "0x0", "data": "0x"})
        assert ok is False
        assert reg.counters()["v2_decode_errors_total"] == 1
        assert reg.pools_tracked() == 0

    def test_get_v2_returns_latest(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v2_log("base", _build_sync_log(block_number=100, log_index=1, reserve0=10, reserve1=20))
        reg.update_from_v2_log("base", _build_sync_log(block_number=101, log_index=0, reserve0=30, reserve1=40))
        st = reg.get_v2("base", "0xV2pooL00000000000000000000000000000F00d1".lower())
        assert st is not None
        assert (st.reserve0, st.reserve1) == (30, 40)
        assert st.block_number == 101

    def test_v2_stale_log_dropped(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v2_log("base", _build_sync_log(block_number=200, log_index=5, reserve0=99, reserve1=99))
        ok = reg.update_from_v2_log("base", _build_sync_log(block_number=199, log_index=99, reserve0=1, reserve1=1))
        assert ok is False
        assert reg.counters()["v2_stale_drops_total"] == 1
        st = reg.get_v2("base", "0xV2pooL00000000000000000000000000000F00d1".lower())
        assert st is not None and st.reserve0 == 99

    def test_v3_and_v2_coexist_independent(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log("base", _build_swap_log())
        reg.update_from_v2_log("base", _build_sync_log())
        assert reg.pools_tracked("base") == 2
        assert reg.counters()["updates_total"] == 1
        assert reg.counters()["v2_updates_total"] == 1
        # Both retrievable independently
        assert reg.get("base", "0xabcDef0000000000000000000000000000001234") is not None
        assert reg.get_v2("base", "0xV2pooL00000000000000000000000000000F00d1".lower()) is not None
        # Cross-getters return None
        assert reg.get_v2("base", "0xabcDef0000000000000000000000000000001234") is None
        assert reg.get("base", "0xV2pooL00000000000000000000000000000F00d1".lower()) is None

    def test_v2_reset_clears(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v2_log("base", _build_sync_log())
        reg.reset()
        assert reg.pools_tracked() == 0
        assert reg.counters()["v2_updates_total"] == 0

    def test_snapshot_with_v2_and_v3(self):
        reg = PoolPriceStateRegistry()
        reg.update_from_v3_log("base", _build_swap_log(block_number=500))
        reg.update_from_v2_log("base", _build_sync_log(block_number=600))
        snap = reg.snapshot()
        assert snap["total_pools_tracked"] == 2
        assert snap["total_v3_pools_tracked"] == 1
        assert snap["total_v2_pools_tracked"] == 1
        assert snap["chains"]["base"]["pools_tracked"] == 2
        assert snap["chains"]["base"]["v3_pools_tracked"] == 1
        assert snap["chains"]["base"]["v2_pools_tracked"] == 1
        assert snap["chains"]["base"]["latest_block"] == 600


# ---------------------------------------------------------------------------
# Hot-lane sink (slice-3)
# ---------------------------------------------------------------------------

from m7.orderflow.pool_price_state import feed_raw_logs  # noqa: E402


class TestFeedRawLogs:
    def setup_method(self):
        reset_registry_for_tests()

    def test_dispatches_v3_and_v2(self):
        out = feed_raw_logs("base", [_build_swap_log(), _build_sync_log()])
        assert out == {"v3_updates": 1, "v2_updates": 1, "skipped": 0}
        reg = get_registry()
        assert reg.pools_tracked() == 2

    def test_skips_unknown_payload_size(self):
        bad = {"address": "0xabc", "blockNumber": 1, "logIndex": 0, "data": "0x" + "ab" * 16}
        out = feed_raw_logs("base", [bad])
        assert out == {"v3_updates": 0, "v2_updates": 0, "skipped": 1}
        assert get_registry().pools_tracked() == 0

    def test_empty_logs_noop(self):
        assert feed_raw_logs("base", []) == {"v3_updates": 0, "v2_updates": 0, "skipped": 0}
        assert feed_raw_logs("base", None) == {"v3_updates": 0, "v2_updates": 0, "skipped": 0}

    def test_never_raises_on_garbage(self):
        out = feed_raw_logs("base", [None, "not a dict", {}, {"data": None}])
        assert out["v3_updates"] == 0
        assert out["v2_updates"] == 0
        assert out["skipped"] == 4

    def test_mixed_valid_and_garbage(self):
        out = feed_raw_logs("base", [_build_swap_log(), {}, _build_sync_log(), None])
        assert out["v3_updates"] == 1
        assert out["v2_updates"] == 1
        assert out["skipped"] == 2

    def test_hexbytes_data_field_decoded(self):
        """E1.51 fix: web3 v6 eth.get_logs() returns log['data'] as HexBytes
        (bytes subclass). feed_raw_logs must not raise TypeError on
        .startswith('0x') and must successfully update the registry."""
        class HexBytes(bytes):
            """Minimal web3 HexBytes stub."""
            def hex(self, *a, **kw):
                return super().hex(*a, **kw)

        swap = _build_swap_log()
        # Replace str data with HexBytes equivalent
        raw_hex = swap["data"]
        hex_no_prefix = raw_hex[2:] if raw_hex.startswith("0x") else raw_hex
        swap["data"] = HexBytes(bytes.fromhex(hex_no_prefix))
        out = feed_raw_logs("base", [swap])
        assert out["v3_updates"] == 1, "HexBytes data must decode as V3 update"
        assert out["skipped"] == 0

    def test_hexbytes_v2_data_field_decoded(self):
        """E1.51 fix: same HexBytes normalization for V2 Sync logs."""
        class HexBytes(bytes):
            def hex(self, *a, **kw):
                return super().hex(*a, **kw)

        sync = _build_sync_log()
        raw_hex = sync["data"]
        hex_no_prefix = raw_hex[2:] if raw_hex.startswith("0x") else raw_hex
        sync["data"] = HexBytes(bytes.fromhex(hex_no_prefix))
        out = feed_raw_logs("base", [sync])
        assert out["v2_updates"] == 1, "HexBytes data must decode as V2 update"
        assert out["skipped"] == 0

    def test_attributedict_mapping_not_dict(self):
        """E1.51 Root Cause 3 fix: web3 AttributeDict inherits Mapping but NOT dict.
        isinstance(lg, dict) is False for AttributeDict → data_hex was always None
        → every log silently skipped. Fix: isinstance(lg, Mapping) covers both."""
        from collections.abc import Mapping as AbcMapping

        class FakeAttributeDict(AbcMapping):
            """Minimal web3 AttributeDict stub — Mapping but NOT dict subclass."""
            def __init__(self, data):
                self._data = data

            def __getitem__(self, key):
                return self._data[key]

            def __iter__(self):
                return iter(self._data)

            def __len__(self):
                return len(self._data)

            def get(self, key, default=None):
                return self._data.get(key, default)

        assert not isinstance(FakeAttributeDict({}), dict), "precondition: not a dict"

        # Build a V3 Swap log wrapped in FakeAttributeDict
        swap = _build_swap_log()
        fake_log = FakeAttributeDict(swap)
        out = feed_raw_logs("base", [fake_log])
        assert out["v3_updates"] == 1, "Mapping (non-dict) log must be processed"
        assert out["skipped"] == 0

