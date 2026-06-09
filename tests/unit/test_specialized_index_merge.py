"""Unit tests for specialized index merge and Maverick log decode."""
from __future__ import annotations

from m8.discovery.maverick_indexer import _decode_pool_created_log


def test_decode_pool_created_log_requires_indexed_pool_topic():
    assert _decode_pool_created_log({"topics": [], "data": "0x"}) is None
    assert _decode_pool_created_log({"topics": ["0xabc"], "data": "0x"}) is None
