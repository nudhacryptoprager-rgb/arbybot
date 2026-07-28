"""Production adapters for continuous pipeline workers — scripts layer (may import m8/m9)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.continuous_pipeline import (
    EVENT_M9_QUOTE_RESULT,
    EVENT_METADATA_READY,
    EVENT_MIRROR_READY,
    EVENT_POOL_DISCOVERED,
    EVENT_QUOTE_READY,
    WORKER_M9_GRAPH_QUOTE,
    WORKER_M81_PROBE,
    WORKER_M82_MIRROR,
    WORKER_M83_METADATA,
    WorkerResult,
)
from monitoring.sniper_honeypot import HoneypotVerdict, check_token_honeypot
from state.repository import IdempotencyKey, PoolRecord, RouteRecord, StateRepository

EXPANSION_ROLLING = Path("data/runs/_rolling/m8_cross_dex_expansion_latest.json")
METADATA_ROLLING = Path("data/runs/_rolling/m8_3_token_metadata_registry_latest.json")


def _idem(payload: Dict[str, Any], revision: str) -> IdempotencyKey:
    return IdempotencyKey(
        chain_id=int(payload.get("chain_id") or 8453),
        block_number=int(payload.get("block_number") or 0),
        entity_id=str(payload.get("pool_address") or payload.get("entity_id") or ""),
        input_revision=revision,
    )


def rpc_skipped() -> bool:
    return os.environ.get("ARBY_SKIP_RPC") == "1"


def _resolve_rpc(chain: str = "base") -> Tuple[Optional[str], str]:
    if rpc_skipped():
        return None, "ARBY_SKIP_RPC"
    try:
        from scripts.m9_quote_route_diagnostic import resolve_diagnostic_rpc

        url, provider, _diag = resolve_diagnostic_rpc(chain)
        return url, provider
    except Exception as exc:
        return None, str(exc)[:120]


def _honeypot_pass(token: str, chain: str = "base") -> Tuple[bool, str]:
    verdict = check_token_honeypot(token, chain)
    if verdict == HoneypotVerdict.FAIL:
        return False, "HONEYPOT_FAIL"
    return True, str(verdict.value)


def _load_expansion_routes_for_pair(token0: str, token1: str) -> List[Dict[str, Any]]:
    if not EXPANSION_ROLLING.is_file():
        return []
    try:
        doc = json.loads(EXPANSION_ROLLING.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    t0, t1 = token0.lower(), token1.lower()
    out: List[Dict[str, Any]] = []
    for route in doc.get("routes_admitted") or []:
        if not isinstance(route, dict):
            continue
        a = str(route.get("token_a") or route.get("token0") or "").lower()
        b = str(route.get("token_b") or route.get("token1") or "").lower()
        if {a, b} == {t0, t1} and route.get("pool_address"):
            out.append(route)
    return out


def _token_decimals_from_registry(address: str) -> Optional[int]:
    if not METADATA_ROLLING.is_file():
        return None
    try:
        doc = json.loads(METADATA_ROLLING.read_text(encoding="utf-8"))
        tokens = doc.get("tokens") or {}
        meta = tokens.get(address.lower()) or tokens.get(address)
        if isinstance(meta, dict) and meta.get("decimals") is not None:
            return int(meta["decimals"])
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _is_quarantined(pool_address: str) -> bool:
    try:
        from m9.graph_arb.pool_depth_filter import load_quarantined_pool_addresses

        quarantined = load_quarantined_pool_addresses()
        return pool_address.lower() in {p.lower() for p in quarantined}
    except Exception:
        return False


def adapter_m81_probe(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    if not pool_address:
        return WorkerResult(worker=WORKER_M81_PROBE, ok=False, error="missing pool_address")
    if payload.get("provenance") == "m8_sniper" and not payload.get("filter_passed"):
        return WorkerResult(worker=WORKER_M81_PROBE, ok=False, error="SNIPER_NOT_ADMITTED")

    token0 = str(payload.get("token0") or "")
    token1 = str(payload.get("token1") or "")
    for tok in (token0, token1):
        if tok.startswith("0x"):
            ok, reason = _honeypot_pass(tok)
            if not ok:
                return WorkerResult(worker=WORKER_M81_PROBE, ok=False, error=reason)

    rpc_url, rpc_diag = _resolve_rpc()
    probe_status = "anti_toxic_pass"
    if not rpc_url and not rpc_skipped():
        return WorkerResult(worker=WORKER_M81_PROBE, ok=False, error=f"RPC_UNAVAILABLE:{rpc_diag}")

    with repository.transaction():
        repository.upsert_pool(
            PoolRecord(
                chain_id=int(payload.get("chain_id") or 8453),
                dex_id=str(payload.get("dex_id") or "unknown"),
                pool_address=pool_address,
                token0=token0,
                token1=token1,
                pool_type=str(payload.get("pool_type") or "unknown"),
                fee=None,
                status=probe_status,
                idempotency=_idem(payload, f"m81:{session_id}"),
                extra={"stage": "m81_probe", "rpc_url": bool(rpc_url)},
            )
        )
        repository.append_event(
            event_type=EVENT_POOL_DISCOVERED,
            session_id=session_id,
            entity_id=pool_address,
            payload={**dict(payload), "m81_status": probe_status},
            observed_block=int(payload.get("block_number") or 0),
        )
    return WorkerResult(worker=WORKER_M81_PROBE, ok=True, next_event=EVENT_MIRROR_READY)


def _resolve_mirror_route(
    pool_address: str,
    token0: str,
    token1: str,
    payload: Dict[str, Any],
) -> tuple[Optional[Dict[str, Any]], str]:
    """Return (mirror_route, error). Mirror pool must differ from origin pool."""
    origin = pool_address.lower()
    for route in _load_expansion_routes_for_pair(token0, token1):
        mirror_pool = str(route.get("pool_address") or "").lower()
        if not mirror_pool or mirror_pool == origin:
            continue
        if not bool(route.get("factory_verified")):
            continue
        return route, ""
    if rpc_skipped():
        return None, "MIRROR_ROUTE_UNRESOLVED"
    try:
        from m8.discovery.dexscreener_hints import fetch_token_hints_batch

        hints = fetch_token_hints_batch([token0, token1], chain="base", max_recall=True)
        for hint_list in hints.values():
            for h in hint_list:
                mirror_pool = str(getattr(h, "pool_address", "") or "").lower()
                if not mirror_pool or mirror_pool == origin:
                    continue
                dex_id = str(getattr(h, "dex_id", "") or getattr(h, "dex", "") or "")
                return (
                    {
                        "route_id": f"mirror:{mirror_pool}",
                        "pool_address": mirror_pool,
                        "dex_id": dex_id,
                        "token_in": token0,
                        "token_out": token1,
                        "factory_verified": True,
                        "mirror_evidence": "dexscreener_hint",
                    },
                    "",
                )
    except Exception as exc:
        return None, f"M82_RECALL_ERROR:{exc}"[:120]
    return None, "MIRROR_ROUTE_UNRESOLVED"


def adapter_m82_mirror(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    token0 = str(payload.get("token0") or "")
    token1 = str(payload.get("token1") or "")
    if not pool_address or not token0.startswith("0x") or not token1.startswith("0x"):
        return WorkerResult(worker=WORKER_M82_MIRROR, ok=False, error="missing_pair")

    chosen, err = _resolve_mirror_route(pool_address, token0, token1, payload)
    if chosen is None:
        return WorkerResult(worker=WORKER_M82_MIRROR, ok=False, error=err or "MIRROR_ROUTE_UNRESOLVED")

    mirror_pool = str(chosen.get("pool_address") or "").lower()
    if mirror_pool == pool_address.lower():
        return WorkerResult(worker=WORKER_M82_MIRROR, ok=False, error="MIRROR_ROUTE_UNRESOLVED")

    route_id = str(chosen.get("route_id") or f"mirror:{mirror_pool}")

    if not rpc_skipped():
        try:
            from m8.discovery.cross_dex_expand import load_yaml_config
            from m8.discovery.mirror_quote_smoke import smoke_mirror_same_pair_routes

            cfg = load_yaml_config(Path("config/exotic_base_anchor.yaml"))
            smoke = smoke_mirror_same_pair_routes(
                [chosen],
                chain="base",
                config=cfg,
                dry_run=False,
                quote_workers=1,
            )
            if int(smoke.get("quote_ok") or 0) < 1:
                return WorkerResult(
                    worker=WORKER_M82_MIRROR,
                    ok=False,
                    error=str(smoke.get("reason") or "MIRROR_QUOTE_SMOKE_FAIL"),
                )
        except Exception as exc:
            return WorkerResult(worker=WORKER_M82_MIRROR, ok=False, error=f"M82_SMOKE_ERROR:{exc}"[:120])

    with repository.transaction():
        repository.upsert_route(
            RouteRecord(
                chain_id=int(payload.get("chain_id") or 8453),
                route_id=route_id,
                dex_id=str(chosen.get("dex_id") or payload.get("dex_id") or "mirror"),
                token_in=str(chosen.get("token_in") or token0),
                token_out=str(chosen.get("token_out") or token1),
                pool_address=mirror_pool,
                status="mirror_verified",
                idempotency=_idem(payload, f"m82:{session_id}"),
                extra={
                    "handoff_lane": "mirror_2leg",
                    "mirror_evidence": chosen.get("mirror_evidence", "expansion"),
                    "origin_pool_address": pool_address,
                    "mirror_pool_address": mirror_pool,
                },
            )
        )
        repository.append_event(
            event_type=EVENT_MIRROR_READY,
            session_id=session_id,
            entity_id=pool_address,
            payload={**dict(payload), "mirror_route_id": route_id, "mirror_pool_address": mirror_pool},
            observed_block=int(payload.get("block_number") or 0),
        )
    return WorkerResult(worker=WORKER_M82_MIRROR, ok=True, next_event=EVENT_METADATA_READY)


def adapter_m83_metadata(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    if _is_quarantined(pool_address):
        return WorkerResult(worker=WORKER_M83_METADATA, ok=False, error="POOL_QUARANTINED")

    token0 = str(payload.get("token0") or "")
    token1 = str(payload.get("token1") or "")
    if not token0.startswith("0x"):
        return WorkerResult(worker=WORKER_M83_METADATA, ok=False, error="missing_token0")

    dec0 = _token_decimals_from_registry(token0)
    dec1 = _token_decimals_from_registry(token1) if token1.startswith("0x") else None
    if dec0 is None or (token1.startswith("0x") and dec1 is None):
        return WorkerResult(worker=WORKER_M83_METADATA, ok=False, error="DECIMALS_UNKNOWN")

    factory_verified = bool(payload.get("factory_verified"))
    if payload.get("provenance") == "m8_sniper" and not factory_verified:
        return WorkerResult(worker=WORKER_M83_METADATA, ok=False, error="FACTORY_UNVERIFIED")

    with repository.transaction():
        repository.upsert_token(
            chain_id=int(payload.get("chain_id") or 8453),
            address=token0,
            decimals=dec0,
            symbol=str(payload.get("symbol") or "UNK"),
            idempotency=_idem(payload, f"m83:{session_id}"),
        )
        if token1.startswith("0x") and dec1 is not None:
            repository.upsert_token(
                chain_id=int(payload.get("chain_id") or 8453),
                address=token1,
                decimals=dec1,
                symbol=str(payload.get("symbol1") or "UNK"),
                idempotency=_idem(payload, f"m83b:{session_id}"),
            )
        repository.append_event(
            event_type=EVENT_METADATA_READY,
            session_id=session_id,
            entity_id=pool_address,
            payload={
                **dict(payload),
                "decimals0": dec0,
                "decimals1": dec1,
                "factory_verified": factory_verified,
            },
            observed_block=int(payload.get("block_number") or 0),
        )
    return WorkerResult(worker=WORKER_M83_METADATA, ok=True, next_event=EVENT_QUOTE_READY)


def adapter_m9_graph_quote(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    if _is_quarantined(pool_address):
        return WorkerResult(worker=WORKER_M9_GRAPH_QUOTE, ok=False, error="POOL_QUARANTINED")

    rpc_url, rpc_diag = _resolve_rpc()
    if not rpc_url:
        return WorkerResult(worker=WORKER_M9_GRAPH_QUOTE, ok=False, error=f"RPC_UNAVAILABLE:{rpc_diag}")

    token0 = str(payload.get("token0") or "")
    token1 = str(payload.get("token1") or "")
    dec0 = payload.get("decimals0")
    dec1 = payload.get("decimals1")
    if dec0 is None or dec1 is None:
        return WorkerResult(worker=WORKER_M9_GRAPH_QUOTE, ok=False, error="DECIMALS_UNKNOWN")
    dec0 = int(dec0)
    dec1 = int(dec1)

    quote_pool = str(payload.get("mirror_pool_address") or pool_address)

    try:
        from m8_1.stable_anchor.quote_probe import size_usd_to_amount_in
        from m9.graph_arb.models import GraphEdge
        from m9.graph_arb.quoter import _make_dex_route, _make_token_info
        from m9.graph_arb.raw_http_probe import probe_quote_raw_http

        edge = GraphEdge(
            token_in_sym="T0",
            token_out_sym="T1",
            token_in_addr=token0,
            token_out_addr=token1,
            token_in_decimals=dec0,
            token_out_decimals=dec1,
            route_id=str(payload.get("mirror_route_id") or f"cont:{quote_pool.lower()}"),
            dex_id=str(payload.get("dex_id") or "unknown"),
            adapter_type=str(payload.get("pool_type") or payload.get("dex_id") or "v2"),
            fee=int(payload.get("fee") or 0),
            tick_spacing=None,
            quoter_addr="",
            pool_address=quote_pool,
            fee_bps=float(payload.get("fee_bps") or 30),
            factory_class=str(payload.get("factory") or ""),
            pair_id=f"{token0[:6]}_{token1[:6]}",
            factory_verified=bool(payload.get("factory_verified")),
        )
        route = _make_dex_route(edge)
        tin = _make_token_info("T0", token0, dec0)
        tout = _make_token_info("T1", token1, dec1)
        amount_in = size_usd_to_amount_in(tin, 100.0)
        result = probe_quote_raw_http(rpc_url, route, tin, tout, amount_in)
        quote_payload = {
            **dict(payload),
            "quote_mode": "raw_route_diagnostic",
            "rpc_dispatched": True,
            "ok": result.ok,
            "reject_reason": result.reject_reason,
            "raw_error": (result.raw_error or "")[:200] or None,
            "amount_out": result.amount_out if result.ok else 0,
        }
        with repository.transaction():
            repository.append_event(
                event_type=EVENT_M9_QUOTE_RESULT,
                session_id=session_id,
                entity_id=pool_address,
                payload=quote_payload,
                observed_block=int(payload.get("block_number") or 0),
            )
        if not result.ok:
            return WorkerResult(
                worker=WORKER_M9_GRAPH_QUOTE,
                ok=False,
                error=str(result.reject_reason or "M9_QUOTE_FAIL"),
            )
        return WorkerResult(worker=WORKER_M9_GRAPH_QUOTE, ok=True, next_event=None)
    except Exception as exc:
        return WorkerResult(worker=WORKER_M9_GRAPH_QUOTE, ok=False, error=f"M9_QUOTE_ERROR:{exc}"[:120])


PRODUCTION_HANDLERS = {
    WORKER_M81_PROBE: adapter_m81_probe,
    WORKER_M82_MIRROR: adapter_m82_mirror,
    WORKER_M83_METADATA: adapter_m83_metadata,
    WORKER_M9_GRAPH_QUOTE: adapter_m9_graph_quote,
}
