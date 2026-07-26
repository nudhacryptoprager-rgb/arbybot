"""M8 sniper → batched streaming handoff (token subset + manifest)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

from application.checkpoint_store import fingerprint_paths
from core.json_io import atomic_write_json
from core.path_lock import path_lock
from core.pipeline_streaming import (
    DEFAULT_SNIPER_ARTIFACT,
    STREAMING_MANIFEST_PATH,
    STREAMING_ROOT_DIR,
    resolve_streaming_batch_paths,
    sanitize_session_id,
)
from m8.discovery.origin_source import collect_m8_token_addrs
from m8.discovery.token_subset import write_token_subset_file


def sniper_content_fingerprint(sniper_path: str | Path = DEFAULT_SNIPER_ARTIFACT) -> str:
    return fingerprint_paths([sniper_path])


STREAMING_FORCE_RERUN_REMEDIATION = (
    "use --new-session or omit --force-rerun-steps; "
    "to resume an existing session use --resume-session without --force-rerun-steps"
)


@dataclass(frozen=True)
class StreamingForceRerunConflict:
    """Forced sniper rerun cannot reuse a session with immutable batch manifests."""

    session_id: str
    immutable_batch_indices: tuple[int, ...]
    batch_index: int
    manifest_fingerprint: str
    current_sniper_fingerprint: str
    remediation: str = STREAMING_FORCE_RERUN_REMEDIATION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reason": "STREAMING_SESSION_REUSE_REQUIRES_NEW_SESSION",
            "session_id": self.session_id,
            "immutable_batch_indices": list(self.immutable_batch_indices),
            "batch_index": self.batch_index,
            "manifest_fingerprint": self.manifest_fingerprint,
            "current_sniper_fingerprint": self.current_sniper_fingerprint,
            "remediation": self.remediation,
        }

    def failure_reason(self) -> str:
        return (
            "STREAMING_SESSION_REUSE_REQUIRES_NEW_SESSION: "
            f"session_id={self.session_id!r} "
            f"immutable_batches={list(self.immutable_batch_indices)} "
            f"batch_index={self.batch_index} "
            f"manifest_fingerprint={self.manifest_fingerprint} "
            f"current_sniper_fingerprint={self.current_sniper_fingerprint} "
            f"remediation={self.remediation}"
        )


def find_immutable_streaming_batches(
    session_id: str,
    batch_indices: Iterable[int],
) -> List[int]:
    immutable: List[int] = []
    for raw_idx in batch_indices:
        idx = int(raw_idx)
        paths = resolve_streaming_batch_paths(idx, session_id=session_id)
        if paths.manifest.is_file():
            immutable.append(idx)
    return sorted(immutable)


def detect_streaming_force_rerun_conflict(
    session_id: str,
    batch_indices: Iterable[int],
    *,
    sniper_artifact: str | Path = DEFAULT_SNIPER_ARTIFACT,
) -> Optional[StreamingForceRerunConflict]:
    """Return conflict details when force-rerun would rewrite sniper input for a frozen session."""
    immutable = find_immutable_streaming_batches(session_id, batch_indices)
    if not immutable:
        return None
    first_batch = immutable[0]
    paths = resolve_streaming_batch_paths(first_batch, session_id=session_id)
    manifest = load_streaming_manifest(paths.manifest)
    return StreamingForceRerunConflict(
        session_id=str(session_id),
        immutable_batch_indices=tuple(immutable),
        batch_index=first_batch,
        manifest_fingerprint=str(manifest.get("sniper_input_fingerprint") or ""),
        current_sniper_fingerprint=sniper_content_fingerprint(sniper_artifact),
    )


def validate_force_rerun_streaming_session(
    session_id: str,
    batch_indices: Iterable[int],
    *,
    sniper_artifact: str | Path = DEFAULT_SNIPER_ARTIFACT,
) -> None:
    conflict = detect_streaming_force_rerun_conflict(
        session_id,
        batch_indices,
        sniper_artifact=sniper_artifact,
    )
    if conflict is not None:
        raise ValueError(conflict.failure_reason())


def _load_sniper_doc(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def extract_sniper_token_addresses(
    sniper_path: str | Path = DEFAULT_SNIPER_ARTIFACT,
) -> Set[str]:
    doc = _load_sniper_doc(sniper_path)
    return collect_m8_token_addrs(sniper=doc)


def _session_lock_path(session_id: str) -> Path:
    safe_sid = sanitize_session_id(session_id)
    return STREAMING_ROOT_DIR / safe_sid / ".session.lock"


def _read_json_dict(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _create_exclusive_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json_dict(path)
    if existing is not None:
        if existing == payload:
            return
        raise ValueError(f"IMMUTABLE_MANIFEST_COLLISION: {path}")
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(str(path), flags)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _build_subset_payload(
    addrs: list[str],
    *,
    batch_index: int,
    session_id: str,
    sniper_path: str | Path,
    sniper_fp: str,
) -> Dict[str, Any]:
    normalized = [{"token": addr.lower()} for addr in addrs if addr.lower().startswith("0x")]
    return {
        "schema_version": "m8_token_subset_v2",
        "source": "m8_streaming_sniper_batch",
        "tokens": normalized,
        "token_count": len(normalized),
        "lane_meta": {
            "batch_index": int(batch_index),
            "session_id": session_id,
            "sniper_artifact": str(sniper_path),
            "sniper_input_fingerprint": sniper_fp,
        },
    }


def _write_exclusive_subset(path: Path, payload: Dict[str, Any]) -> None:
    existing = _read_json_dict(path)
    if existing is not None:
        if existing == payload:
            return
        raise ValueError(f"IMMUTABLE_SUBSET_COLLISION: {path}")
    _create_exclusive_json(path, payload)


def write_streaming_token_subset(
    *,
    batch_index: int,
    sniper_path: str | Path = DEFAULT_SNIPER_ARTIFACT,
    session_id: str,
    output_path: Path | None = None,
) -> Path:
    paths = resolve_streaming_batch_paths(batch_index, session_id=session_id)
    out = output_path or paths.token_subset
    addrs = sorted(extract_sniper_token_addresses(sniper_path))
    sniper_fp = sniper_content_fingerprint(sniper_path)
    payload = _build_subset_payload(
        addrs,
        batch_index=batch_index,
        session_id=session_id,
        sniper_path=sniper_path,
        sniper_fp=sniper_fp,
    )
    with path_lock(_session_lock_path(session_id)):
        _write_exclusive_subset(out, payload)
    return out


def write_streaming_batch_manifest(
    *,
    session_id: str,
    batch_index: int,
    batch_minutes: int,
    sniper_artifact: str = DEFAULT_SNIPER_ARTIFACT,
    output_path: Path | None = None,
    immutable_path: Path | None = None,
    token_subset_path: Path | None = None,
) -> Dict[str, Any]:
    """Record one immutable batched-M8 manifest bundle (subset + manifest)."""
    paths = resolve_streaming_batch_paths(batch_index, session_id=session_id)
    immutable = immutable_path or paths.manifest
    if immutable.is_file():
        existing = load_streaming_manifest(immutable)
        existing_sid = str(existing.get("session_id") or "").strip()
        if existing_sid == session_id.strip():
            subset_file = str(existing.get("token_subset_file") or "").strip()
            if subset_file and Path(subset_file).is_file():
                latest = output_path or STREAMING_MANIFEST_PATH
                latest.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(latest, existing)
                return existing
    sniper_fp = sniper_content_fingerprint(sniper_artifact)
    addrs = sorted(extract_sniper_token_addresses(sniper_artifact))
    subset_path = token_subset_path or paths.token_subset
    subset_payload = _build_subset_payload(
        addrs,
        batch_index=batch_index,
        session_id=session_id,
        sniper_path=sniper_artifact,
        sniper_fp=sniper_fp,
    )
    payload: Dict[str, Any] = {
        "schema_version": "m8_streaming_batch_manifest.4",
        "pipeline_mode": "batched_m8_refresh",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
        "batch_index": int(batch_index),
        "batch_minutes": int(batch_minutes),
        "sniper_artifact": sniper_artifact,
        "sniper_input_fingerprint": sniper_fp,
        "token_subset_file": str(subset_path),
        "m81_output_file": str(paths.m81_output),
        "m82_radar_file": str(paths.m82_radar),
        "m82_hints_file": str(paths.m82_hints),
        "m82_expansion_file": str(paths.m82_expansion),
        "m83_registry_file": str(paths.m83_registry),
        "upstream_gate_output": str(paths.upstream_gate_output),
        "downstream_probe_mode": "fresh_delta",
    }
    with path_lock(_session_lock_path(session_id)):
        _write_exclusive_subset(subset_path, subset_payload)
        immutable.parent.mkdir(parents=True, exist_ok=True)
        _create_exclusive_json(immutable, payload)
    latest = output_path or STREAMING_MANIFEST_PATH
    latest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(latest, payload)
    return payload


def load_streaming_manifest(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"streaming manifest missing: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"invalid streaming manifest: {p}")
    return doc


def validate_streaming_handoff(
    manifest_path: str | Path,
    *,
    expected_session_id: Optional[str] = None,
) -> Dict[str, Any]:
    manifest = load_streaming_manifest(manifest_path)
    session_id = str(manifest.get("session_id") or "").strip()
    if expected_session_id and session_id != expected_session_id.strip():
        raise ValueError(
            f"SESSION_ID_MISMATCH: manifest={session_id!r} expected={expected_session_id!r}"
        )
    sniper_artifact = str(manifest.get("sniper_artifact") or DEFAULT_SNIPER_ARTIFACT)
    expected_fp = str(manifest.get("sniper_input_fingerprint") or "")
    current_fp = sniper_content_fingerprint(sniper_artifact)
    if expected_fp and current_fp != expected_fp:
        raise ValueError(
            f"SNIPER_FINGERPRINT_MISMATCH: manifest={expected_fp} current={current_fp}"
        )
    subset_file = str(manifest.get("token_subset_file") or "").strip()
    if not subset_file or not Path(subset_file).is_file():
        raise ValueError("TOKEN_SUBSET_FILE_MISSING")
    return manifest


def resolve_manifest_for_batch(
    batch_index: int,
    *,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    paths = resolve_streaming_batch_paths(batch_index, session_id=session_id)
    return load_streaming_manifest(paths.manifest)
