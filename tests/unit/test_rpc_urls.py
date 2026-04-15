import unittest
from core.rpc_urls import (
    build_alchemy_http_url, build_alchemy_ws_url, public_fallback_for,
    classify_provider, validate_drpc_url, resolve_rpc_http, resolve_rpc_ws,
)


class TestRpcUrls(unittest.TestCase):
    def test_build_alchemy_http_arbitrum(self):
        url = build_alchemy_http_url('arbitrum', 'APIKEY')
        self.assertIn('alchemy.com', url)
        self.assertIn('APIKEY', url)

    def test_build_alchemy_ws_arbitrum(self):
        url = build_alchemy_ws_url('arbitrum', 'APIKEY')
        self.assertTrue(url.startswith('wss://'))
        self.assertIn('APIKEY', url)

    def test_alias_arbitrum_one(self):
        url = build_alchemy_http_url('arbitrum_one', 'K')
        self.assertIsNotNone(url)

    def test_public_fallback_exists(self):
        fb = public_fallback_for('arbitrum')
        self.assertIsNotNone(fb)


class TestClassifyProvider(unittest.TestCase):
    """classify_provider returns canonical provider types."""

    def test_alchemy(self):
        self.assertEqual(classify_provider("https://arb-mainnet.g.alchemy.com/v2/key"), "alchemy")

    def test_drpc_live(self):
        self.assertEqual(classify_provider("https://lb.drpc.live/base/keyabc"), "drpc")

    def test_drpc_org(self):
        self.assertEqual(classify_provider("https://base.drpc.org"), "drpc")

    def test_publicnode(self):
        self.assertEqual(classify_provider("wss://base-rpc.publicnode.com"), "publicnode")

    def test_flashblocks(self):
        self.assertEqual(classify_provider("wss://mainnet-preconf.base.org"), "flashblocks")

    def test_flashblocks_legacy(self):
        self.assertEqual(classify_provider("wss://base.flashblocks.base.org"), "flashblocks")

    def test_infura(self):
        self.assertEqual(classify_provider("https://mainnet.infura.io/v3/key"), "infura")

    def test_public_fallback_base(self):
        self.assertEqual(classify_provider("https://mainnet.base.org"), "public_fallback")

    def test_public_fallback_arb(self):
        self.assertEqual(classify_provider("https://arb1.arbitrum.io/rpc"), "public_fallback")

    def test_localhost(self):
        self.assertEqual(classify_provider("http://localhost:8545"), "localhost")

    def test_empty(self):
        self.assertEqual(classify_provider(""), "unknown")


class TestValidateDrpcUrl(unittest.TestCase):
    """dRPC chain validation catches wrong-chain URLs."""

    def test_correct_chain_lb_drpc_live(self):
        ok, err = validate_drpc_url("https://lb.drpc.live/base/keyabc", "base")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_wrong_chain_lb_drpc_live(self):
        ok, err = validate_drpc_url("https://lb.drpc.live/arbitrum/keyabc", "base")
        self.assertFalse(ok)
        self.assertIn("mismatch", err)
        self.assertIn("arbitrum", err)

    def test_correct_chain_drpc_org(self):
        ok, err = validate_drpc_url("https://arbitrum.drpc.org", "arbitrum")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_wrong_chain_drpc_org(self):
        ok, err = validate_drpc_url("https://base.drpc.org", "arbitrum")
        self.assertFalse(ok)
        self.assertIn("mismatch", err)

    def test_non_drpc_skipped(self):
        ok, err = validate_drpc_url("https://arb-mainnet.g.alchemy.com/v2/key", "base")
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_empty_url(self):
        ok, err = validate_drpc_url("", "base")
        self.assertTrue(ok)


class TestChainScopedEnvResolution(unittest.TestCase):
    """Chain-scoped env vars (BASE_RPC, BASE_WSS etc.) take priority."""

    def test_base_rpc_env_used(self):
        env = {"BASE_RPC": "https://lb.drpc.live/base/key123", "ALCHEMY_API_KEY": "alch"}
        url, prov, diag = resolve_rpc_http(chain_id=8453, network="base", env=env)
        self.assertIn("drpc.live", url)
        self.assertEqual(prov, "drpc")
        self.assertIn("chain_env", diag["source"])

    def test_base_wss_env_used(self):
        env = {"BASE_WSS": "wss://lb.drpc.live/base/key123", "ALCHEMY_API_KEY": "alch"}
        url, prov, diag = resolve_rpc_ws(chain_id=8453, network="base", env=env)
        self.assertIn("drpc.live", url)
        self.assertEqual(prov, "drpc")
        self.assertIn("chain_env", diag["source"])

    def test_wrong_chain_drpc_rejected(self):
        """BASE_RPC with arbitrum dRPC path is rejected; falls through to Alchemy."""
        env = {"BASE_RPC": "https://lb.drpc.live/arbitrum/key123", "ALCHEMY_API_KEY": "alch"}
        url, prov, diag = resolve_rpc_http(chain_id=8453, network="base", env=env)
        # Should NOT use the wrong-chain dRPC URL
        self.assertNotIn("arbitrum", url.lower().split("alchemy")[0] if "alchemy" in url.lower() else "")
        self.assertIn("skipped_chain_env", diag)

    def test_arbitrum_rpc_env_used(self):
        env = {"ARBITRUM_RPC": "https://lb.drpc.live/arbitrum/key123"}
        url, prov, diag = resolve_rpc_http(chain_id=42161, network="arbitrum", env=env)
        self.assertIn("drpc.live", url)
        self.assertEqual(prov, "drpc")

    def test_chain_env_priority_over_alchemy(self):
        """Chain-scoped env var takes priority over ALCHEMY_API_KEY."""
        env = {
            "BASE_RPC": "https://lb.drpc.live/base/key123",
            "ALCHEMY_API_KEY": "my_alchemy_key",
        }
        url, prov, diag = resolve_rpc_http(chain_id=8453, network="base", env=env)
        self.assertIn("drpc.live", url)
        self.assertEqual(prov, "drpc")


class TestProviderProvenanceAdditive(unittest.TestCase):
    """New fields are additive — existing JSON keys unchanged."""

    def test_resolve_rpc_http_returns_3_tuple(self):
        """resolve_rpc_http always returns (url, provider, diag) 3-tuple."""
        url, prov, diag = resolve_rpc_http(chain_id=8453, network="base", env={})
        self.assertIsInstance(diag, dict)
        self.assertIn("source", diag)

    def test_resolve_rpc_ws_returns_3_tuple(self):
        url, prov, diag = resolve_rpc_ws(chain_id=8453, network="base", env={})
        self.assertIsInstance(diag, dict)
        self.assertIn("source", diag)

    def test_public_ws_fallback_returns_publicnode(self):
        """Public WS fallback now returns 'publicnode' instead of 'public'."""
        url, prov, diag = resolve_rpc_ws(chain_id=8453, network="base", env={})
        # With no env vars, falls through to public WS
        self.assertEqual(prov, "publicnode")
        self.assertIn("publicnode", url)


if __name__ == '__main__':
    unittest.main()
