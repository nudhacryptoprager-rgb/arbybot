"""
dex/gating.py - DEX gating based on verification status.

Provides:
- Load and filter DEXes by verification status
- Quoting universe (verified_for_quoting)
- Execution universe (verified_for_execution)
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DEXConfig:
    """DEX configuration with verification status."""
    chain_key: str
    dex_key: str
    name: str
    adapter_type: str
    factory: str | None
    router: str | None
    quoter: str | None
    fee_tiers: list[int]
    enabled: bool
    verified_for_quoting: bool
    verified_for_execution: bool


def load_dex_configs(dexes_yaml_path: Path) -> dict[str, dict[str, DEXConfig]]:
    """
    Load DEX configs from dexes.yaml.
    
    Returns:
        {chain_key: {dex_key: DEXConfig}}
    """
    if not dexes_yaml_path.exists():
        logger.warning(f"dexes.yaml not found at {dexes_yaml_path}")
        return {}
    
    with open(dexes_yaml_path) as f:
        dexes_yaml = yaml.safe_load(f)
    
    result: dict[str, dict[str, DEXConfig]] = {}
    
    for chain_key, dexes in dexes_yaml.items():
        result[chain_key] = {}
        
        for dex_key, config in dexes.items():
            dex_config = DEXConfig(
                chain_key=chain_key,
                dex_key=dex_key,
                name=config.get("name", dex_key),
                adapter_type=config.get("adapter_type", "unknown"),
                factory=config.get("factory"),
                router=config.get("router"),
                quoter=config.get("quoter_v2") or config.get("quoter"),
                fee_tiers=config.get("fee_tiers", []),
                enabled=config.get("enabled", False),
                verified_for_quoting=config.get("verified_for_quoting", False),
                verified_for_execution=config.get("verified_for_execution", False),
            )
            result[chain_key][dex_key] = dex_config
    
    return result


def load_anchor_verification(report_path: Path) -> dict[str, dict]:
    """
    Load anchor verification report.
    
    Returns:
        {chain_key: {dex_key: verification_result}}
    """
    if not report_path.exists():
        logger.warning(f"Anchor verification report not found at {report_path}")
        return {}
    
    with open(report_path) as f:
        results = json.load(f)
    
    # Convert list to dict by chain_key
    by_chain = {}
    for result in results:
        chain_key = result.get("chain_key")
        if chain_key:
            by_chain[chain_key] = result
    
    return by_chain


class DEXGate:
    """
    Gating for DEX access based on verification status.
    
    Usage:
        gate = DEXGate.from_config()
        for dex in gate.quoting_universe("arbitrum_one"):
            # Only DEXes with verified_for_quoting=true
            ...
    """
    
    def __init__(
        self,
        dex_configs: dict[str, dict[str, DEXConfig]],
        anchor_results: dict[str, dict] | None = None,
    ):
        self.dex_configs = dex_configs
        self.anchor_results = anchor_results or {}
    
    @classmethod
    def from_config(
        cls,
        dexes_yaml: Path | None = None,
        anchor_report: Path | None = None,
    ) -> "DEXGate":
        """Create DEXGate from config files."""
        dexes_yaml = dexes_yaml or Path("config/dexes.yaml")
        anchor_report = anchor_report or Path("data/reports/anchor_verification.json")
        
        dex_configs = load_dex_configs(dexes_yaml)
        anchor_results = load_anchor_verification(anchor_report)
        
        return cls(dex_configs, anchor_results)
    
    def get_dex(self, chain_key: str, dex_key: str) -> DEXConfig | None:
        """Get DEX config by chain and key."""
        chain_dexes = self.dex_configs.get(chain_key, {})
        return chain_dexes.get(dex_key)
    
    def all_dexes(self, chain_key: str) -> Iterator[DEXConfig]:
        """Iterate all DEXes for a chain."""
        chain_dexes = self.dex_configs.get(chain_key, {})
        for dex in chain_dexes.values():
            yield dex
    
    def enabled_dexes(self, chain_key: str) -> Iterator[DEXConfig]:
        """Iterate enabled DEXes for a chain."""
        for dex in self.all_dexes(chain_key):
            if dex.enabled:
                yield dex
    
    def quoting_universe(self, chain_key: str) -> Iterator[DEXConfig]:
        """
        Iterate DEXes allowed for quoting.
        
        A DEX is in the quoting universe if:
        - enabled=true
        - verified_for_quoting=true (from config or anchor report)
        """
        for dex in self.enabled_dexes(chain_key):
            # Check config
            if dex.verified_for_quoting:
                yield dex
                continue
            
            # Check anchor report
            chain_result = self.anchor_results.get(chain_key, {})
            dex_result = chain_result.get("dexes", {}).get(dex.dex_key, {})
            if dex_result.get("verified_for_quoting", False):
                yield dex
    
    def execution_universe(self, chain_key: str) -> Iterator[DEXConfig]:
        """
        Iterate DEXes allowed for execution.
        
        A DEX is in the execution universe if:
        - enabled=true
        - verified_for_execution=true (from config or anchor report)
        """
        for dex in self.enabled_dexes(chain_key):
            # Check config
            if dex.verified_for_execution:
                yield dex
                continue
            
            # Check anchor report
            chain_result = self.anchor_results.get(chain_key, {})
            dex_result = chain_result.get("dexes", {}).get(dex.dex_key, {})
            if dex_result.get("verified_for_execution", False):
                yield dex
    
    def get_summary(self, chain_key: str) -> dict:
        """Get summary of DEX gating for a chain."""
        all_dexes = list(self.all_dexes(chain_key))
        enabled = list(self.enabled_dexes(chain_key))
        quoting = list(self.quoting_universe(chain_key))
        execution = list(self.execution_universe(chain_key))
        
        return {
            "chain": chain_key,
            "total_dexes": len(all_dexes),
            "enabled": len(enabled),
            "quoting_universe": len(quoting),
            "execution_universe": len(execution),
            "quoting_dexes": [d.dex_key for d in quoting],
            "execution_dexes": [d.dex_key for d in execution],
        }
