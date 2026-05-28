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
    """Per-provider 429 tracking within a sliding time window.

    Tracks both windowed 429 rate (for failover) and lifetime counters
    (attempts_total, http_429_total) for per-endpoint telemetry (Step 3).
    Approximate latency percentiles (p50/p90) are computed from the last
    up to 200 recorded latencies.
    """

    def __init__(self, window_s: float = _DEFAULT_WINDOW_S) -> None:
        self._window = window_s
        self._lock = threading.Lock()
        self._ts: "collections.deque[float]" = collections.deque()
        self._failure_ts: "collections.deque[float]" = collections.deque()
        self._success_count: int = 0
        # Lifetime counters (not windowed)
        self._attempts_total: int = 0
        self._http_429_total: int = 0
        self._http_5xx_total: int = 0
        # Recent latencies for p50/p90 (capped to avoid unbounded growth)
        self._latencies: "collections.deque[float]" = collections.deque(maxlen=200)

    def record_429(self) -> None:
        self.record_http_error(429)

    def record_http_error(self, status_code: int) -> None:
        now = time.monotonic()
        with self._lock:
            if status_code == 429:
                self._ts.append(now)
                self._http_429_total += 1
            elif status_code >= 500:
                self._failure_ts.append(now)
                self._http_5xx_total += 1

    def record_success(self) -> None:
        with self._lock:
            self._success_count += 1

    def record_attempt(self, latency_s: Optional[float] = None) -> None:
        """Record one outbound RPC call with optional latency."""
        with self._lock:
            self._attempts_total += 1
            if latency_s is not None and latency_s >= 0:
                self._latencies.append(latency_s)

    def recent_429_count(self) -> int:
        cutoff = time.monotonic() - self._window
        with self._lock:
            while self._ts and self._ts[0] < cutoff:
                self._ts.popleft()
            return len(self._ts)

    def recent_failure_count(self) -> int:
        cutoff = time.monotonic() - self._window
        with self._lock:
            while self._ts and self._ts[0] < cutoff:
                self._ts.popleft()
            while self._failure_ts and self._failure_ts[0] < cutoff:
                self._failure_ts.popleft()
            return len(self._ts) + len(self._failure_ts)

    def snapshot(self) -> dict:
        with self._lock:
            lat = sorted(self._latencies)
            n = len(lat)
            p50: Optional[float] = round(lat[n // 2], 3) if n > 0 else None
            p90: Optional[float] = round(lat[min(int(n * 0.90), n - 1)], 3) if n > 0 else None
            # Inline recent_429_count to avoid re-acquiring self._lock (deadlock risk).
            cutoff = time.monotonic() - self._window
            while self._ts and self._ts[0] < cutoff:
                self._ts.popleft()
            while self._failure_ts and self._failure_ts[0] < cutoff:
                self._failure_ts.popleft()
            recent_429 = len(self._ts)
            recent_failures = recent_429 + len(self._failure_ts)
            return {
                "recent_429": recent_429,
                "recent_failures": recent_failures,
                "success_total": self._success_count,
                "attempts_total": self._attempts_total,
                "http_429_total": self._http_429_total,
                "http_5xx_total": self._http_5xx_total,
                "latency_p50_s": p50,
                "latency_p90_s": p90,
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
        extras: Optional[list] = None,
    ) -> None:
        self._primary = primary
        self._secondary = secondary
        # Extra fallback endpoints (tertiary+). Used in round-robin
        # when both primary and secondary are saturated.
        # De-duplicated; primary and secondary are excluded.
        seen = {primary}
        if secondary:
            seen.add(secondary)
        self._extras: list = []
        for url in extras or []:
            if url and url not in seen:
                self._extras.append(url)
                seen.add(url)
        self._threshold = failover_threshold
        self._cooldown = cooldown_s
        self._stats: dict[str, _ProviderStats] = {
            primary: _ProviderStats(window_s=window_s),
        }
        if secondary:
            self._stats[secondary] = _ProviderStats(window_s=window_s)
        for url in self._extras:
            self._stats[url] = _ProviderStats(window_s=window_s)
        self._lock = threading.Lock()
        self._failover_at: Optional[float] = None  # monotonic clock when failover started
        self._extras_cursor: int = 0  # round-robin pointer over extras

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

        # Extras: explicit pool from ENV (comma-separated) + optional public fallbacks.
        extras: list = []
        pool_env_var = f"{chain.upper()}_RPC_POOL"
        pool_raw = os.environ.get(pool_env_var, "")
        if pool_raw:
            extras.extend([u.strip() for u in pool_raw.split(",") if u.strip()])
        if str(os.environ.get("ARBY_USE_PUBLIC_POOL", "")).strip() == "1":
            try:
                from core.rpc_urls import iter_public_http_fallbacks
                extras.extend(iter_public_http_fallbacks(chain))
            except Exception:
                pass

        log.info(
            "ProviderRouter: primary=%s secondary=%s extras=%d threshold=%d cooldown=%.0fs",
            _mask(primary_url), _mask(secondary_url or ""), len(extras),
            failover_threshold, cooldown_s,
        )
        return cls(
            primary=primary_url,
            secondary=secondary_url,
            failover_threshold=failover_threshold,
            cooldown_s=cooldown_s,
            extras=extras,
        )

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def get_url(self) -> str:
        """Return the currently active RPC URL.

        Uses secondary when primary is over threshold and secondary is available.
        When secondary is *also* over threshold, rotates through ``extras`` in
        round-robin. Retries primary after cooldown.
        """
        if self._secondary is None and not self._extras:
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
            # Still in failover window — pick secondary or rotate through extras
            return self._pick_non_primary()

        # Check if primary just exceeded threshold
        if primary_stats.recent_failure_count() >= self._threshold:
            with self._lock:
                self._failover_at = now
            target = self._pick_non_primary()
            log.warning(
                "ProviderRouter: primary %s hit %d 429s — failing over to %s",
                _mask(self._primary), self._threshold, _mask(target),
            )
            return target

        return self._primary

    def _pick_non_primary(self) -> str:
        """Pick a non-primary endpoint avoiding currently over-threshold ones.

        Preference order: secondary (if healthy) → next healthy extra
        (round-robin) → secondary (even if unhealthy) → next extra (any) →
        primary (last resort).
        """
        candidates: list = []
        if self._secondary is not None:
            candidates.append(self._secondary)
        candidates.extend(self._extras)
        if not candidates:
            return self._primary

        # First pass: prefer endpoints below threshold, starting from cursor.
        n = len(candidates)
        with self._lock:
            start = self._extras_cursor % n
        for i in range(n):
            idx = (start + i) % n
            url = candidates[idx]
            stats = self._stats.get(url)
            if stats is None or stats.recent_failure_count() < self._threshold:
                with self._lock:
                    self._extras_cursor = (idx + 1) % n
                return url

        # Second pass: all saturated → still rotate to spread load.
        with self._lock:
            idx = self._extras_cursor % n
            self._extras_cursor = (idx + 1) % n
        return candidates[idx]

    def record_429(self, url: str) -> None:
        """Record a 429 response for *url*."""
        stats = self._stats.get(url)
        if stats is not None:
            stats.record_429()

    def record_http_error(self, url: str, status_code: int) -> None:
        """Record a provider-level HTTP error for *url*.

        M9 treats 429 and 5xx as provider-quality failures for routing. Other
        status codes are left to request/config diagnostics.
        """
        stats = self._stats.get(url)
        if stats is not None and (status_code == 429 or status_code >= 500):
            stats.record_http_error(status_code)

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
            "extras_count": len(self._extras),
            "extras": [_mask(u) for u in self._extras],
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
