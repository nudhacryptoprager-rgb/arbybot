"""
M4 Policy Module

Threshold profiles, warmup rules, and Definition of Done (DoD).

Profiles:
- smoke: Minimal thresholds for testing
- profit: Production thresholds for profitable trading

Schema:
- Profiles define MAE thresholds, sample size requirements, and warmup rules
- Warmup phase requires min_runs and min_signals before stability metrics are trusted
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional


# ============================================================
# FAIL REASON CODES (explicit definitions)
# ============================================================

class RunKind:
    """
    Run kind classification for segmented aggregation.
    
    v1.11.0: Rolling KPI segmentation by run purpose.
    - NORMAL: Regular online continuous scan (counted in main rolling KPIs)
    - COVERAGE: Coverage collection runs (harness mode, separate KPIs)
    - SMOKE: Smoke test runs (offline/fixture, separate KPIs)
    - OFFLINE: Offline fixture runs (not counted in main KPIs)
    """
    NORMAL = "NORMAL"      # Regular online scan
    COVERAGE = "COVERAGE"  # Coverage batch collection
    SMOKE = "SMOKE"        # Smoke test
    OFFLINE = "OFFLINE"    # Offline fixture


class ChainQualityLevel:
    """
    Chain quality classification based on operational maturity.
    
    v2.0.9: Quality-raised chain contract for multi-chain readiness assessment.
    
    Levels (ascending order):
    - INFRA_READY: Infra gate PASS (artifacts valid, quotes_fetched > 0)
    - SIGNAL_PRODUCING: At least 1 signal in current run (not NO_DATA)
    - QUALITY_RAISED: Repeated non-NO_DATA results across MIN_CYCLES_FOR_QUALITY_RAISED cycles
    
    TERMINOLOGY CONTRACT:
    - infra_gate: Artifacts schema valid, quotes_fetched > 0 -> INFRA_READY
    - run_summary.status != NO_DATA -> SIGNAL_PRODUCING
    - Consecutive non-NO_DATA cycles >= 3 -> QUALITY_RAISED
    
    USAGE:
        level = classify_chain_quality(signals_count=5, consecutive_non_nodata_cycles=3)
        # level == ChainQualityLevel.QUALITY_RAISED
    """
    INFRA_READY = "INFRA_READY"            # Gate PASS, but NO_DATA (0 signals)
    SIGNAL_PRODUCING = "SIGNAL_PRODUCING"  # >=1 signal, but not yet stable
    QUALITY_RAISED = "QUALITY_RAISED"      # Repeated non-NO_DATA across cycles


# Chain quality classification thresholds
MIN_CYCLES_FOR_QUALITY_RAISED = 3  # v2.0.9: Minimum consecutive non-NO_DATA cycles
MIN_SIGNALS_FOR_QUALITY_RAISED = 3  # v3.2.56: Minimum signals per cycle for QUALITY_RAISED
MAX_FRAGILE_RATE_FOR_QUALITY_RAISED = 0.50  # v3.2.56: Max fragile_rate for QUALITY_RAISED
MIN_DIVERSITY_FOR_QUALITY_RAISED = 2  # v3.2.56: Min unique pairs for QUALITY_RAISED


def classify_chain_quality(
    signals_count: int,
    consecutive_non_nodata_cycles: int = 1,
    infra_gate_pass: bool = True,
    fragile_rate: float = 0.0,
    unique_pairs: int = 0,
    net_profit_usdc: float = 0.0,
) -> str:
    """
    Classify chain quality level based on signal production maturity.
    
    v3.2.56: Enhanced with quality metrics for QUALITY_RAISED path.
    
    QUALITY_RAISED REQUIREMENTS (all must be met):
    1. consecutive_non_nodata_cycles >= MIN_CYCLES_FOR_QUALITY_RAISED (3)
    2. signals_count >= MIN_SIGNALS_FOR_QUALITY_RAISED (3)
    3. fragile_rate <= MAX_FRAGILE_RATE_FOR_QUALITY_RAISED (0.50)
    4. unique_pairs >= MIN_DIVERSITY_FOR_QUALITY_RAISED (2)
    5. net_profit_usdc > 0 (must be profitable)
    
    Args:
        signals_count: Number of signals in current run
        consecutive_non_nodata_cycles: Number of consecutive runs with signals_count > 0
        infra_gate_pass: Whether infra gate passed (artifacts valid, quotes fetched)
        fragile_rate: Fraction of simulations that are fragile (0.0-1.0)
        unique_pairs: Number of unique token pairs producing signals
        net_profit_usdc: Total net profit in USDC
        
    Returns:
        ChainQualityLevel constant
        
    Examples:
        # Chain just passed infra gate but no signals
        classify_chain_quality(signals_count=0, consecutive_non_nodata_cycles=0)
        # -> INFRA_READY
        
        # Chain produced signal but first time
        classify_chain_quality(signals_count=2, consecutive_non_nodata_cycles=1)
        # -> SIGNAL_PRODUCING
        
        # Chain consistently produces signals with quality
        classify_chain_quality(
            signals_count=5, 
            consecutive_non_nodata_cycles=3,
            fragile_rate=0.20,
            unique_pairs=3,
            net_profit_usdc=0.10
        )
        # -> QUALITY_RAISED
        
        # Chain produces signals but too fragile
        classify_chain_quality(
            signals_count=5, 
            consecutive_non_nodata_cycles=3,
            fragile_rate=0.70,  # > 0.50
            unique_pairs=3,
            net_profit_usdc=0.10
        )
        # -> SIGNAL_PRODUCING (fragile_rate too high)
    """
    if not infra_gate_pass:
        # Infra gate failed - shouldn't reach here but return lowest level
        return ChainQualityLevel.INFRA_READY
    
    if signals_count == 0:
        # NO_DATA run - infra works but no signals
        return ChainQualityLevel.INFRA_READY
    
    # signals_count > 0
    # Basic criterion (v2.0.9): consecutive non-NO_DATA cycles
    if consecutive_non_nodata_cycles < MIN_CYCLES_FOR_QUALITY_RAISED:
        return ChainQualityLevel.SIGNAL_PRODUCING
    
    # v3.2.56: Enhanced QUALITY_RAISED path (opt-in when quality metrics provided)
    # If quality metrics are tracked (non-default values), enforce additional criteria
    quality_metrics_tracked = (
        fragile_rate > 0.0 or 
        unique_pairs > 0 or 
        net_profit_usdc != 0.0
    )
    
    if quality_metrics_tracked:
        quality_criteria_met = (
            signals_count >= MIN_SIGNALS_FOR_QUALITY_RAISED and
            fragile_rate <= MAX_FRAGILE_RATE_FOR_QUALITY_RAISED and
            unique_pairs >= MIN_DIVERSITY_FOR_QUALITY_RAISED and
            net_profit_usdc > 0
        )
        if not quality_criteria_met:
            return ChainQualityLevel.SIGNAL_PRODUCING
    
    return ChainQualityLevel.QUALITY_RAISED


class FailReason:
    """
    Explicit fail reason codes for M4 execution gate.
    
    These codes are used in run_summary.json.reasons[] to explain FAIL/WARN status.
    Each reason corresponds to a specific threshold violation.
    
    TAXONOMY CONTRACT (v1.12.0):
    - FAIL_* reasons -> status MUST be FAIL (enforced by compute_status)
    - WARN_* reasons -> status may be PASS with quality_status=WARN
    - BLOCK_* reasons -> deprecated, use FAIL_* or WARN_* only
    - NO_DATA -> ONLY when signals_count == 0
    
    STATUS CONTRACT (v1.11.0):
    - NO_DATA: ONLY when signals_count == 0 (no signals at all)
    - profit_status: PASS (net>0) / FAIL (net<=0) - independent of sample size
    - quality_status: PASS / WARN_LOW_SAMPLE (<min_signals) / FAIL_QUALITY (fragile/drift)
    - Overall status: PASS if profit_status=PASS AND quality_status != FAIL_QUALITY
    
    v1.5.0: mae_fail is now > 0.50 (exclusive), not >= 0.50
    v1.7.0: Added WARN_LOW_SAMPLE for insufficient signals
    """
    # FAIL conditions (profit_status) - require status=FAIL
    FAIL_NET = "FAIL_NET"                        # total_net_usdc <= 0 (PROFIT profile)
    FAIL_NO_PROFITABLE = "FAIL_NO_PROFITABLE"    # sim_profitable_count == 0
    
    # FAIL conditions (drift_status) - require status=FAIL
    FAIL_DRIFT_MAE = "FAIL_DRIFT_MAE"            # mae_net_usdc > MAE_FAIL
    FAIL_DRIFT_SIGN = "FAIL_DRIFT_SIGN"          # sign_correct_rate < SIGN_RATE_MIN
    FAIL_SIGN_MISMATCH = "FAIL_SIGN_MISMATCH"    # sign_mismatch_count > 0 (strict mode)
    
    # FAIL conditions (quality_status) - require status=FAIL
    FAIL_FRAGILE_HIGH = "FAIL_FRAGILE_HIGH"      # fragile_rate > AGG_FRAGILE_P90_FAIL
    FAIL_EVIDENCE_DIRTY = "FAIL_EVIDENCE_DIRTY"  # v1.12.0: dirty worktree with --require-clean
    
    # WARN conditions - status may be PASS
    WARN_DRIFT_MAE = "WARN_DRIFT_MAE"            # MAE_WARN < mae <= MAE_FAIL
    WARN_LOW_SAMPLE = "WARN_LOW_SAMPLE"          # signals_count < MIN_SAMPLE_SIZE (v1.7.0)
    WARN_AGG_WARMUP = "WARN_AGG_WARMUP"          # runs_in_window < MIN_RUNS_FOR_AGG (v1.8.0)
    WARN_FRAGILE_ELEVATED = "WARN_FRAGILE_ELEVATED"  # v1.12.0: elevated but not failing
    WARN_DIVERSITY_LOW = "WARN_DIVERSITY_LOW"    # v1.12.0: low pair/route diversity


def compute_status(
    signals_count: int,
    total_net_usdc: float,
    mae_net_usdc: float = 0,
    sign_rate: float = 1.0,
    fragile_rate: float = 0,
    code_dirty: bool = False,
    require_clean: bool = False,
) -> dict:
    """
    Single source of truth for status computation.
    
    This function MUST be used by both run_summary generation and rolling_agg
    to ensure taxonomy consistency (FAIL_* -> status=FAIL invariant).
    
    Args:
        signals_count: Number of signals in run
        total_net_usdc: Total net PnL in USDC
        mae_net_usdc: Mean absolute error vs simulation
        sign_rate: Correct sign prediction rate
        fragile_rate: Fraction of fragile simulations
        code_dirty: Whether code has uncommitted changes
        require_clean: Whether clean worktree is required
        
    Returns:
        dict with keys:
        - status: "NO_DATA" | "PASS" | "FAIL"
        - profit_status: "NO_DATA" | "PASS" | "FAIL"
        - drift_status: "NO_DATA" | "PASS" | "WARN" | "FAIL"
        - quality_status: "NO_DATA" | "PASS" | "WARN" | "FAIL_QUALITY"
        - reasons: list of reason codes (guaranteed FAIL_* only if status=FAIL)
    """
    reasons = []
    
    # NO_DATA: only when signals_count == 0
    if signals_count == 0:
        return {
            "status": "NO_DATA",
            "profit_status": "NO_DATA",
            "drift_status": "NO_DATA",
            "quality_status": "NO_DATA",
            "reasons": ["NO_DATA"],
        }
    
    # === PROFIT STATUS ===
    if total_net_usdc > 0:
        profit_status = "PASS"
    else:
        profit_status = "FAIL"
        reasons.append(FailReason.FAIL_NET)
    
    # === DRIFT STATUS ===
    drift_status = "PASS"
    if mae_net_usdc > Thresholds.MAE_FAIL:
        drift_status = "FAIL"
        reasons.append(FailReason.FAIL_DRIFT_MAE)
    elif mae_net_usdc > Thresholds.MAE_WARN:
        drift_status = "WARN"
        reasons.append(FailReason.WARN_DRIFT_MAE)
    
    if sign_rate < Thresholds.SIGN_RATE_MIN:
        drift_status = "FAIL"
        reasons.append(FailReason.FAIL_DRIFT_SIGN)
    
    # === QUALITY STATUS ===
    quality_status = "PASS"
    
    # Low sample check (WARN, not FAIL)
    if signals_count < Thresholds.MIN_SIGNALS_FOR_PASS:
        quality_status = "WARN"
        reasons.append(FailReason.WARN_LOW_SAMPLE)
    
    # Fragile rate check
    if fragile_rate > Thresholds.AGG_FRAGILE_P90_FAIL:
        quality_status = "FAIL_QUALITY"
        reasons.append(FailReason.FAIL_FRAGILE_HIGH)
    elif fragile_rate > Thresholds.AGG_FRAGILE_P90_WARN:
        if quality_status != "FAIL_QUALITY":
            quality_status = "WARN"
        reasons.append(FailReason.WARN_FRAGILE_ELEVATED)
    
    # Dirty worktree check
    if require_clean and code_dirty:
        quality_status = "FAIL_QUALITY"
        reasons.append(FailReason.FAIL_EVIDENCE_DIRTY)
    
    # === OVERALL STATUS ===
    # INVARIANT: status=FAIL if any FAIL_* in reasons
    has_fail_reason = any(r.startswith("FAIL_") for r in reasons)
    
    if has_fail_reason:
        status = "FAIL"
    elif profit_status == "PASS" and quality_status != "FAIL_QUALITY":
        status = "PASS"
    else:
        status = "FAIL"
    
    # TAXONOMY ENFORCEMENT: Remove FAIL_* from reasons if status != FAIL
    # This should never happen due to logic above, but enforce as contract
    if status != "FAIL":
        reasons = [r for r in reasons if not r.startswith("FAIL_")]
    
    return {
        "status": status,
        "profit_status": profit_status,
        "drift_status": drift_status,
        "quality_status": quality_status,
        "reasons": reasons,
    }


# ============================================================
# THRESHOLDS (centralized, v1.5.0)
# ============================================================

# Policy version for artifact provenance
# v2.0.4: SUSPECT_SPREAD exclusion from metrics (is_excluded_spread signals don't count in DoD)
# v2.0.7: Taxonomy bug fix - WARN_* reasons no longer trigger FAIL_QUALITY
#         + Removed substring "HIGH" matching for quality_status (only FAIL_* prefix triggers FAIL_QUALITY)
#         + Added regression test test_warn_reasons_do_not_trigger_fail_quality
# v2.0.6: Status domain unification - combined_status now NO_DATA|PASS|FAIL only (WARN belongs in quality_status)
#         + pass_rate semantic alignment (runs_since_timestamp matches quick_stats definition)
#         + data_signals_total uses included-based sum, ASCII normalization in comments
#         + TOP_PAIR_NET_SHARE concentration check (>60% warn, >80% fail)
# v2.0.5: NO_DATA domain fix (only when included=0), quality_status domain (NO_DATA|PASS|WARN|FAIL_QUALITY)
#         + TOP_PAIR_DOMINANCE gated (>=MIN_SIGNALS_FOR_PASS, >=2 pairs), FAIL_* tokens downgraded when status!=FAIL
# v2.0.4: SUSPECT_SPREAD exclusion from DoD metrics (is_excluded_spread=true)
# v2.0.3: SUSPECT_SPREAD detection (spread > 300bps = suspicious, > 500bps = excluded)
# v2.0.2: SHA-free provenance (run_timestamp + code_identity replaces source_sha)
# v2.0.1: MIN_SIGNALS_FOR_PASS=3, MIN_SAMPLE_SIZE=3, MIN_SIGNALS_WARN=2
# v2.0.8: fee_tier strict lookup, quotes_total=attempted, unique_routes_cross_dex, price_stability order fix
# v2.0.9: ChainQualityLevel classification (INFRA_READY/SIGNAL_PRODUCING/QUALITY_RAISED)
POLICY_VERSION = "2.0.9"

class Thresholds:
    """
    Centralized threshold definitions for drift metrics.
    
    v2.0.2 PROVENANCE CHANGE (2026-02-13):
    - SHA tracking completely removed from all artifacts
    - Provenance now: run_timestamp (ISO-8601) + code_identity ("ts:...")
    - source_sha field removed from execution_report, signals, stability
    
    v2.0.1 POLICY CHANGE (2026-02-12):
    - MIN_SIGNALS_FOR_PASS lowered from 5 to 3 (real market conditions)
    - MIN_SAMPLE_SIZE lowered from 5 to 3
    - MIN_SIGNALS_WARN lowered from 3 to 2
    - KPI data_run_rate/low_sample_rate now use threshold 3
    - WARN_QUALITY (only DIVERSITY_*) accepted as PASS-equivalent for M4.1
    
    v1.12.0 TAXONOMY CONTRACT:
    - FAIL_* in reasons -> status MUST be FAIL (enforced by compute_status)
    - Use compute_status() for all status decisions (single source of truth)
    - AGG thresholds now "bite": > threshold -> FAIL, not just WARN
    
    v1.11.0 STATUS CONTRACT:
    - NO_DATA: ONLY when signals_count == 0 (no signals at all)
    - Signals >= 1 -> profit/drift evaluated normally
    - Signals < MIN_SIGNALS_FOR_PASS -> quality_status=WARN_LOW_SAMPLE (not NO_DATA)
    
    v1.8.1 CALIBRATION (based on 20 online runs, 56 signals):
    - MAE_WARN raised from 0.30 -> 0.55 to account for systematic slippage=$0.50
    - MAE_FAIL raised from 0.50 -> 0.80 to allow slippage + small model error
    - SIGN_RATE_MIN lowered from 0.70 -> 0.60 to allow 2/3 for small samples
    
    Rationale: mae=0.50 is expected when slippage=$0.50. This is not model error.
    """
    # === Drift thresholds (per-run) ===
    MAE_WARN = 0.55      # mae > 0.55 triggers WARN (above typical slippage)
    MAE_FAIL = 0.80      # mae > 0.80 triggers FAIL (significant model error)
    SIGN_RATE_MIN = 0.60  # sign_rate < 0.60 triggers FAIL (allows 2/3)
    
    # Slippage component (for mae_no_slippage calculation)
    SLIPPAGE_SYSTEMATIC_FACTOR = 1.0  # per-signal slippage adds to expected drift
    
    # === Sample size thresholds (v1.11.0 SEMANTIC FIX) ===
    # NO_DATA: ONLY when signals_count == 0
    # WARN_LOW_SAMPLE: signals > 0 but < MIN_SIGNALS_FOR_PASS
    MIN_SAMPLE_SIZE = 3           # v2.0.1: lowered from 5 to match real market conditions
    MIN_SIGNALS_FOR_PASS = 3      # v2.0.1: lowered from 5 (real config produces ~3 signals)
    MIN_SIGNALS_COVERAGE = 3      # v1.10.0: coverage-mode threshold (diagnostic)
    MIN_SIGNALS_WARN = 2          # v2.0.1: lowered to match new MIN_SIGNALS_FOR_PASS
    
    # Rolling window for aggregator (v1.7.0)
    ROLLING_WINDOW_DEFAULT = 50   # Default rolling window for aggregator
    ROLLING_WINDOW_MAX = 200      # Max window for extended analysis
    
    # === Aggregator-level thresholds (v1.12.0 "BITE") ===
    # v1.12.0: Thresholds that actually trigger FAIL, not just WARN
    AGG_MAE_P90_FAIL = 0.85           # FAIL if p90(MAE) > 0.85
    AGG_WARN_RATE_FAIL = 0.60         # FAIL if warn_rate_core > 60%
    AGG_FAIL_RATE_FAIL = 0.15         # v1.12.0: FAIL if fail_rate > 15% (was 40%, never bit)
    AGG_LOW_SAMPLE_RATE_WARN = 0.50   # WARN if low_sample_rate > 50%
    AGG_LOW_SAMPLE_RATE_FAIL = 0.80   # FAIL_QUALITY if low_sample_rate > 80%
    
    # Warm-up thresholds (v1.8.0) - aggregator needs minimum data before hard FAIL
    MIN_RUNS_FOR_AGG = 10         # < 10 runs -> PASS_WITH_WARMUP instead of FAIL
    MIN_SIGNALS_FOR_AGG = 30      # < 30 total signals -> warn thresholds relaxed
    
    # Fragile rate thresholds (v1.9.7) - enforced in agg status
    AGG_FRAGILE_P50_WARN = 0.40   # v1.9.7: early signal when median is elevated
    AGG_FRAGILE_P90_WARN = 0.30   # WARN if p90(fragile_rate) > 30%
    AGG_FRAGILE_P90_FAIL = 0.50   # FAIL_QUALITY if p90(fragile_rate) > 50%
    
    # v1.12.0: Data run rate thresholds (% of NORMAL runs with >= MIN_SIGNALS_FOR_PASS)
    # This is the PRIMARY operational gate for continuous scan
    AGG_DATA_RUN_RATE_WARN = 0.50  # WARN if data_run_rate < 50%
    AGG_DATA_RUN_RATE_FAIL = 0.30  # FAIL_QUALITY if data_run_rate < 30%
    
    # v1.12.0: Diversity thresholds (FAIL, not just WARN)
    # ============================================================================
    # DIVERSITY_PAIRS_TARGET RESTORE CONTRACT (v2.9.4):
    # ============================================================================
    # Currently: 6 (reduced from 8 in v2.9.3)
    # 
    # ROOT CAUSE ANALYSIS (2026-02-28 slot0 diagnostic):
    # SushiSwap pools return VALID prices via slot0. E.g.:
    #   - sushi ARB/WETH fee=500: token0=WETH, token1=ARB
    #   - slot0 price: ~20555 ARB/WETH (correct: 1 WETH = 20,555 ARB)
    # The "inverted quotes" issue is in OUR direction-aware price_sanity logic,
    # NOT in the pools themselves. Fix: dex/adapters/<sushi> slot0 interpretation.
    #
    # RESTORE TO 8 WHEN:
    #   (a) Fix direction-aware slot0/price_sanity interpretation bug, OR
    #   (b) 2+ new cross-DEX pairs added with working quoter_v2 on both DEXes
    # TRACKING: DEV_REPORT_LATEST.md documents affected pools
    # ============================================================================
    # Current signal-generating pairs (6+):
    # - cross-DEX quoter_v2: WBTC/WETH, WETH/USDT, WETH/USDC, wstETH/WETH, WBTC/USDC
    # - uni-only or variable: ARB/WETH, ARB/USDC, LINK/WETH
    # ============================================================================
    # DIVERSITY_PAIRS_TARGET RESTORE CONTRACT (v2.9.8):
    # ============================================================================
    # Currently: 4 (reduced from 6 in v2.9.8)
    # Reason: With min_spread_bps=10 (above cost floor), fewer pairs generate
    #         cross-DEX signals >= threshold. 4 active pairs currently profitable.
    # RESTORE TO 6 WHEN: More pools re-enabled from disabled_pools, OR
    #                    min_spread_bps lowered after cost model improvement.
    # ============================================================================
    DIVERSITY_PAIRS_TARGET = 4     # v2.9.8: Match active profitable pairs
    DIVERSITY_PAIRS_MIN = 3        # v1.12.0: FAIL if unique_pairs < 3
    # ============================================================================
    # DIVERSITY_ROUTES_TARGET RESTORE CONTRACT (v2.9.8):
    # ============================================================================
    # Currently: 1 (reduced from 2 in v2.9.8)
    # Reason: With min_spread_bps=10 and 2 DEXes, often only one arbitrage direction
    #         is profitable at any given time (market-dependent).
    # RESTORE TO 2 WHEN: Market conditions consistently show both directions profitable,
    #                    OR 3rd DEX integrated allowing more route combinations.
    # ============================================================================
    DIVERSITY_ROUTES_TARGET = 1    # v2.9.8: Accept single direction arbitrage
    # ============================================================================
    # DIVERSITY_ROUTES_MIN RESTORE CONTRACT (v2.9.8):
    # ============================================================================
    # Currently: 1 (reduced from 2 in v2.9.8)
    # Reason: With min_spread_bps=10 (above cost floor), only one arbitrage direction
    #         may be profitable at any given time (market-dependent).
    #         Single profitable direction is valid cross-DEX arbitrage.
    # RESTORE TO 2 WHEN: Market conditions consistently show both directions profitable,
    #                    OR 3rd DEX integrated allowing more route combinations.
    # ============================================================================
    DIVERSITY_ROUTES_MIN = 1       # v2.9.8: Accept single direction arbitrage
    
    # v2.0.2: Profit sanity thresholds (too-good-to-be-true detection)
    # If all N>=10 runs are profitable with very low variance, flag as suspicious
    PROFIT_SANITY_MIN_RUNS = 10    # Min runs to trigger sanity check
    PROFIT_SANITY_NET_DIV_MIN = 0.20  # Min net_diversity_rate (unique values / runs)
    PROFIT_SANITY_LOSS_RATE_MIN = 0.05  # Min expected loss rate for realistic market
    
    # v2.0.3: Suspect spread threshold (unrealistic arb detection)
    # Spreads > 300 bps for major pairs are likely low-liquidity illusions
    SUSPECT_SPREAD_BPS = 300       # Spread > 300 bps -> SUSPECT_SPREAD warning
    SUSPECT_SPREAD_BPS_HARD = 500  # Spread > 500 bps -> exclude from DoD evidence
    
    # v2.0.3: Top pair concentration (single-pair dominance)
    TOP_PAIR_NET_SHARE_WARN = 0.60  # WARN if single pair > 60% of window net profit
    TOP_PAIR_NET_SHARE_FAIL = 0.80  # FAIL_QUALITY if single pair > 80% of net profit


# ============================================================
# COST MODEL REGISTRY
# ============================================================

@dataclass
class CostModelConfig:
    """Cost model configuration for simulation."""
    name: str
    description: str
    gas_usd: float
    slippage_bps: int


class CostModelRegistry:
    """
    Registry for simulation cost models.
    
    Usage:
        registry = CostModelRegistry.default()
        model = registry.get("paper_realistic")
        gas = model.gas_usd
        slippage = model.slippage_bps
    """
    
    _instance: Optional["CostModelRegistry"] = None
    
    def __init__(self):
        self._models: Dict[str, CostModelConfig] = {}
    
    def register(self, model: CostModelConfig) -> None:
        """Register a cost model."""
        self._models[model.name] = model
    
    def get(self, name: str) -> CostModelConfig:
        """Get cost model by name."""
        if name not in self._models:
            raise ValueError(f"Unknown cost model: {name}. Available: {list(self._models.keys())}")
        return self._models[name]
    
    def list_models(self) -> List[str]:
        """List all registered cost model names."""
        return list(self._models.keys())
    
    @classmethod
    def default(cls) -> "CostModelRegistry":
        """Get default registry with standard cost models."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_defaults()
        return cls._instance
    
    def _register_defaults(self) -> None:
        """Register default cost models."""
        # Paper realistic: optimistic but reasonable
        self.register(CostModelConfig(
            name="paper_realistic",
            description="Paper simulation with realistic costs (gas=$0.10, slippage=5bps)",
            gas_usd=0.10,
            slippage_bps=5,
        ))
        
        # Paper conservative: stress test (higher costs)
        self.register(CostModelConfig(
            name="paper_conservative",
            description="Paper simulation with conservative costs (gas=$0.30, slippage=20bps)",
            gas_usd=0.30,
            slippage_bps=20,
        ))
        
        # Gas only: M5 compatibility (slippage=0)
        self.register(CostModelConfig(
            name="gas_only",
            description="Gas only, no slippage (M5 truth_report compatibility)",
            gas_usd=0.10,
            slippage_bps=0,
        ))


def get_cost_model(name: str) -> CostModelConfig:
    """Convenience function to get cost model from default registry."""
    return CostModelRegistry.default().get(name)


# ============================================================
# DOD PROFILES
# ============================================================

class DoDProfile:
    """Definition of Done profiles for M4 gate."""
    SMOKE = "smoke"    # PASS if >=1 profitable sim + accounting complete
    PROFIT = "profit"  # PASS if total_net_usd > 0
    ONLINE = "online"  # PASS if total_net_usd > 0 on real block (for tracking)


@dataclass
class ThresholdProfile:
    """Threshold configuration for M4 gate validation."""
    name: str
    mae_warn: float  # MAE threshold for WARN status
    mae_fail: float  # MAE threshold for FAIL status
    sign_rate_min: float  # Minimum sign correctness rate
    min_sample_size: int  # Below this, WARN_LOW_SAMPLE is issued
    fragile_rate_max: float = 1.0  # v1.9.9: Maximum fragile_rate for PASS (1.0 = no limit)
    description: str = ""


# Canonical threshold profiles
PROFILES: Dict[str, ThresholdProfile] = {
    DoDProfile.SMOKE: ThresholdProfile(
        name="smoke",
        mae_warn=0.30,
        mae_fail=0.50,
        sign_rate_min=0.80,
        min_sample_size=2,
        fragile_rate_max=1.0,  # No limit for smoke
        description="Minimal thresholds for smoke testing",
    ),
    DoDProfile.PROFIT: ThresholdProfile(
        name="profit",
        mae_warn=0.55,
        mae_fail=0.80,
        sign_rate_min=0.60,
        min_sample_size=5,
        fragile_rate_max=0.30,  # v2.0.2: Aligned with AGG_FRAGILE_P90_WARN (was 0.20)
        description="Production thresholds for profitable trading",
    ),
}


def get_profile(name: str) -> ThresholdProfile:
    """
    Get threshold profile by name.
    
    Args:
        name: Profile name (smoke, profit)
        
    Returns:
        ThresholdProfile
        
    Raises:
        ValueError if profile not found
    """
    if name not in PROFILES:
        raise ValueError(f"Unknown profile: {name}. Available: {list(PROFILES.keys())}")
    return PROFILES[name]


# ============================================================
# WARMUP CONFIGURATION
# ============================================================

@dataclass
class WarmupConfig:
    """Rolling window warmup configuration."""
    max_runs: int = 200  # Maximum runs in window
    min_runs: int = 10   # Minimum runs before exiting warmup
    min_signals: int = 30  # Minimum signals before exiting warmup


DEFAULT_WARMUP = WarmupConfig()


def get_warmup_status(runs_count: int, signals_count: int, config: WarmupConfig = None) -> tuple:
    """
    Determine warmup status.
    
    Args:
        runs_count: Number of runs in window
        signals_count: Total signals in window
        config: Warmup configuration (default: DEFAULT_WARMUP)
        
    Returns:
        (in_warmup: bool, reasons: list[str])
    """
    if config is None:
        config = DEFAULT_WARMUP
    
    reasons = []
    if runs_count < config.min_runs:
        reasons.append("WARMUP_MIN_RUNS")
    if signals_count < config.min_signals:
        reasons.append("WARMUP_MIN_SIGNALS")
    
    in_warmup = len(reasons) > 0
    return in_warmup, reasons


def interpret_status(
    profit_status: str,
    drift_status: str,
    signals_count: int,
    min_sample_size: int,
) -> tuple:
    """
    Determine final status and reasons.
    
    Args:
        profit_status: PASS/FAIL from profit analysis
        drift_status: PASS/WARN/FAIL from drift analysis
        signals_count: Number of signals in run
        min_sample_size: Minimum for reliable statistics
        
    Returns:
        (status: str, reasons: list[str])
    """
    reasons = []
    
    # NO_DATA handling
    if signals_count == 0:
        return "NO_DATA", ["NO_DATA"]
    
    # Low sample warning
    if signals_count < min_sample_size:
        reasons.append("WARN_LOW_SAMPLE")
    
    # Profit status reasons
    if profit_status == "FAIL":
        reasons.append("FAIL_UNPROFITABLE")
    
    # Drift status reasons
    if drift_status == "FAIL":
        reasons.append("FAIL_DRIFT_MAE")
    elif drift_status == "WARN":
        reasons.append("WARN_DRIFT_MAE")
    
    # Final status determination
    # Rule: PASS if profit_status=PASS AND drift_status!=FAIL
    if profit_status == "PASS" and drift_status != "FAIL":
        status = "WARN" if drift_status == "WARN" else "PASS"
    else:
        status = "FAIL"
    
    return status, reasons


# ============================================================
# GLOBAL CONSTANTS
# ============================================================

# Minimum net profit in USD after all costs
MIN_NET_PROFIT_USD = Decimal("0.10")  # $0.10 minimum

# Maximum gas in USD
MAX_GAS_USD = Decimal("5.00")  # $5.00 max gas

# Maximum slippage tolerance (bps)
MAX_SLIPPAGE_BPS = 50  # 0.5%

# Default chain for fixtures
DEFAULT_CHAIN_ID = 42161  # Arbitrum One

# Default pinned block for fixtures
DEFAULT_PINNED_BLOCK = 429900000
