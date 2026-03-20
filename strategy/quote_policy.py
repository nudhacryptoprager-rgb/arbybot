# PATH: strategy/quote_policy.py
"""
Quote-level gating / policy decisions extracted from strategy.quotes.

This module owns:
- Runtime filter switch resolution
- Price sanity gate (consolidates 3x duplicated check from collect_quotes)

High-level quote orchestration remains in strategy.quotes.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from core.env import env_flag_enabled as _env_flag_enabled

logger = logging.getLogger("strategy.quotes")


def get_runtime_filter_switches(config: Dict[str, Any]) -> Dict[str, bool]:
    """Resolve debug/bring-up toggles for stateful runtime suppression layers.

    Contract:
    - Truth gates remain active (price sanity, suspect liquidity, drift, mixed-source).
    - These toggles only disable stateful suppression side-effects:
      quarantine and runtime_disabled persistence/skip logic.
    - Default is fully enabled to preserve production behavior.
    """
    disable_all = _env_flag_enabled("ARBY_DISABLE_RUNTIME_SUPPRESSION") or bool(
        config.get("disable_runtime_suppression", False)
    )
    disable_quarantine = disable_all or _env_flag_enabled(
        "ARBY_DISABLE_RUNTIME_QUARANTINE"
    ) or bool(config.get("disable_runtime_quarantine", False))
    disable_runtime_disabled = disable_all or _env_flag_enabled(
        "ARBY_DISABLE_RUNTIME_DISABLED"
    ) or bool(config.get("disable_runtime_disabled", False))
    return {
        "quarantine_enabled": not disable_quarantine,
        "runtime_disabled_enabled": not disable_runtime_disabled,
    }


def apply_price_sanity_gate(
    price_exact: Decimal,
    anchor_price: float,
    anchor_source: str,
    pair_tag: str,
    dex: str,
    fee_tier: int,
    pool_addr: str,
    config: Dict[str, Any],
    quote_source: Optional[str] = None,
    tick_val: Optional[int] = None,
    amount_in_wei: Optional[int] = None,
    target_usd_notional: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Apply price sanity gate and return reject dict if failed, None if passed.

    Consolidates the 3x duplicated price_sanity check (ve33, quoter, slot0 paths).

    Returns:
        None if sanity check passes or is skipped.
        Reject dict (ready for rejected_quotes.append) if failed.
    """
    price_sanity_enabled = config.get("price_sanity_enabled", True)
    price_sanity_max_bps = config.get("price_sanity_max_deviation_bps", 5000)

    if not price_sanity_enabled or not anchor_price or price_exact is None:
        return None

    from core.validators import check_price_sanity

    sanity_passed, sanity_dev_bps, sanity_err, sanity_diag = check_price_sanity(
        price=Decimal(str(price_exact)),
        anchor_price=Decimal(str(anchor_price)),
        pair=pair_tag,
        dex_id=dex,
        fee_tier=fee_tier,
        max_deviation_bps=price_sanity_max_bps,
        anchor_source=anchor_source,
        pool_address=pool_addr,
    )

    if sanity_passed:
        return None

    try:
        ratio = float(price_exact) / float(anchor_price) if anchor_price else 0.0
    except (TypeError, ZeroDivisionError, OverflowError):
        ratio = 0.0

    reject = {
        "pair": pair_tag,
        "dex_id": dex,
        "fee": fee_tier,
        "pool_address": pool_addr,
        "reason": "PRICE_SANITY_FAILED",
        "gate_passed": False,
        "error": sanity_err,
        "deviation_bps": sanity_dev_bps,
        "anchor_price": str(anchor_price),
        "price_exact": str(price_exact),
        "price_ratio": round(ratio, 4) if abs(ratio) < 1e20 else None,
        "anchor_source": anchor_source,
        "diagnostics": sanity_diag,
    }

    # Add path-specific fields
    if quote_source:
        reject["quote_source"] = quote_source
    if tick_val is not None:
        reject["tick"] = tick_val
    if amount_in_wei is not None:
        reject["amount_in_wei"] = amount_in_wei
    if target_usd_notional is not None:
        reject["notional_usd_target"] = target_usd_notional

    logger.info(
        "PRICE_SANITY_FAILED%s: %s %s fee=%d dev=%d bps anchor=%s observed=%s",
        f" ({quote_source})" if quote_source else "",
        dex, pair_tag, fee_tier, sanity_dev_bps,
        str(anchor_price)[:12], str(price_exact)[:20],
    )

    return reject
