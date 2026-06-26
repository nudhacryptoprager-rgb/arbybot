"""Generic ERC20 token metadata worker — token-level truth only."""
from __future__ import annotations

from typing import Any, Dict, Optional

from m8.metadata.contracts import MetadataErrorCode, MetadataTask, TokenMetadataResult
from m8.metadata.registry import (
    ERROR_DECIMALS_CONFLICT,
    ERROR_DECIMALS_UNRESOLVED,
    ERROR_ERC20_DECIMALS_REVERT,
    ERROR_NO_CODE,
    ERROR_NON_ERC20,
    ERROR_PROBE_CAP_EXHAUSTED,
    resolve_token_entry,
)


class Erc20TokenWorker:
    """Probes token contracts; returns results to root aggregator only."""

    worker_id = "erc20_token"

    def build_task(self, address: str, *, scope: str = "all_tokens", priority: int = 0) -> MetadataTask:
        return MetadataTask(
            task_id=f"erc20:{address.lower()}",
            kind="token_erc20",
            worker_id=self.worker_id,
            address=address.lower(),
            scope=scope,
            priority=priority,
        )

    def process(
        self,
        task: MetadataTask,
        *,
        cfg: Any = None,
        sniper_hints: Optional[Dict[str, Dict[str, Any]]] = None,
        m81_hints: Optional[Dict[str, Dict[str, Any]]] = None,
        m82_hints: Optional[Dict[str, Dict[str, Any]]] = None,
        registry_cache: Optional[Dict[str, Dict[str, Any]]] = None,
        external_hints: Optional[Dict[str, Dict[str, Any]]] = None,
        w3: Any = None,
        probe_cap_exhausted: bool = False,
        onchain_prefetch: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> TokenMetadataResult:
        addr = (task.address or "").lower()
        if probe_cap_exhausted and w3 is None:
            return TokenMetadataResult(
                address=addr,
                error_code=ERROR_PROBE_CAP_EXHAUSTED,
                probe_skipped=True,
            )

        code_length: Optional[int] = None
        code_hash: Optional[str] = None
        if w3 is not None:
            from m8.metadata.token_risk import _code_hash, _fetch_code

            code = _fetch_code(w3, addr)
            code_length = len(code) if code and len(code) > 2 else 0
            code_hash = _code_hash(code) if code_length > 0 else None
            if code_length == 0:
                return TokenMetadataResult(
                    address=addr,
                    error_code=ERROR_NO_CODE,
                    code_length=0,
                )

        entry = resolve_token_entry(
            addr,
            cfg=cfg,
            sniper_hints=sniper_hints,
            m81_hints=m81_hints,
            m82_hints=m82_hints,
            registry_cache=registry_cache,
            external_hints=external_hints,
            w3=w3,
            onchain_prefetch=onchain_prefetch,
        )
        err = entry.get("error_code")
        if err == ERROR_ERC20_DECIMALS_REVERT and code_length is not None and code_length > 0:
            err = ERROR_NON_ERC20

        return TokenMetadataResult(
            address=addr,
            decimals=entry.get("decimals"),
            symbol=entry.get("symbol"),
            name=entry.get("name"),
            source=str(entry.get("source") or "unresolved"),
            economics_grade=str(entry.get("economics_grade") or "unresolved"),
            error_code=err,
            code_length=code_length,
            code_hash=code_hash,
        )


def _contract_code_length(w3: Any, addr: str) -> int:
    try:
        code = w3.eth.get_code(w3.to_checksum_address(addr))
        if code is None:
            return 0
        raw = bytes(code)
        if len(raw) <= 2 or raw == b"\x00":
            return 0
        return len(raw)
    except Exception:
        return 0
