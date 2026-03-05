# PATH: tests/unit/test_suggest_anchor_updates.py
"""
Unit tests for scripts/suggest_anchor_updates.py

Uses synthetic fixtures, NOT real data/runs/** artifacts.
"""

import json
import pytest
from pathlib import Path
from typing import Any
from unittest.mock import patch


# Import the module functions
from scripts.suggest_anchor_updates import (
    normalize_pair_key,
    parse_pair_string,
    is_outlier,
    extract_prices,
    compute_anchor_suggestions,
    PriceEvidence,
)


class TestNormalizePairKey:
    """Tests for normalize_pair_key function."""
    
    def test_simple_pair(self):
        assert normalize_pair_key("WETH", "USDC") == "WETH_USDC"
    
    def test_lowercase_converted_to_upper(self):
        assert normalize_pair_key("weth", "usdc") == "WETH_USDC"
    
    def test_mixed_case(self):
        assert normalize_pair_key("WeTh", "UsDc") == "WETH_USDC"


class TestParsePairString:
    """Tests for parse_pair_string function."""
    
    def test_slash_separator(self):
        assert parse_pair_string("ARB/DAI") == ("ARB", "DAI")
    
    def test_underscore_separator(self):
        assert parse_pair_string("ARB_DAI") == ("ARB", "DAI")
    
    def test_lowercase_converted(self):
        assert parse_pair_string("arb/dai") == ("ARB", "DAI")
    
    def test_whitespace_stripped(self):
        assert parse_pair_string(" ARB / DAI ") == ("ARB", "DAI")


class TestIsOutlier:
    """Tests for is_outlier function."""
    
    def test_not_outlier_in_tight_range(self):
        prices = [100.0, 101.0, 99.0, 100.5, 99.5]
        assert is_outlier(100.0, prices) is False
    
    def test_outlier_too_high(self):
        prices = [100.0, 101.0, 99.0, 100.5, 99.5]
        assert is_outlier(5000.0, prices) is True  # 50x median
    
    def test_outlier_too_low(self):
        prices = [100.0, 101.0, 99.0, 100.5, 99.5]
        assert is_outlier(1.0, prices) is True  # 0.01x median
    
    def test_insufficient_data_no_outlier(self):
        prices = [100.0, 5000.0]  # Only 2 prices
        assert is_outlier(100.0, prices) is False


class TestExtractPrices:
    """Tests for extract_prices function."""
    
    def test_extracts_from_quotes_sample(self):
        scan = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2100.5"},
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2101.0"},
            ]
        }
        rh = {"rejects": [], "price_sanity_samples": []}
        
        result = extract_prices(scan, rh)
        
        assert "WETH_USDC" in result
        assert len(result["WETH_USDC"]) == 2
        assert all(e.source == "PASS" for e in result["WETH_USDC"])
    
    def test_extracts_from_rejects_price_sanity_failed(self):
        scan = {"quotes_sample": []}
        rh = {
            "rejects": [
                {"pair": "ARB/DAI", "reason": "PRICE_SANITY_FAILED", "price_exact": "0.018"},
                {"pair": "ARB/DAI", "reason": "PRICE_SANITY_FAILED", "price_exact": "0.019"},
                {"pair": "ARB/DAI", "reason": "SUSPECT_LIQUIDITY", "price_exact": "999.0"},  # Should be ignored
            ],
            "price_sanity_samples": [],
        }
        
        result = extract_prices(scan, rh)
        
        assert "ARB_DAI" in result
        assert len(result["ARB_DAI"]) == 2
        assert all(e.source == "FAIL" for e in result["ARB_DAI"])
    
    def test_normalizes_case(self):
        scan = {
            "quotes_sample": [
                {"token_in": "weth", "token_out": "usdc", "price_exact": "2100.0"},
            ]
        }
        rh = {"rejects": [], "price_sanity_samples": []}
        
        result = extract_prices(scan, rh)
        
        assert "WETH_USDC" in result


class TestComputeAnchorSuggestions:
    """Tests for compute_anchor_suggestions function."""
    
    def test_prefers_pass_over_fail(self):
        evidence = {
            "WETH_USDC": [
                PriceEvidence(2100.0, "PASS"),
                PriceEvidence(2101.0, "PASS"),
                PriceEvidence(300.0, "FAIL"),  # Bad price from FAIL
            ],
        }
        
        anchors, usd_prices, stats = compute_anchor_suggestions(evidence)
        
        # Should use PASS median ~2100.5, not affected by FAIL 300.0
        assert 2099 < anchors["WETH_USDC"] < 2102
        assert stats["WETH_USDC"]["primary_source"] == "PASS"
    
    def test_uses_fail_when_no_pass(self):
        evidence = {
            "WETH_ARB": [
                PriceEvidence(20000.0, "FAIL"),
                PriceEvidence(20100.0, "FAIL"),
            ],
        }
        
        anchors, usd_prices, stats = compute_anchor_suggestions(evidence, weth_usd=2100.0)
        
        assert "WETH_ARB" in anchors
        assert stats["WETH_ARB"]["primary_source"] == "FAIL"
    
    def test_derives_usd_from_weth(self):
        evidence = {
            "WETH_USDC": [PriceEvidence(2100.0, "PASS")],
            "ARB_WETH": [PriceEvidence(0.00005, "FAIL")],  # ARB = 0.00005 * 2100 = 0.105
        }
        
        anchors, usd_prices, stats = compute_anchor_suggestions(evidence)
        
        assert abs(usd_prices["ARB"] - 0.105) < 0.01
    
    def test_derives_usd_from_weth_inverse(self):
        evidence = {
            "WETH_USDC": [PriceEvidence(2100.0, "PASS")],
            "WETH_ARB": [PriceEvidence(20000.0, "FAIL")],  # ARB = 2100/20000 = 0.105
        }
        
        anchors, usd_prices, stats = compute_anchor_suggestions(evidence)
        
        assert "ARB" in usd_prices
        assert abs(usd_prices["ARB"] - 0.105) < 0.01


class TestJsonOutput:
    """Tests for JSON output format."""
    
    def test_json_output_is_valid(self, tmp_path):
        """Test that --json produces valid JSON without any preamble."""
        # Create synthetic artifacts
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        
        scan = {
            "schema_version": "3.2.0",
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2100.0"},
            ],
        }
        rh = {
            "schema_version": "3.2.0",
            "rejects": [],
            "price_sanity_samples": [],
        }
        
        (reports_dir / "scan_test.json").write_text(json.dumps(scan))
        (reports_dir / "reject_histogram_test.json").write_text(json.dumps(rh))
        
        # Import main and run with --json
        import subprocess
        import sys
        
        result = subprocess.run(
            [sys.executable, "scripts/suggest_anchor_updates.py", "--run-dir", str(tmp_path), "--json"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        
        # Should be valid JSON
        try:
            data = json.loads(result.stdout)
            assert "anchors" in data
            assert "usd_prices" in data
            assert "statistics" in data
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON output: {e}\nOutput was: {result.stdout[:500]}")
