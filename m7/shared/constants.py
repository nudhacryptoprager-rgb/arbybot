"""
Canonical M7 constants: event types, reject reasons, blocker tags,
admission sources, thresholds, and chain-specific config.

Single source of truth — all M7 modules import from here.
"""
from __future__ import annotations

from typing import Dict

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------
EVENT_TYPE_SWAP = "swap"
EVENT_TYPE_LARGE_TRANSFER = "large_transfer"
EVENT_TYPE_POOL_REBALANCE = "pool_rebalance"
ALL_EVENT_TYPES = frozenset({EVENT_TYPE_SWAP, EVENT_TYPE_LARGE_TRANSFER, EVENT_TYPE_POOL_REBALANCE})

# ---------------------------------------------------------------------------
# Backrun direction labels
# ---------------------------------------------------------------------------
BACKRUN_BUY_DEPRESSED = "buy_depressed_token"
BACKRUN_SELL_APPRECIATED = "sell_appreciated_token"
BACKRUN_TRIANGULAR = "triangular_post_event"

# ---------------------------------------------------------------------------
# Reject reason codes
# ---------------------------------------------------------------------------
REJECT_NO_COUNTER_VENUE = "NO_COUNTER_VENUE"
REJECT_GAS_EXCEEDS_GROSS = "GAS_EXCEEDS_GROSS"
REJECT_SLIPPAGE_EXCEEDS_GROSS = "SLIPPAGE_EXCEEDS_GROSS"
REJECT_EVENT_TOO_SMALL = "EVENT_TOO_SMALL"
REJECT_SAME_BLOCK_IMPOSSIBLE = "SAME_BLOCK_IMPOSSIBLE"
REJECT_QUOTE_FAILURE = "QUOTE_FAILURE"  # legacy — kept for backward compat
REJECT_INSUFFICIENT_IMPACT = "INSUFFICIENT_IMPACT"
REJECT_TOKEN_PAIR_UNRESOLVED = "TOKEN_PAIR_UNRESOLVED"
# M7.A.5.6: Split QUOTE_FAILURE into granular sub-reasons
REJECT_NO_COUNTER_POOL = "NO_COUNTER_POOL"
REJECT_TOKEN_NOT_ADMITTED = "TOKEN_NOT_ADMITTED"
REJECT_UNSUPPORTED_ADAPTER = "UNSUPPORTED_ADAPTER"
REJECT_RPC_QUOTE_FAIL = "RPC_QUOTE_FAIL"
REJECT_PAIR_RESOLVED_UNTRADEABLE = "PAIR_RESOLVED_BUT_UNTRADEABLE"
# M7.A.5.10: Stale-positive and zero-liquidity gates
REJECT_STALE_POSITIVE = "STALE_POSITIVE"
REJECT_ZERO_LIQUIDITY = "ZERO_LIQUIDITY"
# M7.A.5.11: Granular coverage rejects
REJECT_NO_ACTIVE_COUNTER_POOL = "NO_ACTIVE_COUNTER_POOL"
REJECT_ALL_POOLS_ZERO_LIQUIDITY = "ALL_POOLS_ZERO_LIQUIDITY"
# M7.A.5.12: Coverage/local-sim consistency split
REJECT_COVERAGE_LOCAL_MISMATCH = "COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO"
REJECT_ALL_POOLS_TRULY_INACTIVE = "ALL_CANDIDATE_POOLS_TRULY_INACTIVE"
# M7.A.5.21: Gas-floor prefilter
REJECT_GAS_FLOOR_EXCEEDED = "GAS_FLOOR_EXCEEDED"

ALL_REJECT_REASONS = frozenset({
    REJECT_NO_COUNTER_VENUE,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_EVENT_TOO_SMALL,
    REJECT_SAME_BLOCK_IMPOSSIBLE,
    REJECT_QUOTE_FAILURE,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    REJECT_NO_COUNTER_POOL,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
    REJECT_STALE_POSITIVE,
    REJECT_ZERO_LIQUIDITY,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_GAS_FLOOR_EXCEEDED,
})

# M7.A.5.13: Module-level unscored rejects set
UNSCORED_REJECTS = frozenset({
    REJECT_TOKEN_PAIR_UNRESOLVED, REJECT_NO_COUNTER_POOL,
    REJECT_TOKEN_NOT_ADMITTED, REJECT_UNSUPPORTED_ADAPTER,
    REJECT_RPC_QUOTE_FAIL, REJECT_PAIR_RESOLVED_UNTRADEABLE,
    REJECT_ZERO_LIQUIDITY,
    REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH, REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_GAS_FLOOR_EXCEEDED,
})

# ---------------------------------------------------------------------------
# M7.A.5.7: Admission source tracking
# ---------------------------------------------------------------------------
ADMISSION_CANONICAL = "canonical_core"
ADMISSION_ADDR_TO_SYMBOL = "addr_to_symbol"
ADMISSION_SUBGRAPH_VERIFIED = "subgraph_seeded_verified"
ADMISSION_ONCHAIN_ENRICHED = "onchain_enriched_verified"
ADMISSION_REJECTED = "rejected_unverified"
ALL_ADMISSION_SOURCES = frozenset({
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_SUBGRAPH_VERIFIED,
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_REJECTED,
})

# ---------------------------------------------------------------------------
# M7.A.5.7: Chainlink price feed addresses on Arbitrum One (USD, 8 decimals)
# ---------------------------------------------------------------------------
CHAINLINK_FEEDS_ARBITRUM: Dict[str, str] = {
    "WETH": "0x639Fe6ab55C921f74e7fac1ee960C0B6293ba612",
    "WBTC": "0x6ce185860a4963106506C203335A2910413708e9",
    "USDT": "0x3f3f5dF88dC9F13eac63DF89EC16ef6e7E25DdE7",
    "USDC": "0x50834F3163758fcC1Df9973b6e91f0F0F0434aD3",
    "ARB": "0xb2A824043730FE05F3DA2efaFa1CBbe83fa548D6",
    "LINK": "0x86E53CF1B870786351Da77A57575e79CB55812CB",
    "DAI": "0xc5C8E77B397E531B8EC06BFb0048328B30E9eCfB",
    "UNI": "0x9C917083fDb403ab5ADbEC26Ee294f6EcAda7Fee",
    "GMX": "0xDB98056FecFff59D032aB628337A4887110df3dB",
    "PENDLE": "0x66853E19d73c0F9301fe99c324C1ba0bb3f51b01",
}
CHAINLINK_LATEST_ROUND_SELECTOR = "0xfeaf968c"  # latestRoundData()
CHAINLINK_DECIMALS = 8  # USD feeds return 8-decimal answer

# ---------------------------------------------------------------------------
# M7.A.5.8: Subgraph-backed coverage seed endpoints
# ---------------------------------------------------------------------------
SUBGRAPH_ENDPOINTS_ARBITRUM: Dict[str, str] = {
    "uniswap_v3": "https://gateway.thegraph.com/api/subgraphs/id/5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
    "sushiswap_v3": "https://gateway.thegraph.com/api/subgraphs/id/B2o157JTLbHpqy2MFga4HPrv46RTGiB3FWBQk6SwNkrR",
}
SUBGRAPH_SEED_TOKEN_CAP = 50
SUBGRAPH_TIMEOUT_SECONDS = 10

# ---------------------------------------------------------------------------
# M7.A.5.18 / M7.R1: Canonical blocker tags
# ---------------------------------------------------------------------------
BLOCKER_LOW_LAG_NONE_THIS_WINDOW = "LOW_LAG_NONE_THIS_WINDOW"
BLOCKER_LOW_LAG_NO_COUNTER_POOL = "LOW_LAG_NO_COUNTER_POOL"
BLOCKER_LOW_LAG_V2_UNSUPPORTED = "LOW_LAG_V2_UNSUPPORTED"
BLOCKER_LOW_LAG_INACTIVE_POOL = "LOW_LAG_INACTIVE_POOL"
BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY = "LOW_LAG_REMOTE_QUOTER_LATENCY"
BLOCKER_LOW_LAG_RPC_QUOTE_FAIL = "LOW_LAG_RPC_QUOTE_FAIL"
BLOCKER_GAS_L1_DATA_DOMINANT = "GAS_L1_DATA_DOMINANT"
BLOCKER_SUBGRAPH_API_KEY_REQUIRED = "SUBGRAPH_API_KEY_REQUIRED"

ALL_BLOCKER_TAGS = frozenset({
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
})

# ---------------------------------------------------------------------------
# Intent/auction surface types
# ---------------------------------------------------------------------------
SURFACE_MEV_SHARE_BACKRUN = "mev_share_backrun"
SURFACE_UNISWAPX_FILLER = "uniswapx_filler"
SURFACE_COW_SOLVER = "cow_solver"
SURFACE_BLOCK_BACKRUN = "block_event_backrun"

ALL_SURFACES = frozenset({
    SURFACE_MEV_SHARE_BACKRUN,
    SURFACE_UNISWAPX_FILLER,
    SURFACE_COW_SOLVER,
    SURFACE_BLOCK_BACKRUN,
})

# ---------------------------------------------------------------------------
# Thresholds and sizing
# ---------------------------------------------------------------------------
MIN_EVENT_SIZE_USD = 100.0
SIGNIFICANT_IMPACT_BPS = 5.0
DEFAULT_BACKRUN_GAS = 200_000
DEFAULT_GAS_PRICE_GWEI = 0.1

# M7.A.5.9: Decimal-aware size normalization reference bounds (18-decimal tokens)
_REF_MIN_WEI_18 = 10**15   # 0.001 of an 18-decimal token
_REF_MAX_WEI_18 = 10**18   # 1.0 of an 18-decimal token

# Canonical chain for M7.A.4/M7.A.5
M7A4_CHAIN = "arbitrum_one"

# Uniswap V3 Swap event topic
SWAP_EVENT_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

# Default number of recent blocks to scan for live events
DEFAULT_LIVE_BLOCKS = 5

# M7.A.5.9: Gas denomination conversion
_FALLBACK_ETH_PRICE_USD = 3500.0

# V3 fee tiers to try when pool fee is unknown
_DEFAULT_FEE_TIERS = [500, 3000, 100, 10000]

# ---------------------------------------------------------------------------
# M7.A.5.21: Gas-floor prefilter threshold (Arbitrum)
# ---------------------------------------------------------------------------
# Minimum gross bps needed to cover Arbitrum gas (L2 exec + L1 data poster).
# Events whose estimated gross < this floor are rejected without quoting.
GAS_FLOOR_BPS_ARBITRUM = 2.0  # ~2 bps baseline gas cost on Arbitrum
