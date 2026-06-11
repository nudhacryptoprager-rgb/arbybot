"""Profit-validation primitives for the M9 exotic / new-pool strategy.

This module converts *raw* cycle quotes into *trustworthy* candidates.  The
exotic / new-pool field is dominated by thin, one-directional, and toxic
pools, so the edge of a solo operator is **precision of selection against
toxicity**, not speed.  The functions here encode that discipline:

* Step 3 — depth-aware phantom ceiling + round-trip asymmetry rejection
* Step 1 — toxicity gauntlet (honeypot + phantom + asymmetry + unknown depth)
* Step 4 — size & tax aware honest net
* Step 5 — low-frequency precision gate (recall down, precision up)
* Step 6 — micro-live safety guard (kept **blocked** by construction)

Design rules
------------
* Every function is **pure** (no RPC / IO) so it can be unit-tested offline.
* Public API is **additive** — nothing here removes or renames existing
  symbols elsewhere in the repo.
* Defaults are conservative: when in doubt, a candidate is treated as toxic
  / phantom rather than accepted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence

from m9.graph_arb.cost_model import net_bps_size_aware


# Verdict strings (mirror monitoring.sniper_honeypot.HoneypotVerdict values so
# callers can pass either the enum or its ``.value``).
HONEYPOT_PASS = "PASS"
HONEYPOT_FAIL = "FAIL"
HONEYPOT_UNKNOWN = "UNKNOWN"

# Reject reason strings surfaced into artifacts / telemetry.
REASON_HONEYPOT_FAIL = "HONEYPOT_FAIL"
REASON_SUSPECT_PHANTOM = "SUSPECT_PHANTOM"
REASON_ASYMMETRIC_ROUNDTRIP = "ASYMMETRIC_ROUNDTRIP"
REASON_UNKNOWN_DEPTH = "UNKNOWN_DEPTH"
REASON_NET_BELOW_BUFFER = "NET_BELOW_BUFFER"
REASON_SELL_NOT_VERIFIED = "SELL_NOT_VERIFIED"
REASON_INSUFFICIENT_VENUES = "INSUFFICIENT_VENUES"


# ---------------------------------------------------------------------------
# Step 3 — depth-aware phantom ceiling
# ---------------------------------------------------------------------------
# A genuine arbitrage spread on Base is small (single to low-double-digit bps).
# A round-trip cycle reporting hundreds/thousands of bps is almost always a
# *phantom*: revert data decoded as amount_out, wrong token indices, or a thin
# one-directional pool.  The plausible ceiling scales (slowly) with the
# measured bottleneck depth — deeper pools can momentarily show a slightly
# larger spread, thin/unknown pools cannot.

_PHANTOM_CEILING_NO_DEPTH_BPS: float = 500.0
_PHANTOM_CEILING_MAX_BPS: float = 2000.0


def depth_aware_phantom_ceiling_bps(
    depth_usd: Optional[float],
    *,
    depth_probe_status: Optional[str] = None,
    freshness_window: bool = False,
) -> float:
    """Return the maximum plausible absolute gross_bps for a given pool depth.

    ``depth_usd`` is the bottleneck ``effective_depth_usd`` of the cycle (the
    notional at which marginal price impact reaches the LOW threshold).  When
    no depth is measured the strictest ceiling applies, because an unknown-depth
    pool is the most likely phantom source.

    Fresh M8 pools with ladder lower-bound depth use a relaxed ceiling so
    capped/fallback depth does not hard-quarantine before round-trip replay.
    """
    from m9.graph_arb.depth_capacity_probe import (
        DEPTH_PROBE_LOWER_BOUND_AT_MAX,
        DEPTH_PROBE_MEASURED_CAPACITY,
    )

    if depth_usd is None or depth_usd <= 0:
        base = _PHANTOM_CEILING_NO_DEPTH_BPS
    elif depth_usd < 1_000:
        base = _PHANTOM_CEILING_NO_DEPTH_BPS
    elif depth_usd < 10_000:
        base = 800.0
    elif depth_usd < 100_000:
        base = 1_200.0
    else:
        base = _PHANTOM_CEILING_MAX_BPS

    if freshness_window and depth_probe_status in (
        DEPTH_PROBE_LOWER_BOUND_AT_MAX,
        DEPTH_PROBE_MEASURED_CAPACITY,
    ):
        return max(base, 1_200.0)
    if (
        depth_probe_status == DEPTH_PROBE_LOWER_BOUND_AT_MAX
        and depth_usd is not None
        and float(depth_usd) >= 500.0
    ):
        return max(base, 800.0)
    return base


def is_phantom_gross(gross_bps: float, depth_usd: Optional[float]) -> bool:
    """True when ``gross_bps`` exceeds the depth-aware plausibility ceiling."""
    return abs(gross_bps) > depth_aware_phantom_ceiling_bps(depth_usd)


# ---------------------------------------------------------------------------
# Step 3 — round-trip asymmetry detection
# ---------------------------------------------------------------------------
# A real closed arbitrage cycle and its reverse cannot *both* be profitable:
# in a consistent market reversing the path roughly negates the gross (minus
# the round-trip fees).  Two tell-tale phantom signatures:
#   1. forward AND reverse both report profit  → impossible, mispriced/phantom
#   2. |forward + reverse| is large            → the legs do not reconcile

_ASYMMETRY_MAX_ABS_SPREAD_BPS: float = 400.0


def detect_asymmetry(
    forward_bps: float,
    reverse_bps: float,
    *,
    max_abs_spread_bps: float = _ASYMMETRY_MAX_ABS_SPREAD_BPS,
) -> bool:
    """Return True when a forward/reverse quote pair is internally inconsistent.

    Both legs profitable, or a forward+reverse sum that does not roughly cancel,
    indicates a one-directional phantom rather than a tradeable spread.
    """
    if forward_bps > 0 and reverse_bps > 0:
        return True
    return abs(forward_bps + reverse_bps) > max_abs_spread_bps


# ---------------------------------------------------------------------------
# Step 4 — size & tax aware honest net
# ---------------------------------------------------------------------------
# The price-impact model lives in cost_model (size_aware_slippage_bps /
# net_bps_size_aware); here we expose a tax-aware convenience wrapper.


def tax_adjusted_net_bps(
    gross_bps: float,
    adapter_types: Sequence[str],
    size_usd: float,
    depth_usd: Optional[float],
    *,
    token_tax_bps: float = 0.0,
    mev_haircut_bps: float = 0.0,
) -> float:
    """Return the honest net spread after every modelled cost.

    net = gross
          - per-leg adapter cost (cycle_cost_bps)
          - per-leg size-aware slippage
          - token transfer tax
          - MEV haircut
    """
    return net_bps_size_aware(
        gross_bps,
        list(adapter_types),
        size_usd,
        depth_usd,
        token_tax_bps=token_tax_bps,
        mev_haircut_bps=mev_haircut_bps,
    )


# ---------------------------------------------------------------------------
# Step 1 — toxicity gauntlet
# ---------------------------------------------------------------------------


@dataclass
class ToxicityVerdict:
    """Outcome of the mandatory toxicity gauntlet for a single candidate."""

    is_toxic: bool
    reasons: List[str] = field(default_factory=list)
    honeypot_verdict: str = HONEYPOT_UNKNOWN
    phantom: bool = False
    asymmetric: bool = False
    unknown_depth: bool = False


def _normalise_verdict(verdict: object) -> str:
    """Coerce a HoneypotVerdict enum or string into its canonical value."""
    value = getattr(verdict, "value", verdict)
    return str(value).upper()


def evaluate_toxicity(
    *,
    gross_bps: float,
    depth_usd: Optional[float],
    honeypot_verdict: object = HONEYPOT_UNKNOWN,
    forward_bps: Optional[float] = None,
    reverse_bps: Optional[float] = None,
    require_known_depth: bool = False,
) -> ToxicityVerdict:
    """Run the hard-toxicity checks for a candidate cycle.

    A candidate is toxic (and must not become a tradeable signal) when:
      * its token failed the honeypot / sell-simulation check, or
      * its gross spread exceeds the depth-aware phantom ceiling, or
      * its forward/reverse round-trip is asymmetric, or
      * (optionally) its depth is unknown and ``require_known_depth`` is set.

    A honeypot verdict of UNKNOWN is **not** hard-toxic here — it is handled by
    the precision gate's "sell verified" requirement (Step 5), so discovery
    telemetry is not destroyed while the strict gate still refuses it.
    """
    reasons: List[str] = []
    hv = _normalise_verdict(honeypot_verdict)

    if hv == HONEYPOT_FAIL:
        reasons.append(REASON_HONEYPOT_FAIL)

    phantom = is_phantom_gross(gross_bps, depth_usd)
    if phantom:
        reasons.append(REASON_SUSPECT_PHANTOM)

    asymmetric = False
    if forward_bps is not None and reverse_bps is not None:
        asymmetric = detect_asymmetry(forward_bps, reverse_bps)
        if asymmetric:
            reasons.append(REASON_ASYMMETRIC_ROUNDTRIP)

    unknown_depth = depth_usd is None or depth_usd <= 0
    if require_known_depth and unknown_depth:
        reasons.append(REASON_UNKNOWN_DEPTH)

    return ToxicityVerdict(
        is_toxic=bool(reasons),
        reasons=reasons,
        honeypot_verdict=hv,
        phantom=phantom,
        asymmetric=asymmetric,
        unknown_depth=unknown_depth,
    )


# ---------------------------------------------------------------------------
# Step 5 — low-frequency precision gate
# ---------------------------------------------------------------------------


@dataclass
class PrecisionConfig:
    """Tunables for the precision gate.  Zero signals beats 57 phantoms."""

    min_net_bps: float = 30.0          # net after ALL costs must clear this buffer
    require_sell_verified: bool = True  # honeypot must be PASS (not UNKNOWN/FAIL)
    min_quoteable_venues: int = 2       # OR a proven launch mispricing
    allow_launch_mispricing: bool = True


@dataclass
class PrecisionResult:
    """Result of evaluating a candidate against :class:`PrecisionConfig`."""

    passed: bool
    reasons: List[str] = field(default_factory=list)


def passes_precision_gate(
    *,
    net_bps: float,
    honeypot_verdict: object,
    quoteable_venues: int,
    launch_mispricing: bool = False,
    toxic: bool = False,
    cfg: Optional[PrecisionConfig] = None,
) -> PrecisionResult:
    """Acceptance: net >= buffer AND sell-path verified AND (>=2 venues OR launch).

    A toxic candidate can never pass.  This is deliberately low-recall — it is
    correct for 0 candidates to pass rather than admit a single phantom.
    """
    cfg = cfg or PrecisionConfig()
    reasons: List[str] = []

    if toxic:
        reasons.append("TOXIC")

    if net_bps < cfg.min_net_bps:
        reasons.append(REASON_NET_BELOW_BUFFER)

    if cfg.require_sell_verified and _normalise_verdict(honeypot_verdict) != HONEYPOT_PASS:
        reasons.append(REASON_SELL_NOT_VERIFIED)

    venues_ok = quoteable_venues >= cfg.min_quoteable_venues or (
        cfg.allow_launch_mispricing and launch_mispricing
    )
    if not venues_ok:
        reasons.append(REASON_INSUFFICIENT_VENUES)

    return PrecisionResult(passed=not reasons, reasons=reasons)


# ---------------------------------------------------------------------------
# Step 6 — micro-live safety guard (BLOCKED by construction)
# ---------------------------------------------------------------------------
# Real on-chain execution is intentionally disabled.  The fork-sim path may run
# (simulate-only), but any attempt to escalate to micro-live MUST raise.  This
# is a hard safety boundary — do not flip ``MICRO_LIVE_ENABLED`` without an
# explicit, reviewed, kill-switch-gated change.

MICRO_LIVE_ENABLED: bool = False


class MicroLiveBlocked(RuntimeError):
    """Raised when micro-live execution is requested while it is disabled."""


def assert_micro_live_blocked(
    *,
    execution_enabled: bool,
    kill_switch_active: bool,
) -> None:
    """Raise :class:`MicroLiveBlocked` unless micro-live is fully unlocked.

    Micro-live is only permitted when *all* of the following hold:
      * the module-level ``MICRO_LIVE_ENABLED`` flag is True (it is False), and
      * ``execution_enabled`` is True, and
      * ``kill_switch_active`` is False.

    Because ``MICRO_LIVE_ENABLED`` is False, this always raises today — exactly
    the intended safety posture.
    """
    if MICRO_LIVE_ENABLED and execution_enabled and not kill_switch_active:
        return
    raise MicroLiveBlocked(
        "micro-live execution is disabled "
        f"(MICRO_LIVE_ENABLED={MICRO_LIVE_ENABLED}, "
        f"execution_enabled={execution_enabled}, "
        f"kill_switch_active={kill_switch_active})"
    )


# ---------------------------------------------------------------------------
# Gauntlet orchestration over a batch of cycle results
# ---------------------------------------------------------------------------

GAUNTLET_REJECT_STATUS = "GAUNTLET_REJECTED"


def _cycle_tokens(cycle: object) -> List[str]:
    """Return the lowercase token addresses participating in a cycle."""
    addrs: List[str] = []
    for edge in getattr(cycle, "edges", ()):  # GraphEdge
        for attr in ("token_in_addr", "token_out_addr"):
            val = getattr(edge, attr, None)
            if val:
                addrs.append(str(val).lower())
    # preserve order, drop dups
    seen: set = set()
    uniq: List[str] = []
    for a in addrs:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


def apply_profit_gauntlet(
    cycle_results: Sequence[object],
    *,
    honeypot_fn: Optional[Callable[[str], object]] = None,
    require_known_depth: bool = False,
) -> dict:
    """Re-tag toxic/phantom *positive* cycles in place and return telemetry.

    For every result currently reporting a positive gross, the toxicity
    gauntlet is run.  Toxic results are downgraded (``gross_bps`` zeroed,
    ``status`` set to ``GAUNTLET_REJECTED``, ``reject_reason`` set to the first
    failing reason) so downstream artifact counters no longer treat them as
    candidates.  Non-toxic results are annotated but otherwise unchanged.

    Returns a telemetry dict suitable for embedding in run metrics.
    """
    if honeypot_fn is None:
        from monitoring.sniper_honeypot import check_token_honeypot as honeypot_fn  # type: ignore

    evaluated = 0
    downgraded = 0
    reason_hist: dict = {}

    for qr in cycle_results:
        status = getattr(qr, "status", None)
        gross = getattr(qr, "gross_bps", 0.0) or 0.0
        if status != "POSITIVE_GROSS" or gross <= 0:
            continue
        evaluated += 1

        depth = getattr(qr, "cycle_min_depth_usd", None)
        if depth is None:
            cyc = getattr(qr, "cycle", None)
            depth = getattr(cyc, "min_effective_depth_usd", None) if cyc is not None else None

        # Worst (FAIL beats UNKNOWN beats PASS) honeypot verdict over the path.
        worst = HONEYPOT_PASS
        for addr in _cycle_tokens(getattr(qr, "cycle", None)):
            try:
                v = _normalise_verdict(honeypot_fn(addr))
            except Exception:
                v = HONEYPOT_UNKNOWN
            if v == HONEYPOT_FAIL:
                worst = HONEYPOT_FAIL
                break
            if v == HONEYPOT_UNKNOWN and worst != HONEYPOT_FAIL:
                worst = HONEYPOT_UNKNOWN

        verdict = evaluate_toxicity(
            gross_bps=gross,
            depth_usd=depth,
            honeypot_verdict=worst,
            forward_bps=gross,
            reverse_bps=getattr(qr, "reverse_gross_bps", None),
            require_known_depth=require_known_depth,
        )
        # annotate (additive fields; safe if dataclass defines them)
        try:
            qr.toxicity_reasons = list(verdict.reasons)
        except Exception:
            pass

        if verdict.is_toxic:
            downgraded += 1
            reason = verdict.reasons[0]
            reason_hist[reason] = reason_hist.get(reason, 0) + 1
            try:
                qr.gross_bps = 0.0
                qr.status = GAUNTLET_REJECT_STATUS
                qr.reject_reason = reason
            except Exception:
                pass

    return {
        "schema_version": "m9_profit_gauntlet.1",
        "evaluated_positive": evaluated,
        "downgraded": downgraded,
        "kept": evaluated - downgraded,
        "reason_histogram": dict(sorted(reason_hist.items())),
        "require_known_depth": require_known_depth,
    }
