"""
Unit tests for quoter canonical behavior (M4.2).

Verifies:
1. When quoter succeeds, slot0 failure does NOT block the quote
2. quote_source = "quoter_v2" when quoter is used
3. Algebra DEXes without quoter get ALGEBRA_NEEDS_QUOTER rejection
"""

import pytest
from unittest.mock import patch, MagicMock
import os


class TestQuoterCanonical:
    """Test quoter is canonical source when available."""
    
    @pytest.fixture
    def mock_env(self, monkeypatch, tmp_path):
        """Set up test environment."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
        
        # v3.2.11: Monkeypatch cache paths to avoid loading stale data from disk
        from pathlib import Path
        fake_cache = tmp_path / "cache"
        fake_cache.mkdir()
        monkeypatch.setattr(
            "strategy.dynamic_anchors._get_anchor_cache_path",
            lambda chain_key=None: fake_cache / f"dynamic_anchors_{chain_key or 'legacy'}.json"
        )
        monkeypatch.setattr(
            "strategy.quarantine._get_quarantine_cache_path",
            lambda chain_key=None: fake_cache / f"quarantine_{chain_key or 'legacy'}.json"
        )
        monkeypatch.setattr(
            "strategy.runtime_disabled._get_runtime_disabled_cache_path",
            lambda chain_key=None: str(fake_cache / f"runtime_disabled_{chain_key or 'legacy'}.json")
        )
        
        # v2.2.0: Reset anchor manager to avoid pollution from other tests
        from strategy.dynamic_anchors import reset_anchor_manager
        from strategy.quarantine import reset_quarantine_manager
        from strategy.runtime_disabled import clear_runtime_disabled_manager
        reset_anchor_manager()
        reset_quarantine_manager()
        clear_runtime_disabled_manager()
        
    def test_quoter_success_bypasses_slot0(self, mock_env, monkeypatch):
        """When quoter succeeds, slot0 is not even called for that quote."""
        from strategy.quotes import collect_quotes
        
        slot0_called = []
        
        def mock_slot0(pool_addr, rpc_url, block):
            slot0_called.append(pool_addr)
            return None, None  # slot0 fails
        
        def mock_quoter_v2(quoter_addr, token_in, token_out, amount_in, fee, rpc_url, block):
            return {
                "amount_out": 2500 * 10**6,  # 2500 USDC
                "gas_estimate": 150000,
                "ticks_crossed": 2,
            }
        
        monkeypatch.setattr("strategy.quotes.read_slot0_v3", mock_slot0)
        monkeypatch.setattr("strategy.quotes.read_quoter_v2", mock_quoter_v2)
        
        config = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],
            "use_quoter_v2": True,
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "tokens_anchor_price": {"WETH_USDC": 6250.0},  # v2.2.0: Match mock output
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "token_addresses": {
                "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            },
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500]},
            ],
            "pools": {
                "uniswap_v3_WETH_USDC_500": "0x1234567890123456789012345678901234567890",
            },
        }
        
        quotes, rejected, counts = collect_quotes(config, 12345)
        
        # Quoter succeeds → quote should be in quotes_sample
        assert len(quotes) == 1, f"Expected 1 quote, got {len(quotes)}: {rejected}"
        
        # quote_source should be quoter_v2
        assert quotes[0].get("quote_source") == "quoter_v2"
        
        # slot0 should NOT have been called (quoter continues early)
        assert len(slot0_called) == 0, f"slot0 was called but shouldn't be: {slot0_called}"
        
    def test_quoter_with_slot0_fails_still_works(self, mock_env, monkeypatch):
        """Even if slot0 would fail, quoter path succeeds independently."""
        from strategy.quotes import collect_quotes
        
        def mock_slot0(pool_addr, rpc_url, block):
            return None, None  # slot0 FAILS
        
        def mock_quoter_v2(quoter_addr, token_in, token_out, amount_in, fee, rpc_url, block):
            return {
                "amount_out": 1000 * 10**6,  # 1000 USDC
                "gas_estimate": 100000,
                "ticks_crossed": 1,
            }
        
        monkeypatch.setattr("strategy.quotes.read_slot0_v3", mock_slot0)
        monkeypatch.setattr("strategy.quotes.read_quoter_v2", mock_quoter_v2)
        
        config = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],
            "use_quoter_v2": True,
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "tokens_anchor_price": {"WETH_USDC": 2500.0},  # v2.2.0: Match mock output
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "token_addresses": {
                "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            },
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [3000]},
            ],
            "pools": {
                "uniswap_v3_WETH_USDC_3000": "0xABCD567890123456789012345678901234567890",
            },
        }
        
        quotes, rejected, counts = collect_quotes(config, 12345)
        
        # Quoter succeeds → quote in quotes_sample regardless of slot0
        assert len(quotes) == 1
        assert quotes[0].get("quote_source") == "quoter_v2"
        assert quotes[0].get("gas_estimate") == 100000
        assert quotes[0].get("ticks_crossed") == 1


class TestAlgebraNeedsQuoter:
    """Test that Algebra DEXes require quoter (slot0 ABI incompatible)."""
    
    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Set up test environment."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
        
    def test_algebra_without_quoter_rejected(self, mock_env, monkeypatch):
        """Algebra DEX without use_quoter_v2 should get ALGEBRA_NEEDS_QUOTER."""
        from strategy.quotes import collect_quotes
        
        def mock_slot0(pool_addr, rpc_url, block):
            # This shouldn't even be called for algebra
            raise AssertionError("slot0 should not be called for algebra")
        
        monkeypatch.setattr("strategy.quotes.read_slot0_v3", mock_slot0)
        
        config = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["camelot_v3"],  # Algebra-based
            "use_quoter_v2": False,  # Quoter disabled
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "token_addresses": {
                "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            },
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [0]},  # Algebra uses fee=0
            ],
            "pools": {
                "camelot_v3_WETH_USDC_0": "0xCAME567890123456789012345678901234567890",
            },
        }
        
        quotes, rejected, counts = collect_quotes(config, 12345)
        
        # Should be rejected with ALGEBRA_NEEDS_QUOTER
        assert len(quotes) == 0, f"Expected no quotes for algebra without quoter: {quotes}"
        assert len(rejected) == 1
        assert rejected[0].get("reason") == "ALGEBRA_NEEDS_QUOTER"
        assert counts.get("algebra_needs_quoter", 0) == 1
        
    def test_algebra_with_quoter_works(self, mock_env, monkeypatch):
        """Algebra DEX with quoter enabled should succeed."""
        from strategy.quotes import collect_quotes
        
        def mock_algebra_quoter(quoter_addr, token_in, token_out, amount_in, rpc_url, block):
            return {
                "amount_out": 999 * 10**6,  # 999 USDC
                "gas_estimate": 180000,
                "ticks_crossed": 3,
            }
        
        monkeypatch.setattr("strategy.quotes.read_algebra_quoter", mock_algebra_quoter)
        
        config = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["camelot_v3"],  # Algebra-based
            "use_quoter_v2": True,  # Quoter enabled
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "token_addresses": {
                "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            },
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [0]},  # Algebra uses fee=0
            ],
            "pools": {
                "camelot_v3_WETH_USDC_0": "0xCAME567890123456789012345678901234567890",
            },
        }
        
        quotes, rejected, counts = collect_quotes(config, 12345)
        
        # Should succeed with quoter
        assert len(quotes) == 1, f"Expected 1 quote: rejected={rejected}"
        assert quotes[0].get("quote_source") == "quoter_v2"
        assert quotes[0].get("dex_id") == "camelot_v3"


class TestSlot0FallbackForUniswapV3:
    """Test slot0 fallback still works for UniswapV3 without quoter."""
    
    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Set up test environment."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
        
    def test_slot0_path_for_uniswap_v3(self, mock_env, monkeypatch):
        """UniswapV3 without quoter falls back to slot0."""
        from strategy.quotes import collect_quotes
        
        def mock_slot0(pool_addr, rpc_url, block):
            # sqrtPriceX96 for WETH/USDC ~$2500
            return (202919, 1986710939268379567088427556864)
        
        monkeypatch.setattr("strategy.quotes.read_slot0_v3", mock_slot0)
        
        config = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],
            "use_quoter_v2": False,  # Quoter disabled - use slot0
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "token_addresses": {
                "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            },
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500]},
            ],
            "pools": {
                "uniswap_v3_WETH_USDC_500": "0x1234567890123456789012345678901234567890",
            },
        }
        
        quotes, rejected, counts = collect_quotes(config, 12345)
        
        # Should succeed via slot0 path
        assert len(quotes) == 1, f"Expected 1 quote: rejected={rejected}"
        assert quotes[0].get("quote_source") == "slot0"
        assert quotes[0].get("dex_id") == "uniswap_v3"
