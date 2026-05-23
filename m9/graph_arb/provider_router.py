"""Multi-provider RPC router with automatic failover (Step 8).

Maintains a primary and optional secondary RPC endpoint.
When the primary accumulates too many HTTP 429 responses within a sliding
window, requests are routed to the secondary until the primary cools down.

Usage::

    router = ProviderRouter.from_env(chain="base")
    rpc_url = router.get_url()          # call before every batch of RPC requests
    # ... if a request returns 429:
    router.record_429(rpc_url)
    # next call to get_url() may return secondary

    # Embed in raw_http_probe:
    router.record_success(rpc_url)      # optional: track successes

ENV variables read:
    BASE_RPC           — primary HTTP endpoint
    BASE_RPC_SECONDARY — secondary HTTP endpoint (optional)
    ARBY_PROVIDER_FAILOVER_THRESHOLD — 429s within window before failover (default 5)
    ARBY_PROVIDER_COOLDOWN_S         — seconds before retrying primary (default 60)
"""
from __future__ import annotations

import collections
import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger(__name__)

# Number of 429s within the sliding window that triggers failover
_DEFAULT_FAILOVER_THRESHOLD = int(os.environ.get("ARBY_PROVIDER_FAILOVER_THRESHOLD", "5"))
# Sliding window size (seconds) for 429 counting
_DEFAULT_WINDOW_S: float = 30.0
# How long to stick with secondary before retrying primary
_DEFAULT_COOLDOWN_S: float = float(os.environ.get("ARBY_PROVIDER_COOLDOWN_S", "60"))

# Chain-specific secondary RPC env var patterns
_SECONDARY_ENV_VAR = {
    "base": "BASE_RPC_SECONDARY",
    "arbitrum": "ARBITRUM_RPC_SECONDARY",
    "linea": "LINEA_RPC_SECONDARY",
    "mantle": "MANTLE_RPC_SECONDARY",
}


class _ProviderStats:
    """Per-provider 429 tracking within a sliding time window."""

    def __init__(self, window_s: float = _DEFAULT_WINDOW_S) -> None:
        self._window = window_s
        self._lock = threading.Lock()
        self._ts: "collections.deque[float]" = collections.deque()
        self._success_count: int = 0

    def record_429(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._ts.append(now)

    def record_success(self) -> None:
        with self._lock:
            self._success_count += 1

    def recent_429_count(self) -> int:
        cutoff = time.monotonic() - self._window
        with self._lock:
            while self._ts and self._ts[0] < cutoff:
                self._ts.popleft()
            return len(self._ts)

    def snapshot(self) -> dict:
        return {
            "recent_429": self.recent_429_count(),
            "success_total": self._success_count,
        }


class ProviderRouter:
    """Routes RPC calls to primary or secondary endpoint based on 429 health.

    Thread-safe.  Use :meth:`from_env` to construct from environment variables.
    """

    def __init__(
        self,
        primary: str,
        secondary: Optional[str] = None,
        failover_threshold: int = _DEFAULT_FAILOVER_THRESHOLD,
        cooldown_s: float = _DEFAULT_COOLDOWN_S,
        window_s: float = _DEFAULT_WINDOW_S,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        self._threshold = failover_threshold
        self._cooldown = cooldown_s
        self._stats: dict[str, _ProviderStats] = {
            primary: _ProviderStats(window_s=window_s),
        }
        if secondary:
            self._stats[secondary] = _ProviderStats(window_s=window_s)
        self._lock = threading.Lock()
        self._failover_at: Optional[float] = None  # monotonic clock when failover started

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        chain: str = "base",
        failover_threshold: int = _DEFAULT_FAILOVER_THRESHOLD,
        cooldown_s: float = _DEFAULT_COOLDOWN_S,
    ) -> "ProviderRouter":
        """Construct from environment variables for *chain*.

        Primary: chain-specific env var (e.g. BASE_RPC) or public fallback.
        Secondary: chain-specific secondary env var (e.g. BASE_RPC_SECONDARY).
        """
        from core.env import load_root_dotenv
        load_root_dotenv()

        try:
            from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
            chain_id = _CHAIN_KEY_TO_ID.get(chain.lower())
            primary_url, _, _ = resolve_rpc_http(
                chain_id=chain_id,
                network=chain,
                env=dict(os.environ),
            )
        except Exception:
            primary_url = os.environ.get("BASE_RPC", "https://mainnet.base.org")

        sec_var = _SECONDARY_ENV_VAR.get(chain.lower())
        secondary_url = os.environ.get(sec_var, "") if sec_var else ""
        secondary_url = secondary_url.strip() or None

        log.info(
            "ProviderRouter: primary=%s secondary=%s threshold=%d cooldown=%.0fs",
            _mask(primary_url), _mask(secondary_url or ""), failover_threshold, cooldown_s,
        )
        return cls(
            primary=primary_url,
            secondary=secondary_url,
            failover_threshold=failover_threshold,
            cooldown_s=cooldown_s,
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def get_url(self) -> str:
        """Return the currently active RPC URL.

        Uses secondary when primary is over threshold and secondary is available.
        Retries primary after cooldown.
        """
        if self._secondary is None:
            return self._primary

        primary_stats = self._stats[self._primary]
        with self._lock:
            failover_at = self._failover_at

        now = time.monotonic()

        if failover_at is not None:
            # Retry primary if cooldown elapsed
            if now - failover_at >= self._cooldown:
                with self._lock:
                    self._failover_at = None
                log.info(
                    "ProviderRouter: primary cooldown expired, retrying %s",
                    _mask(self._primary),
                )
                return self._primary
            # Still in failover window
            return self._secondary

        # Check if primary just exceeded threshold
        if primary_stats.recent_429_count() >= self._threshold:
            with self._lock:
                self._failover_at = now
            log.warning(
                "ProviderRouter: primary %s hit %d 429s — failing over to %s",
                _mask(self._primary), self._threshold, _mask(self._secondary),
            )
            return self._secondary

        return self._primary

    def record_429(self, url: str) -> None:
        """Record a 429 response for *url*."""
        stats = self._stats.get(url)
        if stats is not None:
            stats.record_429()

    def record_success(self, url: str) -> None:
        """Record a successful response for *url*."""
        stats = self._stats.get(url)
        if stats is not None:
            stats.record_success()

    @property
    def primary(self) -> str:
        return self._primary

    @property
    def secondary(self) -> Optional[str]:
        return self._secondary

    @property
    def is_failed_over(self) -> bool:
        with self._lock:
            return self._failover_at is not None

    def snapshot(self) -> dict:
        """Return a dict suitable for inclusion in rolling artifact."""
        with self._lock:
            failover_at = self._failover_at
        result: dict = {
            "primary": _mask(self._primary),
            "secondary": _mask(self._secondary or ""),
            "is_failed_over": failover_at is not None,
            "providers": {
                _mask(url): stats.snapshot()
                for url, stats in self._stats.items()
            },
        }
        return result


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _mask(url: str) -> str:
    """Mask API key portion of URL for safe logging."""
    if not url:
        return ""
    # Keep domain + first path segment; mask the rest
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        parts = p.path.strip("/").split("/")
        if len(parts) > 1:
            masked_path = "/" + parts[0] + "/<masked>"
        else:
            masked_path = p.path
        return f"{p.scheme}://{p.netloc}{masked_path}"
    except Exception:
        return url[:30] + "..."
