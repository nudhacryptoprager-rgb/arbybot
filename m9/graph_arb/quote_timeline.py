"""Wall-clock quote timeline — SLO timestamps must not use per-RPC elapsed_s."""
from __future__ import annotationsimport threadingfrom datetime import datetime, timezonefrom typing import Any, Dict, Optional__all__ = ["QuoteTimelineTracker"]


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class QuoteTimelineTracker:
    """Records first econ RPC dispatch and first successful quote at wall-clock time."""

    def __init__(self) -> None:
        self.first_econ_rpc_attempt_at_utc: Optional[str] = None
        self.first_successful_econ_quote_at_utc: Optional[str] = None
        self.queue_delay_seconds: Optional[float] = None
        self.rpc_service_duration_seconds: Optional[float] = None
        self._lock = threading.Lock()

    def try_mark_econ_dispatch(self, *, size_usd: float, econ_floor_usd: float, queue_delay_s: float) -> None:
        """Stamp first economic-sized RPC dispatch (thread-safe, idempotent)."""
        if float(size_usd) < float(econ_floor_usd):
            return
        with self._lock:
            if self.first_econ_rpc_attempt_at_utc is None:
                self.first_econ_rpc_attempt_at_utc = _iso_now()
                self.queue_delay_seconds = round(float(queue_delay_s), 3)

    def mark_successful_quote(self, *, rpc_duration_s: Optional[float] = None) -> None:
        with self._lock:
            if self.first_successful_econ_quote_at_utc is None:
                self.first_successful_econ_quote_at_utc = _iso_now()
                if rpc_duration_s is not None:
                    self.rpc_service_duration_seconds = round(float(rpc_duration_s), 3)

    def to_scan_scope(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.first_econ_rpc_attempt_at_utc:
            out["first_econ_rpc_attempt_at_utc"] = self.first_econ_rpc_attempt_at_utc
        if self.first_successful_econ_quote_at_utc:
            out["first_successful_econ_quote_at_utc"] = self.first_successful_econ_quote_at_utc
            out["first_shadow_quote_at_utc"] = self.first_successful_econ_quote_at_utc
        if self.queue_delay_seconds is not None:
            out["quote_queue_delay_seconds"] = self.queue_delay_seconds
        if self.rpc_service_duration_seconds is not None:
            out["quote_rpc_service_duration_seconds"] = self.rpc_service_duration_seconds
        return out
