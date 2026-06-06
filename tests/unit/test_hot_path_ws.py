"""Live WS hot-path helpers."""
from __future__ import annotations

from m8.discovery.hot_path_mirror import split_token_anchor_from_event


def test_split_token_anchor_by_address_usdc_pair():
    event = {
        "token0": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1": "0xabc1234567890123456789012345678901234567",
        "token0_symbol": "",
        "token1_symbol": "",
    }
    split = split_token_anchor_from_event(event)
    assert split is not None
    assert split[0] == "0xabc1234567890123456789012345678901234567"
    assert split[2] == "USDC"
