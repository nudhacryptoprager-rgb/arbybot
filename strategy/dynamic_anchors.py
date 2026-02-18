# PATH: strategy/dynamic_anchors.py
"""
Dynamic anchors v1: Rolling median valid quotes as primary anchor source.

Team Lead requirement:
- Rolling median valid quotes (per pair, per "anchor DEX priority")
- YAML `tokens_anchor_price` = fallback only
- Log `anchor_source` per-quote ("dynamic" vs "yaml_fallback")
"""

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("strategy.dynamic_anchors")

# Default cache file location
DEFAULT_CACHE_PATH = Path("data/cache/dynamic_anchors.json")

# Config
DYNAMIC_ANCHOR_CONFIG = {
    # Minimum samples needed to use dynamic anchor
    "min_samples": 3,
    
    # Maximum age of samples (seconds)
    "max_sample_age_seconds": 3600,  # 1 hour
    
    # Maximum samples to keep per pair
    "max_samples_per_pair": 100,
    
    # DEX priority for anchor (prefer more liquid DEXes)
    "dex_priority": [
        "uniswap_v3",
        "sushiswap_v3",
        "camelot_v3",
    ],
}


@dataclass
class AnchorSample:
    """Single price sample for anchor calculation."""
    timestamp: float
    price: float
    dex_id: str
    fee_tier: int
    block: int


@dataclass
class PairAnchorData:
    """Anchor data for a trading pair."""
    pair: str
    samples: List[AnchorSample] = field(default_factory=list)
    last_updated: float = 0.0
    
    def add_sample(self, sample: AnchorSample, max_samples: int = 100) -> None:
        """Add a sample, maintaining max sample limit."""
        self.samples.append(sample)
        self.last_updated = sample.timestamp
        
        # Prune oldest samples if over limit
        if len(self.samples) > max_samples:
            self.samples = sorted(self.samples, key=lambda s: s.timestamp)[-max_samples:]
    
    def get_valid_samples(self, max_age_seconds: float) -> List[AnchorSample]:
        """Get samples within max age."""
        cutoff = time.time() - max_age_seconds
        return [s for s in self.samples if s.timestamp >= cutoff]
    
    def calculate_median(self, max_age_seconds: float, min_samples: int) -> Optional[float]:
        """Calculate median price from valid samples."""
        valid = self.get_valid_samples(max_age_seconds)
        if len(valid) < min_samples:
            return None
        
        prices = [s.price for s in valid]
        return statistics.median(prices)


class DynamicAnchorManager:
    """
    Manages dynamic anchor prices based on rolling valid quotes.
    """
    
    def __init__(
        self,
        config: Dict[str, Any] | None = None,
        cache_path: Path | None = None,
        load_cache: bool = True,
    ):
        self.config = config or DYNAMIC_ANCHOR_CONFIG
        self.cache_path = cache_path or DEFAULT_CACHE_PATH
        self._pairs: Dict[str, PairAnchorData] = {}
        
        # Try to load from cache (can be disabled for testing)
        if load_cache:
            self._load_cache()
    
    def _load_cache(self) -> None:
        """Load cached anchor data."""
        if not self.cache_path.exists():
            return
        
        try:
            with open(self.cache_path) as f:
                data = json.load(f)
            
            for pair, pair_data in data.get("pairs", {}).items():
                samples = [
                    AnchorSample(
                        timestamp=s["timestamp"],
                        price=s["price"],
                        dex_id=s["dex_id"],
                        fee_tier=s["fee_tier"],
                        block=s.get("block", 0),
                    )
                    for s in pair_data.get("samples", [])
                ]
                self._pairs[pair] = PairAnchorData(
                    pair=pair,
                    samples=samples,
                    last_updated=pair_data.get("last_updated", 0.0),
                )
            
            logger.info(f"Loaded {len(self._pairs)} pairs from anchor cache")
        except Exception as e:
            logger.warning(f"Failed to load anchor cache: {e}")
    
    def _save_cache(self) -> None:
        """Save anchor data to cache."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": "1.0",
                "saved_at": time.time(),
                "pairs": {
                    pair: {
                        "pair": pair_data.pair,
                        "last_updated": pair_data.last_updated,
                        "samples": [
                            {
                                "timestamp": s.timestamp,
                                "price": s.price,
                                "dex_id": s.dex_id,
                                "fee_tier": s.fee_tier,
                                "block": s.block,
                            }
                            for s in pair_data.samples
                        ],
                    }
                    for pair, pair_data in self._pairs.items()
                },
            }
            
            with open(self.cache_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save anchor cache: {e}")
    
    def record_quote(
        self,
        pair: str,
        price: float,
        dex_id: str,
        fee_tier: int,
        block: int,
    ) -> None:
        """
        Record a valid quote for anchor calculation.
        
        Only call this for quotes that passed price sanity validation.
        """
        if pair not in self._pairs:
            self._pairs[pair] = PairAnchorData(pair=pair)
        
        sample = AnchorSample(
            timestamp=time.time(),
            price=price,
            dex_id=dex_id,
            fee_tier=fee_tier,
            block=block,
        )
        
        max_samples = self.config.get("max_samples_per_pair", 100)
        self._pairs[pair].add_sample(sample, max_samples)
    
    def get_anchor(
        self,
        pair: str,
        yaml_fallback: Optional[float] = None,
    ) -> Tuple[Optional[float], str]:
        """
        Get anchor price for a pair.
        
        Args:
            pair: Pair tag (e.g., "WETH/USDC")
            yaml_fallback: Fallback anchor from YAML config
        
        Returns:
            (anchor_price, anchor_source) where anchor_source is "dynamic" or "yaml_fallback"
        """
        # Check if we have enough dynamic samples
        if pair in self._pairs:
            pair_data = self._pairs[pair]
            max_age = self.config.get("max_sample_age_seconds", 3600)
            min_samples = self.config.get("min_samples", 3)
            
            median = pair_data.calculate_median(max_age, min_samples)
            if median is not None:
                # v2.2.0: Check for anchor drift from YAML baseline
                if yaml_fallback is not None and yaml_fallback > 0:
                    drift_pct = abs(median - yaml_fallback) / yaml_fallback * 100
                    drift_threshold = self.config.get("drift_warning_pct", 10.0)
                    if drift_pct > drift_threshold:
                        logger.warning(
                            "ANCHOR_DRIFT: %s dynamic=%.4f yaml=%.4f drift=%.1f%%",
                            pair, median, yaml_fallback, drift_pct
                        )
                
                return median, "dynamic"
        
        # Fallback to YAML
        if yaml_fallback is not None:
            return yaml_fallback, "yaml_fallback"
        
        return None, "none"
    
    def get_anchor_detailed(
        self,
        pair: str,
        yaml_fallback: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Get detailed anchor information including age.
        
        Returns dict with: anchor_value, anchor_source, anchor_age_seconds, sample_count
        """
        result = {
            "anchor_value": None,
            "anchor_source": "none",
            "anchor_age_seconds": None,
            "sample_count": 0,
        }
        
        if pair in self._pairs:
            pair_data = self._pairs[pair]
            max_age = self.config.get("max_sample_age_seconds", 3600)
            min_samples = self.config.get("min_samples", 3)
            
            valid_samples = pair_data.get_valid_samples(max_age)
            result["sample_count"] = len(valid_samples)
            
            if valid_samples and len(valid_samples) >= min_samples:
                median = pair_data.calculate_median(max_age, min_samples)
                if median is not None:
                    result["anchor_value"] = median
                    result["anchor_source"] = "dynamic"
                    # Age is time since newest sample
                    newest_ts = max(s.timestamp for s in valid_samples)
                    result["anchor_age_seconds"] = time.time() - newest_ts
                    return result
        
        # Fallback to YAML
        if yaml_fallback is not None:
            result["anchor_value"] = yaml_fallback
            result["anchor_source"] = "yaml_fallback"
            result["anchor_age_seconds"] = None  # YAML has no age
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about anchor data."""
        max_age = self.config.get("max_sample_age_seconds", 3600)
        
        active_pairs = 0
        total_samples = 0
        
        for pair_data in self._pairs.values():
            valid_samples = pair_data.get_valid_samples(max_age)
            if valid_samples:
                active_pairs += 1
                total_samples += len(valid_samples)
        
        return {
            "total_pairs": len(self._pairs),
            "active_pairs": active_pairs,
            "total_samples": total_samples,
            "config": {
                "min_samples": self.config.get("min_samples"),
                "max_sample_age_seconds": self.config.get("max_sample_age_seconds"),
            },
        }
    
    def flush(self) -> None:
        """Flush cache to disk."""
        self._save_cache()
    
    def clear(self) -> None:
        """Clear all anchor data."""
        self._pairs.clear()


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_anchor_manager: DynamicAnchorManager | None = None


def get_anchor_manager() -> DynamicAnchorManager:
    """Get the singleton anchor manager."""
    global _anchor_manager
    if _anchor_manager is None:
        _anchor_manager = DynamicAnchorManager()
    return _anchor_manager


def reset_anchor_manager() -> None:
    """Reset the singleton (for testing). Does NOT load from cache."""
    global _anchor_manager
    if _anchor_manager is not None:
        _anchor_manager.clear()
    # Create fresh manager without loading cache
    _anchor_manager = DynamicAnchorManager(load_cache=False)
