# PATH: config/pairs.py
"""
Pair configuration loader for ARBY.

Loads trading pairs from:
1. intent.txt (canonical source of truth)
2. YAML config pairs section (runtime override)
3. core_tokens.yaml (for addresses and decimals)

Usage:
    from config.pairs import load_pairs, get_pair_info
    
    # Load pairs for a chain
    pairs = load_pairs("arbitrum_one")
    
    # Get full info for a pair
    info = get_pair_info("arbitrum_one", "WETH", "USDC")
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import CONFIG_DIR, load_core_tokens

# v2.0.4: Import canonical pool_key builder
# RESTORE CONTRACT: Use core.pool_keys.make_pool_key() for all pool key generation
from core.pool_keys import make_pool_key


@dataclass
class PairConfig:
    """Configuration for a trading pair."""
    chain: str
    token_in: str
    token_out: str
    token_in_address: Optional[str] = None
    token_out_address: Optional[str] = None
    token_in_decimals: int = 18
    token_out_decimals: int = 18
    fee_tiers: List[int] = None
    pool_addresses: Optional[List[str]] = None  # Optional: pre-resolved pool addresses
    # v2.6.0: pool_info stores dex/fee/address mapping for discovery_runtime
    pool_info: Optional[List[Dict[str, Any]]] = None  # [{dex, fee, address}, ...]
    
    def __post_init__(self):
        if self.fee_tiers is None:
            self.fee_tiers = [500, 3000]  # default v3 fee tiers
    
    @property
    def pair_tag(self) -> str:
        """Pool lookup tag: TOKENA_TOKENB"""
        return f"{self.token_in}_{self.token_out}"
    
    @property
    def display_name(self) -> str:
        """Human-readable: TOKENA/TOKENB"""
        return f"{self.token_in}/{self.token_out}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization."""
        result = {
            "chain": self.chain,
            "token_in": self.token_in,
            "token_out": self.token_out,
            "token_in_address": self.token_in_address,
            "token_out_address": self.token_out_address,
            "token_in_decimals": self.token_in_decimals,
            "token_out_decimals": self.token_out_decimals,
            "fee_tiers": self.fee_tiers,
            "pair_tag": self.pair_tag,
            "display_name": self.display_name,
        }
        if self.pool_addresses:
            result["pool_addresses"] = self.pool_addresses
        if self.pool_info:
            result["pool_info"] = self.pool_info
        return result

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PairConfig":
        """Deserialize from to_dict() output (hot pairs cache round-trip)."""
        return cls(
            chain=d["chain"],
            token_in=d["token_in"],
            token_out=d["token_out"],
            token_in_address=d.get("token_in_address"),
            token_out_address=d.get("token_out_address"),
            token_in_decimals=d.get("token_in_decimals", 18),
            token_out_decimals=d.get("token_out_decimals", 18),
            fee_tiers=d.get("fee_tiers"),
            pool_addresses=d.get("pool_addresses"),
            pool_info=d.get("pool_info"),
        )


def parse_intent_file(chain_filter: Optional[str] = None) -> List[Tuple[str, str, str]]:
    """
    Parse intent.txt and extract pairs.
    
    Args:
        chain_filter: Only return pairs for this chain (e.g. "arbitrum_one")
        
    Returns:
        List of (chain, token_in, token_out) tuples
    """
    intent_path = CONFIG_DIR / "intent.txt"
    if not intent_path.exists():
        return []
    
    pairs = []
    with open(intent_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Format: chain:TOKENA/TOKENB
            if ":" not in line or "/" not in line:
                continue
            try:
                chain, pair_str = line.split(":", 1)
                token_in, token_out = pair_str.split("/", 1)
                chain = chain.strip()
                token_in = token_in.strip()
                token_out = token_out.strip()
                
                if chain_filter and chain != chain_filter:
                    continue
                    
                pairs.append((chain, token_in, token_out))
            except ValueError:
                continue
    
    return pairs


def load_pairs_from_config(config: Dict[str, Any], chain: str) -> List[Tuple[str, str, List[int]]]:
    """
    Load pairs from YAML config's pairs section.
    
    Args:
        config: Loaded YAML config dict
        chain: Chain key for context
        
    Returns:
        List of (token_in, token_out, fee_tiers) tuples
    """
    pairs_section = config.get("pairs", [])
    if not pairs_section:
        return []
    
    result = []
    for p in pairs_section:
        token_in = p.get("token_in")
        token_out = p.get("token_out")
        fee_tiers = p.get("fee_tiers", [500, 3000])
        if token_in and token_out:
            result.append((token_in, token_out, fee_tiers))
    
    return result


def resolve_token_info(chain: str, symbol: str) -> Tuple[Optional[str], int]:
    """
    Resolve token address and decimals from core_tokens.yaml.
    
    Args:
        chain: Chain key
        symbol: Token symbol
        
    Returns:
        (address, decimals) tuple
    """
    tokens = load_core_tokens()
    chain_tokens = tokens.get(chain, {})
    token_info = chain_tokens.get(symbol, {})
    
    address = token_info.get("address")
    decimals = token_info.get("decimals", 18)
    
    return address, decimals


def load_pairs(
    chain: str,
    config: Optional[Dict[str, Any]] = None,
    use_intent: bool = False,
    force_intent: bool = False,
) -> List[PairConfig]:
    """
    Load pairs for a chain with full token info.
    
    Priority:
    1. If force_intent=True, use intent.txt directly (ignore config pairs)
    2. If config has pairs section, use it (runtime override)
    3. If use_intent=True, fallback to intent.txt
    4. If neither, return empty list
    
    Args:
        chain: Chain key (e.g. "arbitrum_one")
        config: Optional YAML config dict with pairs section
        use_intent: Whether to fallback to intent.txt
        force_intent: If True, use intent.txt directly (v2.3.0 intent_forced mode)
                      NOTE: This does NOT verify pools on-chain. See verify_v3_pools.py.
        
    Returns:
        List of PairConfig objects with resolved addresses/decimals
    """
    result = []
    
    # v2.3.0: force_intent bypasses config pairs entirely
    if force_intent:
        try:
            from discovery.intent_loader import get_intent_universe
            universe = get_intent_universe()
            intent_pairs = universe.get_pairs_for_chain(chain)
            for pair in intent_pairs:
                in_addr, in_dec = resolve_token_info(chain, pair.token_a)
                out_addr, out_dec = resolve_token_info(chain, pair.token_b)
                
                result.append(PairConfig(
                    chain=chain,
                    token_in=pair.token_a,
                    token_out=pair.token_b,
                    token_in_address=in_addr,
                    token_out_address=out_addr,
                    token_in_decimals=in_dec,
                    token_out_decimals=out_dec,
                    fee_tiers=[500, 3000],  # default for intent pairs
                ))
            return result
        except ImportError:
            pass  # Fall through to config pairs
    
    # Try config pairs first
    if config:
        config_pairs = load_pairs_from_config(config, chain)
        for token_in, token_out, fee_tiers in config_pairs:
            in_addr, in_dec = resolve_token_info(chain, token_in)
            out_addr, out_dec = resolve_token_info(chain, token_out)
            
            result.append(PairConfig(
                chain=chain,
                token_in=token_in,
                token_out=token_out,
                token_in_address=in_addr,
                token_out_address=out_addr,
                token_in_decimals=in_dec,
                token_out_decimals=out_dec,
                fee_tiers=fee_tiers,
            ))
    
    # Fallback to intent.txt
    # v2.2.0 Fix Step 9: Use discovery/intent_loader.py as canonical module
    if not result and use_intent:
        try:
            from discovery.intent_loader import get_intent_universe
            universe = get_intent_universe()
            intent_pairs = universe.get_pairs_for_chain(chain)
            for pair in intent_pairs:
                in_addr, in_dec = resolve_token_info(chain, pair.token_a)
                out_addr, out_dec = resolve_token_info(chain, pair.token_b)
                
                result.append(PairConfig(
                    chain=chain,
                    token_in=pair.token_a,
                    token_out=pair.token_b,
                    token_in_address=in_addr,
                    token_out_address=out_addr,
                    token_in_decimals=in_dec,
                    token_out_decimals=out_dec,
                    fee_tiers=[500, 3000],  # default for intent pairs
                ))
        except ImportError:
            # v2.2.1 Fix Step 9: Emit warning when using legacy fallback
            import logging
            logging.getLogger(__name__).warning(
                "INTENT_LOADER_FALLBACK: Using legacy parse_intent_file() - "
                "discovery/intent_loader.py not available. This is deprecated."
            )
            intent_pairs = parse_intent_file(chain_filter=chain)
            for _, token_in, token_out in intent_pairs:
                in_addr, in_dec = resolve_token_info(chain, token_in)
                out_addr, out_dec = resolve_token_info(chain, token_out)
                
                result.append(PairConfig(
                    chain=chain,
                    token_in=token_in,
                    token_out=token_out,
                    token_in_address=in_addr,
                    token_out_address=out_addr,
                    token_in_decimals=in_dec,
                    token_out_decimals=out_dec,
                    fee_tiers=[500, 3000],  # default for intent pairs
                ))
    
    return result


def get_pair_info(chain: str, token_in: str, token_out: str) -> Optional[PairConfig]:
    """
    Get full info for a specific pair.
    
    Args:
        chain: Chain key
        token_in: Input token symbol
        token_out: Output token symbol
        
    Returns:
        PairConfig or None if tokens not found
    """
    in_addr, in_dec = resolve_token_info(chain, token_in)
    out_addr, out_dec = resolve_token_info(chain, token_out)
    
    return PairConfig(
        chain=chain,
        token_in=token_in,
        token_out=token_out,
        token_in_address=in_addr,
        token_out_address=out_addr,
        token_in_decimals=in_dec,
        token_out_decimals=out_dec,
    )


def is_pool_disabled(
    config: Dict[str, Any],
    dex: str,
    pair_tag: str,
    fee_tier: int,
) -> Optional[Dict[str, Any]]:
    """
    Check if a pool is in the disabled_pools section.
    
    Args:
        config: YAML config dict
        dex: DEX key (e.g. "uniswap_v3")
        pair_tag: Pair tag (e.g. "WETH_USDC")
        fee_tier: Fee tier (e.g. 500)
        
    Returns:
        Disabled pool info dict if disabled, None otherwise
        The dict contains: address, reason, detail, evidence_run, disabled_date
    """
    disabled_pools = config.get("disabled_pools", {})
    # v2.0.4: Use canonical pool_key builder
    key = make_pool_key(dex, pair_tag, fee_tier)
    
    if key in disabled_pools:
        info = disabled_pools[key]
        if isinstance(info, dict):
            return info
        # Legacy: just address string
        return {"address": info, "reason": "DISABLED"}
    
    return None


def get_pool_address(
    config: Dict[str, Any],
    dex: str,
    pair_tag: str,
    fee_tier: Optional[int] = None,
    enforcement_mode: str = "warn",
) -> Optional[str]:
    """
    Look up pool address from config.pools section.
    
    Format: pools.{dex}_{pair_tag}_{fee_tier}
    Example: pools.uniswap_v3_WETH_USDC_500
    
    Args:
        config: YAML config dict
        dex: DEX key (e.g. "uniswap_v3")
        pair_tag: Pair tag (e.g. "WETH_USDC")
        fee_tier: Optional fee tier (e.g. 500)
        enforcement_mode: "warn" (default) or "enforce"
            - warn: return None if not found (will be rejected with POOL_MISSING)
            - enforce: raise ValueError if not in whitelist
        
    Returns:
        Pool address or None
        
    Raises:
        ValueError: if enforcement_mode="enforce" and pool not in whitelist
    """
    pools = config.get("pools", {})
    
    # v2.0.8: STRICT fee-tier lookup - no fallback when fee_tier is specified
    if fee_tier is not None:
        # v2.0.4: Use canonical pool_key builder
        key = make_pool_key(dex, pair_tag, fee_tier)
        if key in pools:
            addr = pools[key]
            # Skip null/zero addresses
            if addr and addr != "0x0000000000000000000000000000000000000000":
                return addr
        # v2.0.8: fee_tier specified but not found - return None or raise (NO FALLBACK)
        if enforcement_mode == "enforce":
            raise ValueError(f"WHITELIST_ENFORCE: pool not found for {dex}/{pair_tag}/{fee_tier}")
        return None
    
    # fee_tier not specified - find any matching pool (legacy behavior)
    for key, addr in pools.items():
        if dex in key and pair_tag in key:
            if addr and addr != "0x0000000000000000000000000000000000000000":
                return addr
    
    # Pool not found
    if enforcement_mode == "enforce":
        raise ValueError(f"WHITELIST_ENFORCE: pool not found for {dex}/{pair_tag}/{fee_tier}")
    
    return None
