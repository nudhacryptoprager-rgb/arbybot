"""M8.3 metadata task/result contracts (root aggregator ↔ child workers)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

TaskKind = Literal["token_erc20", "dex_route"]


class MetadataErrorCode(str, Enum):
    DECIMALS_UNRESOLVED = "DECIMALS_UNRESOLVED"
    ERC20_DECIMALS_REVERT = "ERC20_DECIMALS_REVERT"
    DECIMALS_CONFLICT = "DECIMALS_CONFLICT"
    NO_CODE = "NO_CODE"
    NON_ERC20 = "NON_ERC20"
    PROBE_CAP_EXHAUSTED = "PROBE_CAP_EXHAUSTED"
    DEX_ROUTE_METADATA_MISSING = "DEX_ROUTE_METADATA_MISSING"
    DEX_ROUTE_METADATA_PARTIAL = "DEX_ROUTE_METADATA_PARTIAL"


@dataclass(frozen=True)
class MetadataTask:
    """Work unit dispatched by root aggregator to a child worker."""

    task_id: str
    kind: TaskKind
    worker_id: str
    address: Optional[str] = None
    route_id: Optional[str] = None
    route: Optional[Dict[str, Any]] = None
    scope: str = "all_routes"
    priority: int = 0


@dataclass
class TokenMetadataResult:
    """Token-level result returned to aggregator (not written by worker)."""

    address: str
    worker_id: str = "erc20_token"
    decimals: Optional[int] = None
    symbol: Optional[str] = None
    name: Optional[str] = None
    source: str = "unresolved"
    economics_grade: str = "unresolved"
    error_code: Optional[str] = None
    code_length: Optional[int] = None
    code_hash: Optional[str] = None
    probe_skipped: bool = False


@dataclass
class DexRouteMetadataResult:
    """DEX-specific route metadata — pool/order/indices, not token decimals."""

    route_id: str
    worker_id: str
    dex_family: str
    ready: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_code: Optional[str] = None
    missing_fields: List[str] = field(default_factory=list)
    quoteability_hint: Optional[str] = None


@dataclass
class MetadataAuthorityDecision:
    """Root merge decision for one token or route."""

    entity_id: str
    entity_kind: TaskKind
    accepted: bool
    authority: str = "m8_3_root_aggregator"
    reason: str = ""
    precedence_rank: int = 0
