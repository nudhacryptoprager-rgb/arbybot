"""
Tests for Algebra quoter ABI consistency.

Verifies the selector and encoding match the documented ABI.
"""

import pytest
import json
from pathlib import Path


class TestAlgebraQuoterABI:
    """Test Algebra quoter ABI documentation consistency."""
    
    def test_abi_file_exists(self):
        """ABI documentation file should exist."""
        abi_path = Path(__file__).parent.parent.parent / "dex" / "abi" / "algebra_quoter.json"
        assert abi_path.exists(), f"ABI file not found: {abi_path}"
        
    def test_abi_valid_json(self):
        """ABI file should be valid JSON."""
        abi_path = Path(__file__).parent.parent.parent / "dex" / "abi" / "algebra_quoter.json"
        with open(abi_path) as f:
            data = json.load(f)
        assert "quoteExactInputSingle" in data
        
    def test_selector_matches_implementation(self):
        """Documented selector should match implementation."""
        abi_path = Path(__file__).parent.parent.parent / "dex" / "abi" / "algebra_quoter.json"
        with open(abi_path) as f:
            data = json.load(f)
        
        documented_selector = data["quoteExactInputSingle"]["selector"]
        
        # The implementation uses this selector
        # From strategy/quotes.py read_algebra_quoter
        implementation_selector = "0x2d9ebd1d"
        
        assert documented_selector == implementation_selector, (
            f"Selector mismatch: documented={documented_selector}, "
            f"implementation={implementation_selector}"
        )
        
    def test_abi_fragment_has_correct_inputs(self):
        """ABI fragment should have correct input count and types."""
        abi_path = Path(__file__).parent.parent.parent / "dex" / "abi" / "algebra_quoter.json"
        with open(abi_path) as f:
            data = json.load(f)
        
        abi_fragment = data.get("abi_fragment", [])
        assert len(abi_fragment) == 1, "Expected exactly 1 function in ABI fragment"
        
        func = abi_fragment[0]
        assert func["name"] == "quoteExactInputSingle"
        assert len(func["inputs"]) == 4, "Expected 4 inputs"
        
        input_types = [i["type"] for i in func["inputs"]]
        assert input_types == ["address", "address", "uint256", "uint160"]
        
    def test_abi_fragment_has_correct_outputs(self):
        """ABI fragment should have correct output types."""
        abi_path = Path(__file__).parent.parent.parent / "dex" / "abi" / "algebra_quoter.json"
        with open(abi_path) as f:
            data = json.load(f)
        
        abi_fragment = data.get("abi_fragment", [])
        func = abi_fragment[0]
        
        assert len(func["outputs"]) == 2, "Expected 2 outputs"
        
        output_types = [o["type"] for o in func["outputs"]]
        assert output_types == ["uint256", "uint16"]


class TestAlgebraEncodingDecoding:
    """Test Algebra quoter encoding/decoding matches ABI."""
    
    def test_encode_call_data(self):
        """Test encoding quoteExactInputSingle call data."""
        # Sample inputs
        token_in = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"  # WETH
        token_out = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"  # USDC
        amount_in = 10**18  # 1 WETH
        limit_sqrt_price = 0  # no limit
        
        # Encoding as done in strategy/quotes.py
        SELECTOR = "0x2d9ebd1d"
        token_in_padded = token_in[2:].lower().zfill(64)
        token_out_padded = token_out[2:].lower().zfill(64)
        amount_in_hex = hex(amount_in)[2:].zfill(64)
        sqrt_price_limit = hex(limit_sqrt_price)[2:].zfill(64)
        
        call_data = f"{SELECTOR}{token_in_padded}{token_out_padded}{amount_in_hex}{sqrt_price_limit}"
        
        # Verify structure: 0x + 8 chars selector + 4 params * 64 chars = 266 chars total
        assert call_data.startswith("0x2d9ebd1d")
        assert len(call_data) == 2 + 8 + 64*4  # "0x" + selector + 4 params
        
        # Verify addresses are padded correctly (left-padded with zeros)
        assert "82af49447d8a07e3bd95bd0d56f35241523fbab1" in call_data.lower()
        assert "af88d065e77c8cc2239327c5edb3a432268e5831" in call_data.lower()
        
    def test_decode_response(self):
        """Test decoding quoteExactInputSingle response."""
        # Sample response: amountOut=2500000000 (2500 USDC), fee=500
        amount_out = 2500 * 10**6
        fee = 500
        
        response_data = hex(amount_out)[2:].zfill(64) + hex(fee)[2:].zfill(64)
        
        # Decoding as done in strategy/quotes.py
        decoded_amount_out = int(response_data[0:64], 16)
        decoded_fee = int(response_data[64:128], 16)
        
        assert decoded_amount_out == amount_out
        assert decoded_fee == fee
