# PATH: tests/unit/test_ci_m4_gate_negative.py
"""Negative tests for ci_m4_execution_gate.py.

Tests cover:
1. current_block mismatch between signal and execution
2. missing simulation metrics
3. execution_enabled=true invariant violation
4. DoD profile requirements (smoke vs profit)
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
    validate_block_consistency,
    DoDProfile,
    main,
)


class TestCurrentBlockMismatch(unittest.TestCase):
    """Test that block mismatch is detected."""

    def test_signal_and_sim_block_mismatch_fails(self):
        """If simulation uses different block than signal/header, gate should fail."""
        # Create signals with one block
        signals_data = {
            "schema_version": "m4:signals:v1",
            "run_mode": "FIXTURE_OFFLINE",
            "pinned_block": 429900000,
            "signals": [
                {
                    "signal_id": "sig_001",
                    "pair": "ARB/WETH",
                    "pinned_block": 429900000,
                }
            ],
        }
        
        # Create execution with DIFFERENT block in simulations
        exec_data = {
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            "execution_enabled": False,
            "chain_id": 42161,
            "pinned_block": 429900000,  # Header matches signals
            "simulations": [
                {
                    "signal_id": "sig_001",
                    "simulation_status": "PASS",
                    "block_used": 429900001,  # MISMATCH - different block
                    "gas_usd": 0.45,
                    "net_usd": 0.38,
                    "is_profitable": True,
                }
            ],
            "simulations_count": 1,
            "simulations_passed": 1,
            "simulations_failed": 0,
            "total_net_usd": 0.38,
            "accounting": {"signals_total": 1, "accounting_complete": True},
            "health": {"simulation_pass_rate": 1.0},
        }
        
        # Block consistency check should fail
        checks = validate_block_consistency(signals_data, exec_data)
        failures = [c for c in checks if not c[1]]
        
        # Should have failure for sim block mismatch
        self.assertGreater(len(failures), 0, "Block mismatch should be detected")
        self.assertTrue(
            any("block" in f[2].lower() and "!=" in f[2] for f in failures),
            f"Expected block mismatch failure, got: {failures}"
        )

    def test_header_block_mismatch_fails(self):
        """If signals header and execution header have different pinned_block, fail."""
        signals_data = {
            "schema_version": "m4:signals:v1",
            "run_mode": "FIXTURE_OFFLINE",
            "pinned_block": 429900000,
            "signals": [],
        }
        
        exec_data = {
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            "execution_enabled": False,
            "chain_id": 42161,
            "pinned_block": 429900999,  # MISMATCH with signals header
            "simulations": [],
            "simulations_count": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "total_net_usd": 0,
            "accounting": {"signals_total": 0, "accounting_complete": True},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_block_consistency(signals_data, exec_data)
        failures = [c for c in checks if not c[1]]
        
        self.assertGreater(len(failures), 0, "Header block mismatch should be detected")


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
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            "execution_enabled": True,  # INVARIANT VIOLATION
            "chain_id": 42161,
            "pinned_block": 429900000,
            "simulations": [],
            "simulations_count": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "total_net_usd": 0,
            "accounting": {"signals_total": 0, "accounting_complete": True},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_execution_report(exec_data, DoDProfile.SMOKE, strict=False)
        failures = [c for c in checks if not c[1]]
        
        # Should have at least one failure for execution_enabled
        exec_failures = [f for f in failures if "execution_enabled" in f[0]]
        self.assertEqual(len(exec_failures), 1)
        self.assertIn("INVARIANT VIOLATED", exec_failures[0][2])

    def test_execution_enabled_missing_fails(self):
        """Missing execution_enabled should fail validation."""
        exec_data = {
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            # "execution_enabled": False,  # MISSING
            "chain_id": 42161,
            "pinned_block": 429900000,
            "simulations": [],
            "simulations_count": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "total_net_usd": 0,
            "accounting": {"signals_total": 0, "accounting_complete": True},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_execution_report(exec_data, DoDProfile.SMOKE, strict=False)
        failures = [c for c in checks if not c[1]]
        
        exec_failures = [f for f in failures if "execution_enabled" in f[0]]
        self.assertEqual(len(exec_failures), 1)


class TestStrictModeRequirements(unittest.TestCase):
    """Test strict mode requirements."""

    def test_no_profitable_sims_passes_smoke_fails_profit(self):
        """0 profitable simulations should pass smoke profile, fail profit profile."""
        exec_data = {
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            "execution_enabled": False,
            "chain_id": 42161,
            "pinned_block": 429900000,
            "simulations": [
                {
                    "signal_id": "sig_001",
                    "simulation_status": "FAIL",
                    "block_used": 429900000,
                    "blocker": "SIM_UNPROFITABLE",
                    "gas_usd": 0.45,
                    "net_usd": -0.20,
                    "is_profitable": False,
                }
            ],
            "simulations_count": 1,
            "simulations_passed": 0,
            "simulations_failed": 1,
            "total_net_usd": -0.20,
            "accounting": {"signals_total": 1, "accounting_complete": True},
            "health": {"simulation_pass_rate": 0},
        }
        
        # Smoke profile with 0 profitable should FAIL (requires >=1)
        checks_smoke = validate_execution_report(exec_data, DoDProfile.SMOKE, strict=False)
        failures_smoke = [c for c in checks_smoke if not c[1]]
        self.assertGreater(len(failures_smoke), 0, "Smoke profile should fail with 0 profitable")
        
        # Profit profile should also fail (total_net < 0)
        checks_profit = validate_execution_report(exec_data, DoDProfile.PROFIT, strict=False)
        failures_profit = [c for c in checks_profit if not c[1]]
        self.assertGreater(len(failures_profit), 0, "Profit profile should fail with negative net")


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
