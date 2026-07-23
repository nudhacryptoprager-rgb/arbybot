"""M8 sniper -> StateRepository sink (vertical migration Step 4).

Reads the canonical M8 sniper rolling artifact (or any compatible
``recent_events`` list) and writes ``PoolRecord`` rows through a
``StateRepository``. The repository is the new system of record; the legacy
``new_pool_sniper_latest.json`` writer stays untouched (the reviewer's
"only after evidence remove the corresponding legacy writer" rule).

Design contract (from production-readiness review issue 4):

* The sink is *additive*: it never weakens or replaces the legacy sniper
  JSON writer; it adds a parallel persistence path so evidence can be
  collected before any legacy code is removed.
* Writes are idempotent via ``IdempotencyKey(chain_id, block_number,
  entity_id=event_id, input_revision=run_timestamp)``. Re-running the same
  sink against the same artifact is a no-op.
* Writes are transactional: every batch is committed via
  ``repository.transaction()``; a failure rolls back the whole batch.
* Each pool row carries the ``factory``/``adapter_type``/``dex``/``fee``
  moved to ``extra`` so operator-facing JSON projections preserve all of
  the legacy sniper fields (the API export stays drop-in).

Chain mapping: the sniper stores the chain *key* (e.g. ``"base"``) on each
``EventTrace``; the repository schema is keyed by ``chain_id`` (integer).
``chains.yaml`` provides the mapping. If the chain is unknown or the
mapping is unreadable, the sink skips the event with a non-error reason
recorded in ``stats.skipped_unknown_chain`` (no silent clobbering).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from state.repository import IdempotencyKey, PoolRecord, StateRepository

__all__ = [
    "ingest_sniper_pool_records",
    "sniper_events_to_pool_records",
    "load_chain_id_map",
]


def load_chain_id_map(chains_yaml: Optional[Path] = None) -> Mapping[str, int]:
    """Return a chain-key -> chain_id map from ``config/chains.yaml``.

    Resilient: returns an empty map if yaml parsing fails or the file is
    absent. The sink then records ``skipped_unknown_chain`` and skips
    events instead of writing rows with ``chain_id=0``.
    """
    path = chains_yaml or (Path("config") / "chains.yaml")
    try:
        import yaml  # type: ignore

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, ValueError, ImportError):
        return {}
    out: Dict[str, int] = {}
    for key, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        cid = cfg.get("chain_id")
        if isinstance(cid, int) and cid > 0:
            out[str(key)] = int(cid)
    return out


def _norm_addr(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = str(s).lower()
    if not s.startswith("0x"):
        return None
    if len(s) != 42:
        return None
    return s


def sniper_events_to_pool_records(
    events: Iterable[Mapping[str, Any]],
    *,
    run_timestamp: str,
    chain_id_map: Optional[Mapping[str, int]] = None,
) -> tuple[List[PoolRecord], Dict[str, int]]:
    """Translate sniper recent_events into PoolRecords.

    Returns ``(records, stats)``. ``stats`` keys: ``admitted``,
    ``skipped_no_pool``, ``skipped_no_chain``, ``skipped_unknown_chain``.
    The caller is responsible for committing them via
    ``repository.transaction()``.
    """
    cmap = chain_id_map or {}
    records: List[PoolRecord] = []
    stats = {
        "admitted": 0,
        "skipped_no_pool": 0,
        "skipped_no_chain": 0,
        "skipped_unknown_chain": 0,
    }
    for ev in events:
        if not isinstance(ev, Mapping):
            stats["skipped_no_pool"] += 1
            continue
        pool = _norm_addr(ev.get("pool") or ev.get("pool_address"))
        if pool is None:
            stats["skipped_no_pool"] += 1
            continue
        chain_key = str(ev.get("chain") or "")
        if not chain_key:
            stats["skipped_no_chain"] += 1
            continue
        chain_id = cmap.get(chain_key)
        if chain_id is None:
            stats["skipped_unknown_chain"] += 1
            continue
        token0 = _norm_addr(ev.get("token0")) or "0x" + "0" * 40
        token1 = _norm_addr(ev.get("token1")) or "0x" + "0" * 40
        dex_id = str(ev.get("dex") or ev.get("dex_id") or "")
        if not dex_id:
            stats["skipped_no_pool"] += 1
            continue
        try:
            block_number = int(ev.get("block_number") or 0)
        except (TypeError, ValueError):
            block_number = 0
        fee = ev.get("fee")
        try:
            fee = int(fee) if fee is not None else None
        except (TypeError, ValueError):
            fee = None
        pool_type = str(
            ev.get("adapter_type") or ev.get("pool_type") or ev.get("layout") or ""
        )
        event_id = str(ev.get("event_id") or f"{dex_id}:{pool}:{block_number}")
        idempotency = IdempotencyKey(
            chain_id=chain_id,
            block_number=block_number,
            entity_id=f"sniper:{event_id}",
            input_revision=str(run_timestamp),
        )
        extra: Dict[str, Any] = {
            "event_id": event_id,
            "factory": str(ev.get("factory") or ""),
            "adapter_type": pool_type,
            "received_ts": ev.get("received_ts"),
            "filter_passed": bool(ev.get("filter_passed") or False),
            "candidate": bool(ev.get("candidate") or False),
            "reject_reason": ev.get("reject_reason"),
            "source_artifact_run_timestamp": run_timestamp,
        }
        # Drop None values from extra to keep projections lean.
        extra = {k: v for k, v in extra.items() if v is not None}
        records.append(
            PoolRecord(
                chain_id=chain_id,
                dex_id=dex_id,
                pool_address=pool,
                token0=token0,
                token1=token1,
                pool_type=pool_type,
                fee=fee,
                status="active",
                idempotency=idempotency,
                extra=extra,
            )
        )
        stats["admitted"] += 1
    return records, stats


def ingest_sniper_pool_records(
    sniper_artifact: Mapping[str, Any],
    repository: StateRepository,
    *,
    chain_id_map: Optional[Mapping[str, int]] = None,
    run_timestamp: Optional[str] = None,
) -> Dict[str, int]:
    """Ingest ``new_pool_sniper_latest.json`` into ``repository``.

    Reads ``run_context.run_timestamp`` (canonical provenance) first,
    falling back to ``generated_at_utc``. Runs the whole batch inside one
    repository transaction. Returns a stats dict (same dict as
    ``sniper_events_to_pool_records`` plus ``committed``).
    """
    rc = sniper_artifact.get("run_context")
    if isinstance(rc, Mapping):
        rts = rc.get("run_timestamp")
    else:
        rts = None
    rts = rts or sniper_artifact.get("generated_at_utc") or "1970-01-01T00:00:00Z"
    if run_timestamp is not None:
        rts = run_timestamp
    events = sniper_artifact.get("recent_events") or []
    if not isinstance(events, list):
        events = []
    records, stats = sniper_events_to_pool_records(
        events, run_timestamp=str(rts), chain_id_map=chain_id_map
    )
    if not records:
        stats["committed"] = 0
        return stats
    try:
        with repository.transaction():
            for rec in records:
                repository.upsert_pool(rec)
    except Exception:
        stats["committed"] = 0
        stats["error"] = 1
        raise
    stats["committed"] = len(records)
    return stats