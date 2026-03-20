# PATH: tests/unit/test_scan_universe.py
"""
Contract tests for strategy/scan_universe.py.

Verifies resolve_universe() with different universe_source values,
fallback behavior, and strategy_mode assignment.
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from strategy.scan_universe import resolve_universe
from config.pairs import PairConfig


def _base_config(**overrides):
    cfg = {"chain": "arbitrum_one", "universe_source": "config"}
    cfg.update(overrides)
    return cfg


class TestResolveUniverseConfig:
    """Default config-based universe resolution."""

    def test_config_source(self):
        result = resolve_universe(
            config=_base_config(),
            chain_key="arbitrum_one",
            dexes_list=["uniswap_v3"],
            run_kind="NORMAL",
            cap_switches={},
        )
        assert result["pairs_list"] is None  # config default: let collect_quotes load
        assert result["stats_updates"]["universe_source"] == "config"
        assert result["stats_updates"]["strategy_mode"] == "TRUTH_PROBE"

    def test_same_dex_only(self):
        result = resolve_universe(
            config=_base_config(require_cross_dex=False),
            chain_key="arbitrum_one",
            dexes_list=[],
            run_kind="NORMAL",
            cap_switches={},
        )
        assert result["stats_updates"]["same_dex_only"] is True


class TestResolveUniverseIntentForbidden:
    """Intent/intent_forced must be rejected for NORMAL/COVERAGE runs."""

    def test_intent_forbidden_normal(self):
        with pytest.raises(RuntimeError, match="forbidden"):
            resolve_universe(
                config=_base_config(universe_source="intent"),
                chain_key="arbitrum_one",
                dexes_list=[],
                run_kind="NORMAL",
                cap_switches={},
            )

    def test_intent_forced_forbidden_coverage(self):
        with pytest.raises(RuntimeError, match="forbidden"):
            resolve_universe(
                config=_base_config(universe_source="intent_forced"),
                chain_key="arbitrum_one",
                dexes_list=[],
                run_kind="COVERAGE",
                cap_switches={},
            )

    def test_intent_allowed_smoke(self):
        # SMOKE runs may use intent
        result = resolve_universe(
            config=_base_config(universe_source="intent"),
            chain_key="arbitrum_one",
            dexes_list=[],
            run_kind="SMOKE",
            cap_switches={},
        )
        assert result["stats_updates"]["universe_source"] == "intent"
        assert result["stats_updates"]["strategy_mode"] == "BOOTSTRAP"


class TestResolveUniverseStrategyMode:
    """Strategy mode assignment from universe_source."""

    def test_discovery_runtime_mode(self):
        # Mock discovery_runtime to avoid actual RPC
        mock_stats = MagicMock()
        mock_stats.to_dict.return_value = {}
        mock_stats.cross_dex_pairs_count = 0
        with patch("discovery.runtime.resolve_runtime_pairs", return_value=([], mock_stats)), \
             patch("discovery.runtime.runtime_pairs_to_pair_configs", return_value=[]):
            result = resolve_universe(
                config=_base_config(universe_source="discovery_runtime"),
                chain_key="arbitrum_one",
                dexes_list=["uniswap_v3"],
                run_kind="NORMAL",
                cap_switches={},
            )
            assert result["stats_updates"]["strategy_mode"] == "DYNAMIC_VERIFIED"

    def test_intent_forced_mode(self):
        result = resolve_universe(
            config=_base_config(universe_source="intent_forced"),
            chain_key="arbitrum_one",
            dexes_list=[],
            run_kind="SMOKE",
            cap_switches={},
        )
        assert result["stats_updates"]["strategy_mode"] == "BOOTSTRAP"


class TestHotRequoteCacheContract:
    """Hot cache must preserve discovery provenance and write atomically."""

    def test_hot_cache_restores_discovery_runtime_metadata(self, tmp_path, monkeypatch):
        hot_file = tmp_path / "hot_pairs_linea.json"
        hot_file.write_text(
            """
{
  "schema": "hot_pairs_cache:v1.0",
  "chain": "linea",
  "universe_source": "discovery_runtime",
  "origin_universe_source": "discovery_runtime",
  "pairs_count": 1,
  "cross_dex_pairs_count": 1,
  "discovery_runtime_pairs_count": 1,
  "discovery_runtime_pools_resolved": 2,
  "pairs": [
    {
      "chain": "linea",
      "token_in": "WETH",
      "token_out": "USDC",
      "fee_tiers": [500, 3000],
      "display_name": "WETH/USDC",
      "pool_info": [
        {"dex": "lynex_v3", "fee": 500, "address": "0x111"},
        {"dex": "pancakeswap_v3", "fee": 500, "address": "0x222"}
      ]
    }
  ]
}
""".strip(),
            encoding="utf-8",
        )
        monkeypatch.setenv("ARBY_HOT_PAIRS_FILE", str(hot_file))
        try:
            result = resolve_universe(
                config=_base_config(chain="linea", universe_source="discovery_runtime"),
                chain_key="linea",
                dexes_list=["lynex_v3", "pancakeswap_v3"],
                run_kind="COVERAGE",
                cap_switches={},
            )
        finally:
            monkeypatch.delenv("ARBY_HOT_PAIRS_FILE", raising=False)

        assert result["stats_updates"]["universe_source"] == "hot_requote"
        assert result["stats_updates"]["hot_pairs_origin_universe_source"] == "discovery_runtime"
        assert result["stats_updates"]["strategy_mode"] == "HOT_REQUOTE"
        assert result["discovery_runtime_stats"] is not None
        assert result["discovery_runtime_stats"].cross_dex_pairs_count == 1
        assert len(result["discovery_runtime_resolved"]) == 2

    def test_hot_cache_write_is_atomic_and_carries_runtime_metadata(self):
        pair = PairConfig(
            chain="base",
            token_in="WETH",
            token_out="USDC",
            fee_tiers=[500],
            pool_info=[
                {"dex": "uniswap_v3", "fee": 500, "address": "0x111"},
                {"dex": "pancakeswap_v3", "fee": 500, "address": "0x222"},
            ],
        )
        mock_stats = MagicMock()
        mock_stats.to_dict.return_value = {"cross_dex_pairs_count": 1}

        with patch("discovery.runtime.resolve_runtime_pairs", return_value=([], mock_stats)), \
             patch("discovery.runtime.runtime_pairs_to_pair_configs", return_value=[pair]), \
             patch("strategy.scan_universe.atomic_write_json") as mock_atomic_write:
            resolve_universe(
                config=_base_config(chain="base", universe_source="discovery_runtime"),
                chain_key="base",
                dexes_list=["uniswap_v3", "pancakeswap_v3"],
                run_kind="COVERAGE",
                cap_switches={},
            )

        cache_payload = mock_atomic_write.call_args.args[1]
        assert cache_payload["origin_universe_source"] == "discovery_runtime"
        assert cache_payload["cross_dex_pairs_count"] == 1
        assert cache_payload["discovery_runtime_pairs_count"] == 1
