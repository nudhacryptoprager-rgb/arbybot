# PATH: engine/triangular_cycles.py
"""
M7.A — 3-hop triangular cycle discovery and measured scoring.

Finds simple cycles A -> B -> C -> A in a PoolGraph and produces
full decomposition artifacts per step_M7.md spec.

CONTRACTS:
- Only 3-hop simple cycles (no repeated tokens, no repeated edges).
- Scoring reuses current measured-cost discipline (fees, slippage, gas).
- Raw spread is diagnostic only; promotion requires full decomposition.
- Same-state classification is mandatory: same_state_proven /
  same_state_ambiguous / same_state_violated.
- Every candidate cycle produces a machine-readable artifact with
  ALL required fields from step_M7.md.
- No cross-chain cycles, no 4+ hops, no aggregator routing.

CYCLE ARTIFACT (required fields):
    gross_bps, fee_leg1_bps, fee_leg2_bps, fee_leg3_bps,
    slippage_leg1_bps_heuristic, slippage_leg2_bps_heuristic, slippage_leg3_bps_heuristic,
    gas_bps, final_net_bps, scored_size_usd, block_tag,
    provenance_summary
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from engine.triangular_graph import PoolEdge, PoolGraph

logger = logging.getLogger("engine.triangular_cycles")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TriangularCycle:
    """A 3-hop cycle: leg1 -> leg2 -> leg3, returning to the start token.

    Immutable: represents a structural cycle in the graph, independent of
    pricing/scoring.
    """
    leg1: PoolEdge
    leg2: PoolEdge
    leg3: PoolEdge

    def __post_init__(self):
        # Validate cycle structure at construction time
        if self.leg1.token_out != self.leg2.token_in:
            raise ValueError(
                f"Leg1 token_out ({self.leg1.token_out}) != Leg2 token_in ({self.leg2.token_in})"
            )
        if self.leg2.token_out != self.leg3.token_in:
            raise ValueError(
                f"Leg2 token_out ({self.leg2.token_out}) != Leg3 token_in ({self.leg3.token_in})"
            )
        if self.leg3.token_out != self.leg1.token_in:
            raise ValueError(
                f"Leg3 token_out ({self.leg3.token_out}) != Leg1 token_in ({self.leg1.token_in})"
            )

    @property
    def tokens(self) -> Tuple[str, str, str]:
        return (self.leg1.token_in, self.leg2.token_in, self.leg3.token_in)

    @property
    def token_set(self) -> frozenset:
        return frozenset(self.tokens)

    @property
    def cycle_key(self) -> str:
        """Deterministic key for this specific cycle (pool-level)."""
        return f"{self.leg1.edge_key}|{self.leg2.edge_key}|{self.leg3.edge_key}"

    @property
    def route_display(self) -> str:
        """Human-readable: WETH->USDC->ARB->WETH (uni_v3/sushi_v3/uni_v3)"""
        return (
            f"{self.leg1.token_in}->{self.leg2.token_in}->"
            f"{self.leg3.token_in}->{self.leg3.token_out} "
            f"({self.leg1.dex}/{self.leg2.dex}/{self.leg3.dex})"
        )

    def has_repeated_pool(self) -> bool:
        """Check if any pool address is used more than once."""
        addrs = [self.leg1.pool_address, self.leg2.pool_address, self.leg3.pool_address]
        return len(set(addrs)) < 3

    def legs(self) -> Tuple[PoolEdge, PoolEdge, PoolEdge]:
        return (self.leg1, self.leg2, self.leg3)


# Same-state classification
SAME_STATE_PROVEN = "same_state_proven"
SAME_STATE_AMBIGUOUS = "same_state_ambiguous"
SAME_STATE_VIOLATED = "same_state_violated"


@dataclass
class CycleScore:
    """Full measured decomposition artifact for a scored triangular cycle.

    All fields from step_M7.md Required Cycle Artifact.
    """
    cycle: TriangularCycle

    # Required fields (step_M7.md)
    gross_bps: float = 0.0
    fee_leg1_bps: float = 0.0
    fee_leg2_bps: float = 0.0
    fee_leg3_bps: float = 0.0
    slippage_leg1_bps: float = 0.0
    slippage_leg2_bps: float = 0.0
    slippage_leg3_bps: float = 0.0
    gas_bps: float = 0.0
    final_net_bps: float = 0.0
    scored_size_usd: float = 0.0
    block_tag: str = ""
    provenance_summary: str = ""

    # Same-state classification (hard acceptance criterion)
    same_state_class: str = SAME_STATE_AMBIGUOUS

    # Recommended supporting fields
    reject_reason: Optional[str] = None
    total_fee_bps: float = 0.0
    total_slippage_bps: float = 0.0
    route_viable: bool = True

    def is_promoted(self) -> bool:
        """Whether this cycle meets canonical truth requirements.

        Per step_M7.md: cycle must have full decomposition, acceptable
        route viability, acceptable provenance, and same_state_proven.
        """
        return (
            self.same_state_class == SAME_STATE_PROVEN
            and self.route_viable
            and self.reject_reason is None
            and self.final_net_bps > 0
        )

    def to_dict(self) -> Dict[str, Any]:
        """Machine-readable decomposition artifact."""
        return {
            "route": self.cycle.route_display,
            "tokens": list(self.cycle.tokens),
            "cycle_key": self.cycle.cycle_key,
            # Required (step_M7.md)
            "gross_bps": round(self.gross_bps, 4),
            "fee_leg1_bps": round(self.fee_leg1_bps, 4),
            "fee_leg2_bps": round(self.fee_leg2_bps, 4),
            "fee_leg3_bps": round(self.fee_leg3_bps, 4),
            "total_fee_bps": round(self.total_fee_bps, 4),
            "slippage_leg1_bps_heuristic": round(self.slippage_leg1_bps, 4),
            "slippage_leg2_bps_heuristic": round(self.slippage_leg2_bps, 4),
            "slippage_leg3_bps_heuristic": round(self.slippage_leg3_bps, 4),
            "total_slippage_bps_heuristic": round(self.total_slippage_bps, 4),
            "gas_bps": round(self.gas_bps, 4),
            "final_net_bps": round(self.final_net_bps, 4),
            "scored_size_usd": round(self.scored_size_usd, 2),
            "block_tag": self.block_tag,
            "provenance_summary": self.provenance_summary,
            # Classification
            "same_state_class": self.same_state_class,
            "is_promoted": self.is_promoted(),
            "reject_reason": self.reject_reason,
            "route_viable": self.route_viable,
            # Per-leg pool identity
            "leg1": {
                "dex": self.cycle.leg1.dex,
                "pool": self.cycle.leg1.pool_address,
                "fee": self.cycle.leg1.fee,
                "adapter_type": self.cycle.leg1.adapter_type,
                "token_in": self.cycle.leg1.token_in,
                "token_out": self.cycle.leg1.token_out,
            },
            "leg2": {
                "dex": self.cycle.leg2.dex,
                "pool": self.cycle.leg2.pool_address,
                "fee": self.cycle.leg2.fee,
                "adapter_type": self.cycle.leg2.adapter_type,
                "token_in": self.cycle.leg2.token_in,
                "token_out": self.cycle.leg2.token_out,
            },
            "leg3": {
                "dex": self.cycle.leg3.dex,
                "pool": self.cycle.leg3.pool_address,
                "fee": self.cycle.leg3.fee,
                "adapter_type": self.cycle.leg3.adapter_type,
                "token_in": self.cycle.leg3.token_in,
                "token_out": self.cycle.leg3.token_out,
            },
        }


# ---------------------------------------------------------------------------
# Cycle finder
# ---------------------------------------------------------------------------

def find_3hop_cycles(
    graph: PoolGraph,
    start_tokens: Optional[Set[str]] = None,
    max_cycles: int = 10_000,
) -> List[TriangularCycle]:
    """Find all valid 3-hop simple cycles A -> B -> C -> A in the graph.

    Rules (from step_M7.md):
    - No repeated tokens (A, B, C must be distinct).
    - No repeated pool addresses (all 3 legs use different pools).
    - Deterministic ordering: canonicalized by sorted token triple
      and edge keys to avoid emitting the same cycle from different
      starting points.

    Args:
        graph: PoolGraph to search.
        start_tokens: If provided, only emit cycles starting from these
                      tokens. Useful for narrowing to core/liquid tokens.
        max_cycles: Safety cap to prevent combinatorial explosion.

    Returns:
        List of TriangularCycle objects (deduplicated).
    """
    tokens_to_scan = start_tokens if start_tokens else graph.all_tokens()
    seen_keys: Set[str] = set()
    cycles: List[TriangularCycle] = []

    for token_a in sorted(tokens_to_scan):
        if len(cycles) >= max_cycles:
            logger.warning("max_cycles=%d reached, stopping enumeration", max_cycles)
            break

        edges_a = graph.neighbors(token_a)
        for e1 in edges_a:
            token_b = e1.token_out
            if token_b == token_a:
                continue  # self-loop edge

            edges_b = graph.neighbors(token_b)
            for e2 in edges_b:
                token_c = e2.token_out
                if token_c == token_a or token_c == token_b:
                    continue  # must be 3 distinct tokens

                # Look for closing edge C -> A
                edges_c = graph.neighbors(token_c)
                for e3 in edges_c:
                    if e3.token_out != token_a:
                        continue  # must close

                    # No repeated pool
                    pool_set = {e1.pool_address, e2.pool_address, e3.pool_address}
                    if len(pool_set) < 3:
                        continue

                    # Canonicalize: use smallest token as start to dedup
                    # rotations of the same cycle (A->B->C->A == B->C->A->B)
                    canon_start = min(token_a, token_b, token_c)
                    if token_a != canon_start:
                        continue  # only emit from canonical start

                    cycle = TriangularCycle(leg1=e1, leg2=e2, leg3=e3)
                    key = cycle.cycle_key
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    cycles.append(cycle)

                    if len(cycles) >= max_cycles:
                        break
                if len(cycles) >= max_cycles:
                    break
            if len(cycles) >= max_cycles:
                break

    logger.info(
        "Found %d 3-hop cycles (chain=%s, scanned_tokens=%d)",
        len(cycles), graph.chain, len(tokens_to_scan),
    )
    return cycles


# ---------------------------------------------------------------------------
# Fee-based scoring (no RPC, uses pool metadata only)
# ---------------------------------------------------------------------------

def _fee_tier_to_bps(fee: Optional[int]) -> float:
    """Convert V3 fee tier (e.g. 3000 = 0.30%) to bps.

    V3 fee tiers are in units of 1/1_000_000, so fee=3000 means 0.3%.
    In bps (1 bp = 0.01%): fee / 100.
    """
    if fee is None:
        return 30.0  # V2 default: 0.30% = 30 bps
    return fee / 100.0


def score_cycle_fees_only(
    cycle: TriangularCycle,
    gas_cost_usd: float = 0.50,
    notional_usd: float = 100.0,
) -> CycleScore:
    """DIAGNOSTIC PREFILTER — score a cycle by fee structure alone (no RPC).

    NOT a canonical truth scorer. This function computes the minimum fee+gas
    cost that any gross spread must overcome, using only pool metadata.
    It is intended for filtering structurally unviable cycles before
    committing RPC calls for live quotes.

    Canonical truth scoring (with live quotes, slippage, same-state proof)
    belongs in a future per-leg scorer that reuses engine/roundtrip.py.

    Args:
        cycle: The triangular cycle to score.
        gas_cost_usd: Estimated gas cost for 3-swap execution.
        notional_usd: Assumed notional for gas-to-bps conversion.

    Returns:
        CycleScore with fee and gas decomposition, gross_bps=0 (no quote),
        same_state_class=AMBIGUOUS, reject_reason='FEE_ONLY_SCORE'.
    """
    f1 = _fee_tier_to_bps(cycle.leg1.fee)
    f2 = _fee_tier_to_bps(cycle.leg2.fee)
    f3 = _fee_tier_to_bps(cycle.leg3.fee)
    total_fee = f1 + f2 + f3
    gas_bps = (gas_cost_usd / notional_usd) * 10_000 if notional_usd > 0 else 0
    total_cost_bps = total_fee + gas_bps

    return CycleScore(
        cycle=cycle,
        gross_bps=0.0,  # no quote data
        fee_leg1_bps=f1,
        fee_leg2_bps=f2,
        fee_leg3_bps=f3,
        total_fee_bps=total_fee,
        slippage_leg1_bps=0.0,
        slippage_leg2_bps=0.0,
        slippage_leg3_bps=0.0,
        total_slippage_bps=0.0,
        gas_bps=gas_bps,
        final_net_bps=-total_cost_bps,  # purely cost; needs positive gross to overcome
        scored_size_usd=notional_usd,
        block_tag="N/A",
        provenance_summary="fee_structure_only",
        same_state_class=SAME_STATE_AMBIGUOUS,
        reject_reason="FEE_ONLY_SCORE" if total_cost_bps > 0 else None,
        route_viable=True,
    )


# ---------------------------------------------------------------------------
# Ranking / filtering utilities
# ---------------------------------------------------------------------------

def rank_cycles_by_net(
    scores: List[CycleScore],
    min_net_bps: Optional[float] = None,
    promoted_only: bool = False,
) -> List[CycleScore]:
    """Rank scored cycles by final_net_bps descending.

    Args:
        scores: List of scored cycles.
        min_net_bps: If set, filter to cycles with final_net_bps >= threshold.
        promoted_only: If True, only include canonically promoted cycles.

    Returns:
        Sorted list (best first).
    """
    result = scores
    if promoted_only:
        result = [s for s in result if s.is_promoted()]
    if min_net_bps is not None:
        result = [s for s in result if s.final_net_bps >= min_net_bps]
    return sorted(result, key=lambda s: s.final_net_bps, reverse=True)


def filter_viable_fee_structures(
    cycles: List[TriangularCycle],
    max_total_fee_bps: float = 100.0,
) -> List[TriangularCycle]:
    """Pre-filter cycles whose fee structure alone exceeds a threshold.

    Cycles where the sum of LP fees across all 3 legs is already above
    max_total_fee_bps are unlikely to be profitable regardless of spread.

    Args:
        cycles: List of cycles to filter.
        max_total_fee_bps: Maximum allowed total fee in bps.

    Returns:
        Filtered list of cycles.
    """
    result = []
    for c in cycles:
        total = (
            _fee_tier_to_bps(c.leg1.fee)
            + _fee_tier_to_bps(c.leg2.fee)
            + _fee_tier_to_bps(c.leg3.fee)
        )
        if total <= max_total_fee_bps:
            result.append(c)
    filtered = len(cycles) - len(result)
    if filtered > 0:
        logger.info(
            "Fee filter: %d/%d cycles removed (max_total_fee_bps=%.1f)",
            filtered, len(cycles), max_total_fee_bps,
        )
    return result


# ---------------------------------------------------------------------------
# RPC result -> LegQuote adapter (pure conversion, no RPC imports)
# ---------------------------------------------------------------------------

def leg_quote_from_rpc_result(
    rpc_result: Optional[Dict[str, Any]],
    amount_in_wei: int,
    fee_tier: Optional[int] = None,
    block_number: Optional[int] = None,
    quote_source: str = "unknown",
) -> Optional["LegQuote"]:
    """Convert a raw RPC quote result dict to a LegQuote.

    Accepts the canonical dict shape returned by read_quoter_v2,
    read_algebra_quoter, or a ve33-style dict.

    Args:
        rpc_result: Dict with at minimum "amount_out" (int).
            Optional: "gas_estimate", "ticks_crossed", "sqrt_price_after".
            None means the quote failed.
        amount_in_wei: The amount fed into this leg.
        fee_tier: Pool fee tier (from PoolEdge.fee).
        block_number: Block at which the quote was taken.
        quote_source: Adapter/quote source label.

    Returns:
        LegQuote on success, None if rpc_result is None or amount_out <= 0.
    """
    if rpc_result is None:
        return None
    amount_out = rpc_result.get("amount_out", 0)
    if amount_out <= 0:
        return None
    return LegQuote(
        amount_in_wei=amount_in_wei,
        amount_out_wei=amount_out,
        gas_estimate=rpc_result.get("gas_estimate") or 150_000,
        fee_tier=fee_tier,
        ticks_crossed=rpc_result.get("ticks_crossed") or 0,
        block_number=block_number,
        quote_source=quote_source,
        sqrt_price_after=rpc_result.get("sqrt_price_after"),
    )


# ---------------------------------------------------------------------------
# Same-state provenance classifier (3-leg block consistency)
# ---------------------------------------------------------------------------

def classify_same_state(
    leg_block_numbers: List[Optional[int]],
    max_block_drift: int = 1,
) -> str:
    """Classify same-state consistency across 3 legs.

    Per step_M7.md: same-state is a hard acceptance criterion.
    A cycle must not be promoted unless block provenance shows
    sufficiently consistent market state across all legs.

    Args:
        leg_block_numbers: [block_leg1, block_leg2, block_leg3].
            None means block info unavailable for that leg.
        max_block_drift: Maximum allowed block difference (inclusive).
            Default 1 = quotes from same or adjacent blocks.

    Returns:
        SAME_STATE_PROVEN if all legs have block numbers and
            max(blocks) - min(blocks) <= max_block_drift.
        SAME_STATE_VIOLATED if drift exceeds threshold.
        SAME_STATE_AMBIGUOUS if any leg has None block info.
    """
    if any(b is None for b in leg_block_numbers):
        return SAME_STATE_AMBIGUOUS
    blocks = [b for b in leg_block_numbers if b is not None]
    drift = max(blocks) - min(blocks)
    if drift <= max_block_drift:
        return SAME_STATE_PROVEN
    return SAME_STATE_VIOLATED


# ---------------------------------------------------------------------------
# Live measured scorer (reuses roundtrip.py discipline)
# ---------------------------------------------------------------------------

@dataclass
class LegQuote:
    """Per-leg quote result for triangular scoring.

    Captures the same information as roundtrip.py quote dicts
    but structured for 3-leg cycles.
    """
    amount_in_wei: int
    amount_out_wei: int
    gas_estimate: int = 150_000
    fee_tier: Optional[int] = None
    ticks_crossed: int = 0
    block_number: Optional[int] = None
    quote_source: str = "unknown"
    sqrt_price_before: Optional[int] = None
    sqrt_price_after: Optional[int] = None


def score_cycle_measured(
    cycle: TriangularCycle,
    leg1_quote: LegQuote,
    leg2_quote: LegQuote,
    leg3_quote: LegQuote,
    gas_price_wei: int = 100_000_000,
    l1_cost_wei: int = 6_000_000_000_000,
    eth_usd_price: float = 2000.0,
    max_block_drift: int = 1,
) -> CycleScore:
    """Live measured scorer for a triangular cycle.

    Reuses the measured-cost discipline from engine/roundtrip.py:
    - gross = amount_out_leg3 / amount_in_leg1 - 1 (the triangular return)
    - fees are embedded in quotes (LP fees are already deducted from amount_out)
    - slippage from ticks_crossed heuristic or sqrtPrice measurement
    - gas from quoter estimates + L1 overhead
    - same-state from block number comparison across 3 legs

    IMPORTANT: In a standard AMM quote, LP fees are already deducted from
    amount_out. So gross_bps already includes fee impact. We still report
    per-leg fee_bps for decomposition visibility (from pool metadata), but
    fees are NOT subtracted again from final_net.

    Args:
        cycle: The TriangularCycle to score.
        leg1_quote: Quote for leg1 (amount_in = starting amount).
        leg2_quote: Quote for leg2 (amount_in = leg1.amount_out).
        leg3_quote: Quote for leg3 (amount_in = leg2.amount_out).
        gas_price_wei: L2 gas price in wei.
        l1_cost_wei: L1 data posting overhead in wei.
        eth_usd_price: ETH/USD price for gas-to-bps conversion.
        max_block_drift: Max block drift for same-state classification.

    Returns:
        CycleScore with full measured decomposition.
    """
    # --- Gross return ---
    amount_start = leg1_quote.amount_in_wei
    amount_end = leg3_quote.amount_out_wei
    if amount_start <= 0:
        return CycleScore(
            cycle=cycle,
            reject_reason="ZERO_AMOUNT_IN",
            provenance_summary="measured",
        )

    gross_bps = ((amount_end - amount_start) / amount_start) * 10_000

    # --- Per-leg fee decomposition (metadata, for visibility) ---
    f1 = _fee_tier_to_bps(cycle.leg1.fee)
    f2 = _fee_tier_to_bps(cycle.leg2.fee)
    f3 = _fee_tier_to_bps(cycle.leg3.fee)
    total_fee = f1 + f2 + f3

    # --- Per-leg slippage heuristic (ticks_crossed * 0.5 bps per tick) ---
    # NOTE: This is a diagnostic heuristic, not truly measured slippage.
    # True measured slippage would require comparing quote to a zero-impact reference.
    slip1 = float(leg1_quote.ticks_crossed) * 0.5
    slip2 = float(leg2_quote.ticks_crossed) * 0.5
    slip3 = float(leg3_quote.ticks_crossed) * 0.5
    total_slippage = slip1 + slip2 + slip3

    # --- Gas ---
    total_gas_units = (
        leg1_quote.gas_estimate
        + leg2_quote.gas_estimate
        + leg3_quote.gas_estimate
    )
    l2_gas_cost_wei = total_gas_units * gas_price_wei
    total_gas_cost_wei = l2_gas_cost_wei + l1_cost_wei
    gas_cost_usd = (total_gas_cost_wei / 1e18) * eth_usd_price

    # Notional in USD for bps conversion — use leg1 decimals
    dec_in = cycle.leg1.decimals_in
    # Token USD price: for WETH we use eth_usd_price, for stablecoins ~1.0
    # Simplified: use amount_start in token-native + decimals
    notional_usd = (amount_start / (10 ** dec_in)) * _token_usd_estimate(
        cycle.leg1.token_in, eth_usd_price
    )
    gas_bps = (gas_cost_usd / notional_usd) * 10_000 if notional_usd > 0 else 0.0

    # --- Final net ---
    # Gross already embeds LP fees (AMM quotes are fee-inclusive).
    # Subtract only gas (the external cost not captured in quotes).
    final_net_bps = gross_bps - gas_bps

    # --- Same-state ---
    blocks = [leg1_quote.block_number, leg2_quote.block_number, leg3_quote.block_number]
    same_state = classify_same_state(blocks, max_block_drift=max_block_drift)

    # --- Block tag ---
    known_blocks = [b for b in blocks if b is not None]
    block_tag = str(min(known_blocks)) if known_blocks else "N/A"

    # --- Scored size (single tested notional, not an optimized best size) ---
    scored_size_usd = notional_usd

    # --- Route viability ---
    route_viable = (
        leg1_quote.amount_out_wei > 0
        and leg2_quote.amount_out_wei > 0
        and leg3_quote.amount_out_wei > 0
    )

    # --- Reject reason ---
    reject_reason: Optional[str] = None
    if not route_viable:
        reject_reason = "ZERO_AMOUNT_OUT"
    elif same_state == SAME_STATE_VIOLATED:
        reject_reason = "SAME_STATE_VIOLATED"
    elif final_net_bps <= 0:
        reject_reason = "NET_NEGATIVE"

    return CycleScore(
        cycle=cycle,
        gross_bps=gross_bps,
        fee_leg1_bps=f1,
        fee_leg2_bps=f2,
        fee_leg3_bps=f3,
        total_fee_bps=total_fee,
        slippage_leg1_bps=slip1,
        slippage_leg2_bps=slip2,
        slippage_leg3_bps=slip3,
        total_slippage_bps=total_slippage,
        gas_bps=gas_bps,
        final_net_bps=final_net_bps,
        scored_size_usd=scored_size_usd,
        block_tag=block_tag,
        provenance_summary="measured",
        same_state_class=same_state,
        reject_reason=reject_reason,
        route_viable=route_viable,
    )


# ---------------------------------------------------------------------------
# Size sweep result (bounded size ladder over top candidates)
# ---------------------------------------------------------------------------

@dataclass
class SizeSweepPoint:
    """Single point on a size sweep curve."""
    size_usd: float
    final_net_bps: float
    quoted: bool  # False if quoting failed at this size


@dataclass
class SizeSweepResult:
    """Size sweep result for a single cycle.

    Captures the full size curve and identifies the best notional.
    """
    cycle: TriangularCycle
    best_size_usd: float
    best_net_bps: float
    best_score: CycleScore
    size_curve: List[SizeSweepPoint]
    sizes_attempted: int
    sizes_quoted: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_key": self.cycle.cycle_key,
            "route": self.cycle.route_display,
            "best_size_usd": round(self.best_size_usd, 2),
            "best_net_bps": round(self.best_net_bps, 4),
            "sizes_attempted": self.sizes_attempted,
            "sizes_quoted": self.sizes_quoted,
            "size_curve": [
                {
                    "size_usd": round(p.size_usd, 2),
                    "final_net_bps": round(p.final_net_bps, 4),
                    "quoted": p.quoted,
                }
                for p in self.size_curve
            ],
            "best_decomposition": self.best_score.to_dict(),
        }


def _token_usd_estimate(token: str, eth_usd: float) -> float:
    """Rough USD price estimate for gas-to-bps conversion.

    Reuses canonical DEFAULT_TOKEN_USD_PRICES from strategy.quotes
    as single source of truth. Falls back to $1 for unknowns.
    This is NOT a price oracle — just enough for notional sizing.
    """
    from strategy.quotes import DEFAULT_TOKEN_USD_PRICES
    t = token.upper()
    # Direct lookup (canonical dict is case-sensitive, check both forms)
    if token in DEFAULT_TOKEN_USD_PRICES:
        return DEFAULT_TOKEN_USD_PRICES[token]
    if t in DEFAULT_TOKEN_USD_PRICES:
        return DEFAULT_TOKEN_USD_PRICES[t]
    # Case-insensitive fallback
    for k, v in DEFAULT_TOKEN_USD_PRICES.items():
        if k.upper() == t:
            return v
    return 1.0
