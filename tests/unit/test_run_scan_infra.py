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


if __name__ == '__main__':
    unittest.main()
