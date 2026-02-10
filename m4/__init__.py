"""
M4 Execution Gate Library

This module provides the core functionality for M4 gate validation,
broken out from the monolithic ci_m4_execution_gate.py script.

Modules:
- evidence: Git context, evidence attachment, dirty detection
- rolling_store: Rolling artifact persistence (aggregator, latest files)
- policy: Threshold profiles, warmup rules, DoD definitions
- fixtures: Fixture generation for offline/online testing
- gates: Gate runners and validation logic
- discovery: Artifact discovery helpers
- cli: Command-line interface

Usage:
    from m4.evidence import get_git_context, get_git_head_sha
    from m4.rolling_store import emit_to_aggregator_light
    from m4.policy import ThresholdProfile, PROFILES, DoDProfile
    from m4.gates import run_offline_gate, run_online_gate
    from m4.cli import main
"""

__version__ = "1.9.4"

# Re-export key functions for convenience
from .evidence import get_git_context, get_git_head_sha, is_evidence_ok
from .rolling_store import emit_to_aggregator_light, ensure_rolling_agg_exists
from .policy import (
    ThresholdProfile, 
    PROFILES, 
    WarmupConfig,
    DoDProfile,
    FailReason,
    Thresholds,
    get_cost_model,
)
from .discovery import find_latest_run_dir, discover_m4_artifacts
from .gates import run_offline_gate, run_online_gate, validate_gate
from .cli import main
