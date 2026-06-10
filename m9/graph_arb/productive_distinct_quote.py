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


def balancer_cap_amount_in(
    amount_in: int,
    token_in: str,
    *,
    assets: Optional[List[str]] = None,
    balances: Optional[List[int]] = None,
    max_in_ratio: float = 0.02,
) -> int:
    """Cap swap input below Balancer max-in-ratio (BAL#304) using vault balances."""
    if not assets or not balances:
        return amount_in
    assets_lc = [str(a).lower() for a in assets]
    token_lc = token_in.lower()
    if token_lc not in assets_lc:
        return amount_in
    idx = assets_lc.index(token_lc)
    bal = int(balances[idx]) if idx < len(balances) else 0
    if bal <= 0:
        return amount_in
    cap = max(int(bal * max_in_ratio), 10**4)
    return min(amount_in, cap)


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
    balances: Optional[List[int]] = None,
) -> Tuple[int, Dict[str, Any]]:
    """Quote via BalancerQueries (preferred) or Vault; returns (amount_out, debug)."""
    from m8.discovery.balancer_indexer import load_balancer_config

    cfg = load_balancer_config(chain)
    sender_addr = sender or cfg["quote_smoke_sender"]
    recipient_addr = recipient or cfg["quote_smoke_recipient"]
    vault_addr = str(vault or BALANCER_VAULT_ADDRESS).lower()
    amount_in = balancer_cap_amount_in(
        amount_in,
        token_in,
        assets=all_assets,
        balances=balances,
    )
    data = _encode_query_batch_swap(
        pool_id,
        token_in,
        token_out,
        amount_in,
        sender=sender_addr,
        recipient=recipient_addr,
        all_assets=all_assets,
    )
    last_debug: Dict[str, Any] = {
        "quote_abi_path": "queryBatchSwap",
        "quote_selector": "0x" + _SELECTOR_QUERY_BATCH_SWAP.hex(),
        "quote_pool_id": pool_id,
    }
    try_amounts = [amount_in]
    if amount_in > 10**6:
        try_amounts.extend(
            max(amount_in // div, 10**4)
            for div in (10, 50, 200)
            if amount_in // div >= 10**4
        )
    for probe_in in try_amounts:
        data = _encode_query_batch_swap(
            pool_id,
            token_in,
            token_out,
            probe_in,
            sender=sender_addr,
            recipient=recipient_addr,
            all_assets=all_assets,
        )
        hex_data = "0x" + data.hex()
        for contour, target in balancer_quote_targets(
            chain=chain, vault=vault_addr, rpc_url=rpc_url
        ):
            debug = {
                **last_debug,
                "quote_contour": contour,
                "quote_target": target,
                "probe_amount_in": probe_in,
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
                if "BAL#304" not in str(err).upper():
                    break
    raise ValueError(last_debug.get("raw_error") or "balancer productive quote failed")


# Pool-lane smoke ladder (m8.discovery.maverick_indexer.quote_smoke_maverick).
MAVERICK_POOL_LANE_PROBE_LADDER: Tuple[int, ...] = (10_000, 1_000_000, 10**15)


def maverick_cycle_amount_in(
    cycle_amount_in: int,
    *,
    pool_lane_probe_amount: Optional[int] = None,
    min_quoteable: Optional[int] = None,
    max_quoteable: Optional[int] = None,
) -> int:
    """Prefer smallest verified pool-lane probe over USD-derived cycle size."""
    verified: Optional[int] = None
    if min_quoteable and int(min_quoteable) > 0:
        verified = int(min_quoteable)
    elif pool_lane_probe_amount and int(pool_lane_probe_amount) > 0:
        verified = int(pool_lane_probe_amount)
    if verified is not None:
        chosen = verified
    else:
        chosen = int(cycle_amount_in)
    if max_quoteable and int(max_quoteable) > 0 and chosen > int(max_quoteable):
        chosen = int(max_quoteable)
    return max(chosen, 1)


def cap_leg_amount_in_for_edge(edge: Any, amount_in: int) -> int:
    """Per-leg amount cap before RPC (Maverick probe replay, Balancer max-in-ratio)."""
    adapter = str(getattr(edge, "adapter_type", "") or "")
    if adapter == "maverick_v2":
        return maverick_cycle_amount_in(
            amount_in,
            pool_lane_probe_amount=getattr(edge, "maverick_pool_lane_probe_amount", None),
            min_quoteable=getattr(edge, "maverick_min_quoteable_amount_raw", None),
            max_quoteable=getattr(edge, "maverick_max_quoteable_amount_raw", None),
        )
    if adapter in ("balancer_stable", "balancer_weighted", "balancer_vault"):
        assets = getattr(edge, "balancer_assets", None)
        balances = getattr(edge, "balancer_balances", None)
        token_in = getattr(edge, "token_in_addr", None)
        if assets and balances and token_in:
            return balancer_cap_amount_in(
                int(amount_in),
                str(token_in).lower(),
                assets=list(assets),
                balances=list(balances),
            )
    return int(amount_in)


def _maverick_probe_amounts(
    amount_in: int,
    *,
    pool_lane_probe: Optional[int] = None,
) -> List[int]:
    """Smaller ladder for thin-bin Maverick pools (mirrors Balancer BAL#304 retry)."""
    amounts: List[int] = []
    if pool_lane_probe and pool_lane_probe > 0:
        amounts.append(int(pool_lane_probe))
    if amount_in > 0 and amount_in not in amounts:
        amounts.append(int(amount_in))
    if not amounts:
        amounts = [max(int(amount_in), 1)]
    seed = amounts[0]
    if seed > 10_000:
        for div in (10, 50, 200, 1000):
            probe = max(seed // div, 10**3)
            if probe < seed and probe not in amounts:
                amounts.append(probe)
    return amounts


def _maverick_direction_candidates(
    token_a_in: bool,
    *,
    token_in: Optional[str] = None,
    token_a: Optional[str] = None,
) -> List[bool]:
    """Probe order: explicit flag, address-inferred direction, then flip."""
    candidates: List[bool] = [token_a_in]
    if token_in and token_a:
        inferred = token_in.lower() == token_a.lower()
        if inferred not in candidates:
            candidates.insert(0, inferred)
    flipped = not candidates[0]
    if flipped not in candidates:
        candidates.append(flipped)
    return candidates


def _maverick_contours(
    pool_lc: str,
    *,
    probe_in: int,
    token_a_in: bool,
    chain: str,
    allow_pool_direct: bool = False,
) -> List[Tuple[str, str, str, Callable[[], str]]]:
    quoter = _maverick_quoter_address(chain)
    pool_info = _maverick_pool_info_address(chain)
    contours: List[Tuple[str, str, str, Callable[[], str]]] = []
    if quoter:
        contours.append(
            (
                "maverick_quoter",
                quoter,
                "0x" + _SELECTOR_QUOTER_CALCULATE_SWAP.hex(),
                lambda _pin=probe_in, _tai=token_a_in: _encode_quoter_calculate_swap(
                    pool_lc, _pin, _tai, tick_limit=0
                ),
            )
        )
    if pool_info and pool_info != quoter:
        contours.append(
            (
                "pool_information",
                pool_info,
                "0x" + _SELECTOR_CALCULATE_SWAP.hex(),
                lambda _pin=probe_in, _tai=token_a_in: _encode_calculate_swap(
                    pool_lc, _pin, token_a_in=_tai
                ),
            )
        )
    if allow_pool_direct and pool_lc not in {quoter, pool_info}:
        contours.append(
            (
                "pool_direct",
                pool_lc,
                "0x" + _SELECTOR_CALCULATE_SWAP.hex(),
                lambda _pin=probe_in, _tai=token_a_in: _encode_calculate_swap(
                    pool_lc, _pin, token_a_in=_tai
                ),
            )
        )
    return contours


def quote_maverick_productive(
    eth_call: EthCallFn,
    *,
    pool_address: str,
    amount_in: int,
    token_a_in: bool,
    chain: str = "base",
    token_in: Optional[str] = None,
    token_a: Optional[str] = None,
    allow_pool_direct: bool = False,
    pool_lane_probe_amount: Optional[int] = None,
) -> Tuple[int, Optional[int], Dict[str, Any]]:
    """Quoter-first Maverick quote; pool-direct only when explicitly enabled."""
    pool_lc = pool_address.lower()
    audit = {
        "pool_address": pool_lc,
        "token_in": (token_in or "").lower() or None,
        "token_a": (token_a or "").lower() or None,
    }
    effective_in = maverick_cycle_amount_in(
        amount_in,
        pool_lane_probe_amount=pool_lane_probe_amount,
    )
    last_debug: Dict[str, Any] = {
        "quote_pool_id": pool_lc,
        "cycle_amount_in": amount_in,
        "pool_lane_probe_amount": pool_lane_probe_amount,
        **audit,
    }
    for dir_flag in _maverick_direction_candidates(
        token_a_in, token_in=token_in, token_a=token_a
    ):
        for probe_in in _maverick_probe_amounts(
            effective_in, pool_lane_probe=pool_lane_probe_amount
        ):
            for contour_name, target, selector, encode_fn in _maverick_contours(
                pool_lc,
                probe_in=probe_in,
                token_a_in=dir_flag,
                chain=chain,
                allow_pool_direct=allow_pool_direct,
            ):
                debug = {
                    **last_debug,
                    "token_a_in": dir_flag,
                    "probe_amount_in": probe_in,
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
                    debug["calldata_prefix"] = calldata[:18]
                    debug["exact_output"] = False
                    debug["tick_limit"] = 0
                    result = eth_call(target, calldata)
                    if contour_name == "maverick_quoter":
                        _amount_in, amount_out, gas_est = _decode_quoter_calculate_swap(result)
                        debug["amount_in_decoded"] = _amount_in
                    else:
                        amount_out, _end = _decode_calculate_swap(result)
                        gas_est = None
                    debug["amount_out"] = amount_out
                    if amount_out > 0:
                        debug["status"] = "QUOTE_OK_MAVERICK"
                        return amount_out, gas_est, debug
                    last_debug = {**debug, "status": "MAVERICK_ZERO_OUT"}
                except Exception as exc:
                    err = exc if isinstance(exc, dict) else str(exc)
                    last_debug = {
                        **debug,
                        "status": "MAVERICK_QUOTE_REVERT",
                        "raw_error": err,
                    }
    raise ValueError(json.dumps(last_debug))
