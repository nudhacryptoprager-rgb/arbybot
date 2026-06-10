"""Token address normalization for M8 discovery."""
from __future__ import annotations

from m8.discovery.token_normalize import (
    TOKEN_ADDRESS_UNRESOLVED,
    is_valid_eth_address,
    normalize_token_addr_or_symbol,
    normalize_pair_addresses,
)


def test_is_valid_eth_address():
    assert is_valid_eth_address("0x4200000000000000000000000000000000000006")
    assert not is_valid_eth_address("0x420000")
    assert not is_valid_eth_address("0x833589")


def test_reject_partial_address():
    addr, sym, rej = normalize_token_addr_or_symbol("0x420000")
    assert rej == TOKEN_ADDRESS_UNRESOLVED
    assert addr is None


def test_resolve_weth_from_config():
    config = {
        "chain": "base",
        "tokens": {
            "WETH": {"address": "0x4200000000000000000000000000000000000006"},
            "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
        },
    }
    addr, sym, rej = normalize_token_addr_or_symbol("WETH", config=config)
    assert rej is None
    assert addr == "0x4200000000000000000000000000000000000006"
    assert sym == "WETH"


def test_normalize_pair_rejects_truncated():
    _, _, _, _, rej = normalize_pair_addresses(
        exotic_symbol="0x420000",
        anchor_symbol="USDC",
        config={"chain": "base", "tokens": {}},
    )
    assert rej == TOKEN_ADDRESS_UNRESOLVED
