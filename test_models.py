"""
tests/unit/test_models.py - Tests for core/models.py

Tests for data models: Token, Pool, Quote, Opportunity, PnL.
"""

import pytest
from datetime import datetime
from decimal import Decimal

from core.models import (
    Token,
    Pool,
    Quote,
    QuoteCurve,
    PnLBreakdown,
    Opportunity,
    Trade,
    RejectReason,
    ChainInfo,
)
from core.constants import (
    DexType,
    TokenStatus,
    PoolStatus,
    TradeDirection,
    TradeStatus,
    OpportunityStatus,
)
from core.exceptions import ErrorCode
from core.time import now_ms


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def weth_token():
    """WETH token on Arbitrum."""
    return Token(
        chain_id=42161,
        address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        symbol="WETH",
        name="Wrapped Ether",
        decimals=18,
        is_core=True,
    )


@pytest.fixture
def usdc_token():
    """USDC token on Arbitrum."""
    return Token(
        chain_id=42161,
        address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        symbol="USDC",
        name="USD Coin",
        decimals=6,
        is_core=True,
    )


@pytest.fixture
def v3_pool(weth_token, usdc_token):
    """Uniswap V3 WETH/USDC pool."""
    return Pool(
        chain_id=42161,
        dex_id="uniswap_v3_arbitrum",
        dex_type=DexType.UNISWAP_V3,
        pool_address="0xC6962004f452bE9203591991D15f6b388e09E8D0",
        token0=usdc_token,  # USDC is token0 (sorted)
        token1=weth_token,
        fee=500,  # 0.05%
        status=PoolStatus.ACTIVE,
    )


# =============================================================================
# TOKEN TESTS
# =============================================================================

class TestToken:
    """Test Token model."""
    
    def test_token_creation(self, weth_token):
        """Create token with all fields."""
        assert weth_token.chain_id == 42161
        assert weth_token.symbol == "WETH"
        assert weth_token.decimals == 18
        assert weth_token.is_core is True
    
    def test_token_hash(self, weth_token):
        """Tokens hash by chain_id and address."""
        same_token = Token(
            chain_id=42161,
            address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            symbol="WETH",
            name="Wrapped Ether",
            decimals=18,
        )
        assert hash(weth_token) == hash(same_token)
    
    def test_token_equality(self, weth_token):
        """Tokens equal by chain_id and address (case-insensitive)."""
        same_token = Token(
            chain_id=42161,
            address="0x82af49447d8a07e3bd95bd0d56f35241523fbab1",  # lowercase
            symbol="WETH",
            name="Different Name",
            decimals=18,
        )
        assert weth_token == same_token
    
    def test_token_inequality(self, weth_token, usdc_token):
        """Different tokens are not equal."""
        assert weth_token != usdc_token
    
    def test_token_default_status(self):
        """Token has default status."""
        token = Token(
            chain_id=1,
            address="0x123",
            symbol="TEST",
            name="Test",
            decimals=18,
        )
        assert token.status == TokenStatus.VERIFIED


# =============================================================================
# POOL TESTS
# =============================================================================

class TestPool:
    """Test Pool model."""
    
    def test_pool_creation(self, v3_pool):
        """Create pool with all fields."""
        assert v3_pool.chain_id == 42161
        assert v3_pool.dex_type == DexType.UNISWAP_V3
        assert v3_pool.fee == 500
        assert v3_pool.status == PoolStatus.ACTIVE
    
    def test_pool_hash(self, v3_pool):
        """Pools hash by chain_id and address."""
        h = hash(v3_pool)
        assert isinstance(h, int)
    
    def test_pool_pair_key(self, v3_pool):
        """Pool has canonical pair key (sorted)."""
        # USDC/WETH sorted alphabetically
        assert v3_pool.pair_key == "USDC/WETH"


# =============================================================================
# QUOTE TESTS
# =============================================================================

class TestQuote:
    """Test Quote model."""
    
    def test_quote_creation(self, v3_pool, weth_token, usdc_token):
        """Create quote with all fields."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=1_000_000_000_000_000_000,  # 1 ETH
            amount_out=2500_000_000,  # 2500 USDC
            block_number=12345678,
            timestamp_ms=now_ms(),
            gas_estimate=150000,
            ticks_crossed=2,
        )
        assert quote.amount_in == 1_000_000_000_000_000_000
        assert quote.amount_out == 2500_000_000
        assert quote.direction == TradeDirection.SELL
    
    def test_quote_is_fresh(self, v3_pool, weth_token, usdc_token):
        """Fresh quote is detected."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=1000,
            amount_out=100,
            block_number=100,
            timestamp_ms=now_ms(),
            gas_estimate=100000,
        )
        assert quote.is_fresh is True
    
    def test_quote_is_stale(self, v3_pool, weth_token, usdc_token):
        """Stale quote is detected."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=1000,
            amount_out=100,
            block_number=100,
            timestamp_ms=now_ms() - 5000,  # 5 seconds ago
            gas_estimate=100000,
        )
        assert quote.is_fresh is False
    
    def test_quote_effective_price_sell(self, v3_pool, weth_token, usdc_token):
        """Effective price for SELL direction."""
        # SELL: WETH -> USDC
        # 1 WETH (18 dec) -> 2500 USDC (6 dec)
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,  # WETH (18 dec)
            token_out=usdc_token,  # USDC (6 dec)
            amount_in=1_000_000_000_000_000_000,  # 1 WETH
            amount_out=2500_000_000,  # 2500 USDC
            block_number=100,
            timestamp_ms=now_ms(),
            gas_estimate=100000,
        )
        # Price = 2500 USDC / 1 WETH = 2500
        price = quote.effective_price
        assert price == Decimal("2500")
    
    def test_quote_zero_input(self, v3_pool, weth_token, usdc_token):
        """Zero input returns zero price."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=0,
            amount_out=100,
            block_number=100,
            timestamp_ms=now_ms(),
            gas_estimate=100000,
        )
        assert quote.effective_price == Decimal("0")


# =============================================================================
# PNL TESTS
# =============================================================================

class TestPnLBreakdown:
    """Test PnLBreakdown model."""
    
    def test_pnl_breakdown_creation(self):
        """Create PnL breakdown."""
        pnl = PnLBreakdown(
            gross_revenue=Decimal("110.00"),
            gross_cost=Decimal("100.00"),
            gas_cost=Decimal("0.50"),
            dex_fee=Decimal("0.30"),
            slippage_cost=Decimal("0.20"),
            net_pnl=Decimal("9.00"),
            settlement_currency="USDC",
        )
        assert pnl.net_pnl == Decimal("9.00")
        assert pnl.settlement_currency == "USDC"
    
    def test_pnl_net_bps(self):
        """Calculate net PnL in basis points."""
        pnl = PnLBreakdown(
            gross_revenue=Decimal("110.00"),
            gross_cost=Decimal("100.00"),
            gas_cost=Decimal("0.50"),
            dex_fee=Decimal("0.30"),
            slippage_cost=Decimal("0.20"),
            net_pnl=Decimal("9.00"),
            settlement_currency="USDC",
        )
        # 9 / 100 * 10000 = 900 bps = 9%
        assert pnl.net_bps == Decimal("900")
    
    def test_pnl_zero_cost(self):
        """Zero cost returns zero bps."""
        pnl = PnLBreakdown(
            gross_revenue=Decimal("100"),
            gross_cost=Decimal("0"),
            gas_cost=Decimal("0"),
            dex_fee=Decimal("0"),
            slippage_cost=Decimal("0"),
            net_pnl=Decimal("100"),
            settlement_currency="USDC",
        )
        assert pnl.net_bps == Decimal("0")
    
    def test_pnl_to_dict(self):
        """PnL serializes to dict."""
        pnl = PnLBreakdown(
            gross_revenue=Decimal("110"),
            gross_cost=Decimal("100"),
            gas_cost=Decimal("0.5"),
            dex_fee=Decimal("0.3"),
            slippage_cost=Decimal("0.2"),
            net_pnl=Decimal("9"),
            settlement_currency="USDC",
        )
        d = pnl.to_dict()
        assert d["net_pnl"] == "9"
        assert d["settlement_currency"] == "USDC"


# =============================================================================
# REJECT REASON TESTS
# =============================================================================

class TestRejectReason:
    """Test RejectReason model."""
    
    def test_reject_reason_creation(self):
        """Create reject reason."""
        reason = RejectReason(
            code=ErrorCode.SLIPPAGE_TOO_HIGH,
            message="Slippage exceeds threshold",
            details={"slippage_bps": 150, "max_bps": 50},
        )
        assert reason.code == ErrorCode.SLIPPAGE_TOO_HIGH
        assert reason.details["slippage_bps"] == 150
    
    def test_reject_reason_to_dict(self):
        """RejectReason serializes."""
        reason = RejectReason(
            code=ErrorCode.POOL_NO_LIQUIDITY,
            message="No liquidity",
        )
        d = reason.to_dict()
        assert d["code"] == "POOL_NO_LIQUIDITY"


# =============================================================================
# OPPORTUNITY TESTS
# =============================================================================

class TestOpportunity:
    """Test Opportunity model."""
    
    def test_opportunity_creation(self, v3_pool, weth_token, usdc_token):
        """Create opportunity."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=1000,
            amount_out=100,
            block_number=100,
            timestamp_ms=now_ms(),
            gas_estimate=100000,
        )
        opp = Opportunity(
            id="test-123",
            created_at=datetime.now(),
            leg_buy=quote,
            leg_sell=quote,
        )
        assert opp.id == "test-123"
        assert opp.status == OpportunityStatus.VALID
    
    def test_opportunity_is_executable_no_pnl(self, v3_pool, weth_token, usdc_token):
        """Opportunity without PnL is not executable."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=1000,
            amount_out=100,
            block_number=100,
            timestamp_ms=now_ms(),
            gas_estimate=100000,
        )
        opp = Opportunity(
            id="test",
            created_at=datetime.now(),
            leg_buy=quote,
            leg_sell=quote,
            pnl=None,
        )
        assert opp.is_executable is False
    
    def test_opportunity_is_executable_positive_pnl(self, v3_pool, weth_token, usdc_token):
        """Opportunity with positive PnL is executable."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=1000,
            amount_out=100,
            block_number=100,
            timestamp_ms=now_ms(),
            gas_estimate=100000,
        )
        pnl = PnLBreakdown(
            gross_revenue=Decimal("110"),
            gross_cost=Decimal("100"),
            gas_cost=Decimal("0.5"),
            dex_fee=Decimal("0.3"),
            slippage_cost=Decimal("0.2"),
            net_pnl=Decimal("9"),
            settlement_currency="USDC",
        )
        opp = Opportunity(
            id="test",
            created_at=datetime.now(),
            leg_buy=quote,
            leg_sell=quote,
            pnl=pnl,
        )
        assert opp.is_executable is True
    
    def test_opportunity_is_executable_rejected(self, v3_pool, weth_token, usdc_token):
        """Rejected opportunity is not executable."""
        quote = Quote(
            pool=v3_pool,
            direction=TradeDirection.SELL,
            token_in=weth_token,
            token_out=usdc_token,
            amount_in=1000,
            amount_out=100,
            block_number=100,
            timestamp_ms=now_ms(),
            gas_estimate=100000,
        )
        opp = Opportunity(
            id="test",
            created_at=datetime.now(),
            leg_buy=quote,
            leg_sell=quote,
            status=OpportunityStatus.REJECTED,
            reject_reason=RejectReason(
                code=ErrorCode.SLIPPAGE_TOO_HIGH,
                message="Too much slippage",
            ),
        )
        assert opp.is_executable is False


# =============================================================================
# TRADE TESTS
# =============================================================================

class TestTrade:
    """Test Trade model."""
    
    def test_trade_creation(self):
        """Create trade."""
        trade = Trade(
            id="trade-123",
            opportunity_id="opp-456",
            created_at=datetime.now(),
        )
        assert trade.id == "trade-123"
        assert trade.status == TradeStatus.PENDING
    
    def test_trade_to_dict(self):
        """Trade serializes."""
        trade = Trade(
            id="trade-123",
            opportunity_id="opp-456",
            created_at=datetime.now(),
            status=TradeStatus.CONFIRMED,
            tx_hash="0xabc",
            gas_used=150000,
        )
        d = trade.to_dict()
        assert d["id"] == "trade-123"
        assert d["status"] == "confirmed"
        assert d["tx_hash"] == "0xabc"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
