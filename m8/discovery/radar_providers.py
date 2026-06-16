"""M8.2 non-RPC mirror radar providers (hint-only; never canonical without verify)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from m8.discovery.pool_hints import PoolHint

_log = logging.getLogger(__name__)

NOT_CONFIGURED = "NOT_CONFIGURED"

_RADAR_STUB_PROVIDERS = frozenset(
    {"coinmarketcap_dex", "dexpaprika", "moralis", "codex_defined", "coingecko_onchain"}
)


def _empty_batch(provider: str, *, reason: str = "not_configured") -> List[PoolHint]:
    _log.debug("radar provider=%s skipped: %s", provider, reason)
    return []


def fetch_coinmarketcap_dex_hints(
    token: str,
    *,
    chain: str = "base",
) -> List[PoolHint]:
    """CoinMarketCap DEX API — stub until API key wiring (hints only)."""
    return _empty_batch("coinmarketcap_dex")


def fetch_dexpaprika_hints(
    token: str,
    *,
    chain: str = "base",
) -> List[PoolHint]:
    """DexPaprika — stub until endpoint wiring (hints only)."""
    return _empty_batch("dexpaprika")


def fetch_moralis_hints(
    token: str,
    *,
    chain: str = "base",
) -> List[PoolHint]:
    """Moralis DEX API — stub until API key wiring (hints only)."""
    return _empty_batch("moralis")


def fetch_codex_defined_hints(
    token: str,
    *,
    chain: str = "base",
) -> List[PoolHint]:
    """Codex / Defined.fi — stub until API key wiring (hints only)."""
    return _empty_batch("codex_defined")


def radar_provider_metrics(
    source_pool_counts: Dict[str, int],
    per_source_verified_yield: Dict[str, int],
    *,
    sources_requested: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Aggregate mirror_source_yield_by_provider for hint artifact metrics."""
    mirror_yield: Dict[str, int] = dict(per_source_verified_yield)
    for src, count in source_pool_counts.items():
        mirror_yield.setdefault(f"{src}_pools", int(count or 0))
        mirror_yield.setdefault(src, int(per_source_verified_yield.get(src, 0)))

    provider_status: Dict[str, str] = {}
    for provider in _RADAR_STUB_PROVIDERS:
        if sources_requested and provider not in sources_requested:
            provider_status[provider] = "NOT_REQUESTED"
        elif int(source_pool_counts.get(provider, 0)) > 0:
            provider_status[provider] = "ACTIVE"
        else:
            provider_status[provider] = NOT_CONFIGURED

    return {
        "mirror_source_yield_by_provider": mirror_yield,
        "radar_provider_status": provider_status,
    }
