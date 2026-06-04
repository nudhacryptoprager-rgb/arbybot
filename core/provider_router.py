"""Canonical multi-provider RPC router for all ARBY subsystems.

Wraps :class:`m9.graph_arb.provider_router.ProviderRouter` with env aliases
``BASE_RPC_PRIMARY`` / ``BASE_RPC_SECONDARY`` and dedicated-RPC policy.
"""
from __future__ import annotations

import os
from typing import Optional

from m9.graph_arb.provider_router import ProviderRouter as ProviderRouter  # re-export
from m9.graph_arb.provider_router import _ProviderStats as _ProviderStats  # noqa: F401

_PRIMARY_ENV = {
    "base": ("BASE_RPC_PRIMARY", "BASE_RPC"),
    "arbitrum": ("ARBITRUM_RPC_PRIMARY", "ARBITRUM_RPC"),
    "linea": ("LINEA_RPC_PRIMARY", "LINEA_RPC"),
    "mantle": ("MANTLE_RPC_PRIMARY", "MANTLE_RPC"),
}

_SECONDARY_ENV = {
    "base": ("BASE_RPC_SECONDARY",),
    "arbitrum": ("ARBITRUM_RPC_SECONDARY",),
    "linea": ("LINEA_RPC_SECONDARY",),
    "mantle": ("MANTLE_RPC_SECONDARY",),
}


def _chain_http_urls(chain: str, env: Optional[dict] = None) -> tuple[str, Optional[str]]:
    """Resolve primary/secondary HTTP URLs from env aliases."""
    env = dict(env if env is not None else os.environ)
    chain_key = chain.lower()
    primary = ""
    for key in _PRIMARY_ENV.get(chain_key, ("BASE_RPC_PRIMARY", "BASE_RPC")):
        primary = (env.get(key) or "").strip()
        if primary:
            break
    secondary = None
    for key in _SECONDARY_ENV.get(chain_key, ("BASE_RPC_SECONDARY",)):
        val = (env.get(key) or "").strip()
        if val:
            secondary = val
            break
    if not primary:
        try:
            from core.rpc_urls import _CHAIN_KEY_TO_ID, resolve_rpc_http

            chain_id = _CHAIN_KEY_TO_ID.get(chain_key)
            primary, _, _ = resolve_rpc_http(
                chain_id=chain_id, network=chain_key, env=env
            )
        except Exception:
            primary = env.get("BASE_RPC", "https://mainnet.base.org")
    return primary, secondary


def from_env(
    chain: str = "base",
    failover_threshold: Optional[int] = None,
    cooldown_s: Optional[float] = None,
) -> ProviderRouter:
    """Build router using PRIMARY/SECONDARY env contract."""
    from core.env import load_root_dotenv

    load_root_dotenv()
    env = dict(os.environ)
    primary, secondary = _chain_http_urls(chain, env=env)

    from core.rpc_urls import require_dedicated_rpc_or_raise

    require_dedicated_rpc_or_raise(primary, chain=chain, env=env)

    threshold = failover_threshold
    if threshold is None:
        threshold = int(env.get("ARBY_PROVIDER_FAILOVER_THRESHOLD", "5"))
    cool = cooldown_s
    if cool is None:
        cool = float(env.get("ARBY_PROVIDER_COOLDOWN_S", "60"))

    extras: list = []
    pool_mode = (env.get("ARBY_PROVIDER_POOL_MODE") or "failover").strip().lower()
    use_public = str(env.get("ARBY_USE_PUBLIC_POOL", "")).strip().lower() in (
        "1",
        "true",
        "yes",
    )
    pool_raw = env.get(f"{chain.upper()}_RPC_POOL", "")
    if pool_raw and (use_public or pool_mode != "weighted"):
        extras.extend([u.strip() for u in pool_raw.split(",") if u.strip()])

    from core.rpc_urls import is_public_rpc_url

    if pool_mode == "weighted":
        # Productive pool: Alchemy+dRPC primary/secondary only; no public extras.
        extras = [u for u in extras if u and not is_public_rpc_url(u)]
        if is_public_rpc_url(primary) and secondary and not is_public_rpc_url(secondary):
            primary, secondary = secondary, None

    return ProviderRouter(
        primary=primary,
        secondary=secondary,
        failover_threshold=threshold,
        cooldown_s=cool,
        extras=extras,
    )
