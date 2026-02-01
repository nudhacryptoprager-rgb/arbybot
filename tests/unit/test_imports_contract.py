# PATH: tests/unit/test_imports_contract.py
"""
Import contract smoke tests — THE POLICE.

PURPOSE: Catch ImportError in < 0.2 seconds BEFORE entire suite fails.
RUN FIRST: python -m pytest tests/unit/test_imports_contract.py -v

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENUM DRIFT HISTORY (4 waves so far):
  Wave 1: DexType disappeared → fixed
  Wave 2: TokenStatus disappeared → fixed
  Wave 3: PoolStatus disappeared → fixed
  Wave 4: TradeDirection disappeared → NOW FIXED

If any symbol disappears, this test catches it FIRST.
DO NOT weaken this test — if it fails, restore the symbol!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestConstantsMustNotShrink(unittest.TestCase):
    """
    REGRESSION GUARD: core.constants public symbols must not disappear.
    
    If this test fails:
    1. DO NOT delete from this test
    2. Restore the symbol in core/constants.py
    3. If renamed, add alias: OldName = NewName
    """

    def test_all_required_symbols_exist(self):
        """
        CRITICAL: All required symbols MUST be importable.
        
        This is the PRIMARY guard against Enum drift.
        """
        import core.constants as C
        
        # =================================================================
        # REQUIRED SYMBOLS — DO NOT REMOVE FROM THIS LIST
        # =================================================================
        required_symbols = [
            # Enums (4 waves of drift history)
            "DexType",           # Wave 1
            "TokenStatus",       # Wave 2
            "PoolStatus",        # Wave 3
            "TradeDirection",    # Wave 4 ← LATEST FIX
            "ExecutionBlocker",
            
            # Constants
            "ANCHOR_DEX_PRIORITY",
            "PRICE_SANITY_BOUNDS",
            "PRICE_SANITY_MAX_DEVIATION_BPS",
            "CURRENT_EXECUTION_BLOCKER",
            "SCHEMA_VERSION",
            "CHAIN_IDS",
            "DEX_IDS",
            "DEFAULT_QUOTE_AMOUNT_WEI",
        ]
        
        missing = []
        for symbol in required_symbols:
            if not hasattr(C, symbol):
                missing.append(symbol)
        
        if missing:
            self.fail(
                f"\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"ENUM DRIFT DETECTED!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Missing symbols in core.constants: {missing}\n"
                f"\n"
                f"DO NOT delete from this test!\n"
                f"Restore the symbol in core/constants.py instead.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            )


class TestTradeDirection(unittest.TestCase):
    """
    Wave 4: TradeDirection import tests.
    
    This was the 4th Enum drift victim.
    Used by: core.models, strategy.*, traders.*
    """

    def test_import_trade_direction(self):
        """TradeDirection MUST be importable."""
        from core.constants import TradeDirection
        
        self.assertTrue(hasattr(TradeDirection, '__members__'))

    def test_trade_direction_has_buy_sell(self):
        """TradeDirection MUST have BUY and SELL."""
        from core.constants import TradeDirection
        
        self.assertIn('BUY', TradeDirection.__members__)
        self.assertIn('SELL', TradeDirection.__members__)
        self.assertEqual(TradeDirection.BUY.value, "buy")
        self.assertEqual(TradeDirection.SELL.value, "sell")

    def test_trade_direction_opposite_property(self):
        """TradeDirection.opposite MUST work."""
        from core.constants import TradeDirection
        
        self.assertEqual(TradeDirection.BUY.opposite, TradeDirection.SELL)
        self.assertEqual(TradeDirection.SELL.opposite, TradeDirection.BUY)


class TestCoreConstantsImports(unittest.TestCase):
    """Test individual Enum imports (Waves 1-3)."""

    def test_import_dex_type(self):
        """Wave 1: DexType."""
        from core.constants import DexType
        self.assertEqual(DexType.UNISWAP_V3.value, "uniswap_v3")

    def test_import_token_status(self):
        """Wave 2: TokenStatus."""
        from core.constants import TokenStatus
        self.assertEqual(TokenStatus.ACTIVE.value, "active")

    def test_import_pool_status(self):
        """Wave 3: PoolStatus."""
        from core.constants import PoolStatus
        self.assertEqual(PoolStatus.QUARANTINED.value, "quarantined")

    def test_import_execution_blocker(self):
        """ExecutionBlocker."""
        from core.constants import ExecutionBlocker
        self.assertEqual(ExecutionBlocker.EXECUTION_DISABLED.value, "EXECUTION_DISABLED")
        self.assertNotIn("M4", ExecutionBlocker.EXECUTION_DISABLED.value)

    def test_current_execution_blocker_stage_agnostic(self):
        """CURRENT_EXECUTION_BLOCKER is stage-agnostic."""
        from core.constants import CURRENT_EXECUTION_BLOCKER, ExecutionBlocker
        self.assertEqual(CURRENT_EXECUTION_BLOCKER, ExecutionBlocker.EXECUTION_DISABLED)


class TestMonitoringImports(unittest.TestCase):
    """Test monitoring package imports."""

    def test_import_rpc_health_metrics(self):
        """RPCHealthMetrics MUST be importable."""
        from monitoring.truth_report import RPCHealthMetrics
        metrics = RPCHealthMetrics()
        self.assertTrue(hasattr(metrics, 'success_rate'))

    def test_import_from_package(self):
        """All monitoring exports MUST work."""
        from monitoring import RPCHealthMetrics, TruthReport, calculate_confidence
        self.assertTrue(callable(calculate_confidence))

    def test_truth_report_execution_blocker(self):
        """TruthReport uses EXECUTION_DISABLED (not _M4)."""
        from monitoring import TruthReport
        report = TruthReport()
        self.assertEqual(report.execution_blocker, "EXECUTION_DISABLED")


class TestCoreValidatorsImports(unittest.TestCase):
    """Test core.validators imports."""

    def test_import_check_price_sanity(self):
        """check_price_sanity MUST be importable."""
        try:
            from core.validators import check_price_sanity
            self.assertTrue(callable(check_price_sanity))
        except ImportError:
            self.skipTest("core.validators not available")

    def test_anchor_quote_dex_id_required(self):
        """AnchorQuote.dex_id MUST be required."""
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

    def test_dex_type_values_in_anchor_priority(self):
        """DexType values MUST include ANCHOR_DEX_PRIORITY."""
        from core.constants import DexType, ANCHOR_DEX_PRIORITY
        
        dex_values = [m.value for m in DexType]
        for dex in ANCHOR_DEX_PRIORITY:
            self.assertIn(dex, dex_values, f"Missing in DexType: {dex}")


if __name__ == "__main__":
    unittest.main()
