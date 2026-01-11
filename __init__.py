"""
chains/ - Blockchain interaction layer.

Modules:
- providers: RPC provider management with failover
- block: Block number management and pinning
"""

from chains.providers import (
    RPCProvider,
    RPCResponse,
    RPCStats,
    ProviderRegistry,
    get_provider,
    register_provider,
    close_all_providers,
)
from chains.block import (
    BlockState,
    BlockPinner,
    fetch_block_number,
)

__all__ = [
    # Providers
    "RPCProvider",
    "RPCResponse", 
    "RPCStats",
    "ProviderRegistry",
    "get_provider",
    "register_provider",
    "close_all_providers",
    # Block
    "BlockState",
    "BlockPinner",
    "fetch_block_number",
]
