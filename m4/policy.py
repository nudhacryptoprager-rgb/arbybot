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

class FailReason:
    """
    Explicit fail reason codes for M4 execution gate.
    
    These codes are used in run_summary.json.reasons[] to explain FAIL/WARN status.
    Each reason corresponds to a specific threshold violation.
    
    v1.5.0: mae_fail is now > 0.50 (exclusive), not >= 0.50
    v1.7.0: Added WARN_LOW_SAMPLE for insufficient signals
    """
    # FAIL conditions (profit_status)
    FAIL_NET = "FAIL_NET"                        # total_net_usdc <= 0 (PROFIT profile)
    FAIL_NO_PROFITABLE = "FAIL_NO_PROFITABLE"    # sim_profitable_count == 0
    
    # FAIL conditions (drift_status)
    FAIL_DRIFT_MAE = "FAIL_DRIFT_MAE"            # mae_net_usdc > 0.50 (exclusive)
    FAIL_DRIFT_SIGN = "FAIL_DRIFT_SIGN"          # sign_correct_rate < 0.70
    FAIL_SIGN_MISMATCH = "FAIL_SIGN_MISMATCH"    # sign_mismatch_count > 0 (strict mode)
    
    # WARN conditions
    WARN_DRIFT_MAE = "WARN_DRIFT_MAE"            # 0.30 < mae <= 0.50
    WARN_LOW_SAMPLE = "WARN_LOW_SAMPLE"          # signals_count < MIN_SAMPLE_SIZE (v1.7.0)
    WARN_AGG_WARMUP = "WARN_AGG_WARMUP"          # runs_in_window < MIN_RUNS_FOR_AGG (v1.8.0)


# ============================================================
# THRESHOLDS (centralized, v1.5.0)
# ============================================================

# Policy version for artifact provenance
POLICY_VERSION = "1.9.7"

class Thresholds:
    """
    Centralized threshold definitions for drift metrics.
    
    v1.9.7 UNIFIED SAMPLE THRESHOLDS:
    - MIN_SIGNALS_FOR_PASS unified with MIN_SAMPLE_SIZE = 5
    - signals < 5 → NO_DATA (not counted in pass_rate)
    - Added AGG_FRAGILE_P50_WARN for early signal
    
    v1.9.5 QUALITY GATES:
    - Added MIN_SIGNALS_FOR_PASS: runs with < 5 signals get NO_DATA
    - Added AGG_LOW_SAMPLE_RATE_FAIL: if > 50% runs are low-sample, agg fails quality
    - AGG_FRAGILE_P90_WARN/FAIL now enforced in aggregator status
    
    v1.8.1 CALIBRATION (based on 20 online runs, 56 signals):
    - MAE_WARN raised from 0.30 → 0.55 to account for systematic slippage=$0.50
    - MAE_FAIL raised from 0.50 → 0.80 to allow slippage + small model error
    - SIGN_RATE_MIN lowered from 0.70 → 0.60 to allow 2/3 for small samples
    
    Rationale: mae=0.50 is expected when slippage=$0.50. This is not model error.
    """
    # === Drift thresholds (per-run) ===
    MAE_WARN = 0.55      # mae > 0.55 triggers WARN (above typical slippage)
    MAE_FAIL = 0.80      # mae > 0.80 triggers FAIL (significant model error)
    SIGN_RATE_MIN = 0.60  # sign_rate < 0.60 triggers FAIL (allows 2/3)
    
    # Slippage component (for mae_no_slippage calculation)
    SLIPPAGE_SYSTEMATIC_FACTOR = 1.0  # per-signal slippage adds to expected drift
    
    # === Sample size thresholds (v1.9.7 UNIFIED) ===
    # Single threshold: signals < 5 → NO_DATA (not pass, not counted in pass_rate)
    MIN_SAMPLE_SIZE = 5           # < 5 signals → NO_DATA
    MIN_SIGNALS_FOR_PASS = 5      # v1.9.7: unified with MIN_SAMPLE_SIZE
    
    # Rolling window for aggregator (v1.7.0)
    ROLLING_WINDOW_DEFAULT = 50   # Default rolling window for aggregator
    ROLLING_WINDOW_MAX = 200      # Max window for extended analysis
    
    # === Aggregator-level thresholds (v1.9.7) ===
    AGG_MAE_P90_FAIL = 0.85           # FAIL if p90(MAE) > 0.85
    AGG_WARN_RATE_FAIL = 0.60         # FAIL if warn_rate_core > 60%
    AGG_FAIL_RATE_FAIL = 0.40         # FAIL if fail_rate > 40%
    AGG_LOW_SAMPLE_RATE_WARN = 0.50   # WARN if low_sample_rate > 50%
    AGG_LOW_SAMPLE_RATE_FAIL = 0.80   # FAIL_QUALITY if low_sample_rate > 80%
    
    # Warm-up thresholds (v1.8.0) - aggregator needs minimum data before hard FAIL
    MIN_RUNS_FOR_AGG = 10         # < 10 runs → PASS_WITH_WARMUP instead of FAIL
    MIN_SIGNALS_FOR_AGG = 30      # < 30 total signals → warn thresholds relaxed
    
    # Fragile rate thresholds (v1.9.7) - enforced in agg status
    AGG_FRAGILE_P50_WARN = 0.40   # v1.9.7: early signal when median is elevated
    AGG_FRAGILE_P90_WARN = 0.30   # WARN if p90(fragile_rate) > 30%
    AGG_FRAGILE_P90_FAIL = 0.50   # FAIL_QUALITY if p90(fragile_rate) > 50%


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
    description: str = ""


# Canonical threshold profiles
PROFILES: Dict[str, ThresholdProfile] = {
    DoDProfile.SMOKE: ThresholdProfile(
        name="smoke",
        mae_warn=0.30,
        mae_fail=0.50,
        sign_rate_min=0.80,
        min_sample_size=2,
        description="Minimal thresholds for smoke testing",
    ),
    DoDProfile.PROFIT: ThresholdProfile(
        name="profit",
        mae_warn=0.55,
        mae_fail=0.80,
        sign_rate_min=0.60,
        min_sample_size=5,
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
