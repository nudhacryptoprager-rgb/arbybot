"""M8.3 — Token Metadata Registry & Decimals Service."""

from m8.metadata.acceptance import build_m8_3_diagnostics, evaluate_m8_3_acceptance
from m8.metadata.registry import (
    DEFAULT_REGISTRY_PATH,
    M8_3_DECIMALS_SOURCE_PREFIX,
    apply_registry_to_route,
    build_token_metadata_registry,
    is_economics_grade_entry,
    is_m8_3_provenance_locked,
    load_registry,
    save_registry,
)

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "M8_3_DECIMALS_SOURCE_PREFIX",
    "apply_registry_to_route",
    "build_m8_3_diagnostics",
    "build_token_metadata_registry",
    "evaluate_m8_3_acceptance",
    "is_economics_grade_entry",
    "is_m8_3_provenance_locked",
    "load_registry",
    "save_registry",
]
