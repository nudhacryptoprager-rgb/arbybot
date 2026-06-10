"""Adapter-family contracts for DEX discovery, verification, and quoting.

Each enabled ``dex_id`` maps to a family that defines the canonical on-chain
verification and quote path.  Per-DEX factory/quoter/topic config lives in YAML;
this module defines shared semantics only.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Optional, Tuple

# ---------------------------------------------------------------------------
# Family identifiers
# ---------------------------------------------------------------------------
FAMILY_V2_FORK = "v2_fork"
FAMILY_V3_FORK = "v3_fork"
FAMILY_V4_POOL_MANAGER = "v4_pool_manager"
FAMILY_AERO_VOLATILE = "aerodrome_ve33_volatile"
FAMILY_AERO_STABLE = "aerodrome_ve33_stable"
FAMILY_AERO_SLIPSTREAM = "aerodrome_slipstream_cl"
FAMILY_CURVE_STABLE = "curve_stableswap"
FAMILY_BALANCER_VAULT = "balancer_vault"
FAMILY_MAVERICK_V2 = "maverick_v2"

DEX_TO_FAMILY: Dict[str, str] = {
    "uniswap_v2": FAMILY_V2_FORK,
    "sushiswap_v2": FAMILY_V2_FORK,
    "baseswap_v2": FAMILY_V2_FORK,
    "uniswap_v3": FAMILY_V3_FORK,
    "pancakeswap_v3": FAMILY_V3_FORK,
    "sushiswap_v3": FAMILY_V3_FORK,
    "aerodrome_slipstream": FAMILY_AERO_SLIPSTREAM,
    "aerodrome": FAMILY_AERO_VOLATILE,
    "aerodrome_v2_stable": FAMILY_AERO_STABLE,
    "uniswap_v4": FAMILY_V4_POOL_MANAGER,
    "curve_stable": FAMILY_CURVE_STABLE,
    "curve": FAMILY_CURVE_STABLE,
    "balancer_vault": FAMILY_BALANCER_VAULT,
    "balancer_stable": FAMILY_BALANCER_VAULT,
    "balancer_weighted": FAMILY_BALANCER_VAULT,
    "maverick_v2": FAMILY_MAVERICK_V2,
}

FAMILY_CONTRACTS: Dict[str, Dict[str, str]] = {
    FAMILY_V2_FORK: {
        "verify": "factory.getPair + pair.getReserves + pair.code",
        "quote": "reserve_math_from_getReserves",
        "depth": "reserve_usd_multicall",
        "must_not": "eth_getCode(pool) as existence for V4-style ids",
    },
    FAMILY_V3_FORK: {
        "verify": "factory.getPool(tokenA,tokenB,fee) + slot0/liquidity",
        "quote": "QuoterV2.quoteExactInputSingle (per-dex quoter from config)",
        "depth": "liquidity_usd_from_slot0",
    },
    FAMILY_V4_POOL_MANAGER: {
        "verify": "PoolManager.Initialize event + PoolId + StateView (not pair address code)",
        "quote": "V4 Quoter via poolId/currency hooks",
        "depth": "StateView liquidity snapshot",
        "must_not": "eth_getCode(pool_address) — V4 uses bytes32 pool id",
    },
    FAMILY_AERO_VOLATILE: {
        "verify": "factory createPool + pool.stable=false",
        "quote": "pool.getAmountOut(amountIn, tokenIn)",
        "depth": "reserve_depth",
        "pool_kind": "volatile",
    },
    FAMILY_AERO_STABLE: {
        "verify": "factory createPool + pool.stable=true",
        "quote": "pool.getAmountOut (stable invariant)",
        "depth": "reserve_depth",
        "pool_kind": "stable",
    },
    FAMILY_AERO_SLIPSTREAM: {
        "verify": "slipstream factory getPool + tickSpacing",
        "quote": "slipstream quoter (V3-like fee/tick)",
        "depth": "liquidity_usd_from_slot0",
    },
    FAMILY_CURVE_STABLE: {
        "verify": "factory pool_list + registry coin_indices",
        "quote": "get_dy(i,j,dx) with directed pair indices",
        "depth": "pool_balances_probe",
        "productive_gate": "probe_status QUOTE_OK_* from m9_curve_pool_indices",
    },
    FAMILY_BALANCER_VAULT: {
        "verify": "Vault.getPoolTokens(poolId)",
        "quote": "BalancerQueries.queryBatchSwap / Vault batchSwap simulation",
        "depth": "vault_token_balances_usd",
        "required_fields": "pool_id,vault_address,assets[],assetInIndex,assetOutIndex",
    },
    FAMILY_MAVERICK_V2: {
        "verify": "factory.lookup pagination + pool lens",
        "quote": "PoolInformation.calculateSwap",
        "depth": "pool_lens_depth_probe",
        "productive_gate": "quote_smoke + factory pagination verified",
    },
}

V2_DEX_IDS: FrozenSet[str] = frozenset(
    dex for dex, fam in DEX_TO_FAMILY.items() if fam == FAMILY_V2_FORK
)
V3_DEX_IDS: FrozenSet[str] = frozenset(
    dex for dex, fam in DEX_TO_FAMILY.items() if fam == FAMILY_V3_FORK
)
AERO_DEX_IDS: FrozenSet[str] = frozenset(
    {
        "aerodrome",
        "aerodrome_v2_stable",
        "aerodrome_slipstream",
    }
)


def family_for_dex(dex_id: str) -> str:
    return DEX_TO_FAMILY.get(str(dex_id or ""), "unknown")


def family_contract(family: str) -> Dict[str, str]:
    return dict(FAMILY_CONTRACTS.get(family, {}))


def route_family(route: Dict[str, Any]) -> str:
    dex = str(route.get("dex_id") or "")
    if dex in DEX_TO_FAMILY:
        return DEX_TO_FAMILY[dex]
    adapter = str(route.get("adapter_type") or "")
    if adapter in ("uniswap_v2",):
        return FAMILY_V2_FORK
    if adapter in ("uniswap_v3", "algebra"):
        return FAMILY_V3_FORK
    if adapter == "uniswap_v4":
        return FAMILY_V4_POOL_MANAGER
    if adapter == "ve33":
        return FAMILY_AERO_VOLATILE
    if adapter == "aerodrome_v2_stable":
        return FAMILY_AERO_STABLE
    if adapter == "aerodrome_slipstream":
        return FAMILY_AERO_SLIPSTREAM
    if adapter in ("curve_stable", "curve_stableswap"):
        return FAMILY_CURVE_STABLE
    if adapter in ("balancer_vault", "balancer_stable", "balancer_weighted"):
        return FAMILY_BALANCER_VAULT
    if adapter == "maverick_v2":
        return FAMILY_MAVERICK_V2
    return "unknown"


def balancer_route_metadata_complete(route: Dict[str, Any]) -> bool:
    """True when Balancer route has fields required for Vault batchSwap quotes."""
    if route_family(route) != FAMILY_BALANCER_VAULT:
        return True
    pool_id = route.get("pool_id")
    vault = route.get("vault_address")
    t0 = route.get("token0_addr") or route.get("token0")
    t1 = route.get("token1_addr") or route.get("token1")
    return bool(pool_id and vault and t0 and t1)
