"""Data models for M9 graph-arbitrage scanner."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class GraphEdge:
    """One directed DEX hop: token_in → token_out through a specific pool/route."""

    token_in_sym: str
    token_out_sym: str
    token_in_addr: str
    token_out_addr: str
    token_in_decimals: int
    token_out_decimals: int
    route_id: str
    dex_id: str
    adapter_type: str
    fee: int
    tick_spacing: Optional[int]
    quoter_addr: str
    pool_address: str
    fee_bps: float
    factory_class: str
    pair_id: str
    factory_verified: bool = False  # True when pool_verifier confirmed this route on-chain

    def __post_init__(self) -> None:
        if not self.token_in_addr.startswith("0x"):
            raise ValueError(f"token_in_addr must be 0x-prefixed: {self.token_in_addr!r}")
        if not self.token_out_addr.startswith("0x"):
            raise ValueError(f"token_out_addr must be 0x-prefixed: {self.token_out_addr!r}")
        if self.token_in_sym == self.token_out_sym:
            raise ValueError(
                f"token_in_sym and token_out_sym must differ: {self.token_in_sym!r}"
            )
        if self.fee_bps < 0:
            raise ValueError(f"fee_bps must be >= 0, got {self.fee_bps}")


@dataclass
class GraphCycle:
    """A closed multi-hop arbitrage cycle through the token graph."""

    edges: tuple  # tuple[GraphEdge, ...]

    def __post_init__(self) -> None:
        if len(self.edges) < 3:
            raise ValueError(
                f"GraphCycle requires >= 3 edges, got {len(self.edges)}"
            )
        # Validate closed path
        for i, edge in enumerate(self.edges):
            next_edge = self.edges[(i + 1) % len(self.edges)]
            if edge.token_out_sym != next_edge.token_in_sym:
                raise ValueError(
                    f"Cycle path not closed at hop {i}: "
                    f"{edge.token_out_sym!r} != {next_edge.token_in_sym!r}"
                )
        # Validate chain continuity (token_out_addr → token_in_addr)
        for i, edge in enumerate(self.edges):
            next_edge = self.edges[(i + 1) % len(self.edges)]
            if edge.token_out_addr.lower() != next_edge.token_in_addr.lower():
                raise ValueError(
                    f"Cycle address chain broken at hop {i}: "
                    f"{edge.token_out_addr} != {next_edge.token_in_addr}"
                )

    @property
    def length(self) -> int:
        return len(self.edges)

    @property
    def token_path(self) -> List[str]:
        return [e.token_in_sym for e in self.edges]

    @property
    def cycle_id(self) -> str:
        """12-char hex derived from sorted route_ids + token_path."""
        route_ids_sorted = sorted(e.route_id for e in self.edges)
        raw = ":".join(route_ids_sorted) + "|" + ":".join(self.token_path)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    @property
    def total_fee_bps(self) -> float:
        return sum(e.fee_bps for e in self.edges)

    @property
    def start_token_sym(self) -> str:
        return self.edges[0].token_in_sym

    @property
    def min_factory_class(self) -> str:
        """Return the 'worst' factory class in the cycle (used for ranking)."""
        order = {"EFFICIENT_BASELINE": 0, "MID_EFFICIENCY": 1, "LOW_EFFICIENCY": 2}
        return max(
            (e.factory_class for e in self.edges),
            key=lambda fc: order.get(fc, 99),
        )


@dataclass
class CycleQuoteResult:
    """Result of quoting a :class:`GraphCycle` at a given size."""

    cycle: GraphCycle
    size_usd: float
    amount_in: int
    amount_out: int
    gross_bps: float
    status: str  # POSITIVE_GROSS | NEGATIVE_GROSS | ZERO_AMOUNT_IN | QUOTE_FAILED | CYCLE_QUOTE_TIMEOUT
    reject_reason: Optional[str]
    leg_results: list  # List of per-leg QuoteResult
    elapsed_s: float
    dynamic_size_usd: Optional[float] = None
    size_candidates_usd: tuple = ()
    depth_curve: Optional[List[Dict[str, Any]]] = None
    dynamic_size_source: Optional[str] = None


@dataclass
class GraphTopology:
    """Summary of the token exchange graph structure."""

    token_count: int
    edge_count: int
    route_count: int
    hub_tokens: List[str]
    dead_end_tokens: List[str]
    missing_edges_for_3cycle: List[Dict]
    adjacency_summary: Dict[str, List[str]]
