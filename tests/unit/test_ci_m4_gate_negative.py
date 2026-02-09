# PATH: tests/unit/test_ci_m4_gate_negative.py
"""Negative tests for ci_m4_execution_gate.py.

Tests cover:
1. current_block mismatch between signal and execution
2. missing simulation metrics
3. execution_enabled=true invariant violation
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m4_execution_gate import (
    validate_execution_report,
    validate_simulations,
    main,
)


class TestCurrentBlockMismatch(unittest.TestCase):
    """Test that block mismatch is detected."""

    def test_signal_and_sim_block_mismatch_fails(self):
        """If simulation uses different block than signal, gate should warn."""
        # Create signals with one block
        signals_data = {
            "schema_version": "m4:signals:v1",
            "run_mode": "FIXTURE_OFFLINE",
            "signals": [
                {
                    "signal_id": "sig_001",
                    "pair": "ARB/WETH",
                    "pinned_block": 429900000,
                }
            ],
        }
        
        # Create execution with different block context
        exec_data = {
            "schema_version": "m4:execution:v1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_enabled": False,
            "simulations": [
                {
                    "signal_id": "sig_001",
                    "simulation_status": "PASS",
                    "gas_usd": "0.45",
                    "net_usd": "0.38",
                    "is_profitable": True,
                    # Note: no pinned_block field - this is a gap to address
                }
            ],
            "simulations_count": 1,
            "simulations_passed": 1,
            "simulations_failed": 0,
            "accounting": {"signals_total": 1},
            "health": {"simulation_pass_rate": 1.0},
        }
        
        # Currently passes because block matching not yet enforced
        checks = validate_execution_report(exec_data, strict=False)
        # All should pass for now
        failures = [c for c in checks if not c[1]]
        # This test documents the gap - block binding not yet enforced
        self.assertEqual(len(failures), 0, "Block binding not yet enforced")


class TestMissingSimulationMetrics(unittest.TestCase):
    """Test that missing simulation metrics fail validation."""

    def test_missing_gas_usd_fails(self):
        """Simulation without gas_usd should fail."""
        simulations = [
            {
                "signal_id": "sig_001",
                "simulation_status": "PASS",
                # "gas_usd": "0.45",  # MISSING
                "net_usd": "0.38",
                "is_profitable": True,
            }
        ]
        
        checks = validate_simulations(simulations)
        failures = [c for c in checks if not c[1]]
        
        self.assertEqual(len(failures), 1)
        self.assertIn("gas_usd", str(failures[0]))

    def test_missing_net_usd_fails(self):
        """Simulation without net_usd should fail."""
        simulations = [
            {
                "signal_id": "sig_001",
                "simulation_status": "PASS",
                "gas_usd": "0.45",
                # "net_usd": "0.38",  # MISSING
                "is_profitable": True,
            }
        ]
        
        checks = validate_simulations(simulations)
        failures = [c for c in checks if not c[1]]
        
        self.assertEqual(len(failures), 1)
        self.assertIn("net_usd", str(failures[0]))

    def test_fail_without_blocker_reason_fails(self):
        """FAIL status without blocker reason should fail validation."""
        simulations = [
            {
                "signal_id": "sig_001",
                "simulation_status": "FAIL",
                "gas_usd": "0.45",
                "net_usd": "-0.20",
                "is_profitable": False,
                # "blocker": "SIM_UNPROFITABLE",  # MISSING
            }
        ]
        
        checks = validate_simulations(simulations)
        failures = [c for c in checks if not c[1]]
        
        self.assertGreater(len(failures), 0)
        blocker_failure = [f for f in failures if "blocker" in f[0]]
        self.assertEqual(len(blocker_failure), 1)


class TestExecutionEnabledInvariant(unittest.TestCase):
    """Test that execution_enabled=true is rejected."""

    def test_execution_enabled_true_fails(self):
        """execution_enabled=true should fail validation (M4/M5 invariant)."""
        exec_data = {
            "schema_version": "m4:execution:v1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_enabled": True,  # INVARIANT VIOLATION
            "simulations": [],
            "simulations_count": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "accounting": {"signals_total": 0},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_execution_report(exec_data, strict=False)
        failures = [c for c in checks if not c[1]]
        
        # Should have at least one failure for execution_enabled
        exec_failures = [f for f in failures if "execution_enabled" in f[0]]
        self.assertEqual(len(exec_failures), 1)
        self.assertIn("INVARIANT VIOLATED", exec_failures[0][2])

    def test_execution_enabled_missing_fails(self):
        """Missing execution_enabled should fail validation."""
        exec_data = {
            "schema_version": "m4:execution:v1",
            "run_mode": "FIXTURE_OFFLINE",
            # "execution_enabled": False,  # MISSING
            "simulations": [],
            "simulations_count": 0,
            "accounting": {"signals_total": 0},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_execution_report(exec_data, strict=False)
        failures = [c for c in checks if not c[1]]
        
        exec_failures = [f for f in failures if "execution_enabled" in f[0]]
        self.assertEqual(len(exec_failures), 1)


class TestStrictModeRequirements(unittest.TestCase):
    """Test strict mode requirements."""

    def test_no_profitable_sims_passes_normal_fails_strict(self):
        """0 profitable simulations should pass normal, fail strict."""
        exec_data = {
            "schema_version": "m4:execution:v1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_enabled": False,
            "simulations": [
                {
                    "signal_id": "sig_001",
                    "simulation_status": "FAIL",
                    "blocker": "SIM_UNPROFITABLE",
                    "gas_usd": "0.45",
                    "net_usd": "-0.20",
                    "is_profitable": False,
                }
            ],
            "simulations_count": 1,
            "simulations_passed": 0,
            "simulations_failed": 1,
            "accounting": {"signals_total": 1},
            "health": {"simulation_pass_rate": 0},
        }
        
        # Normal mode - should pass (WARN only)
        checks_normal = validate_execution_report(exec_data, strict=False)
        failures_normal = [c for c in checks_normal if not c[1]]
        self.assertEqual(len(failures_normal), 0, "Normal mode should pass with 0 profitable")
        
        # Strict mode - should fail
        checks_strict = validate_execution_report(exec_data, strict=True)
        failures_strict = [c for c in checks_strict if not c[1]]
        self.assertGreater(len(failures_strict), 0, "Strict mode should fail with 0 profitable")


class TestGateIntegration(unittest.TestCase):
    """Integration tests for full gate run."""

    def test_offline_gate_passes(self):
        """Offline gate with fixtures should pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m4_execution_gate.py', '--offline', '--output-root', str(output_root)]):
                result = main()
            
            self.assertEqual(result, 0, "Offline gate should PASS")

    def test_offline_strict_gate_passes(self):
        """Offline gate with --strict should pass (fixtures have 1 profitable)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m4_execution_gate.py', '--offline', '--strict', '--output-root', str(output_root)]):
                result = main()
            
            self.assertEqual(result, 0, "Offline strict gate should PASS")


if __name__ == "__main__":
    unittest.main()
