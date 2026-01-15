"""
discovery/quarantine.py - Quarantine system for toxic combinations.

Hard-filter for (pair, fee, dex) combinations that consistently fail gates.
Tracks failure rates and auto-quarantines combinations exceeding thresholds.

Team Lead directive:
"Зробити hard-filter у registry/universe: прибрати (pair, fee, dex), 
які дають PRICE_SANITY_FAILED > X% за останні N циклів."
"""

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import get_logger
from core.exceptions import ErrorCode

logger = get_logger(__name__)


# =============================================================================
# QUARANTINE THRESHOLDS
# =============================================================================

# Minimum attempts before quarantine decision
MIN_ATTEMPTS_FOR_QUARANTINE = 5

# Failure rate thresholds (percentage)
PRICE_SANITY_FAIL_THRESHOLD = 50   # 50% = quarantine
QUOTE_REVERT_FAIL_THRESHOLD = 80   # 80% = quarantine  
GAS_TOO_HIGH_FAIL_THRESHOLD = 70   # 70% = quarantine

# Quarantine duration (cycles)
QUARANTINE_DURATION_CYCLES = 20

# Auto-release after N successful quotes post-quarantine
RELEASE_AFTER_SUCCESS = 3


@dataclass
class CombinationStats:
    """Statistics for a (pair, dex, fee) combination."""
    pair: str
    dex_id: str
    fee: int
    
    # Counters
    total_attempts: int = 0
    successful_quotes: int = 0
    
    # Failure counters by reason
    failures: dict = field(default_factory=dict)
    
    # Quarantine state
    is_quarantined: bool = False
    quarantine_reason: str = ""
    quarantine_cycle: int = 0
    quarantine_until_cycle: int = 0
    
    # Post-quarantine success counter
    post_quarantine_success: int = 0
    
    @property
    def combination_id(self) -> str:
        return f"{self.pair}_{self.dex_id}_{self.fee}"
    
    @property
    def failure_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return (self.total_attempts - self.successful_quotes) / self.total_attempts
    
    def get_failure_rate_by_reason(self, reason: str) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.failures.get(reason, 0) / self.total_attempts
    
    def to_dict(self) -> dict:
        return {
            "pair": self.pair,
            "dex_id": self.dex_id,
            "fee": self.fee,
            "combination_id": self.combination_id,
            "total_attempts": self.total_attempts,
            "successful_quotes": self.successful_quotes,
            "failure_rate": round(self.failure_rate * 100, 1),
            "failures": dict(self.failures),
            "is_quarantined": self.is_quarantined,
            "quarantine_reason": self.quarantine_reason,
            "quarantine_cycle": self.quarantine_cycle,
            "quarantine_until_cycle": self.quarantine_until_cycle,
        }


class QuarantineManager:
    """
    Manages quarantine state for (pair, dex, fee) combinations.
    
    Features:
    - Tracks failure rates per combination
    - Auto-quarantines combinations exceeding thresholds
    - Auto-releases after quarantine period
    - Persists state across runs
    """
    
    def __init__(
        self,
        data_dir: Path = Path("data/quarantine"),
        price_sanity_threshold: float = PRICE_SANITY_FAIL_THRESHOLD,
        quote_revert_threshold: float = QUOTE_REVERT_FAIL_THRESHOLD,
        gas_too_high_threshold: float = GAS_TOO_HIGH_FAIL_THRESHOLD,
        quarantine_duration: int = QUARANTINE_DURATION_CYCLES,
    ):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Thresholds (as percentages)
        self.price_sanity_threshold = price_sanity_threshold
        self.quote_revert_threshold = quote_revert_threshold
        self.gas_too_high_threshold = gas_too_high_threshold
        self.quarantine_duration = quarantine_duration
        
        # Stats storage: combination_id -> CombinationStats
        self._stats: dict[str, CombinationStats] = {}
        
        # Current cycle
        self._current_cycle = 0
        
        # Load persisted state
        self._load_state()
    
    def _load_state(self) -> None:
        """Load persisted quarantine state."""
        state_file = self.data_dir / "quarantine_state.json"
        
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                
                self._current_cycle = data.get("current_cycle", 0)
                
                for combo_data in data.get("combinations", []):
                    stats = CombinationStats(
                        pair=combo_data["pair"],
                        dex_id=combo_data["dex_id"],
                        fee=combo_data["fee"],
                        total_attempts=combo_data.get("total_attempts", 0),
                        successful_quotes=combo_data.get("successful_quotes", 0),
                        failures=combo_data.get("failures", {}),
                        is_quarantined=combo_data.get("is_quarantined", False),
                        quarantine_reason=combo_data.get("quarantine_reason", ""),
                        quarantine_cycle=combo_data.get("quarantine_cycle", 0),
                        quarantine_until_cycle=combo_data.get("quarantine_until_cycle", 0),
                        post_quarantine_success=combo_data.get("post_quarantine_success", 0),
                    )
                    self._stats[stats.combination_id] = stats
                
                logger.info(
                    f"Loaded quarantine state: {len(self._stats)} combinations, "
                    f"cycle {self._current_cycle}"
                )
            except Exception as e:
                logger.warning(f"Failed to load quarantine state: {e}")
    
    def _save_state(self) -> None:
        """Persist quarantine state."""
        state_file = self.data_dir / "quarantine_state.json"
        
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "current_cycle": self._current_cycle,
            "combinations": [stats.to_dict() for stats in self._stats.values()],
        }
        
        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)
    
    def _get_or_create_stats(self, pair: str, dex_id: str, fee: int) -> CombinationStats:
        """Get or create stats for a combination."""
        combo_id = f"{pair}_{dex_id}_{fee}"
        
        if combo_id not in self._stats:
            self._stats[combo_id] = CombinationStats(
                pair=pair,
                dex_id=dex_id,
                fee=fee,
            )
        
        return self._stats[combo_id]
    
    def start_cycle(self) -> None:
        """Start a new scan cycle."""
        self._current_cycle += 1
        
        # Check for quarantine releases
        released = []
        for combo_id, stats in self._stats.items():
            if stats.is_quarantined and self._current_cycle >= stats.quarantine_until_cycle:
                stats.is_quarantined = False
                stats.quarantine_reason = ""
                stats.post_quarantine_success = 0
                released.append(combo_id)
        
        if released:
            logger.info(
                f"Released {len(released)} combinations from quarantine",
                extra={"context": {"released": released}}
            )
        
        self._save_state()
    
    def is_quarantined(self, pair: str, dex_id: str, fee: int) -> bool:
        """Check if a combination is quarantined."""
        stats = self._get_or_create_stats(pair, dex_id, fee)
        return stats.is_quarantined
    
    def record_success(self, pair: str, dex_id: str, fee: int) -> None:
        """Record a successful quote."""
        stats = self._get_or_create_stats(pair, dex_id, fee)
        stats.total_attempts += 1
        stats.successful_quotes += 1
        
        # Track post-quarantine success for early release
        if stats.post_quarantine_success > 0:
            stats.post_quarantine_success += 1
            if stats.post_quarantine_success >= RELEASE_AFTER_SUCCESS:
                logger.info(
                    f"Early release from quarantine: {stats.combination_id}",
                    extra={"context": {"post_quarantine_success": stats.post_quarantine_success}}
                )
    
    def record_failure(
        self,
        pair: str,
        dex_id: str,
        fee: int,
        reason: ErrorCode | str,
    ) -> bool:
        """
        Record a failed quote.
        
        Returns:
            True if combination was quarantined as a result
        """
        stats = self._get_or_create_stats(pair, dex_id, fee)
        stats.total_attempts += 1
        
        # Convert ErrorCode to string
        reason_str = reason.value if isinstance(reason, ErrorCode) else str(reason)
        stats.failures[reason_str] = stats.failures.get(reason_str, 0) + 1
        
        # Check quarantine thresholds
        if stats.total_attempts >= MIN_ATTEMPTS_FOR_QUARANTINE and not stats.is_quarantined:
            quarantine_reason = self._check_quarantine_thresholds(stats)
            
            if quarantine_reason:
                stats.is_quarantined = True
                stats.quarantine_reason = quarantine_reason
                stats.quarantine_cycle = self._current_cycle
                stats.quarantine_until_cycle = self._current_cycle + self.quarantine_duration
                
                logger.warning(
                    f"Quarantined combination: {stats.combination_id}",
                    extra={"context": {
                        "reason": quarantine_reason,
                        "failure_rate": round(stats.failure_rate * 100, 1),
                        "attempts": stats.total_attempts,
                        "failures": dict(stats.failures),
                        "until_cycle": stats.quarantine_until_cycle,
                    }}
                )
                return True
        
        return False
    
    def _check_quarantine_thresholds(self, stats: CombinationStats) -> str | None:
        """Check if stats exceed any quarantine threshold."""
        # PRICE_SANITY_FAILED
        price_sanity_rate = stats.get_failure_rate_by_reason("PRICE_SANITY_FAILED") * 100
        if price_sanity_rate >= self.price_sanity_threshold:
            return f"PRICE_SANITY_FAILED ({price_sanity_rate:.0f}%)"
        
        # QUOTE_REVERT
        revert_rate = stats.get_failure_rate_by_reason("QUOTE_REVERT") * 100
        if revert_rate >= self.quote_revert_threshold:
            return f"QUOTE_REVERT ({revert_rate:.0f}%)"
        
        # QUOTE_GAS_TOO_HIGH
        gas_rate = stats.get_failure_rate_by_reason("QUOTE_GAS_TOO_HIGH") * 100
        if gas_rate >= self.gas_too_high_threshold:
            return f"QUOTE_GAS_TOO_HIGH ({gas_rate:.0f}%)"
        
        return None
    
    def get_quarantined_combinations(self) -> list[CombinationStats]:
        """Get all currently quarantined combinations."""
        return [s for s in self._stats.values() if s.is_quarantined]
    
    def get_stats_summary(self) -> dict:
        """Get summary of quarantine statistics."""
        quarantined = self.get_quarantined_combinations()
        
        # Aggregate failure rates by reason
        reason_totals: dict[str, int] = defaultdict(int)
        for stats in self._stats.values():
            for reason, count in stats.failures.items():
                reason_totals[reason] += count
        
        return {
            "current_cycle": self._current_cycle,
            "total_combinations_tracked": len(self._stats),
            "quarantined_count": len(quarantined),
            "quarantined_combinations": [s.combination_id for s in quarantined],
            "failure_totals_by_reason": dict(reason_totals),
        }
    
    def get_debug_samples(
        self,
        pair: str,
        dex_id: str,
        max_samples: int = 3,
    ) -> list[dict]:
        """
        Get debug samples for a pair/dex combination.
        
        Team Lead directive:
        "Для WETH/LINK і WETH/ARB на sushiswap_v3: зробити 'debug mode' — 
        зберігати 1–3 кейси з anchor_price/quote_price/fee/amount"
        """
        debug_file = self.data_dir / f"debug_{pair}_{dex_id}.json"
        
        if debug_file.exists():
            with open(debug_file) as f:
                samples = json.load(f)
            return samples[:max_samples]
        
        return []
    
    def save_debug_sample(
        self,
        pair: str,
        dex_id: str,
        fee: int,
        amount_in: int,
        quote_price: str,
        anchor_price: str,
        deviation_bps: int,
        error_code: str,
        extra: dict | None = None,
    ) -> None:
        """
        Save a debug sample for analysis.
        
        Keeps only the last N samples per pair/dex.
        """
        debug_file = self.data_dir / f"debug_{pair}_{dex_id}.json"
        
        # Load existing samples
        samples = []
        if debug_file.exists():
            with open(debug_file) as f:
                samples = json.load(f)
        
        # Add new sample
        sample = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pair": pair,
            "dex_id": dex_id,
            "fee": fee,
            "amount_in": amount_in,
            "quote_price": quote_price,
            "anchor_price": anchor_price,
            "deviation_bps": deviation_bps,
            "error_code": error_code,
        }
        if extra:
            sample["extra"] = extra
        
        samples.append(sample)
        
        # Keep only last 10 samples
        samples = samples[-10:]
        
        with open(debug_file, "w") as f:
            json.dump(samples, f, indent=2)


# =============================================================================
# EXCLUDED COMBINATIONS (static, from intent analysis)
# =============================================================================

# Combinations that should never be scanned
# Team Lead: "Для wstETH→WETH QUOTE_REVERT: перевірити існування пулу...
# Якщо ні — виключити комбінацію з intent."
EXCLUDED_COMBINATIONS = {
    # wstETH/WETH on sushiswap_v3 fee=3000 - confirmed no pool
    ("wstETH/WETH", "sushiswap_v3", 3000),
    ("WETH/wstETH", "sushiswap_v3", 3000),
    
    # Add more as discovered
}


def is_excluded_combination(pair: str, dex_id: str, fee: int) -> bool:
    """Check if a combination is statically excluded."""
    return (pair, dex_id, fee) in EXCLUDED_COMBINATIONS


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_quarantine_manager: QuarantineManager | None = None


def get_quarantine_manager() -> QuarantineManager:
    """Get singleton quarantine manager."""
    global _quarantine_manager
    
    if _quarantine_manager is None:
        _quarantine_manager = QuarantineManager()
    
    return _quarantine_manager


def reset_quarantine_manager() -> None:
    """Reset singleton (for testing)."""
    global _quarantine_manager
    _quarantine_manager = None
