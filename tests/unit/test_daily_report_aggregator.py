import json
import tempfile
from pathlib import Path

from scripts.generate_daily_report import aggregate_run


def make_minimal_run(tmp_path: Path) -> Path:
    run = tmp_path / "run1"
    run.mkdir()
    # minimal scan
    scan = {"quotes_total": 2, "quotes_fetched": 2}
    # Add spread_signals for paper PnL calculation (new schema with paper estimates)
    truth = {
        "quotes_total": 2,
        "price_sanity_passed": 1,
        "pnl": {"net_pnl_usdc": 12.5},
        "health": {"rpc": {"success_rate": 1.0}},
        "spread_signals": [
            {
                "pair": "WETH/USDC",
                "spread_pct": 0.5,  # 0.5% 
                "spread_bps_exact": 50.0,
                "spread_bps_ui": 50,
                "size_usd": 1000,
                "gross_pnl_usdc_est": 5.0,
                "net_pnl_usdc_est": 3.9,  # gross - gas - slippage
                "is_gross_positive": True,
                "is_net_positive_est": True,
            },
            {
                "pair": "WETH/USDC",
                "spread_pct": 0.75,  # 0.75%
                "spread_bps_exact": 75.0,
                "spread_bps_ui": 75,
                "size_usd": 1000,
                "gross_pnl_usdc_est": 7.5,
                "net_pnl_usdc_est": 6.4,  # gross - gas - slippage
                "is_gross_positive": True,
                "is_net_positive_est": True,
            },
        ],  # Total gross = 12.5 USD
    }
    reject = {"rejects": [{"error": "deviation_exceeded"}, {"suspect_reason": "way_below_expected"}]}
    (run / "scan_1.json").write_text(json.dumps(scan))
    (run / "truth_report_1.json").write_text(json.dumps(truth))
    (run / "reject_histogram_1.json").write_text(json.dumps(reject))
    return run


def test_aggregate_minimal(tmp_path):
    run = make_minimal_run(tmp_path)
    rpt = aggregate_run(run)
    assert rpt["schema_version"] == "m5:daily:v1.3"  # v1.7.0: bumped for session completion fields
    assert rpt["runs_included"] == 1
    # v3.2.58: Session completion fields are now mandatory
    assert "session" in rpt
    assert rpt["session"]["goal_status"] == "IN_PROGRESS"
    assert rpt["session"]["close_allowed"] is False
    # M5 reports use paper_net_pnl_usdc calculated from spread_signals
    # gross = 5 + 7.5 = 12.5, gas_only gas = 0.10 → net = 12.40
    assert rpt.get("paper_net_pnl_usdc") == 12.40  # gas_only: 12.5 - 0.10
    assert rpt.get("paper_net_pnl_usdc_gas_only") == 12.40
    # realistic: 12.5 - 0.10 - slippage (2 signals * 1000 * 5bps = 1.0) = 11.40
    assert rpt.get("paper_net_pnl_usdc_realistic") == 11.40
    assert rpt.get("gross_spread_usdc") == 12.5
    assert rpt.get("spread_signals_count") == 2
    # Signals vs Opportunities counters
    assert rpt.get("signals_total") == 2
    assert rpt.get("opportunities_total") == 2  # both are net-positive
    # top_signal should have the best spread
    top_signal = rpt.get("top_signal")
    assert top_signal is not None
    # Now uses spread_bps_exact and spread_bps_ui
    assert top_signal.get("spread_bps_exact") == 75.0  # best one
    assert top_signal.get("spread_bps_ui") == 75
    assert isinstance(rpt["top_reject_reasons"], list)


def test_session_context_propagation(tmp_path):
    """Test that session_context is properly propagated to the report."""
    run = make_minimal_run(tmp_path)
    session_context = {
        "session_goal": "Test session goal",
        "goal_status": "REACHED",
        "close_allowed": True,
        "remaining_blockers": [],
        "evidence_session_run_dirs": ["run1", "run2"],
    }
    rpt = aggregate_run(run, session_context=session_context)
    
    session = rpt.get("session")
    assert session is not None
    assert session["session_goal"] == "Test session goal"
    assert session["goal_status"] == "REACHED"
    assert session["close_allowed"] is True
    assert session["remaining_blockers"] == []
    assert session["evidence_session_run_dirs"] == ["run1", "run2"]


def test_session_context_defaults_when_none(tmp_path):
    """Test that session defaults are used when session_context is None."""
    run = make_minimal_run(tmp_path)
    rpt = aggregate_run(run)
    
    session = rpt.get("session")
    assert session is not None
    assert session["session_goal"] is None
    assert session["goal_status"] == "IN_PROGRESS"
    assert session["close_allowed"] is False
    assert session["remaining_blockers"] == []
    # Default evidence_session_run_dirs should contain the run directory name
    assert "run1" in session["evidence_session_run_dirs"][0]


def test_session_context_blocked_state(tmp_path):
    """Test session context with BLOCKED state."""
    run = make_minimal_run(tmp_path)
    session_context = {
        "session_goal": "Blocked session",
        "goal_status": "BLOCKED",
        "close_allowed": False,
        "remaining_blockers": ["RPC unreachable", "DEX offline"],
    }
    rpt = aggregate_run(run, session_context=session_context)
    
    session = rpt.get("session")
    assert session["goal_status"] == "BLOCKED"
    assert session["close_allowed"] is False
    assert len(session["remaining_blockers"]) == 2
    assert "RPC unreachable" in session["remaining_blockers"]


def test_theoretical_net_profit_m4_sim_field(tmp_path):
    """Test that m4_sim_net_usdc field is present (None when no execution_report)."""
    run = make_minimal_run(tmp_path)
    rpt = aggregate_run(run)
    
    tnp = rpt.get("theoretical_net_profit")
    assert tnp is not None
    # m4_sim_net_usdc should be present (None when no execution_report exists)
    assert "m4_sim_net_usdc" in tnp
    assert "m4_execution_report_path" in tnp


def test_m4_sim_net_usdc_with_execution_report(tmp_path):
    """Test that m4_sim_net_usdc is populated when execution_report exists."""
    run = make_minimal_run(tmp_path)
    
    # Add an execution_report
    exec_report = {
        "schema_version": "m4:execution:v1",
        "total_net_usdc": 3.0586,
        "simulations_count": 1,
        "simulations_passed": 1,
    }
    (run / "execution_report_20260309.json").write_text(json.dumps(exec_report))
    
    rpt = aggregate_run(run)
    
    tnp = rpt.get("theoretical_net_profit")
    assert tnp is not None
    assert tnp["m4_sim_net_usdc"] == 3.0586
    assert tnp["m4_execution_report_path"] is not None


def test_session_blocker_fields_propagation(tmp_path):
    """Test that v1.8.0 blocker fields are properly propagated to the report."""
    run = make_minimal_run(tmp_path)
    session_context = {
        "session_goal": "Resolve multi-chain signals",
        "goal_status": "REACHED",
        "close_allowed": True,
        "remaining_blockers": [],
        "evidence_session_run_dirs": ["run1"],
        "primary_blocker_of_session": "multi-chain signal production",
        "blocker_status_before": "ACTIVE",
        "blocker_status_after": "RESOLVED",
        "docs_reread_confirmed": True,
    }
    rpt = aggregate_run(run, session_context=session_context)
    
    session = rpt.get("session")
    assert session is not None
    assert session["primary_blocker_of_session"] == "multi-chain signal production"
    assert session["blocker_status_before"] == "ACTIVE"
    assert session["blocker_status_after"] == "RESOLVED"
    assert session["docs_reread_confirmed"] is True


def test_session_blocker_fields_defaults_when_none(tmp_path):
    """Test that blocker fields default to None/False when session_context is None."""
    run = make_minimal_run(tmp_path)
    rpt = aggregate_run(run)
    
    session = rpt.get("session")
    assert session is not None
    assert session["primary_blocker_of_session"] is None
    assert session["blocker_status_before"] is None
    assert session["blocker_status_after"] is None
    assert session["docs_reread_confirmed"] is False


def test_session_blocker_blocked_state(tmp_path):
    """Test blocker fields with BLOCKED status (session cannot close yet)."""
    run = make_minimal_run(tmp_path)
    session_context = {
        "session_goal": "Resolve zkSync NO_DATA",
        "goal_status": "BLOCKED",
        "close_allowed": False,
        "remaining_blockers": ["zkSync RPC unreliable"],
        "primary_blocker_of_session": "zkSync signal production",
        "blocker_status_before": "ACTIVE",
        "blocker_status_after": "BLOCKED",
        "docs_reread_confirmed": True,
    }
    rpt = aggregate_run(run, session_context=session_context)
    
    session = rpt.get("session")
    assert session["goal_status"] == "BLOCKED"
    assert session["close_allowed"] is False
    assert session["blocker_status_after"] == "BLOCKED"
    # Even when blocked, docs_reread_confirmed should be true
    assert session["docs_reread_confirmed"] is True
