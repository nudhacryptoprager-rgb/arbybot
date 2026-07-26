"""Post-depth effective execution inventory — single materialization, read-only consumers."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from core.pipeline_provenance import pipeline_session_id

log = logging.getLogger(__name__)

ENV_EFFECTIVE_INVENTORY_PATH = "ARBY_M9_EFFECTIVE_INVENTORY_PATH"
ENV_ALLOW_LIVE_MATERIALIZE = "ARBY_M9_ALLOW_LIVE_EFFECTIVE_INVENTORY_MATERIALIZE"
LEGACY_EFFECTIVE_INVENTORY_PATH = "data/tmp/m9_inventory_truth_enriched.json"
MANIFEST_SCHEMA_VERSION = "m9_effective_inventory_manifest.2"

_EXECUTION_CRITICAL_ROUTE_KEYS = (
    "route_id",
    "pool_address",
    "token0",
    "token1",
    "token0_decimals",
    "token1_decimals",
    "factory_verified",
    "effective_depth_usd",
    "adapter_family",
    "adapter_type",
    "quote_backend",
    "source",
    "mirror_of",
    "verified_mirror",
    "cross_mechanic",
    "m8_3_preflight_applied",
)

__all__ = (
    "ENV_ALLOW_LIVE_MATERIALIZE",
    "ENV_EFFECTIVE_INVENTORY_PATH",
    "LEGACY_EFFECTIVE_INVENTORY_PATH",
    "MANIFEST_SCHEMA_VERSION",
    "assert_post_depth_inventory",
    "build_execution_content_fingerprint",
    "build_route_universe_identity",
    "ensure_effective_inventory",
    "load_effective_inventory",
    "materialize_effective_inventory",
    "prepare_effective_execution_inventory",
    "resolve_effective_inventory_path",
    "sanitize_session_token",
    "validate_effective_inventory_integrity",
)


def sanitize_session_token(session_id: Optional[str]) -> str:
    sid = str(session_id or pipeline_session_id() or "unknown").strip()
    safe = re.sub(r"[^a-zA-Z0-9._-]", "_", sid)
    return (safe[:96] or "unknown").strip("_") or "unknown"


def resolve_effective_inventory_path(session_id: Optional[str] = None) -> str:
    env = os.environ.get(ENV_EFFECTIVE_INVENTORY_PATH, "").strip()
    if env:
        return env.replace("\\", "/")
    token = sanitize_session_token(session_id)
    return f"data/tmp/m9_effective_execution_inventory_{token}.json"


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_inventory_doc(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _config_fingerprint(config_path: str) -> str:
    try:
        return hashlib.sha256(Path(config_path).read_bytes()).hexdigest()[:32]
    except OSError:
        return ""


def _token_prices_content_hash(prices: Optional[Mapping[str, float]]) -> str:
    if not prices:
        return ""
    payload = json.dumps(sorted((str(k), float(v)) for k, v in prices.items()), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _canonical_route_rows(doc: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for route in sorted(
        (doc.get("active_routes") or []),
        key=lambda r: str(r.get("route_id") or ""),
    ):
        if not isinstance(route, dict):
            continue
        rows.append({key: route.get(key) for key in _EXECUTION_CRITICAL_ROUTE_KEYS})
    return rows


def _source_bridge_content_hash(doc: Mapping[str, Any]) -> str:
    canonical = {
        "depth_enrichment": dict(doc.get("depth_enrichment") or {}),
        "active_routes": _canonical_route_rows(doc),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def build_execution_content_fingerprint(doc: Mapping[str, Any]) -> str:
    routes = list(doc.get("active_routes") or [])
    canonical: List[Dict[str, Any]] = []
    for route in sorted(routes, key=lambda r: str(r.get("route_id") or "")):
        canonical.append({key: route.get(key) for key in _EXECUTION_CRITICAL_ROUTE_KEYS})
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def build_route_universe_identity_from_doc(doc: Mapping[str, Any]) -> Dict[str, str]:
    route_ids = sorted(
        str(r.get("route_id") or "").strip()
        for r in (doc.get("active_routes") or [])
        if str(r.get("route_id") or "").strip()
    )
    depth = doc.get("depth_enrichment") or {}
    route_hash = hashlib.sha256("|".join(route_ids).encode("utf-8")).hexdigest()[:16]
    return {
        "route_universe_hash": route_hash,
        "post_depth_content_hash": str(depth.get("post_depth_content_hash") or ""),
        "execution_content_fingerprint": build_execution_content_fingerprint(doc),
    }


def build_route_universe_identity(inventory_path: str) -> Dict[str, str]:
    return build_route_universe_identity_from_doc(_load_inventory_doc(inventory_path))


def build_effective_inventory_manifest(
    *,
    source_bridge_path: str,
    source_bridge_doc: Mapping[str, Any],
    effective_doc: Mapping[str, Any],
    config_path: str,
    session_id: Optional[str],
    token_prices: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    identity = build_route_universe_identity_from_doc(effective_doc)
    prices = dict(token_prices or {})
    prices_hash = _token_prices_content_hash(prices)
    if not prices:
        raise ValueError("effective inventory manifest requires frozen token prices")
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "materialized_at_utc": _iso_now(),
        "session_id": session_id,
        "source_bridge_path": str(source_bridge_path).replace("\\", "/"),
        "source_bridge_content_hash": _source_bridge_content_hash(source_bridge_doc),
        "config_fingerprint": _config_fingerprint(config_path),
        "route_universe_hash": identity["route_universe_hash"],
        "post_depth_content_hash": identity["post_depth_content_hash"],
        "execution_content_fingerprint": identity["execution_content_fingerprint"],
        "prices_frozen": True,
        "token_prices_content_hash": prices_hash,
        "price_snapshot_id": prices_hash,
        "price_snapshot_source": "materialize_effective_inventory",
        "immutable": True,
    }


def assert_post_depth_inventory(doc: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    if not doc:
        return False, ["inventory_missing"]
    depth = doc.get("depth_enrichment") or {}
    blockers: List[str] = []
    if not str(depth.get("post_depth_content_hash") or "").strip():
        blockers.append("PRE_DEPTH_INVENTORY")
    if not str(depth.get("depth_enrichment_session_id") or "").strip():
        blockers.append("DEPTH_ENRICHMENT_SESSION_ID_MISSING")
    return len(blockers) == 0, blockers


def validate_effective_inventory_integrity(
    doc: Mapping[str, Any],
    *,
    expected_session_id: Optional[str] = None,
    source_bridge_doc: Optional[Mapping[str, Any]] = None,
    config_path: Optional[str] = None,
) -> List[str]:
    """Fail-close integrity checks for a materialized effective inventory document."""
    blockers: List[str] = []
    manifest = doc.get("effective_inventory_manifest") or {}
    if str(manifest.get("schema_version") or "") != MANIFEST_SCHEMA_VERSION:
        blockers.append("EFFECTIVE_INVENTORY_MANIFEST_SCHEMA_MISMATCH")
    if not manifest.get("immutable"):
        blockers.append("EFFECTIVE_INVENTORY_NOT_IMMUTABLE")
    exp_sid = str(expected_session_id or pipeline_session_id() or "").strip()
    man_sid = str(manifest.get("session_id") or "").strip()
    if exp_sid and not man_sid:
        blockers.append("EFFECTIVE_INVENTORY_SESSION_MISSING")
    elif exp_sid and man_sid and exp_sid != man_sid:
        blockers.append("EFFECTIVE_INVENTORY_SESSION_MISMATCH")
    recomputed_fp = build_execution_content_fingerprint(doc)
    if str(manifest.get("execution_content_fingerprint") or "") != recomputed_fp:
        blockers.append("EFFECTIVE_INVENTORY_EXECUTION_FINGERPRINT_MISMATCH")
    frozen = doc.get("frozen_token_prices") or {}
    if not isinstance(frozen, dict) or not frozen:
        blockers.append("EFFECTIVE_INVENTORY_FROZEN_PRICES_MISSING")
    elif str(manifest.get("token_prices_content_hash") or "") != _token_prices_content_hash(frozen):
        blockers.append("EFFECTIVE_INVENTORY_FROZEN_PRICES_HASH_MISMATCH")
    if config_path:
        if str(manifest.get("config_fingerprint") or "") != _config_fingerprint(config_path):
            blockers.append("EFFECTIVE_INVENTORY_CONFIG_FINGERPRINT_MISMATCH")
    if source_bridge_doc is not None:
        expected_bridge_hash = _source_bridge_content_hash(source_bridge_doc)
        if str(manifest.get("source_bridge_content_hash") or "") != expected_bridge_hash:
            blockers.append("EFFECTIVE_INVENTORY_SOURCE_BRIDGE_HASH_MISMATCH")
    return blockers


@contextmanager
def _materialize_lock(effective_path: str, session_id: Optional[str]) -> Iterator[None]:
    lock_path = Path(f"{effective_path}.materialize.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd: Optional[int] = None
    acquired = False
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        acquired = True
        os.write(fd, str(session_id or "unknown").encode("utf-8"))
        yield
    except FileExistsError as exc:
        raise RuntimeError(
            f"effective inventory materialization already in progress: {lock_path}"
        ) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if acquired:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass


def _atomic_write_json(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _manifest_matches_bridge(
    manifest: Mapping[str, Any],
    *,
    source_bridge_path: str,
    source_bridge_doc: Mapping[str, Any],
    config_path: str,
    session_id: Optional[str],
) -> bool:
    if str(manifest.get("schema_version") or "") != MANIFEST_SCHEMA_VERSION:
        return False
    if not manifest.get("immutable"):
        return False
    if str(manifest.get("source_bridge_content_hash") or "") != _source_bridge_content_hash(
        source_bridge_doc
    ):
        return False
    if str(manifest.get("source_bridge_path") or "").replace("\\", "/") != str(
        source_bridge_path
    ).replace("\\", "/"):
        return False
    if str(manifest.get("config_fingerprint") or "") != _config_fingerprint(config_path):
        return False
    exp_sid = str(session_id or "").strip()
    man_sid = str(manifest.get("session_id") or "").strip()
    if exp_sid and man_sid and exp_sid != man_sid:
        return False
    return True


def _validate_loaded_inventory(
    effective_path: str,
    *,
    source_bridge_path: Optional[str],
    source_bridge_doc: Optional[Mapping[str, Any]],
    config_path: Optional[str],
    session_id: Optional[str],
) -> None:
    doc = _load_inventory_doc(effective_path)
    blockers = validate_effective_inventory_integrity(
        doc,
        expected_session_id=session_id,
        source_bridge_doc=source_bridge_doc,
        config_path=config_path,
    )
    if blockers:
        raise ValueError(
            f"effective inventory integrity failed ({','.join(blockers)}): {effective_path}"
        )


def _live_materialize_allowed() -> bool:
    return os.environ.get(ENV_ALLOW_LIVE_MATERIALIZE, "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def materialize_effective_inventory(
    inventory_path: str,
    config_path: str,
    *,
    chain: Optional[str] = None,
    output_path: Optional[str] = None,
    session_id: Optional[str] = None,
    require_post_depth: bool = True,
    force: bool = False,
    w3: Any = None,
    token_prices: Optional[Dict[str, float]] = None,
) -> str:
    if not _live_materialize_allowed():
        raise ValueError(
            f"live effective inventory materialization disabled; "
            f"set {ENV_ALLOW_LIVE_MATERIALIZE}=1 on the writer stage"
        )
    inv_p = Path(inventory_path)
    if not inv_p.is_file():
        raise FileNotFoundError(f"inventory not found: {inventory_path}")

    with inv_p.open(encoding="utf-8") as fh:
        bridge_doc = json.load(fh)

    if require_post_depth:
        ok, blockers = assert_post_depth_inventory(bridge_doc)
        if not ok:
            raise ValueError(
                f"effective inventory requires post-depth bridge ({','.join(blockers)})"
            )

    resolved_out = output_path or resolve_effective_inventory_path(session_id)
    out_path = Path(resolved_out)
    if not force and out_path.is_file():
        try:
            _validate_loaded_inventory(
                resolved_out,
                source_bridge_path=inventory_path,
                source_bridge_doc=bridge_doc,
                config_path=config_path,
                session_id=session_id,
            )
            log.info("Reusing materialized effective inventory: %s", resolved_out)
            return resolved_out
        except ValueError:
            if not force:
                raise

    from m9.graph_arb.inventory_truth import enrich_inventory_for_quote_truth

    resolved_w3 = w3
    resolved_prices = token_prices
    if resolved_w3 is None and chain:
        try:
            from web3 import Web3

            from core.rpc_urls import get_rpc_url

            url = get_rpc_url(chain)
            if url:
                resolved_w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))
        except Exception as exc:
            log.debug("effective inventory: rpc connect skipped: %s", exc)

    if resolved_prices is None:
        from m9.graph_arb.token_price_fetcher import (
            build_dual_key_price_map,
            extend_price_map_from_inventory,
            fetch_token_prices_usd,
        )

        price_result = fetch_token_prices_usd(timeout_s=3.0)
        resolved_prices = extend_price_map_from_inventory(
            str(inv_p),
            config_path,
            price_result.prices_by_address
            or build_dual_key_price_map(price_result.prices),
        )

    if not resolved_prices:
        raise ValueError("effective inventory materialization requires frozen token prices")

    enrich_tmp = out_path.with_suffix(out_path.suffix + ".enrich.tmp")
    with _materialize_lock(resolved_out, session_id):
        enrich_out = enrich_inventory_for_quote_truth(
            str(inv_p),
            config_path,
            w3=resolved_w3,
            token_prices=resolved_prices,
            output_path=str(enrich_tmp),
        )
        out_doc = _load_inventory_doc(enrich_out)
        manifest = build_effective_inventory_manifest(
            source_bridge_path=inventory_path,
            source_bridge_doc=bridge_doc,
            effective_doc=out_doc,
            config_path=config_path,
            session_id=session_id or pipeline_session_id(),
            token_prices=resolved_prices,
        )
        out_doc["effective_inventory_manifest"] = manifest
        out_doc["frozen_token_prices"] = dict(resolved_prices)
        out_doc["price_snapshot_policy"] = {
            "policy": "frozen_single_writer",
            "price_snapshot_id": manifest["price_snapshot_id"],
            "price_snapshot_source": manifest["price_snapshot_source"],
            "materialized_at_utc": manifest["materialized_at_utc"],
        }
        _atomic_write_json(out_path, out_doc)
        try:
            enrich_tmp.unlink(missing_ok=True)
        except OSError:
            pass
    log.info("Materialized effective execution inventory: %s -> %s", inventory_path, resolved_out)
    return str(out_path)


def load_effective_inventory(
    *,
    session_id: Optional[str] = None,
    effective_path: Optional[str] = None,
    source_bridge_path: Optional[str] = None,
    config_path: Optional[str] = None,
) -> str:
    path = str(effective_path or resolve_effective_inventory_path(session_id)).strip()
    if not Path(path).is_file():
        raise FileNotFoundError(
            f"effective inventory not materialized at {path}; "
            "run scripts/m9_prepare_effective_inventory.py pipeline stage"
        )
    bridge_doc = _load_inventory_doc(source_bridge_path) if source_bridge_path else None
    _validate_loaded_inventory(
        path,
        source_bridge_path=source_bridge_path,
        source_bridge_doc=bridge_doc,
        config_path=config_path,
        session_id=session_id,
    )
    return path


def ensure_effective_inventory(
    inventory_path: str,
    config_path: str,
    *,
    session_id: Optional[str] = None,
    effective_path: Optional[str] = None,
    require_post_depth: bool = True,
) -> str:
    """Read-only ensure — never materializes (writer stage must call materialize_*)."""
    del require_post_depth
    return load_effective_inventory(
        session_id=session_id,
        effective_path=effective_path or resolve_effective_inventory_path(session_id),
        source_bridge_path=inventory_path,
        config_path=config_path,
    )


def load_frozen_token_prices(effective_inventory_path: str) -> Optional[Dict[str, float]]:
    doc = _load_inventory_doc(effective_inventory_path)
    manifest = doc.get("effective_inventory_manifest") or {}
    if not manifest.get("prices_frozen"):
        return None
    prices = doc.get("frozen_token_prices")
    return dict(prices) if isinstance(prices, dict) else None


def prepare_effective_execution_inventory(
    inventory_path: str,
    config_path: str,
    **kwargs: Any,
) -> str:
    """Backward-compatible alias for materialize (pipeline writer stage only)."""
    return materialize_effective_inventory(inventory_path, config_path, **kwargs)
