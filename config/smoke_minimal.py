"""
config/smoke_minimal.py - Minimal SMOKE configuration.

Team Lead Крок 4:
"Зменшити SMOKE навантаження: 1–2 пари, 2 DEX, 1 fee tier, 1 fixed amount_in.
Поки не зникне GATES_CHANGED масово."

Team Lead Update (2026-01-16):
"Викинь/заміни wstETH/WETH зі smoke_minimal — вона генерує купу 'очікуваних' фейлів (ticks+gas)."

This config provides:
- Minimal pairs (2) - NO wstETH/WETH (токсична пара для smoke)
- Minimal DEXes (2)
- Single fee tier (500 = 0.05%)
- Fixed amount_in (0.1 ETH)
"""

# =============================================================================
# SMOKE MINIMAL CONFIG
# =============================================================================

SMOKE_MINIMAL = {
    # Pairs: only 2 well-understood pairs
    # EXCLUDED: wstETH/WETH (generates expected fails: ticks+gas too high)
    "pairs": [
        "WETH/USDC",
        "WETH/ARB",
    ],
    
    # Toxic pairs to exclude from smoke (generate expected fails)
    "excluded_pairs": [
        "wstETH/WETH",  # High ticks (16-20), high gas (500k-846k)
        "WETH/wstETH",
    ],
    
    # DEXes: only 2 most reliable
    "dexes": [
        "uniswap_v3",
        "sushiswap_v3",
    ],
    
    # Fee tiers: only 500 (0.05%)
    "fee_tiers": [500],
    
    # Amount: fixed 0.1 ETH
    "amount_in_wei": 10**17,  # 0.1 ETH
    
    # No size ladder in minimal mode
    "use_size_ladder": False,
    
    # Cycles
    "cycles": 10,
    "interval_seconds": 5,
    
    # Revalidation: strict mode
    "revalidation": {
        "same_block": True,       # Use pinned block for revalidation
        "static_gas_price": True,  # Don't recalculate gas
        "same_anchor": True,       # Use same anchor from original quote
    },
    
    # Team Lead: Paper trading mode ignores verified_for_execution
    "paper_trading": {
        "ignore_verification": True,  # Allow execution_ready in paper mode
        "log_blocked_reason": True,   # Log "blocked_by_verification" for real mode
    },
    
    # Team Lead Крок 9: Notion capital for PnL normalization
    # "прив'яжи до фіксованого notion-capital або перестань показувати cumulative у SMOKE"
    "notion_capital_usdc": 10000.0,  # $10k notional for SMOKE mode
}


# =============================================================================
# M3 PROGRESSION KPI RULES (Team Lead Крок 10)
# =============================================================================

M3_KPI_RULES = {
    # Required minimums
    "rpc_success_rate_min": 0.8,
    "quote_fetch_rate_min": 0.7,
    "gate_pass_rate_min": 0.4,
    
    # Revalidation stability
    "gates_changed_pct_max": 5.0,  # GATES_CHANGED < 5% in smoke
    
    # Invariant checks
    "invariants_required": True,
    
    # Execution readiness (for M4)
    "execution_ready_min": 0,  # M3 allows 0, M4 requires > 0
}


def check_m3_kpi(truth_report_dict: dict) -> dict:
    """
    Check if KPI rules are met for M3 progression.
    
    Args:
        truth_report_dict: TruthReport.to_dict() result
    
    Returns:
        dict with:
        - passed: bool
        - violations: list[str]
        - metrics: dict of actual values
    """
    violations = []
    metrics = {}
    
    # Extract health metrics
    health = truth_report_dict.get("health", {})
    revalidation = truth_report_dict.get("revalidation", {})
    
    rpc_success = health.get("rpc_success_rate", 0)
    quote_fetch = health.get("quote_fetch_rate", 0)
    gate_pass = health.get("quote_gate_pass_rate", 0)
    gates_changed_pct = revalidation.get("gates_changed_pct", 0)
    
    metrics["rpc_success_rate"] = rpc_success
    metrics["quote_fetch_rate"] = quote_fetch
    metrics["gate_pass_rate"] = gate_pass
    metrics["gates_changed_pct"] = gates_changed_pct
    
    # Check rules
    if rpc_success < M3_KPI_RULES["rpc_success_rate_min"]:
        violations.append(
            f"rpc_success_rate {rpc_success:.1%} < {M3_KPI_RULES['rpc_success_rate_min']:.1%}"
        )
    
    if quote_fetch < M3_KPI_RULES["quote_fetch_rate_min"]:
        violations.append(
            f"quote_fetch_rate {quote_fetch:.1%} < {M3_KPI_RULES['quote_fetch_rate_min']:.1%}"
        )
    
    if gate_pass < M3_KPI_RULES["gate_pass_rate_min"]:
        violations.append(
            f"gate_pass_rate {gate_pass:.1%} < {M3_KPI_RULES['gate_pass_rate_min']:.1%}"
        )
    
    if gates_changed_pct > M3_KPI_RULES["gates_changed_pct_max"]:
        violations.append(
            f"gates_changed_pct {gates_changed_pct:.1f}% > {M3_KPI_RULES['gates_changed_pct_max']:.1f}%"
        )
    
    # Check invariants
    invariant_violations = truth_report_dict.get("invariant_violations", [])
    if invariant_violations and M3_KPI_RULES["invariants_required"]:
        violations.extend(invariant_violations)
    
    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "metrics": metrics,
    }


def print_kpi_status(kpi_result: dict) -> None:
    """Print KPI status to console."""
    print("\n" + "=" * 50)
    print("M3 KPI STATUS")
    print("=" * 50)
    
    status = "✅ PASSED" if kpi_result["passed"] else "❌ FAILED"
    print(f"Status: {status}")
    
    print("\nMetrics:")
    for key, value in kpi_result["metrics"].items():
        if "rate" in key:
            print(f"  {key}: {value:.1%}")
        else:
            print(f"  {key}: {value}")
    
    if kpi_result["violations"]:
        print("\nViolations:")
        for v in kpi_result["violations"]:
            print(f"  ❌ {v}")
    
    print("=" * 50)
