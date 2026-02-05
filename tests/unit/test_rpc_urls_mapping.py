from core.rpc_urls import resolve_rpc_http


def test_resolve_arbitrum_alchemy_mapping():
    env = {"ALCHEMY_API_KEY": "testkey", "NETWORK": "arbitrum_one"}
    url, provider, diag = resolve_rpc_http(env=env)
    assert provider == "alchemy"
    assert "arb-mainnet.g.alchemy.com" in url
