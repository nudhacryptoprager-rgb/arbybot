# PATH: discovery/graph_client.py
"""
The Graph API client for on-chain pool discovery.

Queries subgraph APIs to discover high-TVL pools on supported chains,
supplementing the static intent.txt universe with dynamically discovered pairs.

Supported subgraphs:
  - Uniswap V3 on Base (decentralized network)
  - Aerodrome on Base (decentralized network)

Usage:
    from discovery.graph_client import discover_graph_pools

    pools = discover_graph_pools(
        chain="base",
        min_tvl_usd=10_000,
        max_pools=50,
    )

Environment:
    GRAPH_API_KEY — optional API key for The Graph decentralized network.
                    Without it, uses free public gateway (rate-limited).
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("discovery.graph_client")

# ---------------------------------------------------------------------------
# Subgraph registry — maps (chain, protocol) to subgraph IDs on The Graph
# decentralized network, plus free hosted fallback URLs.
# ---------------------------------------------------------------------------

# The Graph decentralized gateway
_GRAPH_GATEWAY = "https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{subgraph_id}"

# Subgraph IDs for The Graph decentralized network
_SUBGRAPH_IDS: Dict[str, Dict[str, str]] = {
    "base": {
        # Uniswap V3 on Base — official deployment
        "uniswap_v3": "GqzP4Xaehti8KSfQMv2GDGqA8hS3gcv9n2wSAePEzFRo",
        # Aerodrome (Velodrome fork on Base) — community subgraph
        "aerodrome": "GENunHLLfqLFKEgVrTe4LQrmRFnMiV7JohvGEupuwTz4",
    },
}

# Free hosted service fallback URLs (no API key needed, may be deprecated)
_HOSTED_FALLBACKS: Dict[str, Dict[str, str]] = {
    "base": {
        "uniswap_v3": "https://api.studio.thegraph.com/query/48211/uniswap-v3-base/version/latest",
        "aerodrome": "https://api.studio.thegraph.com/query/50873/aerodrome-base/version/latest",
    },
}

def _token_symbols_for_chain(chain: str) -> Dict[str, str]:
    """Address → symbol from config/core_tokens.yaml (not inline hardcode)."""
    from m9.graph_arb.core_tokens_loader import address_symbol_map

    return {k.lower(): v for k, v in address_symbol_map(chain).items()}


@dataclass
class GraphPool:
    """A pool discovered via The Graph API."""
    chain: str
    protocol: str          # e.g. "uniswap_v3", "aerodrome"
    pool_address: str
    token0_address: str
    token0_symbol: str
    token0_decimals: int
    token1_address: str
    token1_symbol: str
    token1_decimals: int
    fee_tier: int          # in ppm (e.g. 3000 = 0.3%)
    tvl_usd: float
    volume_usd_24h: float

    @property
    def pair_key(self) -> str:
        t0, t1 = sorted([self.token0_symbol, self.token1_symbol])
        return f"{t0}/{t1}"


def _get_graph_url(chain: str, protocol: str) -> Optional[str]:
    """Get the best available Graph API URL for a chain/protocol."""
    api_key = os.environ.get("GRAPH_API_KEY", "").strip()

    # Prefer decentralized network with API key
    subgraph_id = _SUBGRAPH_IDS.get(chain, {}).get(protocol)
    if api_key and subgraph_id:
        return _GRAPH_GATEWAY.format(api_key=api_key, subgraph_id=subgraph_id)

    # Fallback to hosted service (free, rate-limited)
    fallback = _HOSTED_FALLBACKS.get(chain, {}).get(protocol)
    if fallback:
        return fallback

    return None


def _graphql_query(url: str, query: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """Execute a GraphQL query against a subgraph endpoint."""
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available, falling back to urllib")
        return _graphql_query_urllib(url, query, timeout)

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json={"query": query})
            resp.raise_for_status()
            data = resp.json()
            if "errors" in data:
                logger.warning("GraphQL errors: %s", data["errors"][:2])
                return None
            return data.get("data")
    except Exception as e:
        logger.warning("Graph query failed: %s %s", type(e).__name__, e)
        return None


def _graphql_query_urllib(url: str, query: str, timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """Fallback GraphQL query using stdlib urllib."""
    import json
    import urllib.request

    payload = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "errors" in data:
                logger.warning("GraphQL errors: %s", data["errors"][:2])
                return None
            return data.get("data")
    except Exception as e:
        logger.warning("Graph query (urllib) failed: %s %s", type(e).__name__, e)
        return None


def _query_uniswap_v3_pools(
    chain: str,
    min_tvl_usd: float = 10_000,
    max_pools: int = 50,
) -> List[GraphPool]:
    """Query Uniswap V3 subgraph for top pools by TVL."""
    url = _get_graph_url(chain, "uniswap_v3")
    if not url:
        logger.debug("No Graph URL for %s/uniswap_v3", chain)
        return []

    query = """
    {
      pools(
        first: %d,
        orderBy: totalValueLockedUSD,
        orderDirection: desc,
        where: { totalValueLockedUSD_gt: "%s" }
      ) {
        id
        token0 { id symbol decimals }
        token1 { id symbol decimals }
        feeTier
        totalValueLockedUSD
        volumeUSD
      }
    }
    """ % (max_pools, str(min_tvl_usd))

    data = _graphql_query(url, query)
    if not data or "pools" not in data:
        logger.info("No Uniswap V3 pools returned for %s", chain)
        return []

    results = []
    for p in data["pools"]:
        try:
            t0_addr = p["token0"]["id"].lower()
            t1_addr = p["token1"]["id"].lower()
            t0_sym = p["token0"].get("symbol", "") or _token_symbols_for_chain(chain).get(t0_addr, "")
            t1_sym = p["token1"].get("symbol", "") or _token_symbols_for_chain(chain).get(t1_addr, "")
            t0_dec = int(p["token0"].get("decimals", 18))
            t1_dec = int(p["token1"].get("decimals", 18))

            results.append(GraphPool(
                chain=chain,
                protocol="uniswap_v3",
                pool_address=p["id"],
                token0_address=t0_addr,
                token0_symbol=t0_sym,
                token0_decimals=t0_dec,
                token1_address=t1_addr,
                token1_symbol=t1_sym,
                token1_decimals=t1_dec,
                fee_tier=int(p.get("feeTier", 3000)),
                tvl_usd=float(p.get("totalValueLockedUSD", 0)),
                volume_usd_24h=float(p.get("volumeUSD", 0)),
            ))
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("Skipping malformed pool: %s", e)
            continue

    logger.info("Graph: %d Uniswap V3 pools on %s (TVL > $%s)", len(results), chain, min_tvl_usd)
    return results


def _query_aerodrome_pools(
    chain: str,
    min_tvl_usd: float = 10_000,
    max_pools: int = 50,
) -> List[GraphPool]:
    """Query Aerodrome subgraph for top pools by TVL."""
    url = _get_graph_url(chain, "aerodrome")
    if not url:
        logger.debug("No Graph URL for %s/aerodrome", chain)
        return []

    # Aerodrome uses Solidly-style schema — pool entity names may vary
    query = """
    {
      pools(
        first: %d,
        orderBy: totalValueLockedUSD,
        orderDirection: desc,
        where: { totalValueLockedUSD_gt: "%s" }
      ) {
        id
        token0 { id symbol decimals }
        token1 { id symbol decimals }
        isStable
        totalValueLockedUSD
        volumeUSD
      }
    }
    """ % (max_pools, str(min_tvl_usd))

    data = _graphql_query(url, query)
    if not data or "pools" not in data:
        logger.info("No Aerodrome pools returned for %s", chain)
        return []

    results = []
    for p in data["pools"]:
        try:
            t0_addr = p["token0"]["id"].lower()
            t1_addr = p["token1"]["id"].lower()
            t0_sym = p["token0"].get("symbol", "") or _token_symbols_for_chain(chain).get(t0_addr, "")
            t1_sym = p["token1"].get("symbol", "") or _token_symbols_for_chain(chain).get(t1_addr, "")
            t0_dec = int(p["token0"].get("decimals", 18))
            t1_dec = int(p["token1"].get("decimals", 18))
            is_stable = p.get("isStable", False)
            # Aerodrome ve33: fee=1 for stable, fee=0 for volatile
            fee_tier = 1 if is_stable else 0

            results.append(GraphPool(
                chain=chain,
                protocol="aerodrome",
                pool_address=p["id"],
                token0_address=t0_addr,
                token0_symbol=t0_sym,
                token0_decimals=t0_dec,
                token1_address=t1_addr,
                token1_symbol=t1_sym,
                token1_decimals=t1_dec,
                fee_tier=fee_tier,
                tvl_usd=float(p.get("totalValueLockedUSD", 0)),
                volume_usd_24h=float(p.get("volumeUSD", 0)),
            ))
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("Skipping malformed Aerodrome pool: %s", e)
            continue

    logger.info("Graph: %d Aerodrome pools on %s (TVL > $%s)", len(results), chain, min_tvl_usd)
    return results


def _query_pools_for_token(
    chain: str,
    protocol: str,
    token_address: str,
    max_pools: int = 20,
) -> List[GraphPool]:
    """Query subgraph for pools containing *token_address* (M8.2 hint layer)."""
    url = _get_graph_url(chain, protocol)
    if not url:
        return []
    addr = token_address.lower()
    if protocol == "uniswap_v3":
        query = """
        {
          pools(
            first: %d,
            orderBy: totalValueLockedUSD,
            orderDirection: desc,
            where: {
              or: [
                { token0: "%s" },
                { token1: "%s" }
              ]
            }
          ) {
            id
            token0 { id symbol decimals }
            token1 { id symbol decimals }
            feeTier
            totalValueLockedUSD
            volumeUSD
          }
        }
        """ % (max_pools, addr, addr)
    elif protocol == "aerodrome":
        query = """
        {
          pools(
            first: %d,
            orderBy: totalValueLockedUSD,
            orderDirection: desc,
            where: {
              or: [
                { token0: "%s" },
                { token1: "%s" }
              ]
            }
          ) {
            id
            token0 { id symbol decimals }
            token1 { id symbol decimals }
            isStable
            totalValueLockedUSD
            volumeUSD
          }
        }
        """ % (max_pools, addr, addr)
    else:
        return []

    data = _graphql_query(url, query)
    if not data or "pools" not in data:
        return []

    results: List[GraphPool] = []
    for p in data["pools"]:
        try:
            t0_addr = p["token0"]["id"].lower()
            t1_addr = p["token1"]["id"].lower()
            t0_sym = p["token0"].get("symbol", "") or _token_symbols_for_chain(chain).get(t0_addr, "")
            t1_sym = p["token1"].get("symbol", "") or _token_symbols_for_chain(chain).get(t1_addr, "")
            fee_tier = int(p.get("feeTier", 3000)) if protocol == "uniswap_v3" else (
                1 if p.get("isStable", False) else 0
            )
            results.append(
                GraphPool(
                    chain=chain,
                    protocol=protocol,
                    pool_address=p["id"],
                    token0_address=t0_addr,
                    token0_symbol=t0_sym,
                    token0_decimals=int(p["token0"].get("decimals", 18)),
                    token1_address=t1_addr,
                    token1_symbol=t1_sym,
                    token1_decimals=int(p["token1"].get("decimals", 18)),
                    fee_tier=fee_tier,
                    tvl_usd=float(p.get("totalValueLockedUSD", 0) or 0),
                    volume_usd_24h=float(p.get("volumeUSD", 0) or 0),
                )
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("Skipping malformed token pool: %s", e)
            continue
    return results


def query_pools_by_token(
    chain: str,
    token_address: str,
    *,
    max_pools: int = 20,
    protocols: Optional[List[str]] = None,
) -> List[GraphPool]:
    """Discover pools for a specific token via The Graph (hint-only)."""
    available = _SUBGRAPH_IDS.get(chain, {}) or _HOSTED_FALLBACKS.get(chain, {})
    if not available:
        return []
    query_protocols = protocols or list(available.keys())
    all_pools: List[GraphPool] = []
    for proto in query_protocols:
        if proto in ("uniswap_v3", "aerodrome"):
            all_pools.extend(
                _query_pools_for_token(chain, proto, token_address, max_pools=max_pools)
            )
    seen: set = set()
    deduped: List[GraphPool] = []
    for pool in sorted(all_pools, key=lambda p: p.tvl_usd, reverse=True):
        addr = pool.pool_address.lower()
        if addr not in seen:
            seen.add(addr)
            deduped.append(pool)
    logger.info(
        "Graph token pools: %d for %s on %s",
        len(deduped),
        token_address[:10],
        chain,
    )
    return deduped


def discover_graph_pools(
    chain: str,
    min_tvl_usd: float = 10_000,
    max_pools: int = 50,
    protocols: Optional[List[str]] = None,
) -> List[GraphPool]:
    """Discover pools via The Graph API across all supported protocols for a chain.

    Args:
        chain: Chain key (e.g. "base")
        min_tvl_usd: Minimum TVL threshold in USD
        max_pools: Max pools per protocol to return
        protocols: Specific protocols to query (default: all available)

    Returns:
        List of GraphPool objects sorted by TVL descending
    """
    available = _SUBGRAPH_IDS.get(chain, {})
    if not available:
        available = _HOSTED_FALLBACKS.get(chain, {})
    if not available:
        logger.info("No Graph subgraphs configured for chain %s", chain)
        return []

    query_protocols = protocols or list(available.keys())
    all_pools: List[GraphPool] = []

    for proto in query_protocols:
        if proto == "uniswap_v3":
            all_pools.extend(_query_uniswap_v3_pools(chain, min_tvl_usd, max_pools))
        elif proto == "aerodrome":
            all_pools.extend(_query_aerodrome_pools(chain, min_tvl_usd, max_pools))
        else:
            logger.debug("Unknown protocol %s for Graph discovery", proto)

    # Sort by TVL descending, deduplicate by pool address
    seen = set()
    deduped = []
    for pool in sorted(all_pools, key=lambda p: p.tvl_usd, reverse=True):
        addr = pool.pool_address.lower()
        if addr not in seen:
            seen.add(addr)
            deduped.append(pool)

    logger.info(
        "Graph discovery: %d total pools on %s (min_tvl=$%s)",
        len(deduped), chain, min_tvl_usd,
    )
    return deduped


def graph_pools_to_intent_pairs(
    pools: List[GraphPool],
    known_tokens: Optional[set] = None,
) -> List[str]:
    """Convert GraphPool list to intent.txt format lines.

    Only includes pools where both token symbols are known (in core_tokens.yaml).
    This ensures the discovery pipeline can resolve addresses.

    Args:
        pools: List of GraphPool objects
        known_tokens: Set of known token symbols for the chain.
                      If None, all pools are included.

    Returns:
        List of intent lines like ["base:cbBTC/USDC", "base:AERO/WETH"]
    """
    intent_lines = []
    seen = set()

    for pool in pools:
        sym0 = pool.token0_symbol.upper()
        sym1 = pool.token1_symbol.upper()

        if not sym0 or not sym1:
            continue

        # Filter to known tokens if provided
        if known_tokens is not None:
            if sym0 not in known_tokens or sym1 not in known_tokens:
                continue

        # Canonical ordering
        t0, t1 = sorted([sym0, sym1])
        pair_key = f"{pool.chain}:{t0}/{t1}"
        if pair_key in seen:
            continue
        seen.add(pair_key)
        intent_lines.append(pair_key)

    logger.info("Graph→intent: %d unique pairs from %d pools", len(intent_lines), len(pools))
    return intent_lines
