#!/usr/bin/env python3
# PATH: scripts/ci_m4_execution_gate.py
"""
M4 Execution Gate - DEX↔DEX Atomic Execution v1.

This is a thin wrapper around the m4 package. All implementation
details have been moved to the m4/ module.

VERSION: 1.9.3 (modular refactor)
STATUS: ACTIVE

CANONICAL COMMANDS:
    # Offline - synthetic fixtures (no RPC)
    python scripts/ci_m4_execution_gate.py --offline
    python scripts/ci_m4_execution_gate.py --offline --profile smoke
    python scripts/ci_m4_execution_gate.py --offline --profile profit

    # Online - real artifacts (requires prior scan/simulation run)
    python scripts/ci_m4_execution_gate.py --online --run-dir data/runs/<dir>
    python scripts/ci_m4_execution_gate.py --online --profile profit

EXIT CODES: 0=PASS, 1=FAIL validation, 2=NO_SIGNALS, 3=SIM_FAILED

See m4/ package for implementation details:
    - m4/policy.py: Thresholds, profiles, cost models  
    - m4/evidence.py: Git context, evidence tracking
    - m4/rolling_store.py: Rolling artifact persistence
    - m4/fixtures.py: Fixture generation
    - m4/gates.py: Gate runners and validation
    - m4/discovery.py: Artifact discovery
    - m4/cli.py: CLI and orchestration
"""

import sys
from pathlib import Path

# Ensure repository root is on sys.path for m4 package import
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Import version for backward compatibility
__version__ = "1.9.3"

# Re-export all public API for backward compatibility
# Policy and thresholds
from m4.policy import (
    FailReason,
    Thresholds,
    CostModelConfig,
    CostModelRegistry,
    get_cost_model,
    DoDProfile,
    ThresholdProfile,
    PROFILES,
    get_profile,
    WarmupConfig,
    DEFAULT_WARMUP,
    get_warmup_status,
    interpret_status,
    MIN_NET_PROFIT_USD,
    MAX_GAS_USD,
    MAX_SLIPPAGE_BPS,
    DEFAULT_CHAIN_ID,
    DEFAULT_PINNED_BLOCK,
)

# Evidence and git helpers
from m4.evidence import (
    get_git_head_sha,
    get_git_context,
    is_evidence_ok,
)

# Rolling store
from m4.rolling_store import (
    emit_to_aggregator_light,
    ensure_rolling_agg_exists,
    reset_rolling_window,
)

# Discovery
from m4.discovery import (
    find_latest_run_dir,
    discover_m4_artifacts,
)

# Fixtures
from m4.fixtures import (
    generate_m4_fixture,
    generate_m4_from_online_inputs,
)

# Gates
from m4.gates import (
    run_offline_gate,
    run_online_gate,
    validate_gate,
    validate_execution_report,
    validate_simulations,
    validate_block_consistency,
)

# CLI
from m4.cli import main, run_dry_run


# Legacy aliases for backward compatibility
def get_git_sha() -> str:
    """Legacy alias for get_git_head_sha."""
    return get_git_head_sha()


def get_source_sha() -> str:
    """DEPRECATED: Use get_git_context()['code_sha'] instead."""
    return get_git_head_sha()


if __name__ == "__main__":
    sys.exit(main())
