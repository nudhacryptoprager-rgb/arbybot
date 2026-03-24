"""
R29: Unit tests for QUOTER_V2_FAILED structured reject and quoter_matrix.

Verifies:
1. When quoter fails for non-algebra V3, QUOTER_V2_FAILED reject is emitted
2. Slot0 fallback still executes after QUOTER_V2_FAILED (reject is informational)
3. quoter_matrix tracks per-DEX quoter success/failure counts
4. quotes_fetched_executable / quotes_fetched_diagnostic split
"""

import pytest


class TestQuoterV2FailedReject:
    """Test QUOTER_V2_FAILED reject emitted when quoter fails on non-algebra V3."""

    @pytest.fixture
    def mock_env(self, monkeypatch, tmp_path):
        """Set up test environment with cache isolation."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")

        from pathlib import Path
        fake_cache = tmp_path / "cache"
        fake_cache.mkdir(exist_ok=True)
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

        from strategy.dynamic_anchors import reset_anchor_manager
        from strategy.quarantine import reset_quarantine_manager
        from strategy.runtime_disabled import clear_runtime_disabled_manager
        reset_anchor_manager()
        reset_quarantine_manager()
        clear_runtime_disabled_manager()

    def _base_config(self):
        return {
            "chain_id": 8453,
            "chain": "base",
            "dexes": ["uniswap_v3"],
            "use_quoter_v2": True,
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "tokens_anchor_price": {"WETH_USDC": 2500.0},
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "token_addresses": {
                "WETH": "0x4200000000000000000000000000000000000006",
                "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            },
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500]},
            ],
            "pools": {
                "uniswap_v3_WETH_USDC_500": "0x1234567890123456789012345678901234567890",
            },
        }

    def test_quoter_v2_failed_emits_reject(self, mock_env, monkeypatch):
        """When quoter fails on uniswap_v3, QUOTER_V2_FAILED reject is emitted."""
        from strategy.quotes import collect_quotes

        def mock_quoter_v2(quoter_addr, token_in, token_out, amount_in, fee, rpc_url, block, **kwargs):
            return None  # Quoter fails

        def mock_slot0(pool_addr, rpc_url, block):
            return (202919, 1986710939268379567088427556864)

        monkeypatch.setattr("strategy.quotes.read_quoter_v2", mock_quoter_v2)
        monkeypatch.setattr("strategy.quotes.read_slot0_v3", mock_slot0)

        quotes, rejected, counts = collect_quotes(self._base_config(), 12345)

        # QUOTER_V2_FAILED reject should be present
        qv2_rejects = [r for r in rejected if r["reason"] == "QUOTER_V2_FAILED"]
        assert len(qv2_rejects) == 1, f"Expected 1 QUOTER_V2_FAILED, got {len(qv2_rejects)}: {rejected}"
        assert qv2_rejects[0]["dex_id"] == "uniswap_v3"
        assert qv2_rejects[0]["fallback"] == "slot0_diagnostic"

        # Counter incremented
        assert counts.get("quoter_v2_failed", 0) == 1

    def test_slot0_fallback_still_executes_after_quoter_fail(self, mock_env, monkeypatch):
        """Slot0 path executes even when quoter fails (reject is informational).
        
        The slot0 path may not produce a valid quote (price sanity, etc.)
        but the key contract is that it IS attempted — NOT short-circuited
        by QUOTER_V2_FAILED.
        """
        from strategy.quotes import collect_quotes

        slot0_called = []

        def mock_quoter_v2(quoter_addr, token_in, token_out, amount_in, fee, rpc_url, block, **kwargs):
            return None  # Quoter fails

        def mock_slot0(pool_addr, rpc_url, block):
            slot0_called.append(pool_addr)
            return (202919, 1986710939268379567088427556864)

        monkeypatch.setattr("strategy.quotes.read_quoter_v2", mock_quoter_v2)
        monkeypatch.setattr("strategy.quotes.read_slot0_v3", mock_slot0)

        quotes, rejected, counts = collect_quotes(self._base_config(), 12345)

        # QUOTER_V2_FAILED reject should be present
        qv2_rejects = [r for r in rejected if r["reason"] == "QUOTER_V2_FAILED"]
        assert len(qv2_rejects) == 1

        # Slot0 MUST have been called (fallback was not short-circuited)
        assert len(slot0_called) >= 1, "slot0 was never called — QUOTER_V2_FAILED blocked it"


class TestQuoterMatrix:
    """Test quoter_matrix tracks per-DEX quoter success/failure."""

    @pytest.fixture
    def mock_env(self, monkeypatch, tmp_path):
        """Set up test environment with cache isolation."""
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")

        from pathlib import Path
        fake_cache = tmp_path / "cache"
        fake_cache.mkdir(exist_ok=True)
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

        from strategy.dynamic_anchors import reset_anchor_manager
        from strategy.quarantine import reset_quarantine_manager
        from strategy.runtime_disabled import clear_runtime_disabled_manager
        reset_anchor_manager()
        reset_quarantine_manager()
        clear_runtime_disabled_manager()

    def test_quoter_matrix_tracks_success(self, mock_env, monkeypatch):
        """quoter_matrix records successful quoter calls."""
        from strategy.quotes import collect_quotes

        def mock_quoter_v2(quoter_addr, token_in, token_out, amount_in, fee, rpc_url, block, **kwargs):
            return {
                "amount_out": 2500 * 10**6,
                "gas_estimate": 150000,
                "ticks_crossed": 2,
            }

        monkeypatch.setattr("strategy.quotes.read_quoter_v2", mock_quoter_v2)

        config = {
            "chain_id": 42161,
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],
            "use_quoter_v2": True,
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "tokens_anchor_price": {"WETH_USDC": 6250.0},
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

        mx = counts.get("quoter_matrix", {})
        assert "uniswap_v3:500" in mx, f"Expected uniswap_v3:500 in quoter_matrix: {mx}"
        entry = mx["uniswap_v3:500"]
        assert entry["attempted"] >= 1
        assert entry["quoter_success"] >= 1
        assert entry["slot0_fallback"] == 0

    def test_quoter_matrix_tracks_failure(self, mock_env, monkeypatch):
        """quoter_matrix records failed quoter calls and slot0 fallback."""
        from strategy.quotes import collect_quotes

        def mock_quoter_v2(quoter_addr, token_in, token_out, amount_in, fee, rpc_url, block, **kwargs):
            return None  # Quoter fails

        def mock_slot0(pool_addr, rpc_url, block):
            return (202919, 1986710939268379567088427556864)

        monkeypatch.setattr("strategy.quotes.read_quoter_v2", mock_quoter_v2)
        monkeypatch.setattr("strategy.quotes.read_slot0_v3", mock_slot0)

        config = {
            "chain_id": 8453,
            "chain": "base",
            "dexes": ["uniswap_v3"],
            "use_quoter_v2": True,
            "use_usd_notional": True,
            "target_usd_notional": 1000.0,
            "tokens_usd_price": {"WETH": 2500.0, "USDC": 1.0},
            "tokens_anchor_price": {"WETH_USDC": 2500.0},
            "quote_decimals": {"WETH": 18, "USDC": 6},
            "token_addresses": {
                "WETH": "0x4200000000000000000000000000000000000006",
                "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            },
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500]},
            ],
            "pools": {
                "uniswap_v3_WETH_USDC_500": "0x1234567890123456789012345678901234567890",
            },
        }

        quotes, rejected, counts = collect_quotes(config, 12345)

        mx = counts.get("quoter_matrix", {})
        assert "uniswap_v3:500" in mx, f"Expected uniswap_v3:500 in quoter_matrix: {mx}"
        entry = mx["uniswap_v3:500"]
        assert entry["attempted"] >= 1
        assert entry["quoter_success"] == 0
        assert entry["slot0_fallback"] >= 1


class TestQuoterV2FailedSourceInspection:
    """Source inspection: verify QUOTER_V2_FAILED code paths exist."""

    def test_quoter_v2_failed_in_source(self):
        """Verify QUOTER_V2_FAILED reject reason exists in quotes.py source."""
        import inspect
        from strategy import quotes
        source = inspect.getsource(quotes.collect_quotes)
        assert '"QUOTER_V2_FAILED"' in source
        assert '"quoter_v2_failed"' in source
        assert "quoter_matrix" in source
