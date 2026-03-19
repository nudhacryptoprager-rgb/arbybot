# PATH: tests/unit/test_scan_universe.py
"""
Contract tests for strategy/scan_universe.py.

Verifies resolve_universe() with different universe_source values,
fallback behavior, and strategy_mode assignment.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from strategy.scan_universe import resolve_universe


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
