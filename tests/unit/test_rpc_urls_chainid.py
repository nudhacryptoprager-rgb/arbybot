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


class TestRollingSHAProvenance:
    """v1.12.3: Test rolling_store provenance logic."""
    
    def test_compute_quick_stats_no_args_uses_git_fallback(self):
        """_compute_quick_stats with no run_summary/target_sha falls back to git."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats({"runs": []})
        
        # Should not crash (was NameError before fix)
        assert "runs_since_sha" in result
        assert "sha" in result["runs_since_sha"]
    
    def test_compute_quick_stats_with_target_sha(self):
        """_compute_quick_stats with explicit target_sha uses it."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "abc123", "run_kind": "NORMAL", "signals_count": 5}]},
            target_sha="abc123"
        )
        
        assert result["runs_since_sha"]["sha"] == "abc123"
        assert result["runs_since_sha"]["runs_count"] == 1
    
    def test_compute_quick_stats_with_run_summary_context(self):
        """_compute_quick_stats extracts SHA from run_summary.run_context."""
        from m4.rolling_store import _compute_quick_stats
        
        run_summary = {"run_context": {"code_sha": "def456"}}
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "def456", "run_kind": "NORMAL", "signals_count": 5}]},
            run_summary=run_summary
        )
        
        assert result["runs_since_sha"]["sha"] == "def456"
        assert result["runs_since_sha"]["runs_count"] == 1
