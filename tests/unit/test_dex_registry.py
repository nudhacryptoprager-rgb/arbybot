# PATH: tests/unit/test_dex_registry.py
"""
Tests for dex/registry.py - Roadmap M2.1.

Contract:
- Registry maps adapter_type -> AdapterClass
- load_dex_configs() parses config/dexes.yaml
- get_adapter_class() returns class or None
"""

import pytest
from pathlib import Path


class TestDexRegistry:
    """Test DEX registry functionality."""
    
    def test_list_adapter_types(self):
        """Registry returns list of known adapter types."""
        from dex.registry import list_adapter_types
        
        types = list_adapter_types()
        
        # At minimum, uniswap_v3 should be registered
        assert "uniswap_v3" in types
        assert isinstance(types, list)
    
    def test_get_adapter_class_uniswap_v3(self):
        """get_adapter_class returns UniswapV3Adapter for uniswap_v3."""
        from dex.registry import get_adapter_class
        
        cls = get_adapter_class("uniswap_v3")
        
        assert cls is not None
        assert cls.__name__ == "UniswapV3Adapter"
    
    def test_get_adapter_class_algebra(self):
        """get_adapter_class returns AlgebraAdapter for algebra."""
        from dex.registry import get_adapter_class
        
        cls = get_adapter_class("algebra")
        
        assert cls is not None
        assert cls.__name__ == "AlgebraAdapter"
    
    def test_get_adapter_class_unknown(self):
        """get_adapter_class returns None for unknown type."""
        from dex.registry import get_adapter_class
        
        cls = get_adapter_class("nonexistent_adapter")
        
        assert cls is None


class TestDexConfigLoading:
    """Test DEX config loading from YAML."""
    
    def test_load_dex_configs_arbitrum(self):
        """load_dex_configs returns configs for arbitrum_one."""
        from dex.registry import load_dex_configs
        
        configs = load_dex_configs("arbitrum_one")
        
        assert "uniswap_v3" in configs
        assert "sushiswap_v3" in configs
        assert configs["uniswap_v3"].adapter_type == "uniswap_v3"
        assert configs["uniswap_v3"].factory.startswith("0x")
    
    def test_load_dex_configs_camelot(self):
        """camelot_v3 uses algebra adapter_type."""
        from dex.registry import load_dex_configs
        
        configs = load_dex_configs("arbitrum_one")
        
        assert "camelot_v3" in configs
        assert configs["camelot_v3"].adapter_type == "algebra"
    
    def test_load_dex_configs_unknown_chain(self):
        """load_dex_configs returns empty dict for unknown chain."""
        from dex.registry import load_dex_configs
        
        configs = load_dex_configs("unknown_chain_xyz")
        
        assert configs == {}
    
    def test_dex_config_get_quoter_address(self):
        """DexConfig.get_quoter_address returns quoter_v2 or quoter."""
        from dex.registry import load_dex_configs
        
        configs = load_dex_configs("arbitrum_one")
        
        # uniswap_v3 uses quoter_v2
        assert configs["uniswap_v3"].get_quoter_address() is not None
        assert "0x" in configs["uniswap_v3"].get_quoter_address()
        
        # camelot_v3 uses quoter
        assert configs["camelot_v3"].get_quoter_address() is not None


class TestGetDexConfig:
    """Test single DEX config retrieval."""
    
    def test_get_dex_config_existing(self):
        """get_dex_config returns config for existing DEX."""
        from dex.registry import get_dex_config
        
        config = get_dex_config("arbitrum_one", "uniswap_v3")
        
        assert config is not None
        assert config.name == "uniswap_v3"
        assert config.adapter_type == "uniswap_v3"
    
    def test_get_dex_config_nonexistent(self):
        """get_dex_config returns None for nonexistent DEX."""
        from dex.registry import get_dex_config
        
        config = get_dex_config("arbitrum_one", "nonexistent_dex")
        
        assert config is None


class TestCreateAdapter:
    """Test adapter factory."""
    
    def test_create_adapter_uniswap_v3(self):
        """create_adapter creates UniswapV3Adapter instance."""
        from dex.registry import get_dex_config, create_adapter
        
        config = get_dex_config("arbitrum_one", "uniswap_v3")
        assert config is not None
        
        # Create without RPC (provider=None)
        adapter = create_adapter(config, rpc_provider=None)
        
        assert adapter is not None
        assert adapter.dex_id == "uniswap_v3"
        assert adapter.quoter_address != ""
    
    def test_create_adapter_algebra(self):
        """create_adapter creates AlgebraAdapter for camelot_v3."""
        from dex.registry import get_dex_config, create_adapter
        
        config = get_dex_config("arbitrum_one", "camelot_v3")
        assert config is not None
        
        adapter = create_adapter(config, rpc_provider=None)
        
        assert adapter is not None
        assert adapter.dex_id == "camelot_v3"
    
    def test_create_adapter_unknown_type(self):
        """create_adapter returns None for unknown adapter type."""
        from dex.registry import DexConfig, create_adapter
        
        fake_config = DexConfig(
            name="fake_dex",
            adapter_type="nonexistent_type",
            factory="0x0000000000000000000000000000000000000000",
        )
        
        adapter = create_adapter(fake_config, rpc_provider=None)
        
        assert adapter is None
