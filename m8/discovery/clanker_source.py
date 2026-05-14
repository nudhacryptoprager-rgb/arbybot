"""M8 Phase 1 — Clanker external discovery source.

Clanker is a token-launchpad on Base that deploys ERC-20 tokens and
automatically creates Uniswap V4 pools for each new token.  It is NOT a
DEX — it does not have its own AMM — so it must NOT be added as a DEX
adapter or a factory in ``config/new_pool_factories.yaml``.

Role in the M8 discovery pipeline
-----------------------------------
The on-chain listener (``m8/runtime/smoke_run.py``) already captures every
Uniswap V4 PoolManager ``Initialize`` event.  Clanker-created pools therefore
appear naturally in the V4 listener stream.

This module adds a *supplementary* discovery channel via the GeckoTerminal
REST API:
  - Polls ``/networks/base/new_pools`` every ``poll_interval_s`` seconds.
  - Filters for ``uniswap-v4-base`` entries (the dominant Clanker surface).
  - Returns raw GeckoTerminal pool dicts with normalized fields.

The data from this source can be used to:
  1. Cross-validate that the on-chain V4 listener is not missing pools.
  2. Enrich pool metadata (e.g. pool name, volume, fdv) faster than RPC.
  3. Serve as a fallback discovery lane when WS is unavailable.

Usage (standalone)
-------------------
    from m8.discovery.clanker_source import ClankerDiscoverySource

    source = ClankerDiscoverySource(chain="base")
    pools = source.fetch_new_pools(page=1)
    for pool in pools:
        print(pool["pool_address"], pool["dex_id"], pool["name"])

Design constraints
-------------------
- This module is side-effect-free at import time (no network calls on load).
- Raises ``ClankerSourceError`` on HTTP errors; callers should catch.
- ``fetch_new_pools`` returns an empty list on soft errors (timeouts) so the
  main pipeline is never blocked by external API availability.
- No authentication required for GeckoTerminal public API.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

__all__ = [
    "ClankerDiscoverySource",
    "ClankerPool",
    "ClankerSourceError",
    "CLANKER_DEX_ID",
    "GECKOTERMINAL_BASE_URL",
]

GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"
CLANKER_DEX_ID = "uniswap-v4-base"  # GeckoTerminal dex_id for V4 pools on Base
_DEFAULT_TIMEOUT_S: float = 10.0
_DEFAULT_POLL_INTERVAL_S: float = 60.0
_DEFAULT_MAX_PAGES: int = 3


class ClankerSourceError(RuntimeError):
    """Raised on non-recoverable API errors (e.g. 4xx status codes)."""


@dataclass
class ClankerPool:
    """Normalized representation of a GeckoTerminal new pool entry."""

    pool_address: str        # pool address from GeckoTerminal (lowercase)
    dex_id: str              # e.g. "uniswap-v4-base"
    chain_id: str            # e.g. "base"
    name: str                # e.g. "PEPE / WETH 0.3%"
    token0_address: str      # base token address (lowercase)
    token1_address: str      # quote token address (lowercase)
    created_at: Optional[str]  # ISO-8601 timestamp from GeckoTerminal
    fdv_usd: Optional[float]
    volume_usd_24h: Optional[float]
    raw: Dict[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_gecko_data(cls, data: Dict[str, Any], network: str = "base") -> "ClankerPool":
        """Build a ClankerPool from a GeckoTerminal ``/new_pools`` data item."""
        attrs = data.get("attributes", {})
        rels = data.get("relationships", {})
        dex_id = rels.get("dex", {}).get("data", {}).get("id", "")
        tokens = rels.get("base_token", {}).get("data", {}) or {}
        quote_tokens = rels.get("quote_token", {}).get("data", {}) or {}

        def _tok_addr(tok: Dict[str, Any]) -> str:
            tok_id = tok.get("id", "")
            # GeckoTerminal id format: "base_0xABCD..."
            parts = tok_id.split("_")
            return parts[-1].lower() if parts else ""

        return cls(
            pool_address=(attrs.get("address") or "").lower(),
            dex_id=dex_id,
            chain_id=network,
            name=attrs.get("name") or "",
            token0_address=_tok_addr(tokens),
            token1_address=_tok_addr(quote_tokens),
            created_at=attrs.get("pool_created_at"),
            fdv_usd=_safe_float(attrs.get("fdv_usd")),
            volume_usd_24h=_safe_float(attrs.get("volume_usd", {}).get("h24") if isinstance(attrs.get("volume_usd"), dict) else None),
            raw=data,
        )


def _safe_float(v: Any) -> Optional[float]:
    """Convert v to float; return None on any failure."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class ClankerDiscoverySource:
    """External discovery source backed by the GeckoTerminal new-pools API.

    Parameters
    ----------
    chain:
        Network identifier (default ``"base"``).
    timeout_s:
        HTTP request timeout in seconds.
    dex_filter:
        If set, only return pools for this dex_id.  Defaults to
        ``CLANKER_DEX_ID`` (``"uniswap-v4-base"``).  Pass ``None`` to
        disable filtering and return all DEXes on the network.
    """

    def __init__(
        self,
        chain: str = "base",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        dex_filter: Optional[str] = CLANKER_DEX_ID,
    ) -> None:
        self.chain = chain
        self.timeout_s = timeout_s
        self.dex_filter = dex_filter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_new_pools(self, page: int = 1) -> List[ClankerPool]:
        """Fetch one page of new pools from GeckoTerminal.

        Returns an empty list on soft errors (timeouts, 5xx).
        Raises ``ClankerSourceError`` on hard errors (4xx).

        Parameters
        ----------
        page:
            GeckoTerminal page number (1-indexed).
        """
        url = f"{GECKOTERMINAL_BASE_URL}/networks/{self.chain}/new_pools?page={page}"
        try:
            raw_data = self._get_json(url)
        except ClankerSourceError:
            raise
        except Exception:
            return []

        items = raw_data.get("data") or []
        pools: List[ClankerPool] = []
        for item in items:
            try:
                pool = ClankerPool.from_gecko_data(item, network=self.chain)
            except Exception:
                continue
            if self.dex_filter is None or pool.dex_id == self.dex_filter:
                pools.append(pool)
        return pools

    def iter_new_pools(
        self,
        max_pages: int = _DEFAULT_MAX_PAGES,
        poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
    ) -> Iterator[List[ClankerPool]]:
        """Yield batches of new pools, polling every ``poll_interval_s`` seconds.

        This is a blocking generator — call it from a background thread.

        Parameters
        ----------
        max_pages:
            Number of API pages to fetch per poll cycle.
        poll_interval_s:
            Seconds to sleep between poll cycles.
        """
        while True:
            all_pools: List[ClankerPool] = []
            for page in range(1, max_pages + 1):
                try:
                    batch = self.fetch_new_pools(page=page)
                except ClankerSourceError:
                    break
                all_pools.extend(batch)
                if not batch:
                    break
            yield all_pools
            time.sleep(poll_interval_s)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_json(self, url: str) -> Dict[str, Any]:
        """Fetch JSON from *url*.  Raises ``ClankerSourceError`` on 4xx."""
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "arby-m8-sniper/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read()
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise ClankerSourceError(
                    f"GeckoTerminal API returned {exc.code} for {url}"
                ) from exc
            raise  # 5xx: let caller handle as soft error
