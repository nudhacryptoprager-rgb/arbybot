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

# Extended public HTTP fallback pool (no API key required).
# Used by ProviderRouter polyglot fanout when ARBY_USE_PUBLIC_POOL=1.
# Ordered roughly by observed reliability/latency (best first).
_PUBLIC_HTTP_FALLBACKS = {
    "base": [
        "https://mainnet.base.org",
        "https://base-rpc.publicnode.com",
        "https://base.llamarpc.com",
        "https://base.blockpi.network/v1/rpc/public",
        "https://1rpc.io/base",
        "https://base.meowrpc.com",
        "https://base-mainnet.public.blastapi.io",
        "https://endpoints.omniatech.io/v1/base/mainnet/public",
    ],
    "arbitrum": [
        "https://arb1.arbitrum.io/rpc",
        "https://arbitrum-one-rpc.publicnode.com",
        "https://arbitrum.llamarpc.com",
        "https://arbitrum.blockpi.network/v1/rpc/public",
        "https://1rpc.io/arb",
        "https://arbitrum.meowrpc.com",
        "https://arbitrum-one.public.blastapi.io",
    ],
    "linea": [
        "https://rpc.linea.build",
        "https://linea-rpc.publicnode.com",
        "https://1rpc.io/linea",
    ],
    "mantle": [
        "https://rpc.mantle.xyz",
        "https://mantle-rpc.publicnode.com",
        "https://1rpc.io/mantle",
    ],
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


# Host substrings indicating rate-limited / non-dedicated public endpoints.
_PUBLIC_RPC_HOST_MARKERS = (
    "publicnode.com",
    "mainnet.base.org",
    "llamarpc.com",
    "blastapi.io",
    "1rpc.io",
    "meowrpc.com",
    "blockpi.network/v1/rpc/public",
    "omniatech.io/v1/",
)


def is_public_rpc_url(url: Optional[str]) -> bool:
    """True when URL looks like a free/public RPC endpoint."""
    u = (url or "").strip().lower()
    if not u:
        return True
    return any(marker in u for marker in _PUBLIC_RPC_HOST_MARKERS)


def require_dedicated_rpc_or_raise(
    url: Optional[str],
    *,
    chain: str = "base",
    env: Optional[dict] = None,
) -> None:
    """Hard-fail when ARBY_REQUIRE_DEDICATED_RPC=1 and URL is public."""
    import os

    env = env if env is not None else os.environ
    flag = str(env.get("ARBY_REQUIRE_DEDICATED_RPC", "")).strip().lower()
    if flag not in ("1", "true", "yes"):
        return
    if is_public_rpc_url(url):
        raise RuntimeError(
            f"ARBY_REQUIRE_DEDICATED_RPC=1: refusing public RPC for chain={chain!r} "
            f"url={url!r}. Set BASE_RPC_PRIMARY to a dedicated provider."
        )


def iter_dedicated_http_providers(
    chain: str = "base",
    *,
    env: Optional[dict] = None,
) -> list[tuple[str, str]]:
    """Collect non-public HTTP RPC URLs for A/B (labels are provider class or role)."""
    import os

    env = dict(env if env is not None else os.environ)
    chain_key = chain.lower().strip()
    prefix = chain_key.upper()
    seen: set[str] = set()
    out: list[tuple[str, str]] = []

    def add(url: str, label: str) -> None:
        u = (url or "").strip()
        if not u or u in seen or is_public_rpc_url(u):
            return
        seen.add(u)
        out.append((label, u))

    primary = (env.get(f"{prefix}_RPC_PRIMARY") or "").strip()
    if primary:
        add(primary, "primary")

    api = (env.get("ALCHEMY_API_KEY") or "").strip()
    if api:
        url = build_alchemy_http_url(chain_key, api)
        if url:
            add(url, "alchemy")

    secondary = (env.get(f"{prefix}_RPC_SECONDARY") or "").strip()
    if secondary:
        add(secondary, "secondary")

    for key in ("DRPC_BASE_HTTP", "DRPC_HTTP", "ALCHEMY_BASE_HTTP"):
        val = (env.get(key) or "").strip()
        if val:
            add(val, classify_provider(val))

    if not primary:
        fallback = (env.get(f"{prefix}_RPC") or "").strip()
        if fallback:
            add(fallback, classify_provider(fallback))

    wss = (env.get(f"{prefix}_WSS") or "").strip()
    if wss.startswith("wss://"):
        add("https://" + wss[6:], classify_provider(wss))
    elif wss.startswith("ws://"):
        add("http://" + wss[5:], classify_provider(wss))

    if not out:
        chain_id = _CHAIN_KEY_TO_ID.get(chain_key)
        http, prov, _ = resolve_rpc_http(chain_id=chain_id, network=chain_key, env=env)
        if http:
            add(http, prov if prov != "public" else "resolved")

    return out


def apply_productive_rpc_env(
    chain: str = "base",
    *,
    env: Optional[dict] = None,
) -> dict:
    """Return env dict with Alchemy primary, dRPC secondary, dedicated policy flags."""
    import os

    base = dict(env if env is not None else os.environ)
    providers = iter_dedicated_http_providers(chain, env=base)
    alchemy_url = ""
    drpc_url = ""
    for _label, url in providers:
        prov = classify_provider(url)
        if prov == "alchemy" and not alchemy_url:
            alchemy_url = url
        elif prov == "drpc" and not drpc_url:
            drpc_url = url
    if not alchemy_url:
        raise RuntimeError(
            "No Alchemy HTTP URL: set ALCHEMY_API_KEY or BASE_RPC_PRIMARY in .env"
        )
    prefix = chain.upper()
    out = dict(base)
    out[f"{prefix}_RPC_PRIMARY"] = alchemy_url
    if drpc_url:
        out[f"{prefix}_RPC_SECONDARY"] = drpc_url
    out[f"{prefix}_RPC"] = alchemy_url
    out["ARBY_REQUIRE_DEDICATED_RPC"] = "1"
    out["ARBY_PROVIDER_POOL_MODE"] = "weighted"
    out.setdefault("ARBY_USE_PUBLIC_POOL", "0")
    return out


def resolve_productive_http_rpc(chain: str = "base", *, env: Optional[dict] = None) -> str:
    """Dedicated HTTP URL for depth/quote (Alchemy preferred)."""
    env = apply_productive_rpc_env(chain, env=env)
    return env[f"{chain.upper()}_RPC_PRIMARY"]


def print_rpc_env_contract(chain: str = "base", *, env: Optional[dict] = None) -> None:
    """Print env presence / policy flags without secret values."""
    import os

    env = dict(env if env is not None else os.environ)
    prefix = chain.upper()
    keys = (
        f"{prefix}_RPC_PRIMARY",
        f"{prefix}_RPC_SECONDARY",
        f"{prefix}_WSS",
        "ALCHEMY_API_KEY",
        "ARBY_REQUIRE_DEDICATED_RPC",
        "ARBY_PROVIDER_POOL_MODE",
        "ARBY_USE_PUBLIC_POOL",
    )

    def _present(key: str) -> bool:
        return bool((env.get(key) or "").strip())

    print("RPC env contract (values redacted):")
    for key in keys:
        if key.startswith("ARBY_"):
            val = (env.get(key) or "").strip()
            print(f"  {key}={val or '(unset)'}")
        else:
            present = _present(key)
            pub = False
            if present:
                pub = is_public_rpc_url(env.get(key))
            print(f"  {key}: present={present} public={pub}")
    dedicated = iter_dedicated_http_providers(chain, env=env)
    print(f"  dedicated_http_providers: {len(dedicated)} ({', '.join(l[0] for l in dedicated) or 'none'})")


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
    if "flashblocks" in low or "preconf" in low:
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


def _env_rpc_url(env: dict, key: str) -> Optional[str]:
    val = (env.get(key) or "").strip()
    return val or None


def _validated_http_url(
    url: Optional[str],
    net: Optional[str],
    diagnostics: dict,
) -> tuple[Optional[str], Optional[str]]:
    """Return (url, provider) when *url* passes dRPC chain validation."""
    if not url:
        return None, None
    if net:
        drpc_ok, drpc_err = validate_drpc_url(url, net)
        if not drpc_ok:
            diagnostics.setdefault("skipped_urls", []).append(
                {"url": url[:80], "reason": drpc_err}
            )
            return None, None
    return url, classify_provider(url)


def resolve_sniper_rpc_lane(
    chain_id: Optional[int] = None,
    network: Optional[str] = None,
    env: Optional[dict] = None,
    override: Optional[str] = None,
):
    """Resolve HTTP endpoints for M8 sniper discovery (eth_getLogs lane).

    Primary priority (discovery lane, separate from M9 quote PRIMARY):
        1. CLI override (``--rpc-url``)
        2. ``{CHAIN}_SNIPER_RPC_PRIMARY``
        3. ``{CHAIN}_RPC_SECONDARY`` (often dRPC — better for bounded getLogs)
        4. ``resolve_rpc_http()`` productive PRIMARY

    Secondary priority (getLogs failover target):
        1. ``{CHAIN}_SNIPER_RPC_SECONDARY``
        2. ``{CHAIN}_RPC_PRIMARY`` (when distinct from primary)
        3. ``{CHAIN}_RPC_SECONDARY`` (when distinct from primary)

    Returns
    -------
    (primary_url, primary_provider, secondary_url_or_none, secondary_provider_or_none, diagnostics)
    """
    env = env or {}
    diagnostics: dict = {}
    net = _normalize_network_from_chain(chain_id, env.get("NETWORK") or network)
    prefix = (net or "base").upper()

    primary_url: Optional[str] = None
    primary_provider: Optional[str] = None
    primary_source: Optional[str] = None

    if override and override.strip():
        primary_url, primary_provider = _validated_http_url(
            override.strip(), net, diagnostics
        )
        primary_source = "cli_override"
    elif net:
        sniper_pri_var = f"{prefix}_SNIPER_RPC_PRIMARY"
        primary_url, primary_provider = _validated_http_url(
            _env_rpc_url(env, sniper_pri_var), net, diagnostics
        )
        if primary_url:
            primary_source = sniper_pri_var

    if not primary_url and net:
        sec_var = f"{prefix}_RPC_SECONDARY"
        primary_url, primary_provider = _validated_http_url(
            _env_rpc_url(env, sec_var), net, diagnostics
        )
        if primary_url:
            primary_source = sec_var

    if not primary_url:
        url, prov, prod_diag = resolve_rpc_http(
            chain_id=chain_id, network=net, env=env
        )
        diagnostics["productive_resolve"] = prod_diag
        if url:
            primary_url, primary_provider = url, prov
            primary_source = prod_diag.get("source", "productive_primary")

    if not primary_url:
        fb = public_fallback_for(net)
        if fb:
            primary_url, primary_provider = fb, classify_provider(fb)
            primary_source = "public_fallback"

    if not primary_url or not primary_provider:
        raise RuntimeError(
            f"No sniper RPC URL for network={net!r}. "
            f"Set {prefix}_SNIPER_RPC_PRIMARY, {prefix}_RPC_SECONDARY, "
            f"or pass --rpc-url."
        )

    secondary_url: Optional[str] = None
    secondary_provider: Optional[str] = None
    secondary_source: Optional[str] = None

    if net:
        sniper_sec_var = f"{prefix}_SNIPER_RPC_SECONDARY"
        secondary_url, secondary_provider = _validated_http_url(
            _env_rpc_url(env, sniper_sec_var), net, diagnostics
        )
        if secondary_url == primary_url:
            secondary_url, secondary_provider = None, None
        elif secondary_url:
            secondary_source = sniper_sec_var

    if not secondary_url and net:
        pri_var = f"{prefix}_RPC_PRIMARY"
        secondary_url, secondary_provider = _validated_http_url(
            _env_rpc_url(env, pri_var), net, diagnostics
        )
        if secondary_url == primary_url:
            secondary_url, secondary_provider = None, None
        elif secondary_url:
            secondary_source = pri_var

    if not secondary_url and net:
        sec_var = f"{prefix}_RPC_SECONDARY"
        secondary_url, secondary_provider = _validated_http_url(
            _env_rpc_url(env, sec_var), net, diagnostics
        )
        if secondary_url == primary_url:
            secondary_url, secondary_provider = None, None
        elif secondary_url:
            secondary_source = sec_var

    diagnostics["primary_source"] = primary_source
    diagnostics["secondary_source"] = secondary_source
    return primary_url, primary_provider, secondary_url, secondary_provider, diagnostics


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

    # 1) Chain-scoped env var (e.g. BASE_RPC_PRIMARY, BASE_RPC)
    if net and net in _CHAIN_ENV_VARS:
        http_var, _ws_var = _CHAIN_ENV_VARS[net]
        primary_var = f"{net.upper()}_RPC_PRIMARY"
        chain_url = (env.get(primary_var) or "").strip() or None
        if not chain_url:
            fallback = (env.get(http_var) or "").strip()
            if fallback and not is_public_rpc_url(fallback):
                chain_url = fallback
            elif fallback and is_public_rpc_url(fallback):
                diagnostics["skipped_public_chain_env"] = http_var
        if chain_url:
            # Validate dRPC chain match
            drpc_ok, drpc_err = validate_drpc_url(chain_url, net)
            if not drpc_ok:
                diagnostics["skipped_chain_env"] = drpc_err
                # Fall through to other resolution
            else:
                prov = classify_provider(chain_url)
                src = f"chain_env_{primary_var}" if env.get(primary_var) else f"chain_env_{http_var}"
                diagnostics["source"] = src
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
    0. (NEW) ARBY_FORCE_PUBLIC_WS=1 — short-circuit straight to publicnode
       fallback. Used when premium providers (drpc/alchemy) are 429-storming
       and we want the system to keep flowing on a free public WS endpoint.
    1. Chain-scoped env var (e.g. BASE_WSS, ARBITRUM_WSS)
    2. Global explicit env var (ALCHEMY_RPC_WS / ARBY_RPC_WS_PRIMARY)
    3. Alchemy API key
    4. Public WS fallback (publicnode)
    """
    env = env or {}
    diagnostics = {}

    net = _normalize_network_from_chain(chain_id, env.get("NETWORK") or network)

    # 0) Force-public override — bypass premium providers entirely.
    if str(env.get("ARBY_FORCE_PUBLIC_WS", "")).strip() == "1":
        if net and net in _PUBLIC_WS_FALLBACKS:
            diagnostics["source"] = "force_public_ws"
            diagnostics["normalized_network"] = net
            return _PUBLIC_WS_FALLBACKS[net], "publicnode", diagnostics

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


def iter_public_http_fallbacks(network: Optional[str]) -> list:
    """Return ordered list of free public HTTP RPC endpoints for *network*.

    Used by polyglot fanout in ``ProviderRouter`` to spread load across
    multiple no-API-key endpoints (publicnode, llamarpc, blockpi, ...).

    Returns an empty list if the network is unknown.
    """
    net = _normalize_network(network)
    if not net:
        return []
    return list(_PUBLIC_HTTP_FALLBACKS.get(net, ()))
