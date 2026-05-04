"""
Unit tests for chains.l1_cost module.

v2.1.0: Tests for L1 cost estimation with source tracking.
"""
import unittest
from unittest.mock import MagicMock, patch


class TestL1CostImports(unittest.TestCase):
    """Test that L1 cost functions can be imported."""
    
    def test_import_get_l1_cost_with_source(self):
        """get_l1_cost_with_source must be importable."""
        from chains.l1_cost import get_l1_cost_with_source
        self.assertTrue(callable(get_l1_cost_with_source))
    
    def test_import_estimate_l1_cost_from_config(self):
        """estimate_l1_cost_from_config must be importable."""
        from chains.l1_cost import estimate_l1_cost_from_config
        self.assertTrue(callable(estimate_l1_cost_from_config))
    
    def test_import_estimate_l1_cost_default(self):
        """estimate_l1_cost_default must be importable."""
        from chains.l1_cost import estimate_l1_cost_default
        self.assertTrue(callable(estimate_l1_cost_default))


class TestEstimateL1CostFromConfig(unittest.TestCase):
    """Tests for config-based L1 cost estimation."""
    
    def test_with_config_values(self):
        """Should calculate L1 cost from config parameters."""
        from chains.l1_cost import estimate_l1_cost_from_config
        
        config = {
            "l1_data_gas_units": 2000,
            "l1_gas_price_gwei": 30,
        }
        
        expected = int(2000 * 30 * 1e9)  # 60000000000000 wei
        result = estimate_l1_cost_from_config(config)
        
        self.assertEqual(result, expected)
    
    def test_with_default_fallback(self):
        """Should use defaults for missing config keys."""
        from chains.l1_cost import estimate_l1_cost_from_config, DEFAULT_L1_GAS_PRICE_GWEI
        
        # Empty config should use defaults
        result = estimate_l1_cost_from_config({})
        
        # Default: 2000 * DEFAULT_L1_GAS_PRICE_GWEI * 1e9
        expected = int(2000 * DEFAULT_L1_GAS_PRICE_GWEI * 1e9)
        self.assertEqual(result, expected)


class TestEstimateL1CostDefault(unittest.TestCase):
    """Tests for default L1 cost estimation."""
    
    def test_returns_positive_value(self):
        """Default L1 cost should be positive and reasonable."""
        from chains.l1_cost import estimate_l1_cost_default
        
        result = estimate_l1_cost_default()
        
        self.assertGreater(result, 0)
        # Should be in reasonable range: ~$0.10-$1.00 at ETH=$2000
        # 60000 gwei = 0.00006 ETH = $0.12 at $2000/ETH
        self.assertGreater(result, 1e12)  # > 1000 gwei
        self.assertLess(result, 1e16)  # < 10000000 gwei


class TestGetL1CostWithSource(unittest.TestCase):
    """Tests for get_l1_cost_with_source with source tracking."""
    
    def test_returns_default_without_w3_or_config(self):
        """Should return default source when no w3 or config provided."""
        from chains.l1_cost import get_l1_cost_with_source
        
        cost, source = get_l1_cost_with_source()
        
        self.assertGreater(cost, 0)
        self.assertEqual(source, "default")
    
    def test_returns_config_source_when_config_provided(self):
        """Should return config source when config dict provided."""
        from chains.l1_cost import get_l1_cost_with_source
        
        config = {
            "l1_data_gas_units": 1500,
            "l1_gas_price_gwei": 25,
        }
        
        cost, source = get_l1_cost_with_source(config=config)
        
        expected_cost = int(1500 * 25 * 1e9)
        self.assertEqual(cost, expected_cost)
        self.assertEqual(source, "config")
    
    def test_prefers_onchain_when_w3_provided(self):
        """Should try onchain first when w3 is provided."""
        from chains.l1_cost import get_l1_cost_with_source
        
        # Mock w3 that fails (no contract)
        mock_w3 = MagicMock()
        mock_w3.eth.contract.return_value.functions.gasEstimateL1Component.side_effect = Exception("Not found")
        
        # Should fall back to default
        cost, source = get_l1_cost_with_source(w3=mock_w3)
        
        # Should be default since onchain failed and no config
        self.assertEqual(source, "default")
    
    def test_source_is_onchain_when_nodeinterface_works(self):
        """Should return onchain source when NodeInterface query succeeds."""
        from chains.l1_cost import get_l1_cost_with_source
        
        # Mock successful NodeInterface response
        mock_w3 = MagicMock()
        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract
        mock_w3.to_checksum_address = lambda x: x
        
        # Mock gasEstimateL1Component return value
        # (gasEstimateForL1, baseFee, l1BaseFeeEstimate)
        mock_contract.functions.gasEstimateL1Component.return_value.call.return_value = (
            1000,  # gasEstimateForL1
            50_000_000_000,  # baseFee (50 gwei)
            30_000_000_000,  # l1BaseFeeEstimate (30 gwei)
        )
        
        cost, source = get_l1_cost_with_source(w3=mock_w3)
        
        # cost = 1000 * 50_000_000_000 = 50_000_000_000_000 wei
        expected = 1000 * 50_000_000_000
        self.assertEqual(cost, expected)
        self.assertEqual(source, "onchain")


class TestGetL1CostForChain(unittest.TestCase):
    """Tests for get_l1_cost_for_chain with chain-aware dispatch."""

    def test_base_chain_dispatches_to_op(self):
        """Base chain should use OP-Stack GasPriceOracle, not NodeInterface."""
        from chains.l1_cost import get_l1_cost_for_chain, DEFAULT_OP_L1_FEE_WEI

        # R40.1: With w3=None, code tries public-RPC fallback before default.
        # For a deterministic unit test we must block fallback so we assert the
        # default branch (`default_op`). Patch Web3 inside the module so any
        # fallback attempt raises.
        with patch("chains.l1_cost.Web3", side_effect=RuntimeError("no network in test")):
            cost, source = get_l1_cost_for_chain(w3=None, chain="base")
        self.assertEqual(source, "default_op")
        self.assertEqual(cost, DEFAULT_OP_L1_FEE_WEI)

    def test_base_onchain_op_success(self):
        """Base chain with working w3 should call GasPriceOracle."""
        from chains.l1_cost import get_l1_cost_for_chain

        mock_w3 = MagicMock()
        mock_contract = MagicMock()
        mock_w3.eth.contract.return_value = mock_contract
        mock_w3.to_checksum_address = lambda x: x
        mock_contract.functions.getL1Fee.return_value.call.return_value = 2_500_000_000_000

        cost, source = get_l1_cost_for_chain(w3=mock_w3, chain="base", calldata=b"\x00" * 100)
        self.assertEqual(source, "onchain_op")
        self.assertEqual(cost, 2_500_000_000_000)

    def test_arbitrum_falls_through_to_nodeinterface(self):
        """Arbitrum chain should go to get_l1_cost_with_source (NodeInterface path)."""
        from chains.l1_cost import get_l1_cost_for_chain

        cost, source = get_l1_cost_for_chain(w3=None, chain="arbitrum")
        self.assertEqual(source, "default")
        self.assertGreater(cost, 0)

    def test_arbitrum_one_variant(self):
        """'arbitrum_one' chain name should also dispatch to Arbitrum path."""
        from chains.l1_cost import get_l1_cost_for_chain

        cost, source = get_l1_cost_for_chain(w3=None, chain="arbitrum_one")
        self.assertEqual(source, "default")

    def test_base_op_default_cheaper_than_arb_default(self):
        """OP-Stack default L1 cost should be <= Arbitrum default (post-EIP-4844)."""
        from chains.l1_cost import get_l1_cost_for_chain

        base_cost, _ = get_l1_cost_for_chain(w3=None, chain="base")
        arb_cost, _ = get_l1_cost_for_chain(w3=None, chain="arbitrum")
        self.assertLessEqual(base_cost, arb_cost)


class TestCreateSampleSwapCalldata(unittest.TestCase):
    """Tests for sample swap calldata generation."""

    def test_creates_bytes(self):
        """Should return bytes."""
        from chains.l1_cost import create_sample_swap_calldata

        result = create_sample_swap_calldata(
            token_in="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            token_out="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            amount_in=int(1e18),
            fee=3000,
        )

        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 4)  # At least selector

    def test_calldata_is_228_bytes(self):
        """E1.57: Calldata must be 228 bytes (SwapRouter02 exactInputSingle)."""
        from chains.l1_cost import create_sample_swap_calldata

        result = create_sample_swap_calldata(
            token_in="0x4200000000000000000000000000000000000006",
            token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            amount_in=int(1e17),
            fee=500,
        )

        # 4-byte selector + 7 × 32-byte ABI params = 228 bytes
        self.assertEqual(len(result), 228, f"Expected 228 bytes, got {len(result)}")

    def test_calldata_starts_with_swaprouter02_selector(self):
        """E1.57: Selector must be SwapRouter02 exactInputSingle (0x04e45aaf)."""
        from chains.l1_cost import create_sample_swap_calldata

        result = create_sample_swap_calldata(
            token_in="0x4200000000000000000000000000000000000006",
            token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            amount_in=int(1e17),
            fee=500,
        )

        self.assertEqual(result[:4].hex(), "04e45aaf")


class TestGetL1FeeWei(unittest.TestCase):
    """E1.57: Tests for the get_l1_fee_wei convenience function."""

    def test_non_op_chain_returns_zero(self):
        """Chains without L1 data fees should return 0 immediately."""
        from chains.l1_cost import get_l1_fee_wei

        self.assertEqual(get_l1_fee_wei("arbitrum"), 0)
        self.assertEqual(get_l1_fee_wei("arbitrum_one"), 0)
        self.assertEqual(get_l1_fee_wei("ethereum"), 0)

    def test_base_chain_returns_int(self):
        """Base chain must return a non-negative int (network call or fallback)."""
        from unittest.mock import patch, MagicMock
        from chains.l1_cost import get_l1_fee_wei

        # Monkeypatch get_l1_cost_for_chain to avoid real network call
        with patch("chains.l1_cost.get_l1_cost_for_chain") as mock_fn:
            mock_fn.return_value = (400_000_000, "onchain_op_fallback")
            result = get_l1_fee_wei("base")

        self.assertIsInstance(result, int)
        self.assertEqual(result, 400_000_000)

    def test_base_chain_returns_default_on_failure(self):
        """When all RPCs fail, fallback value must be the DEFAULT_OP_L1_FEE_WEI."""
        from unittest.mock import patch
        from chains.l1_cost import get_l1_fee_wei, DEFAULT_OP_L1_FEE_WEI

        with patch("chains.l1_cost.get_l1_cost_for_chain") as mock_fn:
            mock_fn.return_value = (DEFAULT_OP_L1_FEE_WEI, "default_op")
            result = get_l1_fee_wei("base")

        self.assertEqual(result, DEFAULT_OP_L1_FEE_WEI)


if __name__ == "__main__":
    unittest.main()
