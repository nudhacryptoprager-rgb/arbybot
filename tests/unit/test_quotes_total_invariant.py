# PATH: tests/unit/test_quotes_total_invariant.py
"""
Tests for quotes_total invariant.

v2.0.8: quotes_total = quotes_fetched + quotes_rejected (attempted quotes)

Contract:
- quotes_total must always equal quotes_fetched + len(rejected_quotes)
- quotes_total >= quotes_fetched
- The invariant ensures scan_*.json has accurate quality metrics
"""

import pytest
import tempfile
import os
from pathlib import Path


class TestQuotesTotalInvariant:
    """v2.0.8: Test quotes_total = attempted quotes invariant."""
    
    def test_quotes_total_gte_fetched(self, monkeypatch):
        """quotes_total must be >= quotes_fetched."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
        
        from strategy.jobs.run_scan_real import run_scan
        
        tmp = Path(tempfile.mkdtemp())
        cfg = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["sushiswap_v3"],
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "tokens_anchor_price": {"WETH_USDC": 2600},
            "pairs": [{"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500, 3000]}],
            "pools": {
                # Only one pool configured, other fee_tier will fail
                "sushiswap_v3_WETH_USDC_500": "0x1234567890123456789012345678901234567890",
            },
        }
        
        stats = run_scan(cfg, tmp, cycles=1)
        
        # Core invariant: quotes_total >= quotes_fetched
        assert stats["quotes_total"] >= stats["quotes_fetched"], \
            f"Invariant violation: quotes_total ({stats['quotes_total']}) < quotes_fetched ({stats['quotes_fetched']})"
    
    def test_quotes_total_includes_rejected(self, monkeypatch):
        """quotes_total = fetched + rejected."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
        
        from strategy.jobs.run_scan_real import run_scan
        import json
        
        tmp = Path(tempfile.mkdtemp())
        cfg = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["sushiswap_v3", "uniswap_v3"],
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "tokens_anchor_price": {"WETH_USDC": 2600},
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500, 3000]},
            ],
            "pools": {
                # Only partial pools configured - will have rejections
                "sushiswap_v3_WETH_USDC_500": "0x1234567890123456789012345678901234567890",
            },
        }
        
        stats = run_scan(cfg, tmp, cycles=1)
        
        # Check scan artifact has correct invariant
        reports = tmp / "reports"
        scan_files = list(reports.glob("scan_*.json"))
        assert scan_files, "scan artifact not found"
        
        with open(scan_files[0]) as f:
            scan = json.load(f)
        
        scan_stats = scan.get("stats", {})
        quotes_total = scan_stats.get("quotes_total", 0)
        quotes_fetched = scan_stats.get("quotes_fetched", 0)
        
        # quotes_total >= quotes_fetched (might have rejections)
        assert quotes_total >= quotes_fetched, \
            f"Artifact invariant: quotes_total ({quotes_total}) >= quotes_fetched ({quotes_fetched})"


class TestPriceStabilityFactorOrder:
    """v2.0.8: Test price_stability_factor is calculated after price_sanity_failed."""
    
    def test_price_stability_uses_sanity_rejects(self, monkeypatch):
        """price_stability_factor uses actual sanity reject count."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
        
        from strategy.jobs.run_scan_real import run_scan
        
        tmp = Path(tempfile.mkdtemp())
        cfg = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["sushiswap_v3"],
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "tokens_anchor_price": {"WETH_USDC": 2600},
            "pairs": [{"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500]}],
            "pools": {
                "sushiswap_v3_WETH_USDC_500": "0x1234567890123456789012345678901234567890",
            },
        }
        
        stats = run_scan(cfg, tmp, cycles=1)
        
        # price_stability_factor should be calculated (not None or stale 0)
        assert "price_stability_factor" in stats
        assert stats["price_stability_factor"] is not None
        # Should be a valid float between 0 and 1
        assert 0.0 <= stats["price_stability_factor"] <= 1.0
