"""
M7 triangular — 3-hop cycle discovery, measured scoring, and ranking.

Contains data structures (TriangularCycle, CycleScore, LegQuote,
SizeSweepPoint, SizeSweepResult), cycle finder, fee-based and measured
scorers, ranking/filtering utilities, and same-state classification.

Extracted from engine/triangular_cycles.py during M7.R1 structural refactor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from m7.triangular.graph import PoolEdge, PoolGraph

logger = logging.getLogger("m7.triangular.scoring")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TriangularCycle:
    """A 3-hop cycle: leg1 -> leg2 -> leg3, returning to the start token."""
    leg1: PoolEdge
    leg2: PoolEdge
    leg3: PoolEdge

    def __post_init__(self):
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
        return f"{self.leg1.edge_key}|{self.leg2.edge_key}|{self.leg3.edge_key}"

    @property
    def route_display(self) -> str:
        return (
            f"{self.leg1.token_in}->{self.leg2.token_in}->"
            f"{self.leg3.token_in}->{self.leg3.token_out} "
            f"({self.leg1.dex}/{self.leg2.dex}/{self.leg3.dex})"
        )

    def has_repeated_pool(self) -> bool:
        addrs = [self.leg1.pool_address, self.leg2.pool_address, self.leg3.pool_address]
        return len(set(addrs)) < 3

    def legs(self) -> Tuple[PoolEdge, PoolEdge, PoolEdge]:
        return (self.leg1, self.leg2, self.leg3)


# Same-state classification constants
SAME_STATE_PROVEN = "same_state_proven"
SAME_STATE_AMBIGUOUS = "same_state_ambiguous"
SAME_STATE_VIOLATED = "same_state_violated"


@dataclass
class CycleScore:
    """Full measured decomposition artifact for a scored triangular cycle."""
    cycle: TriangularCycle

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

    same_state_class: str = SAME_STATE_AMBIGUOUS

    reject_reason: Optional[str] = None
    total_fee_bps: float = 0.0
    total_slippage_bps: float = 0.0
    route_viable: bool = True

    def is_promoted(self) -> bool:
        return (
            self.same_state_class == SAME_STATE_PROVEN
            and self.route_viable
            and self.reject_reason is None
            and self.final_net_bps > 0
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route": self.cycle.route_display,
            "tokens": list(self.cycle.tokens),
            "cycle_key": self.cycle.cycle_key,
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
            "same_state_class": self.same_state_class,
            "is_promoted": self.is_promoted(),
            "reject_reason": self.reject_reason,
            "route_viable": self.route_viable,
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


@dataclass
class LegQuote:
    """Per-leg quote result for triangular scoring."""
    amount_in_wei: int
    amount_out_wei: int
    gas_estimate: int = 150_000
    fee_tier: Optional[int] = None
    ticks_crossed: int = 0
    block_number: Optional[int] = None
    quote_source: str = "unknown"
    sqrt_price_before: Optional[int] = None
    sqrt_price_after: Optional[int] = None


@dataclass
class SizeSweepPoint:
    """Single point on a size sweep curve."""
    size_usd: float
    final_net_bps: float
    quoted: bool


@dataclass
class SizeSweepResult:
    """Size sweep result for a single cycle."""
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


# ---------------------------------------------------------------------------
# Cycle finder
# ---------------------------------------------------------------------------

def find_3hop_cycles(
    graph: PoolGraph,
    start_tokens: Optional[Set[str]] = None,
    max_cycles: int = 10_000,
) -> List[TriangularCycle]:
    """Find all valid 3-hop simple cycles A -> B -> C -> A in the graph."""
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
                continue

            edges_b = graph.neighbors(token_b)
            for e2 in edges_b:
                token_c = e2.token_out
                if token_c == token_a or token_c == token_b:
                    continue

                edges_c = graph.neighbors(token_c)
                for e3 in edges_c:
                    if e3.token_out != token_a:
                        continue

                    pool_set = {e1.pool_address, e2.pool_address, e3.pool_address}
                    if len(pool_set) < 3:
                        continue

                    canon_start = min(token_a, token_b, token_c)
                    if token_a != canon_start:
                        continue

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
    """Convert V3 fee tier to bps. V2 default: 30 bps."""
    if fee is None:
        return 30.0
    return fee / 100.0


def score_cycle_fees_only(
    cycle: TriangularCycle,
    gas_cost_usd: float = 0.50,
    notional_usd: float = 100.0,
) -> CycleScore:
    """DIAGNOSTIC PREFILTER — score a cycle by fee structure alone (no RPC)."""
    f1 = _fee_tier_to_bps(cycle.leg1.fee)
    f2 = _fee_tier_to_bps(cycle.leg2.fee)
    f3 = _fee_tier_to_bps(cycle.leg3.fee)
    total_fee = f1 + f2 + f3
    gas_bps = (gas_cost_usd / notional_usd) * 10_000 if notional_usd > 0 else 0
    total_cost_bps = total_fee + gas_bps

    return CycleScore(
        cycle=cycle,
        gross_bps=0.0,
        fee_leg1_bps=f1,
        fee_leg2_bps=f2,
        fee_leg3_bps=f3,
        total_fee_bps=total_fee,
        slippage_leg1_bps=0.0,
        slippage_leg2_bps=0.0,
        slippage_leg3_bps=0.0,
        total_slippage_bps=0.0,
        gas_bps=gas_bps,
        final_net_bps=-total_cost_bps,
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
    """Rank scored cycles by final_net_bps descending."""
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
    """Pre-filter cycles whose fee structure alone exceeds a threshold."""
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
# RPC result -> LegQuote adapter
# ---------------------------------------------------------------------------

def leg_quote_from_rpc_result(
    rpc_result: Optional[Dict[str, Any]],
    amount_in_wei: int,
    fee_tier: Optional[int] = None,
    block_number: Optional[int] = None,
    quote_source: str = "unknown",
) -> Optional[LegQuote]:
    """Convert a raw RPC quote result dict to a LegQuote."""
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
# Same-state provenance classifier
# ---------------------------------------------------------------------------

def classify_same_state(
    leg_block_numbers: List[Optional[int]],
    max_block_drift: int = 1,
) -> str:
    """Classify same-state consistency across 3 legs."""
    if any(b is None for b in leg_block_numbers):
        return SAME_STATE_AMBIGUOUS
    blocks = [b for b in leg_block_numbers if b is not None]
    drift = max(blocks) - min(blocks)
    if drift <= max_block_drift:
        return SAME_STATE_PROVEN
    return SAME_STATE_VIOLATED


# ---------------------------------------------------------------------------
# Live measured scorer
# ---------------------------------------------------------------------------

def _token_usd_estimate(token: str, eth_usd: float) -> float:
    """Rough USD price estimate for gas-to-bps conversion."""
    from strategy.quotes import DEFAULT_TOKEN_USD_PRICES
    t = token.upper()
    if token in DEFAULT_TOKEN_USD_PRICES:
        return DEFAULT_TOKEN_USD_PRICES[token]
    if t in DEFAULT_TOKEN_USD_PRICES:
        return DEFAULT_TOKEN_USD_PRICES[t]
    for k, v in DEFAULT_TOKEN_USD_PRICES.items():
        if k.upper() == t:
            return v
    return 1.0


def score_cycle_measured(
    cycle: TriangularCycle,
    leg1_quote: LegQuote,
    leg2_quote: LegQuote,
    leg3_quote: LegQuote,
    gas_price_wei: int = 100_000_000,
    l1_cost_wei: Optional[int] = None,
    eth_usd_price: float = 2000.0,
    max_block_drift: int = 1,
) -> CycleScore:
    """Live measured scorer for a triangular cycle.

    l1_cost_wei defaults are chain-aware:
      arbitrum_one = 6_000_000_000_000, base/OP-stack = 5_000_000_000_000.
    """
    if l1_cost_wei is None:
        chain_lower = cycle.leg1.chain.lower() if cycle.leg1.chain else ""
        if chain_lower in ("base", "optimism", "zora", "mode"):
            l1_cost_wei = 5_000_000_000_000
        else:
            l1_cost_wei = 6_000_000_000_000
    amount_start = leg1_quote.amount_in_wei
    amount_end = leg3_quote.amount_out_wei
    if amount_start <= 0:
        return CycleScore(
            cycle=cycle,
            reject_reason="ZERO_AMOUNT_IN",
            provenance_summary="measured",
        )

    gross_bps = ((amount_end - amount_start) / amount_start) * 10_000

    f1 = _fee_tier_to_bps(cycle.leg1.fee)
    f2 = _fee_tier_to_bps(cycle.leg2.fee)
    f3 = _fee_tier_to_bps(cycle.leg3.fee)
    total_fee = f1 + f2 + f3

    slip1 = float(leg1_quote.ticks_crossed) * 0.5
    slip2 = float(leg2_quote.ticks_crossed) * 0.5
    slip3 = float(leg3_quote.ticks_crossed) * 0.5
    total_slippage = slip1 + slip2 + slip3

    total_gas_units = (
        leg1_quote.gas_estimate
        + leg2_quote.gas_estimate
        + leg3_quote.gas_estimate
    )
    l2_gas_cost_wei = total_gas_units * gas_price_wei
    total_gas_cost_wei = l2_gas_cost_wei + l1_cost_wei
    gas_cost_usd = (total_gas_cost_wei / 1e18) * eth_usd_price

    dec_in = cycle.leg1.decimals_in
    notional_usd = (amount_start / (10 ** dec_in)) * _token_usd_estimate(
        cycle.leg1.token_in, eth_usd_price
    )
    gas_bps = (gas_cost_usd / notional_usd) * 10_000 if notional_usd > 0 else 0.0

    final_net_bps = gross_bps - gas_bps

    blocks = [leg1_quote.block_number, leg2_quote.block_number, leg3_quote.block_number]
    same_state = classify_same_state(blocks, max_block_drift=max_block_drift)

    known_blocks = [b for b in blocks if b is not None]
    block_tag = str(min(known_blocks)) if known_blocks else "N/A"

    scored_size_usd = notional_usd

    route_viable = (
        leg1_quote.amount_out_wei > 0
        and leg2_quote.amount_out_wei > 0
        and leg3_quote.amount_out_wei > 0
    )

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
