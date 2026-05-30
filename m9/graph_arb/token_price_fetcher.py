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
from typing import Dict
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

_BASELINE_PRICES: Dict[str, float] = {
    "WETH": 3500.0,
    "WETH_BASE": 3500.0,
    "cbBTC": 110000.0,
    "LBTC": 110000.0,
    "cbETH": 3700.0,
    "wstETH": 4200.0,
    "USDC": 1.0,
    "EURC": 1.10,
    "DAI": 1.0,
    "USDT": 1.0,
    "crvUSD": 1.0,
    "USDbC": 1.0,
    "MONEY": 1.0,
    "AERO": 0.70,
    "VIRTUAL": 0.80,
    "TOSHI": 0.0001,
    "BRETT": 0.08,
    "DEGEN": 0.005,
    "WELL": 0.04,
    "SNX": 2.5,
    "YFI": 8000.0,
    "LINK": 15.0,
    "UNI": 8.0,
    # Balancer-specific tokens (added 2026-05-29)
    "OLAS": 0.30,
    "IMO": 0.02,
    "GYD": 1.0,
    "AaveUSDC": 1.0,
}

# ---------------------------------------------------------------------------
# Token address → symbol mapping for Base chain (for CoinGecko lookup).
# Addresses are lowercase without trailing newline.
# ---------------------------------------------------------------------------

_BASE_ADDR_TO_SYMBOL: Dict[str, str] = {
    "0x4200000000000000000000000000000000000006": "WETH",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
    "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42": "EURC",
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": "cbBTC",
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631": "AERO",
    "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b": "VIRTUAL",
    "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4": "TOSHI",
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
    "0x417ac0e078398c154edfadd9ef675d30be60af93": "crvUSD",
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": "USDbC",
    "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": "cbETH",
    "0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452": "wstETH",
    "0x4ed4e862860bed51a9570b96d89af5e1b0efefed": "DEGEN",
    "0x532f27101965dd16442e59d40670faf5ebb142e4": "BRETT",
    # Balancer-specific tokens
    "0x54330d28ca3357f294334bdc454a032e7f353416": "OLAS",
    "0x5a7a2bf9ffae199f088b25837dcd7e115cf8e1bb": "IMO",
    "0xca5d8f8a8d49439357d3cf46ca2e720702f132b8": "GYD",
    "0x4ea71a20e655794051d1ee8b6e4a3269b13ccacc": "AaveUSDC",
}

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
    prices = dict(_BASELINE_PRICES)

    try:
        import httpx  # optional hard dep — available in the project

        addrs_param = ",".join(_BASE_ADDR_TO_SYMBOL.keys())
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
        for addr_lower, symbol in _BASE_ADDR_TO_SYMBOL.items():
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

        log.info(
            "CoinGecko token prices fetched: updated=%s stale_symbols=%s",
            updated,
            [s for s in _BASELINE_PRICES if s not in updated],
        )
        return TokenPriceResult(prices=prices, source="coingecko", stale=False)

    except Exception as exc:
        log.warning(
            "CoinGecko price fetch failed (%s: %s) — using hardcoded fallback prices",
            type(exc).__name__,
            str(exc)[:200],
        )
        return TokenPriceResult(prices=prices, source="hardcoded_fallback", stale=True)
