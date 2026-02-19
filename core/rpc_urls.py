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


# Map common chain IDs to canonical network names (partial list; extend as needed)
_CHAIN_ID_TO_NETWORK = {
    42161: "arbitrum",
    8453: "base",
    59144: "linea",
    5000: "mantle",
}

# v1.12.2: Host patterns for chain validation
_CHAIN_ID_HOST_PATTERNS = {
    42161: ["arb", "arbitrum"],
    8453: ["base"],
    59144: ["linea"],
    5000: ["mantle"],
}


def validate_chain_rpc_consistency(chain_id: int, rpc_http_host: str) -> tuple:
    """
    Validate that the RPC host matches the expected chain.
    
    Returns (is_valid, error_message).
    If chain_id is unknown, returns (True, None) - allows unknown chains.
    
    v1.12.2: Prevent chain_id / RPC mismatch (e.g., Arbitrum chain_id with Mantle host).
    """
    if chain_id not in _CHAIN_ID_HOST_PATTERNS:
        return True, None  # Unknown chain, can't validate
    
    expected_patterns = _CHAIN_ID_HOST_PATTERNS[chain_id]
    expected_network = _CHAIN_ID_TO_NETWORK.get(chain_id, "unknown")
    host_lower = rpc_http_host.lower()
    
    # Check if host contains at least one expected pattern
    if any(pattern in host_lower for pattern in expected_patterns):
        return True, None
    
    # Check for known mismatches
    for other_chain_id, other_patterns in _CHAIN_ID_HOST_PATTERNS.items():
        if other_chain_id != chain_id:
            if any(pattern in host_lower for pattern in other_patterns):
                other_network = _CHAIN_ID_TO_NETWORK.get(other_chain_id, "unknown")
                return False, (
                    f"chain_id={chain_id} ({expected_network}) but RPC host '{rpc_http_host}' "
                    f"appears to be for {other_network} (chain_id={other_chain_id})"
                )
    
    return True, None  # No mismatch detected


def _normalize_network_from_chain(chain_id: Optional[int], network: Optional[str]) -> Optional[str]:
    # Prefer chain_id mapping when available (avoid accidental mismatched NETWORK env)
    if chain_id is not None:
        mapped = _CHAIN_ID_TO_NETWORK.get(int(chain_id))
        if mapped:
            return mapped
    # Fallback to explicit network string if chain_id not mapped
    if network:
        return _normalize_network(network)
    return None


def resolve_rpc_http(chain_id: Optional[int] = None, network: Optional[str] = None, env: Optional[dict] = None):
    """Resolve an HTTP RPC URL from environment or Alchemy API key.

    Returns tuple (url_or_none, provider_name, diagnostics_dict).
    """
    env = env or {}
    diagnostics = {}

    # Prefer explicit env var
    http = env.get("ALCHEMY_RPC_HTTP") or env.get("ARBY_RPC_HTTP_PRIMARY")
    if http:
        diagnostics["source"] = "explicit"
        return http, ("alchemy" if "alchemy" in http else "public"), diagnostics

    # Build from api key if present
    api = env.get("ALCHEMY_API_KEY")
    net = _normalize_network_from_chain(chain_id, env.get("NETWORK") or network)
    diagnostics["normalized_network"] = net
    if api and net:
        url = build_alchemy_http_url(net, api)
        if url:
            diagnostics["source"] = "alchemy_api_key"
            return url, "alchemy", diagnostics

    # Fallback to public
    fb = public_fallback_for(net)
    if fb:
        diagnostics["source"] = "public_fallback"
        return fb, "public", diagnostics

    diagnostics["source"] = "none"
    return None, "unknown", diagnostics


def resolve_rpc_ws(chain_id: Optional[int] = None, network: Optional[str] = None, env: Optional[dict] = None):
    """Resolve a WS (wss) URL similarly to resolve_rpc_http.

    Returns tuple (url_or_none, provider_name, diagnostics_dict).
    """
    env = env or {}
    diagnostics = {}

    ws = env.get("ALCHEMY_RPC_WS") or env.get("ARBY_RPC_WS_PRIMARY")
    if ws:
        diagnostics["source"] = "explicit"
        return ws, ("alchemy" if "alchemy" in ws else "public"), diagnostics

    api = env.get("ALCHEMY_API_KEY")
    net = _normalize_network_from_chain(chain_id, env.get("NETWORK") or network)
    diagnostics["normalized_network"] = net
    if api and net:
        url = build_alchemy_ws_url(net, api)
        if url:
            diagnostics["source"] = "alchemy_api_key"
            return url, "alchemy", diagnostics

    diagnostics["source"] = "none"
    return None, "unknown", diagnostics


# =============================================================================
# SIMPLE HELPERS (v2.3.2)
# =============================================================================

# Chain key to chain_id mapping
_CHAIN_KEY_TO_ID = {
    "arbitrum_one": 42161,
    "arbitrum": 42161,
    "base": 8453,
    "linea": 59144,
    "mantle": 5000,
}


def get_rpc_url(chain: str) -> Optional[str]:
    """
    Get RPC URL for a chain (simple helper).
    
    Args:
        chain: Chain key (e.g., "arbitrum_one", "base")
        
    Returns:
        RPC HTTP URL or None if unavailable
        
    CONTRACT:
    - Uses resolve_rpc_http() with os.environ
    - Returns None if no RPC available (never raises)
    """
    import os
    
    chain_id = _CHAIN_KEY_TO_ID.get(chain.lower())
    url, _provider, _diag = resolve_rpc_http(
        chain_id=chain_id,
        network=chain,
        env=dict(os.environ),
    )
    return url


