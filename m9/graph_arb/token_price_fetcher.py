"""Token price fetcher for M9 graph-arb runner.

Tries CoinGecko free API (by contract address on Base chain) with a short
timeout, then falls back to the hardcoded baseline dict.  Designed to be
called once at runner startup; results are cached for the session.

Public API
----------
    result = fetch_token_prices_usd(timeout_s=5.0)
    # result.prices: Dict[str, float]  — symbol → USD price
    # result.source: str               — "coingecko" | "hardcoded_fallback"
    # result.stale: bool               — True when using fallback
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)


def _get_coingecko_api_key() -> str | None:
    """Extract CoinGecko demo API key from COINGECKO_API_URL env var.

    Supports the format stored in .env:
        COINGECKO_API_URL=https://api.coingecko.com/...&x_cg_demo_api_key=CG-...
    Also checks the standalone env var CG_DEMO_API_KEY as fallback.
    """
    # First try standalone env var
    key = os.environ.get("CG_DEMO_API_KEY", "").strip()
    if key:
        return key
    # Parse from COINGECKO_API_URL
    url = os.environ.get("COINGECKO_API_URL", "").strip()
    if url:
        try:
            params = parse_qs(urlparse(url).query)
            key = (params.get("x_cg_demo_api_key") or params.get("x_cg_pro_api_key") or [None])[0]
            if key and key.startswith("CG-"):
                return key
        except Exception:
            pass
    return None

# ---------------------------------------------------------------------------
# Baseline (hard-coded fallback) prices — approximate order-of-magnitude values.
# Update manually when prices drift significantly.  The fetcher tries CoinGecko
# first and only falls back to these when the API is unreachable.
# ---------------------------------------------------------------------------

def _baseline_prices(chain: str = "base") -> Dict[str, float]:
    from m9.graph_arb.core_tokens_loader import symbol_baseline_prices

    return symbol_baseline_prices(chain)


def _base_addr_to_symbol(chain: str = "base") -> Dict[str, str]:
    from m9.graph_arb.core_tokens_loader import address_symbol_map

    return address_symbol_map(chain)

# CoinGecko platform ID for Base chain
_COINGECKO_PLATFORM = "base"
_COINGECKO_URL_TEMPLATE = (
    "https://api.coingecko.com/api/v3/simple/token_price/{platform}"
    "?contract_addresses={addrs}&vs_currencies=usd"
)


@dataclass
class TokenPriceResult:
    """Result of a token price fetch operation."""

    prices: Dict[str, float] = field(default_factory=dict)
    source: str = "hardcoded_fallback"
    stale: bool = True
    prices_by_address: Dict[str, float] = field(default_factory=dict)


def _price_by_truncated_prefix(sym: str, price_map: Dict[str, float]) -> Optional[float]:
    """Match ``0x833589``-style labels to a unique full-address price entry."""
    s = (sym or "").strip().lower()
    if not s.startswith("0x") or len(s) >= 42:
        return None
    hits = [
        float(p)
        for a, p in price_map.items()
        if isinstance(a, str)
        and len(a) == 42
        and a.startswith("0x")
        and a.lower().startswith(s)
        and float(p) > 0
    ]
    if len(hits) == 1:
        return hits[0]
    return None


def resolve_token_price_usd(
    token_addr: str,
    token_sym: str,
    price_map: Optional[Dict[str, float]] = None,
) -> Optional[float]:
    """Address-first USD price lookup; symbol fallback for canonical labels only."""
    if not price_map:
        return None
    addr_l = (token_addr or "").strip().lower()
    if len(addr_l) == 42 and addr_l.startswith("0x"):
        p = price_map.get(addr_l)
        if p is not None and float(p) > 0:
            return float(p)
    sym = (token_sym or "").strip()
    if sym and not (sym.lower().startswith("0x") and len(sym) < 42):
        p = price_map.get(sym)
        if p is not None and float(p) > 0:
            return float(p)
    px = _price_by_truncated_prefix(sym, price_map)
    if px is not None:
        return px
    px = _price_by_truncated_prefix(addr_l, price_map)
    if px is not None:
        return px
    return None


def extend_price_map_from_inventory(
    inventory_path: str,
    config_path: str,
    price_map: Dict[str, float],
) -> Dict[str, float]:
    """Add address-keyed prices for every token seen in bridge inventory."""
    import json
    from pathlib import Path

    from m8_1.stable_anchor.config_loader import load_config

    out = dict(price_map)
    inv_p = Path(inventory_path)
    if not inv_p.exists():
        return build_dual_key_price_map(out)

    try:
        with inv_p.open(encoding="utf-8") as fh:
            inv = json.load(fh)
    except Exception:
        return build_dual_key_price_map(out)

    cfg = None
    if Path(config_path).exists():
        try:
            cfg = load_config(config_path)
        except Exception:
            cfg = None

    stable_addrs = frozenset(
        a.lower()
        for a, sym in _base_addr_to_symbol().items()
        if sym in ("USDC", "USDbC", "DAI", "crvUSD", "EURC", "GYD", "AaveUSDC", "MONEY")
    )

    for route in inv.get("active_routes") or []:
        for addr_key, sym_key in (
            ("token0_addr", "token0"),
            ("token1_addr", "token1"),
        ):
            addr = str(route.get(addr_key) or "").strip().lower()
            sym = str(route.get(sym_key) or "").strip()
            if len(addr) != 42 or not addr.startswith("0x"):
                continue
            if addr in out and float(out[addr]) > 0:
                continue
            if addr in _base_addr_to_symbol():
                baseline = _baseline_prices().get(_base_addr_to_symbol().get(addr, ""))
                if baseline and float(baseline) > 0:
                    out[addr] = float(baseline)
                    continue
            if cfg is not None:
                for tc in cfg.tokens.values():
                    if (tc.address or "").lower() == addr:
                        px = out.get(tc.symbol) or _baseline_prices().get(tc.symbol)
                        if px and float(px) > 0:
                            out[addr] = float(px)
                        break
            if addr in stable_addrs and addr not in out:
                out[addr] = 1.0
            elif sym and sym in _baseline_prices() and addr not in out:
                out[addr] = float(_baseline_prices()[sym])

    return build_dual_key_price_map(out)


def build_dual_key_price_map(symbol_prices: Dict[str, float]) -> Dict[str, float]:
    """Merge symbol prices with lowercase address keys for runtime quoting."""
    out = dict(symbol_prices)
    for addr_lower, symbol in _base_addr_to_symbol().items():
        px = symbol_prices.get(symbol)
        if px is not None and float(px) > 0:
            out[addr_lower] = float(px)
    return out


def fetch_token_prices_usd(timeout_s: float = 5.0) -> TokenPriceResult:
    """Fetch USD prices for known Base-chain tokens.

    Attempts CoinGecko `/simple/token_price/base` with *timeout_s* seconds
    timeout.  On any error (network failure, rate limit, bad response) falls
    back to :data:`_BASELINE_PRICES` without raising.

    Returns
    -------
    TokenPriceResult
        `.prices`  — symbol → float price dict (always populated)
        `.source`  — "coingecko" or "hardcoded_fallback"
        `.stale`   — True when using fallback prices
    """
    # Start with the baseline so the result is always non-empty
    prices = dict(_baseline_prices())
    prices_by_address = build_dual_key_price_map(prices)

    try:
        import httpx  # optional hard dep — available in the project

        addrs_param = ",".join(_base_addr_to_symbol().keys())
        url = _COINGECKO_URL_TEMPLATE.format(
            platform=_COINGECKO_PLATFORM,
            addrs=addrs_param,
        )

        headers: dict[str, str] = {"Accept": "application/json"}
        api_key = _get_coingecko_api_key()
        if api_key:
            headers["x-cg-demo-api-key"] = api_key
            url = f"{url}&x_cg_demo_api_key={api_key}"
            log.debug("CoinGecko: using demo API key %s…", api_key[:8])
        else:
            log.debug("CoinGecko: no API key found — using unauthenticated request")

        with httpx.Client(timeout=httpx.Timeout(timeout_s)) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, dict) or not data:
            raise ValueError(f"CoinGecko returned empty/non-dict response: {str(data)[:120]}")

        updated: list[str] = []
        for addr_lower, symbol in _base_addr_to_symbol().items():
            entry = data.get(addr_lower) or data.get(addr_lower.lower())
            if entry and isinstance(entry, dict):
                usd_price = entry.get("usd")
                if usd_price is not None and float(usd_price) > 0:
                    prices[symbol] = float(usd_price)
                    # Aliases
                    if symbol == "WETH":
                        prices["WETH_BASE"] = float(usd_price)
                    elif symbol == "cbBTC":
                        prices["LBTC"] = float(usd_price)
                    updated.append(symbol)

        prices_by_address = build_dual_key_price_map(prices)
        log.info(
            "CoinGecko token prices fetched: updated=%s stale_symbols=%s",
            updated,
            [s for s in _baseline_prices() if s not in updated],
        )
        return TokenPriceResult(
            prices=prices,
            source="coingecko",
            stale=False,
            prices_by_address=prices_by_address,
        )

    except Exception as exc:
        log.warning(
            "CoinGecko price fetch failed (%s: %s) — using hardcoded fallback prices",
            type(exc).__name__,
            str(exc)[:200],
        )
        return TokenPriceResult(
            prices=prices,
            source="hardcoded_fallback",
            stale=True,
            prices_by_address=prices_by_address,
        )
