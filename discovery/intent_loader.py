# PATH: discovery/intent_loader.py
"""
Intent-driven universe loader (Roadmap Appendix A Step 1).

Parses config/intent.txt and provides canonical pair-universe per chain.

Format:
  chain:TOKENA/TOKENB
  
Example:
  arbitrum_one:WETH/USDC
  arbitrum_one:ARB/WETH

This module does NOT resolve token addresses. That's done by discovery/verify.py.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Set

logger = logging.getLogger("discovery.intent_loader")

DEFAULT_INTENT_PATH = Path("config/intent.txt")


class IntentPair(NamedTuple):
    """A trading pair from intent.txt."""
    chain: str
    token_a: str
    token_b: str
    
    @property
    def canonical_key(self) -> str:
        """Canonical key with sorted tokens (for deduplication)."""
        t0, t1 = sorted([self.token_a, self.token_b])
        return f"{self.chain}:{t0}/{t1}"
    
    @property
    def display_key(self) -> str:
        """Display key (preserves original order)."""
        return f"{self.chain}:{self.token_a}/{self.token_b}"


class IntentUniverse:
    """
    Loaded intent universe with chain->pairs mapping.
    """
    
    def __init__(self):
        self._pairs: Dict[str, List[IntentPair]] = {}  # chain -> pairs
        self._all_pairs: List[IntentPair] = []
        self._source_path: Optional[Path] = None
    
    def add_pair(self, pair: IntentPair) -> None:
        """Add a pair to the universe."""
        if pair.chain not in self._pairs:
            self._pairs[pair.chain] = []
        self._pairs[pair.chain].append(pair)
        self._all_pairs.append(pair)
    
    def get_pairs_for_chain(self, chain: str) -> List[IntentPair]:
        """Get all pairs for a specific chain."""
        return self._pairs.get(chain, [])
    
    def get_all_chains(self) -> List[str]:
        """Get list of all chains in the universe."""
        return list(self._pairs.keys())
    
    def get_all_pairs(self) -> List[IntentPair]:
        """Get all pairs across all chains."""
        return self._all_pairs.copy()
    
    def get_tokens_for_chain(self, chain: str) -> Set[str]:
        """Get set of unique tokens for a chain."""
        tokens = set()
        for pair in self._pairs.get(chain, []):
            tokens.add(pair.token_a)
            tokens.add(pair.token_b)
        return tokens

    def get_pair_tuples_for_chain(self, chain: str) -> List[tuple]:
        """Get pairs as list of (token_a, token_b) symbol tuples for a chain.

        Returns the display-order tuples (as written in intent.txt), deduplicated
        by canonical key. Used by m7 prewarm and other consumers that only need
        the symbol layer (addresses resolved separately via discovery).

        E1.30: Tokens are case-normalized against ``config/core_tokens.yaml``
        so that mixed-case symbols like ``cbBTC`` / ``cbETH`` resolve correctly
        downstream (``parse_intent_line`` uppercases everything; this method
        undoes that for tokens whose canonical casing differs).
        """
        # Build case-preserving symbol map for this chain from core_tokens.yaml.
        casing: Dict[str, str] = {}
        try:
            from config import load_core_tokens

            chain_tokens = load_core_tokens().get(chain, {}) or {}
            for canonical in chain_tokens.keys():
                casing[canonical.upper()] = canonical
        except Exception:
            casing = {}

        def _canon_case(sym: str) -> str:
            return casing.get(sym.upper(), sym)

        seen = set()
        result: List[tuple] = []
        for pair in self._pairs.get(chain, []):
            key = pair.canonical_key
            if key in seen:
                continue
            seen.add(key)
            result.append((_canon_case(pair.token_a), _canon_case(pair.token_b)))
        return result
    
    def __len__(self) -> int:
        return len(self._all_pairs)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        return {
            "source_path": str(self._source_path) if self._source_path else None,
            "total_pairs": len(self._all_pairs),
            "chains": {
                chain: [p.display_key for p in pairs]
                for chain, pairs in self._pairs.items()
            },
        }


def parse_intent_line(line: str) -> Optional[IntentPair]:
    """
    Parse a single intent line.
    
    Format: chain:TOKENA/TOKENB
    
    Returns IntentPair or None if line is comment/empty/invalid.
    """
    line = line.strip()
    
    # Skip empty lines and comments
    if not line or line.startswith("#"):
        return None
    
    # Parse chain:PAIR format
    if ":" not in line:
        logger.debug("Invalid intent line (no colon): %s", line)
        return None
    
    chain, pair_str = line.split(":", 1)
    chain = chain.strip().lower()
    pair_str = pair_str.strip()
    
    # Parse TOKENA/TOKENB
    if "/" not in pair_str:
        logger.debug("Invalid pair format (no slash): %s", pair_str)
        return None
    
    parts = pair_str.split("/")
    if len(parts) != 2:
        logger.debug("Invalid pair format (multiple slashes): %s", pair_str)
        return None
    
    token_a = parts[0].strip().upper()
    token_b = parts[1].strip().upper()
    
    if not token_a or not token_b:
        logger.debug("Empty token in pair: %s", pair_str)
        return None
    
    return IntentPair(chain=chain, token_a=token_a, token_b=token_b)


def load_intent(path: Optional[Path] = None) -> IntentUniverse:
    """
    Load intent.txt and return IntentUniverse.
    
    Args:
        path: Path to intent.txt (default: config/intent.txt; can be
              overridden via ``ARBY_INTENT_FILE`` environment variable).
        
    Returns:
        IntentUniverse with all parsed pairs
    """
    import os

    if path is None:
        env_override = os.environ.get("ARBY_INTENT_FILE", "").strip()
        if env_override:
            path = Path(env_override)
            logger.info("Intent file overridden via ARBY_INTENT_FILE=%s", path)
    path = path or DEFAULT_INTENT_PATH
    universe = IntentUniverse()
    universe._source_path = path
    
    if not path.exists():
        logger.warning("Intent file not found: %s", path)
        return universe
    
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        
        parsed_count = 0
        skipped_count = 0
        seen_keys: Set[str] = set()
        
        for line in lines:
            pair = parse_intent_line(line)
            if pair is None:
                if line.strip() and not line.strip().startswith("#"):
                    skipped_count += 1
                continue
            
            # Deduplicate by canonical key
            if pair.canonical_key in seen_keys:
                logger.debug("Duplicate pair skipped: %s", pair.display_key)
                continue
            
            seen_keys.add(pair.canonical_key)
            universe.add_pair(pair)
            parsed_count += 1
        
        logger.info(
            "Loaded intent: %d pairs from %s (%d skipped)",
            parsed_count, path.name, skipped_count
        )
        
    except Exception as e:
        logger.error("Failed to load intent file: %s", e)
    
    return universe


def get_chain_pairs(chain: str, path: Optional[Path] = None) -> List[IntentPair]:
    """
    Convenience function: Get pairs for a specific chain.
    
    Args:
        chain: Chain key (e.g., "arbitrum_one")
        path: Optional path to intent.txt
        
    Returns:
        List of IntentPair for the chain
    """
    universe = load_intent(path)
    return universe.get_pairs_for_chain(chain)


# =============================================================================
# MODULE CACHE (for singleton pattern)
# =============================================================================

_cached_universe: Optional[IntentUniverse] = None


def get_intent_universe(reload: bool = False) -> IntentUniverse:
    """
    Get the cached intent universe (singleton).
    
    Args:
        reload: Force reload from disk
        
    Returns:
        IntentUniverse
    """
    global _cached_universe
    
    if _cached_universe is None or reload:
        _cached_universe = load_intent()
    
    return _cached_universe


def clear_intent_cache() -> None:
    """Clear the cached universe (for testing)."""
    global _cached_universe
    _cached_universe = None
