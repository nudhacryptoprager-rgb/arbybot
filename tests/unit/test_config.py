# PATH: tests/unit/test_config.py
"""
Unit tests for configuration loading.
"""

import unittest
from pathlib import Path

# Check if config files exist before running tests
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


class TestConfigLoading(unittest.TestCase):
    """Tests for config loading functions."""
    
    def test_config_dir_exists(self):
        """Config directory exists."""
        self.assertTrue(CONFIG_DIR.exists())
    
    def test_load_chains(self):
        """Can load chains.yaml."""
        if not (CONFIG_DIR / "chains.yaml").exists():
            self.skipTest("chains.yaml not found")
        
        from config import load_chains
        chains = load_chains()
        
        self.assertIsInstance(chains, dict)
        self.assertIn("arbitrum_one", chains)
    
    def test_load_dexes(self):
        """Can load dexes.yaml."""
        if not (CONFIG_DIR / "dexes.yaml").exists():
            self.skipTest("dexes.yaml not found")
        
        from config import load_dexes
        dexes = load_dexes()
        
        self.assertIsInstance(dexes, dict)
    
    def test_load_core_tokens(self):
        """Can load core_tokens.yaml."""
        if not (CONFIG_DIR / "core_tokens.yaml").exists():
            self.skipTest("core_tokens.yaml not found")
        
        from config import load_core_tokens
        tokens = load_core_tokens()
        
        self.assertIsInstance(tokens, dict)
    
    def test_load_strategy(self):
        """Can load strategy.yaml."""
        if not (CONFIG_DIR / "strategy.yaml").exists():
            self.skipTest("strategy.yaml not found")
        
        from config import load_strategy
        strategy = load_strategy()
        
        self.assertIsInstance(strategy, dict)
        self.assertIn("quote", strategy)
        self.assertIn("sizes_usd", strategy["quote"])
    
    def test_get_chain_config(self):
        """Can get specific chain config."""
        if not (CONFIG_DIR / "chains.yaml").exists():
            self.skipTest("chains.yaml not found")
        
        from config import get_chain_config
        
        config = get_chain_config("arbitrum_one")
        
        self.assertEqual(config["chain_id"], 42161)
        self.assertIn("rpc_endpoints", config)
    
    def test_get_chain_config_unknown(self):
        """Unknown chain raises KeyError."""
        if not (CONFIG_DIR / "chains.yaml").exists():
            self.skipTest("chains.yaml not found")
        
        from config import get_chain_config
        
        with self.assertRaises(KeyError):
            get_chain_config("unknown_chain")
    
    def test_get_token_address(self):
        """Can get token address."""
        if not (CONFIG_DIR / "core_tokens.yaml").exists():
            self.skipTest("core_tokens.yaml not found")
        
        from config import get_token_address
        
        address = get_token_address("arbitrum_one", "USDC")
        
        self.assertIsNotNone(address)
        self.assertTrue(address.startswith("0x"))


if __name__ == "__main__":
    unittest.main()