"""External router probes (0x / 1inch / Uniswap) — liveness benchmark only.

These routes are **not** canonical arbitrage truth and must never enter bridge
admission. Use for ``external_route_liveness`` telemetry only.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

NOT_CONFIGURED = "NOT_CONFIGURED"
LIVENESS_PROBE_ONLY = "external_route_liveness_no_bridge_admission"

_CHAIN_ID_BASE = 8453
_DEFAULT_TIMEOUT_S = 10.0


def _probe_tokens(chain: str = "base") -> tuple[str, str]:
    from core.token_identity import address_symbol_map

    addr_map = address_symbol_map(chain)
    sym_to_addr = {v.upper(): k.lower() for k, v in addr_map.items()}
    usdc = sym_to_addr.get("USDC") or sym_to_addr.get("USDBC") or ""
    weth = sym_to_addr.get("WETH") or sym_to_addr.get("WETH_BASE") or ""
    return usdc, weth


def _probe_http(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "arby-m8-radar/1.0", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe_0x_swap_liveness(
    *,
    sell_token: str = "",
    buy_token: str = "",
    sell_amount: str = "1000000",
    chain_id: int = _CHAIN_ID_BASE,
    chain: str = "base",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    api_key = os.environ.get("ZEROX_API_KEY", "").strip()
    if not sell_token or not buy_token:
        sell_token, buy_token = _probe_tokens(chain)
        if not sell_token or not buy_token:
            return {
                "provider": "0x",
                "status": NOT_CONFIGURED,
                "admission": LIVENESS_PROBE_ONLY,
                "error": "core_tokens_unresolved",
            }
    if not api_key:
        return {
            "provider": "0x",
            "status": NOT_CONFIGURED,
            "admission": LIVENESS_PROBE_ONLY,
        }
    url = (
        f"https://api.0x.org/swap/permit2/price"
        f"?chainId={chain_id}&sellToken={sell_token}&buyToken={buy_token}"
        f"&sellAmount={sell_amount}"
    )
    try:
        body = _probe_http(url, headers={"0x-api-key": api_key}, timeout_s=timeout_s)
        ok = bool(body.get("buyAmount") or body.get("liquidityAvailable"))
        return {
            "provider": "0x",
            "status": "LIVE" if ok else "NO_ROUTE",
            "admission": LIVENESS_PROBE_ONLY,
            "buy_amount": body.get("buyAmount"),
        }
    except Exception as exc:
        return {
            "provider": "0x",
            "status": "ERROR",
            "admission": LIVENESS_PROBE_ONLY,
            "error": str(exc)[:120],
        }


def probe_1inch_liveness(
    *,
    src: str = "",
    dst: str = "",
    amount: str = "1000000",
    chain_id: int = _CHAIN_ID_BASE,
    chain: str = "base",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    api_key = os.environ.get("ONEINCH_API_KEY", "").strip()
    if not src or not dst:
        src, dst = _probe_tokens(chain)
        if not src or not dst:
            return {
                "provider": "1inch",
                "status": NOT_CONFIGURED,
                "admission": LIVENESS_PROBE_ONLY,
                "error": "core_tokens_unresolved",
            }
    if not api_key:
        return {
            "provider": "1inch",
            "status": NOT_CONFIGURED,
            "admission": LIVENESS_PROBE_ONLY,
        }
    url = (
        f"https://api.1inch.dev/swap/v6.0/{chain_id}/quote"
        f"?src={src}&dst={dst}&amount={amount}"
    )
    try:
        body = _probe_http(
            url, headers={"Authorization": f"Bearer {api_key}"}, timeout_s=timeout_s
        )
        ok = bool(body.get("dstAmount") or body.get("toAmount"))
        return {
            "provider": "1inch",
            "status": "LIVE" if ok else "NO_ROUTE",
            "admission": LIVENESS_PROBE_ONLY,
            "dst_amount": body.get("dstAmount") or body.get("toAmount"),
        }
    except Exception as exc:
        return {
            "provider": "1inch",
            "status": "ERROR",
            "admission": LIVENESS_PROBE_ONLY,
            "error": str(exc)[:120],
        }


def probe_uniswap_routing_liveness(
    *,
    token_in: str = "",
    token_out: str = "",
    amount: str = "1000000",
    chain_id: int = _CHAIN_ID_BASE,
    chain: str = "base",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """Uniswap routing API quote — benchmark only."""
    if not token_in or not token_out:
        token_in, token_out = _probe_tokens(chain)
        if not token_in or not token_out:
            return {
                "provider": "uniswap_routing",
                "status": NOT_CONFIGURED,
                "admission": LIVENESS_PROBE_ONLY,
                "error": "core_tokens_unresolved",
            }
    url = (
        f"https://interface.gateway.uniswap.org/v1/quote"
        f"?tokenInChainId={chain_id}&tokenOutChainId={chain_id}"
        f"&tokenInAddress={token_in}&tokenOutAddress={token_out}"
        f"&amount={amount}&type=exactIn"
    )
    try:
        body = _probe_http(url, timeout_s=timeout_s)
        quote = body.get("quote") or body
        ok = bool(quote.get("quote") or quote.get("amountOut"))
        return {
            "provider": "uniswap_routing",
            "status": "LIVE" if ok else "NO_ROUTE",
            "admission": LIVENESS_PROBE_ONLY,
        }
    except Exception as exc:
        return {
            "provider": "uniswap_routing",
            "status": "ERROR",
            "admission": LIVENESS_PROBE_ONLY,
            "error": str(exc)[:120],
        }


def run_external_route_liveness_probes(
    *,
    chain: str = "base",
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> List[Dict[str, Any]]:
    return [
        probe_0x_swap_liveness(chain=chain, timeout_s=timeout_s),
        probe_1inch_liveness(chain=chain, timeout_s=timeout_s),
        probe_uniswap_routing_liveness(chain=chain, timeout_s=timeout_s),
    ]
