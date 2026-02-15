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
        from chains.l1_cost import estimate_l1_cost_from_config
        
        # Empty config should use defaults
        result = estimate_l1_cost_from_config({})
        
        # Default: 2000 * 30 * 1e9
        expected = int(2000 * 30 * 1e9)
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


if __name__ == "__main__":
    unittest.main()
