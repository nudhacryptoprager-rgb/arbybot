"""Mandatory token metadata resolver for bridge/M9 graph build."""
from __future__ import annotations

from typing import Any, Dict, Optional

from m9.graph_arb.core_tokens_loader import resolve_truncated_address
from m9.graph_arb.token_decimals import (
    DECIMALS_SOURCE_CORE_CONFIG,
    DECIMALS_SOURCE_ERC20,
    DECIMALS_SOURCE_HINT,
    enrich_route_decimals,
    fetch_on_chain_decimals,
    is_strict_token_address,
    is_valid_eth_address,
)


def probe_erc20_metadata(w3: Any, address: str) -> Dict[str, Any]:
    """On-chain ERC20 metadata probe for unknown_token RCA."""
    addr = str(address or "").strip().lower()
    if not is_strict_token_address(addr):
        return {"erc20_probe_status": "malformed_address", "address": addr}
    if w3 is None:
        return {"erc20_probe_status": "no_rpc", "address": addr}
    try:
        code = w3.eth.get_code(addr)
        if not code or code in (b"", b"\x00") or code == "0x":
            return {"erc20_probe_status": "not_contract", "address": addr}
    except Exception as exc:
        return {"erc20_probe_status": "timeout", "address": addr, "error": str(exc)[:120]}
    dec = fetch_on_chain_decimals(w3, addr)
    if dec is not None:
        return {
            "erc20_probe_status": "erc20_decimals_ok",
            "address": addr,
            "decimals": int(dec),
        }
    return {"erc20_probe_status": "erc20_decimals_revert", "address": addr}


def _normalize_addr_field(route: Dict[str, Any], addr_key: str, sym_key: str) -> Optional[str]:
    chain = route.get("chain") or "base"
    for candidate in (route.get(addr_key), route.get(sym_key)):
        if is_strict_token_address(candidate):
            route[addr_key] = str(candidate).lower()
            return str(candidate).lower()
    for candidate in (route.get(addr_key), route.get(sym_key)):
        if isinstance(candidate, str) and candidate.lower().startswith("0x") and len(candidate) < 42:
            resolved = resolve_truncated_address(candidate, chain=chain)
            if resolved:
                route[addr_key] = resolved
                route[f"{addr_key}_resolved_from"] = "truncated_symbol"
                return resolved
    return None


def validate_route_token_addresses(route: Dict[str, Any]) -> Optional[str]:
    """Return reject reason when normalized address fields are malformed."""
    for key in ("token0_addr", "token1_addr"):
        val = route.get(key)
        if val is None or val == "":
            continue
        if not is_strict_token_address(str(val).strip()):
            return "malformed_token_address"
    return None


def enrich_route_token_metadata(
    route: Dict[str, Any],
    *,
    cfg: Any = None,
    cache: Optional[Dict[str, int]] = None,
    w3: Any = None,
    chain: str = "base",
    topology_probe: bool = False,
) -> Dict[str, Any]:
    """Resolve addresses, decimals, and metadata_source tags on one route."""
    route["chain"] = chain
    _normalize_addr_field(route, "token0_addr", "token0")
    _normalize_addr_field(route, "token1_addr", "token1")
    reject = validate_route_token_addresses(route)
    if reject:
        route["metadata_reject_reason"] = reject
        return route

    enrich_route_decimals(
        route, cfg=cfg, cache=cache, w3=w3, topology_probe=topology_probe, persist_cache=False
    )

    sources = []
    for leg in ("token0", "token1"):
        src = route.get(f"{leg}_decimals_source")
        sym = route.get(f"{leg}_symbol") or route.get(leg)
        addr = route.get(f"{leg}_addr")
        if src:
            sources.append(str(src))
        route[f"{leg}_metadata_source"] = src or "unresolved"
        if sym and not route.get(f"{leg}_symbol"):
            route[f"{leg}_symbol"] = sym

    if route.get("token0_decimals") is not None and route.get("token1_decimals") is not None:
        route["metadata_status"] = "resolved"
    else:
        route["metadata_status"] = "partial"
    route["metadata_sources"] = sources
    return route


def is_economics_grade_metadata(route: Dict[str, Any]) -> bool:
    """True when both legs have economics-grade decimals (M8.3-aware)."""
    from m9.graph_arb.token_decimals import is_economics_grade_decimals_source

    return (
        is_economics_grade_decimals_source(route.get("token0_decimals_source"))
        and is_economics_grade_decimals_source(route.get("token1_decimals_source"))
    )
