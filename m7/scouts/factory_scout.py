"""E1.83 — Factory enumeration scout.

Queries on-chain DEX factories for a given set of token pairs to discover
which pools actually exist across all fee-tiers/tick-spacings.  This gives a
ground-truth ``factory_pool_count`` and ``factory_dex_count`` that is more
complete than the TVL-scout or GeckoTerminal data (which only surface pools
that have already accrued measurable liquidity in their APIs).

Supported factory types (Base chain):
  - ``uniswap_v3``  (getPool(tokenA, tokenB, fee) for each fee tier)
  - ``aerodrome_slipstream``  (getPool(tokenA, tokenB, tickSpacing) for each ts)
  - ``ve33``  (getPool(tokenA, tokenB, stable) for stable=False and stable=True)
  - ``uniswap_v2``  (getPair(tokenA, tokenB))

All network I/O is fail-soft:
  - If ARBY_SKIP_RPC=1, all scan functions return [].
  - If web3 is unavailable, returns [].
  - RPC errors per-pool are logged at DEBUG and silently skipped.

Pure parsing helpers are unit-tested.  Network queries are opt-in.

Usage (offline — pure):
    from m7.scouts.factory_scout import FactoryPoolEntry, build_pool_family_truth
    result = build_pool_family_truth(entries)

Usage (online — requires RPC):
    from m7.scouts.factory_scout import scan_factories_for_pairs
    pools = scan_factories_for_pairs(network="base", pairs=[...], rpc_url="...")
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from core.logging import get_logger

logger = get_logger(__name__)

__all__ = [
    "FactoryPoolEntry",
    "PoolFamilyTruth",
    "scan_factories_for_pairs",
    "build_pool_family_truth",
    "write_pool_family_truth",
    "load_pool_family_truth",
    "BASE_TARGET_PAIRS",
    "ZERO_ADDRESS",
]

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# ---------------------------------------------------------------------------
# ABIs — factory call ABIs only (not pool ABIs)
# ---------------------------------------------------------------------------

_V3_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# Aerodrome Slipstream CL factory uses int24 tickSpacing as the third param.
_SLIPSTREAM_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "int24", "name": "tickSpacing", "type": "int24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

_VE33_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
            {"internalType": "bool", "name": "stable", "type": "bool"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "pool", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

_V2_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "tokenA", "type": "address"},
            {"internalType": "address", "name": "tokenB", "type": "address"},
        ],
        "name": "getPair",
        "outputs": [{"internalType": "address", "name": "pair", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactoryPoolEntry:
    """A pool confirmed to exist on-chain by factory query."""

    chain: str
    dex: str                    # e.g. "uniswap_v3", "aerodrome_slipstream"
    adapter_type: str           # e.g. "uniswap_v3", "ve33", "uniswap_v2"
    pool_address: str           # lowercased checksum address
    token_a: str                # symbol, uppercase, canonical order (alphabetical)
    token_b: str                # symbol, uppercase
    addr_a: str                 # token address, lowercased
    addr_b: str                 # token address, lowercased
    fee_tier: Optional[int]     # fee in bps×100 (e.g. 3000 = 0.3%); None for V2/ve33
    tick_spacing: Optional[int] # for slipstream; None for V3/V2/ve33
    stable: Optional[bool]      # for ve33; None for V3/V2

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PoolFamilyTruth:
    """Aggregated ground-truth for a canonical pair across all DEXes."""

    pair: str                       # canonical pair key e.g. "USDC/WETH"
    token_a: str
    token_b: str
    addr_a: str
    addr_b: str
    pool_count: int = 0
    dex_count: int = 0
    dex_set: Set[str] = field(default_factory=set)
    fee_tiers: List[int] = field(default_factory=list)
    tick_spacings: List[int] = field(default_factory=list)
    has_stable_pool: bool = False
    has_volatile_pool: bool = False
    pools: List[FactoryPoolEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pair": self.pair,
            "token_a": self.token_a,
            "token_b": self.token_b,
            "addr_a": self.addr_a,
            "addr_b": self.addr_b,
            "pool_count": self.pool_count,
            "dex_count": self.dex_count,
            "dex_set": sorted(self.dex_set),
            "fee_tiers": sorted(set(self.fee_tiers)),
            "tick_spacings": sorted(set(self.tick_spacings)),
            "has_stable_pool": self.has_stable_pool,
            "has_volatile_pool": self.has_volatile_pool,
            "pools": [p.to_dict() for p in self.pools],
        }


# ---------------------------------------------------------------------------
# Default factory config for Base chain (mirrors config/dexes.yaml)
# ---------------------------------------------------------------------------

BASE_FACTORIES: List[Dict[str, Any]] = [
    {
        "dex": "uniswap_v3",
        "adapter_type": "uniswap_v3",
        "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
        "fee_tiers": [100, 500, 3000, 10000],
    },
    {
        "dex": "aerodrome_slipstream",
        "adapter_type": "aerodrome_slipstream",
        "factory": "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A",
        "tick_spacings": [1, 50, 100, 200, 2000],
    },
    {
        "dex": "aerodrome",
        "adapter_type": "ve33",
        "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
    },
    {
        "dex": "sushiswap_v3",
        "adapter_type": "uniswap_v3",
        "factory": "0xc35DADB65012eC5796536bD9864eD8773aBc74C4",
        "fee_tiers": [100, 500, 3000, 10000],
    },
    {
        "dex": "pancakeswap_v3",
        "adapter_type": "uniswap_v3",
        "factory": "0x0BFbCF9fa4f9C56B0F40a671Ad40E0805A091865",
        "fee_tiers": [100, 500, 2500, 10000],
    },
    {
        "dex": "sushiswap_v2",
        "adapter_type": "uniswap_v2",
        "factory": "0x71524B4f93c58fcbF659783284E38825f0622859",
    },
    {
        "dex": "baseswap_v2",
        "adapter_type": "uniswap_v2",
        "factory": "0xFDa619b6d20975be80A10332cD39b9a4b0FAa8BB",
    },
]

_FACTORIES_BY_NETWORK: Dict[str, List[Dict[str, Any]]] = {
    "base": BASE_FACTORIES,
}

# ---------------------------------------------------------------------------
# Pure helper: canonical pair key (alphabetical symbol order)
# ---------------------------------------------------------------------------


def _canonical_pair(sym_a: str, sym_b: str) -> Tuple[str, str, str]:
    """Return (key, sym_lo, sym_hi) in alphabetical order."""
    a, b = sym_a.upper(), sym_b.upper()
    if a <= b:
        return f"{a}/{b}", a, b
    return f"{b}/{a}", b, a


# ---------------------------------------------------------------------------
# Pure aggregation: build PoolFamilyTruth from a list of FactoryPoolEntry
# ---------------------------------------------------------------------------


def build_pool_family_truth(
    entries: Sequence[FactoryPoolEntry],
) -> Dict[str, PoolFamilyTruth]:
    """Aggregate FactoryPoolEntry rows into PoolFamilyTruth keyed by pair.

    This function is pure (no I/O) and fully unit-testable.

    Parameters
    ----------
    entries:
        All discovered pools from one or more factory scans.

    Returns
    -------
    dict mapping canonical pair key → PoolFamilyTruth.
    """
    families: Dict[str, PoolFamilyTruth] = {}

    for e in entries:
        key, sym_a, sym_b = _canonical_pair(e.token_a, e.token_b)
        addr_a = e.addr_a if sym_a == e.token_a else e.addr_b
        addr_b = e.addr_b if sym_b == e.token_b else e.addr_a

        if key not in families:
            families[key] = PoolFamilyTruth(
                pair=key,
                token_a=sym_a,
                token_b=sym_b,
                addr_a=addr_a,
                addr_b=addr_b,
            )

        fam = families[key]
        fam.pools.append(e)
        fam.pool_count += 1
        fam.dex_set.add(e.dex)
        fam.dex_count = len(fam.dex_set)

        if e.fee_tier is not None:
            fam.fee_tiers.append(e.fee_tier)
        if e.tick_spacing is not None:
            fam.tick_spacings.append(e.tick_spacing)
        if e.stable is True:
            fam.has_stable_pool = True
        if e.stable is False:
            fam.has_volatile_pool = True

    return families


# ---------------------------------------------------------------------------
# RPC helpers — each returns a list of found pool addresses
# ---------------------------------------------------------------------------


def _is_rpc_disabled() -> bool:
    return os.environ.get("ARBY_SKIP_RPC", "0") == "1"


def _make_w3(rpc_url: str):  # type: ignore[return]
    """Create a Web3 HTTP provider with a shared requests Session for connection reuse."""
    from web3 import Web3  # noqa: PLC0415
    return Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 3}))


def _query_v3_factory(
    w3: Any,
    factory_addr: str,
    token_a: str,
    token_b: str,
    fee: int,
) -> Optional[str]:
    """Call factory.getPool(tokenA, tokenB, fee) → pool address or None."""
    try:
        from web3 import Web3  # noqa: PLC0415
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_addr),
            abi=_V3_FACTORY_ABI,
        )
        addr = factory.functions.getPool(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
            fee,
        ).call()
        if addr and addr != ZERO_ADDRESS:
            return addr.lower()
    except Exception as exc:
        logger.debug("v3 getPool failed (%s fee=%s): %s", factory_addr[:10], fee, exc)
    return None


def _query_slipstream_factory(
    w3: Any,
    factory_addr: str,
    token_a: str,
    token_b: str,
    tick_spacing: int,
) -> Optional[str]:
    """Call Slipstream factory.getPool(tokenA, tokenB, tickSpacing)."""
    try:
        from web3 import Web3  # noqa: PLC0415
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_addr),
            abi=_SLIPSTREAM_FACTORY_ABI,
        )
        addr = factory.functions.getPool(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
            tick_spacing,
        ).call()
        if addr and addr != ZERO_ADDRESS:
            return addr.lower()
    except Exception as exc:
        logger.debug(
            "slipstream getPool failed (%s ts=%s): %s",
            factory_addr[:10], tick_spacing, exc,
        )
    return None


def _query_ve33_factory(
    w3: Any,
    factory_addr: str,
    token_a: str,
    token_b: str,
    stable: bool,
) -> Optional[str]:
    """Call ve33 factory.getPool(tokenA, tokenB, stable)."""
    try:
        from web3 import Web3  # noqa: PLC0415
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_addr),
            abi=_VE33_FACTORY_ABI,
        )
        addr = factory.functions.getPool(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
            stable,
        ).call()
        if addr and addr != ZERO_ADDRESS:
            return addr.lower()
    except Exception as exc:
        logger.debug(
            "ve33 getPool failed (%s stable=%s): %s",
            factory_addr[:10], stable, exc,
        )
    return None


def _query_v2_factory(
    w3: Any,
    factory_addr: str,
    token_a: str,
    token_b: str,
) -> Optional[str]:
    """Call V2 factory.getPair(tokenA, tokenB)."""
    try:
        from web3 import Web3  # noqa: PLC0415
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_addr),
            abi=_V2_FACTORY_ABI,
        )
        addr = factory.functions.getPair(
            Web3.to_checksum_address(token_a),
            Web3.to_checksum_address(token_b),
        ).call()
        if addr and addr != ZERO_ADDRESS:
            return addr.lower()
    except Exception as exc:
        logger.debug("v2 getPair failed (%s): %s", factory_addr[:10], exc)
    return None


# ---------------------------------------------------------------------------
# Top-level scan: all factories for a list of pairs
# ---------------------------------------------------------------------------


def scan_factories_for_pairs(
    network: str,
    pairs: Sequence[Dict[str, str]],
    rpc_url: str,
    factory_overrides: Optional[List[Dict[str, Any]]] = None,
) -> List[FactoryPoolEntry]:
    """Scan all DEX factories for the given token pairs.

    Parameters
    ----------
    network:
        Chain name, e.g. ``"base"``.
    pairs:
        List of dicts, each with keys: ``symbol_a``, ``symbol_b``,
        ``addr_a``, ``addr_b`` (hex addresses, any case).
    rpc_url:
        HTTP RPC endpoint. If empty, returns [] (fail-soft).
    factory_overrides:
        If provided, use instead of default factory list for *network*.

    Returns
    -------
    List of FactoryPoolEntry for every pool that exists on-chain.
    Fail-soft: any RPC error returns [] for that specific call.
    """
    if not rpc_url:
        logger.debug("factory_scout: no rpc_url — skipping")
        return []
    if _is_rpc_disabled():
        logger.debug("factory_scout: ARBY_SKIP_RPC=1 — skipping")
        return []

    factories = factory_overrides if factory_overrides is not None else (
        _FACTORIES_BY_NETWORK.get(network, [])
    )
    if not factories:
        logger.warning("factory_scout: no factories configured for network=%s", network)
        return []

    # Create ONE shared Web3 instance for all calls (avoids 147 separate HTTP sessions)
    try:
        w3 = _make_w3(rpc_url)
    except Exception as exc:
        logger.warning("factory_scout: failed to create web3: %s", exc)
        return []

    results: List[FactoryPoolEntry] = []

    for pair in pairs:
        sym_a = pair["symbol_a"].upper()
        sym_b = pair["symbol_b"].upper()
        raw_addr_a = pair["addr_a"]
        raw_addr_b = pair["addr_b"]

        for fac in factories:
            dex = fac["dex"]
            adapter = fac["adapter_type"]
            faddr = fac["factory"]

            if adapter == "uniswap_v3":
                for fee in fac.get("fee_tiers", [100, 500, 3000, 10000]):
                    pool = _query_v3_factory(
                        w3, faddr, raw_addr_a, raw_addr_b, fee
                    )
                    if pool:
                        results.append(FactoryPoolEntry(
                            chain=network,
                            dex=dex,
                            adapter_type=adapter,
                            pool_address=pool,
                            token_a=sym_a,
                            token_b=sym_b,
                            addr_a=raw_addr_a.lower(),
                            addr_b=raw_addr_b.lower(),
                            fee_tier=fee,
                            tick_spacing=None,
                            stable=None,
                        ))

            elif adapter == "aerodrome_slipstream":
                for ts in fac.get("tick_spacings", [1, 50, 100, 200, 2000]):
                    pool = _query_slipstream_factory(
                        w3, faddr, raw_addr_a, raw_addr_b, ts
                    )
                    if pool:
                        results.append(FactoryPoolEntry(
                            chain=network,
                            dex=dex,
                            adapter_type=adapter,
                            pool_address=pool,
                            token_a=sym_a,
                            token_b=sym_b,
                            addr_a=raw_addr_a.lower(),
                            addr_b=raw_addr_b.lower(),
                            fee_tier=None,
                            tick_spacing=ts,
                            stable=None,
                        ))

            elif adapter == "ve33":
                for stable in (False, True):
                    pool = _query_ve33_factory(
                        w3, faddr, raw_addr_a, raw_addr_b, stable
                    )
                    if pool:
                        results.append(FactoryPoolEntry(
                            chain=network,
                            dex=dex,
                            adapter_type=adapter,
                            pool_address=pool,
                            token_a=sym_a,
                            token_b=sym_b,
                            addr_a=raw_addr_a.lower(),
                            addr_b=raw_addr_b.lower(),
                            fee_tier=None,
                            tick_spacing=None,
                            stable=stable,
                        ))

            elif adapter == "uniswap_v2":
                pool = _query_v2_factory(w3, faddr, raw_addr_a, raw_addr_b)
                if pool:
                    results.append(FactoryPoolEntry(
                        chain=network,
                        dex=dex,
                        adapter_type=adapter,
                        pool_address=pool,
                        token_a=sym_a,
                        token_b=sym_b,
                        addr_a=raw_addr_a.lower(),
                        addr_b=raw_addr_b.lower(),
                        fee_tier=None,
                        tick_spacing=None,
                        stable=None,
                    ))

            else:
                logger.debug("factory_scout: unknown adapter_type=%s, skip", adapter)

    logger.info(
        "factory_scout: scanned %d pairs × %d factories → %d pools found",
        len(pairs), len(factories), len(results),
    )
    return results


# ---------------------------------------------------------------------------
# Rolling artifact: pool_family_truth.json
# ---------------------------------------------------------------------------

_POOL_FAMILY_TRUTH_PATH = os.path.join(
    "data", "runs", "_rolling", "pool_family_truth.json"
)

# Target token pairs for factory enumeration on Base.
# Includes bluechip multi-DEX candidates and known CE pairs (VIRTUAL/WETH).
BASE_TARGET_PAIRS: List[Dict[str, str]] = [
    {
        "symbol_a": "USDC",
        "symbol_b": "WETH",
        "addr_a": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "addr_b": "0x4200000000000000000000000000000000000006",
    },
    {
        "symbol_a": "VIRTUAL",
        "symbol_b": "WETH",
        "addr_a": "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b",
        "addr_b": "0x4200000000000000000000000000000000000006",
    },
    {
        "symbol_a": "AERO",
        "symbol_b": "USDC",
        "addr_a": "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
        "addr_b": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    {
        "symbol_a": "AERO",
        "symbol_b": "WETH",
        "addr_a": "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
        "addr_b": "0x4200000000000000000000000000000000000006",
    },
    {
        "symbol_a": "CBBTC",
        "symbol_b": "USDC",
        "addr_a": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
        "addr_b": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    {
        "symbol_a": "CBBTC",
        "symbol_b": "WETH",
        "addr_a": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
        "addr_b": "0x4200000000000000000000000000000000000006",
    },
    {
        "symbol_a": "KEYCAT",
        "symbol_b": "WETH",
        "addr_a": "0x9a26F5433671751C3276a065f57e5a02D2817973",
        "addr_b": "0x4200000000000000000000000000000000000006",
    },
]


def write_pool_family_truth(
    entries: Sequence[FactoryPoolEntry],
    path: str = _POOL_FAMILY_TRUTH_PATH,
    network: str = "base",
) -> None:
    """Aggregate *entries* and write ``pool_family_truth.json`` rolling artifact.

    Idempotent: overwrites the file on every call.  Callers should throttle
    invocations (e.g. at most once per 10 minutes) to avoid RPC overload.
    """
    truth = build_pool_family_truth(entries)
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    artifact = {
        "schema": "pool_family_truth_v1",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "network": network,
        "pair_count": len(truth),
        "pairs": {k: v.to_dict() for k, v in truth.items()},
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2)
    os.replace(tmp, path)
    logger.info(
        "factory_scout: wrote pool_family_truth → %s (%d pairs)",
        path, len(truth),
    )


def load_pool_family_truth(
    path: str = _POOL_FAMILY_TRUTH_PATH,
    max_age_s: float = 3600.0,
) -> Dict[str, Any]:
    """Load ``pool_family_truth.json`` if it exists and is fresh.

    Parameters
    ----------
    path:
        Path to the rolling artifact (default ``_POOL_FAMILY_TRUTH_PATH``).
    max_age_s:
        Maximum age in seconds before treating the file as stale.
        Default 3600 s (1 hour) — factory registrations rarely change intraday.
        Pass ``float("inf")`` to always load.

    Returns
    -------
    Dict mapping canonical pair key → dict (the ``pairs`` sub-object).
    Returns ``{}`` when the file is missing, stale, or malformed.
    """
    if not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if (time.time() - mtime) > max_age_s:
            logger.debug("factory_scout: pool_family_truth stale (%.0fs > %.0fs)", time.time() - mtime, max_age_s)
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pairs = data.get("pairs") or {}
        logger.debug("factory_scout: loaded pool_family_truth %d pairs from %s", len(pairs), path)
        return pairs
    except Exception as exc:
        logger.debug("factory_scout: failed to load pool_family_truth: %s", exc)
        return {}
