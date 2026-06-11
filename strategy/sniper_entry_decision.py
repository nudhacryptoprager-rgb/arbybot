"""M8 Phase 2 — Sniper entry decision engine (paper-only).

Pure, side-effect-free decision module.  Given a parsed ``NewPoolEvent``
plus pre-computed metadata, returns a structured :class:`EntryDecision`
saying whether the bot WOULD enter the snipe.

**No on-chain execution.  No signing.  No state mutation.**
This module is the Phase 2 paper-only entry brain.  Real execution is
explicitly blocked until Phase 3 and stays behind the global kill-switch.

The four-phase gating model (matches ``docs/step_pivot.md`` Phase 2.2 A):

    A. Liquidity gate          — initial liquidity ≥ min threshold
    B. Spread estimation       — estimated spread ≥ min bps
    C. Mirror search           — mirror pool found OR strong base token
    D. Composite               — all of the above + honeypot SAFE

Default thresholds are conservative and tunable via constructor.

Public API
----------
- :class:`EntryDecisionVerdict` — enum WOULD_ENTER | SKIP
- :class:`EntryDecision`        — dataclass with verdict + reject_reason + confidence
- :class:`EntryDecisionEngine`  — engine with ``decide(candidate)`` method
- ``make_default_engine()``      — convenience factory with default thresholds

Reject reason codes (closed taxonomy — extend with care):
    NO_LIQUIDITY            — initial liquidity below threshold
    LOW_LIQUIDITY           — liquidity above zero but below min_liquidity_usd
    SPREAD_TOO_TIGHT        — estimated spread below min_spread_bps
    NO_MIRROR_NO_ANCHOR     — no mirror pool and base token not in anchor set
    HONEYPOT_FAIL           — honeypot detector returned FAIL
    HONEYPOT_UNKNOWN        — honeypot returned UNKNOWN (conservative reject)
    INSUFFICIENT_DATA       — required candidate field missing or None
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "EntryDecisionVerdict",
    "EntryDecision",
    "EntryCandidate",
    "EntryDecisionEngine",
    "make_default_engine",
    "DEFAULT_MIN_LIQUIDITY_USD",
    "DEFAULT_MIN_SPREAD_BPS",
    "DEFAULT_ANCHOR_TOKENS",
]

# ---------------------------------------------------------------------------
# Defaults (conservative — see step_pivot.md Phase 2.2 A)
# ---------------------------------------------------------------------------

DEFAULT_MIN_LIQUIDITY_USD: float = 1000.0
DEFAULT_MIN_SPREAD_BPS: float = 50.0

def _load_default_anchor_tokens(chain: str = "base") -> frozenset:
    from m9.graph_arb.core_tokens_loader import anchor_token_addresses

    return anchor_token_addresses(chain)


DEFAULT_ANCHOR_TOKENS: frozenset = _load_default_anchor_tokens()


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class EntryDecisionVerdict(str, Enum):
    """Outcome of the entry-decision engine."""

    WOULD_ENTER = "WOULD_ENTER"
    SKIP = "SKIP"


@dataclass(frozen=True)
class EntryCandidate:
    """Input to the engine.

    All fields are optional except the address fields; missing numeric
    inputs fall through to ``INSUFFICIENT_DATA``.
    """

    # Identity (lowercase hex)
    token0: str
    token1: str
    pool: str

    # Pre-computed metrics (may be None if not yet observed)
    liquidity_usd: Optional[float] = None
    estimated_spread_bps: Optional[float] = None

    # Mirror search result (True = mirror pool found on another DEX)
    mirror_found: bool = False

    # Honeypot verdict — must be one of "PASS", "FAIL", "UNKNOWN", or None
    honeypot_verdict: Optional[str] = None

    # Optional context, propagated to telemetry
    dex: Optional[str] = None
    block_number: Optional[int] = None


@dataclass(frozen=True)
class EntryDecision:
    """Output of the engine."""

    verdict: EntryDecisionVerdict
    reject_reason: Optional[str]    # None when verdict == WOULD_ENTER
    confidence: float                # 0.0..1.0, conservative
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "reject_reason": self.reject_reason,
            "confidence": self.confidence,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class EntryDecisionEngine:
    """Stateless 4-phase entry decision engine."""

    def __init__(
        self,
        *,
        min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD,
        min_spread_bps: float = DEFAULT_MIN_SPREAD_BPS,
        anchor_tokens: Optional[frozenset] = None,
        reject_unknown_honeypot: bool = True,
    ) -> None:
        if min_liquidity_usd < 0:
            raise ValueError("min_liquidity_usd must be >= 0")
        if min_spread_bps < 0:
            raise ValueError("min_spread_bps must be >= 0")

        self.min_liquidity_usd = float(min_liquidity_usd)
        self.min_spread_bps = float(min_spread_bps)
        self.anchor_tokens = (
            frozenset(t.lower() for t in anchor_tokens)
            if anchor_tokens is not None
            else DEFAULT_ANCHOR_TOKENS
        )
        self.reject_unknown_honeypot = bool(reject_unknown_honeypot)

    # ------------------------------------------------------------------
    # Phase gates
    # ------------------------------------------------------------------

    def _gate_liquidity(self, c: EntryCandidate) -> Optional[str]:
        if c.liquidity_usd is None:
            return "INSUFFICIENT_DATA"
        if c.liquidity_usd <= 0:
            return "NO_LIQUIDITY"
        if c.liquidity_usd < self.min_liquidity_usd:
            return "LOW_LIQUIDITY"
        return None

    def _gate_spread(self, c: EntryCandidate) -> Optional[str]:
        if c.estimated_spread_bps is None:
            return "INSUFFICIENT_DATA"
        if c.estimated_spread_bps < self.min_spread_bps:
            return "SPREAD_TOO_TIGHT"
        return None

    def _gate_mirror_or_anchor(self, c: EntryCandidate) -> Optional[str]:
        if c.mirror_found:
            return None
        t0 = (c.token0 or "").lower()
        t1 = (c.token1 or "").lower()
        if t0 in self.anchor_tokens or t1 in self.anchor_tokens:
            return None
        return "NO_MIRROR_NO_ANCHOR"

    def _gate_honeypot(self, c: EntryCandidate) -> Optional[str]:
        verdict = c.honeypot_verdict
        if verdict == "FAIL":
            return "HONEYPOT_FAIL"
        if verdict == "UNKNOWN" and self.reject_unknown_honeypot:
            return "HONEYPOT_UNKNOWN"
        if verdict is None:
            return "INSUFFICIENT_DATA"
        return None

    # ------------------------------------------------------------------
    # Composite decision
    # ------------------------------------------------------------------

    def decide(self, candidate: EntryCandidate) -> EntryDecision:
        notes: list = []

        # Run gates in priority order (cheapest, most decisive first).
        for gate_name, gate in (
            ("liquidity", self._gate_liquidity),
            ("spread", self._gate_spread),
            ("mirror_or_anchor", self._gate_mirror_or_anchor),
            ("honeypot", self._gate_honeypot),
        ):
            reason = gate(candidate)
            if reason is not None:
                notes.append(f"{gate_name}:{reason}")
                return EntryDecision(
                    verdict=EntryDecisionVerdict.SKIP,
                    reject_reason=reason,
                    confidence=0.0,
                    notes=tuple(notes),
                )
            notes.append(f"{gate_name}:pass")

        # All gates passed — confidence scales with margin above thresholds.
        liq_margin = min(
            1.0,
            (candidate.liquidity_usd or 0.0) / max(1.0, self.min_liquidity_usd * 3.0),
        )
        spread_margin = min(
            1.0,
            (candidate.estimated_spread_bps or 0.0) / max(1.0, self.min_spread_bps * 3.0),
        )
        confidence = round(0.5 * (liq_margin + spread_margin), 4)

        return EntryDecision(
            verdict=EntryDecisionVerdict.WOULD_ENTER,
            reject_reason=None,
            confidence=confidence,
            notes=tuple(notes),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_default_engine() -> EntryDecisionEngine:
    """Return an engine pre-configured with conservative defaults."""
    return EntryDecisionEngine()
