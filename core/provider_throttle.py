"""E1.59 step #2: provider throttle policy with per-method buckets and 408/429 breaker.

Wraps the existing ``core.rpc_rate_limiter.TokenBucketRateLimiter`` with:

  * per-method buckets (``logs`` / ``calls`` / ``sim``) so a 429-storm on
    one method does not starve the others,
  * a per-method circuit breaker that tracks consecutive 408/429 failures
    and applies exponential backoff (cooldown) before the next attempt,
  * lightweight stats so the rollup writer can surface `breaker_state` /
    `cooldown_until` per method.

Default OFF — opt-in via ``ARBY_PROVIDER_THROTTLE=1``. When OFF, the
``acquire()`` / ``record_response()`` methods are no-ops so existing
code paths are not affected.

Public API:
  * ``acquire(method)`` -> bool : True if cleared, False if cooldown.
  * ``record_response(method, status_code, ok)`` : feedback for breaker.
  * ``snapshot()`` -> dict : current per-method stats.
  * ``reset()`` : clear buckets + breakers (testing).
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, Optional

# Reuse the existing token-bucket implementation so behaviour is identical.
from core.rpc_rate_limiter import TokenBucketRateLimiter


def _is_enabled() -> bool:
    return os.environ.get("ARBY_PROVIDER_THROTTLE", "0") == "1"


# Per-method default RPS / burst. Conservative for dRPC free tier.
_DEFAULT_BUDGETS: Dict[str, Dict[str, int]] = {
    "logs": {"rps": 20, "burst": 10},
    "calls": {"rps": 30, "burst": 15},
    "sim": {"rps": 5, "burst": 3},
}

# Backoff schedule (seconds) per consecutive failure count.
# After N consecutive 408/429s, the breaker stays open for at least
# ``_BACKOFF_SCHEDULE[min(N-1, len-1)]`` seconds.
_BACKOFF_SCHEDULE: tuple = (1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
# E1.64-7: HTTP 408 (request timeout) is server-side flakiness, not a hard
# rate-limit signal like WS 429.  Use a softer ladder so a single 408 burst
# from a slow upstream does not collapse the per-method bucket for a full
# minute.  WS 429 keeps the original schedule.
_BACKOFF_SCHEDULE_408: tuple = (0.25, 0.5, 1.0, 2.0, 5.0, 15.0)


class _MethodState:
    __slots__ = (
        "limiter",
        "consec_failures",
        "consec_failures_408",
        "consec_failures_429",
        "cooldown_until",
        "total_408",
        "total_429",
        "total_other_errors",
        "total_ok",
        "total_blocked",
    )

    def __init__(self, rps: int, burst: int) -> None:
        self.limiter = TokenBucketRateLimiter(rps=rps, burst=burst)
        self.consec_failures = 0
        self.consec_failures_408 = 0
        self.consec_failures_429 = 0
        self.cooldown_until = 0.0
        self.total_408 = 0
        self.total_429 = 0
        self.total_other_errors = 0
        self.total_ok = 0
        self.total_blocked = 0


class ProviderThrottle:
    """Thread-safe per-method throttle + circuit breaker."""

    def __init__(self, budgets: Optional[Dict[str, Dict[str, int]]] = None) -> None:
        budgets = budgets or _DEFAULT_BUDGETS
        self._lock = threading.Lock()
        self._states: Dict[str, _MethodState] = {}
        for name, b in budgets.items():
            self._states[name] = _MethodState(rps=int(b["rps"]), burst=int(b["burst"]))

    def _get_or_default(self, method: str) -> _MethodState:
        # Allow unknown methods through a generic "calls" bucket.
        if method in self._states:
            return self._states[method]
        if "calls" in self._states:
            return self._states["calls"]
        # Last-resort fallback bucket created on demand.
        st = _MethodState(rps=10, burst=5)
        self._states[method] = st
        return st

    def acquire(self, method: str, *, blocking: bool = True) -> bool:
        """Attempt to consume 1 token for ``method``.

        Returns True if cleared (token taken or throttle disabled), False
        if the breaker is OPEN (cooldown not yet elapsed) — in which case
        the caller MUST NOT issue the RPC.
        """
        if not _is_enabled():
            return True
        st = self._get_or_default(method)
        with self._lock:
            if st.cooldown_until > time.monotonic():
                st.total_blocked += 1
                return False
        if blocking:
            st.limiter.acquire()
        return True

    def record_response(
        self,
        method: str,
        *,
        status_code: Optional[int] = None,
        ok: bool = True,
    ) -> None:
        """Feed back the outcome so the breaker can update.

        408 / 429 are tracked as throttling signals; consecutive
        failures escalate the cooldown per ``_BACKOFF_SCHEDULE``. Any
        other ``ok=True`` resets the consecutive-failure counter.
        """
        if not _is_enabled():
            return
        st = self._get_or_default(method)
        with self._lock:
            if status_code == 408:
                st.total_408 += 1
                self._open_breaker(st, kind=408)
            elif status_code == 429:
                st.total_429 += 1
                self._open_breaker(st, kind=429)
            elif ok:
                st.total_ok += 1
                st.consec_failures = 0
                st.consec_failures_408 = 0
                st.consec_failures_429 = 0
                st.cooldown_until = 0.0
            else:
                st.total_other_errors += 1

    def _open_breaker(self, st: _MethodState, *, kind: int = 429) -> None:
        # E1.64-7: 408 (server timeout) and 429 (rate-limit) accumulate on
        # separate counters and use separate ladders.  The breaker fires off
        # the larger of the two cooldowns so explicit 429 still dominates.
        st.consec_failures += 1
        if kind == 408:
            st.consec_failures_408 += 1
            idx = min(st.consec_failures_408 - 1, len(_BACKOFF_SCHEDULE_408) - 1)
            cooldown = _BACKOFF_SCHEDULE_408[idx]
        else:
            st.consec_failures_429 += 1
            idx = min(st.consec_failures_429 - 1, len(_BACKOFF_SCHEDULE) - 1)
            cooldown = _BACKOFF_SCHEDULE[idx]
        new_until = time.monotonic() + cooldown
        if new_until > st.cooldown_until:
            st.cooldown_until = new_until

    def snapshot(self) -> Dict[str, Dict[str, object]]:
        out: Dict[str, Dict[str, object]] = {}
        now = time.monotonic()
        with self._lock:
            for method, st in self._states.items():
                cooldown_remaining = max(0.0, st.cooldown_until - now)
                out[method] = {
                    "consec_failures": st.consec_failures,
                    "consec_failures_408": st.consec_failures_408,
                    "consec_failures_429": st.consec_failures_429,
                    "cooldown_remaining_s": round(cooldown_remaining, 3),
                    "breaker_open": cooldown_remaining > 0.0,
                    "total_408": st.total_408,
                    "total_429": st.total_429,
                    "total_other_errors": st.total_other_errors,
                    "total_ok": st.total_ok,
                    "total_blocked": st.total_blocked,
                    "rps_limit": st.limiter.rps,
                    "burst": st.limiter.burst,
                }
        return out

    def reset(self) -> None:
        with self._lock:
            for st in self._states.values():
                st.consec_failures = 0
                st.consec_failures_408 = 0
                st.consec_failures_429 = 0
                st.cooldown_until = 0.0
                st.total_408 = 0
                st.total_429 = 0
                st.total_other_errors = 0
                st.total_ok = 0
                st.total_blocked = 0


# Module-level singleton.
provider_throttle = ProviderThrottle()
