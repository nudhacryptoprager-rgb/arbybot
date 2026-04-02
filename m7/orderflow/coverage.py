"""
M7 orderflow token admission, counter-venue coverage scanning,
and subgraph-backed token seeding.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from m7.shared.constants import (
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_SUBGRAPH_VERIFIED,
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_REJECTED,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_NO_COUNTER_POOL,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
    SUBGRAPH_ENDPOINTS_ARBITRUM,
    SUBGRAPH_SEED_TOKEN_CAP,
    SUBGRAPH_TIMEOUT_SECONDS,
    _DEFAULT_FEE_TIERS,
)
from m7.orderflow.resolve import (
    _resolve_pool_addresses_multicall,
    enrich_tokens_batch,
)

logger = logging.getLogger("m7.orderflow.coverage")

def admit_event_tokens(
    token_in_addr: str,
    token_out_addr: str,
    addr_to_symbol: Dict[str, str],
    canonical_token_addrs: Dict[str, str],
) -> Dict[str, Any]:
    """Check whether event tokens are admissible for quoting.

    A token is 'admitted' if its address maps to a known symbol in
    canonical_token_addrs OR in addr_to_symbol.  This allows temporary
    admission of tokens resolved from pool contracts even if they are
    not in the canonical narrow universe.

    M7.A.5.7: Returns admission_source to disambiguate how tokens were admitted.

    Returns dict with:
        admitted: bool
        token_in_symbol: str or None
        token_out_symbol: str or None
        token_in_known: bool   # in canonical universe
        token_out_known: bool
        blocker_reason: str or None
        admission_source: str  # canonical_core | addr_to_symbol | subgraph_seeded_verified | rejected_unverified
    """
    reverse_canonical = {v.lower(): k for k, v in canonical_token_addrs.items() if v}
    in_sym = addr_to_symbol.get(token_in_addr.lower()) or reverse_canonical.get(token_in_addr.lower())
    out_sym = addr_to_symbol.get(token_out_addr.lower()) or reverse_canonical.get(token_out_addr.lower())
    in_known = token_in_addr.lower() in reverse_canonical
    out_known = token_out_addr.lower() in reverse_canonical

    # Admitted if we have ANY symbol mapping (even truncated addr fallback is NOT admitted)
    in_admitted = in_sym is not None and len(in_sym) > 10  # truncated addrs are <=10
    out_admitted = out_sym is not None and len(out_sym) > 10
    # But canonical tokens are always admitted regardless of symbol length
    if in_known:
        in_admitted = True
    if out_known:
        out_admitted = True
    # Also admit if addr_to_symbol returned a real symbol (not a truncated address)
    if in_sym and not in_sym.startswith("0x"):
        in_admitted = True
    if out_sym and not out_sym.startswith("0x"):
        out_admitted = True

    admitted = in_admitted and out_admitted
    blocker = None
    if not in_admitted and not out_admitted:
        blocker = "both_tokens_unknown"
    elif not in_admitted:
        blocker = "token_in_unknown"
    elif not out_admitted:
        blocker = "token_out_unknown"

    # M7.A.5.7: Determine admission source
    if not admitted:
        admission_source = ADMISSION_REJECTED
    elif in_known and out_known:
        admission_source = ADMISSION_CANONICAL
    elif in_known or out_known:
        # One canonical, one from addr_to_symbol mapping
        admission_source = ADMISSION_ADDR_TO_SYMBOL
    else:
        # Both from addr_to_symbol (e.g. subgraph-seeded tokens verified on-chain)
        admission_source = ADMISSION_ADDR_TO_SYMBOL

    return {
        "admitted": admitted,
        "token_in_symbol": in_sym,
        "token_out_symbol": out_sym,
        "token_in_known": in_known,
        "token_out_known": out_known,
        "blocker_reason": blocker,
        "admission_source": admission_source,
    }



def counter_venue_coverage_scan(
    token_in_addr: str,
    token_out_addr: str,
    dex_configs: Dict[str, Any],
    rpc_url: str,
    block_num: int,
    pool_registry: Any = None,
) -> Dict[str, Any]:
    """Scan counter-venue coverage for a resolved token pair.

    Uses multicall to check which DEXes have deployed pools with liquidity
    for the given pair.

    M7.A.5.11: Active-liquidity-aware coverage.  coverage_complete requires
    at least 1 buy + 1 sell venue backed by a pool with liquidity > 0.

    Returns machine-readable truth block:
        known_pools_total: int      # pools found via factory.getPool (any state)
        active_pools_total: int     # pools with liquidity > 0
        inactive_pool_count: int    # pools with liquidity == 0
        known_dexes: list[str]      # DEX names with at least one live pool (any liq)
        active_dexes: list[str]     # DEX names with at least one active pool (liq > 0)
        buy_venues: int             # venues with quoter (any pool)
        sell_venues: int            # venues with quoter (any pool)
        active_buy_venues: int      # venues with quoter AND active pool
        active_sell_venues: int     # venues with quoter AND active pool
        coverage_complete: bool     # at least 1 active buy + 1 active sell venue
        coverage_blocker_reason: str or None
        # Legacy aliases (backward compat)
        known_pools: int            # == known_pools_total
    """
    pool_map = _resolve_pool_addresses_multicall(
        dex_configs, token_in_addr, token_out_addr, rpc_url, block_num,
    )

    known_pools_total = 0
    active_pools_total = 0
    known_dexes: List[str] = []
    active_dexes: List[str] = []

    # M7.A.5.12: Build per-pool debug list
    candidate_pools: List[Dict[str, Any]] = []

    for dex_name, pools in pool_map.items():
        dex_has_pool = False
        dex_has_active = False
        for p in pools:
            if p["address"] is not None:
                known_pools_total += 1
                dex_has_pool = True
                liq = p["liquidity"]
                _drop_reason = None
                if liq is not None and liq > 0:
                    active_pools_total += 1
                    dex_has_active = True
                elif liq is None:
                    # Unknown liquidity — treat as potentially active
                    active_pools_total += 1
                    dex_has_active = True
                    _drop_reason = "liquidity_unknown_assumed_active"
                else:
                    _drop_reason = "liquidity_zero"
                candidate_pools.append({
                    "address": p["address"],
                    "dex": dex_name,
                    "fee": p["fee"],
                    "liquidity": liq,
                    "activity_source": "batch_full_pool_data",
                    "activity_drop_reason": _drop_reason,
                })
        if dex_has_pool:
            known_dexes.append(dex_name)
        if dex_has_active:
            active_dexes.append(dex_name)

    inactive_pool_count = known_pools_total - active_pools_total

    # ── M7.A.5.21: Merge registry pools ────────────────────────────────
    # Registry pools supplement the multicall-discovered pools.  Dedup by address.
    _seen_addrs = {cp["address"] for cp in candidate_pools if cp.get("address")}
    _registry_merged = 0
    if pool_registry is not None:
        try:
            reg_entries = pool_registry.lookup_pair(token_in_addr, token_out_addr)
            for re in reg_entries:
                if re.address not in _seen_addrs:
                    cp_dict = re.to_candidate_pool()
                    candidate_pools.append(cp_dict)
                    _seen_addrs.add(re.address)
                    _registry_merged += 1
                    known_pools_total += 1
                    if re.is_active():
                        active_pools_total += 1
                        # Add dex to active lists if not already there
                        if re.dex not in active_dexes:
                            active_dexes.append(re.dex)
                    if re.dex not in known_dexes:
                        known_dexes.append(re.dex)
            inactive_pool_count = known_pools_total - active_pools_total
        except Exception as exc:
            logger.debug("Registry merge failed: %s", str(exc)[:80])

    # Check which have quoter for buy/sell (any pool)
    buy_venues = 0
    sell_venues = 0
    active_buy_venues = 0
    active_sell_venues = 0
    for dex_name in known_dexes:
        cfg = dex_configs.get(dex_name, {})
        quoter = cfg.get("quoter_v2") or cfg.get("quoter")
        if quoter:
            buy_venues += 1
            sell_venues += 1  # same quoter can do both directions
            if dex_name in active_dexes:
                active_buy_venues += 1
                active_sell_venues += 1

    # M7.A.5.11: coverage_complete requires ACTIVE venues (liquidity > 0)
    coverage_complete = active_buy_venues >= 1 and active_sell_venues >= 1
    blocker = None
    if known_pools_total == 0:
        blocker = "no_pools_found"
    elif active_pools_total == 0:
        blocker = "all_pools_zero_liquidity"
    elif active_buy_venues == 0 and active_sell_venues == 0:
        blocker = "no_quoter_for_active_pools"
    elif active_buy_venues == 0:
        blocker = "no_active_buy_venue"
    elif active_sell_venues == 0:
        blocker = "no_active_sell_venue"

    return {
        "known_pools_total": known_pools_total,
        "active_pools_total": active_pools_total,
        "inactive_pool_count": inactive_pool_count,
        "known_dexes": known_dexes,
        "active_dexes": active_dexes,
        "buy_venues": buy_venues,
        "sell_venues": sell_venues,
        "active_buy_venues": active_buy_venues,
        "active_sell_venues": active_sell_venues,
        "coverage_complete": coverage_complete,
        "coverage_blocker_reason": blocker,
        # M7.A.5.12: Per-pool debug for diagnostics
        "candidate_pools": candidate_pools,
        # M7.A.5.21: Registry merge stats
        "registry_pools_merged": _registry_merged,
        # Legacy alias
        "known_pools": known_pools_total,
    }



def seed_tokens_from_subgraph(
    existing_addr_to_symbol: Dict[str, str],
    rpc_url: str,
    block_num: int,
    chain: str = "arbitrum_one",
) -> Dict[str, Any]:
    """Seed addr_to_symbol with top tokens from supported DEX subgraphs.

    Queries The Graph for the top tokens (by tx count) from Uniswap V3 and
    SushiSwap V3 subgraphs on Arbitrum. For each new token found, verifies
    symbol + decimals on-chain via multicall before adding to addr_to_symbol.

    This is a bounded coverage enrichment — NOT a price oracle.

    Args:
        existing_addr_to_symbol: Current addr→symbol mapping (will be mutated)
        rpc_url: HTTP RPC URL for on-chain verification
        block_num: Block number for multicall context
        chain: Chain key (only arbitrum_one supported)

    Returns dict with:
        tokens_discovered: int (from subgraph queries)
        tokens_new: int (not already in addr_to_symbol)
        tokens_verified: int (verified on-chain and added)
        tokens_failed_verification: int
        sources_queried: list[str]
        errors: list[str]
    """
    import json
    import urllib.request
    import urllib.error

    stats: Dict[str, Any] = {
        "tokens_discovered": 0,
        "tokens_new": 0,
        "tokens_verified": 0,
        "tokens_failed_verification": 0,
        "sources_queried": [],
        "errors": [],
    }

    if chain != "arbitrum_one":
        stats["errors"].append(f"subgraph seed not supported for chain: {chain}")
        return stats

    # GraphQL query: top tokens by txCount (bounded)
    query = """
    {
      tokens(first: %d, orderBy: txCount, orderDirection: desc) {
        id
        symbol
        decimals
      }
    }
    """ % SUBGRAPH_SEED_TOKEN_CAP

    candidate_tokens: Dict[str, str] = {}  # addr_lower → symbol

    for dex_name, endpoint in SUBGRAPH_ENDPOINTS_ARBITRUM.items():
        try:
            payload = json.dumps({"query": query}).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=SUBGRAPH_TIMEOUT_SECONDS) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            tokens_data = body.get("data", {}).get("tokens", [])
            stats["sources_queried"].append(dex_name)
            for t in tokens_data:
                addr = t.get("id", "").lower()
                sym = t.get("symbol", "")
                if addr and sym and len(sym) <= 20 and not sym.startswith("0x"):
                    candidate_tokens[addr] = sym
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            stats["errors"].append(f"{dex_name}: {str(exc)[:80]}")
        except Exception as exc:
            stats["errors"].append(f"{dex_name}: {str(exc)[:80]}")

    stats["tokens_discovered"] = len(candidate_tokens)

    # Filter to tokens not already known
    new_tokens = {
        addr: sym for addr, sym in candidate_tokens.items()
        if addr not in existing_addr_to_symbol
    }
    stats["tokens_new"] = len(new_tokens)

    if not new_tokens:
        return stats

    # Verify on-chain via multicall (symbol + decimals)
    addrs_to_verify = list(new_tokens.keys())[:SUBGRAPH_SEED_TOKEN_CAP]
    try:
        verified = enrich_tokens_batch(addrs_to_verify, rpc_url, block_num)
        for addr, info in verified.items():
            if info["enriched"] and info["symbol"]:
                existing_addr_to_symbol[addr] = info["symbol"]
                stats["tokens_verified"] += 1
            else:
                stats["tokens_failed_verification"] += 1
    except Exception as exc:
        stats["errors"].append(f"verification: {str(exc)[:80]}")
        stats["tokens_failed_verification"] = len(addrs_to_verify)

    return stats

