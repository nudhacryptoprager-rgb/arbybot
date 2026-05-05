"""E1.59 step #6: extended revert taxonomy + sample retention.

Reviewer 3h-soak finding: PROD ``cold_immediate_sim_revert_total=248``;
recent samples mix ``REVERT:STF``, ``REVERT:unknown:no_data``, HTTP 408.
Without separate buckets the operator can't distinguish "router/token
allowance issue (STF)" from "stale price data (no_data)" from "infra
flakiness (HTTP 408)".

This module classifies a raw revert-or-error reason into one of:

  * ``STF`` — SafeTransferFrom failure (allowance / balance).
  * ``NO_DATA`` — simulator returned no decodable data / unknown payload.
  * ``HTTP_408`` — transport timeout while attempting the simulation.
  * ``HTTP_429`` — rate-limit signal during simulation.
  * ``OUT_OF_GAS`` — gas exhausted.
  * ``EXECUTION_REVERTED`` — explicit EVM revert with no further detail.
  * ``OTHER`` — anything else (preserved verbatim in the sample).

Plus per-bucket counters + per-bucket recent-sample buffer (size-bisection
seed: ``size_hint`` field optional). All counters reset only via
``reset()`` / ``reset_for_tests()``.

Default OFF — opt-in via ``ARBY_REVERT_TAXONOMY=1``. Stays compatible
with existing ``cold_immediate_sim_revert_samples_recent`` flow.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def is_enabled() -> bool:
    return os.environ.get("ARBY_REVERT_TAXONOMY", "0") == "1"


# Public bucket names, ordered by priority (first match wins).
BUCKETS: tuple = (
    "STF",
    "HTTP_408",
    "HTTP_429",
    "OUT_OF_GAS",
    "NO_DATA",
    "EXECUTION_REVERTED",
    "OTHER",
)


def classify(reason: Optional[str]) -> str:
    """Map a raw reason string into one of ``BUCKETS``."""
    if reason is None:
        return "OTHER"
    r = str(reason).strip()
    if not r:
        return "OTHER"
    rl = r.lower()
    if "stf" in rl or "transferfrom" in rl:
        return "STF"
    if "408" in r or "timeout" in rl:
        return "HTTP_408"
    if "429" in r or "rate limit" in rl or "too many" in rl:
        return "HTTP_429"
    if "out of gas" in rl or "out_of_gas" in rl:
        return "OUT_OF_GAS"
    if "no_data" in rl or "no data" in rl or "unknown:no_data" in rl:
        return "NO_DATA"
    if "execution reverted" in rl or "execution_reverted" in rl:
        return "EXECUTION_REVERTED"
    return "OTHER"


_SAMPLES_PER_BUCKET = 20


@dataclass
class _BucketState:
    count: int = 0
    samples: List[Dict[str, Any]] = field(default_factory=list)


_STATE: Dict[str, _BucketState] = {b: _BucketState() for b in BUCKETS}


def record(
    reason: Optional[str],
    *,
    pair: Optional[str] = None,
    fee: Optional[int] = None,
    pool: Optional[str] = None,
    size_wei: Optional[int] = None,
    block: Optional[int] = None,
    extra: Optional[dict] = None,
) -> str:
    """Classify and record a revert/error sample.

    Returns the assigned bucket name. When the feature flag is OFF, the
    reason is still classified (so callers can log it) but nothing is
    stored.
    """
    bucket = classify(reason)
    if not is_enabled():
        return bucket
    st = _STATE[bucket]
    st.count += 1
    sample = {
        "reason": reason,
        "pair": pair,
        "fee": fee,
        "pool": pool,
        "size_wei": size_wei,
        "block": block,
    }
    if extra:
        sample["extra"] = dict(extra)
    if len(st.samples) >= _SAMPLES_PER_BUCKET:
        st.samples.pop(0)
    st.samples.append(sample)
    return bucket


def snapshot() -> Dict[str, Any]:
    """Return a structured snapshot suitable for the rollup writer."""
    by_bucket: Dict[str, Any] = {}
    total = 0
    for name, st in _STATE.items():
        by_bucket[name] = {
            "count": st.count,
            "recent_samples": list(st.samples),
        }
        total += st.count
    return {
        "buckets": by_bucket,
        "total": total,
    }


def reset() -> None:
    for st in _STATE.values():
        st.count = 0
        st.samples.clear()


# Test-only alias for parity with other modules in this repo.
reset_for_tests = reset


__all__ = [
    "BUCKETS",
    "classify",
    "is_enabled",
    "record",
    "reset",
    "reset_for_tests",
    "snapshot",
]
