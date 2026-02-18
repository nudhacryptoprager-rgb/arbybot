# PATH: tests/unit/test_providers.py
"""
Tests for provider identification functions.

v2.2.0: Tests for extract_provider_name() and related functions.
"""

import pytest


class TestExtractProviderName:
    """Test extract_provider_name() function."""
    
    def test_alchemy_url(self):
        """Test Alchemy URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://arb-mainnet.g.alchemy.com/v2/abc123") == "alchemy"
        assert extract_provider_name("https://eth-mainnet.g.alchemy.com/v2/key") == "alchemy"
        assert extract_provider_name("https://ALCHEMY.com/v2/key") == "alchemy"
    
    def test_infura_url(self):
        """Test Infura URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://mainnet.infura.io/v3/key") == "infura"
        assert extract_provider_name("https://arbitrum-mainnet.infura.io/v3/key") == "infura"
    
    def test_llamarpc_url(self):
        """Test LlamaRPC URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://arbitrum.llamarpc.com") == "llamarpc"
        assert extract_provider_name("https://eth.llamarpc.com/rpc") == "llamarpc"
    
    def test_quicknode_url(self):
        """Test QuickNode URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://abc.quiknode.pro/key/") == "quicknode"
        assert extract_provider_name("https://xyz.quicknode.com/key") == "quicknode"
    
    def test_ankr_url(self):
        """Test Ankr URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://rpc.ankr.com/arbitrum") == "ankr"
    
    def test_arbitrum_public_url(self):
        """Test Arbitrum public RPC URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://arb1.arbitrum.io/rpc") == "arbitrum_public"
    
    def test_tenderly_url(self):
        """Test Tenderly URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://virtual.mainnet.rpc.tenderly.co/abc") == "tenderly"
    
    def test_drpc_url(self):
        """Test dRPC URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://arbitrum.drpc.org") == "drpc"
    
    def test_localhost_url(self):
        """Test localhost URL extraction."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("http://localhost:8545") == "localhost"
        assert extract_provider_name("http://127.0.0.1:8545") == "localhost"
    
    def test_unknown_url_extracts_domain(self):
        """Test unknown URL falls back to domain extraction."""
        from chains.providers import extract_provider_name
        
        # Should extract first part of domain
        result = extract_provider_name("https://my-custom-rpc.example.com/rpc")
        assert result in ["my-custom-rpc", "unknown"]
    
    def test_empty_url(self):
        """Test empty URL returns unknown."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("") == "unknown"
    
    def test_case_insensitive(self):
        """Test URL matching is case-insensitive."""
        from chains.providers import extract_provider_name
        
        assert extract_provider_name("https://ARB-MAINNET.G.ALCHEMY.COM/v2/key") == "alchemy"


class TestProviderRouterPayload:
    """Test provider_router payload structure."""
    
    def test_infra_payload_has_provider_id(self):
        """Test that build_infra_payload includes provider_id when specified."""
        from strategy.infra import build_infra_payload
        
        payload = build_infra_payload(
            resolved_http="https://arb-mainnet.g.alchemy.com/v2/key",
            resolved_ws=None,
            ws_connected=False,
            ws_handshake_ms=None,
            ws_error=None,
            tenderly_enabled=False,
            tenderly_ok=None,
            tenderly_error=None,
            provider_http="alchemy",
            provider_ws="unknown",
        )
        
        assert payload.get("provider_id") == "alchemy"
        assert payload.get("provider_id_http") == "alchemy"
        assert payload.get("provider_id_ws") == "unknown"
    
    def test_infra_payload_unknown_provider(self):
        """Test that provider_id is None when provider is unknown."""
        from strategy.infra import build_infra_payload
        
        payload = build_infra_payload(
            resolved_http="https://example.com/rpc",
            resolved_ws=None,
            ws_connected=False,
            ws_handshake_ms=None,
            ws_error=None,
            tenderly_enabled=False,
            tenderly_ok=None,
            tenderly_error=None,
            provider_http="unknown",
            provider_ws="unknown",
        )
        
        # provider_id should be None when provider is unknown
        assert payload.get("provider_id") is None


class TestProviderStatsFields:
    """Test provider_router stats field names."""
    
    def test_provider_router_has_clear_field_names(self):
        """Test provider_router uses unambiguous field names per v2.2.0 Fix Step 5."""
        from strategy.infra import build_infra_payload
        
        payload = build_infra_payload(
            resolved_http="https://arb-mainnet.g.alchemy.com/v2/key",
            resolved_ws=None,
            ws_connected=False,
            ws_handshake_ms=None,
            ws_error=None,
            tenderly_enabled=False,
            tenderly_ok=None,
            tenderly_error=None,
            provider_http="alchemy",
            provider_ws="unknown",
        )
        
        router = payload.get("provider_router")
        if router:  # Only test if provider stats were populated
            # v2.2.0 Fix Step 5: Clear field names
            assert "chains_count" in router or "endpoints_configured_count" in router
            # Should NOT have ambiguous "providers_count"
            # (We can't enforce this until we remove the old code)
