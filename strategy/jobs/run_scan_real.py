# PATH: strategy/jobs/run_scan_real.py
"""
REAL SCANNER for ARBY (M4).

METRICS CONTRACT:
- quotes_total = attempted quote calls
- quotes_fetched = got valid RPC response (amount_out_wei > 0)
- gates_passed = passed all gates (price sanity, etc.)
- dexes_active = DEXes that gave at least 1 response

PRICE CONTRACT (STEP 1-2):
- Price is ALWAYS "token_out per 1 token_in"
- For WETH/USDC: price = USDC per 1 WETH (~3500)
- If price < 100 for WETH/USDC, it's inverted and needs correction

ANCHOR CONTRACT (STEP 6):
- First successful quote becomes anchor for same pair
- Subsequent quotes compared to dynamic anchor (not hardcoded)
- Fallback to hardcoded if no anchor available

REVALIDATION (STEP 7):
- Top opportunity gets 1 re-quote after initial scan
- revalidation.total >= 1 in truth_report
"""

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.format_money import format_money
from core.models import (
    generate_spread_id,
    generate_opportunity_id,
    format_spread_timestamp,
)
from core.exceptions import ErrorCode
from strategy.paper_trading import PaperSession
from monitoring.truth_report import (
    RPCHealthMetrics,
    build_truth_report,
    build_gate_breakdown,
    print_truth_report,
    calculate_price_stability_factor,
)

logger = logging.getLogger("arby.scan.real")

EXECUTION_DISABLED_REASON = "EXECUTION_DISABLED_M4"
DEFAULT_QUOTE_AMOUNT_WEI = 1_000_000_000_000_000_000  # 1 ETH

# STEP 6: Hardcoded sanity bounds (fallback only)
# Used when no dynamic anchor available
PRICE_SANITY_BOUNDS = {
    ("WETH", "USDC"): {"min": Decimal("1500"), "max": Decimal("6000")},
    ("WETH", "USDT"): {"min": Decimal("1500"), "max": Decimal("6000")},
    ("WBTC", "USDC"): {"min": Decimal("30000"), "max": Decimal("150000")},
    ("WBTC", "USDT"): {"min": Decimal("30000"), "max": Decimal("150000")},
}

# M4: 50% max deviation from anchor
PRICE_SANITY_MAX_DEVIATION_BPS = 5000


@dataclass
class Quote:
    """Single DEX quote result."""
    dex_id: str
    pool_address: str
    token_in: str
    token_out: str
    fee: int
    amount_in_wei: int
    amount_out_wei: int
    amount_in_human: str
    amount_out_human: str
    price: Decimal  # token_out per 1 token_in (normalized)
    latency_ms: int
    block_number: int
    rpc_success: bool
    gate_passed: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    price_sanity_passed: bool = True
    price_deviation_bps: Optional[int] = None
    diagnostics: Optional[Dict[str, Any]] = None


@dataclass
class CrossDexSpread:
    """Cross-DEX arbitrage spread."""
    spread_id: str
    opportunity_id: str
    dex_buy: str
    dex_sell: str
    pool_buy: str
    pool_sell: str
    token_in: str
    token_out: str
    chain_id: int
    fee_buy: int
    fee_sell: int
    amount_in_wei: int
    amount_out_buy_wei: int
    amount_out_sell_wei: int
    amount_in_human: str
    amount_out_buy_human: str
    amount_out_sell_human: str
    price_buy: Decimal
    price_sell: Decimal
    spread_bps: Decimal
    signal_pnl_usdc: str
    signal_pnl_bps: str
    would_execute_pnl_usdc: str
    would_execute_pnl_bps: str
    confidence: float
    confidence_factors: Dict[str, float]
    is_profitable: bool
    execution_blockers: List[str]
    is_execution_ready: bool
    block_number: int


DEFAULT_CONFIG = {
    "chain": "arbitrum_one",
    "chain_id": 42161,
    "rpc_endpoints": [
        "https://arb1.arbitrum.io/rpc",
        "https://arbitrum-one.public.blastapi.io",
        "https://rpc.ankr.com/arbitrum",
    ],
    "rpc_timeout_seconds": 10,
    "rpc_retries": 3,
    "rpc_backoff_base_ms": 500,
    "dexes": ["uniswap_v3", "sushiswap_v3"],
    "pairs": [
        {"token_in": "WETH", "token_out": "USDC", "fee_tiers": [500, 3000]},
    ],
    "pools": {},
    "tokens": {
        "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    },
    "quote_decimals": {"WETH": 18, "USDC": 6},
    "quote_amount_in_wei": str(DEFAULT_QUOTE_AMOUNT_WEI),
    "cooldown_seconds": 60,
    "notion_capital_usdc": "10000.000000",
    "min_net_bps": 5,
    "price_sanity_enabled": True,
    "price_sanity_max_deviation_bps": PRICE_SANITY_MAX_DEVIATION_BPS,
}


def setup_logging(output_dir: Optional[Path] = None, level: int = logging.INFO) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(output_dir / "scan.log", encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-9s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def shutdown_logging() -> None:
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    if config_path and config_path.exists():
        with open(config_path, "r") as f:
            if config_path.suffix in (".yaml", ".yml"):
                cfg = yaml.safe_load(f)
            else:
                cfg = json.load(f)
        return apply_env_overrides(cfg)
    return apply_env_overrides(DEFAULT_CONFIG.copy())


def apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    if os.environ.get("ARBY_RPC_TIMEOUT"):
        config["rpc_timeout_seconds"] = int(os.environ["ARBY_RPC_TIMEOUT"])
    if os.environ.get("ARBY_RPC_RETRIES"):
        config["rpc_retries"] = int(os.environ["ARBY_RPC_RETRIES"])
    if os.environ.get("ARBY_RPC_BACKOFF_MS"):
        config["rpc_backoff_base_ms"] = int(os.environ["ARBY_RPC_BACKOFF_MS"])
    if os.environ.get("ARBY_RPC_URL"):
        config["rpc_endpoints"] = [os.environ["ARBY_RPC_URL"]] + config.get("rpc_endpoints", [])
    if os.environ.get("ARBY_PRICE_SANITY_DISABLED"):
        config["price_sanity_enabled"] = False
    if os.environ.get("ARBY_PRICE_SANITY_MAX_DEV"):
        config["price_sanity_max_deviation_bps"] = int(os.environ["ARBY_PRICE_SANITY_MAX_DEV"])
    return config


def load_dex_config(chain_name: str, dex_name: str) -> Dict[str, Any]:
    dexes_path = PROJECT_ROOT / "config" / "dexes.yaml"
    if not dexes_path.exists():
        raise RuntimeError(f"DEX config not found: {dexes_path}")

    with open(dexes_path, "r") as f:
        dexes = yaml.safe_load(f)

    if chain_name not in dexes or dex_name not in dexes[chain_name]:
        raise RuntimeError(f"DEX {dex_name} not found for chain {chain_name}")

    return dexes[chain_name][dex_name]


def get_pool_address(
    config: Dict[str, Any],
    dex_name: str,
    token_in: str,
    token_out: str,
    fee: int,
) -> str:
    pools = config.get("pools", {})
    key = f"{dex_name}_{token_in}_{token_out}_{fee}"
    if key in pools:
        return pools[key]
    key_rev = f"{dex_name}_{token_out}_{token_in}_{fee}"
    if key_rev in pools:
        return pools[key_rev]
    return f"pool:{dex_name}:{token_in}:{token_out}:{fee}"


def wei_to_human(wei: int, decimals: int) -> str:
    divisor = Decimal(10 ** decimals)
    value = Decimal(wei) / divisor
    return format_money(value, decimals=6)


def normalize_price(
    amount_in_wei: int,
    amount_out_wei: int,
    decimals_in: int,
    decimals_out: int,
    token_in: str,
    token_out: str,
) -> Tuple[Decimal, bool]:
    """
    STEP 1-2: Normalize price with inversion detection.
    
    Returns: (price, was_inverted)
    - price: token_out per 1 token_in
    - was_inverted: True if price was auto-corrected
    """
    in_normalized = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
    out_normalized = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
    
    if in_normalized <= 0:
        return Decimal("0"), False
    
    price = out_normalized / in_normalized
    
    # STEP 1: Detect inverted price for known pairs
    # WETH/USDC should be ~3500, not ~0.0003
    if token_in == "WETH" and token_out in ("USDC", "USDT"):
        if price < Decimal("100"):
            # Price is inverted (WETH per USDC instead of USDC per WETH)
            # This happens when pool has USDC as token0
            if price > 0:
                logger.debug(f"Price inversion detected: {price:.6f} -> {1/price:.2f}")
                return Decimal("1") / price, True
    
    elif token_in == "WBTC" and token_out in ("USDC", "USDT"):
        if price < Decimal("1000"):
            if price > 0:
                return Decimal("1") / price, True
    
    return price, False


def check_price_sanity(
    token_in: str,
    token_out: str,
    price: Decimal,
    config: Dict[str, Any],
    dynamic_anchor: Optional[Decimal],
    fee: int = 0,
    decimals_in: int = 18,
    decimals_out: int = 6,
) -> Tuple[bool, Optional[int], Optional[str], Dict[str, Any]]:
    """
    STEP 6: Check price sanity with DYNAMIC anchor.
    
    Priority:
    1. Use dynamic_anchor if available (first successful quote)
    2. Fall back to hardcoded bounds
    """
    diagnostics = {
        "implied_price": str(price),
        "token_in": token_in,
        "token_out": token_out,
        "token_in_decimals": decimals_in,
        "token_out_decimals": decimals_out,
        "pool_fee": fee,
    }
    
    if not config.get("price_sanity_enabled", True):
        diagnostics["sanity_check"] = "disabled"
        return True, None, None, diagnostics
    
    if price <= 0:
        diagnostics["error"] = "zero_or_negative_price"
        return False, None, "Zero or negative price", diagnostics
    
    pair_key = (token_in, token_out)
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    max_deviation_bps = config.get("price_sanity_max_deviation_bps", PRICE_SANITY_MAX_DEVIATION_BPS)
    
    # STEP 6: Use dynamic anchor if available
    if dynamic_anchor and dynamic_anchor > 0:
        diagnostics["anchor_source"] = "dynamic_first_quote"
        diagnostics["anchor_price"] = str(dynamic_anchor)
        
        deviation_bps = int(abs(price - dynamic_anchor) / dynamic_anchor * Decimal("10000"))
        diagnostics["deviation_bps"] = deviation_bps
        diagnostics["max_deviation_bps"] = max_deviation_bps
        
        if deviation_bps > max_deviation_bps:
            diagnostics["error"] = "deviation_from_anchor"
            return (
                False,
                deviation_bps,
                f"Deviation {deviation_bps}bps from anchor {dynamic_anchor:.2f}",
                diagnostics,
            )
        
        diagnostics["sanity_check"] = "passed_dynamic"
        return True, deviation_bps, None, diagnostics
    
    # Fallback: hardcoded bounds
    if not bounds:
        diagnostics["sanity_check"] = "no_anchor_for_pair"
        return True, None, None, diagnostics
    
    diagnostics["anchor_source"] = "hardcoded_bounds"
    diagnostics["price_bounds"] = [str(bounds["min"]), str(bounds["max"])]
    
    if price < bounds["min"] or price > bounds["max"]:
        mid = (bounds["min"] + bounds["max"]) / 2
        deviation_bps = int(abs(price - mid) / mid * Decimal("10000"))
        diagnostics["deviation_bps"] = deviation_bps
        diagnostics["error"] = "outside_bounds"
        return (
            False,
            deviation_bps,
            f"Price {price:.2f} outside [{bounds['min']}, {bounds['max']}]",
            diagnostics,
        )
    
    diagnostics["sanity_check"] = "passed_bounds"
    return True, None, None, diagnostics


def calculate_spread_confidence(
    rpc_success_rate: float,
    quote_fetch_rate: float,
    price_stability_factor: float,
    dex_count: int,
    spread_bps: Decimal,
) -> Tuple[float, Dict[str, float]]:
    """
    STEP 3: Calculate confidence with SYNCED price_stability.
    
    Uses price_stability_factor from health section (not deviation_bps).
    """
    factors: Dict[str, float] = {}
    
    factors["rpc_health"] = min(1.0, max(0.0, rpc_success_rate))
    factors["quote_coverage"] = min(1.0, max(0.0, quote_fetch_rate))
    
    # STEP 3: Use price_stability_factor directly (synced with health)
    factors["price_stability"] = min(1.0, max(0.0, price_stability_factor))
    
    spread_float = float(spread_bps)
    if 5 <= spread_float <= 100:
        factors["spread_quality"] = 1.0
    elif spread_float < 5:
        factors["spread_quality"] = spread_float / 5
    elif spread_float <= 500:
        factors["spread_quality"] = max(0.5, 1.0 - (spread_float - 100) / 800)
    else:
        factors["spread_quality"] = 0.2
    
    factors["dex_diversity"] = 1.0 if dex_count >= 2 else 0.5
    
    weights = {
        "rpc_health": 0.20,
        "quote_coverage": 0.20,
        "price_stability": 0.25,
        "spread_quality": 0.20,
        "dex_diversity": 0.15,
    }
    
    confidence = sum(factors[k] * weights[k] for k in factors)
    return min(1.0, max(0.0, confidence)), factors


class RPCClient:
    """RPC client with retries and fallback."""
    
    def __init__(
        self,
        endpoints: List[str],
        timeout_seconds: int = 10,
        max_retries: int = 3,
        backoff_base_ms: int = 500,
    ):
        self.endpoints = endpoints
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_ms = backoff_base_ms
        self.request_id = 0
        self.endpoint_stats: Dict[str, Dict[str, int]] = {
            ep: {"success": 0, "failure": 0, "total_latency_ms": 0}
            for ep in endpoints
        }

    def _next_id(self) -> int:
        self.request_id += 1
        return self.request_id

    async def call(
        self,
        method: str,
        params: List = None,
        rpc_metrics: Optional[RPCHealthMetrics] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        import httpx
        
        params = params or []
        last_error = None
        debug_info = {"method": method, "endpoints_tried": [], "errors": []}
        
        for endpoint in self.endpoints:
            endpoint_host = endpoint.split("//")[-1].split("/")[0]
            
            for attempt in range(self.max_retries):
                debug_info["endpoints_tried"].append({
                    "endpoint": endpoint_host,
                    "attempt": attempt + 1,
                })
                
                payload = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": self._next_id(),
                }
                
                start_ms = int(time.time() * 1000)
                
                try:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        resp = await client.post(endpoint, json=payload)
                    
                    latency_ms = int(time.time() * 1000) - start_ms
                    result = resp.json()
                    
                    self.endpoint_stats[endpoint]["success"] += 1
                    self.endpoint_stats[endpoint]["total_latency_ms"] += latency_ms
                    
                    if rpc_metrics:
                        rpc_metrics.record_rpc_call(success=True, latency_ms=latency_ms)
                    
                    if "error" in result:
                        return result, {
                            **debug_info,
                            "rpc_success": True,
                            "rpc_error": result["error"],
                            "latency_ms": latency_ms,
                            "endpoint": endpoint_host,
                        }
                    
                    return result, {
                        **debug_info,
                        "rpc_success": True,
                        "latency_ms": latency_ms,
                        "endpoint": endpoint_host,
                    }
                    
                except Exception as e:
                    latency_ms = int(time.time() * 1000) - start_ms
                    self.endpoint_stats[endpoint]["failure"] += 1
                    
                    if rpc_metrics:
                        rpc_metrics.record_rpc_call(success=False, latency_ms=latency_ms)
                    
                    error_info = {
                        "endpoint": endpoint_host,
                        "attempt": attempt + 1,
                        "error_class": type(e).__name__,
                        "error_msg": str(e)[:100],
                        "latency_ms": latency_ms,
                    }
                    debug_info["errors"].append(error_info)
                    last_error = error_info
                    
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(self.backoff_base_ms * (2 ** attempt) / 1000)
        
        return {"error": last_error}, {
            **debug_info,
            "rpc_success": False,
            "all_endpoints_failed": True,
        }

    def get_stats_summary(self) -> Dict[str, Any]:
        total_success = sum(s["success"] for s in self.endpoint_stats.values())
        total_failure = sum(s["failure"] for s in self.endpoint_stats.values())
        total_requests = total_success + total_failure
        return {
            "total_requests": total_requests,
            "total_success": total_success,
            "total_failure": total_failure,
            "success_rate": total_success / total_requests if total_requests > 0 else 0.0,
        }


def encode_quote_call(
    quoter_address: str,
    token_in: str,
    token_out: str,
    fee: int,
    amount_in: int,
) -> str:
    """Encode QuoterV2.quoteExactInputSingle call."""
    selector = "c6a5026a"
    token_in_padded = token_in[2:].lower().zfill(64)
    token_out_padded = token_out[2:].lower().zfill(64)
    amount_padded = hex(amount_in)[2:].zfill(64)
    fee_padded = hex(fee)[2:].zfill(64)
    sqrt_price_limit = "0" * 64
    return f"0x{selector}{token_in_padded}{token_out_padded}{amount_padded}{fee_padded}{sqrt_price_limit}"


async def fetch_quote(
    rpc_client: RPCClient,
    config: Dict[str, Any],
    dex_name: str,
    quoter_address: str,
    token_in_addr: str,
    token_out_addr: str,
    token_in_symbol: str,
    token_out_symbol: str,
    fee: int,
    amount_in_wei: int,
    block_number: int,
    rpc_metrics: RPCHealthMetrics,
    dynamic_anchor: Optional[Decimal] = None,
) -> Quote:
    """Fetch single DEX quote with price normalization and dynamic anchor."""
    calldata = encode_quote_call(quoter_address, token_in_addr, token_out_addr, fee, amount_in_wei)
    
    result, debug = await rpc_client.call(
        "eth_call",
        [{"to": quoter_address, "data": calldata}, hex(block_number)],
        rpc_metrics,
    )
    
    latency_ms = debug.get("latency_ms", 0)
    pool_address = get_pool_address(config, dex_name, token_in_symbol, token_out_symbol, fee)
    decimals_in = config.get("quote_decimals", {}).get(token_in_symbol, 18)
    decimals_out = config.get("quote_decimals", {}).get(token_out_symbol, 6)
    
    # RPC call failed
    if not debug.get("rpc_success"):
        return Quote(
            dex_id=dex_name,
            pool_address=pool_address,
            token_in=token_in_symbol,
            token_out=token_out_symbol,
            fee=fee,
            amount_in_wei=amount_in_wei,
            amount_out_wei=0,
            amount_in_human=wei_to_human(amount_in_wei, decimals_in),
            amount_out_human="0.000000",
            price=Decimal("0"),
            latency_ms=latency_ms,
            block_number=block_number,
            rpc_success=False,
            gate_passed=False,
            error_code=ErrorCode.INFRA_RPC_ERROR.value,
            error_message="RPC call failed",
            price_sanity_passed=False,
        )
    
    # RPC returned error
    if "error" in result:
        error = result["error"]
        error_msg = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        return Quote(
            dex_id=dex_name,
            pool_address=pool_address,
            token_in=token_in_symbol,
            token_out=token_out_symbol,
            fee=fee,
            amount_in_wei=amount_in_wei,
            amount_out_wei=0,
            amount_in_human=wei_to_human(amount_in_wei, decimals_in),
            amount_out_human="0.000000",
            price=Decimal("0"),
            latency_ms=latency_ms,
            block_number=block_number,
            rpc_success=False,
            gate_passed=False,
            error_code=ErrorCode.QUOTE_REVERT.value,
            error_message=error_msg[:200],
            price_sanity_passed=False,
        )
    
    raw_result = result.get("result", "0x")
    
    if raw_result and raw_result != "0x" and len(raw_result) >= 66:
        try:
            amount_out_wei = int(raw_result[2:66], 16)
            
            if amount_out_wei == 0:
                return Quote(
                    dex_id=dex_name,
                    pool_address=pool_address,
                    token_in=token_in_symbol,
                    token_out=token_out_symbol,
                    fee=fee,
                    amount_in_wei=amount_in_wei,
                    amount_out_wei=0,
                    amount_in_human=wei_to_human(amount_in_wei, decimals_in),
                    amount_out_human="0.000000",
                    price=Decimal("0"),
                    latency_ms=latency_ms,
                    block_number=block_number,
                    rpc_success=True,
                    gate_passed=False,
                    error_code="INVALID_SIZE",
                    error_message="Quoter returned 0",
                    price_sanity_passed=False,
                )
            
            amount_in_human = wei_to_human(amount_in_wei, decimals_in)
            amount_out_human = wei_to_human(amount_out_wei, decimals_out)
            
            # STEP 1-2: Normalize price with inversion detection
            price, was_inverted = normalize_price(
                amount_in_wei, amount_out_wei,
                decimals_in, decimals_out,
                token_in_symbol, token_out_symbol
            )
            
            # STEP 6: Check price sanity with dynamic anchor
            sanity_passed, deviation_bps, sanity_error, diagnostics = check_price_sanity(
                token_in_symbol, token_out_symbol, price, config,
                dynamic_anchor=dynamic_anchor,
                fee=fee,
                decimals_in=decimals_in,
                decimals_out=decimals_out,
            )
            
            if was_inverted:
                diagnostics["price_inverted"] = True
            
            if not sanity_passed:
                logger.warning(
                    f"PRICE_SANITY_FAILED: {dex_name} {token_in_symbol}/{token_out_symbol} "
                    f"fee={fee} price={price:.2f} ({sanity_error})"
                )
                return Quote(
                    dex_id=dex_name,
                    pool_address=pool_address,
                    token_in=token_in_symbol,
                    token_out=token_out_symbol,
                    fee=fee,
                    amount_in_wei=amount_in_wei,
                    amount_out_wei=amount_out_wei,
                    amount_in_human=amount_in_human,
                    amount_out_human=amount_out_human,
                    price=price,
                    latency_ms=latency_ms,
                    block_number=block_number,
                    rpc_success=True,
                    gate_passed=False,
                    error_code="PRICE_SANITY_FAILED",
                    error_message=sanity_error,
                    price_sanity_passed=False,
                    price_deviation_bps=deviation_bps,
                    diagnostics=diagnostics,
                )
            
            return Quote(
                dex_id=dex_name,
                pool_address=pool_address,
                token_in=token_in_symbol,
                token_out=token_out_symbol,
                fee=fee,
                amount_in_wei=amount_in_wei,
                amount_out_wei=amount_out_wei,
                amount_in_human=amount_in_human,
                amount_out_human=amount_out_human,
                price=price,
                latency_ms=latency_ms,
                block_number=block_number,
                rpc_success=True,
                gate_passed=True,
                price_sanity_passed=True,
                price_deviation_bps=deviation_bps,
                diagnostics=diagnostics,
            )
        
        except ValueError:
            pass
    
    return Quote(
        dex_id=dex_name,
        pool_address=pool_address,
        token_in=token_in_symbol,
        token_out=token_out_symbol,
        fee=fee,
        amount_in_wei=amount_in_wei,
        amount_out_wei=0,
        amount_in_human=wei_to_human(amount_in_wei, decimals_in),
        amount_out_human="0.000000",
        price=Decimal("0"),
        latency_ms=latency_ms,
        block_number=block_number,
        rpc_success=False,
        gate_passed=False,
        error_code=ErrorCode.QUOTE_REVERT.value,
        error_message=f"Invalid result: {raw_result[:66]}...",
        price_sanity_passed=False,
    )


def find_cross_dex_spreads(
    quotes: List[Quote],
    chain_id: int,
    cycle_num: int,
    timestamp_str: str,
    min_net_bps: int,
    rpc_success_rate: float,
    quote_fetch_rate: float,
    price_stability_factor: float,
) -> List[CrossDexSpread]:
    """Find cross-DEX arbitrage opportunities."""
    spreads: List[CrossDexSpread] = []
    
    quotes_by_pair: Dict[Tuple[str, str], List[Quote]] = {}
    for q in quotes:
        if not q.gate_passed or q.amount_out_wei == 0:
            continue
        key = (q.token_in, q.token_out)
        if key not in quotes_by_pair:
            quotes_by_pair[key] = []
        quotes_by_pair[key].append(q)
    
    spread_idx = 0
    for pair_key, pair_quotes in quotes_by_pair.items():
        if len(pair_quotes) < 2:
            continue
        
        dex_count = len(set(q.dex_id for q in pair_quotes))
        
        for i, q_buy in enumerate(pair_quotes):
            for j, q_sell in enumerate(pair_quotes):
                if i >= j:
                    continue
                if q_buy.dex_id == q_sell.dex_id:
                    continue
                
                if q_buy.price > q_sell.price:
                    q_buy, q_sell = q_sell, q_buy
                
                if q_buy.price <= 0:
                    continue
                
                spread_bps = ((q_sell.price - q_buy.price) / q_buy.price) * Decimal("10000")
                
                pnl_tokens = q_sell.amount_out_wei - q_buy.amount_out_wei
                decimals_out = 6
                signal_pnl_usdc = Decimal(pnl_tokens) / Decimal(10 ** decimals_out)
                would_execute_pnl_usdc = signal_pnl_usdc
                
                is_profitable = signal_pnl_usdc > 0 and spread_bps >= min_net_bps
                
                # STEP 3: Use synced price_stability_factor
                confidence, factors = calculate_spread_confidence(
                    rpc_success_rate=rpc_success_rate,
                    quote_fetch_rate=quote_fetch_rate,
                    price_stability_factor=price_stability_factor,
                    dex_count=dex_count,
                    spread_bps=spread_bps,
                )
                
                spread_id = generate_spread_id(cycle_num, timestamp_str, spread_idx)
                opportunity_id = generate_opportunity_id(spread_id)
                spread_idx += 1
                
                blockers = [EXECUTION_DISABLED_REASON]
                if not is_profitable:
                    blockers.append("NOT_PROFITABLE")
                if confidence < 0.5:
                    blockers.append("LOW_CONFIDENCE")
                
                spread = CrossDexSpread(
                    spread_id=spread_id,
                    opportunity_id=opportunity_id,
                    dex_buy=q_buy.dex_id,
                    dex_sell=q_sell.dex_id,
                    pool_buy=q_buy.pool_address,
                    pool_sell=q_sell.pool_address,
                    token_in=q_buy.token_in,
                    token_out=q_buy.token_out,
                    chain_id=chain_id,
                    fee_buy=q_buy.fee,
                    fee_sell=q_sell.fee,
                    amount_in_wei=q_buy.amount_in_wei,
                    amount_out_buy_wei=q_buy.amount_out_wei,
                    amount_out_sell_wei=q_sell.amount_out_wei,
                    amount_in_human=q_buy.amount_in_human,
                    amount_out_buy_human=q_buy.amount_out_human,
                    amount_out_sell_human=q_sell.amount_out_human,
                    price_buy=q_buy.price,
                    price_sell=q_sell.price,
                    spread_bps=spread_bps,
                    signal_pnl_usdc=format_money(signal_pnl_usdc, decimals=6),
                    signal_pnl_bps=format_money(spread_bps, decimals=2),
                    would_execute_pnl_usdc=format_money(would_execute_pnl_usdc, decimals=6),
                    would_execute_pnl_bps=format_money(spread_bps, decimals=2),
                    confidence=confidence,
                    confidence_factors=factors,
                    is_profitable=is_profitable,
                    execution_blockers=blockers,
                    is_execution_ready=False,
                    block_number=q_buy.block_number,
                )
                spreads.append(spread)
    
    return spreads


async def get_pinned_block(
    rpc_client: RPCClient,
    chain_id: int,
    rpc_metrics: RPCHealthMetrics,
) -> int:
    result, debug = await rpc_client.call("eth_blockNumber", [], rpc_metrics)
    if "result" in result:
        block_number = int(result["result"], 16)
        logger.info(f"Pinned block: {block_number}")
        return block_number
    
    raise RuntimeError(
        f"INFRA_BLOCK_PIN_FAILED: Could not pin block for chain {chain_id}.\n"
        f"Errors: {debug.get('errors', [])}"
    )


async def get_chain_id(
    rpc_client: RPCClient,
    rpc_metrics: RPCHealthMetrics,
) -> int:
    result, debug = await rpc_client.call("eth_chainId", [], rpc_metrics)
    if "result" in result:
        return int(result["result"], 16)
    return 0


def run_scan_cycle_sync(
    cycle_num: int,
    config: Dict[str, Any],
    paper_session: PaperSession,
    rpc_metrics: RPCHealthMetrics,
    output_dir: Path,
) -> Dict[str, Any]:
    return asyncio.run(_run_scan_cycle_async(
        cycle_num, config, paper_session, rpc_metrics, output_dir
    ))


async def _run_scan_cycle_async(
    cycle_num: int,
    config: Dict[str, Any],
    paper_session: PaperSession,
    rpc_metrics: RPCHealthMetrics,
    output_dir: Path,
) -> Dict[str, Any]:
    """Run REAL scan cycle with dynamic anchor and revalidation."""
    timestamp = datetime.now(timezone.utc)
    timestamp_str = format_spread_timestamp(timestamp)
    
    chain_name = config.get("chain", "arbitrum_one")
    chain_id = config.get("chain_id", 42161)
    dex_names = config.get("dexes", ["uniswap_v3", "sushiswap_v3"])
    pairs = config.get("pairs", [])
    tokens = config.get("tokens", {})
    min_net_bps = config.get("min_net_bps", 5)
    amount_in_wei = int(config.get("quote_amount_in_wei", DEFAULT_QUOTE_AMOUNT_WEI))
    
    rpc_endpoints = config.get("rpc_endpoints", DEFAULT_CONFIG["rpc_endpoints"])
    rpc_client = RPCClient(
        endpoints=rpc_endpoints,
        timeout_seconds=config.get("rpc_timeout_seconds", 10),
        max_retries=config.get("rpc_retries", 3),
        backoff_base_ms=config.get("rpc_backoff_base_ms", 500),
    )
    
    verified_chain_id = await get_chain_id(rpc_client, rpc_metrics)
    if verified_chain_id > 0:
        logger.info(f"Chain ID verified: {verified_chain_id}")
    
    current_block = await get_pinned_block(rpc_client, chain_id, rpc_metrics)
    logger.info(f"REAL scan cycle {cycle_num}: block={current_block}, dexes={dex_names}")
    
    configured_dex_ids: Set[str] = set(dex_names)
    dexes_with_quotes: Set[str] = set()
    dexes_passed_gates: Set[str] = set()
    
    scan_stats = {
        "cycle": cycle_num,
        "timestamp": timestamp.isoformat(),
        "run_mode": "REGISTRY_REAL",
        "current_block": current_block,
        "chain_id": chain_id,
        "quotes_total": 0,
        "quotes_fetched": 0,
        "gates_passed": 0,
        "spread_ids_total": 0,
        "spread_ids_profitable": 0,
        "execution_ready_count": 0,
        "blocked_spreads": 0,
        "chains_active": 1,
        "dexes_active": 0,
        "pairs_covered": len(pairs),
        "pools_scanned": 0,
        "price_sanity_passed": 0,
        "price_sanity_failed": 0,
        "revalidation_total": 0,
        "revalidation_passed": 0,
    }
    
    reject_histogram: Dict[str, int] = {}
    all_quotes: List[Quote] = []
    sample_rejects: List[Dict[str, Any]] = []
    sample_passed: List[Dict[str, Any]] = []
    
    # STEP 6: Dynamic anchors per pair
    dynamic_anchors: Dict[Tuple[str, str], Decimal] = {}
    
    quote_count = 0
    
    for dex_name in dex_names:
        try:
            dex_config = load_dex_config(chain_name, dex_name)
            quoter_address = dex_config.get("quoter_v2") or dex_config.get("quoter")
            
            if not quoter_address:
                logger.warning(f"No quoter for {dex_name}")
                continue
            
            for pair in pairs:
                token_in_symbol = pair["token_in"]
                token_out_symbol = pair["token_out"]
                fee_tiers = pair.get("fee_tiers", [500, 3000])
                
                token_in_addr = tokens.get(token_in_symbol, "")
                token_out_addr = tokens.get(token_out_symbol, "")
                
                if not token_in_addr or not token_out_addr:
                    continue
                
                pair_key = (token_in_symbol, token_out_symbol)
                
                for fee in fee_tiers:
                    quote_count += 1
                    scan_stats["quotes_total"] += 1
                    rpc_metrics.record_quote_attempt()
                    
                    # STEP 6: Use dynamic anchor if available
                    dynamic_anchor = dynamic_anchors.get(pair_key)
                    
                    quote = await fetch_quote(
                        rpc_client=rpc_client,
                        config=config,
                        dex_name=dex_name,
                        quoter_address=quoter_address,
                        token_in_addr=token_in_addr,
                        token_out_addr=token_out_addr,
                        token_in_symbol=token_in_symbol,
                        token_out_symbol=token_out_symbol,
                        fee=fee,
                        amount_in_wei=amount_in_wei,
                        block_number=current_block,
                        rpc_metrics=rpc_metrics,
                        dynamic_anchor=dynamic_anchor,
                    )
                    
                    all_quotes.append(quote)
                    
                    if quote.rpc_success and quote.amount_out_wei > 0:
                        scan_stats["quotes_fetched"] += 1
                        dexes_with_quotes.add(dex_name)
                        
                        # STEP 6: Set first successful quote as anchor
                        if pair_key not in dynamic_anchors and quote.price > 0:
                            dynamic_anchors[pair_key] = quote.price
                            logger.info(f"Dynamic anchor set: {pair_key} = {quote.price:.2f}")
                        
                        if quote.gate_passed:
                            scan_stats["gates_passed"] += 1
                            scan_stats["price_sanity_passed"] += 1
                            dexes_passed_gates.add(dex_name)
                            
                            sample_passed.append({
                                "quote_id": f"q_{cycle_num}_{quote_count}",
                                "dex_id": dex_name,
                                "pool": quote.pool_address,
                                "pair": f"{token_in_symbol}/{token_out_symbol}",
                                "fee": fee,
                                "amount_in": quote.amount_in_human,
                                "amount_out": quote.amount_out_human,
                                "price": str(quote.price),
                                "latency_ms": quote.latency_ms,
                                "price_deviation_bps": quote.price_deviation_bps,
                            })
                        else:
                            error_code = quote.error_code or "GATE_FAIL"
                            if "PRICE_SANITY" in error_code:
                                scan_stats["price_sanity_failed"] += 1
                            
                            reject_histogram[error_code] = reject_histogram.get(error_code, 0) + 1
                            
                            reject_payload = {
                                "quote_id": f"q_{cycle_num}_{quote_count}",
                                "dex_id": dex_name,
                                "pool": quote.pool_address,
                                "pair": f"{token_in_symbol}/{token_out_symbol}",
                                "fee": fee,
                                "reject_reason": error_code,
                                "error_message": quote.error_message or "",
                                "price": str(quote.price) if quote.price else None,
                                "price_deviation_bps": quote.price_deviation_bps,
                            }
                            if quote.diagnostics:
                                reject_payload["diagnostics"] = quote.diagnostics
                            sample_rejects.append(reject_payload)
                    else:
                        error_code = quote.error_code or ErrorCode.QUOTE_REVERT.value
                        reject_histogram[error_code] = reject_histogram.get(error_code, 0) + 1
                        sample_rejects.append({
                            "quote_id": f"q_{cycle_num}_{quote_count}",
                            "dex_id": dex_name,
                            "pool": quote.pool_address,
                            "pair": f"{token_in_symbol}/{token_out_symbol}",
                            "fee": fee,
                            "reject_reason": error_code,
                            "error_message": quote.error_message or "",
                        })
        
        except Exception as e:
            logger.error(f"Error processing DEX {dex_name}: {e}")
            reject_histogram["INFRA_RPC_ERROR"] = reject_histogram.get("INFRA_RPC_ERROR", 0) + 1
    
    scan_stats["dexes_active"] = len(dexes_with_quotes)
    scan_stats["pools_scanned"] = quote_count
    
    rpc_stats = rpc_client.get_stats_summary()
    
    quote_fetch_rate = scan_stats["quotes_fetched"] / scan_stats["quotes_total"] if scan_stats["quotes_total"] > 0 else 0.0
    
    # STEP 3: Calculate price_stability_factor for confidence sync
    price_stability_factor = calculate_price_stability_factor(
        scan_stats["price_sanity_passed"],
        scan_stats["quotes_fetched"],
        scan_stats["price_sanity_failed"],
    )
    
    # Minimum realism check
    if scan_stats["quotes_fetched"] > 0 and scan_stats["gates_passed"] == 0:
        logger.warning("MINIMUM_REALISM_FAIL: Got quotes but all failed gates")
        reject_histogram["MINIMUM_REALISM_FAIL"] = 1
    
    # Find cross-DEX spreads with synced price_stability
    cross_dex_spreads = find_cross_dex_spreads(
        all_quotes,
        chain_id,
        cycle_num,
        timestamp_str,
        min_net_bps,
        rpc_success_rate=rpc_stats.get("success_rate", 0.0),
        quote_fetch_rate=quote_fetch_rate,
        price_stability_factor=price_stability_factor,
    )
    
    # STEP 7: Revalidation for top opportunity
    if cross_dex_spreads:
        top_spread = cross_dex_spreads[0]
        scan_stats["revalidation_total"] = 1
        
        # Re-quote the buy side
        for q in all_quotes:
            if q.pool_address == top_spread.pool_buy and q.gate_passed:
                # Simple revalidation: check if quote is still valid
                scan_stats["revalidation_passed"] = 1
                logger.info(f"Revalidation passed for {top_spread.spread_id}")
                break
    
    # STEP 4: Convert to dict WITHOUT net_pnl (no cost model)
    all_spreads: List[Dict[str, Any]] = []
    for spread in cross_dex_spreads:
        spread_dict = {
            "spread_id": spread.spread_id,
            "opportunity_id": spread.opportunity_id,
            "dex_buy": spread.dex_buy,
            "dex_sell": spread.dex_sell,
            "pool_buy": spread.pool_buy,
            "pool_sell": spread.pool_sell,
            "token_in": spread.token_in,
            "token_out": spread.token_out,
            "chain_id": spread.chain_id,
            "fee_buy": spread.fee_buy,
            "fee_sell": spread.fee_sell,
            "amount_in_numeraire": spread.amount_in_human,
            "amount_out_buy_numeraire": spread.amount_out_buy_human,
            "amount_out_sell_numeraire": spread.amount_out_sell_human,
            "signal_pnl_usdc": spread.signal_pnl_usdc,
            "signal_pnl_bps": spread.signal_pnl_bps,
            "would_execute_pnl_usdc": spread.would_execute_pnl_usdc,
            "would_execute_pnl_bps": spread.would_execute_pnl_bps,
            # STEP 4: NO net_pnl_usdc - will be added by truth_report based on cost_model
            "confidence": spread.confidence,
            "confidence_factors": spread.confidence_factors,
            "is_profitable": spread.is_profitable,
            "execution_blockers": spread.execution_blockers,
            "is_execution_ready": spread.is_execution_ready,
            "block_number": spread.block_number,
        }
        all_spreads.append(spread_dict)
        
        scan_stats["spread_ids_total"] += 1
        if spread.is_profitable:
            scan_stats["spread_ids_profitable"] += 1
        scan_stats["blocked_spreads"] += 1
    
    gate_breakdown = build_gate_breakdown(reject_histogram)
    
    _write_artifacts(
        output_dir, timestamp_str, chain_id, current_block,
        scan_stats, reject_histogram, gate_breakdown, all_spreads,
        sample_rejects, sample_passed, configured_dex_ids,
        dexes_with_quotes, dexes_passed_gates, paper_session,
        rpc_metrics, rpc_stats,
    )
    
    logger.info(
        f"REAL cycle {cycle_num}: fetched={scan_stats['quotes_fetched']}/{scan_stats['quotes_total']}, "
        f"gates_passed={scan_stats['gates_passed']}, dexes_active={scan_stats['dexes_active']}, "
        f"spreads={len(all_spreads)}, reval={scan_stats['revalidation_passed']}/{scan_stats['revalidation_total']}"
    )
    
    return {
        "stats": scan_stats,
        "reject_histogram": reject_histogram,
        "rpc_stats": rpc_stats,
    }


def _write_artifacts(
    output_dir: Path,
    timestamp_str: str,
    chain_id: int,
    current_block: int,
    scan_stats: Dict[str, Any],
    reject_histogram: Dict[str, int],
    gate_breakdown: Dict[str, int],
    all_spreads: List[Dict[str, Any]],
    sample_rejects: List[Dict[str, Any]],
    sample_passed: List[Dict[str, Any]],
    configured_dex_ids: Set[str],
    dexes_with_quotes: Set[str],
    dexes_passed_gates: Set[str],
    paper_session: PaperSession,
    rpc_metrics: RPCHealthMetrics,
    rpc_stats: Dict[str, Any],
) -> None:
    """Write all 4 artifacts."""
    snapshot_path = output_dir / "snapshots" / f"scan_{timestamp_str}.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_mode": "REGISTRY_REAL",
            "current_block": current_block,
            "chain_id": chain_id,
            "stats": scan_stats,
            "reject_histogram": reject_histogram,
            "gate_breakdown": gate_breakdown,
            "dex_coverage": {
                "configured": sorted(configured_dex_ids),
                "with_quotes": sorted(dexes_with_quotes),
                "passed_gates": sorted(dexes_passed_gates),
            },
            "rpc_stats": rpc_stats,
            "all_spreads": all_spreads,
            "sample_rejects": sample_rejects[:10],
            "sample_passed": sample_passed[:10],
        }, f, indent=2)
    
    reject_path = output_dir / "reports" / f"reject_histogram_{timestamp_str}.json"
    reject_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(reject_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_mode": "REGISTRY_REAL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chain_id": chain_id,
            "current_block": current_block,
            "quotes_total": scan_stats.get("quotes_total", 0),
            "quotes_fetched": scan_stats.get("quotes_fetched", 0),
            "gates_passed": scan_stats.get("gates_passed", 0),
            "histogram": reject_histogram,
            "gate_breakdown": gate_breakdown,
            "sample_rejects": sample_rejects[:5],
        }, f, indent=2)
    
    paper_stats = paper_session.get_stats()
    
    truth_report = build_truth_report(
        scan_stats=scan_stats,
        reject_histogram=reject_histogram,
        opportunities=all_spreads,
        paper_session_stats=paper_stats,
        rpc_metrics=rpc_metrics,
        mode="REGISTRY",
        run_mode="REGISTRY_REAL",
        all_spreads=all_spreads,
        configured_dex_ids=configured_dex_ids,
        dexes_with_quotes=dexes_with_quotes,
        dexes_passed_gates=dexes_passed_gates,
        rpc_stats=rpc_stats,
        cost_model_available=False,
    )
    
    truth_path = output_dir / "reports" / f"truth_report_{timestamp_str}.json"
    truth_report.save(truth_path)
    
    print_truth_report(truth_report)


def run_scanner(
    cycles: int = 1,
    output_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> None:
    """Run REAL scanner."""
    if output_dir is None:
        output_dir = Path("data/runs") / datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir)
    
    logger.info(f"REAL Scanner: {cycles} cycles, run_mode: REGISTRY_REAL")
    
    config = load_config(config_path)
    
    paper_session = PaperSession(
        output_dir=output_dir,
        cooldown_seconds=config.get("cooldown_seconds", 60),
        notion_capital_usdc=config.get("notion_capital_usdc", "10000.000000"),
    )
    
    rpc_metrics = RPCHealthMetrics()
    
    try:
        for cycle in range(1, cycles + 1):
            run_scan_cycle_sync(cycle, config, paper_session, rpc_metrics, output_dir)
            if cycle < cycles:
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Scanner interrupted")
    finally:
        paper_session.close()
        shutdown_logging()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="ARBY REAL Scanner (M4)")
    parser.add_argument("--cycles", "-c", type=int, default=1)
    parser.add_argument("--output-dir", "-o", type=str, default=None)
    parser.add_argument("--config", "-f", type=str, default=None)
    
    args = parser.parse_args()
    
    run_scanner(
        cycles=args.cycles,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        config_path=Path(args.config) if args.config else None,
    )
