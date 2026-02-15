# PATH: dex/registry.py
"""
DEX Registry - Roadmap M2.1 implementation.

Central registry mapping adapter_type -> AdapterClass.
Provides factory for creating adapter instances from config/dexes.yaml.

Contract:
- adapter_type must match config/dexes.yaml `adapter_type` field
- Each adapter must implement get_quote() method
- Registry is the single source of truth for adapter classes

M2.1 STATUS (v2.0.9):
- Registry provides DexConfig loading from config/dexes.yaml ✓
- Registry provides adapter_type -> quoter_address mapping ✓
- Registry provides create_adapter() factory ✓
- TODO(M2.1): Scanner should quote ONLY via registry-created adapters
  Current: Scanner uses registry for metadata but calls read_slot0/read_quoter directly
  Target: Scanner calls adapter.get_quote() which internally handles quoter vs slot0
"""

from dataclasses import dataclass
from typing import Dict, Optional, Type, Any
from pathlib import Path
import yaml

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DexConfig:
    """Configuration for a single DEX."""
    name: str               # DEX name (e.g., "uniswap_v3", "sushiswap_v3")
    adapter_type: str       # Adapter type (e.g., "uniswap_v3", "algebra")
    factory: str            # Factory contract address
    router: Optional[str] = None
    quoter_v2: Optional[str] = None      # QuoterV2 for uniswap_v3 type
    quoter: Optional[str] = None         # Generic quoter for algebra type
    fee_tiers: Optional[list] = None     # Fee tiers (for uniswap_v3)
    
    def get_quoter_address(self) -> Optional[str]:
        """Get quoter address (QuoterV2 or generic quoter)."""
        return self.quoter_v2 or self.quoter


class BaseAdapter:
    """
    Base adapter interface.
    
    All DEX adapters must inherit from this and implement get_quote().
    """
    
    def __init__(self, config: DexConfig, rpc_provider: Any = None):
        self.config = config
        self.rpc_provider = rpc_provider
        self.name = config.name
    
    def get_quote(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: Optional[int] = None,
        block_number: Optional[int] = None,
    ) -> dict:
        """
        Get quote for exact input swap.
        
        Returns:
            dict with keys: amount_out, gas_estimate, ticks_crossed, sqrt_price_after
        """
        raise NotImplementedError("Subclasses must implement get_quote()")
    
    def supports_fee_tiers(self) -> bool:
        """Whether this adapter uses discrete fee tiers."""
        return self.config.fee_tiers is not None


# =============================================================================
# REGISTRY
# =============================================================================

# Adapter type -> Adapter class mapping
# Lazy-loaded to avoid circular imports
_ADAPTER_REGISTRY: Dict[str, Type[BaseAdapter]] = {}


def _register_adapters():
    """Register built-in adapters. Called once on first registry access."""
    global _ADAPTER_REGISTRY
    if _ADAPTER_REGISTRY:
        return  # Already registered
    
    # Import adapters here to avoid circular imports
    # Note: Each adapter has its own constructor signature, so we store class + factory
    try:
        from dex.adapters.uniswap_v3 import UniswapV3Adapter
        _ADAPTER_REGISTRY["uniswap_v3"] = UniswapV3Adapter
    except ImportError as e:
        logger.warning(f"Failed to import uniswap_v3 adapter: {e}")
    
    try:
        from dex.adapters.algebra import AlgebraAdapter
        _ADAPTER_REGISTRY["algebra"] = AlgebraAdapter
    except ImportError as e:
        logger.warning(f"Failed to import algebra adapter: {e}")
    
    # Mark ve33 as not yet implemented
    logger.debug(f"Registered adapters: {list(_ADAPTER_REGISTRY.keys())}")


def get_adapter_class(adapter_type: str) -> Optional[Type[BaseAdapter]]:
    """
    Get adapter class by type name.
    
    Args:
        adapter_type: Adapter type from config (e.g., "uniswap_v3", "algebra")
        
    Returns:
        Adapter class or None if not found
    """
    _register_adapters()
    return _ADAPTER_REGISTRY.get(adapter_type)


def create_adapter(
    dex_config: DexConfig,
    rpc_provider: Any = None,
) -> Optional[BaseAdapter]:
    """
    Create adapter instance from DexConfig.
    
    M4.2 FIX: Use factory pattern that matches actual adapter constructors.
    Adapters expect (provider, quoter_address, dex_id) not (DexConfig, rpc_provider).
    
    Args:
        dex_config: DEX configuration
        rpc_provider: RPC provider for blockchain calls (web3 or RPCProvider)
        
    Returns:
        Adapter instance or None if adapter type not supported
    """
    adapter_class = get_adapter_class(dex_config.adapter_type)
    if adapter_class is None:
        logger.warning(f"Unknown adapter type: {dex_config.adapter_type} for {dex_config.name}")
        return None
    
    try:
        quoter_address = dex_config.get_quoter_address() or ""
        dex_id = dex_config.name
        
        # Both UniswapV3Adapter and AlgebraAdapter have signature:
        # __init__(self, provider/web3, quoter_address: str, dex_id: str = ...)
        return adapter_class(rpc_provider, quoter_address, dex_id)
    except Exception as e:
        logger.warning(f"Failed to create adapter for {dex_config.name}: {e}")
        return None


def list_adapter_types() -> list[str]:
    """List all registered adapter types."""
    _register_adapters()
    return list(_ADAPTER_REGISTRY.keys())


# =============================================================================
# CONFIG LOADING
# =============================================================================

def load_dex_configs(chain: str, config_path: Optional[Path] = None) -> Dict[str, DexConfig]:
    """
    Load DEX configurations from config/dexes.yaml for a given chain.
    
    Args:
        chain: Chain name (e.g., "arbitrum_one", "base")
        config_path: Optional path to dexes.yaml (default: config/dexes.yaml)
        
    Returns:
        Dict of dex_name -> DexConfig
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "dexes.yaml"
    
    try:
        with open(config_path) as f:
            all_configs = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load dexes.yaml: {e}")
        return {}
    
    chain_configs = all_configs.get(chain, {})
    if not chain_configs:
        logger.warning(f"No DEX configs found for chain: {chain}")
        return {}
    
    result = {}
    for dex_name, dex_data in chain_configs.items():
        try:
            result[dex_name] = DexConfig(
                name=dex_name,
                adapter_type=dex_data.get("adapter_type", ""),
                factory=dex_data.get("factory", ""),
                router=dex_data.get("router"),
                quoter_v2=dex_data.get("quoter_v2"),
                quoter=dex_data.get("quoter"),
                fee_tiers=dex_data.get("fee_tiers"),
            )
        except Exception as e:
            logger.warning(f"Failed to parse config for {dex_name}: {e}")
    
    return result


def get_dex_config(chain: str, dex_name: str) -> Optional[DexConfig]:
    """Get single DEX config by chain and name."""
    configs = load_dex_configs(chain)
    return configs.get(dex_name)
