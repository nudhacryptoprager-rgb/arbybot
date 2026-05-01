"""M7.E1.51 slice-6 — flashblocks ingest stub tests."""
from __future__ import annotations

from m7.orderflow.flashblocks_ingest import FlashblockSubscriber, consume_flashblock
from m7.orderflow.pool_price_state import get_registry, reset_registry_for_tests


def _u256_hex(val: int) -> str:
    return f"{val & ((1 << 256) - 1):064x}"


def _build_v3_log(pool: str = "0xfb" + "0" * 38) -> dict:
    sqrt = 79228162514264337593543950336
    data = _u256_hex(0) + _u256_hex(0) + _u256_hex(sqrt) + _u256_hex(1) + _u256_hex(0)
    return {
        "address": pool,
        "blockNumber": 1,
        "logIndex": 0,
        "data": "0x" + data,
        "preConfirmed": True,
    }


def setup_function(_fn):
    reset_registry_for_tests()


def test_consume_flashblock_feeds_registry():
    out = consume_flashblock("base", [_build_v3_log()])
    assert out["v3_updates"] == 1
    assert get_registry().pools_tracked() == 1


def test_consume_flashblock_handles_none():
    out = consume_flashblock("base", None)
    assert out == {"v3_updates": 0, "v2_updates": 0, "skipped": 0}


def test_consume_flashblock_empty_iterable():
    out = consume_flashblock("base", [])
    assert out == {"v3_updates": 0, "v2_updates": 0, "skipped": 0}


def test_subscriber_stub_constructs():
    s = FlashblockSubscriber("base", ws_url="wss://example/flashblocks")
    assert s.chain == "base"
    assert s.ws_url == "wss://example/flashblocks"


def test_subscriber_run_noop():
    import asyncio

    s = FlashblockSubscriber("base")
    asyncio.run(s.run())  # must not raise
