# PATH: config/__init__.py
"""
Configuration loading utilities for ARBY.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


CONFIG_DIR = Path(__file__).parent


def load_yaml(filename: str) -> Dict[str, Any]:
    """
    Load a YAML configuration file.
    
    Args:
        filename: Name of file in config directory
        
    Returns:
        Parsed YAML as dict
    """
    filepath = CONFIG_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(f"Config file not found: {filepath}")
    
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_chains() -> Dict[str, Any]:
    """Load chains configuration."""
    return load_yaml("chains.yaml")


def load_dexes() -> Dict[str, Any]:
    """Load DEXes configuration."""
    return load_yaml("dexes.yaml")


def load_core_tokens() -> Dict[str, Any]:
    """Load core tokens configuration."""
    return load_yaml("core_tokens.yaml")


def load_strategy() -> Dict[str, Any]:
    """Load strategy configuration."""
    return load_yaml("strategy.yaml")


def get_chain_config(chain_key: str) -> Dict[str, Any]:
    """
    Get configuration for a specific chain.
    
    Args:
        chain_key: Chain identifier (e.g., 'arbitrum_one')
        
    Returns:
        Chain configuration dict
    """
    chains = load_chains()
    if chain_key not in chains:
        raise KeyError(f"Unknown chain: {chain_key}")
    return chains[chain_key]


def get_dex_config(chain_key: str, dex_key: str) -> Dict[str, Any]:
    """
    Get configuration for a specific DEX on a chain.
    
    Args:
        chain_key: Chain identifier
        dex_key: DEX identifier
        
    Returns:
        DEX configuration dict
    """
    dexes = load_dexes()
    if chain_key not in dexes:
        raise KeyError(f"No DEXes configured for chain: {chain_key}")
    if dex_key not in dexes[chain_key]:
        raise KeyError(f"Unknown DEX {dex_key} on chain {chain_key}")
    return dexes[chain_key][dex_key]


def get_token_address(chain_key: str, symbol: str) -> Optional[str]:
    """
    Get token address for a symbol on a chain.
    
    Args:
        chain_key: Chain identifier
        symbol: Token symbol (e.g., 'USDC')
        
    Returns:
        Token address or None if not found
    """
    tokens = load_core_tokens()
    if chain_key not in tokens:
        return None
    if symbol not in tokens[chain_key]:
        return None
    return tokens[chain_key][symbol].get("address")