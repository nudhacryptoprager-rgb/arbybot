"""
monitoring/quality_kpis.py - Quality KPIs tracking system.

Team Lead directive:
"Ввести 'quality KPIs': частка reject по кожному коду, 
і ціль — зменшити топ-3 reject-и на 30–50%."

Tracks:
- Reject rates by error code
- Trend analysis (improving/degrading)
- Target tracking
- Alerts when targets missed
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import get_logger
from core.exceptions import ErrorCode

logger = get_logger(__name__)


# =============================================================================
# KPI TARGETS
# =============================================================================

# Target: reduce top-3 rejects by 30-50%
# Baseline from Team Lead analysis (2026-01-15):
BASELINE_REJECTS = {
    "QUOTE_GAS_TOO_HIGH": 260,
    "PRICE_SANITY_FAILED": 240,
    "TICKS_CROSSED_TOO_MANY": 200,
    "QUOTE_REVERT": 120,
    "SLIPPAGE_TOO_HIGH": 60,
}

# Target percentages (relative to baseline)
TARGET_REDUCTION_PERCENT = 30  # 30% reduction target
STRETCH_TARGET_PERCENT = 50    # 50% stretch goal

# Calculate absolute targets
def calculate_targets(baseline: dict[str, int]) -> dict[str, dict]:
    """Calculate target values from baseline."""
    targets = {}
    for reason, count in baseline.items():
        targets[reason] = {
            "baseline": count,
            "target_30": int(count * 0.70),  # 30% reduction
            "target_50": int(count * 0.50),  # 50% reduction (stretch)
        }
    return targets

REJECT_TARGETS = calculate_targets(BASELINE_REJECTS)


# =============================================================================
# KPI DATA STRUCTURES
# =============================================================================

@dataclass
class CycleMetrics:
    """Metrics for a single scan cycle."""
    cycle_number: int
    timestamp: str
    
    # Quote metrics
    quotes_attempted: int = 0
    quotes_fetched: int = 0
    quotes_passed_gates: int = 0
    
    # Reject counts by reason
    rejects: dict = field(default_factory=dict)
    
    # Spread metrics
    total_spreads: int = 0
    executable_spreads: int = 0
    blocked_spreads: int = 0
    
    # Blocked reasons breakdown
    blocked_reasons: dict = field(default_factory=dict)
    
    @property
    def fetch_rate(self) -> float:
        return self.quotes_fetched / self.quotes_attempted if self.quotes_attempted > 0 else 0.0
    
    @property
    def gate_pass_rate(self) -> float:
        return self.quotes_passed_gates / self.quotes_fetched if self.quotes_fetched > 0 else 0.0
    
    @property
    def execution_rate(self) -> float:
        return self.executable_spreads / self.total_spreads if self.total_spreads > 0 else 0.0
    
    def to_dict(self) -> dict:
        return {
            "cycle_number": self.cycle_number,
            "timestamp": self.timestamp,
            "quotes": {
                "attempted": self.quotes_attempted,
                "fetched": self.quotes_fetched,
                "passed_gates": self.quotes_passed_gates,
                "fetch_rate": round(self.fetch_rate * 100, 1),
                "gate_pass_rate": round(self.gate_pass_rate * 100, 1),
            },
            "rejects": dict(self.rejects),
            "spreads": {
                "total": self.total_spreads,
                "executable": self.executable_spreads,
                "blocked": self.blocked_spreads,
                "execution_rate": round(self.execution_rate * 100, 1),
            },
            "blocked_reasons": dict(self.blocked_reasons),
        }


@dataclass
class KPIReport:
    """Aggregated KPI report."""
    timestamp: str
    cycles_analyzed: int
    
    # Aggregate reject stats
    total_rejects: dict
    avg_rejects_per_cycle: dict
    
    # Target status
    target_status: dict
    
    # Trends (last N cycles)
    trends: dict
    
    # Overall health score
    health_score: float
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "cycles_analyzed": self.cycles_analyzed,
            "total_rejects": self.total_rejects,
            "avg_rejects_per_cycle": self.avg_rejects_per_cycle,
            "target_status": self.target_status,
            "trends": self.trends,
            "health_score": round(self.health_score, 2),
        }


# =============================================================================
# KPI TRACKER
# =============================================================================

class QualityKPITracker:
    """
    Tracks quality KPIs across scan cycles.
    
    Features:
    - Per-cycle metrics collection
    - Rolling averages and trends
    - Target tracking with alerts
    - Persistence across runs
    """
    
    def __init__(
        self,
        data_dir: Path = Path("data/kpis"),
        window_size: int = 20,  # Rolling window for trends
    ):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.window_size = window_size
        
        # Historical metrics
        self._history: list[CycleMetrics] = []
        
        # Load history
        self._load_history()
    
    def _load_history(self) -> None:
        """Load historical metrics."""
        history_file = self.data_dir / "kpi_history.json"
        
        if history_file.exists():
            try:
                with open(history_file) as f:
                    data = json.load(f)
                
                for cycle_data in data.get("cycles", []):
                    metrics = CycleMetrics(
                        cycle_number=cycle_data["cycle_number"],
                        timestamp=cycle_data["timestamp"],
                        quotes_attempted=cycle_data.get("quotes", {}).get("attempted", 0),
                        quotes_fetched=cycle_data.get("quotes", {}).get("fetched", 0),
                        quotes_passed_gates=cycle_data.get("quotes", {}).get("passed_gates", 0),
                        rejects=cycle_data.get("rejects", {}),
                        total_spreads=cycle_data.get("spreads", {}).get("total", 0),
                        executable_spreads=cycle_data.get("spreads", {}).get("executable", 0),
                        blocked_spreads=cycle_data.get("spreads", {}).get("blocked", 0),
                        blocked_reasons=cycle_data.get("blocked_reasons", {}),
                    )
                    self._history.append(metrics)
                
                # Keep only last 100 cycles
                self._history = self._history[-100:]
                
                logger.info(f"Loaded {len(self._history)} cycles of KPI history")
            except Exception as e:
                logger.warning(f"Failed to load KPI history: {e}")
    
    def _save_history(self) -> None:
        """Persist KPI history."""
        history_file = self.data_dir / "kpi_history.json"
        
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycles": [m.to_dict() for m in self._history],
        }
        
        with open(history_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def record_cycle(
        self,
        cycle_number: int,
        quotes_attempted: int,
        quotes_fetched: int,
        quotes_passed_gates: int,
        rejects: dict[str, int],
        total_spreads: int,
        executable_spreads: int,
        blocked_spreads: int,
        blocked_reasons: dict[str, int] | None = None,
    ) -> CycleMetrics:
        """Record metrics for a cycle."""
        metrics = CycleMetrics(
            cycle_number=cycle_number,
            timestamp=datetime.now(timezone.utc).isoformat(),
            quotes_attempted=quotes_attempted,
            quotes_fetched=quotes_fetched,
            quotes_passed_gates=quotes_passed_gates,
            rejects=dict(rejects),
            total_spreads=total_spreads,
            executable_spreads=executable_spreads,
            blocked_spreads=blocked_spreads,
            blocked_reasons=dict(blocked_reasons) if blocked_reasons else {},
        )
        
        self._history.append(metrics)
        
        # Keep only last 100 cycles
        if len(self._history) > 100:
            self._history = self._history[-100:]
        
        self._save_history()
        
        # Check for target alerts
        self._check_alerts(metrics)
        
        return metrics
    
    def _check_alerts(self, metrics: CycleMetrics) -> None:
        """Check for KPI alerts."""
        # Alert if any reject count exceeds 2x baseline
        for reason, count in metrics.rejects.items():
            baseline = BASELINE_REJECTS.get(reason, 0)
            if baseline > 0 and count > baseline * 2:
                logger.warning(
                    f"KPI Alert: {reason} count ({count}) exceeds 2x baseline ({baseline})",
                    extra={"context": {"reason": reason, "count": count, "baseline": baseline}}
                )
        
        # Alert if gate pass rate drops below 50%
        if metrics.gate_pass_rate < 0.5:
            logger.warning(
                f"KPI Alert: Gate pass rate ({metrics.gate_pass_rate:.1%}) below 50%",
                extra={"context": {"gate_pass_rate": metrics.gate_pass_rate}}
            )
    
    def get_rolling_averages(self, window: int | None = None) -> dict[str, float]:
        """Get rolling averages for reject counts."""
        window = window or self.window_size
        recent = self._history[-window:] if len(self._history) >= window else self._history
        
        if not recent:
            return {}
        
        totals: dict[str, int] = defaultdict(int)
        for metrics in recent:
            for reason, count in metrics.rejects.items():
                totals[reason] += count
        
        return {reason: count / len(recent) for reason, count in totals.items()}
    
    def get_trends(self, window: int | None = None) -> dict[str, str]:
        """
        Calculate trends for reject counts.
        
        Compares first half vs second half of window.
        Returns: "improving", "degrading", or "stable" for each reason.
        """
        window = window or self.window_size
        recent = self._history[-window:] if len(self._history) >= window else self._history
        
        if len(recent) < 4:
            return {}
        
        mid = len(recent) // 2
        first_half = recent[:mid]
        second_half = recent[mid:]
        
        def sum_rejects(cycles: list[CycleMetrics], reason: str) -> int:
            return sum(c.rejects.get(reason, 0) for c in cycles)
        
        trends = {}
        all_reasons = set()
        for m in recent:
            all_reasons.update(m.rejects.keys())
        
        for reason in all_reasons:
            first_sum = sum_rejects(first_half, reason)
            second_sum = sum_rejects(second_half, reason)
            
            if first_sum == 0:
                trends[reason] = "new"
            elif second_sum < first_sum * 0.8:
                trends[reason] = "improving"
            elif second_sum > first_sum * 1.2:
                trends[reason] = "degrading"
            else:
                trends[reason] = "stable"
        
        return trends
    
    def get_target_status(self) -> dict[str, dict]:
        """Get status vs targets for each reject reason."""
        averages = self.get_rolling_averages()
        
        status = {}
        for reason, targets in REJECT_TARGETS.items():
            avg = averages.get(reason, 0)
            baseline = targets["baseline"]
            target_30 = targets["target_30"]
            target_50 = targets["target_50"]
            
            if avg <= target_50:
                achievement = "stretch_achieved"
            elif avg <= target_30:
                achievement = "target_achieved"
            elif avg <= baseline:
                achievement = "in_progress"
            else:
                achievement = "above_baseline"
            
            status[reason] = {
                "current_avg": round(avg, 1),
                "baseline": baseline,
                "target_30": target_30,
                "target_50": target_50,
                "reduction_pct": round((1 - avg / baseline) * 100, 1) if baseline > 0 else 0,
                "achievement": achievement,
            }
        
        return status
    
    def calculate_health_score(self) -> float:
        """
        Calculate overall health score (0.0 - 1.0).
        
        Based on:
        - Gate pass rate (40%)
        - Target achievement (30%)
        - Trends (30%)
        """
        if not self._history:
            return 0.5
        
        recent = self._history[-self.window_size:]
        
        # Gate pass rate component
        avg_gate_pass = sum(m.gate_pass_rate for m in recent) / len(recent)
        gate_score = min(1.0, avg_gate_pass / 0.8)  # 80% = perfect
        
        # Target achievement component
        target_status = self.get_target_status()
        achieved = sum(1 for s in target_status.values() 
                      if s["achievement"] in ("target_achieved", "stretch_achieved"))
        target_score = achieved / len(target_status) if target_status else 0.5
        
        # Trends component
        trends = self.get_trends()
        improving = sum(1 for t in trends.values() if t == "improving")
        degrading = sum(1 for t in trends.values() if t == "degrading")
        trend_score = (improving - degrading + len(trends)) / (2 * len(trends)) if trends else 0.5
        
        # Weighted average
        health_score = (
            gate_score * 0.4 +
            target_score * 0.3 +
            trend_score * 0.3
        )
        
        return health_score
    
    def generate_report(self) -> KPIReport:
        """Generate comprehensive KPI report."""
        # Aggregate totals
        total_rejects: dict[str, int] = defaultdict(int)
        for metrics in self._history:
            for reason, count in metrics.rejects.items():
                total_rejects[reason] += count
        
        return KPIReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            cycles_analyzed=len(self._history),
            total_rejects=dict(total_rejects),
            avg_rejects_per_cycle=self.get_rolling_averages(),
            target_status=self.get_target_status(),
            trends=self.get_trends(),
            health_score=self.calculate_health_score(),
        )
    
    def print_report(self) -> None:
        """Print KPI report to console."""
        report = self.generate_report()
        
        print("\n" + "=" * 60)
        print("QUALITY KPI REPORT")
        print("=" * 60)
        print(f"Timestamp: {report.timestamp}")
        print(f"Cycles analyzed: {report.cycles_analyzed}")
        print(f"Health score: {report.health_score:.0%}")
        
        print("\n--- TARGET STATUS ---")
        for reason, status in report.target_status.items():
            trend = report.trends.get(reason, "unknown")
            trend_emoji = {"improving": "📈", "degrading": "📉", "stable": "➡️"}.get(trend, "❓")
            
            print(
                f"  {reason}: {status['current_avg']:.0f} "
                f"(baseline: {status['baseline']}, target: {status['target_30']}) "
                f"[{status['reduction_pct']:+.0f}%] {trend_emoji} {status['achievement']}"
            )
        
        print("=" * 60 + "\n")
    
    def save_report(self, output_dir: Path) -> Path:
        """Save KPI report to file."""
        report = self.generate_report()
        
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filepath = output_dir / f"kpi_report_{timestamp}.json"
        
        with open(filepath, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        
        return filepath


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_kpi_tracker: QualityKPITracker | None = None


def get_kpi_tracker() -> QualityKPITracker:
    """Get singleton KPI tracker."""
    global _kpi_tracker
    
    if _kpi_tracker is None:
        _kpi_tracker = QualityKPITracker()
    
    return _kpi_tracker


def reset_kpi_tracker() -> None:
    """Reset singleton (for testing)."""
    global _kpi_tracker
    _kpi_tracker = None
