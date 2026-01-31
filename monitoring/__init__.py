# PATH: monitoring/__init__.py
"""
Monitoring package.

PUBLIC SYMBOLS (backward compat - DO NOT REMOVE):
- TruthReport
- HealthMetrics
- SpreadSignal
- RPCHealthMetrics ← WAS MISSING!
- create_truth_report
- calculate_confidence
"""

from monitoring.truth_report import (
    TruthReport,
    HealthMetrics,
    SpreadSignal,
    RPCHealthMetrics,
    create_truth_report,
    calculate_confidence,
)

__all__ = [
    "TruthReport",
    "HealthMetrics",
    "SpreadSignal",
    "RPCHealthMetrics",
    "create_truth_report",
    "calculate_confidence",
]
