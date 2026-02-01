# PATH: monitoring/truth_report.py
"""
Truth Report generator for ARBY.

BACKWARD COMPATIBILITY CONTRACT:
- RPCHealthMetrics MUST exist
- TruthReport MUST exist
- calculate_confidence MUST exist

M5_0: Uses EXECUTION_DISABLED (stage-agnostic).
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.constants import (
    SCHEMA_VERSION,
    ExecutionBlocker,
    CURRENT_EXECUTION_BLOCKER,
)


@dataclass
class RPCHealthMetrics:
    """RPC health metrics container."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_requests: int = 0
    avg_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    success_rate: float = 1.0
    endpoints_healthy: int = 0
    endpoints_total: int = 0
    
    @property
    def health_ratio(self) -> float:
        if self.endpoints_total == 0:
            return 0.0
        return self.endpoints_healthy / self.endpoints_total


@dataclass
class SpreadSignal:
    """Spread opportunity."""
    pair: str
    buy_dex: str
    sell_dex: str
    buy_price: str
    sell_price: str
    spread_bps: int
    is_profitable: bool
    confidence: str = "medium"


@dataclass
class HealthMetrics:
    """Health metrics for scan."""
    quotes_total: int = 0
    quotes_fetched: int = 0
    gates_passed: int = 0
    dexes_active: int = 0
    price_sanity_passed: int = 0
    price_sanity_failed: int = 0
    price_stability_factor: float = 0.0
    rpc_errors: int = 0
    rpc_success_rate: float = 1.0


@dataclass
class TruthReport:
    """Truth Report - single source of truth."""
    schema_version: str = SCHEMA_VERSION
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_mode: str = "REGISTRY_REAL"
    
    execution_enabled: bool = False
    execution_blocker: str = CURRENT_EXECUTION_BLOCKER.value
    cost_model_available: bool = False
    
    spread_signals: List[SpreadSignal] = field(default_factory=list)
    health: HealthMetrics = field(default_factory=HealthMetrics)
    stats: Dict[str, Any] = field(default_factory=dict)
    
    chain_id: int = 42161
    current_block: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "timestamp": self.timestamp,
            "run_mode": self.run_mode,
            "execution_enabled": self.execution_enabled,
            "execution_blocker": self.execution_blocker,
            "cost_model_available": self.cost_model_available,
            "chain_id": self.chain_id,
            "current_block": self.current_block,
            "health": asdict(self.health),
            "stats": self.stats,
            "spread_signals": [asdict(s) for s in self.spread_signals],
        }


def calculate_confidence(
    spread_bps: int,
    liquidity_score: float = 1.0,
    rpc_health: Optional[RPCHealthMetrics] = None,
) -> str:
    """Calculate confidence level."""
    if spread_bps < 30:
        return "low"
    elif spread_bps < 100:
        base = "medium"
    else:
        base = "high"
    
    if rpc_health and rpc_health.success_rate < 0.9:
        if base == "high":
            return "medium"
        elif base == "medium":
            return "low"
    
    return base
