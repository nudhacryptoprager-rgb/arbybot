import os
import tempfile
import json
import unittest
from pathlib import Path

from strategy.jobs import run_scan_real


class TestRunScanInfra(unittest.TestCase):
    def test_run_scan_writes_infra_from_env(self):
        env_backup = os.environ.copy()
        try:
            # Set ALCHEMY_API_KEY and skip real RPC to avoid network calls
            os.environ["ALCHEMY_API_KEY"] = "TESTKEY"
            os.environ["NETWORK"] = "arbitrum"
            os.environ["ARBY_SKIP_RPC"] = "1"
            os.environ["ARBY_FAKE_BLOCK"] = "123"
            # Remove chain-scoped env vars so Alchemy resolution is tested
            # (dotenv may have loaded ARBITRUM_RPC from .env)
            for _k in ("ARBITRUM_RPC", "ARBITRUM_WSS", "BASE_RPC", "BASE_WSS",
                        "LINEA_RPC", "LINEA_WSS", "MANTLE_RPC", "MANTLE_WSS",
                        "SCROLL_RPC", "SCROLL_WSS", "OPTIMISM_RPC", "OPTIMISM_WSS",
                        "ARBY_RPC_HTTP_PRIMARY", "ARBY_RPC_WS_PRIMARY",
                        "ARBY_RPC_PROVIDER", "ARBY_RPC_HTTP_HOST",
                        "ARBY_RPC_WS_PROVIDER", "ARBY_RPC_WS_HOST"):
                os.environ.pop(_k, None)

            with tempfile.TemporaryDirectory() as td:
                out = Path(td)
                # provide minimal config to run_scan
                cfg = {"dexes": ["sushiswap_v3"], "chain_id": 42161}
                stats = run_scan_real.run_scan(cfg, out, cycles=1)

                # check artifacts
                reports = out / "reports"
                files = list(reports.glob("*.json"))
                self.assertTrue(len(files) >= 1)

                # read truth_report for infra
                tr_files = list(reports.glob("truth_report_*.json"))
                self.assertTrue(len(tr_files) == 1)
                with open(tr_files[0]) as f:
                    data = json.load(f)
                self.assertIn("infra", data)
                infra = data["infra"]
                self.assertEqual(infra.get("rpc_provider"), "alchemy")
                self.assertFalse(infra.get("ws_enabled") and infra.get("ws_connected"))
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


    def test_phase_timers_expanded_fields(self):
        """R28.5: phase_timers_ms should include expanded fields."""
        env_backup = os.environ.copy()
        try:
            os.environ["ARBY_SKIP_RPC"] = "1"
            os.environ["ARBY_FAKE_BLOCK"] = "123"

            with tempfile.TemporaryDirectory() as td:
                out = Path(td)
                cfg = {"dexes": ["sushiswap_v3"], "chain_id": 42161}
                stats = run_scan_real.run_scan(cfg, out, cycles=1)

                pt = stats.get("phase_timers_ms")
                self.assertIsNotNone(pt, "phase_timers_ms missing from stats")
                # R28.5 expanded fields
                for key in ["total_ms", "discovery_ms", "quote_rpc_ms",
                             "postprocess_ms", "preflight_ms", "report_ms"]:
                    self.assertIn(key, pt, f"Missing phase timer key: {key}")
                    self.assertIsInstance(pt[key], int, f"{key} should be int")
                    self.assertGreaterEqual(pt[key], 0, f"{key} should be >= 0")
                # Legacy aliases for backward compat
                self.assertIn("init_rpc_ms", pt)
                self.assertIn("post_scan_ms", pt)
                # discovery_ms == init_rpc_ms (same value, different name)
                self.assertEqual(pt["discovery_ms"], pt["init_rpc_ms"])
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


if __name__ == '__main__':
    unittest.main()
