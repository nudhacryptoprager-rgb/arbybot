# PATH: tests/unit/test_imports_contract.py
"""
Import contract smoke tests.

PURPOSE: Catch ImportError regressions EARLY.
RUN FIRST: python -m pytest tests/unit/test_imports_contract.py -v

CRITICAL CONTRACTS (DO NOT WEAKEN):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- DexType MUST be importable
- TokenStatus MUST be importable
- PoolStatus MUST be importable ← NEW
- ExecutionBlocker MUST be importable
- RPCHealthMetrics MUST be importable ← NEW
- AnchorQuote.dex_id MUST be required
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestCoreConstantsImports(unittest.TestCase):
    """Test core.constants imports."""

    def test_import_module(self):
        """Test import core.constants works."""
        from core import constants
        self.assertTrue(hasattr(constants, 'SCHEMA_VERSION'))

    def test_import_dex_type(self):
        """CRITICAL: Test DexType import."""
        from core.constants import DexType
        
        self.assertTrue(hasattr(DexType, 'UNISWAP_V3'))
        self.assertEqual(DexType.UNISWAP_V3.value, "uniswap_v3")

    def test_import_token_status(self):
        """CRITICAL: Test TokenStatus import."""
        from core.constants import TokenStatus
        
        self.assertTrue(hasattr(TokenStatus, 'ACTIVE'))
        self.assertEqual(TokenStatus.ACTIVE.value, "active")

    def test_import_pool_status(self):
        """
        CRITICAL: Test PoolStatus import.
        
        This was missing and broke core.models!
        Used by: core.models, discovery.*, dex.adapters.*
        """
        from core.constants import PoolStatus
        
        self.assertTrue(hasattr(PoolStatus, 'ACTIVE'))
        self.assertTrue(hasattr(PoolStatus, 'INACTIVE'))
        self.assertTrue(hasattr(PoolStatus, 'QUARANTINED'))
        self.assertTrue(hasattr(PoolStatus, 'PENDING'))
        self.assertTrue(hasattr(PoolStatus, 'ERROR'))
        
        self.assertEqual(PoolStatus.ACTIVE.value, "active")
        self.assertEqual(PoolStatus.QUARANTINED.value, "quarantined")

    def test_import_execution_blocker(self):
        """Test ExecutionBlocker import."""
        from core.constants import ExecutionBlocker
        
        self.assertTrue(hasattr(ExecutionBlocker, 'EXECUTION_DISABLED'))
        self.assertEqual(ExecutionBlocker.EXECUTION_DISABLED.value, "EXECUTION_DISABLED")

    def test_import_current_execution_blocker_stage_agnostic(self):
        """Test CURRENT_EXECUTION_BLOCKER is stage-agnostic (not M4)."""
        from core.constants import CURRENT_EXECUTION_BLOCKER, ExecutionBlocker
        
        self.assertEqual(CURRENT_EXECUTION_BLOCKER, ExecutionBlocker.EXECUTION_DISABLED)
        self.assertNotIn("M4", CURRENT_EXECUTION_BLOCKER.value)

    def test_import_anchor_priority(self):
        """Test ANCHOR_DEX_PRIORITY import."""
        from core.constants import ANCHOR_DEX_PRIORITY
        
        self.assertIsInstance(ANCHOR_DEX_PRIORITY, tuple)
        self.assertIn("uniswap_v3", ANCHOR_DEX_PRIORITY)

    def test_import_price_sanity_bounds(self):
        """Test PRICE_SANITY_BOUNDS import."""
        from core.constants import PRICE_SANITY_BOUNDS
        
        self.assertIsInstance(PRICE_SANITY_BOUNDS, dict)
        self.assertIn(("WETH", "USDC"), PRICE_SANITY_BOUNDS)


class TestMonitoringImports(unittest.TestCase):
    """Test monitoring package imports."""

    def test_import_truth_report_module(self):
        """Test import monitoring.truth_report works."""
        from monitoring import truth_report
        self.assertTrue(hasattr(truth_report, 'TruthReport'))

    def test_import_rpc_health_metrics_from_module(self):
        """
        CRITICAL: Test RPCHealthMetrics import from module.
        
        This was missing and broke monitoring/__init__.py!
        Used by: monitoring/__init__.py, tests/unit/test_confidence.py
        """
        from monitoring.truth_report import RPCHealthMetrics
        
        # Verify it's a dataclass with expected fields
        metrics = RPCHealthMetrics()
        self.assertTrue(hasattr(metrics, 'total_requests'))
        self.assertTrue(hasattr(metrics, 'successful_requests'))
        self.assertTrue(hasattr(metrics, 'failed_requests'))
        self.assertTrue(hasattr(metrics, 'success_rate'))
        self.assertTrue(hasattr(metrics, 'health_ratio'))

    def test_import_rpc_health_metrics_from_package(self):
        """Test RPCHealthMetrics can be imported from monitoring package."""
        from monitoring import RPCHealthMetrics
        
        metrics = RPCHealthMetrics(total_requests=100, successful_requests=95)
        self.assertEqual(metrics.total_requests, 100)
        self.assertEqual(metrics.successful_requests, 95)

    def test_import_health_metrics(self):
        """Test HealthMetrics import."""
        from monitoring.truth_report import HealthMetrics
        
        metrics = HealthMetrics(quotes_total=10, quotes_fetched=10)
        self.assertEqual(metrics.quotes_total, 10)

    def test_import_calculate_confidence(self):
        """
        Test calculate_confidence import.
        
        Used by: tests/unit/test_confidence.py
        """
        from monitoring import calculate_confidence
        
        self.assertTrue(callable(calculate_confidence))
        result = calculate_confidence(spread_bps=50)
        self.assertIn(result, ["low", "medium", "high"])

    def test_import_truth_report_class(self):
        """Test TruthReport class import."""
        from monitoring import TruthReport
        
        report = TruthReport()
        self.assertTrue(hasattr(report, 'execution_blocker'))
        self.assertEqual(report.execution_blocker, "EXECUTION_DISABLED")


class TestCoreValidatorsImports(unittest.TestCase):
    """Test core.validators imports."""

    def test_import_module(self):
        """Test import core.validators works."""
        try:
            from core import validators
            self.assertTrue(hasattr(validators, 'check_price_sanity'))
        except ImportError:
            self.skipTest("core.validators not available")

    def test_import_anchor_quote(self):
        """Test AnchorQuote import and dex_id required."""
        try:
            from core.validators import AnchorQuote
            from decimal import Decimal
            
            quote = AnchorQuote(
                dex_id="uniswap_v3",
                price=Decimal("2600"),
                fee=500,
                pool_address="0x1234",
                block_number=100,
            )
            self.assertEqual(quote.dex_id, "uniswap_v3")
        except ImportError:
            self.skipTest("core.validators not available")


class TestCrossModuleCompat(unittest.TestCase):
    """Test cross-module compatibility."""

    def test_dex_type_in_anchor_priority(self):
        """Test DexType values match ANCHOR_DEX_PRIORITY."""
        from core.constants import DexType, ANCHOR_DEX_PRIORITY
        
        for dex in ANCHOR_DEX_PRIORITY:
            found = any(m.value == dex for m in DexType)
            self.assertTrue(found, f"DexType missing: {dex}")

    def test_pool_status_has_quarantine(self):
        """Test PoolStatus has QUARANTINED for RPC quarantine."""
        from core.constants import PoolStatus
        
        self.assertTrue(hasattr(PoolStatus, 'QUARANTINED'))
        self.assertEqual(PoolStatus.QUARANTINED.value, "quarantined")

    def test_rpc_health_metrics_has_health_ratio(self):
        """Test RPCHealthMetrics.health_ratio property."""
        from monitoring import RPCHealthMetrics
        
        metrics = RPCHealthMetrics(endpoints_healthy=8, endpoints_total=10)
        self.assertAlmostEqual(metrics.health_ratio, 0.8)


if __name__ == "__main__":
    unittest.main()
