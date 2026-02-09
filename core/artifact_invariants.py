# PATH: core/artifact_invariants.py
"""
Unified artifact invariants for all CI gates.

This is the SINGLE SOURCE OF TRUTH for cross-artifact validation.
Used by: ci_m5_0_gate.py, ci_m5_gate.py, ci_m4_execution_gate.py

CRITICAL: Do not duplicate these checks elsewhere.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


# =============================================================================
# PROFILE REGISTRY
# =============================================================================

@dataclass
class ProfileConfig:
    """Configuration for a DoD profile."""
    name: str
    description: str
    # Profitability thresholds
    min_simulations: int = 1
    min_profitable_sims: int = 1
    require_net_positive: bool = False
    min_net_usdc: float = 0.0
    # Estimation accuracy thresholds
    max_mae_usdc: float = 0.30  # Max mean absolute error
    min_sign_correct_rate: float = 0.80  # 80% minimum
    # Custom validator (optional)
    custom_validator: Optional[Callable[[Dict[str, Any]], List["InvariantCheck"]]] = None


class ProfileRegistry:
    """
    Central registry for DoD profiles.
    
    Usage:
        registry = ProfileRegistry.default()
        profile = registry.get("smoke")
        checks = profile.validate(execution_report)
    """
    
    _instance: Optional["ProfileRegistry"] = None
    
    def __init__(self):
        self._profiles: Dict[str, ProfileConfig] = {}
    
    def register(self, profile: ProfileConfig) -> None:
        """Register a profile."""
        self._profiles[profile.name] = profile
    
    def get(self, name: str) -> ProfileConfig:
        """Get profile by name."""
        if name not in self._profiles:
            raise ValueError(f"Unknown profile: {name}. Available: {list(self._profiles.keys())}")
        return self._profiles[name]
    
    def list_profiles(self) -> List[str]:
        """List all registered profile names."""
        return list(self._profiles.keys())
    
    @classmethod
    def default(cls) -> "ProfileRegistry":
        """Get default registry with standard profiles."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._register_defaults()
        return cls._instance
    
    def _register_defaults(self) -> None:
        """Register default profiles."""
        # M4 SMOKE profile: PASS if at least 1 profitable sim
        self.register(ProfileConfig(
            name="smoke",
            description="M4 smoke: PASS if >= 1 profitable simulation",
            min_simulations=1,
            min_profitable_sims=1,
            require_net_positive=False,
            min_net_usdc=-999999.0,  # No minimum
        ))
        
        # M4 PROFIT profile: PASS if total_net_usdc > 0
        self.register(ProfileConfig(
            name="profit",
            description="M4 profit: PASS if total_net_usdc > 0",
            min_simulations=1,
            min_profitable_sims=1,
            require_net_positive=True,
            min_net_usdc=0.0,  # Must be positive
        ))
        
        # M4 ONLINE profile: PASS if N online runs with net > 0
        # Used for tracking online profit history
        self.register(ProfileConfig(
            name="online",
            description="M4 online: PASS if total_net_usdc > 0 on real block",
            min_simulations=1,
            min_profitable_sims=1,
            require_net_positive=True,
            min_net_usdc=0.0,
            max_mae_usdc=0.50,  # Higher tolerance for online
            min_sign_correct_rate=0.70,  # 70% for online
        ))
        
        # M5 SCAN profile: PASS if quotes fetched successfully
        self.register(ProfileConfig(
            name="scan",
            description="M5 scan: PASS if quotes fetched",
            min_simulations=0,
            min_profitable_sims=0,
            require_net_positive=False,
        ))


def get_profile(name: str) -> ProfileConfig:
    """Convenience function to get profile from default registry."""
    return ProfileRegistry.default().get(name)


class RunMode(Enum):
    """Canonical run mode values."""
    FIXTURE_OFFLINE = "FIXTURE_OFFLINE"      # Synthetic fixtures, no RPC
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"      # Smoke test with simulated DEX
    REGISTRY_REAL = "REGISTRY_REAL"          # Real RPC, real quotes
    REAL = "REAL"                            # Alias for REGISTRY_REAL
    
    @classmethod
    def is_offline(cls, mode: str) -> bool:
        """Check if mode is offline (no RPC required)."""
        return "OFFLINE" in mode.upper() or "FIXTURE" in mode.upper()
    
    @classmethod
    def is_online(cls, mode: str) -> bool:
        """Check if mode requires RPC."""
        return not cls.is_offline(mode)


@dataclass
class InvariantCheck:
    """Result of an invariant check."""
    name: str
    passed: bool
    message: str
    severity: str = "ERROR"  # ERROR, WARN, INFO


# =============================================================================
# CROSS-ARTIFACT INVARIANTS
# =============================================================================

def check_cross_artifact_invariants(
    scan_report: Dict[str, Any],
    truth_report: Dict[str, Any],
    reject_histogram: Optional[Dict[str, Any]] = None,
) -> List[InvariantCheck]:
    """
    Validate cross-artifact invariants between scan, truth, and histogram.
    
    Invariants checked:
    1. current_block consistency
    2. chain_id consistency
    3. run_mode consistency
    4. quotes_total consistency
    5. schema_version compatibility
    """
    checks = []
    
    # 1. current_block consistency
    scan_block = scan_report.get("stats", {}).get("current_block", 0)
    truth_block = truth_report.get("current_block", 0)
    
    if scan_block == truth_block:
        checks.append(InvariantCheck(
            "current_block_match", True,
            f"current_block={scan_block} consistent"
        ))
    else:
        checks.append(InvariantCheck(
            "current_block_match", False,
            f"Block mismatch: scan={scan_block} vs truth={truth_block}"
        ))
    
    # 2. chain_id consistency
    scan_chain = scan_report.get("chain_id", scan_report.get("stats", {}).get("chain_id"))
    truth_chain = truth_report.get("chain_id")
    
    if scan_chain and truth_chain:
        if scan_chain == truth_chain:
            checks.append(InvariantCheck(
                "chain_id_match", True,
                f"chain_id={scan_chain} consistent"
            ))
        else:
            checks.append(InvariantCheck(
                "chain_id_match", False,
                f"Chain mismatch: scan={scan_chain} vs truth={truth_chain}"
            ))
    
    # 3. run_mode consistency
    scan_mode = scan_report.get("run_mode", "")
    truth_mode = truth_report.get("run_mode", "")
    
    if scan_mode and truth_mode:
        if scan_mode == truth_mode:
            checks.append(InvariantCheck(
                "run_mode_match", True,
                f"run_mode={scan_mode} consistent"
            ))
        else:
            checks.append(InvariantCheck(
                "run_mode_match", False,
                f"Mode mismatch: scan={scan_mode} vs truth={truth_mode}"
            ))
    
    # 4. quotes_total consistency
    scan_quotes = scan_report.get("health", {}).get("quotes_total", 0)
    truth_quotes = truth_report.get("quotes_total", 0)
    
    if scan_quotes == truth_quotes:
        checks.append(InvariantCheck(
            "quotes_total_match", True,
            f"quotes_total={scan_quotes} consistent"
        ))
    else:
        checks.append(InvariantCheck(
            "quotes_total_match", False,
            f"Quotes mismatch: scan={scan_quotes} vs truth={truth_quotes}",
            severity="WARN"
        ))
    
    # 5. Reject histogram consistency (if provided)
    if reject_histogram:
        hist_total = reject_histogram.get("total_rejects", 0)
        scan_rejects = scan_report.get("stats", {}).get("quotes_total", 0) - \
                       scan_report.get("stats", {}).get("gates_passed", 0)
        
        # Allow small discrepancy due to timing
        if abs(hist_total - scan_rejects) <= 2:
            checks.append(InvariantCheck(
                "reject_histogram_match", True,
                f"total_rejects={hist_total} ~= scan_rejects"
            ))
        else:
            checks.append(InvariantCheck(
                "reject_histogram_match", False,
                f"Histogram mismatch: hist={hist_total} vs scan_rejects={scan_rejects}",
                severity="WARN"
            ))
    
    return checks


# =============================================================================
# M4 EXECUTION INVARIANTS
# =============================================================================

def check_m4_execution_invariants(
    signals: Dict[str, Any],
    execution_report: Dict[str, Any],
) -> List[InvariantCheck]:
    """
    Validate M4 execution invariants between signals and execution_report.
    
    Invariants checked:
    1. quote_ccy consistency (USDC)
    2. pinned_block consistency
    3. chain_id consistency
    4. all_signals_simulated
    5. execution_enabled=false (M4 safety)
    6. kill_switch_active=true (M4 safety)
    """
    checks = []
    
    # 1. quote_ccy consistency
    signals_ccy = signals.get("quote_ccy", "")
    exec_ccy = execution_report.get("quote_ccy", "")
    
    if signals_ccy == exec_ccy == "USDC":
        checks.append(InvariantCheck(
            "quote_ccy_match", True, "quote_ccy=USDC consistent"
        ))
    else:
        checks.append(InvariantCheck(
            "quote_ccy_match", False,
            f"quote_ccy mismatch: signals={signals_ccy} vs exec={exec_ccy}"
        ))
    
    # 2. pinned_block consistency
    signals_block = signals.get("pinned_block")
    exec_block = execution_report.get("pinned_block")
    
    if signals_block and exec_block:
        if signals_block == exec_block:
            checks.append(InvariantCheck(
                "pinned_block_match", True,
                f"pinned_block={exec_block} consistent"
            ))
        else:
            checks.append(InvariantCheck(
                "pinned_block_match", False,
                f"Block mismatch: signals={signals_block} vs exec={exec_block}"
            ))
    
    # 3. chain_id consistency
    signals_chain = signals.get("chain_id")
    exec_chain = execution_report.get("chain_id")
    
    if signals_chain and exec_chain:
        if signals_chain == exec_chain:
            checks.append(InvariantCheck(
                "chain_id_match", True, f"chain_id={exec_chain} consistent"
            ))
        else:
            checks.append(InvariantCheck(
                "chain_id_match", False,
                f"Chain mismatch: signals={signals_chain} vs exec={exec_chain}"
            ))
    
    # 4. all_signals_simulated
    health = execution_report.get("health", {})
    if health.get("all_signals_simulated", False):
        checks.append(InvariantCheck(
            "all_signals_simulated", True, "All signals have simulations"
        ))
    else:
        checks.append(InvariantCheck(
            "all_signals_simulated", False, "Missing simulations for some signals"
        ))
    
    # 5. M4 safety: execution_enabled=false
    exec_enabled = execution_report.get("execution_enabled")
    if exec_enabled is False:
        checks.append(InvariantCheck(
            "m4_execution_disabled", True, "execution_enabled=false (M4 safe)"
        ))
    else:
        checks.append(InvariantCheck(
            "m4_execution_disabled", False,
            f"DANGER: execution_enabled={exec_enabled} (must be false in M4)"
        ))
    
    # 6. M4 safety: kill_switch_active=true
    kill_switch = execution_report.get("kill_switch_active")
    if kill_switch is True:
        checks.append(InvariantCheck(
            "m4_kill_switch", True, "kill_switch_active=true (M4 safe)"
        ))
    elif kill_switch is None:
        checks.append(InvariantCheck(
            "m4_kill_switch", False, "kill_switch_active is missing"
        ))
    else:
        checks.append(InvariantCheck(
            "m4_kill_switch", False,
            f"DANGER: kill_switch_active={kill_switch} (must be true in M4)"
        ))
    
    return checks


# =============================================================================
# BLOCK VALIDATION
# =============================================================================

# Sentinel block values that indicate failure
SENTINEL_BLOCKS = {0, 1, 999999999}


def validate_block_number(block: int, run_mode: str) -> InvariantCheck:
    """
    Validate block number based on run mode.
    
    - OFFLINE: synthetic block OK (e.g., 429900000)
    - ONLINE: must be real block, not sentinel
    """
    if RunMode.is_offline(run_mode):
        # Offline: any non-sentinel block is OK
        if block in SENTINEL_BLOCKS:
            return InvariantCheck(
                "block_valid", False,
                f"Sentinel block {block} not allowed even in offline mode"
            )
        return InvariantCheck(
            "block_valid", True,
            f"Synthetic block {block} OK for offline mode"
        )
    else:
        # Online: must be real block
        if block in SENTINEL_BLOCKS:
            return InvariantCheck(
                "block_valid", False,
                f"Sentinel block {block} not allowed in online mode"
            )
        if block < 100000:  # Suspiciously low for mainnet
            return InvariantCheck(
                "block_valid", False,
                f"Block {block} too low for mainnet (online mode)",
                severity="WARN"
            )
        return InvariantCheck(
            "block_valid", True, f"Real block {block} valid"
        )


# =============================================================================
# PROFITABILITY INVARIANTS (M4)
# =============================================================================

# Minimum net profit required for M4-profit DoD
MIN_NET_PROFIT_USDC = 0.0  # Zero for smoke, positive for profit profile


def check_m4_profitability(
    execution_report: Dict[str, Any],
    min_net_usdc: float = MIN_NET_PROFIT_USDC,
    require_simulation: bool = True,
) -> List[InvariantCheck]:
    """
    Check M4 profitability invariants.
    
    Args:
        execution_report: Execution report data
        min_net_usdc: Minimum required net profit
        require_simulation: Whether at least 1 simulation is required
    """
    checks = []
    
    # 1. At least one simulation
    sims_count = execution_report.get("simulations_count", 0)
    sims_passed = execution_report.get("simulations_passed", 0)
    
    if require_simulation and sims_count == 0:
        checks.append(InvariantCheck(
            "has_simulations", False, "No simulations (simulations_count=0)"
        ))
    else:
        checks.append(InvariantCheck(
            "has_simulations", True, f"simulations_count={sims_count}"
        ))
    
    # 2. At least one profitable simulation
    if sims_passed >= 1:
        checks.append(InvariantCheck(
            "has_profitable", True, f"simulations_passed={sims_passed} >= 1"
        ))
    else:
        checks.append(InvariantCheck(
            "has_profitable", False, f"simulations_passed={sims_passed} < 1"
        ))
    
    # 3. Net profit check
    total_net = execution_report.get("total_net_usdc", 0)
    if isinstance(total_net, str):
        total_net = float(total_net)
    
    if total_net > min_net_usdc:
        checks.append(InvariantCheck(
            "net_positive", True,
            f"total_net_usdc={total_net:.4f} > {min_net_usdc}"
        ))
    else:
        checks.append(InvariantCheck(
            "net_positive", False,
            f"total_net_usdc={total_net:.4f} <= {min_net_usdc}"
        ))
    
    return checks


# =============================================================================
# SCHEMA VERSION VALIDATION
# =============================================================================

SUPPORTED_SCHEMAS = {
    # M5_0 / M5 scan artifacts
    "3.2.0": "scan_report",
    "3.1.0": "scan_report",
    "3.0.0": "scan_report",
    # M4 execution artifacts
    "m4:signals:v1.1": "signals",
    "m4:signals:v1": "signals",
    "m4:execution:v1.1": "execution_report",
    "m4:execution:v1": "execution_report",
}


def validate_schema_version(version: str, expected_type: str) -> InvariantCheck:
    """Validate schema version is supported and matches expected type."""
    if version not in SUPPORTED_SCHEMAS:
        return InvariantCheck(
            "schema_supported", False,
            f"Unknown schema_version: {version}"
        )
    
    actual_type = SUPPORTED_SCHEMAS[version]
    if actual_type != expected_type:
        return InvariantCheck(
            "schema_type", False,
            f"Schema {version} is for {actual_type}, not {expected_type}"
        )
    
    return InvariantCheck(
        "schema_valid", True, f"schema_version={version} OK"
    )
