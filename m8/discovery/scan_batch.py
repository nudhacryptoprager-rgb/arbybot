"""M8.2 batch factory resolver, negative cache, async RPC, expansion progress."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_log = logging.getLogger(__name__)

SCAN_MODES = frozenset({"audit_full", "hot_path_incremental", "candidate_summary"})

_ZERO_ADDR = "0x" + "0" * 40

_V2_FACTORY_ABI = [
    {
        "constant": True,
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "", "type": "address"},
        ],
        "name": "getPair",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]

_V3_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "address", "name": "", "type": "address"},
            {"internalType": "uint24", "name": "", "type": "uint24"},
        ],
        "name": "getPool",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]


@dataclass
class NegativeResultCache:
    """TTL cache for (token, dex, anchor, fee_tag) -> reason."""

    ttl_s: float = 3600.0
    _entries: Dict[str, Tuple[str, float]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def _key(
        self,
        token: str,
        dex_id: str,
        anchor: str,
        fee_tag: str = "",
    ) -> str:
        return f"{token.lower()}|{dex_id}|{anchor}|{fee_tag}"

    def get(self, token: str, dex_id: str, anchor: str, fee_tag: str = "") -> Optional[str]:
        key = self._key(token, dex_id, anchor, fee_tag)
        row = self._entries.get(key)
        if not row:
            self.misses += 1
            return None
        reason, ts = row
        if time.monotonic() - ts > self.ttl_s:
            del self._entries[key]
            self.misses += 1
            return None
        self.hits += 1
        return reason

    def put(
        self,
        token: str,
        dex_id: str,
        anchor: str,
        reason: str,
        *,
        fee_tag: str = "",
    ) -> None:
        self._entries[self._key(token, dex_id, anchor, fee_tag)] = (
            reason,
            time.monotonic(),
        )

    def stats(self) -> Dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._entries)}


class ExpandProgress:
    """Write expansion phase progress for long-running foreground runs."""

    def __init__(self, path: str | Path = "data/tmp/m8_cross_dex_expand_progress.json"):
        self.path = Path(path)
        self.data: Dict[str, Any] = {
            "schema_version": "m8_cross_dex_expand_progress.1",
            "started_at_utc": _iso_now(),
            "phase": "init",
            "tokens_done": 0,
            "tokens_total": 0,
            "rpc_calls": 0,
            "rpc_429": 0,
            "candidate_progress": {},
            "phase_timings_s": {},
            "scan_mode": "",
        }
        self._phase_t0 = time.monotonic()

    def set_phase(self, phase: str) -> None:
        elapsed = round(time.monotonic() - self._phase_t0, 3)
        if self.data.get("phase"):
            timings = self.data.setdefault("phase_timings_s", {})
            timings[self.data["phase"]] = elapsed
        self.data["phase"] = phase
        self._phase_t0 = time.monotonic()
        self.flush()

    def tick(
        self,
        *,
        tokens_done: int,
        tokens_total: int,
        rpc_stats: Optional[Dict[str, int]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.data["tokens_done"] = tokens_done
        self.data["tokens_total"] = tokens_total
        if rpc_stats:
            self.data["rpc_calls"] = int(rpc_stats.get("rpc_calls", 0))
            self.data["rpc_429"] = int(rpc_stats.get("multicall_429", 0))
        if extra:
            self.data.update(extra)
        self.flush()

    def flush(self) -> None:
        self.data["updated_at_utc"] = _iso_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AsyncRpcBatchClient:
    """Bounded async JSON-RPC batch client (httpx) with 429 backoff.

    Optional ``quota_limiter`` adds per-provider quota throttling
    (``chains.provider_quota.AsyncProviderQuotaLimiter``); ``provider_ids``
    labels each RPC URL so the limiter can apply the right budget.  When no
    limiter is provided the client behaves exactly as before (global
    semaphore only).

    HTTP client reuse (Step 6 fix): the client now keeps one shared
    ``httpx.AsyncClient`` instead of creating a new one per attempt. The
    client is lazily created on first ``batch_call`` and closed via the
    async ``close()`` context. A single client covering a long-lived
    resolver keeps connection pooling warm and removes the per-attempt
    ``httpx.AsyncClient.__init__`` overhead that previously ran inside the
    hot batch loop.

    The ``from_config`` classmethod loads the quota limiter from the
    canonical ``config/provider_quotas.yaml`` (with ``ARBY_QUOTA_<PID>``
    env overrides), wiring *real provider configuration* into the
    production resolver path (review issue 6).
    """

    def __init__(
        self,
        rpc_urls: List[str],
        *,
        max_concurrency: int = 4,
        timeout_s: float = 12.0,
        quota_limiter: Optional[Any] = None,
        provider_ids: Optional[List[str]] = None,
    ):
        self.rpc_urls = [u for u in rpc_urls if u]
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self.timeout_s = timeout_s
        self._quota_limiter = quota_limiter
        self._provider_ids: List[str] = list(provider_ids or [])
        if self._provider_ids and len(self._provider_ids) != len(self.rpc_urls):
            raise ValueError("provider_ids must align 1:1 with rpc_urls")
        self.stats = {"requests": 0, "batches": 0, "429": 0, "errors": 0}
        # Typed failure outcomes per attempt (additive observability; the
        # legacy return contract is unchanged).
        self.last_outcomes: List[Any] = []
        # Reused HTTP client — created on first batch_call, closed via
        # close() (Step 6 fix: avoid per-attempt client creation).
        self._http_client: Any = None

    @classmethod
    def from_config(
        cls,
        rpc_urls: List[str],
        *,
        timeout_s: float = 12.0,
        quota_yaml: Optional[Any] = None,
        provider_ids: Optional[List[str]] = None,
    ) -> "AsyncRpcBatchClient":
        """Build a client with a quota limiter loaded from real provider
        configuration (``config/provider_quotas.yaml`` +
        ``ARBY_QUOTA_<PID>`` env overrides).

        When ``provider_ids`` is not supplied the limiter still picks up
        the per-provider budgets via the limiter's default quota; calling
        code that already labels URLs (e.g. ``iter_dedicated_http_providers``)
        can pass through provider ids to apply per-provider throttling.
        """
        from chains.provider_quota import build_limiter_from_provider_config

        limiter = build_limiter_from_provider_config(
            Path(quota_yaml) if quota_yaml is not None else None
        )
        return cls(
            rpc_urls,
            timeout_s=timeout_s,
            quota_limiter=limiter,
            provider_ids=provider_ids,
        )

    async def _ensure_client(self) -> Any:
        if self._http_client is None:
            import httpx

            self._http_client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._http_client

    def _provider_id_for(self, index: int) -> Optional[str]:
        if 0 <= index < len(self._provider_ids):
            return self._provider_ids[index]
        return None

    async def batch_call(
        self,
        payloads: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not payloads or not self.rpc_urls:
            return []

        body = [
            {"jsonrpc": "2.0", "id": i, "method": p["method"], "params": p.get("params", [])}
            for i, p in enumerate(payloads)
        ]
        async with self._sem:
            self.stats["batches"] += 1
            self.last_outcomes = []
            client = await self._ensure_client()
            for idx, url in enumerate(self.rpc_urls):
                provider_id = self._provider_id_for(idx)
                try:
                    if self._quota_limiter is not None and provider_id is not None:
                        async with self._quota_limiter.acquire(provider_id):
                            resp = await client.post(url, json=body)
                    else:
                        resp = await client.post(url, json=body)
                    self.stats["requests"] += 1
                    if resp.status_code == 429:
                        self.stats["429"] += 1
                        from core.typed_outcomes import outcome_from_http_status

                        self.last_outcomes.append(
                            outcome_from_http_status(429, provider=provider_id or url)
                        )
                        await asyncio.sleep(min(2.0 ** self.stats["429"], 8.0))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    return data if isinstance(data, list) else [data]
                except Exception as exc:
                    self.stats["errors"] += 1
                    from core.typed_outcomes import outcome_from_exception

                    self.last_outcomes.append(
                        outcome_from_exception(exc, provider=provider_id or url)
                    )
                    _log.debug("async rpc batch failed url=%s: %s", url[:40], exc)
        return []

    async def close(self) -> None:
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception:  # pragma: no cover - depends on httpx internals
                _log.debug("httpx.AsyncClient.aclose raised; ignoring")
            self._http_client = None

    def last_failure_summary(self) -> Optional[Any]:
        """Return the highest-severity typed Outcome from the last batch_call.

        Returns ``None`` when the last batch succeeded (or when no typed
        outcomes were recorded — e.g. an empty batch was a no-op, not a
        failure). Callers that previously treated ``batch_call() == []``
        as "no data" can now distinguish:

          * ``last_failure_summary() is None``               -> no data found
          * ``last_failure_summary().retryable == True``     -> transient; can
            be retried (rate-limited / timeout) up to the stage's budget
          * ``last_failure_summary().retryable == False``    -> hard stage
            FAILED. Surface this through StageResult.typed_outcome via
            ``application.pipeline_stage.classify_typed_outcome`` so a
            non-retryable failure does not masquerade as "no data".

        This is the Step 7 fix: typed outcomes become part of the stage
        result instead of being silently swallowed by the legacy
        ``return []`` contract.
        """
        outcomes = self.last_outcomes or []
        non_retryable = [o for o in outcomes if not getattr(o, "retryable", True)]
        if non_retryable:
            return non_retryable[-1]
        retryable = [o for o in outcomes if getattr(o, "retryable", True)]
        if retryable:
            return retryable[-1]
        return None


def _decode_address(ret: bytes) -> Optional[str]:
    if not ret or len(ret) < 32:
        return None
    addr = "0x" + ret[-20:].hex()
    return None if addr.lower() == _ZERO_ADDR else addr.lower()


def _sort_pair(a: str, b: str) -> Tuple[str, str]:
    al, bl = a.lower(), b.lower()
    return (al, bl) if al < bl else (bl, al)


class FactoryBatchResolver:
    """Batch factory getPair/getPool reads via Multicall3."""

    def __init__(self, chain: str, config: Dict[str, Any]):
        self.chain = chain
        self.config = config
        self._batcher = None
        self._w3 = None
        self._rpc_urls: List[str] = []
        self._rpc_index = 0
        self.stats: Dict[str, int] = {"multicall_chunks": 0, "calls": 0, "pools_found": 0}

    def _resolve_rpc_urls(self) -> List[str]:
        if os.environ.get("ARBY_SKIP_RPC") == "1":
            return []
        from core.rpc_urls import (
            apply_productive_rpc_env,
            build_alchemy_ws_url,
            get_rpc_url,
            iter_dedicated_http_providers,
        )

        env = dict(os.environ)
        try:
            env = apply_productive_rpc_env(self.chain, env=env)
        except RuntimeError:
            pass
        api = (env.get("ALCHEMY_API_KEY") or "").strip()
        if api and not (env.get(f"{self.chain.upper()}_WSS") or "").strip():
            ws = build_alchemy_ws_url(self.chain, api)
            if ws:
                env[f"{self.chain.upper()}_WSS"] = ws
        os.environ.update(
            {k: v for k, v in env.items() if k.startswith(("BASE_", "ARBITRUM_", "ARBY_")) or k == "ALCHEMY_API_KEY"}
        )
        urls = [url for _label, url in iter_dedicated_http_providers(self.chain, env=env)]
        if not urls:
            rpc = get_rpc_url(self.chain)
            if rpc:
                urls = [rpc]
        return urls

    def _ensure_batcher(self, rpc_index: Optional[int] = None) -> bool:
        if self._batcher is not None and rpc_index is None:
            return True
        if not self._rpc_urls:
            self._rpc_urls = self._resolve_rpc_urls()
        if not self._rpc_urls:
            return False
        from core.multicall import MulticallBatcher

        idx = self._rpc_index if rpc_index is None else rpc_index
        idx %= len(self._rpc_urls)
        rpc = self._rpc_urls[idx]
        self._batcher = MulticallBatcher(rpc)
        self._w3 = None
        if not self._batcher._ensure_web3():
            return False
        self._rpc_index = idx
        return True

    def _execute_multicall_with_failover(
        self, calls: List[Tuple[str, bool, bytes]]
    ) -> List[Any]:
        if not self._rpc_urls:
            self._rpc_urls = self._resolve_rpc_urls()
        if not self._rpc_urls:
            return []
        last_results: List[Any] = []
        for attempt in range(len(self._rpc_urls)):
            idx = (self._rpc_index + attempt) % len(self._rpc_urls)
            if not self._ensure_batcher(idx):
                continue
            prev_429 = int((self._batcher.stats or {}).get("multicall_429", 0))  # type: ignore[union-attr]
            last_results = self._batcher._execute_multicall(calls)  # type: ignore[union-attr]
            cur_429 = int((self._batcher.stats or {}).get("multicall_429", 0))  # type: ignore[union-attr]
            if last_results:
                self._rpc_index = idx
                return last_results
            if cur_429 > prev_429 and attempt + 1 < len(self._rpc_urls):
                prov = self._rpc_urls[idx].split("/")[2][:30]
                _log.warning("Multicall 429 on %s — failing over to next RPC", prov)
                continue
            break
        return last_results

    def _encode_v2_get_pair(self, factory: str, token_a: str, token_b: str) -> bytes:
        from web3 import Web3

        if self._w3 is None:
            self._w3 = self._batcher._w3  # type: ignore[union-attr]
        contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(factory),
            abi=_V2_FACTORY_ABI,
        )
        t0, t1 = _sort_pair(token_a, token_b)
        return bytes.fromhex(
            contract.encode_abi(
                "getPair",
                [Web3.to_checksum_address(t0), Web3.to_checksum_address(t1)],
            )[2:]
        )

    def _encode_v3_get_pool(
        self, factory: str, token_a: str, token_b: str, fee: int
    ) -> bytes:
        from web3 import Web3

        if self._w3 is None:
            self._w3 = self._batcher._w3  # type: ignore[union-attr]
        contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(factory),
            abi=_V3_FACTORY_ABI,
        )
        t0, t1 = _sort_pair(token_a, token_b)
        return bytes.fromhex(
            contract.encode_abi(
                "getPool",
                [
                    Web3.to_checksum_address(t0),
                    Web3.to_checksum_address(t1),
                    fee,
                ],
            )[2:]
        )

    def _encode_algebra_pool_by_pair(
        self, factory: str, token_a: str, token_b: str
    ) -> bytes:
        from web3 import Web3

        from discovery.index_factories import ALGEBRA_FACTORY_ABI

        if self._w3 is None:
            self._w3 = self._batcher._w3  # type: ignore[union-attr]
        contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(factory),
            abi=ALGEBRA_FACTORY_ABI,
        )
        t0, t1 = _sort_pair(token_a, token_b)
        return bytes.fromhex(
            contract.encode_abi(
                "poolByPair",
                [Web3.to_checksum_address(t0), Web3.to_checksum_address(t1)],
            )[2:]
        )

    def _encode_iziswap_pool(
        self, factory: str, token_a: str, token_b: str, fee: int
    ) -> bytes:
        from web3 import Web3

        if self._w3 is None:
            self._w3 = self._batcher._w3  # type: ignore[union-attr]
        abi = [
            {
                "inputs": [
                    {"internalType": "address", "name": "tokenX", "type": "address"},
                    {"internalType": "address", "name": "tokenY", "type": "address"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                ],
                "name": "pool",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function",
            }
        ]
        contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(factory),
            abi=abi,
        )
        tx, ty = _sort_pair(token_a, token_b)
        return bytes.fromhex(
            contract.encode_abi(
                "pool",
                [Web3.to_checksum_address(tx), Web3.to_checksum_address(ty), fee],
            )[2:]
        )

    def resolve_many(
        self,
        *,
        token_addr: str,
        anchors: List[Tuple[str, str]],
        dex_rows: List[Dict[str, Any]],
        neg_cache: NegativeResultCache,
        adapter_map: Dict[str, str],
        fee_tiers_fn,
    ) -> Dict[Tuple[str, str], Tuple[Optional[str], str]]:
        """Resolve factory pools for one token × dex_rows × anchors via multicall."""
        out: Dict[Tuple[str, str], Tuple[Optional[str], str]] = {}
        if not self._ensure_batcher():
            for dex in dex_rows:
                for anchor_sym, _ in anchors:
                    out[(dex["dex_id"], anchor_sym)] = (None, "SKIPPED_DRY_RUN")
            return out

        from web3 import Web3

        calls: List[Tuple[str, bool, bytes]] = []
        call_keys: List[Tuple[str, str, str]] = []

        for dex in dex_rows:
            dex_id = dex["dex_id"]
            factory = str(dex.get("factory") or "")
            if not factory:
                for anchor_sym, _ in anchors:
                    out[(dex_id, anchor_sym)] = (None, "UNSUPPORTED_DEX")
                continue
            adapter = adapter_map.get(dex_id) or dex.get("adapter_type") or ""
            for anchor_sym, anchor_addr in anchors:
                cached = neg_cache.get(token_addr, dex_id, anchor_sym)
                if cached:
                    out[(dex_id, anchor_sym)] = (None, cached)
                    continue
                if adapter in ("uniswap_v2", "aerodrome_v2_stable"):
                    data = self._encode_v2_get_pair(factory, token_addr, anchor_addr)
                    calls.append((Web3.to_checksum_address(factory), True, data))
                    call_keys.append((dex_id, anchor_sym, "v2"))
                elif adapter == "algebra":
                    data = self._encode_algebra_pool_by_pair(
                        factory, token_addr, anchor_addr
                    )
                    calls.append((Web3.to_checksum_address(factory), True, data))
                    call_keys.append((dex_id, anchor_sym, "algebra"))
                elif adapter == "iziswap":
                    for fee in fee_tiers_fn(self.chain, dex_id)[:2]:
                        ck = neg_cache.get(token_addr, dex_id, anchor_sym, str(fee))
                        if ck:
                            out[(dex_id, anchor_sym)] = (None, ck)
                            break
                        data = self._encode_iziswap_pool(
                            factory, token_addr, anchor_addr, fee
                        )
                        calls.append((Web3.to_checksum_address(factory), True, data))
                        call_keys.append((dex_id, anchor_sym, f"izi:{fee}"))
                elif adapter in ("uniswap_v3", "aerodrome_slipstream"):
                    for fee in fee_tiers_fn(self.chain, dex_id)[:2]:
                        ck = neg_cache.get(token_addr, dex_id, anchor_sym, str(fee))
                        if ck:
                            out[(dex_id, anchor_sym)] = (None, ck)
                            break
                        data = self._encode_v3_get_pool(
                            factory, token_addr, anchor_addr, fee
                        )
                        calls.append((Web3.to_checksum_address(factory), True, data))
                        call_keys.append((dex_id, anchor_sym, f"v3:{fee}"))
                elif adapter == "ve33":
                    for stable in ("0", "1"):
                        data = self._encode_ve33_get_pool(
                            factory, token_addr, anchor_addr, stable == "1"
                        )
                        calls.append((Web3.to_checksum_address(factory), True, data))
                        call_keys.append((dex_id, anchor_sym, f"ve33:{stable}"))
                elif adapter == "uniswap_v4":
                    out[(dex_id, anchor_sym)] = (None, "V4_EVENT_INDEX_ONLY")
                elif adapter in (
                    "curve_stable",
                    "balancer_stable",
                    "maverick_v2",
                ):
                    out[(dex_id, anchor_sym)] = (None, "SPECIALIZED_INDEX_ONLY")
                else:
                    out[(dex_id, anchor_sym)] = (None, "ADAPTER_RESOLVE_PENDING")

        if not calls:
            return out

        self.stats["calls"] += len(calls)
        results = self._execute_multicall_with_failover(calls)
        self.stats["multicall_chunks"] += 1
        if not results:
            for key in call_keys:
                dex_id, anchor_sym, _ = key
                out.setdefault((dex_id, anchor_sym), (None, "NO_POOL"))
            return out

        for key, (ok, ret_bytes) in zip(call_keys, results, strict=False):
            dex_id, anchor_sym, fee_tag = key
            if (dex_id, anchor_sym) in out and out[(dex_id, anchor_sym)][0]:
                continue
            if not ok:
                out[(dex_id, anchor_sym)] = (None, "NO_POOL")
                neg_cache.put(token_addr, dex_id, anchor_sym, "NO_POOL", fee_tag=fee_tag)
                continue
            pool = _decode_address(ret_bytes)
            if pool:
                out[(dex_id, anchor_sym)] = (pool, "OK")
                self.stats["pools_found"] += 1
            else:
                if fee_tag.startswith(("v3:", "izi:")):
                    continue
                out[(dex_id, anchor_sym)] = (None, "NO_POOL")
                neg_cache.put(token_addr, dex_id, anchor_sym, "NO_POOL", fee_tag=fee_tag)

        for dex in dex_rows:
            dex_id = dex["dex_id"]
            for anchor_sym, _ in anchors:
                out.setdefault((dex_id, anchor_sym), (None, "NO_POOL"))
                if out[(dex_id, anchor_sym)][1] == "NO_POOL":
                    neg_cache.put(token_addr, dex_id, anchor_sym, "NO_POOL")
        return out

    def _encode_ve33_get_pool(
        self, factory: str, token_a: str, token_b: str, stable: bool
    ) -> bytes:
        from web3 import Web3

        if self._w3 is None:
            self._w3 = self._batcher._w3  # type: ignore[union-attr]
        abi = [
            {
                "inputs": [
                    {"internalType": "address", "name": "", "type": "address"},
                    {"internalType": "address", "name": "", "type": "address"},
                    {"internalType": "bool", "name": "", "type": "bool"},
                ],
                "name": "getPool",
                "outputs": [{"internalType": "address", "name": "", "type": "address"}],
                "stateMutability": "view",
                "type": "function",
            }
        ]
        contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(factory),
            abi=abi,
        )
        t0, t1 = _sort_pair(token_a, token_b)
        return bytes.fromhex(
            contract.encode_abi(
                "getPool",
                [
                    Web3.to_checksum_address(t0),
                    Web3.to_checksum_address(t1),
                    stable,
                ],
            )[2:]
        )


def split_candidate_rows(
    candidate_rows: List[Dict[str, Any]],
    canonical_dex_ids: Set[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """Split candidate rows into RPC scan vs canonical-covered aliases."""
    rpc_rows: List[Dict[str, Any]] = []
    covered: Dict[str, str] = {}
    for row in candidate_rows:
        dex_id = row["dex_id"]
        cfg_id = str(row.get("config_dex_id") or dex_id)
        status = str(row.get("registry_status") or "")
        if status in ("configured", "verified") and cfg_id in canonical_dex_ids:
            covered[dex_id] = cfg_id
            continue
        rpc_rows.append(row)
    return rpc_rows, covered


def mirror_canonical_candidate_telemetry(
    *,
    scan_telemetry: Dict[str, Any],
    candidate_telemetry: Dict[str, Any],
    token_address: str,
    covered: Dict[str, str],
    anchor_syms: List[str],
) -> None:
    """Copy canonical scan matrix cells into candidate matrix as covered_by_canonical_scan."""
    from m8.discovery.scan_telemetry import record_candidate_scan_attempt

    token = token_address.lower()
    canon_matrix = scan_telemetry.get("scan_attempt_matrix") or {}
    token_row = canon_matrix.get(token) or {}
    for cand_id, canon_id in covered.items():
        canon_dex_row = token_row.get(canon_id) or {}
        for anchor in anchor_syms:
            cell = canon_dex_row.get(anchor)
            if not cell:
                record_candidate_scan_attempt(
                    candidate_telemetry,
                    token_address=token,
                    dex_id=cand_id,
                    anchor=anchor,
                    registry_status="configured",
                    attempted=True,
                    result="COVERED_BY_CANONICAL_SCAN",
                    reason="covered_by_canonical_scan",
                )
                continue
            record_candidate_scan_attempt(
                candidate_telemetry,
                token_address=token,
                dex_id=cand_id,
                anchor=anchor,
                registry_status="configured",
                attempted=bool(cell.get("attempted")),
                result=str(cell.get("result") or "NO_POOL"),
                reason="covered_by_canonical_scan",
                pool_address=cell.get("pool_address"),
            )
