"""M8 ingest — poll sniper artifact with freshness contract and repository cursor."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Set

from core.continuous_pipeline import EVENT_POOL_DISCOVERED, ContinuousOrchestrator, PipelineEvent
from state.repository import StateRepository

SNIPER_ROLLING_PATH = Path("data/runs/_rolling/new_pool_sniper_latest.json")
DEFAULT_MAX_ARTIFACT_AGE_S = 3600
DEFAULT_CHAIN_ID_MAP: Dict[str, int] = {"base": 8453}


def _load_chain_id_map(chains_yaml: Path | None = None) -> Dict[str, int]:
    path = chains_yaml or Path("config/chains.yaml")
    try:
        import yaml  # type: ignore

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, ValueError, ImportError):
        return dict(DEFAULT_CHAIN_ID_MAP)
    out: Dict[str, int] = {}
    for key, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        cid = cfg.get("chain_id")
        if isinstance(cid, int) and cid > 0:
            out[str(key)] = int(cid)
    return out or dict(DEFAULT_CHAIN_ID_MAP)


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _artifact_age_s(doc: Dict[str, Any]) -> float | None:
    rc = doc.get("run_context")
    run_ts = ""
    if isinstance(rc, dict):
        run_ts = str(rc.get("run_timestamp") or "")
    run_ts = run_ts or str(doc.get("generated_at_utc") or "")
    parsed = _parse_ts(run_ts)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _max_artifact_age_s() -> int:
    raw = os.environ.get("ARBY_SNIPER_MAX_ARTIFACT_AGE_S", "")
    if raw.strip().isdigit():
        return int(raw.strip())
    return DEFAULT_MAX_ARTIFACT_AGE_S


def _load_cursor(repository: StateRepository, session_id: str) -> Dict[str, Any]:
    return repository.get_ingest_cursor(session_id)


def _save_cursor(repository: StateRepository, session_id: str, seen: Set[str], run_ts: str) -> None:
    repository.set_ingest_cursor(
        session_id,
        {
            "seen_event_ids": sorted(seen),
            "last_run_timestamp": run_ts,
        },
    )


def _event_id(ev: Dict[str, Any]) -> str:
    return str(ev.get("event_id") or f"{ev.get('dex')}:{ev.get('pool')}:{ev.get('block_number')}")


def poll_sniper_ingest(
    orchestrator: ContinuousOrchestrator,
    *,
    sniper_path: Path = SNIPER_ROLLING_PATH,
    repository: StateRepository | None = None,
) -> int:
    """Read sniper rolling artifact; emit pool_discovered for newly admitted pools."""
    repo = repository or orchestrator.repository
    session_id = orchestrator.session_id

    if not sniper_path.is_file():
        return 0
    try:
        doc = json.loads(sniper_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    age_s = _artifact_age_s(doc)
    if age_s is not None and age_s > float(_max_artifact_age_s()):
        return 0

    run_ts = ""
    rc = doc.get("run_context")
    if isinstance(rc, dict):
        run_ts = str(rc.get("run_timestamp") or "")
    run_ts = run_ts or str(doc.get("generated_at_utc") or "")

    cursor = _load_cursor(repo, session_id)
    seen: Set[str] = set(cursor.get("seen_event_ids") or [])
    chain_map = _load_chain_id_map()
    emitted = 0
    events = doc.get("recent_events") or []
    if not isinstance(events, list):
        return 0

    for ev in events:
        if not isinstance(ev, dict):
            continue
        eid = _event_id(ev)
        if eid in seen:
            continue
        if not bool(ev.get("filter_passed") or ev.get("candidate")):
            continue
        pool = str(ev.get("pool") or ev.get("pool_address") or "").lower()
        if not pool.startswith("0x"):
            continue
        chain_key = str(ev.get("chain") or "base")
        chain_id = int(chain_map.get(chain_key) or 8453)
        block_number = int(ev.get("block_number") or 0)
        orchestrator.emit(
            PipelineEvent(
                event_type=EVENT_POOL_DISCOVERED,
                session_id=session_id,
                payload={
                    "pool_address": pool,
                    "chain_id": chain_id,
                    "block_number": block_number,
                    "token0": ev.get("token0") or "",
                    "token1": ev.get("token1") or "",
                    "dex_id": ev.get("dex") or ev.get("dex_id") or "",
                    "pool_type": ev.get("adapter_type") or ev.get("pool_type") or "",
                    "factory": ev.get("factory") or "",
                    "factory_verified": bool(ev.get("factory_verified") or ev.get("factory")),
                    "event_id": eid,
                    "provenance": "m8_sniper",
                    "filter_passed": bool(ev.get("filter_passed")),
                    "source_run_timestamp": run_ts,
                },
                observed_block=block_number,
                entity_id=pool,
            )
        )
        seen.add(eid)
        emitted += 1

    if emitted or run_ts:
        _save_cursor(repo, session_id, seen, run_ts)
    return emitted


def handle_m8_ingest_poll(orchestrator: ContinuousOrchestrator, _payload: Dict[str, Any]) -> int:
    """Single ingest poll round (only ingest entry point per broker cycle)."""
    return poll_sniper_ingest(orchestrator)
