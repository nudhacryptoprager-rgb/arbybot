"""Loader for config/adapter_metadata.yaml.

Provides per-pool metadata for Curve (coin indices) and Balancer (pool_id,
vault_address) that cannot be derived from on-chain sniper events alone.

Public API:
    load_adapter_metadata(path) -> AdapterMetadata
    AdapterMetadata.curve_indices(pool_address, token_in_sym, token_out_sym)
    AdapterMetadata.balancer_pool_id(pool_address)
    AdapterMetadata.balancer_vault_address(chain) -> str
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml  # type: ignore[import]

log = logging.getLogger(__name__)

_DEFAULT_PATH = "config/adapter_metadata.yaml"
_DEFAULT_CURVE_POOL_INDICES = "data/runs/_rolling/m9_curve_pool_indices_latest.json"
_CURVE_POOL_INDICES_SCHEMA = "m9_curve_pool_indices.1"


@dataclass(frozen=True)
class _CurvePool:
    pool_address: str       # lowercase 0x + 40 hex
    pool_kind: str          # "stable" | "crypto"
    coin_indices: Dict[str, int]  # {TOKEN_SYM: index}


@dataclass(frozen=True)
class _BalancerPool:
    pool_id: str            # lowercase 0x + 64 hex chars (32 bytes)
    pool_address: str       # lowercase 0x + 40 hex (first 20 bytes of pool_id)
    pool_kind: str          # "stable" | "weighted" | "crypto" | "linear"
    assets: Tuple[str, ...]  # token addresses in ascending order


@dataclass
class AdapterMetadata:
    """Parsed contents of config/adapter_metadata.yaml."""

    # Curve: {chain: {pool_address: _CurvePool}}
    curve_pools: Dict[str, Dict[str, _CurvePool]] = field(default_factory=dict)
    # Balancer: {chain: {pool_id: _BalancerPool}}
    balancer_pools: Dict[str, Dict[str, _BalancerPool]] = field(default_factory=dict)
    # Balancer vault: canonical address (same on all chains)
    _balancer_vault: str = "0xba12222222228d8ba445958a75a0704d566bf2c8"

    # Curve factory address per chain (trust anchor, set in adapter_metadata.yaml)
    curve_factory_stable_ng: Dict[str, str] = field(default_factory=dict)
    # Anchor token addresses per chain for discovery filtering: {chain: {addr: symbol}}
    curve_anchor_tokens: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # Rolling coin-index artifact path per chain (from config pool_indices_artifact)
    curve_pool_indices_artifact: Dict[str, str] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Curve helpers
    # ---------------------------------------------------------------------------

    def curve_indices(
        self,
        pool_address: str,
        token_in_sym: str,
        token_out_sym: str,
        chain: str = "base",
    ) -> Tuple[Optional[int], Optional[int]]:
        """Return (token_in_index, token_out_index) for a Curve pool, or (None, None).

        Returns (None, None) when the pool or either token is not in the registry.
        The caller should use fallbacks (0, 1) when None is returned.
        """
        chain_pools = self.curve_pools.get(chain, {})
        pool = chain_pools.get(pool_address.lower())
        if pool is None:
            return None, None
        idx_in = pool.coin_indices.get(token_in_sym)
        idx_out = pool.coin_indices.get(token_out_sym)
        return idx_in, idx_out

    def curve_pool_kind(
        self,
        pool_address: str,
        chain: str = "base",
    ) -> Optional[str]:
        """Return the Curve pool variant ("stable" | "crypto"), or None.

        The variant selects the get_dy ABI in the quoter (int128 vs uint256).
        Returns None when the pool is not in the registry; callers should
        default to the stable ABI in that case.
        """
        pool = self.curve_pools.get(chain, {}).get(pool_address.lower())
        return pool.pool_kind if pool is not None else None

    # ---------------------------------------------------------------------------
    # Balancer helpers
    # ---------------------------------------------------------------------------

    def balancer_pool_meta(
        self,
        pool_address: str,
        chain: str = "base",
    ) -> Optional[_BalancerPool]:
        """Return _BalancerPool for a pool address, or None if not in registry.

        Searches by pool_address (first 20 bytes of pool_id) rather than full pool_id.
        """
        chain_pools = self.balancer_pools.get(chain, {})
        addr_lower = pool_address.lower()
        for pool in chain_pools.values():
            if pool.pool_address.lower() == addr_lower:
                return pool
        return None

    def balancer_vault_address(self, chain: str = "base") -> str:
        """Return Balancer Vault address (canonical, chain-agnostic)."""
        return self._balancer_vault


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _resolve_curve_pool_indices_path(
    meta: AdapterMetadata,
    chain: str,
    curve_pool_indices_path: Optional[str],
) -> Optional[Path]:
    if curve_pool_indices_path:
        return Path(curve_pool_indices_path)
    env_path = os.environ.get("ARBY_CURVE_POOL_INDICES")
    if env_path:
        return Path(env_path)
    configured = meta.curve_pool_indices_artifact.get(chain)
    if configured:
        return Path(configured)
    return Path(_DEFAULT_CURVE_POOL_INDICES)


def _merge_curve_pool_indices_artifact(
    meta: AdapterMetadata,
    artifact_path: Path,
    chain: str = "base",
) -> None:
    """Overlay coin_indices from rolling artifact (bridge / sniper pools)."""
    if not artifact_path.exists():
        return
    try:
        raw = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Failed to load curve pool indices from %s: %s", artifact_path, exc)
        return
    if raw.get("schema_version") != _CURVE_POOL_INDICES_SCHEMA:
        log.warning(
            "Skipping curve pool indices %s: schema_version=%r",
            artifact_path,
            raw.get("schema_version"),
        )
        return
    if raw.get("chain") and raw.get("chain") != chain:
        return
    pools_raw = raw.get("pools") or {}
    if not isinstance(pools_raw, dict):
        return
    chain_pools = dict(meta.curve_pools.get(chain, {}))
    merged = 0
    for pool_addr, pool_data in pools_raw.items():
        if not isinstance(pool_data, dict):
            continue
        coin_raw = pool_data.get("coin_indices") or {}
        if not isinstance(coin_raw, dict) or len(coin_raw) < 2:
            continue
        try:
            coin_indices = {str(sym): int(idx) for sym, idx in coin_raw.items()}
        except (ValueError, TypeError):
            continue
        pool_kind = str(pool_data.get("pool_kind", "stable"))
        chain_pools[str(pool_addr).lower()] = _CurvePool(
            pool_address=str(pool_addr).lower(),
            pool_kind=pool_kind,
            coin_indices=coin_indices,
        )
        merged += 1
    if chain_pools:
        meta.curve_pools[chain] = chain_pools
    if merged:
        log.debug("Merged %d curve pool index entries from %s", merged, artifact_path)


def load_adapter_metadata(
    path: str = _DEFAULT_PATH,
    curve_pool_indices_path: Optional[str] = None,
    *,
    merge_rolling_indices: bool = True,
) -> AdapterMetadata:
    """Load adapter_metadata.yaml and optionally merge rolling curve coin indices.

    Trust anchors and smoke-seed pools live in config/adapter_metadata.yaml.
    Production bridge Curve pools use data/runs/_rolling/m9_curve_pool_indices_latest.json
    (generated by scripts/discover_curve_indices.py).

    Returns an empty AdapterMetadata (no pools registered) when the file is
    missing or malformed — callers fall back gracefully to hardcoded defaults.
    """
    p = Path(path)
    if not p.exists():
        log.debug("adapter_metadata not found at %s; using empty registry", path)
        return AdapterMetadata()

    try:
        with open(p, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception as exc:
        log.warning("Failed to load adapter_metadata from %s: %s", path, exc)
        return AdapterMetadata()

    meta = AdapterMetadata()

    # --- Balancer vault address ---
    balancer_raw = raw.get("balancer", {}) or {}
    vault_addr = balancer_raw.get("vault_address")
    if vault_addr and isinstance(vault_addr, str):
        object.__setattr__(meta, "_balancer_vault", vault_addr.lower())

    # --- Curve pools ---
    curve_raw = (raw.get("curve") or {})
    for chain_name, chain_data in (curve_raw.items() if isinstance(curve_raw, dict) else []):
        if not isinstance(chain_data, dict):
            continue

        # factory_stable_ng trust anchor (string address)
        factory_addr = chain_data.get("factory_stable_ng")
        if factory_addr and isinstance(factory_addr, str):
            meta.curve_factory_stable_ng[chain_name] = factory_addr.lower()

        # anchor_tokens dict: {addr: symbol}
        anchor_raw = chain_data.get("anchor_tokens") or {}
        if isinstance(anchor_raw, dict) and anchor_raw:
            meta.curve_anchor_tokens[chain_name] = {
                str(addr).lower(): str(sym) for addr, sym in anchor_raw.items()
            }

        indices_artifact = chain_data.get("pool_indices_artifact")
        if indices_artifact and isinstance(indices_artifact, str):
            meta.curve_pool_indices_artifact[chain_name] = indices_artifact

        pools_raw = chain_data.get("pools") or {}
        if not isinstance(pools_raw, dict):
            continue
        chain_pools: Dict[str, _CurvePool] = {}
        for pool_addr, pool_data in pools_raw.items():
            if not isinstance(pool_data, dict):
                continue
            coin_raw = pool_data.get("coin_indices") or {}
            if not isinstance(coin_raw, dict):
                continue
            try:
                coin_indices = {str(sym): int(idx) for sym, idx in coin_raw.items()}
            except (ValueError, TypeError) as exc:
                log.warning("Skipping Curve pool %s: bad coin_indices: %s", pool_addr, exc)
                continue
            pool_kind = str(pool_data.get("pool_kind", "stable"))
            chain_pools[pool_addr.lower()] = _CurvePool(
                pool_address=pool_addr.lower(),
                pool_kind=pool_kind,
                coin_indices=coin_indices,
            )
        if chain_pools:
            meta.curve_pools[chain_name] = chain_pools

    # --- Balancer pools ---
    for chain_name, chain_data in (balancer_raw.items() if isinstance(balancer_raw, dict) else []):
        if chain_name == "vault_address" or not isinstance(chain_data, dict):
            continue
        pools_raw = chain_data.get("pools") or {}
        if not isinstance(pools_raw, dict):
            continue
        chain_pools_b: Dict[str, _BalancerPool] = {}
        for pool_id, pool_data in pools_raw.items():
            if not isinstance(pool_data, dict):
                continue
            pool_addr = str(pool_data.get("pool_address", ""))
            pool_kind = str(pool_data.get("pool_kind", "stable"))
            assets_raw = pool_data.get("assets") or []
            assets = tuple(str(a).lower() for a in assets_raw)
            chain_pools_b[pool_id.lower()] = _BalancerPool(
                pool_id=pool_id.lower(),
                pool_address=pool_addr.lower(),
                pool_kind=pool_kind,
                assets=assets,
            )
        if chain_pools_b:
            meta.balancer_pools[chain_name] = chain_pools_b

    if merge_rolling_indices:
        indices_path = _resolve_curve_pool_indices_path(
            meta, "base", curve_pool_indices_path
        )
        if indices_path is not None:
            _merge_curve_pool_indices_artifact(meta, indices_path, chain="base")

    return meta


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def check_curve_pools_configured(
    metadata: "AdapterMetadata",
    enabled_pool_addresses: list,
    chain: str = "base",
) -> list:
    """Return list of pool addresses that are enabled but have no coin_indices configured.

    Use this to detect gaps: Curve pools in bridge inventory without coin_indices
    in config seed pools or the rolling m9_curve_pool_indices artifact.

    Args:
        metadata: Loaded AdapterMetadata (from load_adapter_metadata()).
        enabled_pool_addresses: Pool addresses to check (e.g., from bridge inventory).
        chain: Chain name, default "base".

    Returns:
        List of pool address strings (lowercase) that have no coin_indices entry.
        Empty list means all pools are fully configured.
    """
    chain_pools = metadata.curve_pools.get(chain, {})
    missing: list = []
    for addr in enabled_pool_addresses:
        addr_lower = addr.lower()
        pool = chain_pools.get(addr_lower)
        if pool is None or not pool.coin_indices:
            missing.append(addr_lower)
    return missing
