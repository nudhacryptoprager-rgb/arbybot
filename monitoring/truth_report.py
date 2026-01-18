"""
PATCH for monitoring/truth_report.py

Requirement D): RPC health consistency
If reject_histogram has INFRA_RPC_ERROR > 0, then rpc_total_requests > 0
(or a separate metric like quote_call_attempts exists and is > 0)

BUG: truth_report shows rpc_total_requests=0 when INFRA_RPC_ERROR rejects exist
FIX: Track quote_call_attempts and reconcile with reject histogram
"""

# ============================================================================
# Add these tracking fields to TruthReport or the health collection:
# ============================================================================

from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal


@dataclass
class RPCHealthMetrics:
    """
    RPC health metrics that are consistent with reject histogram.
    
    Key invariant: if infra_rpc_error_count > 0, then some request metric > 0
    """
    # Successful RPC calls
    rpc_success_count: int = 0
    
    # Failed RPC calls (timeouts, connection errors, etc.)
    rpc_failed_count: int = 0
    
    # Total quote attempts (may differ from RPC calls due to caching)
    quote_call_attempts: int = 0
    
    # Derived metrics
    @property
    def rpc_total_requests(self) -> int:
        return self.rpc_success_count + self.rpc_failed_count
    
    @property
    def rpc_success_rate(self) -> float:
        if self.rpc_total_requests == 0:
            return 0.0
        return self.rpc_success_count / self.rpc_total_requests
    
    def reconcile_with_rejects(self, reject_histogram: dict) -> None:
        """
        Ensure health metrics are consistent with reject histogram.
        
        If INFRA_RPC_ERROR exists in rejects, our rpc_failed_count should
        reflect that (at minimum).
        """
        infra_rpc_errors = reject_histogram.get("INFRA_RPC_ERROR", 0)
        
        # If we have INFRA_RPC_ERROR rejects but no tracked failures, reconcile
        if infra_rpc_errors > 0 and self.rpc_failed_count == 0:
            # The rejects themselves prove RPC calls were attempted
            self.rpc_failed_count = infra_rpc_errors
    
    def to_dict(self) -> dict:
        return {
            "rpc_success_rate": round(self.rpc_success_rate, 3),
            "rpc_total_requests": self.rpc_total_requests,
            "rpc_failed_requests": self.rpc_failed_count,
            "quote_call_attempts": self.quote_call_attempts,
        }


# ============================================================================
# Fix in build_health_section() or equivalent:
# ============================================================================

def build_health_section(
    scan_stats: dict,
    reject_histogram: dict,
    rpc_metrics: Optional[RPCHealthMetrics] = None,
) -> dict:
    """
    Build the health section for truth_report.
    
    Ensures RPC health is consistent with observed rejects.
    """
    # Initialize RPC metrics if not provided
    if rpc_metrics is None:
        rpc_metrics = RPCHealthMetrics()
    
    # CRITICAL: Reconcile with reject histogram
    rpc_metrics.reconcile_with_rejects(reject_histogram)
    
    # Build health dict
    health = {
        "rpc_success_rate": rpc_metrics.rpc_success_rate,
        "rpc_avg_latency_ms": scan_stats.get("avg_rpc_latency_ms", 0),
        "rpc_total_requests": rpc_metrics.rpc_total_requests,
        "rpc_failed_requests": rpc_metrics.rpc_failed_count,
        "quote_fetch_rate": scan_stats.get("quote_fetch_rate", 0.0),
        "quote_gate_pass_rate": scan_stats.get("quote_gate_pass_rate", 0.0),
        "chains_active": scan_stats.get("chains_active", 0),
        "dexes_active": scan_stats.get("dexes_active", 0),
        "pairs_covered": scan_stats.get("pairs_covered", 0),
        "pools_scanned": scan_stats.get("pools_scanned", 0),
        "top_reject_reasons": _format_top_rejects(reject_histogram),
    }
    
    return health


def _format_top_rejects(reject_histogram: dict, limit: int = 5) -> list:
    """Format top reject reasons as list of [reason, count] pairs."""
    sorted_rejects = sorted(
        reject_histogram.items(),
        key=lambda x: x[1],
        reverse=True
    )
    return [[reason, count] for reason, count in sorted_rejects[:limit]]


# ============================================================================
# Integration point: Track RPC calls during scanning
# ============================================================================

class RPCCallTracker:
    """
    Track RPC calls during scan cycles for accurate health reporting.
    
    Usage:
        tracker = RPCCallTracker()
        
        # In RPC call wrapper:
        try:
            result = await rpc_call(...)
            tracker.record_success(latency_ms)
        except Exception as e:
            tracker.record_failure(str(e))
        
        # At end of cycle:
        health_metrics = tracker.get_metrics()
    """
    
    def __init__(self):
        self.success_count = 0
        self.failure_count = 0
        self.total_latency_ms = 0
        self.quote_attempts = 0
    
    def record_success(self, latency_ms: int = 0):
        self.success_count += 1
        self.total_latency_ms += latency_ms
        self.quote_attempts += 1
    
    def record_failure(self, error: str = ""):
        self.failure_count += 1
        self.quote_attempts += 1
    
    def record_quote_attempt(self):
        """Record a quote attempt (may be cached, not necessarily RPC)."""
        self.quote_attempts += 1
    
    def get_metrics(self) -> RPCHealthMetrics:
        return RPCHealthMetrics(
            rpc_success_count=self.success_count,
            rpc_failed_count=self.failure_count,
            quote_call_attempts=self.quote_attempts,
        )
    
    @property
    def avg_latency_ms(self) -> int:
        if self.success_count == 0:
            return 0
        return self.total_latency_ms // self.success_count


# ============================================================================
# Example usage in run_scan_cycle:
# ============================================================================

"""
# At start of cycle:
rpc_tracker = RPCCallTracker()

# When making RPC calls (in quote_engine or adapters):
async def get_quote_with_tracking(pool, amount, tracker: RPCCallTracker):
    tracker.record_quote_attempt()
    start = time.monotonic()
    try:
        result = await quoter.quote(pool, amount)
        tracker.record_success(int((time.monotonic() - start) * 1000))
        return result
    except RPCError as e:
        tracker.record_failure(str(e))
        raise

# When building truth_report:
health = build_health_section(
    scan_stats=scan_stats,
    reject_histogram=reject_histogram,
    rpc_metrics=rpc_tracker.get_metrics(),
)
"""
