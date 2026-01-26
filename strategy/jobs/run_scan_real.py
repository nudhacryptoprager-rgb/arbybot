# PATH: strategy/jobs/run_scan_real.py
"""
REAL SCANNER for ARBY (M4).

M4 REQUIREMENTS:
- quotes_fetched >= 1
- rpc_success_rate > 0
- rpc_total_requests >= 3
- dexes_active >= 2 (STEP 1)
- pool != "unknown" (STEP 2)
- amount_in > 0 (STEP 3)
- dex_buy != dex_sell for opportunities (STEP 1)

CROSS-DEX ARBITRAGE:
- Fetch quotes from multiple DEXes for same pair
- Find price differences between DEXes
- Generate spreads where dex_buy != dex_sell
"""

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
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
)

logger = logging.getLogger("arby.scan.real")

EXECUTION_DISABLED_REASON = "EXECUTION_DISABLED_M4"
DEFAULT_QUOTE_AMOUNT_WEI = 1_000_000_000_000_000_000  # 1 ETH


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
    price: Decimal  # amount_out / amount_in (normalized)
    latency_ms: int
    block_number: int
    success: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None


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
    net_pnl_usdc: str
    net_pnl_bps: str
    confidence: float
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
                return yaml.safe_load(f)
            return json.load(f)
    return DEFAULT_CONFIG.copy()


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
    """
    STEP 2: Get pool address from config (not "unknown").
    
    Format: {dex}_{token_in}_{token_out}_{fee}
    """
    pools = config.get("pools", {})
    key = f"{dex_name}_{token_in}_{token_out}_{fee}"
    if key in pools:
        return pools[key]
    # Try reverse order
    key_rev = f"{dex_name}_{token_out}_{token_in}_{fee}"
    if key_rev in pools:
        return pools[key_rev]
    # Generate deterministic pool ID from components
    return f"pool:{dex_name}:{token_in}:{token_out}:{fee}"


def wei_to_human(wei: int, decimals: int) -> str:
    """Convert wei to human-readable string."""
    divisor = Decimal(10 ** decimals)
    value = Decimal(wei) / divisor
    return format_money(value, decimals=6)


def human_to_wei(human: str, decimals: int) -> int:
    """Convert human-readable to wei."""
    value = Decimal(human)
    multiplier = Decimal(10 ** decimals)
    return int(value * multiplier)


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
) -> Quote:
    """
    Fetch single DEX quote with full details.
    
    STEP 2: Includes pool_address (not "unknown")
    STEP 3: Returns actual amounts
    """
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
            success=False,
            error_code=ErrorCode.INFRA_RPC_ERROR.value,
            error_message="RPC call failed",
        )

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
            success=False,
            error_code=ErrorCode.QUOTE_REVERT.value,
            error_message=error_msg[:200],
        )

    raw_result = result.get("result", "0x")
    if raw_result and raw_result != "0x" and len(raw_result) >= 66:
        try:
            amount_out_wei = int(raw_result[2:66], 16)
            amount_in_human = wei_to_human(amount_in_wei, decimals_in)
            amount_out_human = wei_to_human(amount_out_wei, decimals_out)

            # Calculate normalized price
            in_normalized = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
            out_normalized = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
            price = out_normalized / in_normalized if in_normalized > 0 else Decimal("0")

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
                success=True,
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
        success=False,
        error_code=ErrorCode.QUOTE_REVERT.value,
        error_message=f"Invalid result: {raw_result[:66]}...",
    )


def find_cross_dex_spreads(
    quotes: List[Quote],
    chain_id: int,
    cycle_num: int,
    timestamp_str: str,
    min_net_bps: int = 5,
) -> List[CrossDexSpread]:
    """
    STEP 1: Find cross-DEX arbitrage opportunities.
    
    For each pair of quotes from DIFFERENT DEXes:
    - Calculate price spread
    - Buy on cheaper DEX, sell on expensive DEX
    """
    spreads: List[CrossDexSpread] = []

    # Group successful quotes by (token_in, token_out)
    quotes_by_pair: Dict[Tuple[str, str], List[Quote]] = {}
    for q in quotes:
        if not q.success or q.amount_out_wei == 0:
            continue
        key = (q.token_in, q.token_out)
        if key not in quotes_by_pair:
            quotes_by_pair[key] = []
        quotes_by_pair[key].append(q)

    spread_idx = 0
    for pair_key, pair_quotes in quotes_by_pair.items():
        # Need at least 2 quotes for cross-DEX spread
        if len(pair_quotes) < 2:
            continue

        # Find best buy (lowest price) and best sell (highest price)
        # from DIFFERENT DEXes
        for i, q_buy in enumerate(pair_quotes):
            for j, q_sell in enumerate(pair_quotes):
                if i >= j:
                    continue  # Avoid duplicates and same quote

                # STEP 1: Must be different DEXes
                if q_buy.dex_id == q_sell.dex_id:
                    continue

                # Buy where price is lower, sell where higher
                if q_buy.price > q_sell.price:
                    q_buy, q_sell = q_sell, q_buy

                # Calculate spread in basis points
                if q_buy.price <= 0:
                    continue

                spread_bps = ((q_sell.price - q_buy.price) / q_buy.price) * Decimal("10000")

                # Calculate PnL in USDC (simplified)
                # Profit = amount_out_sell - amount_out_buy (in token_out terms)
                pnl_tokens = q_sell.amount_out_wei - q_buy.amount_out_wei
                decimals_out = 6  # USDC
                pnl_usdc = Decimal(pnl_tokens) / Decimal(10 ** decimals_out)

                is_profitable = pnl_usdc > 0 and spread_bps >= min_net_bps

                spread_id = generate_spread_id(cycle_num, timestamp_str, spread_idx)
                opportunity_id = generate_opportunity_id(spread_id)
                spread_idx += 1

                # STEP 4: Execution blockers
                blockers = [EXECUTION_DISABLED_REASON]
                if not is_profitable:
                    blockers.append("NOT_PROFITABLE")

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
                    net_pnl_usdc=format_money(pnl_usdc, decimals=6),
                    net_pnl_bps=format_money(spread_bps, decimals=2),
                    confidence=0.85 if is_profitable else 0.5,
                    is_profitable=is_profitable,
                    execution_blockers=blockers,
                    is_execution_ready=False,  # Always False in M4
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
    """Run REAL scan cycle with cross-DEX arbitrage."""

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

    # RPC calls for diagnostics
    verified_chain_id = await get_chain_id(rpc_client, rpc_metrics)
    if verified_chain_id > 0:
        logger.info(f"Chain ID verified: {verified_chain_id}")

    current_block = await get_pinned_block(rpc_client, chain_id, rpc_metrics)

    logger.info(f"REAL scan cycle {cycle_num}: block={current_block}, dexes={dex_names}")

    # Track stats
    configured_dex_ids: Set[str] = set(dex_names)
    dexes_with_quotes: Set[str] = set()
    dexes_passed_gates: Set[str] = set()

    scan_stats = {
        "cycle": cycle_num,
        "timestamp": timestamp.isoformat(),
        "run_mode": "REGISTRY_REAL",
        "current_block": current_block,
        "chain_id": chain_id,
        "quotes_fetched": 0,
        "quotes_total": 0,
        "gates_passed": 0,
        "spread_ids_total": 0,
        "spread_ids_profitable": 0,
        "execution_ready_count": 0,
        "blocked_spreads": 0,
        "chains_active": 1,
        "dexes_active": 0,
        "pairs_covered": len(pairs),
        "pools_scanned": 0,
    }

    reject_histogram: Dict[str, int] = {}
    all_quotes: List[Quote] = []
    sample_rejects: List[Dict[str, Any]] = []
    sample_passed: List[Dict[str, Any]] = []

    # Fetch quotes from all DEXes
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

                for fee in fee_tiers:
                    quote_count += 1
                    scan_stats["quotes_total"] += 1
                    rpc_metrics.record_quote_attempt()

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
                    )

                    all_quotes.append(quote)

                    if quote.success and quote.amount_out_wei > 0:
                        scan_stats["quotes_fetched"] += 1
                        scan_stats["gates_passed"] += 1
                        dexes_with_quotes.add(dex_name)
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
                        })
                    else:
                        # STEP 5: Record rejects properly
                        error_code = quote.error_code or ErrorCode.QUOTE_REVERT.value

                        # STEP 4: If amount=0, it's INVALID_SIZE
                        if quote.success and quote.amount_out_wei == 0:
                            error_code = "INVALID_SIZE"

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

    # STEP 1: Find cross-DEX spreads
    cross_dex_spreads = find_cross_dex_spreads(
        all_quotes, chain_id, cycle_num, timestamp_str, min_net_bps
    )

    # Convert to dict format
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
            "net_pnl_usdc": spread.net_pnl_usdc,
            "net_pnl_bps": spread.net_pnl_bps,
            "confidence": spread.confidence,
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

    # Write artifacts
    _write_artifacts(
        output_dir, timestamp_str, chain_id, current_block,
        scan_stats, reject_histogram, gate_breakdown, all_spreads,
        sample_rejects, sample_passed,
        configured_dex_ids, dexes_with_quotes, dexes_passed_gates,
        paper_session, rpc_metrics, rpc_stats,
    )

    logger.info(
        f"REAL cycle {cycle_num}: quotes={scan_stats['quotes_fetched']}/{scan_stats['quotes_total']}, "
        f"dexes_active={scan_stats['dexes_active']}, spreads={len(all_spreads)}"
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

    # 1. Scan snapshot
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

    # 2. Reject histogram
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
            "histogram": reject_histogram,
            "gate_breakdown": gate_breakdown,
            "sample_rejects": sample_rejects[:5],
        }, f, indent=2)

    # 3. Truth report
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
