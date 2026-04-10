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
# M7.A.5.25: Pricing anomaly — absurd net_bps from local pricing on thin liquidity
REJECT_PRICING_ANOMALY = "PRICING_ANOMALY"

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
    REJECT_PRICING_ANOMALY,
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
BLOCKER_LOW_LAG_COMPLETION_LATENCY = "LOW_LAG_COMPLETION_LATENCY"
BLOCKER_LOW_LAG_RPC_QUOTE_FAIL = "LOW_LAG_RPC_QUOTE_FAIL"
BLOCKER_GAS_L1_DATA_DOMINANT = "GAS_L1_DATA_DOMINANT"
BLOCKER_SUBGRAPH_API_KEY_REQUIRED = "SUBGRAPH_API_KEY_REQUIRED"

ALL_BLOCKER_TAGS = frozenset({
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_COMPLETION_LATENCY,
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

# M7.E1: Base gas floor — significantly cheaper than Arbitrum (no L1 data poster
# component at current base fee levels; typical swap cost ~0.1-0.3 bps).
GAS_FLOOR_BPS_BASE = 0.5

# ---------------------------------------------------------------------------
# M7.A.5.27: Timeboost ordering — Arbitrum express lane constants
# ---------------------------------------------------------------------------
# Arbitrum Timeboost allows bidding for express lane priority (200ms advantage).
# For backrun execution, this gives ordering advantage over vanilla mempool.
# These constants are placeholder for a future execution path; scoring uses them
# only for feasibility assessment.
TIMEBOOST_BLOCK_TIME_MS = 250  # Arbitrum block time
TIMEBOOST_EXPRESS_ADVANTAGE_MS = 200  # Express lane head start
TIMEBOOST_MIN_PIPELINE_MS = 50  # Minimum scoring time for executable decision
# Maximum pipeline latency to be Timeboost-eligible (budget = block - advantage)
TIMEBOOST_ELIGIBLE_BUDGET_MS = TIMEBOOST_BLOCK_TIME_MS - TIMEBOOST_EXPRESS_ADVANTAGE_MS

# ---------------------------------------------------------------------------
# M7.A.5.36: Hot-path stage budgets (ms) — target p50 ≤ 250ms
# ---------------------------------------------------------------------------
# Hard per-stage budgets for the fast scoring path.
# The fast path assumes pre-warmed registry (zero discovery cost).
# Each stage is enforced individually — exceeding ANY stage aborts.
# resolve_ms, oracle_ms, enrichment_ms, registry_preload_ms are NOT in hot path.
HOT_BUDGET_RESOLVE_MS = 0             # MUST be 0: pre-resolved in prewarm
HOT_BUDGET_ORACLE_MS = 0              # MUST be 0: no oracle in hot lane
HOT_BUDGET_ENRICHMENT_MS = 0          # MUST be 0: no enrichment in hot lane
HOT_BUDGET_REGISTRY_PRELOAD_MS = 0    # MUST be 0: pre-warmed between iterations
HOT_BUDGET_REGISTRY_LOOKUP_MS = 25    # O(1) cache lookup
HOT_BUDGET_POOL_STATE_READ_MS = 50    # Cached entry to_pool_state()
HOT_BUDGET_LOCAL_MATH_MS = 10         # V3/V2 swap math
HOT_BUDGET_PROFIT_GUARD_MS = 40       # Guard feasibility check
HOT_BUDGET_TX_BUILD_MS = 50           # Transaction build/sign prep (future)
HOT_BUDGET_CALLDATA_MS = 20           # ABI calldata encoding (future)
HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS = 30  # Signing or bundle preparation (future)
HOT_BUDGET_TOTAL_MS = 250             # Hard abort if exceeded

# Default watchlist pairs for hot lane fast-path (high-frequency Arbitrum pairs)
# M7.A.5.35: These serve as SEED pairs for the promoted watchlist.
# The promoted watchlist is built dynamically from cold lane results.
HOT_WATCHLIST_PAIRS = [
    ("WETH", "USDC"),
    ("WETH", "USDT"),
    ("WETH", "ARB"),
]

# ---------------------------------------------------------------------------
# M7.E1: Chain-aware prewarm pairs (event-source pilot)
# ---------------------------------------------------------------------------
# Arbitrum: high-frequency DeFi pairs on Arbitrum One
PREWARM_PAIRS_ARBITRUM = [
    ("WETH", "USDC"), ("WETH", "USDT"), ("WETH", "ARB"),
    ("USDC", "USDT"), ("WETH", "WBTC"), ("ARB", "USDC"),
]
# Base production: narrow stable/wrapped contour from onboard_base_profit.yaml
PREWARM_PAIRS_BASE = [
    ("USDC", "DAI"), ("USDC", "USDT"), ("WETH", "USDC"),
]
# M7.E1.10: Base discovery — contour cleanup.
# Structurally stronger pairs first, meme families (cross_dex_expected=1) after.
# AMONGUS removed (not in core_tokens.yaml = dead slot).
PREWARM_PAIRS_BASE_DISCOVERY = [
    ("USDC", "DAI"), ("USDC", "USDT"), ("WETH", "USDC"),  # production core
    ("AERO", "USDC"), ("AERO", "WETH"),  # structurally stronger (cross_dex >= 2)
    ("cbBTC", "USDC"), ("cbBTC", "WETH"),  # structurally stronger (cross_dex >= 2)
    ("DEGEN", "WETH"), ("BRETT", "WETH"), ("TOSHI", "WETH"),  # diagnostic_only (cross_dex=1)
]

# Base Chainlink price feeds (USD, 8 decimals)
# Reference: https://docs.chain.link/data-feeds/price-feeds/addresses?network=base
CHAINLINK_FEEDS_BASE: Dict[str, str] = {
    "WETH": "0x71041dddad3595F9CEd3DcCFBe3D1F4b0a16Bb70",
    "USDC": "0x7e860098F58bBFC8648a4311b374B1D669a2bc6B",
    "DAI":  "0x591e79239a7d679378eC8c847e5038150364C78F",
    "cbBTC": "0x07DA0E54543a844a80ABE69c8A12F22B3aA59f9D",
}


def get_chainlink_feeds(chain: str) -> Dict[str, str]:
    """Return Chainlink feed addresses for the given chain."""
    if chain == "base":
        return CHAINLINK_FEEDS_BASE
    return CHAINLINK_FEEDS_ARBITRUM


def get_gas_floor_bps(chain: str) -> float:
    """Return gas floor BPS threshold for the given chain."""
    if chain == "base":
        return GAS_FLOOR_BPS_BASE
    return GAS_FLOOR_BPS_ARBITRUM


def get_prewarm_pairs(chain: str, profile: str = "production") -> list:
    """Return prewarm pair tuples for the given chain and profile.

    Parameters
    ----------
    chain : chain key (e.g. "base", "arbitrum_one").
    profile : "production" (narrow, default) or "discovery" (wider contour).
    """
    if chain == "base":
        if profile == "discovery":
            return PREWARM_PAIRS_BASE_DISCOVERY
        return PREWARM_PAIRS_BASE
    return PREWARM_PAIRS_ARBITRUM

# ---------------------------------------------------------------------------
# M7.A.5.36: Promoted watchlist rules — cold-to-hot pair promotion
# ---------------------------------------------------------------------------
# A pair is promoted from cold lane to hot watchlist when it meets ALL rules:
# M7.A.5.39: Two-level promotion — candidate (relaxed) + execution (strict)
#
# **Candidate promotion** (level 1): pair enters registry prewarm.
#   Rules: appearances >= threshold, has_active_pools, best_net > min, no anomaly.
#   Does NOT require size_valid_for_token (enrichment may have failed).
#
# **Execution promotion** (level 2): pair eligible for hot-path scoring.
#   Rules: all candidate rules PLUS size_valid_for_token = True.
#
#   1. size_valid_for_token = True in at least one cold scored result  [execution only]
#   2. reject_reason != PRICING_ANOMALY
#   3. registry_pools_active > 0
#   4. Appeared in at least PROMOTED_MIN_COLD_APPEARANCES cold iterations
#   5. NOT stale with contradictory KPIs (stale + negative best_net)
#   6. (M7.A.5.36) best_net_bps > PROMOTED_MIN_NET_BPS
PROMOTED_MIN_COLD_APPEARANCES = 2  # minimum cold iterations to qualify
PROMOTED_MAX_PAIRS = 10            # cap promoted watchlist size
PROMOTED_MIN_NET_BPS = -50.0       # minimum best_net_bps to qualify (not total garbage)
PROMOTED_CANDIDATE_MAX_PAIRS = 20  # cap candidate watchlist (wider than execution)

# ---------------------------------------------------------------------------
# M7.E1.9: Discovery lane budget + promotion rules
# ---------------------------------------------------------------------------
# Discovery profile uses wider prewarm but caps how many can be promoted.
PROMOTED_DISCOVERY_MAX_PAIRS = 15  # discovery cap (wider than production)
# Family repeatability: minimum scored-positive occurrences to graduate
# from discovery lane into production consideration.
DISCOVERY_GRADUATE_MIN_POSITIVE = 3    # min scored_positive across sessions
DISCOVERY_GRADUATE_MIN_SESSIONS = 2    # min distinct sessions with signal
# A "profile" is either "production" (narrow, proven) or "discovery" (wide, exploratory).
VALID_PROFILES = ("production", "discovery")

