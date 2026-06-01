"""Fork-simulation accept-path for M9 candidates (Step 6).

The final proof before a candidate could ever be traded is a re-quote against a
local Anvil **fork** of mainnet using the same calldata path as production.
This is strictly *simulate-only*: it proves the sell path returns the expected
amount on a real fork, but it never broadcasts a transaction.

Micro-live escalation is intentionally gated OFF (see
``profit_validation.assert_micro_live_blocked``).  This module will refuse to
escalate while ``execution_enabled`` is false / the kill switch is active.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from m9.graph_arb.models import GraphCycle
from m9.graph_arb.profit_validation import (
    assert_micro_live_blocked,
    tax_adjusted_net_bps,
)


@dataclass
class ForkSimResult:
    """Outcome of a simulate-only fork re-quote of a candidate cycle."""

    simulate_only: bool
    quoteable: bool
    gross_bps: Optional[float]
    net_bps: Optional[float]
    sell_path_ok: bool
    reject_reason: Optional[str] = None


def fork_sim_revalidate(
    cycle: GraphCycle,
    size_usd: float,
    *,
    w3: Any = None,
    token_price_usd: Optional[dict] = None,
    timeout_s: float = 15.0,
    token_tax_bps: float = 0.0,
    mev_haircut_bps: float = 0.0,
    quote_fn: Optional[Callable[..., Any]] = None,
) -> ForkSimResult:
    """Re-quote ``cycle`` against the local Anvil fork and compute honest net.

    The quote is routed through the ``anvil_fork`` backend so it hits the local
    fork, never the public RPC.  ``quote_fn`` is injectable for testing; by
    default it uses :func:`m9.graph_arb.quoter.quote_cycle_sync` with the
    ``anvil_fork`` backend.

    A positive honest net here means the round-trip (buy + sell) reconciled on a
    real fork — i.e. the sell path is genuine, not a honeypot.
    """
    if quote_fn is None:
        from m9.graph_arb.quoter import BACKEND_ANVIL_FORK, quote_cycle_sync

        def quote_fn(c, s):  # type: ignore[misc]
            return quote_cycle_sync(
                c, s, w3, token_price_usd, timeout_s, BACKEND_ANVIL_FORK, None,
            )

    result = quote_fn(cycle, size_usd)
    status = getattr(result, "status", "QUOTE_FAILED")
    gross = getattr(result, "gross_bps", None)

    if status not in ("POSITIVE_GROSS", "NEGATIVE_GROSS") or gross is None:
        return ForkSimResult(
            simulate_only=True,
            quoteable=False,
            gross_bps=gross,
            net_bps=None,
            sell_path_ok=False,
            reject_reason=getattr(result, "reject_reason", None) or status,
        )

    depth = getattr(cycle, "min_effective_depth_usd", None)
    adapters = [e.adapter_type for e in cycle.edges]
    net = tax_adjusted_net_bps(
        gross,
        adapters,
        size_usd,
        depth,
        token_tax_bps=token_tax_bps,
        mev_haircut_bps=mev_haircut_bps,
    )
    # Sell path is proven when the fork round-trip completes without a phantom
    # rejection and the honest net is non-negative.
    sell_ok = net >= 0.0
    return ForkSimResult(
        simulate_only=True,
        quoteable=True,
        gross_bps=gross,
        net_bps=net,
        sell_path_ok=sell_ok,
        reject_reason=None if sell_ok else "FORK_NET_NEGATIVE",
    )


def attempt_micro_live(
    *,
    execution_enabled: bool = False,
    kill_switch_active: bool = True,
) -> None:
    """Hard safety boundary: refuse to escalate a fork-proven candidate to live.

    Always raises :class:`profit_validation.MicroLiveBlocked` under the current
    safety posture (``MICRO_LIVE_ENABLED`` is False).  This exists so the
    accept-path *code* is complete and tested while real execution stays off.
    """
    assert_micro_live_blocked(
        execution_enabled=execution_enabled,
        kill_switch_active=kill_switch_active,
    )
