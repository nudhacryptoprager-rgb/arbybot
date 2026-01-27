# PATH: monitoring/__init__.py
"""
Monitoring package for ARBY.

STEP 4: Stable import contract.

These exports MUST remain stable:
- calculate_confidence
- calculate_price_stability_factor
- RPCHealthMetrics
- TruthReport
- build_truth_report
- build_health_section
- print_truth_report
"""

from monitoring.truth_report import (
    TruthReport,
    RPCHealthMetrics,
    calculate_confidence,
    calculate_price_stability_factor,
    build_truth_report,
    build_health_section,
    build_gate_breakdown,
    print_truth_report,
    SCHEMA_VERSION,
)

__all__ = [
    "TruthReport",
    "RPCHealthMetrics",
    "calculate_confidence",
    "calculate_price_stability_factor",
    "build_truth_report",
    "build_health_section",
    "build_gate_breakdown",
    "print_truth_report",
    "SCHEMA_VERSION",
]
