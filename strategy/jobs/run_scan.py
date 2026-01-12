#!/usr/bin/env python3
"""
strategy/jobs/run_scan.py - CLI entrypoint for opportunity scanning.

Features:
- Block pinning (M1.1)
- Quote fetching via Uniswap V3 QuoterV2
- DEX gating (verified_for_quoting)
- Quote gates: gas, ticks, slippage, monotonicity
- Structured metrics: attempted → fetched → passed_gates
- Raw spread detection between DEXes

Usage:
    python -m strategy.jobs.run_scan --chain arbitrum_one --once
    python -m strategy.jobs.run_scan --chain all --interval 5000
"""

import asyncio
import json
import signal
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import click
import yaml

from core.logging import get_logger, setup_logging, set_global_context
from core.exceptions import ErrorCode, ArbyError, QuoteError, InfraError
from core.models import Token, Pool, Quote
from core.constants import DexType, PoolStatus
from chains.providers import RPCProvider, register_provider, close_all_providers
from chains.block import BlockPinner
from dex.adapters.uniswap_v3 import UniswapV3Adapter
from dex.adapters.algebra import AlgebraAdapter
from dex.gating import DEXGate
from strategy.gates import (
    apply_single_quote_gates,
    apply_curve_gates,
    calculate_implied_price,
    GateResult,
    ANCHOR_DEX,
)
from strategy.paper_trading import (
    PaperSession,
    PaperTrade,
    TradeOutcome,
    calculate_usdc_value,
    calculate_pnl_usdc,
)
from discovery.registry import PoolRegistry, load_registry, PoolCandidate
from monitoring.truth_report import generate_truth_report, save_truth_report, print_truth_report

logger = get_logger("arby.scan")

# Graceful shutdown flag
_shutdown_requested = False


def handle_shutdown(signum: int, frame: object) -> None:
    """Handle shutdown signals."""
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown requested", extra={"context": {"signal": signum}})


def load_config() -> tuple[dict, dict, dict]:
    """Load chains.yaml, dexes.yaml, core_tokens.yaml."""
    config_dir = Path("config")
    
    with open(config_dir / "chains.yaml") as f:
        chains = yaml.safe_load(f)
    
    with open(config_dir / "dexes.yaml") as f:
        dexes = yaml.safe_load(f)
    
    with open(config_dir / "core_tokens.yaml") as f:
        tokens = yaml.safe_load(f)
    
    return chains, dexes, tokens


def load_enabled_chains(chains_config: dict) -> list[tuple[str, dict]]:
    """Get enabled chains sorted by priority."""
    enabled = []
    for chain_key, config in chains_config.items():
        if config.get("enabled", False):
            priority = config.get("priority", 999)
            enabled.append((priority, chain_key, config))
    
    enabled.sort(key=lambda x: x[0])
    return [(chain_key, config) for _, chain_key, config in enabled]


@dataclass
class DEXQuotingConfig:
    """DEX config for quoting."""
    dex_key: str
    quoter: str
    fee_tiers: list[int]
    adapter_type: str
    verified_for_execution: bool = False


def build_test_pools(
    chain_key: str,
    chain_id: int,
    dex_configs: dict,
    token_configs: dict,
) -> tuple[list[tuple[Pool, Token, Token, str]], list[DEXQuotingConfig]]:
    """
    Build test pools for scanning (SMOKE HARNESS - Core pairs only).
    
    NOTE: This is a smoke test harness. Real universe comes from intent/registry.
    
    Core pairs for smoke:
    - WETH/USDC (base pair)
    - WETH/ARB (native token) 
    - WETH/LINK (DeFi)
    - wstETH/WETH (LST)
    - WETH/USDT (stablecoin)
    
    Returns:
        (pools_list, dexes_passed_gate)
    """
    pools = []
    passed_dexes: list[DEXQuotingConfig] = []
    
    # Define smoke pairs (token_a, token_b) - will try both directions
    SMOKE_PAIRS = [
        ("WETH", "USDC"),
        ("WETH", "ARB"),
        ("WETH", "LINK"),
        ("wstETH", "WETH"),
        ("WETH", "USDT"),
    ]
    
    # Build token objects from config
    tokens_by_symbol = {}
    for symbol in ["WETH", "USDC", "ARB", "LINK", "wstETH", "USDT"]:
        config = token_configs.get(symbol, {})
        if config.get("address"):
            tokens_by_symbol[symbol] = Token(
                chain_id=chain_id,
                address=config["address"],
                symbol=symbol,
                name=config.get("name", symbol),
                decimals=config.get("decimals", 18),
                is_core=True,
            )
    
    if "WETH" not in tokens_by_symbol or "USDC" not in tokens_by_symbol:
        logger.warning(f"Missing WETH/USDC for {chain_key}")
        return pools, passed_dexes
    
    # Build pools for each DEX
    for dex_key, dex_config in dex_configs.items():
        if not dex_config.get("enabled", False):
            continue
        
        if not dex_config.get("verified_for_quoting", False):
            continue
        
        adapter_type = dex_config.get("adapter_type", "")
        quoter = dex_config.get("quoter_v2") or dex_config.get("quoter")
        
        if adapter_type == "uniswap_v3" and quoter:
            fee_tiers = dex_config.get("fee_tiers", [500, 3000])
            verified_for_execution = dex_config.get("verified_for_execution", False)
            
            # Record DEX passed gate
            passed_dexes.append(DEXQuotingConfig(
                dex_key=dex_key,
                quoter=quoter,
                fee_tiers=fee_tiers,
                adapter_type=adapter_type,
                verified_for_execution=verified_for_execution,
            ))
            
            # Build pools for each smoke pair
            for token_a_sym, token_b_sym in SMOKE_PAIRS:
                token_a = tokens_by_symbol.get(token_a_sym)
                token_b = tokens_by_symbol.get(token_b_sym)
                
                if not token_a or not token_b:
                    continue  # Skip if token not configured for this chain
                
                for fee in fee_tiers[:2]:  # Only first 2 fee tiers for smoke
                    # Sort tokens by address for pool
                    if token_b.address.lower() < token_a.address.lower():
                        token0, token1 = token_b, token_a
                    else:
                        token0, token1 = token_a, token_b
                    
                    pool = Pool(
                        chain_id=chain_id,
                        dex_id=dex_key,
                        dex_type=DexType.UNISWAP_V3,
                        pool_address="",  # Smoke harness - no real pool address
                        token0=token0,
                        token1=token1,
                        fee=fee,
                        status=PoolStatus.ACTIVE,
                    )
                    
                    pools.append((pool, token_a, token_b, dex_key))
        
        elif adapter_type == "algebra" and quoter:
            # Algebra has dynamic fees - no fixed fee tiers
            # Use fee=0 as marker for dynamic fee
            verified_for_execution = dex_config.get("verified_for_execution", False)
            
            # Check feature flag
            feature_flag = dex_config.get("feature_flag")
            if feature_flag and not dex_config.get("enabled", False):
                logger.debug(f"Skipping {dex_key}: feature flag disabled")
                continue
            
            passed_dexes.append(DEXQuotingConfig(
                dex_key=dex_key,
                quoter=quoter,
                fee_tiers=[0],  # Single "tier" for dynamic fee
                adapter_type=adapter_type,
                verified_for_execution=verified_for_execution,
            ))
            
            # Build pools for each smoke pair (Algebra: only WETH pairs for now)
            for token_a_sym, token_b_sym in SMOKE_PAIRS:
                token_a = tokens_by_symbol.get(token_a_sym)
                token_b = tokens_by_symbol.get(token_b_sym)
                
                if not token_a or not token_b:
                    continue
                
                # Sort tokens by address for pool
                if token_b.address.lower() < token_a.address.lower():
                    token0, token1 = token_b, token_a
                else:
                    token0, token1 = token_a, token_b
                
                pool = Pool(
                    chain_id=chain_id,
                    dex_id=dex_key,
                    dex_type=DexType.ALGEBRA,
                    pool_address="",  # Smoke harness - no real pool address
                    token0=token0,
                    token1=token1,
                    fee=0,  # Dynamic fee - will be returned by quoter
                    status=PoolStatus.ACTIVE,
                )
                
                pools.append((pool, token_a, token_b, dex_key))
    
    # Log DEXes that passed gating
    if passed_dexes:
        logger.info(
            f"DEXes passed quoting gate: {len(passed_dexes)}",
            extra={"context": {"dexes": [d.dex_key for d in passed_dexes]}}
        )
    
    return pools, passed_dexes


def build_pools_from_registry(
    chain_key: str,
    chain_id: int,
    dex_configs: dict,
    registry: PoolRegistry,
) -> tuple[list[tuple[Pool, Token, Token, str]], list[DEXQuotingConfig]]:
    """
    Build pools from registry (PRODUCTION MODE).
    
    Uses intent.txt → registry pipeline instead of hardcoded smoke harness.
    
    Returns:
        (pools_list, dexes_passed_gate)
    """
    pools = []
    passed_dexes: list[DEXQuotingConfig] = []
    seen_dexes: set[str] = set()
    
    # Get candidates for this chain
    candidates = registry.get_candidates_for_chain(chain_key)
    
    if not candidates:
        logger.warning(f"No registry candidates for {chain_key}")
        return pools, passed_dexes
    
    for candidate in candidates:
        dex_key = candidate.dex_key
        pool = candidate.pool
        
        # Get DEX config
        dex_config = dex_configs.get(dex_key, {})
        quoter = dex_config.get("quoter_v2") or dex_config.get("quoter")
        
        if not quoter:
            continue
        
        # Record DEX if not seen
        if dex_key not in seen_dexes:
            seen_dexes.add(dex_key)
            passed_dexes.append(DEXQuotingConfig(
                dex_key=dex_key,
                quoter=quoter,
                fee_tiers=dex_config.get("fee_tiers", [500, 3000]),
                adapter_type=dex_config.get("adapter_type", "uniswap_v3"),
                verified_for_execution=dex_config.get("verified_for_execution", False),
            ))
        
        # Add pool with base/quote tokens
        pools.append((pool, candidate.base, candidate.quote, dex_key))
    
    # Log DEXes
    if passed_dexes:
        logger.info(
            f"DEXes from registry: {len(passed_dexes)}",
            extra={"context": {"dexes": [d.dex_key for d in passed_dexes]}}
        )
    
    logger.info(
        f"Registry pools for {chain_key}: {len(pools)} pools, {len(set(f'{c.base.symbol}/{c.quote.symbol}' for c in candidates))} pairs"
    )
    
    return pools, passed_dexes


@dataclass
class RejectSample:
    """Sample of a rejected quote for debugging."""
    dex: str
    fee: int
    amount_in: int
    gas_estimate: int
    ticks_crossed: int | None  # None for Algebra
    latency_ms: int
    error_code: str
    details: dict | None = None


class ScanSession:
    """Tracks scan session metrics and generates artifacts."""
    
    MAX_REJECT_SAMPLES = 3  # Per error code
    
    def __init__(self, output_dir: Path, intent_file: Path):
        self.output_dir = output_dir
        self.intent_file = intent_file
        self.started_at = datetime.now(timezone.utc)
        self.cycles: list[dict] = []
        
        # Quote pipeline metrics
        self.quote_reject_histogram: Counter = Counter()
        self.reject_samples: dict[str, list[RejectSample]] = defaultdict(list)
        
        self.total_quotes_attempted = 0
        self.total_quotes_fetched = 0
        self.total_quotes_passed_gates = 0
    
    def add_reject_sample(self, sample: RejectSample) -> None:
        """Add a reject sample (keep top N per code)."""
        samples = self.reject_samples[sample.error_code]
        if len(samples) < self.MAX_REJECT_SAMPLES:
            samples.append(sample)
    
    def record_cycle(self, summary: dict) -> None:
        """Record a scan cycle summary."""
        self.cycles.append(summary)
        self.total_quotes_attempted += summary.get("quotes_attempted", 0)
        self.total_quotes_fetched += summary.get("quotes_fetched", 0)
        self.total_quotes_passed_gates += summary.get("quotes_passed_gates", 0)
        
        # Aggregate reject reasons (support both old and new field names)
        reject_reasons = summary.get("reject_reasons_histogram") or summary.get("quote_reject_reasons", {})
        for code, count in reject_reasons.items():
            self.quote_reject_histogram[code] += count
    
    def get_summary(self) -> dict:
        """Get session summary."""
        fetch_rate = 0.0
        pass_rate = 0.0
        if self.total_quotes_attempted > 0:
            fetch_rate = self.total_quotes_fetched / self.total_quotes_attempted
        if self.total_quotes_fetched > 0:
            pass_rate = self.total_quotes_passed_gates / self.total_quotes_fetched
        
        return {
            "session_start": self.started_at.isoformat(),
            "session_end": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": int((datetime.now(timezone.utc) - self.started_at).total_seconds()),
            "intent_file": str(self.intent_file),
            "total_cycles": len(self.cycles),
            "total_quotes_attempted": self.total_quotes_attempted,
            "total_quotes_fetched": self.total_quotes_fetched,
            "total_quotes_passed_gates": self.total_quotes_passed_gates,
            "fetch_rate": round(fetch_rate, 4),
            "gate_pass_rate": round(pass_rate, 4),
            "quote_reject_histogram": dict(self.quote_reject_histogram),
        }
    
    def save_snapshot(self, cycle_summaries: list[dict]) -> Path:
        """Save scan snapshot to file."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"scan_{timestamp}.json"
        filepath = self.output_dir / filename
        
        # Determine mode from cycle summaries
        modes = set(s.get("mode", "SMOKE") for s in cycle_summaries)
        mode = modes.pop() if len(modes) == 1 else "MIXED"
        
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": mode,  # REGISTRY, SMOKE, or MIXED
            "session_summary": self.get_summary(),
            "cycle_summaries": cycle_summaries,
        }
        
        with open(filepath, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)
        
        logger.info(f"Snapshot saved: {filepath}")
        return filepath
    
    def save_reject_histogram(self) -> Path:
        """Save reject histogram with samples to reports."""
        reports_dir = self.output_dir.parent / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"reject_histogram_{timestamp}.json"
        filepath = reports_dir / filename
        
        # Convert samples to dict
        samples_dict = {}
        for code, samples in self.reject_samples.items():
            samples_dict[code] = [
                {
                    "dex": s.dex,
                    "fee": s.fee,
                    "amount_in": s.amount_in,
                    "gas_estimate": s.gas_estimate,
                    "ticks_crossed": s.ticks_crossed,
                    "latency_ms": s.latency_ms,
                    "details": s.details,
                }
                for s in samples
            ]
        
        # Ensure histogram and samples are consistent
        # If samples exist but histogram is empty, it's a bug we should detect
        histogram = dict(self.quote_reject_histogram)
        total = sum(histogram.values())
        
        # Sanity check: if we have samples, histogram should not be empty
        if samples_dict and not histogram:
            logger.warning(
                "Inconsistency: reject_samples exist but histogram is empty",
                extra={"context": {"sample_codes": list(samples_dict.keys())}}
            )
            # Build histogram from samples (fallback)
            histogram = {code: len(samples) for code, samples in self.reject_samples.items()}
            total = sum(histogram.values())
        
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "quote_rejects": {
                "total": total,
                "histogram": histogram,
                "sorted": dict(sorted(histogram.items(), key=lambda x: x[1], reverse=True)),
                "top_samples": samples_dict,
            },
            # Sanity flag
            "consistent": bool(histogram) == bool(samples_dict) or not samples_dict,
        }
        
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Reject histogram saved: {filepath}")
        return filepath


def calculate_spread_bps(price_a: Decimal, price_b: Decimal) -> int:
    """
    Calculate spread between two prices in basis points.
    
    Spread = |price_a - price_b| / min(price_a, price_b) * 10000
    """
    if price_a == 0 or price_b == 0:
        return 0
    
    diff = abs(price_a - price_b)
    base = min(price_a, price_b)
    return int(diff / base * 10000)


def calculate_gas_cost_bps(
    gas_estimate_a: int,
    gas_estimate_b: int,
    amount_in_wei: int,
    gas_price_wei: int,
) -> int:
    """
    Calculate gas cost in basis points relative to trade size.
    
    For arbitrage: need gas for both legs (buy + sell).
    
    Args:
        gas_estimate_a: Gas estimate for first leg
        gas_estimate_b: Gas estimate for second leg
        amount_in_wei: Trade size in wei
        gas_price_wei: Current gas price in wei (from eth_gasPrice)
    
    Returns:
        Gas cost in basis points of the trade value
        
    Note:
        On L2s with low gas prices (0.02 gwei), gas cost can be < 1 bps
        for large trades (1 ETH). This is correct - L2 gas is cheap.
        For small trades (0.01 ETH), gas cost becomes significant (~40 bps).
    """
    # Total gas = both trades
    total_gas = gas_estimate_a + gas_estimate_b
    
    # Gas cost in wei
    gas_cost_wei = total_gas * gas_price_wei
    
    # Convert to basis points of trade size
    # gas_cost_bps = (gas_cost_wei / amount_in_wei) * 10000
    if amount_in_wei == 0:
        return 0
    
    gas_cost_bps = (gas_cost_wei * 10000) // amount_in_wei
    return int(gas_cost_bps)


async def run_scan_cycle(
    chain_key: str,
    chain_config: dict,
    dex_configs: dict,
    token_configs: dict,
    session: ScanSession,
    paper_session: PaperSession | None = None,
    registry: PoolRegistry | None = None,
) -> dict:
    """
    Run a single scan cycle for a chain.
    
    Pipeline:
    1. Pin block
    2. Fetch quotes from verified DEXes
    3. Apply single-quote gates
    4. Apply curve gates
    5. Calculate spreads between DEXes
    6. Record paper trades with cooldown
    7. Record metrics
    
    Modes:
    - registry=None: SMOKE mode (WETH/USDC only)
    - registry=PoolRegistry: PRODUCTION mode (intent-driven)
    """
    cycle_start = datetime.now(timezone.utc)
    chain_id = chain_config.get("chain_id")
    mode = "REGISTRY" if registry else "SMOKE"
    
    logger.info(
        f"Starting scan cycle ({mode})",
        extra={"context": {"chain": chain_key, "chain_id": chain_id, "mode": mode}}
    )
    
    # Initialize counters
    quote_reject_reasons: Counter = Counter()
    pools_scanned = 0
    planned_pools = 0
    pairs_scanned: set[str] = set()
    pools_skipped: Counter = Counter()  # Track why pools are skipped
    quotes_attempted = 0
    quotes_fetched = 0
    quotes_rejected = 0  # Unique quotes that failed gates
    quotes_passed_gates = 0
    quotes_list: list[dict] = []
    block_number = None
    gas_price_wei = 0
    gas_price_gwei = 0.0
    dexes_passed_gate: list[dict] = []
    spreads: list[dict] = []
    paper_trades_summary: list[dict] = []  # Summary for snapshot
    rpc_stats: dict = {}
    
    # Quotes grouped by (fee, amount_in) for spread calculation
    quotes_by_key: dict[str, dict[str, Quote]] = defaultdict(dict)
    
    # Anchor prices for sanity check (per spread_key)
    anchor_prices: dict[str, Decimal] = {}  # spread_key -> anchor price
    
    try:
        # Setup provider
        rpc_urls = chain_config.get("rpc_urls", [])
        provider = register_provider(chain_id, rpc_urls)
        
        # Pin block
        pinner = BlockPinner(provider)
        block_state = await pinner.refresh()
        block_number = block_state.block_number
        pinned_block = block_number  # For freshness check
        
        logger.info(
            f"Block pinned: {block_number}",
            extra={"context": {"block": block_number, "latency_ms": block_state.latency_ms}}
        )
        
        # Fetch gas price
        gas_price_wei, gas_latency = await provider.get_gas_price()
        gas_price_gwei = gas_price_wei / 10**9
        
        logger.info(
            f"Gas price: {gas_price_gwei:.4f} gwei ({gas_price_wei} wei)",
            extra={"context": {"gas_price_wei": gas_price_wei, "gas_price_gwei": gas_price_gwei}}
        )
        
        # Build pools - REGISTRY or SMOKE mode
        if registry:
            test_pools, passed_dexes = build_pools_from_registry(
                chain_key, chain_id, dex_configs, registry
            )
        else:
            test_pools, passed_dexes = build_test_pools(
                chain_key, chain_id, dex_configs, token_configs
            )
        planned_pools = len(test_pools)
        
        # Record DEXes for artifact
        dexes_passed_gate = [
            {
                "dex_key": d.dex_key,
                "quoter": d.quoter,
                "fee_tiers": d.fee_tiers,
                "verified_for_execution": d.verified_for_execution,
            }
            for d in passed_dexes
        ]
        
        # Build lookup for execution check
        execution_allowed = {d.dex_key: d.verified_for_execution for d in passed_dexes}
        
        logger.info(
            f"Planned pools: {planned_pools}",
            extra={"context": {"chain": chain_key, "planned_pools": planned_pools}}
        )
        
        if not test_pools:
            quote_reject_reasons[ErrorCode.POOL_NOT_FOUND.value] += 1
            logger.warning(f"No test pools for {chain_key}")
        
        # Group pools by DEX + fee + pair for proper scanning
        # Each unique (dex, fee, pair) should be scanned separately
        pools_by_key: dict[str, tuple[Pool, Token, Token, str]] = {}
        for pool, token_in, token_out, dex_key in test_pools:
            # Unique key includes pair to prevent grouping different pairs together
            pair_key = f"{token_in.symbol}/{token_out.symbol}"
            key = f"{dex_key}_{pool.fee}_{pair_key}"
            # Store first occurrence (all should be same anyway)
            if key not in pools_by_key:
                pools_by_key[key] = (pool, token_in, token_out, dex_key)
        
        # Sort keys so ANCHOR_DEX is processed first (sets anchor price before others)
        sorted_keys = sorted(
            pools_by_key.keys(),
            key=lambda k: (0 if k.startswith(ANCHOR_DEX) else 1, k)
        )
        
        # Process each DEX/fee/pair combination (anchor DEX first!)
        for pool_key in sorted_keys:
            pool, token_in, token_out, dex_key = pools_by_key[pool_key]
            pools_scanned += 1
            pairs_scanned.add(f"{token_in.symbol}/{token_out.symbol}")
            
            # Get DEX config
            dex_config = dex_configs.get(dex_key, {})
            adapter_type = dex_config.get("adapter_type", "uniswap_v3")
            quoter_address = dex_config.get("quoter_v2") or dex_config.get("quoter")
            
            if not quoter_address:
                logger.warning(f"No quoter for {dex_key}")
                pools_skipped["no_quoter"] += 1
                quote_reject_reasons[ErrorCode.QUOTE_REVERT.value] += 1
                continue
            
            # Check feature flag for Algebra
            feature_flag = dex_config.get("feature_flag")
            if feature_flag == "algebra_adapter" and adapter_type == "algebra":
                # Feature flagged - check if enabled
                if not dex_config.get("enabled", False):
                    logger.debug(f"Algebra adapter disabled for {dex_key}")
                    pools_skipped["algebra_disabled"] += 1
                    continue
            
            # Create adapter based on type
            if adapter_type == "algebra":
                adapter = AlgebraAdapter(provider, quoter_address, dex_key)
            else:
                # Default to UniswapV3Adapter (works for uniswap_v3, sushiswap_v3, etc)
                adapter = UniswapV3Adapter(provider, quoter_address, dex_key)
            
            # Test sizes: 0.01 ETH, 0.1 ETH, 1 ETH
            test_amounts = [
                10**16,   # 0.01 ETH
                10**17,   # 0.1 ETH
                10**18,   # 1 ETH
            ]
            
            # Collect quotes that passed single gates for curve analysis
            single_passed_quotes: list[Quote] = []
            
            for amount_in in test_amounts:
                quotes_attempted += 1
                
                try:
                    quote = await adapter.get_quote(
                        pool=pool,
                        token_in=token_in,
                        token_out=token_out,
                        amount_in=amount_in,
                        block_number=block_number,
                    )
                    
                    # Successfully fetched and decoded
                    quotes_fetched += 1
                    
                    # Check freshness: quote must be at pinned block
                    if quote.block_number != pinned_block:
                        quote_reject_reasons[ErrorCode.QUOTE_STALE_BLOCK.value] += 1
                        session.add_reject_sample(RejectSample(
                            dex=dex_key, fee=pool.fee, amount_in=amount_in,
                            gas_estimate=quote.gas_estimate, ticks_crossed=quote.ticks_crossed,
                            latency_ms=quote.latency_ms, error_code=ErrorCode.QUOTE_STALE_BLOCK.value,
                            details={"expected_block": pinned_block, "actual_block": quote.block_number},
                        ))
                        continue
                    
                    # Determine spread_key for anchor tracking (must include pair!)
                    pair_id = f"{token_in.symbol}/{token_out.symbol}"
                    spread_key = f"{pair_id}_{pool.fee}_{amount_in}"
                    
                    # Get anchor price for this spread_key
                    anchor_price = anchor_prices.get(spread_key)
                    
                    # If this is anchor DEX and no anchor yet - calculate it first
                    if dex_key == ANCHOR_DEX and anchor_price is None:
                        anchor_price = calculate_implied_price(quote)
                        if anchor_price > 0:
                            anchor_prices[spread_key] = anchor_price
                    
                    # Apply single-quote gates with anchor price
                    gate_failures = apply_single_quote_gates(quote, anchor_price)
                    
                    if gate_failures:
                        # Count this as one rejected quote (unique)
                        quotes_rejected += 1
                        
                        # Add each failure reason to histogram (may be > 1 per quote)
                        for failure in gate_failures:
                            quote_reject_reasons[failure.reject_code.value] += 1
                            session.add_reject_sample(RejectSample(
                                dex=dex_key, fee=pool.fee, amount_in=amount_in,
                                gas_estimate=quote.gas_estimate, ticks_crossed=quote.ticks_crossed,
                                latency_ms=quote.latency_ms, error_code=failure.reject_code.value,
                                details=failure.details,
                            ))
                        continue
                    
                    # Quote passed single gates - add to curve analysis list
                    single_passed_quotes.append(quote)
                    
                    # Calculate implied price
                    implied_price = calculate_implied_price(quote)
                    
                    # Update anchor if this is anchor DEX
                    if dex_key == ANCHOR_DEX and spread_key not in anchor_prices:
                        anchor_prices[spread_key] = implied_price
                    
                    # Store quote data with all fields + pool identity
                    quote_data = {
                        "dex": dex_key,
                        "pair": f"{token_in.symbol}/{token_out.symbol}",
                        "pool_address": pool.pool_address or "computed",
                        "token_in": token_in.address,
                        "token_out": token_out.address,
                        "fee": pool.fee,
                        "quoter": quoter_address,
                        "amount_in": str(amount_in),
                        "amount_out": str(quote.amount_out),
                        "implied_price": str(implied_price),
                        "anchor_price": str(anchor_price) if anchor_price else None,
                        "block_number": block_number,
                        "gas_estimate": quote.gas_estimate,
                        "ticks_crossed": quote.ticks_crossed,
                        "sqrt_price_x96_after": str(quote.sqrt_price_x96_after) if quote.sqrt_price_x96_after else None,
                        "latency_ms": quote.latency_ms,
                    }
                    quotes_list.append(quote_data)
                    
                    # Store for spread calculation: key includes pair!
                    pair_id = f"{token_in.symbol}/{token_out.symbol}"
                    spread_key = f"{pair_id}_{pool.fee}_{amount_in}"
                    quotes_by_key[spread_key][dex_key] = quote
                    
                    logger.debug(
                        f"Quote OK: {dex_key} {token_in.symbol}->{token_out.symbol} "
                        f"fee={pool.fee} in={amount_in} out={quote.amount_out} "
                        f"gas={quote.gas_estimate} ticks={quote.ticks_crossed}"
                    )
                    
                except QuoteError as e:
                    quote_reject_reasons[e.code.value] += 1
                    quotes_rejected += 1
                    session.add_reject_sample(RejectSample(
                        dex=dex_key, fee=pool.fee, amount_in=amount_in,
                        gas_estimate=0, ticks_crossed=0, latency_ms=0,
                        error_code=e.code.value, details=e.details,
                    ))
                    logger.warning(
                        f"Quote error: {e.code.value} - {e.message}",
                        extra={"context": {
                            "dex": dex_key,
                            "quoter": quoter_address,
                            "fee": pool.fee,
                            "amount_in": amount_in,
                            "block": block_number,
                        }}
                    )
                
                except InfraError as e:
                    quote_reject_reasons[e.code.value] += 1
                    quotes_rejected += 1
                    logger.warning(
                        f"Infra error: {e.code.value} - {e.message}",
                        extra={"context": {"dex": dex_key}},
                    )
                    
                except (AttributeError, KeyError, ValueError, TypeError) as e:
                    # Classify error based on type and context
                    import traceback
                    tb = traceback.format_exc()
                    
                    # AttributeError/KeyError in our code = INTERNAL_CODE_ERROR (bug!)
                    # ValueError = bad data from RPC
                    # TypeError = validation issue
                    if isinstance(e, (AttributeError, KeyError)):
                        # Check if it's a real ABI issue or our code bug
                        tb_lower = tb.lower()
                        if "abi" in tb_lower or "decode" in tb_lower or "encode" in tb_lower:
                            error_code = ErrorCode.INFRA_BAD_ABI
                        else:
                            error_code = ErrorCode.INTERNAL_CODE_ERROR  # Our code bug!
                    elif isinstance(e, ValueError):
                        error_code = ErrorCode.QUOTE_REVERT  # Bad data from RPC
                    else:
                        error_code = ErrorCode.VALIDATION_ERROR
                    
                    quote_reject_reasons[error_code.value] += 1
                    quotes_rejected += 1
                    
                    # Add detailed sample for debugging with traceback
                    session.add_reject_sample(RejectSample(
                        dex=dex_key, fee=pool.fee, amount_in=amount_in,
                        gas_estimate=0, ticks_crossed=0, latency_ms=0,
                        error_code=error_code.value,
                        details={
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "traceback": tb.split('\n')[-4:-1],  # Last 3 lines of traceback
                            "quoter": quoter_address,
                            "token_in": token_in.address,
                            "token_out": token_out.address,
                            "token_in_symbol": token_in.symbol,
                            "token_out_symbol": token_out.symbol,
                            "token_in_decimals": token_in.decimals,
                            "token_out_decimals": token_out.decimals,
                            "pool_address": pool.pool_address or "computed",
                        },
                    ))
                    
                    logger.error(
                        f"Code error: {type(e).__name__}: {e}",
                        extra={"context": {
                            "dex": dex_key,
                            "fee": pool.fee,
                            "amount_in": amount_in,
                            "token_in": token_in.symbol,
                            "token_out": token_out.symbol,
                        }},
                        exc_info=True,
                    )
                    
                except Exception as e:
                    quote_reject_reasons[ErrorCode.INFRA_RPC_ERROR.value] += 1
                    quotes_rejected += 1
                    logger.error(
                        f"Unexpected error: {type(e).__name__}: {e}",
                        extra={"context": {"dex": dex_key}},
                        exc_info=True,
                    )
            
            # Apply curve-level gates (slippage, monotonicity)
            # Only to quotes that passed single gates
            if len(single_passed_quotes) >= 2:
                curve_failures = apply_curve_gates(single_passed_quotes)
                
                for failure in curve_failures:
                    quote_reject_reasons[failure.reject_code.value] += 1
                    logger.warning(
                        f"Curve gate failed: {failure.reject_code.value}",
                        extra={"context": {
                            "dex": dex_key,
                            "fee": pool.fee,
                            "details": failure.details,
                        }}
                    )
                
                # Note: quotes_passed_gates will be calculated at end from quotes_list
        
        # Calculate spreads between DEXes (raw opportunity detection)
        for spread_key, dex_quotes in quotes_by_key.items():
            if len(dex_quotes) < 2:
                continue
            
            dex_list = list(dex_quotes.keys())
            for i in range(len(dex_list)):
                for j in range(i + 1, len(dex_list)):
                    dex_a, dex_b = dex_list[i], dex_list[j]
                    quote_a, quote_b = dex_quotes[dex_a], dex_quotes[dex_b]
                    
                    price_a = calculate_implied_price(quote_a)
                    price_b = calculate_implied_price(quote_b)
                    
                    spread_bps = calculate_spread_bps(price_a, price_b)
                    
                    if spread_bps > 0:
                        # Parse spread_key: "PAIR_FEE_AMOUNT"
                        parts = spread_key.split("_")
                        pair = parts[0]
                        fee = parts[1]
                        amount_in_str = parts[2]
                        amount_in = int(amount_in_str)
                        
                        # Calculate gas cost in bps with real gas price
                        total_gas = quote_a.gas_estimate + quote_b.gas_estimate
                        gas_cost_wei = total_gas * gas_price_wei
                        gas_cost_bps = calculate_gas_cost_bps(
                            gas_estimate_a=quote_a.gas_estimate,
                            gas_estimate_b=quote_b.gas_estimate,
                            amount_in_wei=amount_in,
                            gas_price_wei=gas_price_wei,
                        )
                        
                        # Net PnL = spread - gas
                        net_pnl_bps = spread_bps - gas_cost_bps
                        
                        # Determine which DEX is buy vs sell (lower price = buy)
                        if price_a < price_b:
                            buy_dex, sell_dex = dex_a, dex_b
                            buy_quote, sell_quote = quote_a, quote_b
                            buy_price, sell_price = price_a, price_b
                        else:
                            buy_dex, sell_dex = dex_b, dex_a
                            buy_quote, sell_quote = quote_b, quote_a
                            buy_price, sell_price = price_b, price_a
                        
                        # Check executability (both DEXes must be verified)
                        buy_exec = execution_allowed.get(buy_dex, False)
                        sell_exec = execution_allowed.get(sell_dex, False)
                        executable = buy_exec and sell_exec
                        
                        # Get token info from quote (same for both since same pair)
                        token_in_symbol = buy_quote.token_in.symbol
                        token_out_symbol = buy_quote.token_out.symbol
                        pair = f"{token_in_symbol}/{token_out_symbol}"
                        
                        # Extended spread schema with both legs
                        spread_data = {
                            "id": f"{buy_dex}_{sell_dex}_{fee}_{amount_in_str}",
                            "pair": pair,
                            "token_in_symbol": token_in_symbol,
                            "token_out_symbol": token_out_symbol,
                            "buy_leg": {
                                "dex": buy_dex,
                                "price": str(buy_price),
                                "amount_out": str(buy_quote.amount_out),
                                "gas_estimate": buy_quote.gas_estimate,
                                "ticks_crossed": buy_quote.ticks_crossed,
                                "verified_for_execution": buy_exec,
                            },
                            "sell_leg": {
                                "dex": sell_dex,
                                "price": str(sell_price),
                                "amount_out": str(sell_quote.amount_out),
                                "gas_estimate": sell_quote.gas_estimate,
                                "ticks_crossed": sell_quote.ticks_crossed,
                                "verified_for_execution": sell_exec,
                            },
                            "fee": int(fee),
                            "amount_in": amount_in_str,
                            "spread_bps": spread_bps,
                            "gas_price_gwei": round(gas_price_gwei, 4),
                            "gas_total": total_gas,
                            "gas_cost_wei": gas_cost_wei,
                            "gas_cost_bps": gas_cost_bps,
                            "net_pnl_bps": net_pnl_bps,
                            "profitable": net_pnl_bps > 0,
                            "executable": executable,
                        }
                        spreads.append(spread_data)
                        
                        # Paper trading with PaperSession (if enabled)
                        if paper_session is not None and block_number is not None:
                            # Calculate USDC values
                            amount_in_usdc = calculate_usdc_value(
                                amount_in_wei=amount_in,
                                implied_price=buy_price,  # Use buy price for valuation
                                token_in_decimals=18,  # WETH
                            )
                            expected_pnl_usdc = calculate_pnl_usdc(
                                amount_in_wei=amount_in,
                                net_pnl_bps=net_pnl_bps,
                                implied_price=buy_price,
                                token_in_decimals=18,
                            )
                            
                            # Create PaperTrade object
                            paper_trade = PaperTrade(
                                spread_id=spread_data["id"],
                                block_number=block_number,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                chain_id=chain_id,
                                buy_dex=buy_dex,
                                sell_dex=sell_dex,
                                token_in="WETH",
                                token_out="USDC",
                                fee=int(fee),
                                amount_in_wei=amount_in_str,
                                buy_price=str(buy_price),
                                sell_price=str(sell_price),
                                spread_bps=spread_bps,
                                gas_cost_bps=gas_cost_bps,
                                net_pnl_bps=net_pnl_bps,
                                gas_price_gwei=round(gas_price_gwei, 4),
                                amount_in_usdc=round(amount_in_usdc, 2),
                                expected_pnl_usdc=round(expected_pnl_usdc, 4),
                                executable=executable,
                                buy_verified=buy_exec,
                                sell_verified=sell_exec,
                            )
                            
                            # Record with cooldown check
                            recorded = paper_session.record_trade(paper_trade)
                            
                            # Add to snapshot summary
                            paper_trades_summary.append({
                                "spread_id": paper_trade.spread_id,
                                "outcome": paper_trade.outcome,
                                "net_pnl_bps": net_pnl_bps,
                                "expected_pnl_usdc": paper_trade.expected_pnl_usdc,
                                "recorded": recorded,
                            })
                        
                        # Log spread
                        status = "EXECUTABLE" if executable and net_pnl_bps > 0 else (
                            "profitable" if net_pnl_bps > 0 else "unprofitable"
                        )
                        logger.info(
                            f"Spread ({status}): buy@{buy_dex} sell@{sell_dex} = "
                            f"{spread_bps} bps - {gas_cost_bps} gas = {net_pnl_bps} net "
                            f"(fee={fee}, size={amount_in_str}, gas={gas_price_gwei:.2f}gwei)"
                        )
        
        # Collect RPC stats
        rpc_stats = provider.get_stats_summary()
        
        # Check block staleness at end of cycle
        if pinner.is_stale():
            quote_reject_reasons[ErrorCode.QUOTE_STALE_BLOCK.value] += 1
            logger.warning("Block became stale during cycle")
    
    except InfraError as e:
        quote_reject_reasons[e.code.value] += 1
        logger.error(f"Infra error: {e.message}")
        
    except Exception as e:
        quote_reject_reasons[ErrorCode.INFRA_RPC_ERROR.value] += 1
        logger.error(f"Cycle error: {e}", exc_info=True)
    
    cycle_end = datetime.now(timezone.utc)
    duration_ms = int((cycle_end - cycle_start).total_seconds() * 1000)
    
    # ==========================================================================
    # METRICS CALCULATION FROM FACTS (not increments)
    # ==========================================================================
    # quotes_list contains ONLY quotes that passed single gates
    # quotes_by_key contains quotes grouped for spread calculation
    # quote_reject_reasons is histogram of rejection reasons
    
    # Recalculate from facts to ensure consistency
    quotes_passed_gates = len(quotes_list)  # Only passed quotes in list
    total_reject_reasons = sum(quote_reject_reasons.values())
    quotes_fetch_failed = quotes_attempted - quotes_fetched
    
    # Validate invariants
    invariant_errors = []
    
    # Invariant 1: attempted = fetched + fetch_failed
    if quotes_attempted != quotes_fetched + quotes_fetch_failed:
        invariant_errors.append(
            f"attempted({quotes_attempted}) != fetched({quotes_fetched}) + failed({quotes_fetch_failed})"
        )
    
    # Invariant 2: passed <= fetched
    if quotes_passed_gates > quotes_fetched:
        invariant_errors.append(
            f"passed({quotes_passed_gates}) > fetched({quotes_fetched})"
        )
    
    # Invariant 3: passed + rejected should relate to fetched
    # Note: rejected counts unique quotes, histogram can have multiple reasons per quote
    # So we check: passed + rejected <= fetched (some quotes may have multiple failures)
    if quotes_passed_gates + quotes_rejected > quotes_fetched:
        # This can happen if rejected is over-counted, log but don't fail
        logger.warning(
            f"Counter anomaly: passed({quotes_passed_gates}) + rejected({quotes_rejected}) "
            f"> fetched({quotes_fetched})"
        )
    
    # Calculate rates
    fetch_rate = quotes_fetched / quotes_attempted if quotes_attempted > 0 else 0.0
    gate_pass_rate = quotes_passed_gates / quotes_fetched if quotes_fetched > 0 else 0.0
    
    # Sanity check gate_pass_rate
    if gate_pass_rate > 1.0:
        invariant_errors.append(f"gate_pass_rate({gate_pass_rate:.4f}) > 1.0")
        gate_pass_rate = min(gate_pass_rate, 1.0)  # Cap at 1.0
    
    # Log invariant errors
    if invariant_errors:
        logger.error(
            f"Counter invariant violations: {invariant_errors}",
            extra={"context": {
                "attempted": quotes_attempted,
                "fetched": quotes_fetched,
                "passed": quotes_passed_gates,
                "rejected": quotes_rejected,
                "histogram_sum": total_reject_reasons,
            }}
        )
    
    summary = {
        "schema_version": "2026-01-12c",  # c = metric clarity
        "chain": chain_key,
        "chain_id": chain_id,
        "mode": mode,  # REGISTRY or SMOKE
        "cycle_start": cycle_start.isoformat(),
        "cycle_end": cycle_end.isoformat(),
        "duration_ms": duration_ms,
        "block_number": block_number,
        "block_pin": {
            "block_number": block_number,
            "pinned_at_ms": block_state.timestamp_ms if block_state else None,
            "age_ms": block_state.age_ms() if block_state else None,
            "latency_ms": block_state.latency_ms if block_state else None,
            "is_stale": pinner.is_stale() if pinner else None,
        },
        "gas_price_gwei": round(gas_price_gwei, 4),
        "planned_pools": planned_pools,
        "pools_scanned": pools_scanned,
        "pools_skipped": dict(pools_skipped),
        "pairs_scanned": list(pairs_scanned),
        "pairs_covered": len(pairs_scanned),
        "dexes_passed_gate": dexes_passed_gate,
        # Quote counts (unambiguous)
        "quotes_attempted": quotes_attempted,
        "quotes_fetched": quotes_fetched,
        "quotes_fetch_failed": quotes_fetch_failed,  # = attempted - fetched (RPC/decode errors)
        "quotes_rejected_by_gates": max(0, quotes_fetched - quotes_passed_gates),
        "quotes_passed_gates": quotes_passed_gates,
        # Rates
        "fetch_rate": round(fetch_rate, 4),
        "gate_pass_rate": round(gate_pass_rate, 4),
        # Invariant check
        "invariants_ok": len(invariant_errors) == 0,
        "invariant_errors": invariant_errors if invariant_errors else None,
        # Data
        "quotes": quotes_list,
        "spreads": spreads,
        "paper_trades": paper_trades_summary,
        "rpc_stats": rpc_stats,
        # Reject histogram (reasons, not unique quotes)
        "reject_reasons_histogram": dict(quote_reject_reasons),
        "reject_reasons_total": total_reject_reasons,  # Sum of histogram
        "status": "OK" if quotes_passed_gates > 0 else "NO_QUOTES",
    }
    
    session.record_cycle(summary)
    
    # Count paper trade outcomes
    would_execute = sum(1 for t in paper_trades_summary if t.get("outcome") == TradeOutcome.WOULD_EXECUTE.value)
    blocked = sum(1 for t in paper_trades_summary if t.get("outcome") == TradeOutcome.BLOCKED_EXEC.value)
    cooldown = sum(1 for t in paper_trades_summary if t.get("outcome") == TradeOutcome.COOLDOWN.value)
    
    # Get paper session cumulative stats if available
    paper_stats = paper_session.stats if paper_session else {}
    
    logger.info(
        f"Scan cycle complete: {quotes_fetched}/{quotes_attempted} fetched, "
        f"{quotes_passed_gates} passed gates, {len(spreads)} spreads, "
        f"{would_execute} executable, {blocked} blocked, {cooldown} cooldown",
        extra={"context": {
            "chain": chain_key,
            "block": block_number,
            "gas_price_gwei": round(gas_price_gwei, 4),
            "quotes_attempted": quotes_attempted,
            "quotes_fetched": quotes_fetched,
            "quotes_passed_gates": quotes_passed_gates,
            "spreads": len(spreads),
            "paper_would_execute": would_execute,
            "paper_blocked": blocked,
            "paper_cooldown": cooldown,
            "paper_cumulative": paper_stats,
            "rejects": dict(quote_reject_reasons),
        }}
    )
    
    return summary


async def scan_loop(
    chains: list[tuple[str, dict]],
    dexes: dict,
    tokens: dict,
    interval_ms: int,
    session: ScanSession,
    paper_session: PaperSession | None = None,
    registry: PoolRegistry | None = None,
) -> None:
    """Continuous scanning loop."""
    cycle_count = 0
    
    while not _shutdown_requested:
        cycle_count += 1
        
        logger.info(f"=== Scan Cycle {cycle_count} ===")
        
        cycle_summaries = []
        for chain_key, chain_config in chains:
            if _shutdown_requested:
                break
            
            dex_configs = dexes.get(chain_key, {})
            token_configs = tokens.get(chain_key, {})
            
            summary = await run_scan_cycle(
                chain_key, chain_config, dex_configs, token_configs,
                session, paper_session, registry
            )
            cycle_summaries.append(summary)
        
        total_passed = sum(s["quotes_passed_gates"] for s in cycle_summaries)
        total_attempted = sum(s["quotes_attempted"] for s in cycle_summaries)
        total_spreads = sum(len(s.get("spreads", [])) for s in cycle_summaries)
        
        # Paper session cumulative
        paper_cumulative = paper_session.stats if paper_session else {}
        
        logger.info(
            f"Cycle {cycle_count} complete: {total_passed}/{total_attempted} quotes, "
            f"{total_spreads} spreads, paper_cumulative={paper_cumulative}"
        )
        
        if not _shutdown_requested:
            await asyncio.sleep(interval_ms / 1000)
    
    logger.info("Scan loop terminated")


@click.command()
@click.option("--chain", "-c", default="arbitrum_one", help="Chain to scan (or 'all')")
@click.option("--interval", "-i", default=5000, help="Scan interval in milliseconds")
@click.option("--once", is_flag=True, help="Run single scan cycle and exit")
@click.option("--intent", type=click.Path(exists=True), default="config/intent.txt")
@click.option("--output-dir", "-o", default="data/snapshots")
@click.option("--trades-dir", "-t", default="data/trades")
@click.option("--log-level", "-l", default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]))
@click.option("--json-logs/--no-json-logs", default=True)
@click.option("--paper-trading/--no-paper-trading", default=True, help="Enable paper trading")
@click.option("--simulate-blocked/--no-simulate-blocked", default=True, help="Also simulate blocked trades")
@click.option("--cooldown-blocks", default=10, help="Blocks to wait before re-trading same spread")
@click.option("--use-registry/--smoke", default=True, help="Use registry (intent-driven) vs smoke (WETH/USDC only)")
def main(
    chain: str,
    interval: int,
    once: bool,
    intent: str,
    output_dir: str,
    trades_dir: str,
    log_level: str,
    json_logs: bool,
    paper_trading: bool,
    simulate_blocked: bool,
    cooldown_blocks: int,
    use_registry: bool,
) -> None:
    """ARBY Opportunity Scanner - Real quotes from DEXes with gates and spread detection."""
    setup_logging(level=log_level, json_output=json_logs)
    set_global_context(service="arby-scan", version="0.5.0")  # Bump version
    
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    intent_path = Path(intent)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    trades_path = Path(trades_dir)
    trades_path.mkdir(parents=True, exist_ok=True)
    
    # Load config
    chains_config, dexes_config, tokens_config = load_config()
    
    # Determine chains
    if chain == "all":
        chains = load_enabled_chains(chains_config)
    else:
        if chain not in chains_config:
            logger.error(f"Unknown chain: {chain}")
            sys.exit(1)
        chains = [(chain, chains_config[chain])]
    
    session = ScanSession(output_path, intent_path)
    
    # Create paper session if enabled
    paper_session = None
    if paper_trading:
        paper_session = PaperSession(
            trades_dir=trades_path,
            cooldown_blocks=cooldown_blocks,
            simulate_blocked=simulate_blocked,
        )
    
    # Create registry if enabled (PRODUCTION mode)
    registry = None
    if use_registry:
        registry = load_registry(intent_path)
        registry_summary = registry.get_summary()
        logger.info(
            "Registry loaded",
            extra={"context": registry_summary}
        )
        
        # Save registry snapshot
        registry.save_snapshot(output_path.parent / "registry")
    
    mode = "REGISTRY" if use_registry else "SMOKE"
    logger.info(
        f"Starting ARBY Scanner ({mode})",
        extra={"context": {
            "chains": [c[0] for c in chains],
            "mode": mode,
            "once": once,
            "paper_trading": paper_trading,
            "simulate_blocked": simulate_blocked,
            "cooldown_blocks": cooldown_blocks,
        }}
    )
    
    async def run():
        try:
            if once:
                cycle_summaries = []
                for chain_key, chain_config in chains:
                    dex_configs = dexes_config.get(chain_key, {})
                    token_configs = tokens_config.get(chain_key, {})
                    
                    summary = await run_scan_cycle(
                        chain_key, chain_config, dex_configs, token_configs,
                        session, paper_session, registry
                    )
                    cycle_summaries.append(summary)
                
                session.save_snapshot(cycle_summaries)
                session.save_reject_histogram()
                
                # Generate truth report
                snapshot = {
                    "mode": mode,
                    "cycle_summaries": cycle_summaries,
                }
                paper_stats = paper_session.stats if paper_session else None
                truth_report = generate_truth_report(snapshot, paper_stats)
                
                # Save and print
                reports_dir = output_path.parent / "reports"
                save_truth_report(truth_report, reports_dir)
                print_truth_report(truth_report)
            else:
                await scan_loop(
                    chains, dexes_config, tokens_config, interval,
                    session, paper_session, registry
                )
        finally:
            await close_all_providers()
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Scanner interrupted")
    except Exception as e:
        logger.error(f"Scanner error: {e}", exc_info=True)
        sys.exit(1)
    
    # Final summary
    summary = session.get_summary()
    logger.info("Final session summary", extra={"context": summary})
    
    # Paper session summary
    if paper_session:
        paper_summary = paper_session.get_summary()
        logger.info("Paper session summary", extra={"context": paper_summary})
    
    logger.info("Scanner stopped")


if __name__ == "__main__":
    main()
