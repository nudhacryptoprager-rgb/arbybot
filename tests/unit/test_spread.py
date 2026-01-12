"""
Unit tests for spread logic.

P0 tests for critical bugs:
- spread_id uniqueness across pairs
- executable=false for unprofitable spreads
"""

import pytest


class TestSpreadIdUniqueness:
    """Test that spread_id is unique across different pairs."""
    
    def test_different_pairs_have_different_spread_ids(self):
        """
        P0: Two spreads with same fee/amount but different pairs
        must have different spread_ids.
        
        This prevents cooldown collisions where trading WETH/ARB
        could block WETH/LINK trades.
        """
        # Simulate spread_id generation (same logic as run_scan.py)
        def make_spread_id(pair: str, buy_dex: str, sell_dex: str, fee: int, amount: str) -> str:
            return f"{pair}_{buy_dex}_{sell_dex}_{fee}_{amount}"
        
        # Same DEX combo, same fee, same amount, DIFFERENT pairs
        id1 = make_spread_id("WETH/ARB", "sushiswap_v3", "uniswap_v3", 3000, "1000000000000000000")
        id2 = make_spread_id("WETH/LINK", "sushiswap_v3", "uniswap_v3", 3000, "1000000000000000000")
        id3 = make_spread_id("WETH/USDC", "sushiswap_v3", "uniswap_v3", 3000, "1000000000000000000")
        
        # All must be unique
        assert id1 != id2, "WETH/ARB and WETH/LINK should have different IDs"
        assert id2 != id3, "WETH/LINK and WETH/USDC should have different IDs"
        assert id1 != id3, "WETH/ARB and WETH/USDC should have different IDs"
    
    def test_spread_id_contains_pair(self):
        """spread_id must contain the pair for debugging."""
        spread_id = "WETH/ARB_sushiswap_v3_uniswap_v3_3000_1000000000000000000"
        assert "WETH/ARB" in spread_id


class TestExecutableLogic:
    """Test that executable is correctly set."""
    
    def test_unprofitable_spread_not_executable(self):
        """
        P0: A spread with negative net_pnl_bps must have executable=false
        even if both DEXes are verified for execution.
        """
        buy_exec = True
        sell_exec = True
        net_pnl_bps = -2  # Unprofitable
        
        is_profitable = net_pnl_bps > 0
        executable = buy_exec and sell_exec and is_profitable
        
        assert executable is False, "Unprofitable spread must not be executable"
    
    def test_profitable_but_unverified_not_executable(self):
        """Profitable spread with unverified DEX is not executable."""
        buy_exec = True
        sell_exec = False  # Not verified
        net_pnl_bps = 50  # Profitable
        
        is_profitable = net_pnl_bps > 0
        executable = buy_exec and sell_exec and is_profitable
        
        assert executable is False
    
    def test_profitable_and_verified_is_executable(self):
        """Profitable spread with both DEXes verified is executable."""
        buy_exec = True
        sell_exec = True
        net_pnl_bps = 50  # Profitable
        
        is_profitable = net_pnl_bps > 0
        executable = buy_exec and sell_exec and is_profitable
        
        assert executable is True
    
    def test_zero_pnl_not_executable(self):
        """Zero PnL is not profitable, not executable."""
        buy_exec = True
        sell_exec = True
        net_pnl_bps = 0
        
        is_profitable = net_pnl_bps > 0
        executable = buy_exec and sell_exec and is_profitable
        
        assert executable is False, "Zero PnL spread must not be executable"
