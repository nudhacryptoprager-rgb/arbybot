#!/usr/bin/env python3
"""
M7.R1 extraction script: splits m7a_orderflow_replay.py into m7/orderflow/ modules.
Run once, then delete.
"""
import re
import textwrap
from pathlib import Path

SRC = Path("scripts/m7a_orderflow_replay.py")
DST = Path("m7/orderflow")

with open(SRC, "r", encoding="utf-8") as f:
    lines = f.readlines()

def extract(start, end):
    """Extract lines start..end (1-indexed, inclusive)."""
    return "".join(lines[start - 1 : end])


# ── events.py ──────────────────────────────────────────────────
events_header = '''\
"""
M7 orderflow event building, fetching, normalization, and loading.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    EVENT_TYPE_SWAP,
    M7A4_CHAIN,
    MIN_EVENT_SIZE_USD,
    SWAP_EVENT_TOPIC,
    DEFAULT_LIVE_BLOCKS,
)
from m7.orderflow.contracts import OrderflowEvent

logger = logging.getLogger("m7.orderflow.events")

'''
events_body = (
    extract(405, 504) + "\n\n"
    + extract(676, 720) + "\n\n"
    + extract(722, 827) + "\n\n"
    + extract(2858, 2870)
)
(DST / "events.py").write_text(events_header + events_body, encoding="utf-8")
print(f"events.py: {len((events_header + events_body).splitlines())} lines")


# ── resolve.py ─────────────────────────────────────────────────
resolve_header = '''\
"""
M7 orderflow token resolution, pool-address resolution, enrichment,
and pool-state extraction.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from m7.shared.constants import _DEFAULT_FEE_TIERS

logger = logging.getLogger("m7.orderflow.resolve")

'''
resolve_body = (
    extract(653, 659) + "\n\n"
    + extract(661, 674) + "\n\n"
    + extract(1059, 1115) + "\n\n"
    + extract(1123, 1180) + "\n\n"
    + extract(1391, 1421) + "\n\n"
    + extract(1423, 1459) + "\n\n"
    + extract(1564, 1586) + "\n\n"
    + extract(1854, 1863)
)
(DST / "resolve.py").write_text(resolve_header + resolve_body, encoding="utf-8")
print(f"resolve.py: {len((resolve_header + resolve_body).splitlines())} lines")


# ── coverage.py ────────────────────────────────────────────────
coverage_header = '''\
"""
M7 orderflow token admission, counter-venue coverage scanning,
and subgraph-backed token seeding.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from m7.shared.constants import (
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_SUBGRAPH_VERIFIED,
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_REJECTED,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_NO_COUNTER_POOL,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
    SUBGRAPH_ENDPOINTS_ARBITRUM,
    SUBGRAPH_SEED_TOKEN_CAP,
    SUBGRAPH_TIMEOUT_SECONDS,
    _DEFAULT_FEE_TIERS,
)
from m7.orderflow.resolve import (
    _resolve_pool_addresses_multicall,
    enrich_tokens_batch,
)

logger = logging.getLogger("m7.orderflow.coverage")

'''
coverage_body = (
    extract(1187, 1261) + "\n\n"
    + extract(1263, 1385) + "\n\n"
    + extract(1592, 1699)
)
(DST / "coverage.py").write_text(coverage_header + coverage_body, encoding="utf-8")
print(f"coverage.py: {len((coverage_header + coverage_body).splitlines())} lines")


# ── pricing.py ─────────────────────────────────────────────────
pricing_header = '''\
"""
M7 orderflow pricing: classification, estimation, simple live scoring,
gas decomposition, and size sweep.

The heavy parallel scoring pipeline lives in scoring_parallel.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    MIN_EVENT_SIZE_USD,
    SIGNIFICANT_IMPACT_BPS,
    REJECT_EVENT_TOO_SMALL,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_QUOTE_FAILURE,
    REJECT_STALE_POSITIVE,
    M7A4_CHAIN,
    _DEFAULT_FEE_TIERS,
    _FALLBACK_ETH_PRICE_USD,
    _REF_MIN_WEI_18,
    _REF_MAX_WEI_18,
)
from m7.orderflow.contracts import BackrunResult, OrderflowEvent

logger = logging.getLogger("m7.orderflow.pricing")

'''
pricing_body = (
    extract(213, 235) + "\n\n"
    + extract(237, 271) + "\n\n"
    + extract(510, 522) + "\n\n"
    + extract(524, 534) + "\n\n"
    + extract(540, 557) + "\n\n"
    + extract(559, 566) + "\n\n"
    + extract(568, 575) + "\n\n"
    + extract(833, 1052) + "\n\n"
    + extract(1701, 1728) + "\n\n"
    + extract(1730, 1852) + "\n\n"
    + extract(2657, 2684)
)
(DST / "pricing.py").write_text(pricing_header + pricing_body, encoding="utf-8")
print(f"pricing.py: {len((pricing_header + pricing_body).splitlines())} lines")


# ── scoring_parallel.py ───────────────────────────────────────
parallel_header = '''\
"""
M7 orderflow parallel scoring pipeline (score_backrun_live_parallel).

This is the main 3-stage pipeline: pair resolve + coverage scan + quote.
Extracted from the monolith due to size (~787 lines).
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    REJECT_EVENT_TOO_SMALL,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_QUOTE_FAILURE,
    REJECT_STALE_POSITIVE,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    REJECT_NO_COUNTER_POOL,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
    REJECT_ZERO_LIQUIDITY,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    ALL_REJECT_REASONS,
    UNSCORED_REJECTS,
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_SUBGRAPH_VERIFIED,
    CHAINLINK_FEEDS_ARBITRUM,
    _DEFAULT_FEE_TIERS,
    _FALLBACK_ETH_PRICE_USD,
    M7A4_CHAIN,
)
from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.pricing import (
    classify_event_backrun_type,
    _normalized_bounds,
    _gas_cost_in_token_wei,
    estimate_gas_decomposition_bps,
)
from m7.orderflow.resolve import (
    _resolve_event_tokens,
    _resolve_pool_addresses_multicall,
    enrich_tokens_batch,
)
from m7.orderflow.coverage import (
    admit_event_tokens,
    counter_venue_coverage_scan,
)
from m7.orderflow.pricing import check_oracle_sanity

logger = logging.getLogger("m7.orderflow.scoring_parallel")

'''
parallel_body = extract(1865, 2651)
(DST / "scoring_parallel.py").write_text(parallel_header + parallel_body, encoding="utf-8")
print(f"scoring_parallel.py: {len((parallel_header + parallel_body).splitlines())} lines")


# ── artifacts.py ───────────────────────────────────────────────
artifacts_header = '''\
"""
M7 orderflow artifact builders: offline scoring, intent surface
assessments, and the main replay summary aggregator.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    ALL_BLOCKER_TAGS,
    ALL_SURFACES,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
    M7A4_CHAIN,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_NO_COUNTER_POOL,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    SURFACE_BLOCK_BACKRUN,
    SURFACE_COW_SOLVER,
    SURFACE_MEV_SHARE_BACKRUN,
    SURFACE_UNISWAPX_FILLER,
    UNSCORED_REJECTS,
)
from m7.orderflow.contracts import (
    BackrunResult,
    IntentSurfaceAssessment,
    OrderflowEvent,
)
from m7.orderflow.pricing import (
    classify_event_backrun_type,
    classify_event_viability,
    estimate_backrun_gross_bps,
    estimate_fee_cost_bps,
    estimate_gas_cost_bps,
)

logger = logging.getLogger("m7.orderflow.artifacts")

'''
artifacts_body = (
    extract(577, 643) + "\n\n"
    + extract(2690, 2829) + "\n\n"
    + extract(2831, 2852) + "\n\n"
    + extract(2876, 3305)
)
(DST / "artifacts.py").write_text(artifacts_header + artifacts_body, encoding="utf-8")
print(f"artifacts.py: {len((artifacts_header + artifacts_body).splitlines())} lines")


# ── cli.py ─────────────────────────────────────────────────────
cli_header = '''\
"""
M7 orderflow CLI: argument parsing and mode orchestration.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from m7.shared.constants import (
    DEFAULT_LIVE_BLOCKS,
    M7A4_CHAIN,
    SWAP_EVENT_TOPIC,
)
from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.events import (
    build_fixture_events,
    fetch_recent_swap_events,
    load_events_from_file,
    normalize_swap_log,
)
from m7.orderflow.pricing import (
    score_backrun_live,
)
from m7.orderflow.scoring_parallel import score_backrun_live_parallel
from m7.orderflow.artifacts import (
    build_intent_scout_summary,
    build_intent_surface_assessments,
    build_replay_summary,
    score_backrun_offline,
)
from m7.orderflow.resolve import _build_address_to_symbol
from m7.orderflow.coverage import seed_tokens_from_subgraph

logger = logging.getLogger("m7.orderflow.cli")

'''
cli_body = extract(3310, 3382) + "\n\n" + extract(3384, 4443)
(DST / "cli.py").write_text(cli_header + cli_body, encoding="utf-8")
print(f"cli.py: {len((cli_header + cli_body).splitlines())} lines")


print("\nExtraction complete!")
