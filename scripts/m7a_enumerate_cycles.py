#!/usr/bin/env python3
"""
M7.A — Enumeration of triangular cycles from verified pool sources.

Re-export shim — canonical location moved to m7.triangular.*
All public symbols are re-exported for backward compatibility.

Usage:
    python scripts/m7a_enumerate_cycles.py
    python scripts/m7a_enumerate_cycles.py --source runtime --score measured --output data/tmp/m7a_cycles.json
    python scripts/m7a_enumerate_cycles.py --chain arbitrum_one --max-cycles 5000
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is on sys.path so `python scripts/m7a_enumerate_cycles.py` works
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# --- Re-exports from m7.triangular.graph ---
from m7.triangular.graph import (  # noqa: F401
    M7A_DEXES_ARBITRUM_ONE,
    M7A_STABLE_ADAPTERS,
    M7A_TOKENS_ARBITRUM_ONE,
    M7A2_TOKENS_ARBITRUM_ONE,
    PoolEdge,
    PoolGraph,
    build_graph_from_runtime_pairs,
    filter_graph_to_m7a_universe,
    filter_graph_to_m7a2_universe,
)

# --- Re-exports from m7.triangular.scoring ---
from m7.triangular.scoring import (  # noqa: F401
    CycleScore,
    LegQuote,
    SizeSweepPoint,
    SizeSweepResult,
    TriangularCycle,
    filter_viable_fee_structures,
    find_3hop_cycles,
    leg_quote_from_rpc_result,
    rank_cycles_by_net,
    score_cycle_fees_only,
    score_cycle_measured,
)

# --- Re-exports from m7.triangular.verdicts ---
from m7.triangular.verdicts import (  # noqa: F401
    ALL_REGIME_TAGS,
    BLOCKER_GROSS_NEGATIVE_CORE,
    BLOCKER_GAS_DOMINANT_SMALL,
    BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT,
    BLOCKER_SINGLE_TRIPLE_CONCENTRATION,
    BLOCKER_SLIPPAGE_DOMINANT_LARGE,
    BLOCKER_THIRD_LEG_FEE_BINDING,
    REGIME_HIGH_ACTIVITY,
    REGIME_HIGH_ACTIVITY_THRESHOLD,
    REGIME_HIGH_FAILURE,
    REGIME_HIGH_FAILURE_THRESHOLD,
    REGIME_LOW_ACTIVITY,
    REGIME_LOW_ACTIVITY_THRESHOLD,
    REGIME_LOW_FAILURE,
    REGIME_LOW_FAILURE_THRESHOLD,
    REGIME_MEDIUM_ACTIVITY,
    REGIME_TIGHT_SPREAD,
    REGIME_TIGHT_SPREAD_THRESHOLD,
    REGIME_WIDE_SPREAD,
    REGIME_WIDE_SPREAD_THRESHOLD,
    TWO_LEG_BASELINE_NET_BPS,
    _build_blocker_summary,
    build_verdict_summary,
    classify_blocker_tags,
    classify_regime_bucket,
)

# --- Re-exports from m7.triangular.repeatability ---
from m7.triangular.repeatability import (  # noqa: F401
    build_blocker_repeatability,
    build_regime_repeatability_summary,
)

# --- Re-exports from m7.triangular.cli ---
from m7.triangular.cli import (  # noqa: F401
    _build_address_to_symbol,
    _calculate_starting_amount,
    _fee_distribution,
    _dex_distribution,
    _get_current_block,
    _load_pool_resolver_cache,
    _multi_dex_breakdown,
    _quote_single_leg,
    _score_measured,
    _sweep_cycle_sizes,
    build_graph_from_live_runtime,
    build_graph_from_resolver_cache,
    main,
    quote_cycle_3legs,
)

if __name__ == "__main__":
    sys.exit(main())
