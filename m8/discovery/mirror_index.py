"""Read-only loaders for Curve / Balancer / Maverick rolling mirror indices (M8.2)."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

QUOTE_OK_PREFIXES = ("QUOTE_OK",)

DEFAULT_CURVE_DISCOVERY = Path("data/runs/_rolling/m9_curve_discovery_latest.json")
DEFAULT_CURVE_INDICES = Path("data/runs/_rolling/m9_curve_pool_indices_latest.json")
DEFAULT_BALANCER_INDEX = Path("data/runs/_rolling/m8_balancer_pool_index_latest.json")
DEFAULT_MAVERICK_INDEX = Path("data/runs/_rolling/m8_maverick_pool_index_latest.json")

_CURVE_DISCOVERY_SCHEMA = "m9_curve_discovery.1"
_CURVE_INDICES_SCHEMA = "m9_curve_pool_indices.1"
_BALANCER_INDEX_SCHEMA = "m8_balancer_pool_index.1"
_MAVERICK_INDEX_SCHEMA = "m8_maverick_pool_index.1"


def probe_is_quotable(probe_status: Optional[str]) -> bool:
    """Rolling discovery probe_status; None means config/trust anchor (quotable)."""
    if probe_status is None:
        return True
    status = str(probe_status).strip()
    if not status:
        return True
    return any(status.startswith(p) for p in QUOTE_OK_PREFIXES)


@dataclass
class _CurveMirrorEntry:
    pool_address: str
    pool_kind: str
    coin_indices: Dict[str, int]
    coin_addresses: Tuple[str, ...]
    probe_status: Optional[str]
    quote_smoke_status: str


@dataclass
class _BalancerMirrorEntry:
    pool_id: str
    pool_address: str
    vault_address: str
    pool_kind: str
    assets: Tuple[str, ...]
    probe_status: Optional[str]


@dataclass
class _MaverickMirrorEntry:
    pool_address: str
    token_a: str
    token_b: str
    probe_status: Optional[str]


@dataclass
class MirrorIndex:
    """In-memory mirror lookup tables for specialized DEX resolvers."""

    chain: str
    curve: List[_CurveMirrorEntry] = field(default_factory=list)
    balancer: List[_BalancerMirrorEntry] = field(default_factory=list)
    maverick: List[_MaverickMirrorEntry] = field(default_factory=list)
    sources_loaded: Dict[str, bool] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        chain: str = "base",
        *,
        curve_discovery_path: Optional[Path] = None,
        curve_indices_path: Optional[Path] = None,
        balancer_index_path: Optional[Path] = None,
        maverick_index_path: Optional[Path] = None,
    ) -> "MirrorIndex":
        idx = cls(chain=chain)
        idx._load_curve(
            curve_discovery_path or DEFAULT_CURVE_DISCOVERY,
            curve_indices_path or DEFAULT_CURVE_INDICES,
        )
        idx._load_balancer(balancer_index_path or DEFAULT_BALANCER_INDEX)
        idx._load_maverick(maverick_index_path or DEFAULT_MAVERICK_INDEX)
        return idx

    def _load_curve(self, discovery_path: Path, indices_path: Path) -> None:
        by_addr: Dict[str, _CurveMirrorEntry] = {}
        loaded_discovery = False
        loaded_indices = False

        if discovery_path.exists():
            try:
                raw = json.loads(discovery_path.read_text(encoding="utf-8"))
                if raw.get("chain") in (None, "", self.chain):
                    if raw.get("schema_version") == _CURVE_DISCOVERY_SCHEMA:
                        loaded_discovery = True
                        for pool in raw.get("discovered_pools") or []:
                            ent = _curve_entry_from_raw(pool)
                            if ent:
                                by_addr[ent.pool_address] = ent
            except Exception as exc:
                log.warning("curve discovery load failed %s: %s", discovery_path, exc)

        if indices_path.exists():
            try:
                raw = json.loads(indices_path.read_text(encoding="utf-8"))
                if raw.get("chain", self.chain) == self.chain:
                    if raw.get("schema_version") == _CURVE_INDICES_SCHEMA:
                        loaded_indices = True
                        for pool_addr, pool_data in (raw.get("pools") or {}).items():
                            if not isinstance(pool_data, dict):
                                continue
                            ent = _curve_entry_from_raw(
                                {
                                    "pool_address": pool_addr,
                                    **pool_data,
                                }
                            )
                            if ent:
                                by_addr[ent.pool_address] = ent
            except Exception as exc:
                log.warning("curve indices load failed %s: %s", indices_path, exc)

        self.curve = list(by_addr.values())
        self.sources_loaded["curve_discovery"] = loaded_discovery
        self.sources_loaded["curve_indices"] = loaded_indices

    def _load_balancer(self, path: Path) -> None:
        self.balancer = []
        if not path.exists():
            self.sources_loaded["balancer_index"] = False
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != _BALANCER_INDEX_SCHEMA:
                self.sources_loaded["balancer_index"] = False
                return
            if raw.get("chain") and raw.get("chain") != self.chain:
                self.sources_loaded["balancer_index"] = False
                return
            vault = str(raw.get("vault_address") or "").lower()
            for pool in raw.get("pools") or []:
                ent = _balancer_entry_from_raw(pool, vault_default=vault)
                if ent:
                    self.balancer.append(ent)
            self.sources_loaded["balancer_index"] = True
        except Exception as exc:
            log.warning("balancer index load failed %s: %s", path, exc)
            self.sources_loaded["balancer_index"] = False

    def _load_maverick(self, path: Path) -> None:
        self.maverick = []
        if not path.exists():
            self.sources_loaded["maverick_index"] = False
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != _MAVERICK_INDEX_SCHEMA:
                self.sources_loaded["maverick_index"] = False
                return
            if raw.get("chain") and raw.get("chain") != self.chain:
                self.sources_loaded["maverick_index"] = False
                return
            for pool in raw.get("pools") or []:
                ent = _maverick_entry_from_raw(pool)
                if ent:
                    self.maverick.append(ent)
            self.sources_loaded["maverick_index"] = True
        except Exception as exc:
            log.warning("maverick index load failed %s: %s", path, exc)
            self.sources_loaded["maverick_index"] = False

    def resolve_curve(
        self,
        exotic_symbol: str,
        anchor_symbol: str,
        *,
        exotic_address: str = "",
        anchor_address: str = "",
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        if not self.curve:
            return None, "CURVE_INDEX_EMPTY"
        want_syms = {exotic_symbol, anchor_symbol}
        want_addrs = {
            a.lower()
            for a in (exotic_address, anchor_address)
            if a and a.startswith("0x")
        }
        for ent in self.curve:
            if not probe_is_quotable(ent.probe_status):
                continue
            sym_keys = set(ent.coin_indices)
            addr_set = set(ent.coin_addresses)
            sym_match = want_syms <= sym_keys
            addr_match = bool(want_addrs) and want_addrs <= addr_set
            if not sym_match and not addr_match:
                continue
            t0s, t1s = sorted([exotic_symbol, anchor_symbol])
            t0a, t1a = exotic_address.lower(), anchor_address.lower()
            if t0s != exotic_symbol:
                t0a, t1a = t1a, t0a
            return {
                "dex_id": "curve_stable",
                "pool_address": ent.pool_address,
                "token0_symbol": t0s,
                "token1_symbol": t1s,
                "token0_addr": t0a,
                "token1_addr": t1a,
                "pool_kind": ent.pool_kind,
                "coin_indices": dict(ent.coin_indices),
                "quote_smoke": ent.quote_smoke_status,
                "quote_smoke_status": ent.quote_smoke_status,
                "resolve_source": "curve_rolling_index",
                "factory_verified": True,
            }, "OK"
        return None, "CURVE_INDEX_NO_MATCH"

    def resolve_balancer(
        self,
        exotic_symbol: str,
        anchor_symbol: str,
        *,
        exotic_address: str = "",
        anchor_address: str = "",
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        if not self.balancer:
            return None, "BALANCER_INDEX_EMPTY"
        want_addrs = {
            a.lower()
            for a in (exotic_address, anchor_address)
            if a and a.startswith("0x")
        }
        for ent in self.balancer:
            if not probe_is_quotable(ent.probe_status):
                continue
            assets = set(ent.assets)
            if want_addrs and not want_addrs <= assets:
                continue
            if not ent.pool_id or len(ent.pool_id) < 66:
                continue
            t0s, t1s = sorted([exotic_symbol, anchor_symbol])
            addrs = sorted(want_addrs) if want_addrs else []
            t0a = addrs[0] if addrs else ""
            t1a = addrs[1] if len(addrs) > 1 else ""
            if t0s != exotic_symbol and len(addrs) == 2:
                t0a, t1a = t1a, t0a
            return {
                "dex_id": "balancer_vault",
                "pool_address": ent.pool_address,
                "pool_id": ent.pool_id,
                "vault_address": ent.vault_address,
                "pool_kind": ent.pool_kind,
                "token0_symbol": t0s,
                "token1_symbol": t1s,
                "token0_addr": t0a,
                "token1_addr": t1a,
                "quote_smoke": ent.probe_status or "INDEXED",
                "quote_smoke_status": ent.probe_status or "INDEXED",
                "resolve_source": "balancer_pool_index",
                "factory_verified": True,
            }, "OK"
        return None, "BALANCER_INDEX_NO_MATCH"

    def resolve_maverick(
        self,
        exotic_symbol: str,
        anchor_symbol: str,
        *,
        exotic_address: str = "",
        anchor_address: str = "",
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        if not self.maverick:
            return None, "MAVERICK_INDEX_EMPTY"
        want_addrs = {
            a.lower()
            for a in (exotic_address, anchor_address)
            if a and a.startswith("0x")
        }
        indexed_hit = False
        for ent in self.maverick:
            pair_addrs = {ent.token_a, ent.token_b}
            if want_addrs and want_addrs != pair_addrs:
                continue
            indexed_hit = True
            if not probe_is_quotable(ent.probe_status):
                continue
            t0s, t1s = sorted([exotic_symbol, anchor_symbol])
            t0a, t1a = exotic_address.lower(), anchor_address.lower()
            if t0s != exotic_symbol:
                t0a, t1a = t1a, t0a
            return {
                "dex_id": "maverick_v2",
                "pool_address": ent.pool_address,
                "token_a": ent.token_a,
                "token0_symbol": t0s,
                "token1_symbol": t1s,
                "token0_addr": t0a,
                "token1_addr": t1a,
                "quote_smoke": ent.probe_status or "QUOTE_OK",
                "quote_smoke_status": ent.probe_status or "QUOTE_OK",
                "resolve_source": "maverick_pool_index",
                "factory_verified": True,
            }, "OK"
        if indexed_hit:
            return None, "MAVERICK_INDEXED_BUT_NOT_QUOTEABLE"
        return None, "MAVERICK_INDEX_NO_MATCH"


def _curve_entry_from_raw(pool: Dict[str, Any]) -> Optional[_CurveMirrorEntry]:
    pool_addr = str(pool.get("pool_address", "")).lower()
    coin_raw = pool.get("coin_indices") or {}
    if not pool_addr or not isinstance(coin_raw, dict) or len(coin_raw) < 2:
        return None
    try:
        coin_indices = {str(sym): int(idx) for sym, idx in coin_raw.items()}
    except (ValueError, TypeError):
        return None
    addrs_raw = pool.get("coin_addresses") or pool.get("coins") or []
    coin_addresses: Tuple[str, ...] = tuple()
    if isinstance(addrs_raw, list):
        coin_addresses = tuple(
            str(a).lower() for a in addrs_raw if isinstance(a, str) and a.startswith("0x")
        )
    probe = pool.get("probe_status")
    probe_str = str(probe) if probe is not None else None
    qss = probe_str if probe_str else "QUOTE_OK_CONFIG"
    return _CurveMirrorEntry(
        pool_address=pool_addr,
        pool_kind=str(pool.get("pool_kind", "stable")),
        coin_indices=coin_indices,
        coin_addresses=coin_addresses,
        probe_status=probe_str,
        quote_smoke_status=qss,
    )


def _balancer_entry_from_raw(
    pool: Dict[str, Any],
    *,
    vault_default: str,
) -> Optional[_BalancerMirrorEntry]:
    pool_id = str(pool.get("pool_id", "")).lower()
    assets_raw = pool.get("assets") or []
    if not pool_id or not isinstance(assets_raw, list) or len(assets_raw) < 2:
        return None
    assets = tuple(str(a).lower() for a in assets_raw if str(a).startswith("0x"))
    if len(assets) < 2:
        return None
    pool_addr = str(pool.get("pool_address") or pool_id[:42]).lower()
    vault = str(pool.get("vault_address") or vault_default).lower()
    return _BalancerMirrorEntry(
        pool_id=pool_id,
        pool_address=pool_addr,
        vault_address=vault,
        pool_kind=str(pool.get("pool_kind", "stable")),
        assets=assets,
        probe_status=str(pool.get("probe_status")) if pool.get("probe_status") else None,
    )


def _maverick_entry_from_raw(pool: Dict[str, Any]) -> Optional[_MaverickMirrorEntry]:
    pool_addr = str(pool.get("pool_address", "")).lower()
    token_a = str(pool.get("token_a", "")).lower()
    token_b = str(pool.get("token_b", "")).lower()
    if not pool_addr or not token_a or not token_b:
        return None
    probe = pool.get("probe_status")
    return _MaverickMirrorEntry(
        pool_address=pool_addr,
        token_a=token_a,
        token_b=token_b,
        probe_status=str(probe) if probe is not None else None,
    )


def per_dex_expansion_breakdown(
    *,
    pools_found_by_dex: Dict[str, int],
    reject_rows: List[Dict[str, str]],
    routes_admitted: List[Dict[str, Any]],
) -> Dict[str, Dict[str, int]]:
    """Aggregate per-dex pending / no_pool / resolved / quote_smoke for hot-path artifacts."""
    pending_by_dex: Dict[str, int] = {}
    no_pool_by_dex: Dict[str, int] = {}
    resolved_by_dex = dict(pools_found_by_dex)
    quote_smoke_by_dex: Dict[str, int] = {}

    _PENDING_REASONS = frozenset({
        "CURVE_INDEX_EMPTY",
        "CURVE_INDEX_NO_MATCH",
        "BALANCER_INDEX_EMPTY",
        "BALANCER_INDEX_NO_MATCH",
        "MAVERICK_INDEX_EMPTY",
        "MAVERICK_INDEX_NO_MATCH",
        "MAVERICK_INDEXED_BUT_NOT_QUOTEABLE",
        "ADAPTER_RESOLVE_PENDING",
        "SKIPPED_DRY_RUN",
    })
    for row in reject_rows:
        dex = str(row.get("dex_id", ""))
        reason = str(row.get("reason", ""))
        if not dex:
            continue
        if reason == "NO_POOL":
            no_pool_by_dex[dex] = no_pool_by_dex.get(dex, 0) + 1
        elif reason in _PENDING_REASONS:
            pending_by_dex[dex] = pending_by_dex.get(dex, 0) + 1

    for route in routes_admitted:
        dex = str(route.get("dex_id", ""))
        if not dex:
            continue
        qss = route.get("quote_smoke_status") or route.get("quote_smoke")
        if qss and str(qss) not in ("not_run", "skipped_registry"):
            quote_smoke_by_dex[dex] = quote_smoke_by_dex.get(dex, 0) + 1

    return {
        "pending_by_dex": dict(sorted(pending_by_dex.items())),
        "no_pool_by_dex": dict(sorted(no_pool_by_dex.items())),
        "resolved_by_dex": dict(sorted(resolved_by_dex.items())),
        "quote_smoke_by_dex": dict(sorted(quote_smoke_by_dex.items())),
    }
