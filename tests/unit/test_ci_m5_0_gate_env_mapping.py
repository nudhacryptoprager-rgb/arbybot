import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts import ci_m5_0_gate


class TestGateEnvMapping(unittest.TestCase):
    @patch('scripts.ci_m5_0_gate.subprocess.run')
    def test_online_injects_resolved_env_and_ws_flag(self, mock_run):
        env_backup = os.environ.copy()
        try:
            os.environ.pop('ARBY_RUN_DIR', None)
            os.environ['ALCHEMY_API_KEY'] = 'TESTKEY'
            os.environ['NETWORK'] = 'arbitrum'

            # mock subprocess.run to return success
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_run.return_value = mock_proc

            with tempfile.TemporaryDirectory() as tmpdir:
                out_root = Path(tmpdir)
                with patch('sys.argv', ['ci_m5_0_gate.py', '--online', '--output-root', str(out_root), '--ws']):
                    rc = ci_m5_0_gate.main()

            # Ensure subprocess.run was called and env passed contains ARBY_RPC_HTTP_PRIMARY and ARBY_PREFER_WS
            self.assertTrue(mock_run.called)
            called_env = mock_run.call_args[1].get('env')
            self.assertIsNotNone(called_env)
            self.assertIn('ARBY_RPC_HTTP_PRIMARY', called_env)
            self.assertEqual(called_env.get('ARBY_PREFER_WS'), '1')
        finally:
            os.environ.clear()
            os.environ.update(env_backup)


if __name__ == '__main__':
    unittest.main()
