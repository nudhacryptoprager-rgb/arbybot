"""Tests for DexScreener-first radar fast pipeline."""
from __future__ import annotations

from m8.discovery.dexscreener_cache import get_cached_pairs, set_cached_pairs
from m8.discovery.pool_hints import PoolHint
from m8.discovery.radar_fast_pipeline import (
    build_verify_subset_tokens,
    pipeline_metrics,
    tokens_for_secondary_sources,
    ProviderTiming,
)


def _hint(tok: str, dex: str, reason: str = "token_pair_seen") -> PoolHint:
    return PoolHint(
        source="dexscreener",
        chain="base",
        dex_id=dex,
        pool_address=f"0xpool{dex}",
        token0_addr=tok,
        token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        focus_token=tok,
        radar_reason=reason,
    )


def test_build_verify_subset_multi_venue():
    tok = "0xabc0000000000000000000000000000000000001"
    hints = [_hint(tok, "uniswap_v3"), _hint(tok, "aerodrome")]
    subset = build_verify_subset_tokens(hints)
    assert tok in subset


def test_tokens_for_secondary_empty():
    tok = "0xabc0000000000000000000000000000000000001"
    secondary = tokens_for_secondary_sources([tok], [])
    assert secondary == [tok]


def test_dexscreener_cache_roundtrip(tmp_path):
    path = tmp_path / "cache.json"
    set_cached_pairs("0xtok", [{"pairAddress": "0x1"}], path=str(path), persist=True)
    assert get_cached_pairs("0xtok", path=str(path)) is not None


def test_pipeline_metrics_shape():
    m = pipeline_metrics(
        radar_fast_tokens=100,
        radar_candidates=200,
        verify_subset_size=40,
        verified_count=10,
        provider_timing={"dexscreener": ProviderTiming(calls=100, latency_s_sum=50.0)},
    )
    assert m["radar_to_verify_rate"] == 0.25
    assert m["provider_timing"]["dexscreener"]["calls"] == 100
