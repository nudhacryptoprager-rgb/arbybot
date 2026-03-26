"""R28.29: Discovery productivity contract tests.

Lead audit found all 5 onboarding configs pass validate_universe with TOKENS=0
PAIRS=0, meaning they are entirely runtime-discovery-dependent. These tests lock
that observation and verify the scanner emits the metrics needed to track
productivity for such configs.

Contract:
  - discovery_runtime configs MUST pass schema validation (PASS)
  - discovery_runtime configs have TOKENS=0 / PAIRS=0 in validate_universe
  - validate_universe adds a RUNTIME_DEPENDENT warning for discovery_runtime configs
  - scan_universe.resolve_universe with universe_source=discovery_runtime returns
    stats_updates with keys needed for productivity tracking
  - Funnel metrics (pairs_count, cross_dex_pairs_count, quotes_fetched, etc.)
    must appear in stats_updates so long_scan_latest can capture discovery_coverage
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.validate_universe import validate_universe
from strategy.scan_universe import resolve_universe

# ---------------------------------------------------------------------------
# All active onboarding configs that use discovery_runtime
# ---------------------------------------------------------------------------
# R39r+: zksync/mantle/linea/scroll dormant (0 valid quotes, 0 dexes_active).
# Their onboard configs still exist but reference chains removed from chains.yaml.
# Validator correctly fails them with "Chain X not in chains.yaml".
# Only base_stage2 remains as active discovery_runtime config.
DISCOVERY_RUNTIME_CONFIGS = [
    "config/onboard_base_stage2.yaml",
]

# Dormant configs — kept for reference, not validated against chains.yaml
DORMANT_DISCOVERY_CONFIGS = [
    "config/onboard_zksync_candidate.yaml",
    "config/onboard_mantle_stage2.yaml",
    "config/onboard_linea_stage1.yaml",
    "config/onboard_scroll_stage1.yaml",
]


class TestDiscoveryConfigsValidatorClean:
    """All discovery_runtime configs pass validate_universe but have zero static pairs."""

    @pytest.mark.parametrize("config_path", DISCOVERY_RUNTIME_CONFIGS)
    def test_validator_pass(self, config_path):
        path = Path(config_path)
        if not path.exists():
            pytest.skip(f"{config_path} not found")
        result = validate_universe(path)
        assert result["status"] == "PASS", f"Expected PASS, got {result['status']}: {result['errors']}"

    @pytest.mark.parametrize("config_path", DISCOVERY_RUNTIME_CONFIGS)
    def test_zero_static_pairs(self, config_path):
        path = Path(config_path)
        if not path.exists():
            pytest.skip(f"{config_path} not found")
        result = validate_universe(path)
        summary = result.get("summary", {})
        assert summary.get("unique_pairs_count", 0) == 0, \
            f"Expected 0 static pairs, got {summary.get('unique_pairs_count')}"

    @pytest.mark.parametrize("config_path", DISCOVERY_RUNTIME_CONFIGS)
    def test_runtime_dependent_warning(self, config_path):
        """validate_universe should warn that productivity depends on runtime discovery."""
        path = Path(config_path)
        if not path.exists():
            pytest.skip(f"{config_path} not found")
        result = validate_universe(path)
        warnings = result.get("warnings", [])
        assert any("RUNTIME_DEPENDENT" in w for w in warnings), \
            f"Expected RUNTIME_DEPENDENT warning, got: {warnings}"


class TestDiscoveryConfigsDiscoveryMaxPairsSet:
    """All discovery_runtime configs must have discovery_runtime_max_pairs > 0."""

    @pytest.mark.parametrize("config_path", DISCOVERY_RUNTIME_CONFIGS)
    def test_max_pairs_positive(self, config_path):
        path = Path(config_path)
        if not path.exists():
            pytest.skip(f"{config_path} not found")
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        max_pairs = config.get("discovery_runtime_max_pairs", 0)
        assert max_pairs > 0, \
            f"Expected discovery_runtime_max_pairs > 0, got {max_pairs}"


class TestResolveUniverseDiscoveryRuntime:
    """resolve_universe for discovery_runtime returns productivity-trackable stats."""

    def test_returns_pairs_count_in_stats(self):
        """Stats must include pairs_count for productivity tracking."""
        mock_resolved = [MagicMock(), MagicMock()]
        mock_stats = MagicMock()
        mock_stats.to_dict.return_value = {"pairs_evaluated": 10, "pairs_resolved": 3, "cross_dex_pairs_count": 2}
        mock_pair_configs = [MagicMock(), MagicMock()]

        cfg = {
            "chain": "zksync",
            "universe_source": "discovery_runtime",
            "discovery_runtime_max_pairs": 30,
        }
        with patch("discovery.runtime.resolve_runtime_pairs", return_value=(mock_resolved, mock_stats)), \
             patch("discovery.runtime.runtime_pairs_to_pair_configs", return_value=mock_pair_configs):
            result = resolve_universe(
                config=cfg,
                chain_key="zksync",
                dexes_list=["uniswap_v3", "pancakeswap_v3"],
                run_kind="COVERAGE",
                cap_switches={},
            )
        assert result["pairs_list"] is not None
        assert len(result["pairs_list"]) == 2
        stats = result["stats_updates"]
        assert stats["universe_source"] == "discovery_runtime"
        assert "discovery_runtime_pairs_count" in stats
        assert stats["discovery_runtime_pairs_count"] == 2

    def test_stats_strategy_mode_assigned(self):
        """Strategy mode must be set for productivity categorization."""
        mock_resolved = [MagicMock()]
        mock_stats = MagicMock()
        mock_stats.to_dict.return_value = {"pairs_evaluated": 5, "pairs_resolved": 2, "cross_dex_pairs_count": 1}
        mock_pair_configs = [MagicMock()]

        cfg = {
            "chain": "base",
            "universe_source": "discovery_runtime",
            "discovery_runtime_max_pairs": 20,
        }
        with patch("discovery.runtime.resolve_runtime_pairs", return_value=(mock_resolved, mock_stats)), \
             patch("discovery.runtime.runtime_pairs_to_pair_configs", return_value=mock_pair_configs):
            result = resolve_universe(
                config=cfg,
                chain_key="base",
                dexes_list=["uniswap_v3", "aerodrome_v3"],
                run_kind="COVERAGE",
                cap_switches={},
            )
        assert "strategy_mode" in result["stats_updates"]


class TestEnvFlagEnabledCanonical:
    """Verify core.env.env_flag_enabled is the single canonical implementation."""

    def test_import_from_core(self):
        from core.env import env_flag_enabled
        assert callable(env_flag_enabled)

    @pytest.mark.parametrize("value,expected", [
        ("1", True), ("true", True), ("yes", True), ("on", True),
        ("TRUE", True), ("Yes", True), ("ON", True),
        ("0", False), ("false", False), ("no", False), ("", False),
    ])
    def test_truthy_values(self, monkeypatch, value, expected):
        from core.env import env_flag_enabled
        monkeypatch.setenv("_TEST_FLAG", value)
        assert env_flag_enabled("_TEST_FLAG") is expected

    def test_missing_env_var(self, monkeypatch):
        from core.env import env_flag_enabled
        monkeypatch.delenv("_TEST_FLAG", raising=False)
        assert env_flag_enabled("_TEST_FLAG") is False

    def test_quotes_uses_canonical(self):
        """strategy.quote_policy uses core.env.env_flag_enabled (moved from quotes.py)."""
        from strategy.quote_policy import _env_flag_enabled as _flag
        from core.env import env_flag_enabled
        assert _flag is env_flag_enabled

    def test_run_scan_real_uses_canonical(self):
        """strategy.jobs.run_scan_real._env_flag_enabled must be the core.env version."""
        from strategy.jobs.run_scan_real import _env_flag_enabled
        from core.env import env_flag_enabled
        assert _env_flag_enabled is env_flag_enabled


class TestSlot0V3NoDuplicate:
    """read_slot0_v3 must only exist in strategy.quotes (canonical), not in strategy.infra."""

    def test_infra_has_no_read_slot0(self):
        """strategy.infra must NOT export read_slot0_v3 (removed R28.29 dead code)."""
        import strategy.infra
        assert not hasattr(strategy.infra, "read_slot0_v3"), \
            "read_slot0_v3 should be removed from strategy.infra (dead code)"

    def test_quotes_has_read_slot0(self):
        """strategy.quotes must export read_slot0_v3 (canonical with multicall cache)."""
        from strategy.quotes import read_slot0_v3
        assert callable(read_slot0_v3)
