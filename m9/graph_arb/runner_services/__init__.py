"""Runner application services — incremental extraction from runner._run."""
from __future__ import annotations

from m9.graph_arb.runner_services.inventory_admission import (
    ProductiveInventoryAdmissionResult,
    admit_productive_inventory,
)

__all__ = [
    "ProductiveInventoryAdmissionResult",
    "admit_productive_inventory",
]
