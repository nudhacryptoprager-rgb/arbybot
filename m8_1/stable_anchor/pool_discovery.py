"""Pool-discovery and DexRoute primitives for stable-anchor."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from m8_1.stable_anchor.pairs import StablePair


def _quoters_from_config(cfg: "Any") -> "dict[str, str]":
    """Build {dex_id: quoter_addr} from M8_1 config. Includes all dexes (enabled or not)."""
    return {dex_id: dcfg.quoter for dex_id, dcfg in cfg.dexes.items()}


BASE_QUOTERS: "dict[str, str]" = {}


@dataclass(frozen=True)
class DexRoute:
    """A single concrete quoting route for one pair.

    For Uniswap V3-family adapters, ``fee`` and ``tick_spacing`` are
    mandatory.  For AMM-style (aerodrome_v2_stable, uniswap_v2) they may be
    zero / None.
    """

    dex_id: str
    adapter_type: str
    quoter: str
    fee: int
    tick_spacing: Optional[int]
    curve_coin0_sym: Optional[str]
    hooks: Optional[str] = None         # V4 only: hooks address; None = vanilla (0x0)
    token_in_index: Optional[int] = None  # Curve: coin[] index for token_in
    token_out_index: Optional[int] = None  # Curve: coin[] index for token_out
    pool_id: Optional[str] = None         # Balancer: 32-byte pool ID (0x + 64 hex chars)
    vault_address: Optional[str] = None   # Balancer: Vault contract address
    pool_kind: Optional[str] = None       # "stable" | "weighted" | "crypto" | "linear"
    curve_coin1_sym: Optional[str] = None  # Curve: symbol of coin at index 1
    balancer_assets: Optional[List[str]] = None  # Balancer: full pool asset list for queryBatchSwap
    balancer_balances: Optional[List[int]] = None  # Balancer: vault balances aligned to assets
    maverick_pool_lane_probe_amount: Optional[int] = None
    maverick_min_quoteable_amount_raw: Optional[int] = None
    maverick_max_quoteable_amount_raw: Optional[int] = None
    maverick_token_a_in_probe: Optional[bool] = None
    maverick_pool_lane_token_in: Optional[str] = None

    def __post_init__(self) -> None:
        pass


@dataclass
class RouteSet:
    """All quoting routes registered for one pair."""

    pair_id: str
    routes: "tuple[DexRoute, ...]"

    def __post_init__(self) -> None:
        pass

    def __len__(self) -> int:
        return len(self.routes)


def _v3(dex_id: str, quoter: str, fee: int, tick_spacing: Optional[int] = None) -> DexRoute:
    return DexRoute(
        dex_id=dex_id,
        adapter_type="uniswap_v3",
        quoter=quoter,
        fee=fee,
        tick_spacing=tick_spacing,
    )


def _slip(dex_id: str, quoter: str, tick_spacing: int, coin0: Optional[str] = None) -> DexRoute:
    return DexRoute(
        dex_id=dex_id,
        adapter_type="aerodrome_slipstream",
        quoter=quoter,
        fee=0,
        tick_spacing=tick_spacing,
        curve_coin0_sym=coin0,
    )


# Lazy-initialised tuple cache to avoid re-building on every import
_ROUTE_TUPLE_CACHE: "dict[str, Any]" = {}


def _build_route_tuples(
    dex_id: str,
    fee: int,
    tick_spacing: Optional[int] = None,
) -> "DexRoute":
    """Build (ss_defaults, ss_extended, eth_lst_defaults, eth_lst_extended) for dex+fee."""
    # Stub — real logic depends on config; callers use discover_routes instead
    return DexRoute(
        dex_id=dex_id,
        adapter_type="uniswap_v3",
        quoter="0x0000000000000000000000000000000000000000",
        fee=fee,
        tick_spacing=tick_spacing,
        curve_coin0_sym=None,
    )


_STABLE_STABLE_DEFAULTS: tuple = ()
_STABLE_STABLE_EXTENDED: tuple = ()
_ETH_LST_DEFAULTS: tuple = ()
_ETH_LST_EXTENDED: tuple = ()
_POOL_SCOPED_ADAPTERS = frozenset({"aerodrome_v2_stable", "curve_stable"})


def _get_route_tuples(source_path: Optional[str] = None) -> tuple:
    """Return cached (ss_defaults, ss_extended, eth_lst_defaults, eth_lst_extended)."""
    return (_STABLE_STABLE_DEFAULTS, _STABLE_STABLE_EXTENDED, _ETH_LST_DEFAULTS, _ETH_LST_EXTENDED)


def discover_routes(pair: "StablePair", route_class: str = "STABLE_STABLE") -> RouteSet:
    """Return the curated route set for ``pair``.

    ``route_class`` controls which pool universe is used:
    ``STABLE_STABLE`` for stablecoin pairs, ``STABLE_FOREX`` for mixed.
    """
    # Minimal stub — returns empty RouteSet; real implementation uses config
    return RouteSet(pair_id=pair.pair_id, routes=())


def list_supported_dex_ids() -> "List[str]":
    """Return ENABLED DEX IDs supported by M8_1 P0 (from config)."""
    return []
