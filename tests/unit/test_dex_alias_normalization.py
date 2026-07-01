"""Regression: DexScreener aliases with enabled adapters must not be unknown_alias."""
from __future__ import annotations

from pathlib import Path

import yaml

from m8.discovery.dex_coverage_gate import classify_dex_support_status
from m8.discovery.dexscreener_aerodrome_resolver import resolve_aerodrome_dex_variant
from m8.discovery.dexscreener_hints import _pair_to_hint
from m8.discovery.pool_hints import normalize_dex_id


def _base_config() -> dict:
    path = Path("config/exotic_base_anchor.yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _pair(dex_id: str, **extra) -> dict:
    base = {
        "chainId": "base",
        "dexId": dex_id,
        "pairAddress": "0x" + "a" * 40,
        "baseToken": {"address": "0x" + "b" * 40},
        "quoteToken": {"address": "0x" + "c" * 40},
        "liquidity": {"usd": 1200},
        "volume": {"h24": 50},
        "pairCreatedAt": 1_700_000_000_000,
    }
    base.update(extra)
    return base


def test_enabled_adapter_aliases_are_not_unknown():
    cfg = _base_config()
    dexes = cfg.get("dexes") or {}
    enabled = [did for did, row in dexes.items() if row.get("enabled", True)]
    raw_aliases = [
        "uniswap_v2",
        "uniswap_v3",
        "uniswap",
        "pancakeswap_v3",
        "pancakeswap",
        "sushiswap_v2",
        "sushiswap",
        "baseswap_v2",
        "baseswap",
        "aerodrome",
        "aerodrome-slipstream",
    ]
    for raw in raw_aliases:
        internal, status = classify_dex_support_status(
            source="dexscreener",
            raw_dex_id=raw,
            config=cfg,
        )
        assert status != "unknown_alias", f"{raw} -> {internal} classified {status}"
        assert internal in enabled or internal in dexes, f"{raw} -> {internal} not in config"


def test_pair_to_hint_maps_versioned_dex_ids_supported():
    cfg = _base_config()
    for dex_id in ("uniswap_v2", "pancakeswap_v3", "sushiswap_v2", "baseswap_v2"):
        hint = _pair_to_hint(
            _pair(dex_id),
            chain="base",
            focus_token="0x" + "b" * 40,
            max_recall=True,
            dex_config=cfg,
        )
        assert hint is not None, dex_id
        assert hint.raw.get("support_status") == "supported", dex_id


def test_aerodrome_slipstream_labels_resolve():
    dex_id, reason = resolve_aerodrome_dex_variant(
        _pair("aerodrome", labels=["v2", "slipstream"]),
        raw_dex_id="aerodrome",
        normalized_default="aerodrome",
    )
    assert dex_id == "aerodrome_slipstream"
    assert reason == "labels_slipstream"


def test_normalize_dex_id_passes_through_internal_names():
    assert normalize_dex_id("dexscreener", "pancakeswap_v3") == "pancakeswap_v3"
    assert normalize_dex_id("dexscreener", "totally-new-dex") == "totally_new_dex"
