"""
Canonical M7 orderflow data contracts: OrderflowEvent, BackrunResult,
IntentSurfaceAssessment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from m7.shared.constants import ALL_EVENT_TYPES, ALL_SURFACES


@dataclass
class OrderflowEvent:
    """A single orderflow event suitable for backrun replay."""

    event_id: str
    event_type: str  # One of ALL_EVENT_TYPES
    chain: str
    block_number: int
    tx_hash: str  # Real or synthetic
    token_in: str  # Symbol (e.g. "USDC")
    token_out: str  # Symbol (e.g. "WETH")
    amount_in_wei: int
    amount_out_wei: int
    dex: str  # Source DEX where event occurred
    pool_address: str
    fee_tier: int
    estimated_size_usd: float
    estimated_impact_bps: float  # Estimated price impact of user trade
    timestamp: str  # ISO-8601

    def __post_init__(self):
        if self.event_type not in ALL_EVENT_TYPES:
            raise ValueError(f"Unknown event_type: {self.event_type!r}")


@dataclass
class BackrunResult:
    """Result of scoring a backrun opportunity from an event."""

    event_id: str
    event_source: str  # "fixture" | "imported" | "live"
    event_type: str
    post_trade_state_used: str  # "estimated" | "simulated" | "quoted" | "live"
    backrun_direction: str  # Direction of backrun
    best_buy_venue: Optional[str] = None
    best_sell_venue: Optional[str] = None
    candidate_path: Optional[List[str]] = None
    amount_in_wei: int = 0
    gross_pnl_wei: int = 0
    gas_cost_wei: int = 0
    fee_cost_wei: int = 0
    net_pnl_wei: int = 0
    best_backrun_net_bps: float = 0.0
    same_block_possible: bool = False
    route_viable: bool = False
    reject_reason: Optional[str] = None
    # M7.A.5 live replay fields
    event_block: Optional[int] = None
    quote_block: Optional[int] = None
    block_lag: Optional[int] = None
    same_state_class: Optional[str] = None
    counter_venue_count: int = 0
    best_live_net_bps: Optional[float] = None
    # M7.A.5.3 ws-live fields
    ws_provider: Optional[str] = None
    event_detected_at_block: Optional[int] = None
    quote_started_block: Optional[int] = None
    quote_finished_block: Optional[int] = None
    quote_pipeline_latency_ms: Optional[float] = None
    venues_pruned_by_multicall: int = 0
    # M7.A.5.3.1 latency budget fields
    latency_budget_ms: Optional[float] = None
    # M7.A.5.4 two-stage pruning fields
    quote_calls_attempted: Optional[int] = None
    quote_calls_after_pruning: Optional[int] = None
    prune_reason_histogram: Optional[Dict[str, int]] = None
    pipeline_stage_latency_ms: Optional[Dict[str, float]] = None
    # M7.A.5.5 actual-pair resolution fields
    pair_resolved: bool = False
    actual_pair: Optional[str] = None
    size_source: Optional[str] = None
    # M7.A.5.6 coverage scan + size sweep fields
    coverage_result: Optional[Dict[str, Any]] = None
    size_sweep_results: Optional[List[Dict[str, Any]]] = None
    best_sweep_net_bps: Optional[float] = None
    best_sweep_size_wei: Optional[int] = None
    token_admitted: Optional[bool] = None
    # M7.A.5.7 coverage enrichment + oracle guard + local-sim fields
    admission_source: Optional[str] = None
    oracle_guard: Optional[Dict[str, Any]] = None
    local_sim_state: Optional[Dict[str, Any]] = None
    # M7.A.5.8 gas decomposition + subgraph seed fields
    l2_gas_bps: Optional[float] = None
    l1_data_bps: Optional[float] = None
    total_gas_bps: Optional[float] = None
    subgraph_seed_used: Optional[bool] = None
    # M7.A.5.9 decimal-aware size normalization fields
    token_in_decimals: Optional[int] = None
    size_normalization_source: Optional[str] = None
    size_usd_estimate: Optional[float] = None
    size_valid_for_token: Optional[bool] = None
    # M7.A.5.15: Causal detail for TOKEN_PAIR_UNRESOLVED
    pair_unresolved_detail: Optional[str] = None
    # M7.A.5.16: Per-event pool contract truth
    pool_contract_truth: Optional[Dict[str, Any]] = None
    # M7.A.5.17: Which adapter path read pool state
    pool_state_read_path: Optional[str] = None
    # M7.A.5.20: Local-state-first pricing fields
    local_pricing_attempted: Optional[bool] = None
    local_pricing_used: Optional[bool] = None
    local_pricing_failure_reason: Optional[str] = None
    # M7.A.5.21: Factory registry + adapter-complete + gas-floor fields
    registry_pools_found: Optional[int] = None
    registry_pools_active: Optional[int] = None
    adapter_type_used: Optional[str] = None
    gas_floor_exceeded: Optional[bool] = None
    gas_floor_bps: Optional[float] = None
    pricing_path: Optional[str] = None
    # M7.A.5.23→5.24: Scoring path used (renamed from low_lag_scoring_path)
    scoring_path: Optional[str] = None
    # M7.A.5.33: Profit guard result in fast path
    profit_guard_passed: Optional[bool] = None
    # E1.16: Resolved token addresses for execution gate (bypass symbol lookup)
    backrun_token_in_address: Optional[str] = None
    backrun_token_out_address: Optional[str] = None
    # E1.12.2: Terminal execution stages — wired through execution_gate.py
    sim_attempted: Optional[bool] = None
    sim_passed: Optional[bool] = None
    simulation_id: Optional[str] = None
    simulation_error: Optional[str] = None
    submit_ready: Optional[bool] = None
    submit_blocker: Optional[str] = None
    calldata_ready: Optional[bool] = None
    signing_ready: Optional[bool] = None


@dataclass
class IntentSurfaceAssessment:
    """Read-only feasibility assessment of an orderflow surface."""

    surface_type: str  # One of ALL_SURFACES
    chain: str
    description: str
    orderflow_accessible: bool
    execution_model: str
    requires_private_inventory: bool
    requires_onchain_execution: bool
    latency_class: str
    capital_requirement_class: str
    quote_infra_ready: bool
    simulation_possible: bool
    current_repo_gap: str
    feasibility_score: str
    key_advantage: str
    key_risk: str
