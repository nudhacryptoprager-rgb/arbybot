from urllib.parse import urlparse
from core.rpc_urls import resolve_rpc_http


def test_resolve_rpc_http_arbitrum_by_chain_id():
    env = {"ALCHEMY_API_KEY": "testkey"}
    url, provider, diag = resolve_rpc_http(chain_id=42161, network=None, env=env)
    assert url is not None, "Expected a URL for chain_id 42161 with API key"
    netloc = urlparse(url).netloc.lower()
    assert "arb-mainnet" in netloc or "arbitrum" in netloc, f"Unexpected host for Arbitrum: {netloc}"
    assert provider == "alchemy"
