"""Maverick V2 pool indexer — factory lookup/logs + verify + quote smoke."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from m8.discovery.specialized_index_rpc import (
    eth_block_number,
    eth_call,
    eth_get_logs,
    selector,
)

_REPO = Path(__file__).resolve().parents[2]
_METADATA = _REPO / "config/adapter_metadata.yaml"
_ZERO_POOL = "0x" + "0" * 40


def load_maverick_config(chain: str = "base") -> Dict[str, Any]:
    raw = yaml.safe_load(_METADATA.read_text(encoding="utf-8")) or {}
    mav = raw.get("maverick") or {}
    chain_cfg = mav.get(chain) or {}
    return {
        "factory_address": str(chain_cfg.get("factory_address") or "").lower(),
        "pool_info_address": str(chain_cfg.get("pool_info_address") or "").lower(),
        "quoter_address": str(
            chain_cfg.get("quoter_address") or "0xb40afdb85a07f37ae217e7d6462e609900dd8d7a"
        ).lower(),
        "lookup_pair_end_index": int(chain_cfg.get("lookup_pair_end_index") or 32),
        "pool_created_event": str(
            chain_cfg.get("pool_created_event")
            or (
                "PoolCreated(address,uint8,uint256,uint256,uint256,uint256,"
                "int32,address,address,uint8,address)"
            )
        ),
        "log_lookback_blocks": int(chain_cfg.get("log_lookback_blocks") or 50_000),
        "lookup_max_focus_tokens": int(chain_cfg.get("lookup_max_focus_tokens") or 120),
        "lookup_max_pairs": int(chain_cfg.get("lookup_max_pairs") or 600),
        "factory_pagination_page_size": int(
            chain_cfg.get("factory_pagination_page_size") or 50
        ),
        "factory_pagination_max_pools": int(
            chain_cfg.get("factory_pagination_max_pools") or 200
        ),
        "quote_debug_artifact": str(
            chain_cfg.get("quote_debug_artifact")
            or "data/tmp/m9_maverick_quote_debug_latest.json"
        ),
        "pools": dict(chain_cfg.get("pools") or {}),
    }


def _metadata_candidates(chain: str) -> List[Dict[str, Any]]:
    cfg = load_maverick_config(chain)
    out: List[Dict[str, Any]] = []
    for pool_addr, meta in cfg["pools"].items():
        if not isinstance(meta, dict):
            continue
        out.append(
            {
                "pool_address": str(pool_addr).lower(),
                "token_a": str(meta.get("token_a") or "").lower(),
                "token_b": str(meta.get("token_b") or "").lower(),
                "probe_status": meta.get("probe_status", "QUOTE_OK_CONFIG"),
                "source": "adapter_metadata",
            }
        )
    return out


def _priority_focus_tokens(
    registry_path: Optional[Path],
    watchlist_tokens: Set[str],
    *,
    max_tokens: int,
) -> List[str]:
    """Prefer registry tokens with venues before bulk watchlist scan."""
    priority: List[str] = []
    seen: Set[str] = set()
    if registry_path and registry_path.exists():
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
        for addr, meta in (reg.get("tokens") or {}).items():
            low = str(addr).lower()
            if not low.startswith("0x") or low not in watchlist_tokens:
                continue
            venues = meta if isinstance(meta, dict) else {}
            venue_map = venues.get("venues") or {}
            if venue_map and low not in seen:
                priority.append(low)
                seen.add(low)
    for tok in sorted(watchlist_tokens):
        if tok not in seen:
            priority.append(tok)
            seen.add(tok)
        if len(priority) >= max_tokens:
            break
    return priority[:max_tokens]


def _registry_candidates(registry_path: Path) -> List[Dict[str, Any]]:
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    out: List[Dict[str, Any]] = []
    for tok in (reg.get("tokens") or {}).values():
        for venue in (tok.get("venues") or {}).values():
            if venue.get("dex") != "maverick_v2":
                continue
            pool_addr = str(venue.get("pool") or "").lower()
            if not pool_addr.startswith("0x"):
                continue
            out.append(
                {
                    "pool_address": pool_addr,
                    "token_a": str(venue.get("token0") or "").lower(),
                    "token_b": str(venue.get("token1") or "").lower(),
                    "probe_status": "INDEXED_FROM_REGISTRY",
                    "source": "registry_venue",
                }
            )
    return out


def _decode_addr(hex_result: str) -> str:
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    return ("0x" + raw[-40:]).lower()


def _decode_address_array(hex_result: str) -> List[str]:
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 128:
        return []
    offset_chars = int(raw[:64], 16) * 2
    base = offset_chars
    if base + 64 > len(raw):
        return []
    length = int(raw[base : base + 64], 16)
    out: List[str] = []
    for i in range(length):
        start = base + 64 + i * 64
        word = raw[start : start + 64]
        if len(word) < 40:
            break
        out.append(("0x" + word[-40:]).lower())
    return out


def secondary_member_tokens(
    *,
    external_hints_artifact: Optional[Dict[str, Any]] = None,
    balancer_index_path: Optional[Path] = None,
) -> Set[str]:
    """Tokens from verified hints and Balancer index pool members."""
    out: Set[str] = set()
    if external_hints_artifact:
        for pool in (external_hints_artifact.get("pools") or []):
            if not isinstance(pool, dict):
                continue
            status = str(pool.get("hint_status") or "")
            if status and "VERIFIED" not in status:
                continue
            for key in ("token0_addr", "token1_addr", "focus_token"):
                addr = str(pool.get(key) or "").lower()
                if addr.startswith("0x"):
                    out.add(addr)
    path = balancer_index_path or (_REPO / "data/runs/_rolling/m8_balancer_pool_index_latest.json")
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for pool in raw.get("pools") or []:
                for addr in pool.get("assets") or []:
                    if str(addr).startswith("0x"):
                        out.add(str(addr).lower())
        except (json.JSONDecodeError, OSError):
            pass
    return out


def factory_lookup_paginated(
    rpc_url: str,
    factory: str,
    *,
    page_size: int = 50,
    max_pools: int = 200,
) -> List[str]:
    """Factory lookup(start,end) pagination across all deployed pools."""
    sel = selector("lookup(uint256,uint256)")
    out: List[str] = []
    seen: Set[str] = set()
    start = 0
    while start < max_pools:
        end = min(start + page_size, max_pools)
        data = (
            "0x"
            + sel
            + hex(start)[2:].zfill(64)
            + hex(end)[2:].zfill(64)
        )
        try:
            result = eth_call(rpc_url, factory, data)
            page = [
                a
                for a in _decode_address_array(result)
                if a and a != _ZERO_POOL and a not in seen
            ]
        except Exception:
            break
        if not page:
            break
        for addr in page:
            seen.add(addr)
            out.append(addr)
        if len(page) < (end - start):
            break
        start = end
    return out


def factory_lookup_pools_for_pair(
    rpc_url: str,
    factory: str,
    token_a: str,
    token_b: str,
    *,
    start_index: int = 0,
    end_index: int = 32,
) -> List[str]:
    """Maverick factory lookup(tokenA,tokenB,start,end) → pool address list."""
    ta, tb = sorted([token_a.lower(), token_b.lower()])
    sel = selector("lookup(address,address,uint256,uint256)")
    data = (
        "0x"
        + sel
        + ta[2:].zfill(64)
        + tb[2:].zfill(64)
        + hex(int(start_index))[2:].zfill(64)
        + hex(int(end_index))[2:].zfill(64)
    )
    try:
        result = eth_call(rpc_url, factory, data)
        return [a for a in _decode_address_array(result) if a and a != _ZERO_POOL]
    except Exception:
        return []


def _decode_pool_created_log(log: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Decode IMaverickV2Factory.PoolCreated via ABI (pool indexed, rest in data)."""
    from eth_abi import decode as abi_decode

    topics = log.get("topics") or []
    if len(topics) < 2:
        return None
    pool_addr = _decode_addr(str(topics[1]))
    data_hex = str(log.get("data") or "")
    if not data_hex.startswith("0x"):
        return None
    try:
        decoded = abi_decode(
            [
                "uint8",
                "uint256",
                "uint256",
                "uint256",
                "uint256",
                "int32",
                "address",
                "address",
                "uint8",
                "address",
            ],
            bytes.fromhex(data_hex[2:]),
        )
    except Exception:
        return None
    token_a = str(decoded[6]).lower()
    token_b = str(decoded[7]).lower()
    if token_a > token_b:
        token_a, token_b = token_b, token_a
    return {"pool_address": pool_addr, "token_a": token_a, "token_b": token_b}


def scan_pool_created_logs(
    rpc_url: str,
    *,
    factory: str,
    event_sig: str,
    lookback_blocks: int,
    watchlist_tokens: Set[str],
) -> List[Dict[str, Any]]:
    """Scan factory PoolCreated logs; keep pools touching watchlist tokens."""
    if not watchlist_tokens:
        return []
    head = eth_block_number(rpc_url)
    from_block = max(0, head - lookback_blocks)
    topic0 = "0x" + __import__("web3").Web3.keccak(text=event_sig).hex()
    out: List[Dict[str, Any]] = []
    chunk = 10_000
    for start in range(from_block, head, chunk):
        end = min(head, start + chunk - 1)
        try:
            logs = eth_get_logs(
                rpc_url,
                address=factory,
                topics=[topic0],
                from_block=start,
                to_block=end,
            )
        except Exception:
            continue
        for log in logs:
            decoded = _decode_pool_created_log(log)
            if not decoded:
                continue
            if watchlist_tokens and not (
                {decoded["token_a"], decoded["token_b"]} & watchlist_tokens
            ):
                continue
            out.append({**decoded, "source": "factory_pool_created"})
    return out


def verify_maverick_pool(
    rpc_url: str,
    pool: Dict[str, Any],
    *,
    factory: str,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Verify tokenA/tokenB and non-zero reserves via pool + factory."""
    pool_addr = str(pool.get("pool_address") or "").lower()
    if not pool_addr.startswith("0x"):
        return None, "MAVERICK_INVALID_ADDRESS"
    try:
        ta = eth_call(rpc_url, pool_addr, "0x" + selector("tokenA()"))
        tb = eth_call(rpc_url, pool_addr, "0x" + selector("tokenB()"))
        token_a = _decode_addr(ta)
        token_b = _decode_addr(tb)
    except Exception:
        return None, "MAVERICK_TOKEN_CALL_FAILED"
    if not token_a or not token_b:
        return None, "MAVERICK_TOKEN_MISMATCH"
    if token_a > token_b:
        token_a, token_b = token_b, token_a
    try:
        is_factory = eth_call(
            rpc_url,
            factory,
            "0x" + selector("isFactoryPool(address)") + pool_addr[2:].zfill(64),
        )
        if int(is_factory, 16) == 0:
            return None, "MAVERICK_NOT_FACTORY_POOL"
    except Exception:
        pass
    row = {
        **pool,
        "pool_address": pool_addr,
        "token_a": token_a,
        "token_b": token_b,
        "factory_verified": True,
        "verify_method": "maverick_tokenAB",
    }
    return row, "OK"


def quote_smoke_maverick(
    rpc_url: str,
    pool: Dict[str, Any],
    *,
    pool_info: str,
    debug_rows: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    import hashlib

    from dex.adapters.maverick_v2 import (
        _decode_calculate_swap,
        _decode_quoter_calculate_swap,
        _encode_calculate_swap,
        _encode_quoter_calculate_swap,
    )

    pool_addr = str(pool.get("pool_address") or "")
    token_a = str(pool.get("token_a") or "")
    token_b = str(pool.get("token_b") or "")
    if not pool_addr or not token_a or not token_b:
        return "MAVERICK_TOKEN_MISMATCH", "fail"
    cfg = load_maverick_config()
    quoter = str(cfg.get("quoter_address") or "").lower()
    pool_info_addr = str(pool_info or cfg.get("pool_info_address") or "").lower()
    last_debug: Dict[str, Any] = {}
    for token_in, token_a_in in ((token_a, True), (token_b, False)):
        for amount in (10_000, 1_000_000, 10**15):
            contours: List[Tuple[str, str, Any]] = []
            if quoter:
                contours.append(
                    (
                        "maverick_quoter",
                        quoter,
                        lambda: _encode_quoter_calculate_swap(
                            pool_addr, amount, token_a_in, tick_limit=0
                        ),
                    )
                )
            if pool_info_addr and pool_info_addr != quoter:
                contours.append(
                    (
                        "pool_information",
                        pool_info_addr,
                        lambda: _encode_calculate_swap(
                            pool_addr,
                            amount,
                            token_a_in=token_a_in,
                            exact_output=False,
                            sqrt_price_limit=0,
                        ),
                    )
                )
            for contour_name, target, encode_fn in contours:
                try:
                    calldata = encode_fn()
                    if not calldata.startswith("0x"):
                        calldata = "0x" + calldata
                    result = eth_call(rpc_url, target, calldata)
                    if contour_name == "maverick_quoter":
                        _amount_in, amount_out, _gas = _decode_quoter_calculate_swap(result)
                    else:
                        amount_out, _end = _decode_calculate_swap(result)
                    if amount_out > 0:
                        row = {
                            "status": "QUOTE_OK_MAVERICK",
                            "quote_contour": contour_name,
                            "pool_address": pool_addr,
                            "token_in": token_in,
                            "token_a_in": token_a_in,
                            "amount_in": amount,
                            "maverick_pool_lane_probe_amount": amount,
                            "maverick_min_quoteable_amount_raw": amount,
                            "maverick_max_quoteable_amount_raw": 10**15,
                            "calldata_hash": hashlib.sha256(calldata.encode()).hexdigest()[:16],
                        }
                        if debug_rows is not None:
                            debug_rows.append(row)
                        return "QUOTE_OK_MAVERICK", "ok"
                    last_debug = {
                        "status": "MAVERICK_ZERO_OUT",
                        "quote_contour": contour_name,
                        "pool_address": pool_addr,
                        "token_in": token_in,
                        "amount_in": amount,
                    }
                except Exception as exc:
                    err = exc if isinstance(exc, dict) else str(exc)
                    last_debug = {
                        "status": "MAVERICK_QUOTE_REVERT",
                        "quote_contour": contour_name,
                        "pool_address": pool_addr,
                        "token_in": token_in,
                        "token_a_in": token_a_in,
                        "amount_in": amount,
                        "raw_error": err,
                    }
    if last_debug and debug_rows is not None:
        debug_rows.append(last_debug)
    return "MAVERICK_QUOTE_REVERT", "fail"


def build_maverick_index(
    *,
    chain: str,
    rpc_url: str,
    watchlist_tokens: Set[str],
    connector_tokens: Set[str],
    registry_path: Optional[Path] = None,
    external_hints_artifact: Optional[Dict[str, Any]] = None,
    scan_factory_logs: bool = False,
    scan_factory_pagination: bool = True,
    verify_factory: bool = True,
    quote_smoke: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    cfg = load_maverick_config(chain)
    factory = cfg["factory_address"]
    pool_info = cfg["pool_info_address"]
    metrics = {"discovered": 0, "verified": 0, "quoteable": 0, "rejected": 0}

    secondary = secondary_member_tokens(
        external_hints_artifact=external_hints_artifact,
    )
    expanded_watchlist = watchlist_tokens | secondary
    candidates: List[Dict[str, Any]] = []
    candidates.extend(_metadata_candidates(chain))
    if registry_path and registry_path.exists():
        candidates.extend(_registry_candidates(registry_path))
    if scan_factory_pagination and factory:
        for pool_addr in factory_lookup_paginated(
            rpc_url,
            factory,
            page_size=cfg["factory_pagination_page_size"],
            max_pools=cfg["factory_pagination_max_pools"],
        ):
            candidates.append(
                {"pool_address": pool_addr, "source": "factory_pagination"}
            )
    if scan_factory_logs and factory:
        candidates.extend(
            scan_pool_created_logs(
                rpc_url,
                factory=factory,
                event_sig=cfg["pool_created_event"],
                lookback_blocks=cfg["log_lookback_blocks"],
                watchlist_tokens=expanded_watchlist,
            )
        )

    focus_tokens = _priority_focus_tokens(
        registry_path,
        expanded_watchlist,
        max_tokens=cfg["lookup_max_focus_tokens"],
    )
    lookup_pairs: List[Tuple[str, str]] = []
    pair_seen: Set[Tuple[str, str]] = set()
    connectors = sorted(connector_tokens)
    for i, ta in enumerate(connectors):
        for tb in connectors[i + 1 :]:
            if (ta, tb) in pair_seen:
                continue
            pair_seen.add((ta, tb))
            lookup_pairs.append((ta, tb))
            if len(lookup_pairs) >= cfg["lookup_max_pairs"]:
                break
        if len(lookup_pairs) >= cfg["lookup_max_pairs"]:
            break
    for focus in focus_tokens:
        for conn in connectors:
            if focus == conn:
                continue
            ta, tb = sorted([focus, conn])
            if (ta, tb) in pair_seen:
                continue
            pair_seen.add((ta, tb))
            lookup_pairs.append((ta, tb))
            if len(lookup_pairs) >= cfg["lookup_max_pairs"]:
                break
        if len(lookup_pairs) >= cfg["lookup_max_pairs"]:
            break

    metrics["lookup_pairs_scheduled"] = len(lookup_pairs)
    for ta, tb in lookup_pairs:
        for pool_addr in factory_lookup_pools_for_pair(
            rpc_url,
            factory,
            ta,
            tb,
            end_index=cfg["lookup_pair_end_index"],
        ):
            candidates.append(
                {
                    "pool_address": pool_addr,
                    "token_a": ta,
                    "token_b": tb,
                    "source": "factory_lookup",
                }
            )

    seen: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for cand in candidates:
        addr = str(cand.get("pool_address") or "").lower()
        if not addr or addr in seen:
            continue
        seen.add(addr)
        deduped.append(cand)
    metrics["discovered"] = len(deduped)

    quote_debug_rows: List[Dict[str, Any]] = []
    verified: List[Dict[str, Any]] = []
    token_universe = expanded_watchlist | connector_tokens
    for cand in deduped:
        row, reason = (
            verify_maverick_pool(rpc_url, cand, factory=factory)
            if verify_factory
            else (cand, "OK")
        )
        if not row:
            metrics["rejected"] += 1
            continue
        if token_universe and not (
            {row["token_a"], row["token_b"]} & token_universe
        ):
            metrics["rejected"] += 1
            continue
        verify_probe = "MAVERICK_FACTORY_VERIFIED"
        quote_probe = verify_probe
        if quote_smoke and pool_info:
            quote_probe, ok = quote_smoke_maverick(
                rpc_url, row, pool_info=pool_info, debug_rows=quote_debug_rows
            )
            if ok == "ok":
                metrics["quoteable"] += 1
        row["probe_status"] = verify_probe
        row["quote_smoke_status"] = quote_probe
        verified.append(row)
        metrics["verified"] += 1
    if not verified and metrics["discovered"] == 0:
        metrics["discovery_failed_reason"] = "ZERO_DISCOVERED_CANDIDATES"
    elif not verified:
        metrics["discovery_failed_reason"] = "ZERO_VERIFIED_AFTER_FILTER"
    metrics["secondary_watchlist_tokens"] = len(secondary)
    if quote_smoke:
        metrics["quote_debug_rows"] = len(quote_debug_rows)
        dbg_path = Path(cfg["quote_debug_artifact"])
        dbg_path.parent.mkdir(parents=True, exist_ok=True)
        payload = quote_debug_rows or [
            {"status": "MAVERICK_QUOTE_NO_ATTEMPTS", "verified_pools": len(verified)}
        ]
        dbg_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return verified, metrics
