"""Tests for rolling hint artifact merge across radar phases."""
from __future__ import annotations

from m8.discovery.hint_artifact_merge import merge_hint_artifacts
from m8.discovery.pool_hints import PoolHint


def test_merge_hint_artifacts_preserves_prior_and_incoming():
    prior = {
        "hints": [
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0xaaaa",
                token0_addr="0xabc",
                token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                focus_token="0xabc",
                hint_status="VERIFIED_SECOND_POOL",
            ).to_dict()
        ],
        "sources": ["dexscreener"],
    }
    incoming = {
        "hints": [
            PoolHint(
                source="geckoterminal",
                chain="base",
                dex_id="curve_stable",
                pool_address="0xbbbb",
                token0_addr="0xabc",
                token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                focus_token="0xabc",
                hint_status="VERIFIED_SECOND_POOL",
            ).to_dict()
        ],
        "sources": ["geckoterminal"],
    }
    merged = merge_hint_artifacts(prior, incoming, chain="base")
    assert len(merged["hints"]) == 2
    assert "dexscreener" in merged["sources"]
    assert "geckoterminal" in merged["sources"]
