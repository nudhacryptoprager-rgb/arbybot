"""Immutable session aggregate — deduped pools/tokens/routes across batches/events."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.pipeline_streaming import STREAMING_ROOT_DIR, sanitize_session_id
from state.repository import StateRepository


@dataclass
class SessionAggregate:
    session_id: str
    pools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tokens: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    routes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    event_offset_watermark: int = 0

    def upsert_pool(self, pool: Dict[str, Any]) -> None:
        addr = str(pool.get("pool_address") or pool.get("pool") or "").lower()
        if not addr:
            return
        self.pools[addr] = {**self.pools.get(addr, {}), **pool}

    def upsert_token(self, token: Dict[str, Any]) -> None:
        addr = str(token.get("address") or token.get("token") or "").lower()
        if not addr:
            return
        self.tokens[addr] = {**self.tokens.get(addr, {}), **token}

    def upsert_route(self, route: Dict[str, Any]) -> None:
        rid = str(route.get("route_id") or route.get("id") or "")
        if not rid:
            pool = str(route.get("pool_address") or "")
            dex = str(route.get("dex_id") or "")
            rid = f"{dex}:{pool.lower()}"
        self.routes[rid] = {**self.routes.get(rid, {}), **route}

    def record_event(self, event: Dict[str, Any]) -> None:
        self.events.append(dict(event))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "session_aggregate.1",
            "session_id": self.session_id,
            "pools": list(self.pools.values()),
            "tokens": list(self.tokens.values()),
            "routes": list(self.routes.values()),
            "events": list(self.events),
            "event_offset_watermark": int(self.event_offset_watermark),
            "counts": {
                "pools": len(self.pools),
                "tokens": len(self.tokens),
                "routes": len(self.routes),
                "events": len(self.events),
            },
        }

    def write(self, path: Path) -> Path:
        return self.write_atomic(path)

    def write_atomic(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        return path


def session_aggregate_path(session_id: str) -> Path:
    safe = sanitize_session_id(session_id)
    return STREAMING_ROOT_DIR / safe / "session_aggregate.json"


def merge_repository_into_aggregate(
    aggregate: SessionAggregate,
    repository: StateRepository,
) -> SessionAggregate:
    for row in repository.list_pools():
            aggregate.upsert_pool(
                {
                    "pool_address": row.get("pool_address"),
                    "dex_id": row.get("dex_id"),
                    "token0": row.get("token0"),
                    "token1": row.get("token1"),
                    "status": row.get("status"),
                    **(row.get("extra") or {}),
                }
            )
    for row in repository.list_routes():
            aggregate.upsert_route(
                {
                    "route_id": row.get("route_id"),
                    "pool_address": row.get("pool_address"),
                    "dex_id": row.get("dex_id"),
                    "token_in": row.get("token_in"),
                    "token_out": row.get("token_out"),
                    "status": row.get("status"),
                    **(row.get("extra") or {}),
                }
            )
    for row in repository.list_tokens():
            aggregate.upsert_token(
                {
                    "address": row.get("address"),
                    "decimals": row.get("decimals"),
                    "symbol": row.get("symbol"),
                    "chain_id": row.get("chain_id"),
                }
            )
    events_fn = getattr(repository, "list_events", None)
    latest_fn = getattr(repository, "latest_event_offset", None)
    if callable(events_fn):
        since = int(aggregate.event_offset_watermark or 0)
        for ev in events_fn(session_id=aggregate.session_id, since_offset=since):
            aggregate.record_event(
                {
                    "event_type": ev.event_type,
                    "entity_id": ev.entity_id,
                    "observed_block": ev.observed_block,
                    "event_offset": ev.event_offset,
                    "payload": dict(ev.payload),
                }
            )
    if callable(latest_fn):
        aggregate.event_offset_watermark = int(latest_fn())
    return aggregate


def merge_batch_artifacts_into_aggregate(
    aggregate: SessionAggregate,
    batch_dir: Path,
) -> SessionAggregate:
    expansion_path = batch_dir / "m8_cross_dex_expansion.json"
    registry_path = batch_dir / "m8_3_token_metadata_registry.json"
    hints_path = batch_dir / "m8_external_pool_hints.json"

    if expansion_path.is_file():
        try:
            exp = json.loads(expansion_path.read_text(encoding="utf-8"))
            for route in exp.get("routes_admitted") or []:
                if isinstance(route, dict):
                    aggregate.upsert_route(route)
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    if registry_path.is_file():
        try:
            reg = json.loads(registry_path.read_text(encoding="utf-8"))
            tokens = reg.get("tokens") or {}
            if isinstance(tokens, dict):
                for addr, meta in tokens.items():
                    if isinstance(meta, dict):
                        aggregate.upsert_token({"address": addr, **meta})
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    if hints_path.is_file():
        try:
            hints_doc = json.loads(hints_path.read_text(encoding="utf-8"))
            for hint in hints_doc.get("hints") or []:
                if isinstance(hint, dict):
                    aggregate.upsert_pool(hint)
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    return aggregate


def build_session_aggregate(
    session_id: str,
    *,
    repository: Optional[StateRepository] = None,
    batch_dirs: Optional[Iterable[Path]] = None,
) -> SessionAggregate:
    aggregate = SessionAggregate(session_id=session_id)
    if repository is not None:
        merge_repository_into_aggregate(aggregate, repository)
    for batch_dir in batch_dirs or []:
        merge_batch_artifacts_into_aggregate(aggregate, Path(batch_dir))
    return aggregate


def load_or_build_session_aggregate(
    session_id: str,
    *,
    repository: Optional[StateRepository] = None,
) -> SessionAggregate:
    path = session_aggregate_path(session_id)
    agg: Optional[SessionAggregate] = None
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            agg = SessionAggregate(
                session_id=session_id,
                event_offset_watermark=int(doc.get("event_offset_watermark") or 0),
            )
            for pool in doc.get("pools") or []:
                if isinstance(pool, dict):
                    agg.upsert_pool(pool)
            for token in doc.get("tokens") or []:
                if isinstance(token, dict):
                    agg.upsert_token(token)
            for route in doc.get("routes") or []:
                if isinstance(route, dict):
                    agg.upsert_route(route)
            agg.events.extend(doc.get("events") or [])
        except (OSError, json.JSONDecodeError, TypeError):
            agg = None

    if agg is None:
        safe = sanitize_session_id(session_id)
        root = STREAMING_ROOT_DIR / safe
        batch_dirs = sorted(root.glob("batch_*")) if root.is_dir() else []
        agg = build_session_aggregate(
            session_id,
            repository=repository,
            batch_dirs=batch_dirs,
        )
    elif repository is not None:
        merge_repository_into_aggregate(agg, repository)

    agg.write_atomic(path)
    return agg


def bridge_inventory_from_aggregate(aggregate: SessionAggregate) -> Dict[str, Any]:
    """Minimal bridge handoff document from continuous session aggregate."""
    routes = list(aggregate.routes.values())
    return {
        "schema_version": "m9_bridge_inventory.1",
        "session_id": aggregate.session_id,
        "source": "session_aggregate",
        "active_routes": routes,
        "graph_ready_total": len(routes),
        "counts": aggregate.to_dict().get("counts") or {},
    }
