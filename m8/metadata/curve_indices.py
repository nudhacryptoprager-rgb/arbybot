"""Curve pool coin_indices enrichment for M8.3 registry and bridge routes."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_CURVE_POOL_INDICES = "data/runs/_rolling/m9_curve_pool_indices_latest.json"
_CURVE_POOL_INDICES_SCHEMA = "m9_curve_pool_indices.1"


def _resolve_indices_path(
    indices_path: Optional[str] = None,
    *,
    repo_root: Optional[Path] = None,
) -> Optional[Path]:
    if indices_path:
        p = Path(indices_path)
        return p if p.is_file() else None
    env = os.environ.get("ARBY_CURVE_POOL_INDICES")
    if env:
        p = Path(env)
        return p if p.is_file() else None
    root = repo_root or Path(__file__).resolve().parents[2]
    p = root / DEFAULT_CURVE_POOL_INDICES
    return p if p.is_file() else None


def _probe_quotable(probe_status: str) -> bool:
    return str(probe_status or "").startswith("QUOTE_OK")


def load_curve_pool_indices_by_address(
    indices_path: Optional[str] = None,
    *,
    chain: str = "base",
    repo_root: Optional[Path] = None,
    require_quotable: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """Load pool_address -> curve index row from rolling m9_curve_pool_indices artifact."""
    p = _resolve_indices_path(indices_path, repo_root=repo_root)
    if not p:
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if raw.get("schema_version") != _CURVE_POOL_INDICES_SCHEMA:
        return {}
    if raw.get("chain") and raw.get("chain") != chain:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for pool_addr, pool_data in (raw.get("pools") or {}).items():
        if not isinstance(pool_data, dict):
            continue
        coin_raw = pool_data.get("coin_indices") or {}
        if not isinstance(coin_raw, dict) or len(coin_raw) < 2:
            continue
        try:
            coin_indices = {str(sym): int(idx) for sym, idx in coin_raw.items()}
        except (ValueError, TypeError):
            continue
        probe_status = str(pool_data.get("probe_status") or "")
        if require_quotable and probe_status and not _probe_quotable(probe_status):
            continue
        token_order = sorted(coin_indices.keys(), key=lambda sym: coin_indices[sym])
        out[str(pool_addr).lower()] = {
            "coin_indices": coin_indices,
            "token_order": token_order,
            "coins": token_order,
            "pool_kind": pool_data.get("pool_kind"),
            "curve_variant": pool_data.get("curve_variant"),
            "probe_status": probe_status,
            "underlying_indices": pool_data.get("underlying_indices"),
        }
    return out


def _is_curve_route(route: Dict[str, Any]) -> bool:
    adapter = str(route.get("adapter_type") or route.get("dex_id") or "").lower()
    return "curve" in adapter


def enrich_curve_routes(
    routes: List[Dict[str, Any]],
    *,
    indices_path: Optional[str] = None,
    chain: str = "base",
    repo_root: Optional[Path] = None,
    require_quotable: bool = True,
) -> Dict[str, int]:
    """Stamp coin_indices/token_order onto curve routes from rolling indices artifact."""
    by_addr = load_curve_pool_indices_by_address(
        indices_path,
        chain=chain,
        repo_root=repo_root,
        require_quotable=require_quotable,
    )
    enriched = 0
    for route in routes:
        if not _is_curve_route(route):
            continue
        pool = str(route.get("pool_address") or "").lower()
        if not pool:
            continue
        row = by_addr.get(pool)
        if not row:
            continue
        existing = route.get("coin_indices") or {}
        if isinstance(existing, dict) and len(existing) >= 2:
            continue
        route["coin_indices"] = dict(row["coin_indices"])
        route["coins"] = list(row.get("coins") or row["coin_indices"].keys())
        route["token_order"] = list(row.get("token_order") or route["coins"])
        if row.get("pool_kind") and not route.get("pool_kind"):
            route["pool_kind"] = row["pool_kind"]
        if row.get("curve_variant") and not route.get("curve_variant"):
            route["curve_variant"] = row["curve_variant"]
        if row.get("underlying_indices") and not route.get("underlying_indices"):
            route["underlying_indices"] = row["underlying_indices"]
        if row.get("probe_status") and not route.get("quote_smoke_status"):
            route["quote_smoke_status"] = row["probe_status"]
        route["curve_indices_source"] = "m9_curve_pool_indices"
        enriched += 1
    return {"curve_metadata_enriched": enriched}
