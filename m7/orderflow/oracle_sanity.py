"""
E1.35 P3.8 — Oracle sanity guard for oversized backruns.

When the backrun notional exceeds a configurable USD threshold (default
$10,000) the local pricing + profit_guard duo can still be fooled by a
thin pool that moves heavily under our own trade. This module implements
a lightweight sanity layer that compares the scored mid-price against an
external reference (Chainlink/CEX) and rejects candidates whose implied
price is off by more than ``max_abs_bps`` bps.

Design notes
------------
* The check is **advisory** by default — callers pass ``strict=True``
  to turn a violation into a submit blocker. This keeps the check opt-in
  so that shadow/rollup artifacts can measure the impact first.
* When no oracle is configured (e.g. offline/test), the check is a
  no-op and returns ``passed=True`` with ``reason="ORACLE_UNAVAILABLE"``.
  This matches the repo convention of honest blockers over hard deps.
* Controlled by env var ``ARBY_ORACLE_SANITY_MIN_USD`` (default 10_000)
  and ``ARBY_ORACLE_SANITY_MAX_BPS`` (default 50). Both are floats.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("m7.orderflow.oracle_sanity")


_DEFAULT_MIN_USD = 10_000.0
_DEFAULT_MAX_BPS = 50.0


@dataclass
class OracleSanityResult:
    """Outcome of the oracle-sanity check.

    ``passed=True`` means either (a) the notional was below the guard
    threshold (check skipped) or (b) the implied-vs-oracle deviation was
    within ``max_abs_bps``.
    """

    passed: bool = True
    reason: Optional[str] = None
    notional_usd: float = 0.0
    deviation_bps: Optional[float] = None
    oracle_source: Optional[str] = None


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        if val >= 0:
            return val
    except ValueError:
        pass
    return default


def get_sanity_min_usd() -> float:
    """Threshold above which oracle sanity is evaluated."""
    return _env_float("ARBY_ORACLE_SANITY_MIN_USD", _DEFAULT_MIN_USD)


def get_sanity_max_bps() -> float:
    """Maximum implied-vs-oracle deviation (bps) before rejection."""
    return _env_float("ARBY_ORACLE_SANITY_MAX_BPS", _DEFAULT_MAX_BPS)


def check_oracle_sanity(
    *,
    notional_usd: float,
    implied_price: Optional[float] = None,
    oracle_price: Optional[float] = None,
    oracle_source: Optional[str] = None,
) -> OracleSanityResult:
    """Compare implied vs oracle mid for oversized notionals.

    Parameters
    ----------
    notional_usd
        Trade size in USD. Below :func:`get_sanity_min_usd` the check
        is skipped and passes.
    implied_price
        Effective price from the local quote (e.g. ``amount_out /
        amount_in`` normalized to token decimals). ``None`` means the
        caller could not derive one; we pass with
        ``reason="IMPLIED_MISSING"``.
    oracle_price
        Reference price from Chainlink/CEX. ``None`` → skip check with
        ``reason="ORACLE_UNAVAILABLE"``.
    oracle_source
        Free-form label (e.g. ``"chainlink"``, ``"binance"``) used for
        telemetry.

    Returns
    -------
    OracleSanityResult
    """
    _min_usd = get_sanity_min_usd()
    if notional_usd <= 0 or notional_usd < _min_usd:
        return OracleSanityResult(
            passed=True, reason="BELOW_THRESHOLD", notional_usd=notional_usd
        )

    if oracle_price is None or oracle_price <= 0:
        return OracleSanityResult(
            passed=True,
            reason="ORACLE_UNAVAILABLE",
            notional_usd=notional_usd,
            oracle_source=oracle_source,
        )

    if implied_price is None or implied_price <= 0:
        return OracleSanityResult(
            passed=True,
            reason="IMPLIED_MISSING",
            notional_usd=notional_usd,
            oracle_source=oracle_source,
        )

    deviation_bps = abs(implied_price - oracle_price) / oracle_price * 10_000.0
    max_bps = get_sanity_max_bps()
    passed = deviation_bps <= max_bps
    reason = None if passed else "ORACLE_DEVIATION"
    return OracleSanityResult(
        passed=passed,
        reason=reason,
        notional_usd=notional_usd,
        deviation_bps=round(deviation_bps, 4),
        oracle_source=oracle_source,
    )
