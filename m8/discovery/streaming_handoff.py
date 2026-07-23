"""M8 sniper → streaming batch handoff (token subset + manifest)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from application.checkpoint_store import fingerprint_paths
from core.pipeline_streaming import (
    DEFAULT_SNIPER_ARTIFACT,
    STREAMING_MANIFEST_PATH,
    streaming_batch_manifest_path,
    streaming_token_subset_path,
)
from m8.discovery.origin_source import collect_m8_token_addrs
from m8.discovery.token_subset import write_token_subset_file


def sniper_content_fingerprint(sniper_path: str | Path = DEFAULT_SNIPER_ARTIFACT) -> str:
    return fingerprint_paths([sniper_path])


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


def write_streaming_token_subset(
    *,
    batch_index: int,
    sniper_path: str | Path = DEFAULT_SNIPER_ARTIFACT,
    session_id: str,
    output_path: Path | None = None,
) -> Path:
    addrs = sorted(extract_sniper_token_addresses(sniper_path))
    out = output_path or streaming_token_subset_path(batch_index)
    sniper_fp = sniper_content_fingerprint(sniper_path)
    write_token_subset_file(
        addrs,
        out,
        source="m8_streaming_sniper_batch",
        lane_meta={
            "batch_index": int(batch_index),
            "session_id": session_id,
            "sniper_artifact": str(sniper_path),
            "sniper_input_fingerprint": sniper_fp,
        },
    )
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
    """Record one immutable streaming batch manifest for downstream consumers."""
    sniper_fp = sniper_content_fingerprint(sniper_artifact)
    subset_path = write_streaming_token_subset(
        batch_index=batch_index,
        sniper_path=sniper_artifact,
        session_id=session_id,
        output_path=token_subset_path,
    )
    payload: Dict[str, Any] = {
        "schema_version": "m8_streaming_batch_manifest.2",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
        "batch_index": int(batch_index),
        "batch_minutes": int(batch_minutes),
        "sniper_artifact": sniper_artifact,
        "sniper_input_fingerprint": sniper_fp,
        "token_subset_file": str(subset_path),
        "downstream_probe_mode": "fresh_delta",
    }
    immutable = immutable_path or streaming_batch_manifest_path(batch_index)
    immutable.parent.mkdir(parents=True, exist_ok=True)
    immutable.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    latest = output_path or STREAMING_MANIFEST_PATH
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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
    """Refuse M8.1 fresh_delta when session or sniper fingerprint drifted."""
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
