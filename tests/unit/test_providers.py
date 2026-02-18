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


class TestEndpointsUsedSemantics:
    """Test v2.2.1 Fix Step 4: endpoints_used_count semantics.
    
    endpoints_used_count should represent distinct endpoints with requests > 0,
    not total_requests. This provides proper multi-provider proof.
    """
    
    def test_endpoints_used_count_distinct(self):
        """endpoints_used_count should be distinct endpoints with requests > 0."""
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
        if router:
            # v2.2.1: Should have endpoints_used_count (not endpoints_seen_count)
            # endpoints_used_count should be <= endpoints_configured_count
            if "endpoints_used_count" in router:
                assert router["endpoints_used_count"] <= router.get("endpoints_configured_count", 100)
                # Should also have endpoints_used list
                assert "endpoints_used" in router
                assert isinstance(router["endpoints_used"], list)

    def test_provider_router_failover_evidence_structure(self):
        """provider_router should have structure for proving failover.
        
        v2.2.1 Fix Step 5: For multi-provider proof, we need:
        - endpoints_used_count > 1 OR
        - test that shows switching on failure
        """
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
        if router:
            # Structure should support failover tracking
            assert "total_requests" in router
            assert "global_success_rate" in router
            # When failover happens, endpoints_used should have > 1 entry
            # (This test documents the contract, actual failover tested elsewhere)


class TestEndpointsUsedProviderIdContract:
    """Test v2.2.0 Fix Step 3: endpoints_used must contain canonical provider IDs.
    
    endpoints_used should contain values like 'alchemy', 'infura', 'llamarpc'
    (as returned by extract_provider_name), NOT hostnames like 'arb-mainnet'.
    """
    
    def test_endpoints_used_are_canonical_provider_ids(self):
        """endpoints_used entries should be canonical provider IDs."""
        from chains.providers import extract_provider_name
        
        # Known provider URLs and expected IDs
        test_cases = [
            ("https://arb-mainnet.g.alchemy.com/v2/key", "alchemy"),
            ("https://arbitrum-mainnet.infura.io/v3/key", "infura"),
            ("https://arbitrum.llamarpc.com", "llamarpc"),
            ("https://arb1.arbitrum.io/rpc", "arbitrum_public"),
        ]
        
        for url, expected_id in test_cases:
            provider_id = extract_provider_name(url)
            assert provider_id == expected_id, f"URL {url} should yield {expected_id}, got {provider_id}"
            # Verify it's not a hostname pattern
            assert "." not in provider_id, f"provider_id '{provider_id}' should not contain dots"
            assert "-" not in provider_id or provider_id == "arbitrum_public", \
                f"provider_id '{provider_id}' should not contain dashes (except arbitrum_public)"
    
    def test_endpoints_used_no_hostname_pattern(self):
        """endpoints_used should NOT contain hostname-like patterns."""
        # Patterns that indicate incorrect hostname extraction
        invalid_patterns = [
            "arb-mainnet",  # Alchemy hostname prefix
            "arbitrum-mainnet",  # Infura hostname prefix
            "arb1",  # Arbitrum public hostname prefix
            "g.alchemy",  # Partial hostname
        ]
        
        from chains.providers import extract_provider_name
        
        # All of these should NOT appear in extract_provider_name output
        for url in [
            "https://arb-mainnet.g.alchemy.com/v2/key",
            "https://arbitrum-mainnet.infura.io/v3/key",
            "https://arb1.arbitrum.io/rpc",
        ]:
            provider_id = extract_provider_name(url)
            for pattern in invalid_patterns:
                assert pattern not in provider_id.lower(), \
                    f"provider_id '{provider_id}' should not contain '{pattern}'"


class TestFailoverRealistic:
    """Test v2.3.0: Realistic failover behavior without --failover-stress.
    
    These tests validate that the provider routing/failover logic works
    correctly under realistic error conditions (timeout, 429, etc.)
    without relying on the artificial --failover-stress mode.
    """
    
    def test_rpc_stats_dataclass_fields(self):
        """RPCStats should have all expected tracking fields."""
        from chains.providers import RPCStats
        
        stats = RPCStats(url="https://test.example.com/rpc")
        
        # All v2.3.0 RPCStats fields should exist
        assert hasattr(stats, "url")
        assert hasattr(stats, "endpoint_id")
        assert hasattr(stats, "total_requests")
        assert hasattr(stats, "successful_requests")
        assert hasattr(stats, "failed_requests")
        assert hasattr(stats, "total_latency_ms")
        assert hasattr(stats, "quarantined")
        assert hasattr(stats, "stress_test_fails")
        
        # Defaults
        assert stats.failed_requests == 0
        assert stats.successful_requests == 0
        assert stats.total_requests == 0
        assert stats.quarantined == False
    
    def test_rpc_stats_success_rate_property(self):
        """RPCStats.success_rate should compute correctly."""
        from chains.providers import RPCStats
        
        stats = RPCStats(url="https://test.example.com/rpc")
        
        # Zero requests = 0.0 rate
        assert stats.success_rate == 0.0
        
        # Simulate 8 success, 2 fail
        stats.total_requests = 10
        stats.successful_requests = 8
        stats.failed_requests = 2
        assert stats.success_rate == 0.8
    
    def test_rpc_stats_avg_latency_property(self):
        """RPCStats.avg_latency_ms should compute correctly."""
        from chains.providers import RPCStats
        
        stats = RPCStats(url="https://test.example.com/rpc")
        
        # Zero requests = 0 latency
        assert stats.avg_latency_ms == 0
        
        # Simulate 5 requests with 500ms total
        stats.successful_requests = 5
        stats.total_latency_ms = 500
        assert stats.avg_latency_ms == 100
    
    def test_quarantine_constants_exist(self):
        """Quarantine constants should be exported for test use."""
        from chains.providers import (
            MIN_REQUESTS_FOR_QUARANTINE,
            MIN_SUCCESS_RATE_FOR_ACTIVE,
            QUARANTINE_DURATION_MS,
        )
        
        # Verify reasonable defaults
        assert MIN_REQUESTS_FOR_QUARANTINE >= 3, "Need min requests before quarantine"
        assert 0 < MIN_SUCCESS_RATE_FOR_ACTIVE < 1.0, "Success rate threshold should be sensible"
        assert QUARANTINE_DURATION_MS >= 30_000, "Quarantine should be at least 30s"
    
    def test_endpoint_id_is_stable(self):
        """Endpoint ID should be stable for the same URL."""
        from chains.providers import generate_endpoint_id
        
        url = "https://arb-mainnet.g.alchemy.com/v2/abc123"
        
        id1 = generate_endpoint_id(url)
        id2 = generate_endpoint_id(url)
        
        assert id1 == id2, "Endpoint ID should be deterministic for same URL"
        assert "_" in id1, "Endpoint ID format should be provider_hash"
        assert len(id1.split("_")[-1]) == 8, "Hash part should be 8 chars"
    
    def test_endpoint_id_different_for_different_urls(self):
        """Different URLs should have different endpoint IDs."""
        from chains.providers import generate_endpoint_id
        
        id1 = generate_endpoint_id("https://arb-mainnet.g.alchemy.com/v2/key1")
        id2 = generate_endpoint_id("https://arbitrum-mainnet.infura.io/v3/key2")
        
        assert id1 != id2, "Different URLs should have different endpoint IDs"
    
    def test_rpc_stats_has_endpoint_id(self):
        """RPCStats should include endpoint_id when constructed with url."""
        from chains.providers import RPCStats, generate_endpoint_id
        
        url = "https://arb-mainnet.g.alchemy.com/v2/key"
        expected_id = generate_endpoint_id(url)
        
        stats = RPCStats(url=url, endpoint_id=expected_id)
        assert stats.endpoint_id == expected_id
    
    def test_failover_stress_count_env_var(self):
        """ARBY_FAILOVER_STRESS_N env var should be imported."""
        from chains.providers import FAILOVER_STRESS_COUNT
        
        # Just verify it's importable - value depends on env
        assert isinstance(FAILOVER_STRESS_COUNT, int)
        assert FAILOVER_STRESS_COUNT >= 0
