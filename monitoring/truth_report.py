# PATH: monitoring/truth_report.py
"""
Truth Report generator for ARBY.

M5_0: Uses EXECUTION_DISABLED (stage-agnostic), NOT _M4.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.constants import (
    SCHEMA_VERSION,
    ExecutionBlocker,
    CURRENT_EXECUTION_BLOCKER,
)

logger = logging.getLogger("monitoring.truth_report")


@dataclass
class SpreadSignal:
    """Spread opportunity (signal-only without cost model)."""
    pair: str
    buy_dex: str
    sell_dex: str
    buy_price: str
    sell_price: str
    spread_bps: int
    is_profitable: bool  # SIGNAL-ONLY without cost model
    is_profitable_net: Optional[bool] = None
    estimated_profit_usd: Optional[str] = None
    confidence: str = "medium"
    buy_pool_address: Optional[str] = None
    sell_pool_address: Optional[str] = None
    buy_fee: Optional[int] = None
    sell_fee: Optional[int] = None


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
    """
    Truth Report - single source of truth.
    
    M5_0: execution_blocker = EXECUTION_DISABLED (stage-agnostic)
    """
    schema_version: str = SCHEMA_VERSION
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    run_mode: str = "REGISTRY_REAL"
    
    # Execution (disabled, stage-agnostic)
    execution_enabled: bool = False
    execution_blocker: str = CURRENT_EXECUTION_BLOCKER.value  # EXECUTION_DISABLED
    cost_model_available: bool = False
    
    # Signals
    spread_signals: List[SpreadSignal] = field(default_factory=list)
    
    # Health
    health: HealthMetrics = field(default_factory=HealthMetrics)
    
    # Stats
    stats: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    chain_id: int = 42161
    current_block: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON."""
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
    
    def save(self, output_dir: Path, timestamp_str: Optional[str] = None) -> Path:
        """Save report to JSON."""
        if timestamp_str is None:
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        reports_dir = output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = reports_dir / f"truth_report_{timestamp_str}.json"
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        
        logger.info(f"Truth report saved: {output_path}")
        return output_path


def create_truth_report(
    scan_stats: Dict[str, Any],
    spread_signals: List[Dict[str, Any]],
    run_mode: str = "REGISTRY_REAL",
    chain_id: int = 42161,
    current_block: int = 0,
    execution_enabled: bool = False,
    cost_model_available: bool = False,
) -> TruthReport:
    """Create TruthReport from scan results."""
    health = HealthMetrics(
        quotes_total=scan_stats.get("quotes_total", 0),
        quotes_fetched=scan_stats.get("quotes_fetched", 0),
        gates_passed=scan_stats.get("gates_passed", 0),
        dexes_active=scan_stats.get("dexes_active", 0),
        price_sanity_passed=scan_stats.get("price_sanity_passed", 0),
        price_sanity_failed=scan_stats.get("price_sanity_failed", 0),
        price_stability_factor=scan_stats.get("price_stability_factor", 0.0),
        rpc_errors=scan_stats.get("rpc_errors", 0),
        rpc_success_rate=scan_stats.get("rpc_success_rate", 1.0),
    )
    
    signals = []
    for s in spread_signals:
        signals.append(SpreadSignal(
            pair=s.get("pair", ""),
            buy_dex=s.get("buy_dex", ""),
            sell_dex=s.get("sell_dex", ""),
            buy_price=str(s.get("buy_price", "0")),
            sell_price=str(s.get("sell_price", "0")),
            spread_bps=s.get("spread_bps", 0),
            is_profitable=s.get("is_profitable", False),
            is_profitable_net=s.get("is_profitable_net"),
            estimated_profit_usd=str(s.get("estimated_profit_usd")) if s.get("estimated_profit_usd") else None,
            confidence=s.get("confidence", "medium"),
            buy_pool_address=s.get("buy_pool_address"),
            sell_pool_address=s.get("sell_pool_address"),
            buy_fee=s.get("buy_fee"),
            sell_fee=s.get("sell_fee"),
        ))
    
    # Determine blocker (stage-agnostic)
    if not execution_enabled:
        blocker = CURRENT_EXECUTION_BLOCKER.value  # EXECUTION_DISABLED
    elif not cost_model_available:
        blocker = ExecutionBlocker.NO_COST_MODEL.value
    else:
        blocker = ""
    
    return TruthReport(
        run_mode=run_mode,
        execution_enabled=execution_enabled,
        execution_blocker=blocker,
        cost_model_available=cost_model_available,
        spread_signals=signals,
        health=health,
        stats=scan_stats,
        chain_id=chain_id,
        current_block=current_block,
    )
