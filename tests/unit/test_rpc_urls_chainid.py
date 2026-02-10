from urllib.parse import urlparse
from core.rpc_urls import resolve_rpc_http, validate_chain_rpc_consistency


def test_resolve_rpc_http_arbitrum_by_chain_id():
    env = {"ALCHEMY_API_KEY": "testkey"}
    url, provider, diag = resolve_rpc_http(chain_id=42161, network=None, env=env)
    assert url is not None, "Expected a URL for chain_id 42161 with API key"
    netloc = urlparse(url).netloc.lower()
    assert "arb-mainnet" in netloc or "arbitrum" in netloc, f"Unexpected host for Arbitrum: {netloc}"
    assert provider == "alchemy"


class TestChainRpcConsistency:
    """v1.12.2: Validate chain_id / RPC host consistency."""
    
    def test_arbitrum_chain_with_arbitrum_host_valid(self):
        """Arbitrum chain_id with Arbitrum-pattern host is valid."""
        is_valid, error = validate_chain_rpc_consistency(42161, "arb-mainnet.g.alchemy.com")
        assert is_valid is True
        assert error is None
    
    def test_arbitrum_chain_with_mantle_host_invalid(self):
        """Arbitrum chain_id with Mantle-pattern host is INVALID."""
        is_valid, error = validate_chain_rpc_consistency(42161, "mantle-mainnet.g.alchemy.com")
        assert is_valid is False
        assert "chain_id=42161" in error
        assert "mantle" in error.lower()
    
    def test_mantle_chain_with_mantle_host_valid(self):
        """Mantle chain_id with Mantle-pattern host is valid."""
        is_valid, error = validate_chain_rpc_consistency(5000, "mantle-mainnet.g.alchemy.com")
        assert is_valid is True
        assert error is None
    
    def test_mantle_chain_with_arbitrum_host_invalid(self):
        """Mantle chain_id with Arbitrum-pattern host is INVALID."""
        is_valid, error = validate_chain_rpc_consistency(5000, "arb-mainnet.g.alchemy.com")
        assert is_valid is False
        assert "chain_id=5000" in error
        assert "arbitrum" in error.lower()
    
    def test_unknown_chain_allows_any_host(self):
        """Unknown chain_id should pass validation (can't verify)."""
        is_valid, error = validate_chain_rpc_consistency(99999, "some-unknown-rpc.com")
        assert is_valid is True
        assert error is None
    
    def test_base_chain_with_base_host_valid(self):
        """Base chain_id with Base-pattern host is valid."""
        is_valid, error = validate_chain_rpc_consistency(8453, "base-mainnet.g.alchemy.com")
        assert is_valid is True
        assert error is None
    
    def test_base_chain_with_linea_host_invalid(self):
        """Base chain_id with Linea-pattern host is INVALID."""
        is_valid, error = validate_chain_rpc_consistency(8453, "linea-mainnet.g.alchemy.com")
        assert is_valid is False
        assert "chain_id=8453" in error
