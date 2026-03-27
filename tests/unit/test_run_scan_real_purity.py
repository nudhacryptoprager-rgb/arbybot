# PATH: tests/unit/test_run_scan_real_purity.py
"""
Test that run_scan_real.py has no fixture/offline branches.

This test enforces the architectural rule that run_scan_real.py
is ONLY for real RPC orchestration - no fixture generation logic.

Fixture generation lives in:
- ci_m5_0_gate.py --offline
- ci_m4_execution_gate.py --offline
"""

import ast
from pathlib import Path


def test_run_scan_real_has_no_fixture_imports():
    """run_scan_real.py must not import fixture modules."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    
    # Forbidden import patterns
    forbidden = [
        "from tests.",
        "import tests.",
        "from strategy.fixtures",
        "import strategy.fixtures",
        "FIXTURE_OFFLINE",
        "generate_fixture",
    ]
    
    for pattern in forbidden:
        assert pattern not in content, \
            f"run_scan_real.py contains forbidden pattern: {pattern}"


def test_run_scan_real_has_no_offline_mode():
    """run_scan_real.py must not have --offline argument."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    
    # Check for --offline argument
    assert "--offline" not in content, \
        "run_scan_real.py must not have --offline argument"
    
    assert "offline" not in content.lower() or "ARBY_OFFLINE" in content, \
        "run_scan_real.py should not reference 'offline' mode"


def test_run_scan_real_has_expected_functions():
    """run_scan_real.py must have expected structure."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    tree = ast.parse(content)
    
    function_names = {
        node.name for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    
    # Expected core functions
    required = {"run_scan", "run_scanner", "main"}
    missing = required - function_names
    assert not missing, f"Missing expected functions: {missing}"


def test_run_scan_real_line_count():
    """run_scan_real.py should not grow excessively."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    assert path.exists(), f"File not found: {path}"
    
    content = path.read_text(encoding="utf-8")
    line_count = len(content.splitlines())
    
    # Current: ~1313 lines (v3.3.0: +113 for dynamic size sweep)
    # v3.3.1: +9 for compared_fee_tiers collection
    # R17: +6 for compared_fee_tiers_per_route
    # R28.5: +17 for expanded phase timers + COVERAGE sweep skip + multicall stats
    # R28.7: +14 for executable_candidates_count + sweep promotion to core decision
    # R28.11: +39 for hot_requote loading/saving + scan_mode + strategy_mode HOT_REQUOTE
    # R28.15: +105 for live execution probe (simulate_rpc + execute_live gated block)
    # R28.16: +30 for _emit_phase() helper + phase event emissions at boundaries
    # R28.22: +77 for compact live candidate stream builder + candidate_snapshot emission
    # R28.22b: +6 for is_actionable, spread_bps fallback, final_net_pnl_usd
    # R28.24: +48 for filter_funnel artifact + roundtrip_truth_status + config-driven caps
    # R28.27: +62 for cap-isolation toggles (_get_cap_isolation_switches + 3 application sites)
    # For now, just warn if it grows significantly
    max_lines = 1875  # R39v: +22 truth-lane reranking (measured economics priority)
    
    assert line_count <= max_lines, \
        f"run_scan_real.py has {line_count} lines (max: {max_lines}). Consider refactoring."


def test_run_scan_real_has_filter_funnel():
    """R28.24: run_scan_real.py must produce filter_funnel artifact."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")

    assert 'stats["filter_funnel"]' in content, "filter_funnel dict missing from stats"
    # Key stages must be present
    for key in ["resolved_pairs", "quotes_attempted", "quotes_fetched",
                "spread_signals", "opp_engine_combinations", "rt_passed_to_eval",
                "rt_evaluated", "rt_real_quote", "rt_profitable"]:
        assert f'"{key}"' in content, f"filter_funnel key '{key}' missing"


def test_run_scan_real_has_roundtrip_truth_status():
    """R28.24: run_scan_real.py must produce roundtrip_truth_status."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")

    assert 'stats["roundtrip_truth_status"]' in content
    for status in ["PROFITABLE", "EVALUATED_NOT_PROFITABLE", "NO_CANDIDATES"]:
        assert f'"{status}"' in content, f"roundtrip_truth_status value '{status}' missing"


def test_run_scan_real_config_driven_caps():
    """R28.24: Candidate caps must be config-driven, not hardcoded."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")

    assert "roundtrip_max_candidates" in content, "roundtrip_max_candidates config key missing"
    assert "roundtrip_top_n" in content, "roundtrip_top_n config key missing"


def test_filter_funnel_normalized_fields():
    """R28.30: filter_funnel must have stage-annotated keys and cross_dex_pairs_count."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")

    # R28.30: opp_candidates renamed to opp_engine_combinations for disambiguation
    assert '"opp_engine_combinations"' in content, "opp_engine_combinations key missing (was opp_candidates)"
    assert '"opp_candidates"' not in content, "legacy opp_candidates key should have been renamed"
    # R28.30: cross_dex_pairs_count injected from discovery_runtime
    assert '"cross_dex_pairs_count"' in content, "cross_dex_pairs_count key missing from filter_funnel"


def test_cross_dex_pairs_count_fallback_from_quotes():
    """R28.30+: cross_dex_pairs_count must fall back to quote-based computation for config/intent paths."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")

    # When discovery_runtime doesn't provide cross_dex_pairs_count (config/intent/hot path),
    # the funnel builder must compute it from quotes_sample by counting pairs with >=2 DEXes.
    assert "quotes_sample" in content and "_pair_dexes" in content, (
        "filter_funnel must compute cross_dex_pairs_count from quotes_sample "
        "when discovery_runtime is unavailable (config/intent path)"
    )


def test_start_funnel_accumulation_fields():
    """R28.30: chain_stats.py must accumulate funnel productivity counters.

    R33: Fields extracted from start.py to strategy/chain_stats.py.
    """
    path = Path(__file__).parent.parent.parent / "strategy" / "chain_stats.py"
    content = path.read_text(encoding="utf-8")

    for key in [
        "funnel_quotes_attempted_total",
        "funnel_quotes_fetched_total",
        "funnel_spread_signals_total",
        "funnel_rt_evaluated_total",
        "funnel_rt_real_quote_total",
    ]:
        assert key in content, f"chain_stats.py missing accumulated funnel field '{key}'"


def test_eligible_opps_initialized_before_conditional():
    """R33: eligible_opps must be initialized before `if opps_list:` to prevent
    UnboundLocalError when gated opps is empty but reprieve path needs it."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Find the line where eligible_opps = [] is initialized
    init_line = None
    conditional_line = None
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped == "eligible_opps = []" and init_line is None:
            init_line = i
        if "eligible_opps, _rt_filter_stats = select_roundtrip_candidates(" in stripped:
            conditional_line = i

    assert init_line is not None, (
        "eligible_opps = [] initialization not found in run_scan_real.py"
    )
    assert conditional_line is not None, (
        "select_roundtrip_candidates call not found in run_scan_real.py"
    )
    assert init_line < conditional_line, (
        f"eligible_opps = [] (line {init_line}) must come BEFORE "
        f"select_roundtrip_candidates (line {conditional_line})"
    )
