"""Bridge sniper artifacts into StateRepository without violating state/ import boundaries."""
from __future__ import annotationsimport osfrom typing import Any, Dict, Mapping, MutableMapping, Optionalfrom core.env import env_flag_enabledfrom m8.runtime.pool_repository_sink import ingest_sniper_pool_records, load_chain_id_mapfrom state.factory import create_state_repository__all__ = ["ingest_sniper_artifact_to_repository"]


def ingest_sniper_artifact_to_repository(
    artifact: Mapping[str, Any],
    *,
    backend: Optional[str] = None,
    chain_id_map: Optional[Mapping[str, int]] = None,
    mutate_artifact: Optional[MutableMapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Ingest sniper artifact when explicitly enabled; never silent no-op."""
    if not env_flag_enabled("ARBY_STATE_REPOSITORY_ENABLED"):
        stats = {"enabled": False, "skipped": 1}
        if mutate_artifact is not None:
            mutate_artifact["state_repository_ingest"] = stats
        return stats
    resolved_backend = (
        backend or os.environ.get("ARBY_STATE_REPOSITORY_BACKEND", "")
    ).strip()
    if not resolved_backend:
        raise ValueError(
            "ARBY_STATE_REPOSITORY_BACKEND required when ARBY_STATE_REPOSITORY_ENABLED=1"
        )
    if env_flag_enabled("ARBY_STATE_REPOSITORY_PRODUCTION") and resolved_backend != "postgres":
        raise ValueError("production state repository requires postgres backend")
    repo = create_state_repository(backend=resolved_backend)
    stats = ingest_sniper_pool_records(
        artifact,
        repository=repo,
        chain_id_map=chain_id_map or load_chain_id_map(),
        run_timestamp=str(artifact.get("generated_at_utc") or ""),
    )
    stats["enabled"] = True
    stats["backend"] = resolved_backend
    if mutate_artifact is not None:
        mutate_artifact["state_repository_ingest"] = dict(stats)
    return stats
