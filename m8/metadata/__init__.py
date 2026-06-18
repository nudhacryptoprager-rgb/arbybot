"""M8.3 — Token Metadata Registry & Decimals Service."""

from m8.metadata.acceptance import evaluate_m8_3_acceptance
from m8.metadata.aggregator import (
    build_aggregated_registry,
    build_m8_3_worker_diagnostics,
    get_dex_route_metadata,
    get_token_registry,
)
from m8.metadata.registry import (
    DEFAULT_REGISTRY_PATH,
    M8_3_DECIMALS_SOURCE_PREFIX,
    SCHEMA_VERSION,
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
    "SCHEMA_VERSION",
    "apply_registry_to_route",
    "build_aggregated_registry",
    "build_m8_3_worker_diagnostics",
    "build_token_metadata_registry",
    "evaluate_m8_3_acceptance",
    "get_dex_route_metadata",
    "get_token_registry",
    "is_economics_grade_entry",
    "is_m8_3_provenance_locked",
    "load_registry",
    "save_registry",
]
