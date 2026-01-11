"""
strategy/config.py - Strategy configuration.

Gate thresholds and limits with per-chain overrides.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class GateThresholds:
    """Gate threshold configuration."""
    
    # Single-quote gates
    max_gas_estimate: int = 500_000
    max_ticks_crossed: int = 10
    max_price_deviation_bps: int = 1000  # 10%
    
    # Curve gates
    max_slippage_bps: int = 500  # 5%
    
    # Freshness
    max_quote_age_ms: int = 2000  # 2 seconds
    max_block_age_ms: int = 15000  # 15 seconds
    
    # PnL
    min_net_pnl_bps: int = 0  # Minimum profitable spread


@dataclass
class ChainOverride:
    """Per-chain threshold overrides."""
    chain_id: int
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyConfig:
    """Full strategy configuration."""
    
    # Default thresholds
    defaults: GateThresholds = field(default_factory=GateThresholds)
    
    # Per-chain overrides
    chain_overrides: dict[int, dict[str, Any]] = field(default_factory=dict)
    
    # Anchor DEX for price sanity
    anchor_dex: str = "uniswap_v3"
    
    def get_thresholds(self, chain_id: int) -> GateThresholds:
        """Get thresholds for a specific chain (with overrides applied)."""
        base = GateThresholds(
            max_gas_estimate=self.defaults.max_gas_estimate,
            max_ticks_crossed=self.defaults.max_ticks_crossed,
            max_price_deviation_bps=self.defaults.max_price_deviation_bps,
            max_slippage_bps=self.defaults.max_slippage_bps,
            max_quote_age_ms=self.defaults.max_quote_age_ms,
            max_block_age_ms=self.defaults.max_block_age_ms,
            min_net_pnl_bps=self.defaults.min_net_pnl_bps,
        )
        
        # Apply chain-specific overrides
        if chain_id in self.chain_overrides:
            overrides = self.chain_overrides[chain_id]
            for key, value in overrides.items():
                if hasattr(base, key):
                    setattr(base, key, value)
        
        return base


def load_strategy_config(config_path: Path | None = None) -> StrategyConfig:
    """
    Load strategy configuration from YAML file.
    
    Args:
        config_path: Path to strategy.yaml (default: config/strategy.yaml)
    
    Returns:
        StrategyConfig with defaults and overrides
    """
    if config_path is None:
        config_path = Path("config/strategy.yaml")
    
    if not config_path.exists():
        return StrategyConfig()
    
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    
    # Parse defaults
    defaults_data = data.get("defaults", {})
    defaults = GateThresholds(
        max_gas_estimate=defaults_data.get("max_gas_estimate", 500_000),
        max_ticks_crossed=defaults_data.get("max_ticks_crossed", 10),
        max_price_deviation_bps=defaults_data.get("max_price_deviation_bps", 1000),
        max_slippage_bps=defaults_data.get("max_slippage_bps", 500),
        max_quote_age_ms=defaults_data.get("max_quote_age_ms", 2000),
        max_block_age_ms=defaults_data.get("max_block_age_ms", 15000),
        min_net_pnl_bps=defaults_data.get("min_net_pnl_bps", 0),
    )
    
    # Parse chain overrides
    chain_overrides = {}
    for chain_key, overrides in data.get("chains", {}).items():
        # chain_key can be chain_id (int) or chain_name (str)
        # We'll store by chain_id for lookup
        if isinstance(chain_key, int):
            chain_id = chain_key
        else:
            # Map chain names to IDs
            chain_id_map = {
                "arbitrum_one": 42161,
                "base": 8453,
                "linea": 59144,
                "zksync": 324,
            }
            chain_id = chain_id_map.get(chain_key, 0)
        
        if chain_id > 0 and overrides:
            chain_overrides[chain_id] = overrides
    
    return StrategyConfig(
        defaults=defaults,
        chain_overrides=chain_overrides,
        anchor_dex=data.get("anchor_dex", "uniswap_v3"),
    )
