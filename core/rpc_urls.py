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
    "scroll": "scroll",
    "zksync": "zksync",
    "optimism": "optimism",
}

# Chain-scoped env var names: (HTTP_VAR, WSS_VAR) per canonical network.
# These take priority over global ALCHEMY_API_KEY / ARBY_RPC_HTTP_PRIMARY.
_CHAIN_ENV_VARS = {
    "arbitrum": ("ARBITRUM_RPC", "ARBITRUM_WSS"),
    "base":     ("BASE_RPC",     "BASE_WSS"),
    "linea":    ("LINEA_RPC",    "LINEA_WSS"),
    "mantle":   ("MANTLE_RPC",   "MANTLE_WSS"),
    "scroll":   ("SCROLL_RPC",   "SCROLL_WSS"),
    "optimism": ("OPTIMISM_RPC", "OPTIMISM_WSS"),
}

# dRPC path-segment → canonical network mapping for wrong-chain validation.
_DRPC_PATH_SEGMENTS = {
    "arbitrum": "arbitrum",
    "base": "base",
    "linea": "linea",
    "mantle": "mantle",
    "scroll": "scroll",
    "optimism": "optimism",
}

# Alchemy subdomain mapping (best-effort); these are the subdomain prefixes
# used by Alchemy for each network.
_ALCHEMY_SUBDOMAINS = {
    "arbitrum": "arb-mainnet",
    "base": "base-mainnet",
    "linea": "linea-mainnet",
    "mantle": "mantle-mainnet",
    "scroll": "scroll-mainnet",
    "zksync": "zksync-mainnet",
}

# Simple public fallbacks when Alchemy isn't available for a supported network.
_PUBLIC_FALLBACKS = {
    "arbitrum": "https://arb1.arbitrum.io/rpc",
    "base": "https://mainnet.base.org",
    "linea": "https://rpc.linea.build",
    "mantle": "https://rpc.mantle.xyz",
    "scroll": "https://rpc.scroll.io",
    "zksync": "https://mainnet.era.zksync.io",
}

# Public WS fallbacks (free, no API key required).
# Used when Alchemy WS is unavailable (e.g. 429 rate limit).
_PUBLIC_WS_FALLBACKS = {
    "arbitrum": "wss://arbitrum-one-rpc.publicnode.com",
    "base": "wss://base-rpc.publicnode.com",
    "linea": "wss://linea-rpc.publicnode.com",
    "mantle": "wss://mantle-rpc.publicnode.com",
    "scroll": "wss://scroll-rpc.publicnode.com",
    "zksync": "wss://zksync-mainnet-rpc.publicnode.com",
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


def classify_provider(url: str) -> str:
    """Return a canonical provider type for an RPC URL.

    Canonical types: alchemy, drpc, public_fallback, flashblocks, infura,
    publicnode, localhost, unknown.
    """
    if not url:
        return "unknown"
    low = url.lower()
    if "alchemy.com" in low:
        return "alchemy"
    if "drpc.org" in low or "drpc.live" in low:
        return "drpc"
    if "publicnode.com" in low:
        return "publicnode"
    if "flashblocks" in low:
        return "flashblocks"
    if "infura.io" in low:
        return "infura"
    if "localhost" in low or "127.0.0.1" in low:
        return "localhost"
    # Public chain-official endpoints
    for _net, _fb in _PUBLIC_FALLBACKS.items():
        if _fb and _fb.lower().rstrip("/") == low.rstrip("/"):
            return "public_fallback"
    return "unknown"


def validate_drpc_url(url: str, expected_network: Optional[str]) -> tuple:
    """Validate that a dRPC URL matches the expected chain.

    dRPC URLs have the chain in the path: ``lb.drpc.live/<chain>/...``
    or ``<chain>.drpc.org``.

    Returns ``(is_valid, error_message_or_none)``.
    If the URL is not a dRPC URL, returns ``(True, None)`` (nothing to check).
    """
    if not url or not expected_network:
        return True, None
    low = url.lower()
    if "drpc.org" not in low and "drpc.live" not in low:
        return True, None  # not dRPC, skip

    from urllib.parse import urlparse
    parsed = urlparse(url)

    # lb.drpc.live/<chain>/... form
    if "drpc.live" in (parsed.netloc or "").lower():
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if path_parts:
            url_chain = path_parts[0].lower()
            net = _normalize_network(expected_network)
            if net and url_chain in _DRPC_PATH_SEGMENTS:
                drpc_net = _DRPC_PATH_SEGMENTS[url_chain]
                if drpc_net != net:
                    return False, (
                        f"dRPC URL chain mismatch: URL path has '{url_chain}' "
                        f"(={drpc_net}) but expected network is '{net}'"
                    )
        return True, None

    # <chain>.drpc.org form
    host = (parsed.netloc or "").lower().split(":")[0]
    if host.endswith(".drpc.org"):
        url_chain = host.replace(".drpc.org", "")
        net = _normalize_network(expected_network)
        if net and url_chain in _DRPC_PATH_SEGMENTS:
            drpc_net = _DRPC_PATH_SEGMENTS[url_chain]
            if drpc_net != net:
                return False, (
                    f"dRPC URL chain mismatch: host '{host}' "
                    f"(={drpc_net}) but expected network is '{net}'"
                )
    return True, None


# Map common chain IDs to canonical network names (partial list; extend as needed)
_CHAIN_ID_TO_NETWORK = {
    42161: "arbitrum",
    8453: "base",
    59144: "linea",
    5000: "mantle",
    534352: "scroll",
    324: "zksync",
}

# v1.12.2: Host patterns for chain validation
_CHAIN_ID_HOST_PATTERNS = {
    42161: ["arb", "arbitrum"],
    8453: ["base"],
    59144: ["linea"],
    5000: ["mantle"],
    534352: ["scroll"],
    324: ["zksync"],
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
    
    Resolution order:
    1. Chain-scoped env var (e.g. BASE_RPC) — preferred for dRPC/premium
    2. Global explicit env var (ALCHEMY_RPC_HTTP / ARBY_RPC_HTTP_PRIMARY)
    3. Alchemy API key
    4. Public fallback
    
    v3.2.32: Chain-safety validation - explicit env vars are only used if they
    match the requested chain_id. This prevents multi-chain scans from using
    wrong-chain endpoints (e.g., Arbitrum endpoint for Base scan).
    """
    env = env or {}
    diagnostics = {}

    net = _normalize_network_from_chain(chain_id, env.get("NETWORK") or network)

    # 1) Chain-scoped env var (e.g. BASE_RPC, ARBITRUM_RPC)
    if net and net in _CHAIN_ENV_VARS:
        http_var, _ws_var = _CHAIN_ENV_VARS[net]
        chain_url = env.get(http_var)
        if chain_url:
            # Validate dRPC chain match
            drpc_ok, drpc_err = validate_drpc_url(chain_url, net)
            if not drpc_ok:
                diagnostics["skipped_chain_env"] = drpc_err
                # Fall through to other resolution
            else:
                prov = classify_provider(chain_url)
                diagnostics["source"] = f"chain_env_{http_var}"
                return chain_url, prov, diagnostics

    # 2) Prefer explicit env var ONLY if it matches the requested chain_id
    http = env.get("ALCHEMY_RPC_HTTP") or env.get("ARBY_RPC_HTTP_PRIMARY")
    if http:
        # v3.2.32: Validate chain_id consistency before using explicit env var
        if chain_id is not None:
            from urllib.parse import urlparse
            host = urlparse(http).netloc
            is_valid, error_msg = validate_chain_rpc_consistency(chain_id, host)
            if not is_valid:
                diagnostics["skipped_explicit"] = error_msg
                # Fall through to chain-aware resolution below
            else:
                diagnostics["source"] = "explicit"
                return http, classify_provider(http), diagnostics
        else:
            # No chain_id specified, use explicit env var as-is
            diagnostics["source"] = "explicit"
            return http, classify_provider(http), diagnostics

    # 3) Build from api key if present
    api = env.get("ALCHEMY_API_KEY")
    diagnostics["normalized_network"] = net
    if api and net:
        url = build_alchemy_http_url(net, api)
        if url:
            diagnostics["source"] = "alchemy_api_key"
            return url, "alchemy", diagnostics

    # 4) Fallback to public
    fb = public_fallback_for(net)
    if fb:
        diagnostics["source"] = "public_fallback"
        return fb, "public", diagnostics

    diagnostics["source"] = "none"
    return None, "unknown", diagnostics


def resolve_rpc_ws(chain_id: Optional[int] = None, network: Optional[str] = None, env: Optional[dict] = None):
    """Resolve a WS (wss) URL similarly to resolve_rpc_http.

    Returns tuple (url_or_none, provider_name, diagnostics_dict).

    Resolution order:
    1. Chain-scoped env var (e.g. BASE_WSS, ARBITRUM_WSS)
    2. Global explicit env var (ALCHEMY_RPC_WS / ARBY_RPC_WS_PRIMARY)
    3. Alchemy API key
    4. Public WS fallback (publicnode)
    """
    env = env or {}
    diagnostics = {}

    net = _normalize_network_from_chain(chain_id, env.get("NETWORK") or network)

    # 1) Chain-scoped env var
    if net and net in _CHAIN_ENV_VARS:
        _http_var, ws_var = _CHAIN_ENV_VARS[net]
        chain_ws = env.get(ws_var)
        if chain_ws:
            drpc_ok, drpc_err = validate_drpc_url(chain_ws, net)
            if not drpc_ok:
                diagnostics["skipped_chain_env"] = drpc_err
            else:
                prov = classify_provider(chain_ws)
                diagnostics["source"] = f"chain_env_{ws_var}"
                return chain_ws, prov, diagnostics

    # 2) v3.2.32: Validate chain_id consistency for WS too
    ws = env.get("ALCHEMY_RPC_WS") or env.get("ARBY_RPC_WS_PRIMARY")
    if ws:
        if chain_id is not None:
            from urllib.parse import urlparse
            host = urlparse(ws).netloc
            is_valid, error_msg = validate_chain_rpc_consistency(chain_id, host)
            if not is_valid:
                diagnostics["skipped_explicit"] = error_msg
                # Fall through to chain-aware resolution below
            else:
                diagnostics["source"] = "explicit"
                return ws, classify_provider(ws), diagnostics
        else:
            diagnostics["source"] = "explicit"
            return ws, classify_provider(ws), diagnostics

    # 3) Alchemy API key
    api = env.get("ALCHEMY_API_KEY")
    diagnostics["normalized_network"] = net
    if api and net:
        url = build_alchemy_ws_url(net, api)
        if url:
            diagnostics["source"] = "alchemy_api_key"
            return url, "alchemy", diagnostics

    # 4) Fallback to public WS endpoints
    if net and net in _PUBLIC_WS_FALLBACKS:
        diagnostics["source"] = "public_ws_fallback"
        return _PUBLIC_WS_FALLBACKS[net], "publicnode", diagnostics

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
    "scroll": 534352,
    "zksync": 324,
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


