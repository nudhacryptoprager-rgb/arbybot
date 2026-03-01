# PATH: core/pool_keys.py
"""
Canonical pool key generation for ARBY.

v2.0.4: Single source of truth for pool_key and pair_tag formatting.

RESTORE CONTRACT:
    - make_pool_key() is the canonical function for generating pool keys
    - make_pair_tag() is the canonical function for generating pair tags
    - All modules should import from here instead of using f-strings directly

Format:
    pool_key: "{dex}_{pair_tag}_{fee_tier}" (e.g., "uniswap_v3_WETH_USDC_500")
    pair_tag: "{token_a}_{token_b}" (e.g., "WETH_USDC")

Usage:
    from core.pool_keys import make_pool_key, make_pair_tag

    pair_tag = make_pair_tag("WETH", "USDC")
    # Returns: "WETH_USDC"

    key = make_pool_key("uniswap_v3", "WETH/USDC", 500)
    # Returns: "uniswap_v3_WETH_USDC_500"
"""


def make_pair_tag(token_a: str, token_b: str) -> str:
    """
    Create canonical pair tag from two tokens.
    
    Args:
        token_a: First token symbol (e.g., "WETH")
        token_b: Second token symbol (e.g., "USDC")
    
    Returns:
        Pair tag string (e.g., "WETH_USDC")
    """
    return f"{token_a}_{token_b}"


def make_pool_key(dex: str, pair: str, fee_tier: int) -> str:
    """
    Create canonical pool key for identifying a unique pool.
    
    Args:
        dex: DEX identifier (e.g., "uniswap_v3", "sushiswap_v3")
        pair: Pair string with "/" separator (e.g., "WETH/USDC")
              or already formatted pair_tag (e.g., "WETH_USDC")
        fee_tier: Fee tier in hundredths of bps (e.g., 500 for 0.05%)
    
    Returns:
        Pool key string (e.g., "uniswap_v3_WETH_USDC_500")
    
    Examples:
        >>> make_pool_key("uniswap_v3", "WETH/USDC", 500)
        'uniswap_v3_WETH_USDC_500'
        >>> make_pool_key("sushiswap_v3", "WETH_USDT", 3000)
        'sushiswap_v3_WETH_USDT_3000'
    """
    # Normalize pair: replace "/" with "_"
    pair_tag = pair.replace("/", "_")
    return f"{dex}_{pair_tag}_{fee_tier}"


def parse_pool_key(pool_key: str) -> tuple:
    """
    Parse a pool key back into its components.
    
    Args:
        pool_key: Pool key string (e.g., "uniswap_v3_WETH_USDC_500")
    
    Returns:
        Tuple of (dex, pair_tag, fee_tier)
    
    Examples:
        >>> parse_pool_key("uniswap_v3_WETH_USDC_500")
        ('uniswap_v3', 'WETH_USDC', 500)
        >>> parse_pool_key("sushiswap_v3_WETH_USDT_3000")
        ('sushiswap_v3', 'WETH_USDT', 3000)
    
    Raises:
        ValueError: If pool_key format is invalid
    """
    # Split from the end to handle DEX names that might contain underscores
    parts = pool_key.rsplit("_", 3)
    if len(parts) < 4:
        raise ValueError(f"Invalid pool_key format: {pool_key}")
    
    dex = parts[0]
    token_a = parts[1]
    token_b = parts[2]
    fee_tier = int(parts[3])
    
    return (dex, f"{token_a}_{token_b}", fee_tier)
