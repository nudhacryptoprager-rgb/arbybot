# PATH: discovery/verify.py
"""
On-chain token/pool verification (Roadmap Appendix A Step 2).

Resolves symbols -> verified token addresses via:
1. Core tokens from config/core_tokens.yaml (trust anchors)
2. On-chain verification: decimals(), symbol(), name(), totalSupply()

This module does NOT use external APIs like DexScreener for address resolution.
It only verifies addresses that are already known or discovered via factory indexing.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional, Tuple

import yaml

logger = logging.getLogger("discovery.verify")

CORE_TOKENS_PATH = Path("config/core_tokens.yaml")


class TokenInfo(NamedTuple):
    """Verified token information."""
    symbol: str
    address: str
    decimals: int
    name: Optional[str] = None
    is_core: bool = False
    verified_onchain: bool = False


class TokenRegistry:
    """
    Registry of verified tokens per chain.
    
    Priority:
    1. Core tokens from config/core_tokens.yaml (trust anchors)
    2. Verified tokens from on-chain checks
    """
    
    def __init__(self):
        self._tokens: Dict[str, Dict[str, TokenInfo]] = {}  # chain -> symbol -> TokenInfo
        self._core_loaded = False
    
    def _load_core_tokens(self) -> None:
        """Load core tokens from YAML."""
        if self._core_loaded:
            return
        
        if not CORE_TOKENS_PATH.exists():
            logger.warning("Core tokens file not found: %s", CORE_TOKENS_PATH)
            return
        
        try:
            with open(CORE_TOKENS_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            for chain, tokens in data.items():
                if chain not in self._tokens:
                    self._tokens[chain] = {}
                
                for symbol, info in tokens.items():
                    if isinstance(info, dict):
                        self._tokens[chain][symbol.upper()] = TokenInfo(
                            symbol=symbol.upper(),
                            address=info.get("address", ""),
                            decimals=info.get("decimals", 18),
                            name=info.get("name"),
                            is_core=True,
                            verified_onchain=False,
                        )
            
            total = sum(len(t) for t in self._tokens.values())
            logger.info("Loaded %d core tokens from %s", total, CORE_TOKENS_PATH.name)
            self._core_loaded = True
            
        except Exception as e:
            logger.error("Failed to load core tokens: %s", e)
    
    def get_token(self, chain: str, symbol: str) -> Optional[TokenInfo]:
        """
        Get token info by chain and symbol.
        
        Args:
            chain: Chain key (e.g., "arbitrum_one")
            symbol: Token symbol (e.g., "WETH")
            
        Returns:
            TokenInfo or None if not found
        """
        self._load_core_tokens()
        
        chain_tokens = self._tokens.get(chain, {})
        return chain_tokens.get(symbol.upper())
    
    def get_address(self, chain: str, symbol: str) -> Optional[str]:
        """Get token address by chain and symbol."""
        token = self.get_token(chain, symbol)
        return token.address if token else None
    
    def has_token(self, chain: str, symbol: str) -> bool:
        """Check if token exists in registry."""
        return self.get_token(chain, symbol) is not None
    
    def get_all_tokens(self, chain: str) -> Dict[str, TokenInfo]:
        """Get all tokens for a chain."""
        self._load_core_tokens()
        return self._tokens.get(chain, {}).copy()
    
    def register_token(self, chain: str, token: TokenInfo) -> None:
        """Register a verified token."""
        if chain not in self._tokens:
            self._tokens[chain] = {}
        
        existing = self._tokens[chain].get(token.symbol)
        if existing and existing.is_core:
            # Don't override core tokens
            logger.debug("Skipping registration of %s (core token)", token.symbol)
            return
        
        self._tokens[chain][token.symbol] = token
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            chain: {
                symbol: {
                    "address": info.address,
                    "decimals": info.decimals,
                    "name": info.name,
                    "is_core": info.is_core,
                    "verified_onchain": info.verified_onchain,
                }
                for symbol, info in tokens.items()
            }
            for chain, tokens in self._tokens.items()
        }


def verify_token_onchain(
    address: str,
    rpc_url: str,
    expected_symbol: Optional[str] = None,
) -> Tuple[bool, Optional[TokenInfo], Optional[str]]:
    """
    Verify token on-chain by calling decimals(), symbol(), name().
    
    Args:
        address: Token contract address
        rpc_url: RPC URL
        expected_symbol: Expected symbol to match (optional)
        
    Returns:
        (success, TokenInfo, error_msg)
    """
    import os
    
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return False, None, "RPC skipped"
    
    try:
        from web3 import Web3
    except ImportError:
        return False, None, "web3 not installed"
    
    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        checksum_addr = Web3.to_checksum_address(address)
        
        # Minimal ERC20 ABI for verification
        ERC20_ABI = [
            {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "name", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "totalSupply", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
        ]
        
        contract = w3.eth.contract(address=checksum_addr, abi=ERC20_ABI)
        
        # Fetch basic info
        decimals = contract.functions.decimals().call()
        symbol = contract.functions.symbol().call()
        name = contract.functions.name().call()
        
        # Sanity check: totalSupply > 0
        total_supply = contract.functions.totalSupply().call()
        if total_supply == 0:
            return False, None, "totalSupply is 0"
        
        # Check expected symbol if provided
        if expected_symbol and symbol.upper() != expected_symbol.upper():
            return False, None, f"Symbol mismatch: got {symbol}, expected {expected_symbol}"
        
        token_info = TokenInfo(
            symbol=symbol.upper(),
            address=address.lower(),
            decimals=decimals,
            name=name,
            is_core=False,
            verified_onchain=True,
        )
        
        logger.info("Verified token: %s (%s) decimals=%d", symbol, address[:10], decimals)
        return True, token_info, None
        
    except Exception as e:
        return False, None, str(e)


# =============================================================================
# SINGLETON REGISTRY
# =============================================================================

_token_registry: Optional[TokenRegistry] = None


def get_token_registry() -> TokenRegistry:
    """Get the singleton token registry."""
    global _token_registry
    if _token_registry is None:
        _token_registry = TokenRegistry()
    return _token_registry


def reset_token_registry() -> None:
    """Reset the singleton (for testing)."""
    global _token_registry
    _token_registry = None


def resolve_symbol_to_address(chain: str, symbol: str) -> Optional[str]:
    """
    Convenience function: Resolve symbol to address.
    
    Args:
        chain: Chain key
        symbol: Token symbol
        
    Returns:
        Token address or None
    """
    registry = get_token_registry()
    return registry.get_address(chain, symbol)
