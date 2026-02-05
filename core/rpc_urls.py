"""Helpers to build provider RPC URLs from API keys and network names.

This module provides small utilities to generate Alchemy HTTP/WS endpoints
from a single `ALCHEMY_API_KEY` and a canonical network name.
Supported canonical networks: arbitrum, base, linea, mantle
"""
from typing import Optional

_NETWORK_ALIASES = {
    "arbitrum_one": "arbitrum",
    "arbitrum": "arbitrum",
    "base": "base",
    "linea": "linea",
    "mantle": "mantle",
}

# Alchemy subdomain mapping (best-effort); these are the subdomain prefixes
# used by Alchemy for each network.
_ALCHEMY_SUBDOMAINS = {
    "arbitrum": "arb-mainnet",
    "base": "base-mainnet",
    "linea": "linea-mainnet",
    "mantle": "mantle-mainnet",
}

# Simple public fallbacks when Alchemy isn't available for a supported network.
_PUBLIC_FALLBACKS = {
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "base": "https://mainnet.base.org",
    "linea": "https://rpc.linea.build",
    "mantle": "https://rpc.mantle.xyz",
}


def _normalize_network(network: Optional[str]) -> Optional[str]:
    if not network:
        return None
    key = network.strip().lower()
    return _NETWORK_ALIASES.get(key)


def build_alchemy_http_url(network: Optional[str], api_key: str) -> Optional[str]:
    """Return an Alchemy HTTP URL for the given canonical network and API key.

    If the network is unsupported, return None.
    """
    net = _normalize_network(network)
    if not net:
        return None
    sub = _ALCHEMY_SUBDOMAINS.get(net)
    if not sub:
        return None
    return f"https://{sub}.g.alchemy.com/v2/{api_key}"


def build_alchemy_ws_url(network: Optional[str], api_key: str) -> Optional[str]:
    """Return an Alchemy WS URL (wss) for the given network and API key.

    If not supported, return None.
    """
    net = _normalize_network(network)
    if not net:
        return None
    sub = _ALCHEMY_SUBDOMAINS.get(net)
    if not sub:
        return None
    return f"wss://{sub}.g.alchemy.com/v2/{api_key}"


def public_fallback_for(network: Optional[str]) -> Optional[str]:
    net = _normalize_network(network)
    if not net:
        return None
    return _PUBLIC_FALLBACKS.get(net)
