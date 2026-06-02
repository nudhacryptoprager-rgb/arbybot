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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("strategy.dynamic_anchors")

# Default cache file location (legacy, use _get_anchor_cache_path() for chain-scoped)
DEFAULT_CACHE_PATH = Path("data/cache/dynamic_anchors.json")


def _get_anchor_cache_path(chain_key: str | None = None) -> Path:
    """Get chain-scoped dynamic anchors cache path.
    
    v3.2.11: Chain-scoped paths to prevent arbitrum_one <-> linea pollution.
    v3.2.12: WARN log when legacy path used for debug visibility.
    """
    if chain_key and chain_key != "unknown":
        return Path(f"data/cache/dynamic_anchors_{chain_key}.json")
    # v3.2.12: Log when falling back to legacy path
    logger.warning(
        "LEGACY_CACHE_PATH: dynamic_anchors using legacy path (chain_key=%s)",
        chain_key,
    )
    return DEFAULT_CACHE_PATH

# v2.3.0: Configurable TTL and sample settings
# Override via: ARBY_ANCHOR_MAX_AGE_SECONDS, ARBY_ANCHOR_MIN_SAMPLES
import os as _os
_env_max_age = int(_os.environ.get("ARBY_ANCHOR_MAX_AGE_SECONDS", "21600"))  # 6h default
_env_min_samples = int(_os.environ.get("ARBY_ANCHOR_MIN_SAMPLES", "3"))

# Config
DYNAMIC_ANCHOR_CONFIG = {
    # Minimum samples needed to use dynamic anchor
    "min_samples": _env_min_samples,
    
    # Maximum age of samples (seconds)
    # v2.3.0: Changed from 1h to 6h default for better sample accumulation
    "max_sample_age_seconds": _env_max_age,
    
    # Maximum samples to keep per pair
    "max_samples_per_pair": 100,
    
    # DEX priority for anchor (prefer more liquid DEXes)
    "dex_priority": [
        "uniswap_v3",
        "sushiswap_v3",
        "camelot_v3",
    ],
    
    # v2.3.0: Drift warning threshold (percentage)
    "drift_warning_pct": 10.0,
}


def canonicalize_pair(pair: str) -> str:
    """
    Canonicalize pair key for consistent lookup.
    
    v2.3.0: Sorts token symbols alphabetically to ensure
    WETH/USDC and USDC/WETH map to the same anchor.
    v3.2.25: Also normalizes case (wstETH → WSTETH) to prevent key fragmentation.
    
    Args:
        pair: Pair string like "WETH/USDC" or "USDC/WETH"
        
    Returns:
        Canonical pair like "USDC/WETH" (alphabetically sorted, uppercased)
    """
    if "/" not in pair:
        return pair.upper()
    tokens = pair.split("/")
    if len(tokens) != 2:
        return pair.upper()
    # v3.2.25: Uppercase tokens before sorting to prevent case fragmentation
    sorted_tokens = sorted([t.strip().upper() for t in tokens])
    return f"{sorted_tokens[0]}/{sorted_tokens[1]}"


def canonicalize_pair_with_direction(pair: str) -> Tuple[str, bool]:
    """
    Canonicalize pair key and detect if input was inverted relative to canonical.
    
    v2.9.0: Direction-aware anchors - fixes PRICE_SANITY_FAILED bug where
    prices were stored without direction normalization.
    v3.2.25: Also normalizes case (wstETH → WSTETH) to prevent key fragmentation.
    
    Args:
        pair: Pair string like "WETH/USDC" or "USDC/WETH"
        
    Returns:
        (canonical_pair, is_inverted) where:
        - canonical_pair: alphabetically sorted pair like "USDC/WETH" (uppercased)
        - is_inverted: True if input direction was inverted relative to canonical
          (e.g., input "WETH/USDC" → canonical "USDC/WETH" → is_inverted=True)
    """
    if "/" not in pair:
        return pair.upper(), False
    tokens = pair.split("/")
    if len(tokens) != 2:
        return pair.upper(), False
    # v3.2.25: Uppercase tokens before sorting to prevent case fragmentation
    normalized_tokens = [t.strip().upper() for t in tokens]
    sorted_tokens = sorted(normalized_tokens)
    canonical = f"{sorted_tokens[0]}/{sorted_tokens[1]}"
    # Inverted if first token moved position during sort
    is_inverted = normalized_tokens[0] != sorted_tokens[0]
    return canonical, is_inverted


# v2.2.3: Sanity bounds for anchor prices (reject obvious outliers)
# These are conservative bounds - real prices rarely exceed these
ANCHOR_PRICE_MIN = 1e-12  # Smallest reasonable price (e.g., wei/ETH)
ANCHOR_PRICE_MAX = 1e9   # Largest reasonable price (e.g., BTC/wei absurd)


def is_valid_anchor_price(price: float) -> bool:
    """
    Check if a price is within reasonable bounds.
    
    v2.2.3: Rejects NaN, Inf, zero, negative, and obvious outliers.
    """
    import math
    if not math.isfinite(price):
        return False
    if price <= 0:
        return False
    if price < ANCHOR_PRICE_MIN or price > ANCHOR_PRICE_MAX:
        return False
    return True


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
            from core.cache_freshness import cache_freshness

            chain_key = None
            name = self.cache_path.name
            if name.startswith("dynamic_anchors_") and name.endswith(".json"):
                chain_key = name[len("dynamic_anchors_") : -len(".json")]
            fresh, reason = cache_freshness(
                self.cache_path,
                schema_id="dynamic_anchors",
                chain=chain_key,
                max_age_seconds=float(self.config.get("max_sample_age_seconds", _env_max_age)),
            )
            if not fresh:
                logger.warning(
                    "Skipping stale dynamic_anchors cache %s (%s)",
                    self.cache_path,
                    reason,
                )
                return
        except Exception as exc:
            logger.debug("cache freshness check skipped: %s", exc)

        try:
            with open(self.cache_path) as f:
                data = json.load(f)
            
            filtered_count = 0
            for pair, pair_data in data.get("pairs", {}).items():
                # v2.2.3: Filter out invalid samples on load
                valid_samples = []
                for s in pair_data.get("samples", []):
                    price = s["price"]
                    if is_valid_anchor_price(price):
                        valid_samples.append(
                            AnchorSample(
                                timestamp=s["timestamp"],
                                price=price,
                                dex_id=s["dex_id"],
                                fee_tier=s["fee_tier"],
                                block=s.get("block", 0),
                            )
                        )
                    else:
                        filtered_count += 1
                
                if valid_samples:
                    self._pairs[pair] = PairAnchorData(
                        pair=pair,
                        samples=valid_samples,
                        last_updated=pair_data.get("last_updated", 0.0),
                    )
            
            if filtered_count > 0:
                logger.warning("Filtered %d invalid samples from anchor cache", filtered_count)
            
            logger.info(f"Loaded {len(self._pairs)} pairs from anchor cache")
        except Exception as e:
            logger.warning(f"Failed to load anchor cache: {e}")
    
    def _save_cache(self) -> None:
        """Save anchor data to cache."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            
            chain_key = None
            name = self.cache_path.name
            if name.startswith("dynamic_anchors_") and name.endswith(".json"):
                chain_key = name[len("dynamic_anchors_") : -len(".json")]
            now_ts = time.time()
            data = {
                "schema_version": "dynamic_anchors.1",
                "schema_id": "dynamic_anchors",
                "generated_at_utc": datetime.now(tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "chain_key": chain_key,
                "version": "1.0",
                "saved_at": now_ts,
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
        v2.3.0: Uses canonical pair key (sorted tokens).
        v2.9.0: Direction-aware - inverts price when storing if input pair
                was inverted relative to canonical direction.
        """
        # v2.9.0: Canonicalize pair key AND track direction
        canonical_pair, is_inverted = canonicalize_pair_with_direction(pair)
        
        if canonical_pair not in self._pairs:
            self._pairs[canonical_pair] = PairAnchorData(pair=canonical_pair)
        
        # v2.9.0: Normalize price to canonical direction
        # If input pair was inverted (e.g., WETH/ARB → ARB/WETH canonical),
        # the price must be inverted too (price was token_out/token_in, needs token_in/token_out)
        normalized_price = 1.0 / price if is_inverted else price
        
        # v2.2.3: Sanity check - reject outlier prices
        if not is_valid_anchor_price(normalized_price):
            logger.warning(
                "ANCHOR_SAMPLE_REJECTED: %s price=%s normalized=%s (outside valid range [%s, %s])",
                pair, price, normalized_price, ANCHOR_PRICE_MIN, ANCHOR_PRICE_MAX
            )
            return
        
        sample = AnchorSample(
            timestamp=time.time(),
            price=normalized_price,  # v2.9.0: Store in canonical direction
            dex_id=dex_id,
            fee_tier=fee_tier,
            block=block,
        )
        
        max_samples = self.config.get("max_samples_per_pair", 100)
        self._pairs[canonical_pair].add_sample(sample, max_samples)
    
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
        
        v2.3.0: Uses canonical pair key for lookup.
        v2.9.0: Direction-aware - inverts returned price when requested pair
                direction differs from canonical.
        """
        # v2.9.0: Canonicalize pair AND track direction for inversion
        canonical_pair, is_inverted = canonicalize_pair_with_direction(pair)
        
        # Check if we have enough dynamic samples
        if canonical_pair in self._pairs:
            pair_data = self._pairs[canonical_pair]
            max_age = self.config.get("max_sample_age_seconds", 21600)  # v2.3.0: 6h default
            min_samples = self.config.get("min_samples", 3)
            
            median = pair_data.calculate_median(max_age, min_samples)
            if median is not None:
                # v2.9.0: Invert anchor if requested pair direction differs from canonical
                if is_inverted:
                    median = 1.0 / median
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
        v2.3.0: Uses canonical pair key for lookup.
        v2.9.0: Direction-aware - inverts returned value when requested pair
                direction differs from canonical.
        """
        result = {
            "anchor_value": None,
            "anchor_source": "none",
            "anchor_age_seconds": None,
            "sample_count": 0,
        }
        
        # v2.9.0: Canonicalize pair AND track direction for inversion
        canonical_pair, is_inverted = canonicalize_pair_with_direction(pair)
        
        if canonical_pair in self._pairs:
            pair_data = self._pairs[canonical_pair]
            max_age = self.config.get("max_sample_age_seconds", 21600)  # v2.3.0: 6h default
            min_samples = self.config.get("min_samples", 3)
            
            valid_samples = pair_data.get_valid_samples(max_age)
            result["sample_count"] = len(valid_samples)
            
            if valid_samples and len(valid_samples) >= min_samples:
                median = pair_data.calculate_median(max_age, min_samples)
                if median is not None:
                    # v2.9.0: Invert anchor if requested pair direction differs from canonical
                    result["anchor_value"] = 1.0 / median if is_inverted else median
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
        max_age = self.config.get("max_sample_age_seconds", 21600)  # v2.3.0
        min_samples = self.config.get("min_samples", 3)
        
        active_pairs = 0
        total_samples = 0
        dynamic_ready_count = 0  # v2.3.0: Pairs with enough samples for dynamic anchor
        pairs_not_ready: List[str] = []  # v2.3.0: Pairs still on yaml_fallback
        
        for pair, pair_data in self._pairs.items():
            valid_samples = pair_data.get_valid_samples(max_age)
            if valid_samples:
                active_pairs += 1
                total_samples += len(valid_samples)
                if len(valid_samples) >= min_samples:
                    dynamic_ready_count += 1
                else:
                    # v2.3.0: Track pairs that need more samples
                    pairs_not_ready.append(f"{pair} ({len(valid_samples)}/{min_samples})")
        
        # v2.3.0: Compute coverage rate (pairs ready for dynamic anchoring)
        coverage_rate = 0.0
        if active_pairs > 0:
            coverage_rate = round(dynamic_ready_count / active_pairs, 4)
        
        return {
            "total_pairs": len(self._pairs),
            "active_pairs": active_pairs,
            "dynamic_ready_count": dynamic_ready_count,  # v2.3.0: Ready for dynamic anchor
            "coverage_rate": coverage_rate,  # v2.3.0: Fraction of pairs with dynamic data
            "total_samples": total_samples,
            # v2.3.0: List pairs still on yaml_fallback (actionable)
            "pairs_on_yaml_fallback": pairs_not_ready[:10],  # Limit to 10 for artifact size
            "pairs_on_yaml_fallback_count": len(pairs_not_ready),
            "config": {
                "min_samples": self.config.get("min_samples"),
                "max_sample_age_seconds": self.config.get("max_sample_age_seconds"),
                "drift_warning_pct": self.config.get("drift_warning_pct", 10.0),  # v2.3.0
            },
        }
    
    def flush(self) -> None:
        """Flush cache to disk."""
        self._save_cache()
    
    def clear(self) -> None:
        """Clear all anchor data."""
        self._pairs.clear()


# =============================================================================
# SINGLETON INSTANCE (v3.2.11: chain-scoped)
# =============================================================================

_anchor_manager: DynamicAnchorManager | None = None
_current_chain_key: str | None = None


def get_anchor_manager(chain_key: str | None = None) -> DynamicAnchorManager:
    """Get the singleton anchor manager.
    
    v3.2.11: chain_key parameter for chain-scoped persistence.
    If chain_key differs from current, flushes and reloads from new chain's cache.
    """
    global _anchor_manager, _current_chain_key
    
    # v3.2.11: If switching chains, save current and reload from new chain's cache
    if chain_key is not None and chain_key != _current_chain_key:
        if _anchor_manager is not None:
            # Save current state before switching
            _anchor_manager.flush()
            _anchor_manager = None
        _current_chain_key = chain_key
    
    if _anchor_manager is None:
        cache_path = _get_anchor_cache_path(_current_chain_key)
        _anchor_manager = DynamicAnchorManager(cache_path=cache_path)
    return _anchor_manager


def reset_anchor_manager() -> None:
    """Reset the singleton (for testing). Does NOT load from cache.
    
    v3.2.11: Also resets chain_key tracking.
    """
    global _anchor_manager, _current_chain_key
    if _anchor_manager is not None:
        _anchor_manager.clear()
    # Create fresh manager without loading cache
    _anchor_manager = DynamicAnchorManager(load_cache=False)
    _current_chain_key = None


# =============================================================================
# E5: Token→USD helper (drift-free resolver entry point)
# =============================================================================

# Stable tokens that act as the USD leg in a pair; used to derive token→USD
# price from anchors like WETH/USDC, AERO/USDC, cbBTC/USDC, etc.
_USD_LEG_SYMBOLS = {"USDC", "USDC_E", "USDBC", "USDT", "DAI", "FRAX", "LUSD", "USDE", "PYUSD"}


def get_token_usd_from_anchors(
    symbol: str,
    chain_key: Optional[str] = None,
) -> Optional[float]:
    """Return live USD price for ``symbol`` from the dynamic_anchors cache.

    Looks for any cached canonical pair ``<symbol>/<usd_leg>`` (or the
    inverse) and returns the median anchor converted to the symbol's USD
    value. Returns ``None`` when no anchor exists yet (caller should fall
    back to config/stable table).
    """
    if not symbol:
        return None
    sym = symbol.upper()
    if sym in _USD_LEG_SYMBOLS:
        return 1.0
    try:
        mgr = get_anchor_manager(chain_key)
    except Exception:
        return None
    for usd_leg in _USD_LEG_SYMBOLS:
        # mgr.get_anchor() is already direction-aware: requesting
        # "<sym>/<usd_leg>" returns the price in that direction (usd per sym),
        # regardless of whether the canonical key is inverted internally.
        pair_tag = f"{sym}/{usd_leg}"
        price, source = mgr.get_anchor(pair_tag)
        if price is None or source != "dynamic" or price <= 0:
            continue
        return float(price)
    return None


_M7_ANCHOR_SAMPLE_COUNTER = 0
_M7_ANCHOR_FLUSH_EVERY = int(_os.environ.get("ARBY_M7_ANCHOR_FLUSH_EVERY", "25"))


def record_m7_anchor_sample(
    chain_key: Optional[str],
    symbol_in: Optional[str],
    symbol_out: Optional[str],
    amount_in_wei: int,
    amount_out_wei: int,
    decimals_in: Optional[int],
    decimals_out: Optional[int],
    dex_id: Optional[str] = None,
    fee_tier: int = 0,
    block: int = 0,
) -> bool:
    """M7 hot-loop anchor accumulation hook (N5).

    Normalizes an observed swap quote (amount_in → amount_out on a real pool
    at ``block``) into a decimals-aware price and records it into the
    per-chain dynamic_anchors cache. Non-throwing: returns False on any
    invalid input so callers can use it fire-and-forget.

    Auto-flushes to disk every ``ARBY_M7_ANCHOR_FLUSH_EVERY`` recorded
    samples (default 25) so data survives process restarts; M4 relied on
    an explicit flush() at scanner shutdown which M7 hot-loop does not call.
    """
    global _M7_ANCHOR_SAMPLE_COUNTER
    if not symbol_in or not symbol_out:
        logger.debug("N5 reject: missing symbols in=%r out=%r", symbol_in, symbol_out)
        return False
    if amount_in_wei <= 0 or amount_out_wei <= 0:
        logger.debug("N5 reject: zero amounts in=%d out=%d", amount_in_wei, amount_out_wei)
        return False
    if decimals_in is None or decimals_out is None:
        logger.debug("N5 reject: missing decimals in=%r out=%r", decimals_in, decimals_out)
        return False
    try:
        base_units_in = float(amount_in_wei) / (10 ** int(decimals_in))
        base_units_out = float(amount_out_wei) / (10 ** int(decimals_out))
        if base_units_in <= 0:
            return False
        price = base_units_out / base_units_in
        if not is_valid_anchor_price(price):
            logger.debug("N5 reject: price out-of-bounds %s/%s price=%g",
                         symbol_in, symbol_out, price)
            return False
        mgr = get_anchor_manager(chain_key)
        pair_tag = f"{symbol_in.upper()}/{symbol_out.upper()}"
        mgr.record_quote(
            pair=pair_tag,
            price=price,
            dex_id=dex_id or "unknown",
            fee_tier=int(fee_tier) if fee_tier else 0,
            block=int(block) if block else 0,
        )
        _M7_ANCHOR_SAMPLE_COUNTER += 1
        logger.info("N5 record: %s price=%g chain=%s counter=%d flush_every=%d",
                    pair_tag, price, chain_key, _M7_ANCHOR_SAMPLE_COUNTER,
                    _M7_ANCHOR_FLUSH_EVERY)
        if _M7_ANCHOR_FLUSH_EVERY > 0 and (
            _M7_ANCHOR_SAMPLE_COUNTER % _M7_ANCHOR_FLUSH_EVERY == 0
        ):
            try:
                mgr.flush()
                logger.info("N5 flush OK after %d samples", _M7_ANCHOR_SAMPLE_COUNTER)
            except Exception as _fl_exc:
                logger.warning("N5 flush FAILED: %s", _fl_exc)
        return True
    except Exception as _rec_exc:
        logger.warning("N5 record exception: %s", _rec_exc)
        return False

