"""Tests for Aerodrome DexScreener variant resolver."""
from __future__ import annotations

from m8.discovery.dexscreener_aerodrome_resolver import resolve_aerodrome_dex_variant


def test_aerodrome_stable_labels():
    dex_id, reason = resolve_aerodrome_dex_variant(
        {"labels": ["stable", "v2"]},
        raw_dex_id="aerodrome",
        normalized_default="aerodrome",
    )
    assert dex_id == "aerodrome_v2_stable"
    assert reason == "labels_stable"
