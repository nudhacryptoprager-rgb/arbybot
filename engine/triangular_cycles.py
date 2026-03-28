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
    slippage_leg1_bps, slippage_leg2_bps, slippage_leg3_bps,
    gas_bps, final_net_bps, best_size_usd, block_tag,
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
    best_size_usd: float = 0.0
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
            "slippage_leg1_bps": round(self.slippage_leg1_bps, 4),
            "slippage_leg2_bps": round(self.slippage_leg2_bps, 4),
            "slippage_leg3_bps": round(self.slippage_leg3_bps, 4),
            "total_slippage_bps": round(self.total_slippage_bps, 4),
            "gas_bps": round(self.gas_bps, 4),
            "final_net_bps": round(self.final_net_bps, 4),
            "best_size_usd": round(self.best_size_usd, 2),
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
    """Score a cycle using fee structure alone (no live quotes).

    This is a conservative lower-bound: it computes the fee drag
    without any spread information. Useful for filtering structurally
    unviable cycles before calling RPC for live quotes.

    The resulting final_net_bps is the fee+gas cost in bps that any
    gross spread must overcome. A cycle with high fee_total is unlikely
    to be profitable.

    Args:
        cycle: The triangular cycle to score.
        gas_cost_usd: Estimated gas cost for 3-swap execution.
        notional_usd: Assumed notional for gas-to-bps conversion.

    Returns:
        CycleScore with fee and gas decomposition, gross_bps=0 (no quote).
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
        best_size_usd=notional_usd,
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
