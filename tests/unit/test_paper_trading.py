"""
tests/unit/test_paper_trading.py - Paper trading tests.
"""

import json
import pytest
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone

from strategy.paper_trading import (
    PaperSession,
    PaperTrade,
    TradeOutcome,
    calculate_usdc_value,
    calculate_pnl_usdc,
)


@pytest.fixture
def temp_trades_dir(tmp_path):
    """Create temporary trades directory."""
    trades_dir = tmp_path / "trades"
    trades_dir.mkdir()
    return trades_dir


@pytest.fixture
def paper_session(temp_trades_dir):
    """Create paper session for testing."""
    return PaperSession(
        trades_dir=temp_trades_dir,
        session_id="test_session",
        cooldown_blocks=5,
        simulate_blocked=True,
    )


def make_paper_trade(
    spread_id: str = "uniswap_v3_sushiswap_v3_500_1000000000000000000",
    block_number: int = 100,
    net_pnl_bps: int = 10,
    executable: bool = True,
) -> PaperTrade:
    """Create a test paper trade."""
    return PaperTrade(
        spread_id=spread_id,
        block_number=block_number,
        timestamp=datetime.now(timezone.utc).isoformat(),
        chain_id=42161,
        buy_dex="uniswap_v3",
        sell_dex="sushiswap_v3",
        token_in="WETH",
        token_out="USDC",
        fee=500,
        amount_in_wei="1000000000000000000",
        buy_price="2500.00",
        sell_price="2502.50",
        spread_bps=10,
        gas_cost_bps=0,
        net_pnl_bps=net_pnl_bps,
        gas_price_gwei=0.01,
        amount_in_usdc=2500.0,
        expected_pnl_usdc=2.50,
        executable=executable,
        buy_verified=True,
        sell_verified=executable,  # If not executable, sell is not verified
    )


class TestPaperTrade:
    def test_to_dict(self):
        trade = make_paper_trade()
        d = trade.to_dict()
        assert d["spread_id"] == "uniswap_v3_sushiswap_v3_500_1000000000000000000"
        assert d["net_pnl_bps"] == 10
        assert d["executable"] is True
    
    def test_from_dict(self):
        trade = make_paper_trade()
        d = trade.to_dict()
        restored = PaperTrade.from_dict(d)
        assert restored.spread_id == trade.spread_id
        assert restored.net_pnl_bps == trade.net_pnl_bps


class TestPaperSessionCooldown:
    def test_no_cooldown_on_first_trade(self, paper_session):
        trade = make_paper_trade(block_number=100)
        assert not paper_session.is_on_cooldown(trade.spread_id, 100)
    
    def test_cooldown_within_blocks(self, paper_session):
        spread_id = "test_spread"
        
        # Record first trade at block 100
        trade1 = make_paper_trade(spread_id=spread_id, block_number=100)
        paper_session.record_trade(trade1)
        
        # Should be on cooldown at block 103 (< 5 blocks)
        assert paper_session.is_on_cooldown(spread_id, 103)
    
    def test_cooldown_expires(self, paper_session):
        spread_id = "test_spread"
        
        # Record first trade at block 100
        trade1 = make_paper_trade(spread_id=spread_id, block_number=100)
        paper_session.record_trade(trade1)
        
        # Should NOT be on cooldown at block 106 (>= 5 blocks)
        assert not paper_session.is_on_cooldown(spread_id, 106)
    
    def test_cooldown_skips_trade(self, paper_session):
        spread_id = "test_spread"
        
        # First trade
        trade1 = make_paper_trade(spread_id=spread_id, block_number=100)
        recorded1 = paper_session.record_trade(trade1)
        assert recorded1 is True
        
        # Second trade within cooldown
        trade2 = make_paper_trade(spread_id=spread_id, block_number=102)
        recorded2 = paper_session.record_trade(trade2)
        assert recorded2 is False
        assert trade2.outcome == TradeOutcome.COOLDOWN.value
        assert paper_session.stats["cooldown_skipped"] == 1


class TestPaperSessionOutcomes:
    def test_would_execute_outcome(self, paper_session):
        trade = make_paper_trade(executable=True, net_pnl_bps=10)
        paper_session.record_trade(trade)
        
        assert trade.outcome == TradeOutcome.WOULD_EXECUTE.value
        assert paper_session.stats["would_execute"] == 1
        assert paper_session.stats["total_pnl_bps"] == 10
    
    def test_blocked_exec_outcome(self, paper_session):
        trade = make_paper_trade(executable=False, net_pnl_bps=10)
        paper_session.record_trade(trade)
        
        assert trade.outcome == TradeOutcome.BLOCKED_EXEC.value
        assert paper_session.stats["blocked_exec"] == 1
        # Blocked trades don't add to PnL
        assert paper_session.stats["total_pnl_bps"] == 0
    
    def test_unprofitable_outcome(self, paper_session):
        trade = make_paper_trade(executable=True, net_pnl_bps=-5)
        paper_session.record_trade(trade)
        
        assert trade.outcome == TradeOutcome.UNPROFITABLE.value
        assert paper_session.stats["unprofitable"] == 1
    
    def test_simulate_blocked_policy(self, temp_trades_dir):
        # Create session that doesn't simulate blocked
        session = PaperSession(
            trades_dir=temp_trades_dir,
            session_id="no_blocked",
            simulate_blocked=False,
        )
        
        trade = make_paper_trade(executable=False, net_pnl_bps=10)
        recorded = session.record_trade(trade)
        
        assert recorded is False  # Not recorded because blocked
        assert session.stats["blocked_exec"] == 1


class TestPaperSessionPersistence:
    def test_append_and_load_trades(self, paper_session):
        trade1 = make_paper_trade(spread_id="spread_1", block_number=100)
        trade2 = make_paper_trade(spread_id="spread_2", block_number=200)
        
        paper_session.record_trade(trade1)
        paper_session.record_trade(trade2)
        
        # Load trades back
        loaded = paper_session.load_trades()
        assert len(loaded) == 2
        assert loaded[0].spread_id == "spread_1"
        assert loaded[1].spread_id == "spread_2"
    
    def test_jsonl_format(self, paper_session):
        trade = make_paper_trade()
        paper_session.record_trade(trade)
        
        # Check file is valid JSONL
        with open(paper_session.trades_file) as f:
            lines = f.readlines()
        
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["spread_id"] == trade.spread_id


class TestPaperSessionSummary:
    def test_get_summary(self, paper_session):
        trade1 = make_paper_trade(spread_id="s1", block_number=100, executable=True, net_pnl_bps=10)
        trade2 = make_paper_trade(spread_id="s2", block_number=200, executable=False, net_pnl_bps=5)
        
        paper_session.record_trade(trade1)
        paper_session.record_trade(trade2)
        
        summary = paper_session.get_summary()
        
        assert summary["session_id"] == "test_session"
        assert summary["cooldown_blocks"] == 5
        assert summary["stats"]["would_execute"] == 1
        assert summary["stats"]["blocked_exec"] == 1
        assert summary["stats"]["total_pnl_bps"] == 10  # Only from WOULD_EXECUTE


class TestUSDCCalculations:
    def test_calculate_usdc_value_1_eth(self):
        # 1 ETH at price 2500 USDC/ETH
        value = calculate_usdc_value(
            amount_in_wei=10**18,
            implied_price=Decimal("2500"),
            token_in_decimals=18,
        )
        assert value == 2500.0
    
    def test_calculate_usdc_value_0_1_eth(self):
        # 0.1 ETH at price 2500 USDC/ETH
        value = calculate_usdc_value(
            amount_in_wei=10**17,
            implied_price=Decimal("2500"),
            token_in_decimals=18,
        )
        assert value == 250.0
    
    def test_calculate_pnl_usdc_positive(self):
        # 1 ETH trade, 10 bps profit = $2.50
        pnl = calculate_pnl_usdc(
            amount_in_wei=10**18,
            net_pnl_bps=10,
            implied_price=Decimal("2500"),
            token_in_decimals=18,
        )
        assert pnl == 2.5
    
    def test_calculate_pnl_usdc_negative(self):
        # 1 ETH trade, -10 bps loss = -$2.50
        pnl = calculate_pnl_usdc(
            amount_in_wei=10**18,
            net_pnl_bps=-10,
            implied_price=Decimal("2500"),
            token_in_decimals=18,
        )
        assert pnl == -2.5
    
    def test_calculate_pnl_usdc_100_bps(self):
        # 1 ETH trade, 100 bps (1%) = $25
        pnl = calculate_pnl_usdc(
            amount_in_wei=10**18,
            net_pnl_bps=100,
            implied_price=Decimal("2500"),
            token_in_decimals=18,
        )
        assert pnl == 25.0


class TestNegativePnLWithExecutable:
    """Test that negative PnL trades are marked UNPROFITABLE, not WOULD_EXECUTE."""
    
    def test_negative_pnl_executable_true_gives_unprofitable(self, paper_session):
        """
        CRITICAL: executable=True should NOT result in WOULD_EXECUTE
        when net_pnl_bps is negative.
        """
        # Create trade with executable=True but negative PnL (-2 bps)
        trade = make_paper_trade(
            spread_id="test_negative_pnl",
            block_number=100,
            net_pnl_bps=-2,  # Negative PnL
            executable=True,  # Both DEXes verified
        )
        
        paper_session.record_trade(trade)
        
        # Outcome MUST be UNPROFITABLE, not WOULD_EXECUTE
        assert trade.outcome == TradeOutcome.UNPROFITABLE.value
        assert paper_session.stats["unprofitable"] == 1
        assert paper_session.stats["would_execute"] == 0
    
    def test_zero_pnl_gives_unprofitable(self, paper_session):
        """Zero PnL should also be UNPROFITABLE."""
        trade = make_paper_trade(
            spread_id="test_zero_pnl",
            block_number=100,
            net_pnl_bps=0,  # Zero PnL
            executable=True,
        )
        
        paper_session.record_trade(trade)
        
        assert trade.outcome == TradeOutcome.UNPROFITABLE.value
    
    def test_positive_pnl_executable_gives_would_execute(self, paper_session):
        """Positive PnL + executable should give WOULD_EXECUTE."""
        trade = make_paper_trade(
            spread_id="test_positive_pnl",
            block_number=100,
            net_pnl_bps=5,  # Positive PnL
            executable=True,
        )
        
        paper_session.record_trade(trade)
        
        assert trade.outcome == TradeOutcome.WOULD_EXECUTE.value
        assert paper_session.stats["would_execute"] == 1


class TestRevalidation:
    """Test paper trading revalidation logic."""
    
    def test_get_pending_revalidation_filters_correctly(self, tmp_path):
        """get_pending_revalidation returns only eligible trades."""
        from strategy.paper_trading import PaperSession, PaperTrade, TradeOutcome
        
        session = PaperSession(tmp_path, cooldown_blocks=5)
        
        # Trade 1: Should be pending (WOULD_EXECUTE, not revalidated)
        trade1 = PaperTrade(
            spread_id="spread_1", block_number=100, timestamp="2026-01-12T10:00:00Z",
            chain_id=42161, buy_dex="uni", sell_dex="sushi", token_in="WETH",
            token_out="USDC", fee=3000, amount_in_wei="1000000000000000000",
            buy_price="2500", sell_price="2550", spread_bps=200, gas_cost_bps=10,
            net_pnl_bps=190, gas_price_gwei=0.02,
            executable=True, buy_verified=True, sell_verified=True,
        )
        session.record_trade(trade1)
        
        # Trade 2: Should NOT be pending (already revalidated)
        trade2 = PaperTrade(
            spread_id="spread_2", block_number=100, timestamp="2026-01-12T10:00:00Z",
            chain_id=42161, buy_dex="uni", sell_dex="sushi", token_in="WETH",
            token_out="USDC", fee=3000, amount_in_wei="1000000000000000000",
            buy_price="2500", sell_price="2550", spread_bps=200, gas_cost_bps=10,
            net_pnl_bps=190, gas_price_gwei=0.02,
            executable=True, buy_verified=True, sell_verified=True,
            revalidated=True,  # Already revalidated
        )
        session.record_trade(trade2)
        
        # Trade 3: Should NOT be pending (BLOCKED outcome, not verified)
        trade3 = PaperTrade(
            spread_id="spread_3", block_number=100, timestamp="2026-01-12T10:00:00Z",
            chain_id=42161, buy_dex="uni", sell_dex="sushi", token_in="WETH",
            token_out="USDC", fee=3000, amount_in_wei="1000000000000000000",
            buy_price="2500", sell_price="2550", spread_bps=200, gas_cost_bps=10,
            net_pnl_bps=190, gas_price_gwei=0.02,
            executable=False, buy_verified=True, sell_verified=False,
        )
        session.record_trade(trade3)
        
        # Check pending at block 102 (2 blocks later)
        pending = session.get_pending_revalidation(current_block=102, min_blocks=1)
        
        # Only trade1 should be pending (WOULD_EXECUTE, not revalidated)
        assert len(pending) == 1
        assert pending[0].spread_id == "spread_1"
    
    def test_mark_revalidated_updates_trade(self, tmp_path):
        """mark_revalidated updates trade in file."""
        from strategy.paper_trading import PaperSession, PaperTrade, TradeOutcome
        
        session = PaperSession(tmp_path, cooldown_blocks=5)
        
        trade = PaperTrade(
            spread_id="spread_1", block_number=100, timestamp="2026-01-12T10:00:00Z",
            chain_id=42161, buy_dex="uni", sell_dex="sushi", token_in="WETH",
            token_out="USDC", fee=3000, amount_in_wei="1000000000000000000",
            buy_price="2500", sell_price="2550", spread_bps=200, gas_cost_bps=10,
            net_pnl_bps=190, gas_price_gwei=0.02,
            outcome=TradeOutcome.WOULD_EXECUTE.value, revalidated=False,
        )
        session.record_trade(trade)
        
        # Mark as revalidated
        success = session.mark_revalidated(
            spread_id="spread_1",
            original_block=100,
            revalidation_block=105,
            would_still_execute=True,
            new_net_pnl_bps=180,
        )
        
        assert success
        
        # Reload and check
        trades = session.load_trades()
        assert len(trades) == 1
        assert trades[0].revalidated is True
        assert trades[0].revalidation_block == 105
        assert trades[0].would_still_execute is True
    
    def test_mark_revalidated_updates_stats_on_failure(self, tmp_path):
        """When revalidation fails, stats are updated."""
        from strategy.paper_trading import PaperSession, PaperTrade, TradeOutcome
        
        session = PaperSession(tmp_path, cooldown_blocks=5)
        
        trade = PaperTrade(
            spread_id="spread_1", block_number=100, timestamp="2026-01-12T10:00:00Z",
            chain_id=42161, buy_dex="uni", sell_dex="sushi", token_in="WETH",
            token_out="USDC", fee=3000, amount_in_wei="1000000000000000000",
            buy_price="2500", sell_price="2550", spread_bps=200, gas_cost_bps=10,
            net_pnl_bps=190, gas_price_gwei=0.02,
            outcome=TradeOutcome.WOULD_EXECUTE.value, revalidated=False,
        )
        session.record_trade(trade)
        
        # Stats should show 1 would_execute
        assert session.stats["would_execute"] == 1
        
        # Mark as failed revalidation
        session.mark_revalidated(
            spread_id="spread_1",
            original_block=100,
            revalidation_block=105,
            would_still_execute=False,  # Trade no longer works
            new_net_pnl_bps=-10,
        )
        
        # Stats should be updated
        assert session.stats["would_execute"] == 0
        
        # Trade outcome should change
        trades = session.load_trades()
        assert trades[0].outcome == TradeOutcome.GATES_CHANGED.value
