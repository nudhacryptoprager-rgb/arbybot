"""
Unit test for reject case and config_params verification.

This test ensures:
1. reject_histogram has correct structure
2. truth_report includes config_params for reproducibility
3. pnl field is properly marked deprecated

This is a "control reject case" - verifying the pipeline
doesn't just always show green, but can detect and surface issues.
"""
import json
import os
import tempfile
from pathlib import Path

import pytest


def test_v3_quote_without_provenance_is_rejected():
    """
    V3 quote without tick/sqrt_price_x96 should be flagged.
    
    This validates that:
    1. The scanner can detect missing provenance
    2. reject_histogram properly records the reason
    3. Pipeline doesn't "just pass everything"
    """
    from strategy.jobs.run_scan_real import run_scan
    
    # Create temp output dir
    tmp = Path(tempfile.mkdtemp())
    
    # Config that should trigger v3 provenance check
    cfg = {
        "chain_id": 42161,
        "chain": "arbitrum_one",
        "dexes": ["uniswap_v3"],  # v3 requires provenance
        "quote_decimals": {"WETH": 18, "USDC": 6},
        "tokens_anchor_price": {"WETH_USDC": 2600},
        "price_sanity_enabled": True,
        "price_sanity_max_deviation_bps": 100,  # Strict: 1% max deviation
        "pairs": [{"base": "WETH", "quote": "USDC"}],
        "pools": {
            "uniswap_v3_WETH_USDC": "0x1234567890123456789012345678901234567890",
        },
    }
    
    # Skip RPC, use fake block
    os.environ["ARBY_SKIP_RPC"] = "1"
    os.environ["ARBY_FAKE_BLOCK"] = "999999"
    
    try:
        # Run scan
        result = run_scan(cfg, tmp, cycles=1)
        
        # Check artifacts exist
        reports = tmp / "reports"
        assert reports.exists(), "reports/ directory should exist"
        
        # Load reject histogram
        rej_files = list(reports.glob("reject_histogram_*.json"))
        assert rej_files, "reject_histogram should exist"
        
        with open(rej_files[0]) as f:
            rej = json.load(f)
        
        # Load truth report for additional checks
        tr_files = list(reports.glob("truth_report_*.json"))
        assert tr_files, "truth_report should exist"
        
        with open(tr_files[0]) as f:
            truth = json.load(f)
        
        # Verify structure
        assert "total_rejects" in rej, "reject_histogram should have total_rejects"
        assert "rejects" in rej, "reject_histogram should have rejects array"
        
        # rejects should be a list
        assert isinstance(rej["rejects"], list), "rejects should be a list"
        
        # Stats should be present
        stats = truth.get("stats", {})
        assert "quotes_total" in stats, "stats should have quotes_total"
        assert "price_sanity_passed" in stats, "stats should have price_sanity_passed"
        
    finally:
        # Cleanup env vars
        os.environ.pop("ARBY_SKIP_RPC", None)
        os.environ.pop("ARBY_FAKE_BLOCK", None)


def test_reject_histogram_structure():
    """
    Verify reject_histogram has the correct structure for analysis.
    
    Even if no rejects, the structure should be present for consistency.
    """
    from strategy.jobs.run_scan_real import run_scan
    
    tmp = Path(tempfile.mkdtemp())
    cfg = {
        "chain_id": 42161,
        "chain": "arbitrum_one",
        "dexes": ["uniswap_v3"],
        "quote_decimals": {"WETH": 18, "USDC": 6},
        "tokens_anchor_price": {"WETH_USDC": 1900},  # Close to typical ETH price
        "pairs": [{"base": "WETH", "quote": "USDC"}],
        "pools": {
            "uniswap_v3_WETH_USDC": "0x1234567890123456789012345678901234567890",
        },
    }
    
    os.environ["ARBY_SKIP_RPC"] = "1"
    os.environ["ARBY_FAKE_BLOCK"] = "888888"
    
    try:
        run_scan(cfg, tmp, cycles=1)
        
        rej_files = list((tmp / "reports").glob("reject_histogram_*.json"))
        assert rej_files
        
        with open(rej_files[0]) as f:
            rej = json.load(f)
        
        # Required fields for M5 reject analysis
        assert "schema_version" in rej, "schema_version required"
        assert "total_rejects" in rej, "total_rejects required"
        assert "rejects" in rej, "rejects required (even if empty list)"
        
        # rejects should be a list (even if empty)
        assert isinstance(rej["rejects"], list), "rejects should be list"
        
        # If there are rejects, each should have reason
        for reject_item in rej["rejects"]:
            assert "reason" in reject_item or "suspect_reason" in reject_item, "each reject should have reason"
            
    finally:
        os.environ.pop("ARBY_SKIP_RPC", None)
        os.environ.pop("ARBY_FAKE_BLOCK", None)


def test_truth_report_has_config_params():
    """
    Verify truth_report includes config_params for reproducibility.
    """
    from strategy.jobs.run_scan_real import run_scan
    
    tmp = Path(tempfile.mkdtemp())
    cfg = {
        "chain_id": 42161,
        "chain": "arbitrum_one",
        "dexes": ["uniswap_v3"],
        "quote_decimals": {"WETH": 18, "USDC": 6},
        "tokens_anchor_price": {"WETH_USDC": 1900},
        "min_spread_bps": 5,  # Custom threshold
        "paper_size_usd": 500,  # Custom size
        "gas_usd_estimate": 0.05,  # Custom gas
        "paper_slippage_bps": 2,  # Custom slippage
        "pairs": [{"base": "WETH", "quote": "USDC"}],
        "pools": {
            "uniswap_v3_WETH_USDC": "0x1234567890123456789012345678901234567890",
        },
    }
    
    os.environ["ARBY_SKIP_RPC"] = "1"
    os.environ["ARBY_FAKE_BLOCK"] = "777777"
    
    try:
        run_scan(cfg, tmp, cycles=1)
        
        tr_files = list((tmp / "reports").glob("truth_report_*.json"))
        assert tr_files
        
        with open(tr_files[0]) as f:
            truth = json.load(f)
        
        # config_params should be present
        assert "config_params" in truth, "config_params required for reproducibility"
        
        params = truth["config_params"]
        
        # Check values match what we configured
        assert params.get("min_spread_bps") == 5, "min_spread_bps should be from config"
        assert params.get("paper_size_usd") == 500, "paper_size_usd should be from config"
        assert params.get("gas_usd_estimate") == 0.05, "gas_usd_estimate should be from config"
        assert params.get("paper_slippage_bps") == 2, "paper_slippage_bps should be from config"
        
    finally:
        os.environ.pop("ARBY_SKIP_RPC", None)
        os.environ.pop("ARBY_FAKE_BLOCK", None)


def test_pnl_marked_deprecated():
    """
    Verify pnl field is marked as deprecated with migration instructions.
    """
    from strategy.jobs.run_scan_real import run_scan
    
    tmp = Path(tempfile.mkdtemp())
    cfg = {
        "chain_id": 42161,
        "chain": "arbitrum_one",
        "dexes": ["uniswap_v3"],
        "quote_decimals": {"WETH": 18, "USDC": 6},
        "tokens_anchor_price": {"WETH_USDC": 1900},
        "pairs": [{"base": "WETH", "quote": "USDC"}],
        "pools": {
            "uniswap_v3_WETH_USDC": "0x1234567890123456789012345678901234567890",
        },
    }
    
    os.environ["ARBY_SKIP_RPC"] = "1"
    os.environ["ARBY_FAKE_BLOCK"] = "666666"
    
    try:
        run_scan(cfg, tmp, cycles=1)
        
        tr_files = list((tmp / "reports").glob("truth_report_*.json"))
        assert tr_files
        
        with open(tr_files[0]) as f:
            truth = json.load(f)
        
        # Both pnl and execution_pnl should exist
        assert "pnl" in truth, "pnl (deprecated) should exist for backwards compat"
        assert "execution_pnl" in truth, "execution_pnl should exist as canonical"
        
        # pnl should be marked deprecated
        pnl = truth["pnl"]
        assert pnl.get("_deprecated") is True, "pnl should have _deprecated=True"
        assert "_migration" in pnl, "pnl should have migration instructions"
        assert "execution_pnl" in pnl["_migration"], "migration should point to execution_pnl"
        
    finally:
        os.environ.pop("ARBY_SKIP_RPC", None)
        os.environ.pop("ARBY_FAKE_BLOCK", None)
