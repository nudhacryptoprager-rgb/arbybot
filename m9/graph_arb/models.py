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
    hooks: Optional[str] = None       # V4 only: hooks address; None = vanilla (0x0)
    token_in_index: Optional[int] = None  # Curve: coin[] index for token_in
    token_out_index: Optional[int] = None  # Curve: coin[] index for token_out
    pool_id: Optional[str] = None         # Balancer: 32-byte pool ID (0x + 64 hex chars)
    vault_address: Optional[str] = None   # Balancer: Vault contract address
    pool_kind: Optional[str] = None       # "stable" | "weighted" | "crypto" | "linear"
    freshness_window: bool = False        # True when M8 sniped pool is within _FRESH_WINDOW_SECONDS
    effective_depth_usd: Optional[float] = None  # measured on-chain depth (pool_depth_probe)
    balancer_assets: Optional[tuple] = None  # Balancer: full pool asset list for queryBatchSwap
    token_a_address: Optional[str] = None  # Maverick: pool tokenA for direction flag

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

    def reversed(self) -> "GraphEdge":
        """Return the opposite-direction hop through the same pool.

        Used for round-trip / asymmetry validation (Step 3).  Pool identity
        fields (route_id, pool_address, fee, hooks, ...) are preserved; only the
        token in/out orientation (and Curve coin indices) are swapped.
        """
        return GraphEdge(
            token_in_sym=self.token_out_sym,
            token_out_sym=self.token_in_sym,
            token_in_addr=self.token_out_addr,
            token_out_addr=self.token_in_addr,
            token_in_decimals=self.token_out_decimals,
            token_out_decimals=self.token_in_decimals,
            route_id=self.route_id,
            dex_id=self.dex_id,
            adapter_type=self.adapter_type,
            fee=self.fee,
            tick_spacing=self.tick_spacing,
            quoter_addr=self.quoter_addr,
            pool_address=self.pool_address,
            fee_bps=self.fee_bps,
            factory_class=self.factory_class,
            pair_id=self.pair_id,
            factory_verified=self.factory_verified,
            hooks=self.hooks,
            token_in_index=self.token_out_index,
            token_out_index=self.token_in_index,
            pool_id=self.pool_id,
            vault_address=self.vault_address,
            pool_kind=self.pool_kind,
            freshness_window=self.freshness_window,
            effective_depth_usd=self.effective_depth_usd,
            balancer_assets=self.balancer_assets,
            token_a_address=self.token_a_address,
        )


@dataclass
class GraphCycle:
    """A closed multi-hop arbitrage cycle through the token graph."""

    edges: tuple  # tuple[GraphEdge, ...]

    def __post_init__(self) -> None:
        if len(self.edges) < 2:
            raise ValueError(
                f"GraphCycle requires >= 2 edges, got {len(self.edges)}"
            )
        # 2-leg cycles (direct cross-venue arbitrage A->B->A) are only
        # economically meaningful when the two hops traverse DIFFERENT pools.
        # A 2-leg loop through the *same* pool is a guaranteed fee-loss
        # round-trip, never an arbitrage. Reject it at construction so the
        # finder/quoter never waste an RPC on a degenerate self-loop.
        if len(self.edges) == 2:
            if self.edges[0].pool_address.lower() == self.edges[1].pool_address.lower():
                raise ValueError(
                    "2-leg GraphCycle requires two distinct pools, got same pool "
                    f"{self.edges[0].pool_address}"
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
    def min_effective_depth_usd(self) -> Optional[float]:
        """Bottleneck on-chain depth of the cycle (min over edges).

        Returns None when no edge carries a measured ``effective_depth_usd``,
        so callers can distinguish "unknown depth" from "shallow depth".
        """
        depths = [
            e.effective_depth_usd
            for e in self.edges
            if e.effective_depth_usd is not None
        ]
        return min(depths) if depths else None

    def reversed(self) -> "GraphCycle":
        """Return the same cycle traversed in the opposite direction.

        A genuine arbitrage cycle and its reverse cannot both be profitable;
        quoting both lets the validator reject one-directional phantoms
        (Step 3 round-trip asymmetry).
        """
        return GraphCycle(edges=tuple(e.reversed() for e in reversed(self.edges)))

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
    cycle_min_depth_usd: Optional[float] = None  # bottleneck effective_depth_usd of cycle
    depth_capped: bool = False  # True when the size ladder was clamped by cycle depth
    reverse_gross_bps: Optional[float] = None  # gross of the reversed cycle (round-trip, Step 3)
    asymmetry_bps: Optional[float] = None  # |forward + reverse| gross spread (Step 3)
    toxicity_reasons: Optional[List[str]] = None  # gauntlet reasons when downgraded (Step 1)
    precision_pass: Optional[bool] = None  # precision-gate verdict (Step 5)
    # Phantom validation RCA (set when reject_reason=PHANTOM_QUOTE_BPS_OVERFLOW)
    raw_gross_bps: Optional[float] = None  # gross before phantom zeroing
    phantom_ceiling_bps: Optional[float] = None  # depth-aware ceiling that was exceeded


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
