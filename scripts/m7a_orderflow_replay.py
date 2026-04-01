#!/usr/bin/env python3
"""
M7.A.5 вЂ” Live block-event backrun replay on arbitrum_one.

Re-export shim вЂ” canonical location moved to m7.orderflow.*
All public symbols are re-exported for backward compatibility.

Usage:
    python scripts/m7a_orderflow_replay.py --offline --output data/tmp/m7a_orderflow_offline.json
    python scripts/m7a_orderflow_replay.py --replay data/tmp/events.json --output data/tmp/m7a_replay.json
    python scripts/m7a_orderflow_replay.py --intent-scout --output data/tmp/m7a_intent_scout.json
    python scripts/m7a_orderflow_replay.py --online --output data/tmp/m7a_orderflow_online.json
    python scripts/m7a_orderflow_replay.py --live-blocks 5 --output data/tmp/m7a_live_blocks.json
    python scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 10 --output data/tmp/m7a_ws_live.json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# --- Re-exports from m7.shared.constants ---
from m7.shared.constants import (  # noqa: F401
    # Event types
    EVENT_TYPE_SWAP,
    EVENT_TYPE_LARGE_TRANSFER,
    EVENT_TYPE_POOL_REBALANCE,
    ALL_EVENT_TYPES,
    # Backrun directions
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    BACKRUN_TRIANGULAR,
    # Reject reasons
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
    ALL_REJECT_REASONS,
    UNSCORED_REJECTS,
    # Admission sources
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_SUBGRAPH_VERIFIED,
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_REJECTED,
    ALL_ADMISSION_SOURCES,
    # Chainlink
    CHAINLINK_FEEDS_ARBITRUM,
    CHAINLINK_LATEST_ROUND_SELECTOR,
    CHAINLINK_DECIMALS,
    # Subgraph
    SUBGRAPH_ENDPOINTS_ARBITRUM,
    SUBGRAPH_SEED_TOKEN_CAP,
    SUBGRAPH_TIMEOUT_SECONDS,
    # Blocker tags
    ALL_BLOCKER_TAGS,
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
    # Surfaces
    SURFACE_MEV_SHARE_BACKRUN,
    SURFACE_UNISWAPX_FILLER,
    SURFACE_COW_SOLVER,
    SURFACE_BLOCK_BACKRUN,
    ALL_SURFACES,
    # Thresholds and sizing
    MIN_EVENT_SIZE_USD,
    SIGNIFICANT_IMPACT_BPS,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    _REF_MIN_WEI_18,
    _REF_MAX_WEI_18,
    M7A4_CHAIN,
    SWAP_EVENT_TOPIC,
    DEFAULT_LIVE_BLOCKS,
    _FALLBACK_ETH_PRICE_USD,
    GAS_FLOOR_BPS_ARBITRUM,
)

# --- Re-exports from m7.orderflow.contracts ---
from m7.orderflow.contracts import (  # noqa: F401
    BackrunResult,
    IntentSurfaceAssessment,
    OrderflowEvent,
)

# --- Re-exports from m7.orderflow.events ---
from m7.orderflow.events import (  # noqa: F401
    build_fixture_events,
    fetch_recent_swap_events,
    load_events_from_file,
    normalize_swap_log,
)

# --- Re-exports from m7.orderflow.resolve ---
from m7.orderflow.resolve import (  # noqa: F401
    _build_address_to_symbol,
    _get_pool_addresses_for_dexes,
    _get_v3_factory_addresses,
    _resolve_event_tokens,
    _resolve_pool_addresses_multicall,
    enrich_tokens_batch,
    enrich_unknown_token,
    extract_pool_state_for_sim,
)

# --- Re-exports from m7.orderflow.coverage ---
from m7.orderflow.coverage import (  # noqa: F401
    admit_event_tokens,
    counter_venue_coverage_scan,
    seed_tokens_from_subgraph,
)

# --- Re-exports from m7.orderflow.pricing ---
from m7.orderflow.pricing import (  # noqa: F401
    _gas_cost_in_token_wei,
    _normalized_bounds,
    check_oracle_sanity,
    classify_event_backrun_type,
    classify_event_viability,
    estimate_backrun_gross_bps,
    estimate_fee_cost_bps,
    estimate_gas_cost_bps,
    estimate_gas_decomposition_bps,
    score_backrun_live,
    score_backrun_online,
)

# --- Re-exports from m7.orderflow.scoring_parallel ---
from m7.orderflow.scoring_parallel import (  # noqa: F401
    score_backrun_live_parallel,
)

# --- Re-exports from m7.orderflow.v3_math ---
from m7.orderflow.v3_math import (  # noqa: F401
    attempt_local_pricing,
    compute_algebra_swap_amount_out,
    compute_v2_swap_amount_out,
    compute_v3_swap_amount_out,
)

# --- Re-exports from m7.orderflow.artifacts ---
from m7.orderflow.artifacts import (  # noqa: F401
    build_intent_scout_summary,
    build_intent_surface_assessments,
    build_replay_summary,
    score_backrun_offline,
)

# --- Re-exports from m7.orderflow.cli ---
from m7.orderflow.cli import main  # noqa: F401

if __name__ == "__main__":
    main()
