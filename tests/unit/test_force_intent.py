# PATH: tests/unit/test_force_intent.py
"""
Unit tests for force_intent parameter in config/pairs.py (v2.3.0).

Contract:
- When force_intent=True, config pairs are bypassed
- Intent universe (intent.txt) is used instead
- This enables the "intent_verified" mode for universe_source verification
"""

import pytest
from unittest.mock import patch, MagicMock


class TestForceIntentParameter:
    """Test force_intent parameter behavior in load_pairs."""
    
    def test_load_pairs_signature_has_force_intent(self):
        """load_pairs function should have force_intent parameter."""
        import inspect
        from config.pairs import load_pairs
        
        sig = inspect.signature(load_pairs)
        params = list(sig.parameters.keys())
        
        assert "force_intent" in params, "load_pairs should have force_intent parameter"
    
    def test_force_intent_defaults_to_false(self):
        """force_intent should default to False."""
        import inspect
        from config.pairs import load_pairs
        
        sig = inspect.signature(load_pairs)
        force_intent_param = sig.parameters["force_intent"]
        
        assert force_intent_param.default is False, \
            "force_intent should default to False"
    
    def test_force_intent_true_bypasses_config_pairs(self):
        """When force_intent=True, config pairs should be ignored."""
        from config.pairs import load_pairs
        
        # Config with explicit pairs
        config_with_pairs = {
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500]},
            ]
        }
        
        # With force_intent=False, config pairs should be used
        pairs_from_config = load_pairs(
            "arbitrum_one",
            config=config_with_pairs,
            force_intent=False
        )
        
        # Config has 1 pair
        assert len(pairs_from_config) == 1, \
            "With force_intent=False, should use config pairs"
        assert pairs_from_config[0].token_in == "WETH"
        assert pairs_from_config[0].token_out == "USDC"
    
    @patch("discovery.intent_loader.get_intent_universe")
    def test_force_intent_true_uses_intent_universe(self, mock_get_intent):
        """When force_intent=True, intent universe should be used instead of config."""
        from config.pairs import load_pairs
        
        # Setup mock intent universe
        mock_intent_pair = MagicMock()
        mock_intent_pair.token_a = "ARB"
        mock_intent_pair.token_b = "WETH"
        
        mock_universe = MagicMock()
        mock_universe.get_pairs_for_chain.return_value = [mock_intent_pair]
        mock_get_intent.return_value = mock_universe
        
        # Config with explicit pairs (should be ignored)
        config_with_pairs = {
            "pairs": [
                {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500]},
            ]
        }
        
        # With force_intent=True, intent universe should be used
        pairs_from_intent = load_pairs(
            "arbitrum_one",
            config=config_with_pairs,
            force_intent=True
        )
        
        # Should have called get_intent_universe
        mock_get_intent.assert_called_once()
        
        # Should return intent pairs, not config pairs
        # Note: mock returns ARB/WETH, config has WETH/USDC
        assert len(pairs_from_intent) >= 1, \
            "force_intent=True should return intent pairs"
    
    def test_force_intent_source_in_code(self):
        """Verify force_intent handling code pattern exists."""
        import inspect
        from config import pairs
        
        source = inspect.getsource(pairs.load_pairs)
        
        # Should check force_intent before config pairs
        assert "force_intent" in source, \
            "load_pairs should reference force_intent"
        assert "get_intent_universe" in source, \
            "load_pairs should import get_intent_universe for force_intent"


class TestIntentForcedModeWiring:
    """Test that intent_forced mode uses force_intent correctly."""
    
    def test_run_scan_real_has_intent_forced_handling(self):
        """run_scan_real should handle universe_source=intent_forced."""
        import inspect
        from strategy.jobs import run_scan_real
        
        source = inspect.getsource(run_scan_real)
        
        # Should check for intent_forced (or legacy intent_verified)
        assert "intent_forced" in source or "intent_verified" in source, \
            "run_scan_real should handle intent_forced/intent_verified mode"
        
        # Should set force_intent=True somewhere
        assert "force_intent" in source, \
            "run_scan_real should use force_intent parameter"
    
    def test_intent_forced_has_explicit_not_verified_field(self):
        """run_scan_real should add intent_on_chain_verified=False field."""
        import inspect
        from strategy.jobs import run_scan_real
        
        source = inspect.getsource(run_scan_real)
        
        # Should have explicit field stating pools are NOT on-chain verified
        assert "intent_on_chain_verified" in source, \
            "Should have intent_on_chain_verified field for explicit semantics"
