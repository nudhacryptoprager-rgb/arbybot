"""
discovery/registry.py - Registry-driven pool management.

Replaces hardcoded smoke harness with config-driven pool discovery.

Pipeline:
1. Parse intent.txt → list of (chain, base, quote) pairs
2. Resolve token addresses via core_tokens.yaml
3. Generate pool candidates per DEX/fee tier
4. Store in registry for scanner consumption
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import yaml

from core.logging import get_logger
from core.models import Token, Pool
from core.constants import DexType, PoolStatus

logger = get_logger(__name__)


@dataclass
class IntentPair:
    """A trading pair from intent.txt."""
    chain_key: str
    base_symbol: str
    quote_symbol: str
    
    @property
    def pair_id(self) -> str:
        return f"{self.chain_key}:{self.base_symbol}/{self.quote_symbol}"


@dataclass
class ResolvedPair:
    """A pair with resolved token addresses."""
    chain_key: str
    chain_id: int
    base: Token
    quote: Token
    source: str = "core_tokens"  # or "discovery"
    
    @property
    def pair_id(self) -> str:
        return f"{self.chain_key}:{self.base.symbol}/{self.quote.symbol}"


@dataclass
class PoolCandidate:
    """A pool candidate for scanning."""
    pool: Pool
    base: Token
    quote: Token
    dex_key: str
    priority: int = 0  # Lower = higher priority
    
    def to_dict(self) -> dict:
        return {
            "chain_id": self.pool.chain_id,
            "dex_key": self.dex_key,
            "dex_type": self.pool.dex_type.value,
            "pool_address": self.pool.pool_address,
            "base": self.base.symbol,
            "quote": self.quote.symbol,
            "fee": self.pool.fee,
            "priority": self.priority,
        }


class IntentParser:
    """Parse intent.txt into trading pairs."""
    
    def __init__(self, intent_path: Path):
        self.intent_path = intent_path
    
    def parse(self) -> list[IntentPair]:
        """Parse intent file into pairs."""
        pairs = []
        
        with open(self.intent_path) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                
                # Parse chain:BASE/QUOTE
                if ":" not in line or "/" not in line:
                    logger.warning(f"Invalid intent line {line_num}: {line}")
                    continue
                
                chain_part, pair_part = line.split(":", 1)
                chain_key = chain_part.strip()
                
                if "/" not in pair_part:
                    logger.warning(f"Invalid pair format line {line_num}: {line}")
                    continue
                
                base, quote = pair_part.split("/", 1)
                pairs.append(IntentPair(
                    chain_key=chain_key.strip(),
                    base_symbol=base.strip(),
                    quote_symbol=quote.strip(),
                ))
        
        logger.info(f"Parsed {len(pairs)} pairs from intent.txt")
        return pairs


class TokenResolver:
    """Resolve token symbols to addresses."""
    
    def __init__(self, tokens_config: dict, chains_config: dict):
        self.tokens_config = tokens_config
        self.chains_config = chains_config
    
    def resolve(self, chain_key: str, symbol: str) -> Token | None:
        """Resolve symbol to Token on chain."""
        chain_tokens = self.tokens_config.get(chain_key, {})
        token_config = chain_tokens.get(symbol)
        
        if not token_config:
            return None
        
        chain_id = self.chains_config.get(chain_key, {}).get("chain_id")
        if not chain_id:
            return None
        
        return Token(
            chain_id=chain_id,
            address=token_config["address"],
            symbol=symbol,
            name=token_config.get("name", symbol),
            decimals=token_config.get("decimals", 18),
            is_core=True,
        )
    
    def resolve_pair(self, pair: IntentPair) -> ResolvedPair | None:
        """Resolve an intent pair to tokens."""
        chain_id = self.chains_config.get(pair.chain_key, {}).get("chain_id")
        if not chain_id:
            logger.warning(f"Unknown chain: {pair.chain_key}")
            return None
        
        base = self.resolve(pair.chain_key, pair.base_symbol)
        quote = self.resolve(pair.chain_key, pair.quote_symbol)
        
        if not base:
            logger.debug(f"Cannot resolve base {pair.base_symbol} on {pair.chain_key}")
            return None
        
        if not quote:
            logger.debug(f"Cannot resolve quote {pair.quote_symbol} on {pair.chain_key}")
            return None
        
        return ResolvedPair(
            chain_key=pair.chain_key,
            chain_id=chain_id,
            base=base,
            quote=quote,
        )


class PoolRegistry:
    """
    Registry of pool candidates for scanning.
    
    Generates pool candidates from resolved pairs + DEX configs.
    """
    
    def __init__(
        self,
        chains_config: dict,
        dexes_config: dict,
        tokens_config: dict,
    ):
        self.chains_config = chains_config
        self.dexes_config = dexes_config
        self.resolver = TokenResolver(tokens_config, chains_config)
        
        # Cache
        self._resolved_pairs: list[ResolvedPair] = []
        self._pool_candidates: list[PoolCandidate] = []
    
    def load_intent(self, intent_path: Path) -> int:
        """Load and resolve intent pairs."""
        parser = IntentParser(intent_path)
        intent_pairs = parser.parse()
        
        self._resolved_pairs = []
        unresolved = []
        
        for pair in intent_pairs:
            resolved = self.resolver.resolve_pair(pair)
            if resolved:
                self._resolved_pairs.append(resolved)
            else:
                unresolved.append(pair.pair_id)
        
        if unresolved:
            logger.warning(
                f"Could not resolve {len(unresolved)} pairs",
                extra={"context": {"unresolved": unresolved[:10]}}  # First 10
            )
        
        logger.info(f"Resolved {len(self._resolved_pairs)} pairs from intent")
        return len(self._resolved_pairs)
    
    def generate_pool_candidates(self, chain_key: str | None = None) -> list[PoolCandidate]:
        """
        Generate pool candidates from resolved pairs.
        
        For each pair + DEX + fee tier, create a pool candidate.
        """
        self._pool_candidates = []
        
        for resolved in self._resolved_pairs:
            # Filter by chain if specified
            if chain_key and resolved.chain_key != chain_key:
                continue
            
            # Get DEX configs for this chain
            chain_dexes = self.dexes_config.get(resolved.chain_key, {})
            
            for dex_key, dex_config in chain_dexes.items():
                if not dex_config.get("enabled", False):
                    continue
                
                if not dex_config.get("verified_for_quoting", False):
                    continue
                
                adapter_type = dex_config.get("adapter_type", "")
                
                # Only V3-style DEXes for now
                if adapter_type != "uniswap_v3":
                    continue
                
                fee_tiers = dex_config.get("fee_tiers", [500, 3000])
                priority = dex_config.get("priority", 10)
                
                for fee in fee_tiers:
                    # Sort tokens for consistent pool representation
                    if resolved.quote.address.lower() < resolved.base.address.lower():
                        token0, token1 = resolved.quote, resolved.base
                    else:
                        token0, token1 = resolved.base, resolved.quote
                    
                    pool = Pool(
                        chain_id=resolved.chain_id,
                        dex_id=dex_key,
                        dex_type=DexType.UNISWAP_V3,
                        pool_address="",  # Will be computed or discovered
                        token0=token0,
                        token1=token1,
                        fee=fee,
                        status=PoolStatus.ACTIVE,
                    )
                    
                    candidate = PoolCandidate(
                        pool=pool,
                        base=resolved.base,
                        quote=resolved.quote,
                        dex_key=dex_key,
                        priority=priority,
                    )
                    
                    self._pool_candidates.append(candidate)
        
        # Sort by priority
        self._pool_candidates.sort(key=lambda c: c.priority)
        
        logger.info(
            f"Generated {len(self._pool_candidates)} pool candidates",
            extra={"context": {"chain": chain_key or "all"}}
        )
        
        return self._pool_candidates
    
    def get_candidates_for_chain(self, chain_key: str) -> list[PoolCandidate]:
        """Get pool candidates for a specific chain."""
        return [c for c in self._pool_candidates if c.pool.chain_id == self.chains_config.get(chain_key, {}).get("chain_id")]
    
    def get_summary(self) -> dict:
        """Get registry summary."""
        chains = {}
        for candidate in self._pool_candidates:
            chain_id = candidate.pool.chain_id
            if chain_id not in chains:
                chains[chain_id] = {"pairs": set(), "dexes": set(), "pools": 0}
            
            chains[chain_id]["pairs"].add(f"{candidate.base.symbol}/{candidate.quote.symbol}")
            chains[chain_id]["dexes"].add(candidate.dex_key)
            chains[chain_id]["pools"] += 1
        
        # Convert sets to lists for JSON
        for chain_id in chains:
            chains[chain_id]["pairs"] = list(chains[chain_id]["pairs"])
            chains[chain_id]["dexes"] = list(chains[chain_id]["dexes"])
        
        return {
            "total_resolved_pairs": len(self._resolved_pairs),
            "total_pool_candidates": len(self._pool_candidates),
            "chains": chains,
        }
    
    def save_snapshot(self, output_path: Path) -> Path:
        """Save registry snapshot."""
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filepath = output_path / f"registry_{timestamp}.json"
        
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": self.get_summary(),
            "resolved_pairs": [
                {
                    "chain_key": p.chain_key,
                    "chain_id": p.chain_id,
                    "base": p.base.symbol,
                    "quote": p.quote.symbol,
                    "base_address": p.base.address,
                    "quote_address": p.quote.address,
                }
                for p in self._resolved_pairs
            ],
            "pool_candidates": [c.to_dict() for c in self._pool_candidates],
        }
        
        with open(filepath, "w") as f:
            json.dump(snapshot, f, indent=2)
        
        logger.info(f"Registry snapshot saved: {filepath}")
        return filepath


def load_registry(
    intent_path: Path,
    config_dir: Path = Path("config"),
) -> PoolRegistry:
    """
    Load and initialize pool registry.
    
    Convenience function for scanner integration.
    """
    with open(config_dir / "chains.yaml") as f:
        chains_config = yaml.safe_load(f)
    
    with open(config_dir / "dexes.yaml") as f:
        dexes_config = yaml.safe_load(f)
    
    with open(config_dir / "core_tokens.yaml") as f:
        tokens_config = yaml.safe_load(f)
    
    registry = PoolRegistry(chains_config, dexes_config, tokens_config)
    registry.load_intent(intent_path)
    registry.generate_pool_candidates()
    
    return registry
