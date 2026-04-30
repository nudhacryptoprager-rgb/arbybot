"""Factory pool enumeration scaffold.

Reviewer post-2h-soak step #6: extend the production universe via factory
enumeration. The current onboarding loads a hand-curated subset of pools
through ``config/onboard_*.yaml``; this scaffold defines the offline,
deterministic interface a future live-RPC implementation must satisfy.

This module is intentionally **stateless and side-effect-free**:
  - no network calls,
  - no Web3 imports at module load,
  - no implicit cache writes.

A live implementation will plug into ``enumerate_factory_pools`` with a
chain-aware Web3 reader (see ``chains/providers.py``) and emit
``FactoryPoolRecord`` rows that the onboarding layer then ingests into
``data/cache/onboard/<chain>.json``. Until then this module ships:
  - the canonical record schema,
  - JSON-cache I/O helpers,
  - a deterministic enumerator stub that reads from the cache.

The scaffold is required by the post-2h-soak fix list because the 2h Base
soak produced only 1 fresh fast-path score вЂ” the universe is too narrow
for production-scale opportunities. A dedicated live-enumeration iteration
will land on top of this scaffold without touching the orderflow path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, List, Optional


__all__ = [
    "FactoryPoolRecord",
    "EnumerationCache",
    "enumerate_factory_pools",
    "populate_cache_from_pool_index",
    "default_cache_path",
]


CACHE_SCHEMA_VERSION = "factory_enum_v1"


@dataclass(frozen=True)
class FactoryPoolRecord:
    """Canonical row for a pool discovered via factory enumeration."""

    chain: str
    dex: str
    factory_address: str
    pool_address: str
    token0_address: str
    token1_address: str
    fee_tier: Optional[int] = None
    adapter_type: Optional[str] = None  # "v2" | "v3" | "algebra" | ...
    tick_spacing: Optional[int] = None
    discovered_at: Optional[str] = None  # ISO-8601 (set by live enumerator)


@dataclass
class EnumerationCache:
    """In-memory + disk-backed cache of enumerated pools per chain."""

    chain: str
    records: List[FactoryPoolRecord] = field(default_factory=list)

    def add(self, rec: FactoryPoolRecord) -> None:
        if rec.chain != self.chain:
            raise ValueError(
                f"chain mismatch: cache={self.chain} record={rec.chain}"
            )
        self.records.append(rec)

    def to_json(self) -> dict:
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "chain": self.chain,
            "record_count": len(self.records),
            "records": [asdict(r) for r in self.records],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2, sort_keys=True), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "EnumerationCache":
        if not path.is_file():
            raise FileNotFoundError(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("schema_version") != CACHE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version: {raw.get('schema_version')}"
            )
        chain = raw["chain"]
        recs = [FactoryPoolRecord(**r) for r in raw.get("records", [])]
        return cls(chain=chain, records=recs)

    def filter(
        self,
        *,
        dex: Optional[str] = None,
        adapter_type: Optional[str] = None,
        fee_tier: Optional[int] = None,
    ) -> List[FactoryPoolRecord]:
        out: Iterable[FactoryPoolRecord] = self.records
        if dex is not None:
            out = (r for r in out if r.dex == dex)
        if adapter_type is not None:
            out = (r for r in out if r.adapter_type == adapter_type)
        if fee_tier is not None:
            out = (r for r in out if r.fee_tier == fee_tier)
        return list(out)


def enumerate_factory_pools(
    *,
    chain: str,
    dex: str,
    cache_path: Optional[Path] = None,
) -> List[FactoryPoolRecord]:
    """Read enumerated pools for ``(chain, dex)`` from the offline cache.

    Live-RPC enumeration is intentionally NOT performed here. A future
    iteration will inject a Web3 reader and populate the cache. Until
    then, callers must either pre-populate the cache or accept an empty
    list. This makes the scaffold safe to import and call from anywhere
    in the codebase without RPC side effects.
    """
    if cache_path is None or not cache_path.is_file():
        return []
    cache = EnumerationCache.read(cache_path)
    if cache.chain != chain:
        return []
    return cache.filter(dex=dex)


# E1.42 Iter 4 — cold-lane collector wiring.
#
# `populate_cache_from_pool_index` bridges the existing
# `discovery.index_factories.PoolIndex` (already populated by the cold
# lane via `index_intent_pairs` / on-chain factory.getPool calls) into
# the offline enumeration cache that the rest of the system reads via
# `enumerate_factory_pools`. Calling it is side-effect-controlled: a
# single JSON write to `cache_path`. It performs NO RPC.
#
# Hot lane MUST NOT call this; it belongs to the cold lane only.

def default_cache_path(chain: str, root: Optional[Path] = None) -> Path:
    """Canonical cache location: data/cache/factory_enum/<chain>.json."""
    base = root or Path("data") / "cache" / "factory_enum"
    return base / f"{chain}.json"


def populate_cache_from_pool_index(
    *,
    chain: str,
    pool_index: object,
    cache_path: Optional[Path] = None,
    discovered_at: Optional[str] = None,
) -> int:
    """Convert a `PoolIndex` snapshot into an `EnumerationCache` JSON file.

    Returns the number of records written. Idempotent: rewriting the
    same chain replaces prior content.

    `pool_index` is duck-typed: any object with `get_pools(chain)`
    returning iterable of namedtuple-likes with attributes
    (chain, dex, address, token0, token1, fee_tier) is accepted. This
    intentionally avoids a hard import of `discovery.index_factories`
    so the cold collector can also be wired against alternative
    enumerators (subgraph, log-scan) without changing this signature.
    """
    if cache_path is None:
        cache_path = default_cache_path(chain)

    pools = []
    try:
        pools = list(pool_index.get_pools(chain))
    except Exception:
        pools = []

    base = root or Path("data") / "cache" / "factory_enum"
    return base / f"{chain}.json"


def populate_cache_from_pool_index(
    *,
    chain: str,
    pool_index: object,
    cache_path: Optional[Path] = None,
    discovered_at: Optional[str] = None,
) -> int:
    """Convert a `PoolIndex` snapshot into an `EnumerationCache` JSON file.

    Returns the number of records written. Idempotent: rewriting the
    same chain replaces prior content.

    `pool_index` is duck-typed: any object with `get_pools(chain)`
    returning iterable of namedtuple-likes with attributes
    (chain, dex, address, token0, token1, fee_tier) is accepted.
    """
    if cache_path is None:
        cache_path = default_cache_path(chain)

    pools = []
    try:
        pools = list(pool_index.get_pools(chain))
    except Exception:
        pools = []

    cache = EnumerationCache(chain=chain)
    for p in pools:
        try:
            rec = FactoryPoolRecord(
                chain=str(getattr(p, "chain", chain)),
                dex=str(getattr(p, "dex", "unknown")),
                factory_address=str(getattr(p, "factory_address", "") or ""),
                pool_address=str(getattr(p, "address", "") or ""),
                token0_address=str(getattr(p, "token0", "") or ""),
                token1_address=str(getattr(p, "token1", "") or ""),
                fee_tier=getattr(p, "fee_tier", None),
                adapter_type=getattr(p, "adapter_type", None),
                tick_spacing=getattr(p, "tick_spacing", None),
                discovered_at=discovered_at,
            )
        except Exception:
            continue
        if not rec.pool_address:
            continue
        cache.add(rec)

    cache.write(cache_path)
    return len(cache.records)
