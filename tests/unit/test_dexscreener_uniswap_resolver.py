"""Tests for DexScreener uniswap variant resolver."""
from __future__ import annotations

from m8.discovery.dexscreener_uniswap_resolver import resolve_uniswap_dex_variant


def test_resolve_uniswap_v4_from_labels():
    pair = {"labels": ["v4"], "pairAddress": "0x" + "a" * 40}
    dex_id, reason = resolve_uniswap_dex_variant(
        pair, raw_dex_id="uniswap", normalized_default="uniswap_v3"
    )
    assert dex_id == "uniswap_v4"
    assert reason == "labels_or_raw_dex_v4"


def test_resolve_uniswap_v3_from_fee_tier():
    pair = {"pairAddress": "0x" + "b" * 40, "feeTier": 3000}
    dex_id, reason = resolve_uniswap_dex_variant(
        pair, raw_dex_id="uniswap", normalized_default="uniswap_v3"
    )
    assert dex_id == "uniswap_v3"
    assert reason == "fee_tier_hint"


def test_resolve_non_uniswap_passthrough():
    pair = {"pairAddress": "0x" + "c" * 40}
    dex_id, reason = resolve_uniswap_dex_variant(
        pair, raw_dex_id="aerodrome", normalized_default="aerodrome"
    )
    assert dex_id == "aerodrome"
    assert reason is None
