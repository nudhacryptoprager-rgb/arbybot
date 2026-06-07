"""Recent factory-log scan for pools containing a token (Phase 1.5).

Uses ``config/new_pool_factories.yaml`` via :func:`load_factory_config` —
no hardcoded factory addresses or topic0 values.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from discovery.new_pool_listener import (
    FactoryConfig,
    NewPoolEvent,
    load_factory_config,
    parse_raw_log,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_BLOCKS_PER_CALL = 500
DEFAULT_MAX_LOOKBACK_BLOCKS = 43200

GetLogsFn = Callable[[Dict[str, Any]], List[Any]]


def address_to_topic(address: str) -> str:
    """Left-pad a 20-byte address to a 32-byte log topic."""
    raw = (address or "").lower().replace("0x", "")
    if len(raw) != 40:
        raise ValueError(f"invalid address for topic filter: {address!r}")
    return "0x" + raw.zfill(64)


def _build_token_topic_filters(cfg: FactoryConfig, token_topic: str) -> List[List[Any]]:
    """Topic filter variants that match logs where token appears as a pool member."""
    if not cfg.topic0:
        return []
    t0 = cfg.topic0
    if cfg.log_layout == "v4_initialize":
        return [
            [t0, None, token_topic, None],
            [t0, None, None, token_topic],
        ]
    return [
        [t0, token_topic, None],
        [t0, None, token_topic],
    ]


def _chunked_get_logs(
    get_logs: GetLogsFn,
    params: Dict[str, Any],
    *,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
) -> List[Any]:
    from_block = int(params["fromBlock"])
    to_block = int(params["toBlock"])
    if from_block > to_block:
        return []
    if to_block - from_block + 1 <= max_blocks_per_call:
        return list(get_logs(params) or [])

    out: List[Any] = []
    start = from_block
    while start <= to_block:
        end = min(start + max_blocks_per_call - 1, to_block)
        chunk = dict(params)
        chunk["fromBlock"] = start
        chunk["toBlock"] = end
        out.extend(get_logs(chunk) or [])
        start = end + 1
    return out


def find_recent_pools_containing_token(
    token_address: str,
    *,
    from_block: int,
    to_block: int,
    chain: str,
    w3: Any,
    get_logs: Optional[GetLogsFn] = None,
    factory_configs: Optional[Sequence[FactoryConfig]] = None,
    max_blocks_per_call: int = DEFAULT_MAX_BLOCKS_PER_CALL,
) -> List[NewPoolEvent]:
    """Scan enabled factory logs for pools whose members include ``token_address``."""
    token_address = (token_address or "").lower()
    if not token_address.startswith("0x") or len(token_address) != 42:
        return []

    configs = list(factory_configs or load_factory_config(chain_filter=chain))
    if not configs:
        return []

    fetch: GetLogsFn
    if get_logs is not None:
        fetch = get_logs
    else:
        def fetch(p: Dict[str, Any]) -> List[Any]:
            return list(w3.eth.get_logs(p))

    try:
        token_topic = address_to_topic(token_address)
    except ValueError:
        return []

    seen_ids: set[str] = set()
    events: List[NewPoolEvent] = []

    for cfg in configs:
        if cfg.chain != chain:
            continue
        topic_filters = _build_token_topic_filters(cfg, token_topic)
        if not topic_filters:
            continue
        factory_cs = w3.to_checksum_address(cfg.factory)
        for topics in topic_filters:
            params: Dict[str, Any] = {
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": factory_cs,
                "topics": topics,
            }
            try:
                raw_logs = _chunked_get_logs(
                    fetch,
                    params,
                    max_blocks_per_call=max_blocks_per_call,
                )
            except Exception as exc:
                logger.debug(
                    "factory_token_scan get_logs failed dex=%s: %s",
                    cfg.dex,
                    exc,
                )
                continue
            for raw in raw_logs:
                parsed = parse_raw_log(raw, cfg)
                if parsed is None:
                    continue
                if parsed.event_id in seen_ids:
                    continue
                t0 = parsed.token0.lower()
                t1 = parsed.token1.lower()
                if token_address not in (t0, t1):
                    continue
                seen_ids.add(parsed.event_id)
                events.append(parsed)

    events.sort(key=lambda e: (e.block_number, e.log_index))
    return events


def new_pool_event_to_registry_dict(
    event: NewPoolEvent,
    *,
    addr_to_sym: Dict[str, str],
) -> Dict[str, Any]:
    """Convert parsed factory event to pending-registry event dict."""
    d = event.to_dict()
    d["dex_id"] = d.get("dex", "")
    d["pool_address"] = d.get("pool", "")

    def _sym(addr: str) -> str:
        return addr_to_sym.get((addr or "").lower(), "") or (addr or "")[:10]

    d["token0_symbol"] = _sym(d.get("token0", ""))
    d["token1_symbol"] = _sym(d.get("token1", ""))
    return d
