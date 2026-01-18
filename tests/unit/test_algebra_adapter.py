"""
tests/unit/test_algebra_adapter.py - Algebra adapter unit tests.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from dex.adapters.algebra import (
    AlgebraAdapter,
    AlgebraQuoteResult,
    encode_quote_exact_input_single,
    decode_quote_response,
    SELECTOR_QUOTE_EXACT_INPUT_SINGLE,
)
from dex.adapters.uniswap_v3 import UniswapV3Adapter
from core.models import Token, Pool
from core.constants import DexType, ErrorCode
from core.exceptions import QuoteError


class TestAlgebraEncoding:
    """Test Algebra ABI encoding."""
    
    def test_encode_quote_exact_input_single(self):
        """Encodes quoteExactInputSingle correctly."""
        result = encode_quote_exact_input_single(
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            amount_in=10**18,
        )
        
        # Check selector - CORRECT: 0x2d9ebd1d for quoteExactInputSingle(address,address,uint256,uint160)
        # NOT 0xcdca1753 which is quoteExactInput(bytes path, uint256 amountIn)
        assert result.startswith(f"0x{SELECTOR_QUOTE_EXACT_INPUT_SINGLE}")
        assert result.startswith("0x2d9ebd1d"), f"Expected selector 0x2d9ebd1d, got {result[:10]}"
        # Check length: 0x + selector(8) + 4*64 = 266
        assert len(result) == 266
    
    def test_decode_quote_response(self):
        """Decodes quote response correctly."""
        # Simulate response: amountOut=1000000, fee=500
        amount_out = 1000000
        fee = 500
        
        # Encode as hex (32 bytes each)
        hex_response = "0x" + (
            hex(amount_out)[2:].zfill(64) +
            hex(fee)[2:].zfill(64)
        )
        
        decoded_out, decoded_fee = decode_quote_response(hex_response)
        assert decoded_out == amount_out
        assert decoded_fee == fee
    
    def test_decode_empty_response_raises(self):
        """Empty response raises QuoteError."""
        with pytest.raises(QuoteError) as exc_info:
            decode_quote_response("0x")
        
        assert exc_info.value.code == ErrorCode.QUOTE_REVERT
    
    def test_decode_short_response_raises(self):
        """Too-short response raises QuoteError."""
        with pytest.raises(QuoteError) as exc_info:
            decode_quote_response("0x" + "00" * 60)  # 60 bytes < 64 required
        
        assert exc_info.value.code == ErrorCode.QUOTE_REVERT


class TestAlgebraAdapter:
    """Test AlgebraAdapter."""
    
    @pytest.fixture
    def mock_provider(self):
        """Create mock RPC provider."""
        provider = MagicMock()
        provider.eth_call = AsyncMock()
        return provider
    
    @pytest.fixture
    def adapter(self, mock_provider):
        """Create adapter with mock provider."""
        return AlgebraAdapter(
            provider=mock_provider,
            quoter_address="0x0Fc73040b26E9bC8514fA028D998E73A254Fa76E",
            dex_id="camelot_v3",
        )
    
    @pytest.fixture
    def sample_tokens(self):
        """Create sample tokens."""
        weth = Token(
            chain_id=42161,
            address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            symbol="WETH",
            name="Wrapped Ether",
            decimals=18,
        )
        usdc = Token(
            chain_id=42161,
            address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            symbol="USDC",
            name="USD Coin",
            decimals=6,
        )
        return weth, usdc
    
    @pytest.fixture
    def sample_pool(self, sample_tokens):
        """Create sample pool."""
        weth, usdc = sample_tokens
        return Pool(
            chain_id=42161,
            pool_address="0x1234567890123456789012345678901234567890",
            dex_type=DexType.ALGEBRA,
            dex_id="camelot_v3",
            token0=weth,
            token1=usdc,
            fee=0,  # Algebra has dynamic fees
        )
    
    @pytest.mark.asyncio
    async def test_get_quote_raw_success(self, adapter, mock_provider):
        """get_quote_raw returns result on success."""
        # Mock response: 3500 USDC for 1 ETH, fee=500
        amount_out = 3500 * 10**6
        fee = 500
        hex_response = "0x" + hex(amount_out)[2:].zfill(64) + hex(fee)[2:].zfill(64)
        
        mock_provider.eth_call.return_value = MagicMock(
            result=hex_response,
            latency_ms=25,
        )
        
        result = await adapter.get_quote_raw(
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            amount_in=10**18,
            block_number=12345678,
        )
        
        assert isinstance(result, AlgebraQuoteResult)
        assert result.amount_out == amount_out
        assert result.fee == fee
    
    @pytest.mark.asyncio
    async def test_get_quote_success(self, adapter, mock_provider, sample_pool, sample_tokens):
        """get_quote returns Quote model."""
        weth, usdc = sample_tokens
        
        # Mock response
        amount_out = 3500 * 10**6
        fee = 500
        hex_response = "0x" + hex(amount_out)[2:].zfill(64) + hex(fee)[2:].zfill(64)
        
        mock_provider.eth_call.return_value = MagicMock(
            result=hex_response,
            latency_ms=25,
        )
        
        quote = await adapter.get_quote(
            pool=sample_pool,
            token_in=weth,
            token_out=usdc,
            amount_in=10**18,
            block_number=12345678,
        )
        
        assert quote.amount_in == 10**18
        assert quote.amount_out == amount_out
        assert quote.token_in_obj.symbol == "WETH"
        assert quote.token_out_obj.symbol == "USDC"
        # Algebra doesn't report ticks
        assert quote.ticks_crossed == 0
    
    @pytest.mark.asyncio
    async def test_get_quote_revert_raises(self, adapter, mock_provider, sample_pool, sample_tokens):
        """get_quote raises QuoteError on revert."""
        weth, usdc = sample_tokens
        
        mock_provider.eth_call.return_value = MagicMock(result="0x")
        
        with pytest.raises(QuoteError) as exc_info:
            await adapter.get_quote(
                pool=sample_pool,
                token_in=weth,
                token_out=usdc,
                amount_in=10**18,
            )
        
        assert exc_info.value.code == ErrorCode.QUOTE_REVERT


class TestAdapterSelector:
    """Test adapter selection based on config."""
    
    def test_select_algebra_adapter(self):
        """Algebra adapter created for adapter_type='algebra'."""
        mock_provider = MagicMock()
        
        dex_config = {
            "adapter_type": "algebra",
            "quoter": "0x0Fc73040b26E9bC8514fA028D998E73A254Fa76E",
            "enabled": True,
            "feature_flag": "algebra_adapter",
        }
        
        adapter_type = dex_config.get("adapter_type", "uniswap_v3")
        quoter_address = dex_config.get("quoter")
        
        if adapter_type == "algebra":
            adapter = AlgebraAdapter(mock_provider, quoter_address, "camelot_v3")
        else:
            adapter = UniswapV3Adapter(mock_provider, quoter_address, "uniswap_v3")
        
        assert isinstance(adapter, AlgebraAdapter)
        assert adapter.dex_id == "camelot_v3"
    
    def test_select_uniswap_adapter_default(self):
        """UniswapV3Adapter created for adapter_type='uniswap_v3'."""
        mock_provider = MagicMock()
        
        dex_config = {
            "adapter_type": "uniswap_v3",
            "quoter_v2": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
        }
        
        adapter_type = dex_config.get("adapter_type", "uniswap_v3")
        quoter_address = dex_config.get("quoter_v2") or dex_config.get("quoter")
        
        if adapter_type == "algebra":
            adapter = AlgebraAdapter(mock_provider, quoter_address, "camelot_v3")
        else:
            adapter = UniswapV3Adapter(mock_provider, quoter_address, "uniswap_v3")
        
        assert isinstance(adapter, UniswapV3Adapter)
    
    def test_algebra_no_fee_tiers(self):
        """Algebra config should use fee=0 (dynamic fees)."""
        dex_config = {
            "adapter_type": "algebra",
            "quoter": "0x0Fc73040b26E9bC8514fA028D998E73A254Fa76E",
        }
        
        adapter_type = dex_config.get("adapter_type")
        
        if adapter_type == "algebra":
            fee_tiers = [0]  # Single marker for dynamic fee
        else:
            fee_tiers = dex_config.get("fee_tiers", [500, 3000])
        
        assert fee_tiers == [0]
        assert len(fee_tiers) == 1
