"""Compatibility shim: token identity now lives in :mod:`core.token_identity`.

Kept so existing M9 call sites keep working. New code should import from
``core.token_identity`` directly; layers below M9 (M8, M8.1, discovery,
monitoring) must not import this module.
"""
from __future__ import annotations

from core.token_identity import (
    _is_full_eth_address,
    address_decimals_map,
    address_symbol_map,
    anchor_token_addresses,
    build_route_address_prefix_index,
    normalize_chain_key,
    resolve_truncated_address,
    symbol_baseline_prices,
)

__all__ = [
    "address_decimals_map",
    "address_symbol_map",
    "anchor_token_addresses",
    "build_route_address_prefix_index",
    "normalize_chain_key",
    "resolve_truncated_address",
    "symbol_baseline_prices",
]
