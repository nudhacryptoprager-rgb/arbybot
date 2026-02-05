import unittest
from core.rpc_urls import build_alchemy_http_url, build_alchemy_ws_url, public_fallback_for


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


if __name__ == '__main__':
    unittest.main()
