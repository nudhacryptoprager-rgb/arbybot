"""Diagnostic admission policy for M9 productive graph build."""
from __future__ import annotations

import os

DIAGNOSTIC_ADMISSION_MODES = frozenset({"production", "topology_probe"})

PRICE_STATUS_UNKNOWN_DIAGNOSTIC = "UNKNOWN_PRICE_DIAGNOSTIC"


def get_diagnostic_admission_mode() -> str:
    raw = os.environ.get("ARBY_M9_DIAGNOSTIC_ADMISSION_MODE", "production").strip().lower()
    if raw in DIAGNOSTIC_ADMISSION_MODES:
        return raw
    return "production"


def is_topology_probe_mode() -> bool:
    return get_diagnostic_admission_mode() == "topology_probe"
