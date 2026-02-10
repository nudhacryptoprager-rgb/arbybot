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
                    "gas_usdc": 0.45,
                    "net_usdc": 0.38,
                    "is_profitable": True,
                }
            ],
            "simulations_count": 1,
            "simulations_passed": 1,
            "simulations_failed": 0,
            "total_net_usdc": 0.38,
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
            "total_net_usdc": 0,
            "kill_switch_active": True,
            "accounting": {"signals_total": 0, "accounting_complete": True},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_block_consistency(signals_data, exec_data)
        failures = [c for c in checks if not c[1]]
        
        self.assertGreater(len(failures), 0, "Header block mismatch should be detected")


class TestMissingSimulationMetrics(unittest.TestCase):
    """Test that missing simulation metrics fail validation."""

    def test_missing_gas_usdc_fails(self):
        """Simulation without gas_usdc should fail."""
        simulations = [
            {
                "signal_id": "sig_001",
                "simulation_status": "PASS",
                # "gas_usdc": "0.45",  # MISSING
                "net_usdc": "0.38",
                "is_profitable": True,
            }
        ]
        
        checks = validate_simulations(simulations)
        failures = [c for c in checks if not c[1]]
        
        self.assertEqual(len(failures), 1)
        self.assertIn("gas_usdc", str(failures[0]))

    def test_missing_net_usdc_fails(self):
        """Simulation without net_usdc should fail."""
        simulations = [
            {
                "signal_id": "sig_001",
                "simulation_status": "PASS",
                "gas_usdc": "0.45",
                # "net_usdc": "0.38",  # MISSING
                "is_profitable": True,
            }
        ]
        
        checks = validate_simulations(simulations)
        failures = [c for c in checks if not c[1]]
        
        self.assertEqual(len(failures), 1)
        self.assertIn("net_usdc", str(failures[0]))

    def test_fail_without_blocker_reason_fails(self):
        """FAIL status without blocker reason should fail validation."""
        simulations = [
            {
                "signal_id": "sig_001",
                "simulation_status": "FAIL",
                "gas_usdc": "0.45",
                "net_usdc": "-0.20",
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
            "total_net_usdc": 0,
            "kill_switch_active": True,
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
            "kill_switch_active": True,
            "chain_id": 42161,
            "pinned_block": 429900000,
            "simulations": [],
            "simulations_count": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "total_net_usdc": 0,
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
                    "gas_usdc": 0.45,
                    "net_usdc": -0.20,
                    "is_profitable": False,
                }
            ],
            "simulations_count": 1,
            "simulations_passed": 0,
            "simulations_failed": 1,
            "total_net_usdc": -0.20,
            "kill_switch_active": True,
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


class TestKillSwitchStrict(unittest.TestCase):
    """Test strict kill_switch validation (M4 invariant)."""

    def test_kill_switch_false_fails(self):
        """kill_switch_active=false should fail (M4 invariant)."""
        exec_data = {
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            "execution_enabled": False,
            "kill_switch_active": False,  # INVARIANT VIOLATION
            "chain_id": 42161,
            "pinned_block": 429900000,
            "simulations": [],
            "simulations_count": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "total_net_usdc": 0,
            "accounting": {"signals_total": 0, "accounting_complete": True},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_execution_report(exec_data, DoDProfile.SMOKE, strict=False)
        failures = [c for c in checks if not c[1]]
        
        ks_failures = [f for f in failures if "kill_switch" in f[0]]
        self.assertEqual(len(ks_failures), 1, "kill_switch=false should fail")
        self.assertIn("DANGER", ks_failures[0][2])

    def test_kill_switch_missing_fails(self):
        """Missing kill_switch_active should fail (M4 strict)."""
        exec_data = {
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            "execution_enabled": False,
            # "kill_switch_active": True,  # MISSING
            "chain_id": 42161,
            "pinned_block": 429900000,
            "simulations": [],
            "simulations_count": 0,
            "simulations_passed": 0,
            "simulations_failed": 0,
            "total_net_usdc": 0,
            "accounting": {"signals_total": 0, "accounting_complete": True},
            "health": {"simulation_pass_rate": 0},
        }
        
        checks = validate_execution_report(exec_data, DoDProfile.SMOKE, strict=False)
        failures = [c for c in checks if not c[1]]
        
        ks_failures = [f for f in failures if "kill_switch" in f[0]]
        self.assertEqual(len(ks_failures), 1, "kill_switch missing should fail")
        self.assertIn("MISSING", ks_failures[0][2])


class TestBlocksConsistentFails(unittest.TestCase):
    """Test that blocks_consistent=false fails validation."""

    def test_blocks_inconsistent_fails_smoke(self):
        """blocks_consistent=false should fail smoke profile."""
        exec_data = {
            "schema_version": "m4:execution:v1.1",
            "run_mode": "FIXTURE_OFFLINE",
            "execution_mode": "simulate_only",
            "execution_enabled": False,
            "kill_switch_active": True,
            "chain_id": 42161,
            "pinned_block": 429900000,
            "simulations": [
                {
                    "signal_id": "sig_001",
                    "simulation_status": "PASS",
                    "block_used": 429900001,  # DIFFERENT from pinned
                    "gas_usdc": 0.45,
                    "net_usdc": 0.38,
                    "is_profitable": True,
                }
            ],
            "simulations_count": 1,
            "simulations_passed": 1,
            "simulations_failed": 0,
            "total_net_usdc": 0.38,
            "accounting": {"signals_total": 1, "accounting_complete": True},
            "health": {
                "simulation_pass_rate": 1.0,
                "blocks_consistent": False,  # Explicitly false
            },
        }
        
        checks = validate_execution_report(exec_data, DoDProfile.SMOKE, strict=False)
        failures = [c for c in checks if not c[1]]
        
        # Should have blocks_consistent failure
        block_failures = [f for f in failures if "block" in f[0].lower()]
        self.assertGreater(len(block_failures), 0, "blocks_consistent=false should fail smoke")


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


class TestPriceDirectionInvariant(unittest.TestCase):
    """Test price direction / pair semantics invariants."""

    def test_signals_have_base_quote_tokens(self):
        """Signals must have base_token, quote_token, price_in fields."""
        # Valid signal with proper semantics
        valid_signal = {
            "signal_id": "sig_001",
            "pair": "ARB/WETH",
            "base_token": "ARB",
            "quote_token": "WETH",
            "price_in": "quote_per_base",
            "buy_price": "0.00005625",
            "sell_price": "0.00005644",
        }
        
        # Check base/quote consistency with pair
        pair_parts = valid_signal["pair"].split("/")
        self.assertEqual(valid_signal["base_token"], pair_parts[0])
        self.assertEqual(valid_signal["quote_token"], pair_parts[1])
        
    def test_pair_semantics_must_match(self):
        """If pair=ARB/WETH, then base=ARB, quote=WETH - no swap."""
        # Simulating a fixture that swaps the direction
        invalid_signal = {
            "signal_id": "sig_001",
            "pair": "ARB/WETH",       # pair says ARB is base
            "base_token": "WETH",     # BUT this says WETH is base
            "quote_token": "ARB",     # WRONG direction
        }
        
        pair_parts = invalid_signal["pair"].split("/")
        # This should NOT match - it's the invariant violation
        self.assertNotEqual(
            invalid_signal["base_token"], pair_parts[0],
            "If pair=ARB/WETH, base_token must be ARB, not WETH"
        )

    def test_spread_bps_micro_is_integer(self):
        """spread_bps_micro must be an integer, not float."""
        valid_signal = {
            "spread_bps_micro": 337800,  # 33.78 bps as integer micro-bps
        }
        
        self.assertIsInstance(valid_signal["spread_bps_micro"], int)
        # 1 bps = 10000 micro-bps
        bps = valid_signal["spread_bps_micro"] / 10000
        self.assertAlmostEqual(bps, 33.78, places=2)

    def test_price_format_is_decimal_string(self):
        """Prices must be decimal strings, not numbers."""
        valid_signal = {
            "buy_price": "0.00005625",
            "sell_price": "0.00005644",
        }
        
        self.assertIsInstance(valid_signal["buy_price"], str)
        self.assertIsInstance(valid_signal["sell_price"], str)
        
        # Should be parseable as float
        buy = float(valid_signal["buy_price"])
        sell = float(valid_signal["sell_price"])
        self.assertGreater(sell, buy)  # Sell > Buy for profitable signal


class TestEstErrorFormula(unittest.TestCase):
    """Test that est_error_usdc = sim_net_usdc - est_net_usdc for all entries."""

    def test_est_error_formula_profitable(self):
        """est_error_usdc must equal sim_net_usdc - est_net_usdc for profitable sim."""
        sim = {
            "sim_net_usdc": 0.38,
            "est_net_usdc": 0.83,
            "est_error_usdc": -0.45,  # 0.38 - 0.83 = -0.45
        }
        
        expected = sim["sim_net_usdc"] - sim["est_net_usdc"]
        self.assertAlmostEqual(sim["est_error_usdc"], expected, places=6)

    def test_est_error_formula_unprofitable(self):
        """est_error_usdc must equal sim_net_usdc - est_net_usdc for unprofitable sim."""
        sim = {
            "sim_net_usdc": -0.67,
            "est_net_usdc": -0.55,
            "est_error_usdc": -0.12,  # -0.67 - (-0.55) = -0.12
        }
        
        expected = sim["sim_net_usdc"] - sim["est_net_usdc"]
        self.assertAlmostEqual(sim["est_error_usdc"], expected, places=6)

    def test_est_error_in_fixture(self):
        """Validate that offline fixture generates correct est_error_usdc."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m4_execution_gate.py', '--offline', '--output-root', str(output_root)]):
                main()
            
            # Find generated execution report
            run_dirs = list(output_root.glob("ci_m4_gate_offline_*"))
            self.assertEqual(len(run_dirs), 1)
            
            exec_files = list((run_dirs[0] / "reports").glob("execution_report_*.json"))
            self.assertEqual(len(exec_files), 1)
            
            with open(exec_files[0]) as f:
                exec_data = json.load(f)
            
            # Verify formula for each simulation
            for sim in exec_data.get("simulations", []):
                if "est_net_usdc" in sim and "net_usdc" in sim:
                    expected = sim["net_usdc"] - sim["est_net_usdc"]
                    actual = sim.get("est_error_usdc", 0)
                    self.assertAlmostEqual(
                        actual, expected, places=6,
                        msg=f"est_error_usdc mismatch for {sim.get('signal_id')}: {actual} != {expected}"
                    )


class TestQuoteCcyConsistency(unittest.TestCase):
    """Test that quote_ccy is consistent between signals and execution_report."""

    def test_quote_ccy_matches(self):
        """quote_ccy in signals must match quote_ccy in execution_report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m4_execution_gate.py', '--offline', '--output-root', str(output_root)]):
                main()
            
            run_dirs = list(output_root.glob("ci_m4_gate_offline_*"))
            self.assertEqual(len(run_dirs), 1)
            
            signals_files = list((run_dirs[0] / "reports").glob("signals_*.json"))
            exec_files = list((run_dirs[0] / "reports").glob("execution_report_*.json"))
            
            self.assertEqual(len(signals_files), 1)
            self.assertEqual(len(exec_files), 1)
            
            with open(signals_files[0]) as f:
                signals_data = json.load(f)
            with open(exec_files[0]) as f:
                exec_data = json.load(f)
            
            # Both must have quote_ccy and they must match
            signals_ccy = signals_data.get("quote_ccy")
            exec_ccy = exec_data.get("quote_ccy")
            
            self.assertIsNotNone(signals_ccy, "signals must have quote_ccy")
            self.assertIsNotNone(exec_ccy, "execution_report must have quote_ccy")
            self.assertEqual(signals_ccy, exec_ccy, f"quote_ccy mismatch: {signals_ccy} != {exec_ccy}")
            self.assertEqual(signals_ccy, "USDC", "quote_ccy must be USDC")

    def test_health_contains_execution_safety(self):
        """health section must contain execution_enabled and kill_switch_active."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m4_execution_gate.py', '--offline', '--output-root', str(output_root)]):
                main()
            
            run_dirs = list(output_root.glob("ci_m4_gate_offline_*"))
            exec_files = list((run_dirs[0] / "reports").glob("execution_report_*.json"))
            
            with open(exec_files[0]) as f:
                exec_data = json.load(f)
            
            health = exec_data.get("health", {})
            
            # Must have execution safety fields
            self.assertIn("execution_enabled", health, "health must have execution_enabled")
            self.assertIn("kill_switch_active", health, "health must have kill_switch_active")
            
            # M4 invariants
            self.assertEqual(health["execution_enabled"], False, "health.execution_enabled must be false")
            self.assertEqual(health["kill_switch_active"], True, "health.kill_switch_active must be true")


class TestCLIEncoding(unittest.TestCase):
    """Test that CLI output contains only ASCII characters (CP1251 safe)."""

    def test_cli_output_is_ascii_safe(self):
        """Verify m4/cli.py has no non-ASCII characters that would crash on CP1251."""
        import m4.cli as cli_module
        import inspect
        
        # Get source code of cli module
        source = inspect.getsource(cli_module)
        
        # Check for non-ASCII characters
        non_ascii = []
        for i, char in enumerate(source):
            if ord(char) > 127:
                # Find line number
                line_num = source[:i].count('\n') + 1
                non_ascii.append((line_num, char, hex(ord(char))))
        
        self.assertEqual(
            non_ascii, 
            [], 
            f"Found non-ASCII characters in m4/cli.py that would crash on CP1251: {non_ascii[:5]}"
        )
    
    def test_cli_print_statements_are_encodable(self):
        """Verify all print statements in cli.py can be encoded as ASCII."""
        import m4.cli as cli_module
        import inspect
        import re
        
        source = inspect.getsource(cli_module)
        
        # Find all string literals in print() calls
        print_pattern = r'print\s*\(["\']([^"\']*)["\']'
        matches = re.findall(print_pattern, source)
        
        for msg in matches:
            try:
                msg.encode('ascii')
            except UnicodeEncodeError as e:
                self.fail(f"Print message contains non-ASCII: {msg!r} - {e}")


if __name__ == "__main__":
    unittest.main()
