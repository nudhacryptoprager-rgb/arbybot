#!/usr/bin/env python3
"""
Tests for scripts/lint_readiness.py

v3.2.23: Add tests for --config flag and core lint functions.
"""

import pytest
import tempfile
from pathlib import Path

# Import the module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from scripts.lint_readiness import (
    load_coverage_config,
    check_chain_readiness,
)


class TestLoadCoverageConfig:
    """Tests for load_coverage_config function."""
    
    def test_load_minimal_config(self, tmp_path: Path):
        """Test loading a minimal coverage config."""
        config = tmp_path / "test_config.yaml"
        config.write_text("""
chain: test_chain
pairs:
  - WETH/USDC
  - WBTC/USDT
dexes:
  - uniswap_v3
  - sushiswap
""")
        
        chain, symbols, dex_ids = load_coverage_config(config)
        
        assert chain == "test_chain"
        assert symbols == {"WETH", "USDC", "WBTC", "USDT"}
        assert dex_ids == ["uniswap_v3", "sushiswap"]
    
    def test_load_config_empty_pairs(self, tmp_path: Path):
        """Test loading config with no pairs."""
        config = tmp_path / "empty_config.yaml"
        config.write_text("""
chain: linea
pairs: []
dexes:
  - lynex_v3
""")
        
        chain, symbols, dex_ids = load_coverage_config(config)
        
        assert chain == "linea"
        assert symbols == set()
        assert dex_ids == ["lynex_v3"]
    
    def test_load_config_no_dexes(self, tmp_path: Path):
        """Test loading config without dexes key."""
        config = tmp_path / "no_dexes.yaml"
        config.write_text("""
chain: mantle
pairs:
  - WMNT/USDC
""")
        
        chain, symbols, dex_ids = load_coverage_config(config)
        
        assert chain == "mantle"
        assert symbols == {"WMNT", "USDC"}
        assert dex_ids == []


class TestCheckChainReadiness:
    """Tests for check_chain_readiness function."""
    
    def test_ready_chain(self):
        """Test chain that is fully ready."""
        symbols = {"WETH", "USDC"}
        tokens = {"WETH": "0x...", "USDC": "0x...", "WBTC": "0x..."}
        dexes = [
            {"dex_id": "uniswap_v3", "factory": "0xfactory", "quoter": "0xquoter"},
        ]
        
        result = check_chain_readiness("test_chain", symbols, tokens, dexes)
        
        assert result["ready"] is True
        assert result["missing_tokens"] == []
        assert result["issues"] == []
    
    def test_missing_tokens(self):
        """Test chain with missing tokens."""
        symbols = {"WETH", "USDC", "WBTC"}
        tokens = {"WETH": "0x..."}  # Missing USDC, WBTC
        dexes = [
            {"dex_id": "uniswap_v3", "factory": "0xfactory", "quoter": "0xquoter"},
        ]
        
        result = check_chain_readiness("test_chain", symbols, tokens, dexes)
        
        assert result["ready"] is False
        assert sorted(result["missing_tokens"]) == ["USDC", "WBTC"]
        assert any("Missing 2 tokens" in issue for issue in result["issues"])
    
    def test_missing_factory(self):
        """Test chain with DEX missing factory."""
        symbols = {"WETH"}
        tokens = {"WETH": "0x..."}
        dexes = [
            {"dex_id": "broken_dex", "quoter": "0xquoter"},  # No factory
        ]
        
        result = check_chain_readiness("test_chain", symbols, tokens, dexes)
        
        assert result["ready"] is False
        assert any("missing factory" in issue for issue in result["issues"])
    
    def test_missing_quoter(self):
        """Test chain with DEX missing quoter."""
        symbols = {"WETH"}
        tokens = {"WETH": "0x..."}
        dexes = [
            {"dex_id": "no_quoter_dex", "factory": "0xfactory"},  # No quoter
        ]
        
        result = check_chain_readiness("test_chain", symbols, tokens, dexes)
        
        assert result["ready"] is False
        assert any("missing quoter" in issue for issue in result["issues"])
    
    def test_no_dexes(self):
        """Test chain with no DEXes configured."""
        symbols = {"WETH"}
        tokens = {"WETH": "0x..."}
        dexes = []
        
        result = check_chain_readiness("test_chain", symbols, tokens, dexes)
        
        assert result["ready"] is False
        assert any("No DEXes configured" in issue for issue in result["issues"])
    
    def test_quoter_v2_acceptable(self):
        """Test that quoter_v2 is accepted as alternative to quoter."""
        symbols = {"WETH"}
        tokens = {"WETH": "0x..."}
        dexes = [
            {"dex_id": "v2_dex", "factory": "0xfactory", "quoter_v2": "0xquoter_v2"},
        ]
        
        result = check_chain_readiness("test_chain", symbols, tokens, dexes)
        
        # quoter_v2 should be valid
        quoter_issues = [i for i in result["issues"] if "quoter" in i.lower()]
        assert quoter_issues == [], f"Unexpected quoter issues: {quoter_issues}"
