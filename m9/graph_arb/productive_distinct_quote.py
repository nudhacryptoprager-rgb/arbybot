"""Productive M9 quote contours for Balancer / Maverick (aligned with discovery smoke)."""
from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from dex.adapters.balancer_vault import (
    BALANCER_VAULT_ADDRESS,
    _decode_query_batch_swap,
    _encode_query_batch_swap,
    _SELECTOR_QUERY_BATCH_SWAP,
)
from dex.adapters.maverick_v2 import (
    _decode_calculate_swap,
    _decode_quoter_calculate_swap,
    _encode_calculate_swap,
    _encode_quoter_calculate_swap,
    _SELECTOR_CALCULATE_SWAP,
    _SELECTOR_QUOTER_CALCULATE_SWAP,
    MAVERICK_V2_POOL_INFO_ADDRESS,
)

EthCallFn = Callable[[str, str], str]

_BPT_SUFFIX_MARKERS = ("bpt", "bpt-")


def balancer_index_row_tokens(row: dict) -> tuple[str, str, list[str]]:
    """Resolve (token_in, token_out, all_assets) from a Balancer index pool row."""
    assets = [str(a).lower() for a in (row.get("assets") or row.get("tokens_list") or [])]
    if len(assets) >= 2:
        tradeable = [a for a in assets if not any(m in a for m in _BPT_SUFFIX_MARKERS)]
        if len(tradeable) >= 2:
            return tradeable[0], tradeable[1], assets
    token_a = str(row.get("token_a") or row.get("token0_addr") or "").lower()
    token_b = str(row.get("token_b") or row.get("token1_addr") or "").lower()
    if token_a and token_b:
        return token_a, token_b, assets or [token_a, token_b]
    return "", "", assets


def balancer_probe_amount_in(row: dict, *, token_in: str, default: int = 10**15) -> int:
    """Balance-aware smoke amount aligned with discovery indexer."""
    assets = [str(a).lower() for a in (row.get("assets") or [])]
    balances = list(row.get("balances") or [])
    if token_in in assets:
        idx = assets.index(token_in)
        bal = int(balances[idx]) if idx < len(balances) else 0
        if bal > 0:
            return min(default, max(10**6, bal // 1000))
    return default


def _contract_has_code(rpc_url: str, address: str) -> bool:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getCode",
            "params": [address, "latest"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    code = str(body.get("result") or "0x")
    return len(code) > 2


def _balancer_queries_address(chain: str) -> str:
    from m8.discovery.balancer_indexer import load_balancer_config

    return str(load_balancer_config(chain).get("queries_address") or "").lower()


def _maverick_quoter_address(chain: str) -> str:
    from m8.discovery.maverick_indexer import load_maverick_config

    return str(load_maverick_config(chain).get("quoter_address") or "").lower()


def _maverick_pool_info_address(chain: str) -> str:
    from m8.discovery.maverick_indexer import load_maverick_config

    return str(
        load_maverick_config(chain).get("pool_info_address")
        or MAVERICK_V2_POOL_INFO_ADDRESS
    ).lower()


def balancer_quote_targets(
    *,
    chain: str = "base",
    vault: Optional[str] = None,
    rpc_url: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Return (contour_name, target_address) in probe order."""
    vault_addr = str(vault or BALANCER_VAULT_ADDRESS).lower()
    queries = _balancer_queries_address(chain)
    targets: List[Tuple[str, str]] = []
    if queries and rpc_url and _contract_has_code(rpc_url, queries):
        targets.append(("balancer_queries", queries))
    targets.append(("vault", vault_addr))
    return targets


def quote_balancer_productive(
    eth_call: EthCallFn,
    *,
    pool_id: str,
    token_in: str,
    token_out: str,
    amount_in: int,
    chain: str = "base",
    vault: Optional[str] = None,
    all_assets: Optional[List[str]] = None,
    sender: Optional[str] = None,
    recipient: Optional[str] = None,
    rpc_url: Optional[str] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Quote via BalancerQueries (preferred) or Vault; returns (amount_out, debug)."""
    from m8.discovery.balancer_indexer import load_balancer_config

    cfg = load_balancer_config(chain)
    sender_addr = sender or cfg["quote_smoke_sender"]
    recipient_addr = recipient or cfg["quote_smoke_recipient"]
    vault_addr = str(vault or BALANCER_VAULT_ADDRESS).lower()
    data = _encode_query_batch_swap(
        pool_id,
        token_in,
        token_out,
        amount_in,
        sender=sender_addr,
        recipient=recipient_addr,
        all_assets=all_assets,
    )
    hex_data = "0x" + data.hex()
    last_debug: Dict[str, Any] = {
        "quote_abi_path": "queryBatchSwap",
        "quote_selector": "0x" + _SELECTOR_QUERY_BATCH_SWAP.hex(),
        "quote_pool_id": pool_id,
    }
    for contour, target in balancer_quote_targets(
        chain=chain, vault=vault_addr, rpc_url=rpc_url
    ):
        debug = {
            **last_debug,
            "quote_contour": contour,
            "quote_target": target,
        }
        try:
            result = eth_call(target, hex_data)
            _delta_in, delta_out = _decode_query_batch_swap(result)
            amount_out = abs(delta_out)
            if amount_out > 0:
                debug["status"] = "QUOTE_OK_BALANCER"
                return amount_out, debug
            last_debug = {**debug, "status": "BALANCER_ZERO_OUT"}
        except Exception as exc:
            err = exc if isinstance(exc, dict) else str(exc)
            last_debug = {**debug, "status": "BALANCER_QUOTE_REVERT", "raw_error": err}
    raise ValueError(last_debug.get("raw_error") or "balancer productive quote failed")


def quote_maverick_productive(
    eth_call: EthCallFn,
    *,
    pool_address: str,
    amount_in: int,
    token_a_in: bool,
    chain: str = "base",
) -> Tuple[int, Optional[int], Dict[str, Any]]:
    """Quoter-first Maverick quote; PoolInformation only as explicit fallback."""
    pool_lc = pool_address.lower()
    quoter = _maverick_quoter_address(chain)
    pool_info = _maverick_pool_info_address(chain)
    contours: List[Tuple[str, str, str, Callable[[], str]]] = []
    if quoter:
        contours.append(
            (
                "maverick_quoter",
                quoter,
                "0x" + _SELECTOR_QUOTER_CALCULATE_SWAP.hex(),
                lambda: _encode_quoter_calculate_swap(
                    pool_lc, amount_in, token_a_in, tick_limit=0
                ),
            )
        )
    if pool_info and pool_info != quoter:
        contours.append(
            (
                "pool_information",
                pool_info,
                "0x" + _SELECTOR_CALCULATE_SWAP.hex(),
                lambda: _encode_calculate_swap(
                    pool_lc, amount_in, token_a_in=token_a_in
                ),
            )
        )
    last_debug: Dict[str, Any] = {"quote_pool_id": pool_lc}
    for contour_name, target, selector, encode_fn in contours:
        debug = {
            **last_debug,
            "quote_contour": contour_name,
            "quote_target": target,
            "quote_selector": selector,
            "quote_abi_path": (
                "MaverickV2Quoter.calculateSwap"
                if contour_name == "maverick_quoter"
                else "PoolInformation.calculateSwap"
            ),
        }
        try:
            calldata = encode_fn()
            if not calldata.startswith("0x"):
                calldata = "0x" + calldata
            result = eth_call(target, calldata)
            if contour_name == "maverick_quoter":
                _amount_in, amount_out, gas_est = _decode_quoter_calculate_swap(result)
            else:
                amount_out, _end = _decode_calculate_swap(result)
                gas_est = None
            if amount_out > 0:
                debug["status"] = "QUOTE_OK_MAVERICK"
                return amount_out, gas_est, debug
            last_debug = {**debug, "status": "MAVERICK_ZERO_OUT"}
        except Exception as exc:
            err = exc if isinstance(exc, dict) else str(exc)
            last_debug = {**debug, "status": "MAVERICK_QUOTE_REVERT", "raw_error": err}
    raise ValueError(last_debug.get("raw_error") or "maverick productive quote failed")
