"""Artifact-bound sniper streaming checkpoint (replaces env-only skip flags)."""
from __future__ import annotationsimport hashlibimport jsonimport osfrom datetime import datetime, timezonefrom pathlib import Pathfrom typing import Any, Dict, List, Mapping, Optional, SequenceCHECKPOINT_SCHEMA_VERSION = "m8_sniper_checkpoint.2"
DEFAULT_CHECKPOINT_TTL_SECONDS = 14400
ENV_CHECKPOINT_TTL_SECONDS = "ARBY_SNIPER_CHECKPOINT_TTL_SECONDS"

__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_CHECKPOINT_TTL_SECONDS",
    "ENV_CHECKPOINT_TTL_SECONDS",
    "build_factory_config_fingerprint",
    "load_checkpoint",
    "resolve_checkpoint_ttl_seconds",
    "validate_checkpoint_for_batch",
    "write_checkpoint_artifact",
]


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_checkpoint_ttl_seconds() -> int:
    raw = os.environ.get(ENV_CHECKPOINT_TTL_SECONDS, "").strip()
    if raw:
        try:
            return max(int(raw), 60)
        except ValueError:
            pass
    return DEFAULT_CHECKPOINT_TTL_SECONDS


def build_factory_config_fingerprint(configs: Sequence[Any]) -> str:
    parts: List[str] = []
    for cfg in configs:
        parts.append(
            "|".join(
                [
                    str(getattr(cfg, "dex", "") or ""),
                    str(getattr(cfg, "factory", "") or ""),
                    str(getattr(cfg, "adapter_type", "") or ""),
                    str(getattr(cfg, "event_name", "") or ""),
                    str(getattr(cfg, "event_signature", "") or ""),
                    str(getattr(cfg, "topic0", "") or ""),
                    str(bool(getattr(cfg, "topic0_verified", False))),
                    str(bool(getattr(cfg, "discovery_only", False))),
                ]
            )
        )
    payload = "\n".join(sorted(parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _rpc_fingerprint(rpc_url: Optional[str]) -> str:
    return hashlib.sha256(str(rpc_url or "").encode("utf-8")).hexdigest()[:32]


def write_checkpoint_artifact(
    path: str,
    *,
    session_id: Optional[str],
    chain: str,
    rpc_url: Optional[str],
    factory_config_fingerprint: str,
    self_test_results: Mapping[str, Any],
    batch_index: int = 1,
    ttl_seconds: Optional[int] = None,
) -> str:
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("checkpoint requires non-empty session_id")
    if not self_test_results:
        raise ValueError("checkpoint requires completed batch-1 self_test_results")
    ttl = int(ttl_seconds if ttl_seconds is not None else resolve_checkpoint_ttl_seconds())
    doc = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "batch_index": int(batch_index),
        "session_id": sid,
        "chain": chain,
        "rpc_url_fingerprint": _rpc_fingerprint(rpc_url),
        "factory_config_fingerprint": factory_config_fingerprint,
        "self_test_passed": True,
        "self_test_results": dict(self_test_results),
        "generated_at_utc": _iso_now(),
        "ttl_seconds": ttl,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return str(out)


def load_checkpoint(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def validate_checkpoint_for_batch(
    checkpoint: Optional[Mapping[str, Any]],
    *,
    batch_index: int,
    session_id: Optional[str],
    chain: str,
    rpc_url: Optional[str],
    factory_config_fingerprint: str,
    now_utc: Optional[datetime] = None,
) -> List[str]:
    """Return blockers; empty list means checkpoint authorizes skip-self-test."""
    blockers: List[str] = []
    if checkpoint is None:
        blockers.append("SNIPER_CHECKPOINT_MISSING")
        return blockers
    if str(checkpoint.get("schema_version") or "") != CHECKPOINT_SCHEMA_VERSION:
        blockers.append("SNIPER_CHECKPOINT_SCHEMA_MISMATCH")
    if not checkpoint.get("self_test_passed"):
        blockers.append("SNIPER_CHECKPOINT_SELF_TEST_NOT_PASSED")
    if not checkpoint.get("self_test_results"):
        blockers.append("SNIPER_CHECKPOINT_SELF_TEST_RESULTS_MISSING")
    if int(checkpoint.get("batch_index") or 0) != 1:
        blockers.append("SNIPER_CHECKPOINT_INVALID_BATCH_INDEX")
    ck_sid = str(checkpoint.get("session_id") or "").strip()
    exp_sid = str(session_id or "").strip()
    if not exp_sid:
        blockers.append("SNIPER_CHECKPOINT_SESSION_EXPECTED_MISSING")
    if not ck_sid:
        blockers.append("SNIPER_CHECKPOINT_SESSION_MISSING")
    elif exp_sid and ck_sid != exp_sid:
        blockers.append("SNIPER_CHECKPOINT_SESSION_MISMATCH")
    if str(checkpoint.get("chain") or "") != str(chain):
        blockers.append("SNIPER_CHECKPOINT_CHAIN_MISMATCH")
    if str(checkpoint.get("rpc_url_fingerprint") or "") != _rpc_fingerprint(rpc_url):
        blockers.append("SNIPER_CHECKPOINT_RPC_MISMATCH")
    if str(checkpoint.get("factory_config_fingerprint") or "") != factory_config_fingerprint:
        blockers.append("SNIPER_CHECKPOINT_FACTORY_CONFIG_MISMATCH")
    ts = checkpoint.get("generated_at_utc")
    ttl = int(checkpoint.get("ttl_seconds") or resolve_checkpoint_ttl_seconds())
    if ts:
        try:
            ck_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            now = now_utc or datetime.now(tz=timezone.utc)
            age_s = (now - ck_dt).total_seconds()
            if age_s > ttl:
                blockers.append("SNIPER_CHECKPOINT_STALE")
        except ValueError:
            blockers.append("SNIPER_CHECKPOINT_TIMESTAMP_INVALID")
    else:
        blockers.append("SNIPER_CHECKPOINT_TIMESTAMP_MISSING")
    if batch_index < 2:
        blockers.append("SNIPER_CHECKPOINT_NOT_APPLICABLE_BATCH1")
    return blockers
