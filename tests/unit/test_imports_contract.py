# PATH: tests/unit/test_imports_contract.py
"""
Import contract smoke tests — THE POLICE.

PURPOSE: Catch ImportError in < 0.2 seconds BEFORE entire suite fails.
RUN FIRST: python -m pytest tests/unit/test_imports_contract.py -v

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENUM DRIFT HISTORY:
  Wave 1: DexType disappeared → fixed
  Wave 2: TokenStatus disappeared → fixed
  Wave 3: PoolStatus disappeared → fixed
  Wave 4: TradeDirection disappeared → fixed
  Wave 5: TradeStatus/OpportunityStatus/TradeOutcome missing → NOW FIXED

If any symbol disappears, this test catches it FIRST.
DO NOT weaken this test — if it fails, restore the symbol!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# =============================================================================
# REQUIRED SYMBOLS WHITELIST - DO NOT REMOVE FROM THIS LIST
# =============================================================================

REQUIRED_CONSTANTS_SYMBOLS = [
    # Enums (Waves 1-4)
    "DexType",
    "TokenStatus",
    "PoolStatus",
    "TradeDirection",
    
    # Enums (Wave 5)
    "TradeStatus",
    "OpportunityStatus",
    "TradeOutcome",
    
    # Blockers
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

REQUIRED_VALIDATORS_SYMBOLS = [
    "MAX_DEVIATION_BPS_CAP",
    "calculate_deviation_bps",
    "normalize_price",
    "AnchorQuote",
    "select_anchor",
    "check_price_sanity",
]


class TestConstantsMustNotShrink(unittest.TestCase):
    """
    REGRESSION GUARD: core.constants public symbols must not disappear.
    """

    def test_all_required_symbols_exist(self):
        """CRITICAL: All required symbols MUST be importable."""
        import core.constants as C
        
        missing = []
        for symbol in REQUIRED_CONSTANTS_SYMBOLS:
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


class TestValidatorsMustNotShrink(unittest.TestCase):
    """REGRESSION GUARD: core.validators public symbols must not disappear."""

    def test_all_required_symbols_exist(self):
        """CRITICAL: All required symbols MUST be importable."""
        import core.validators as V
        
        missing = []
        for symbol in REQUIRED_VALIDATORS_SYMBOLS:
            if not hasattr(V, symbol):
                missing.append(symbol)
        
        if missing:
            self.fail(
                f"\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"VALIDATORS API DRIFT DETECTED!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Missing symbols in core.validators: {missing}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            )


class TestWave5Enums(unittest.TestCase):
    """Wave 5: TradeStatus, OpportunityStatus, TradeOutcome."""

    def test_trade_status_import(self):
        """TradeStatus MUST be importable."""
        from core.constants import TradeStatus
        
        self.assertTrue(hasattr(TradeStatus, '__members__'))
        required = ['PENDING', 'SUBMITTED', 'MINED', 'FAILED', 'CANCELLED']
        for member in required:
            self.assertIn(member, TradeStatus.__members__)

    def test_opportunity_status_import(self):
        """OpportunityStatus MUST be importable."""
        from core.constants import OpportunityStatus
        
        required = ['NEW', 'VALID', 'REJECTED', 'EXECUTABLE', 'EXECUTED', 'EXPIRED']
        for member in required:
            self.assertIn(member, OpportunityStatus.__members__)

    def test_trade_outcome_import(self):
        """TradeOutcome MUST be importable."""
        from core.constants import TradeOutcome
        
        required = ['WOULD_EXECUTE', 'EXECUTED', 'BLOCKED_EXEC', 'COOLDOWN', 'FAILED', 'REJECTED']
        for member in required:
            self.assertIn(member, TradeOutcome.__members__)


class TestWave1to4Enums(unittest.TestCase):
    """Test Waves 1-4 enums."""

    def test_dex_type(self):
        from core.constants import DexType
        self.assertEqual(DexType.UNISWAP_V3.value, "uniswap_v3")

    def test_token_status(self):
        from core.constants import TokenStatus
        self.assertEqual(TokenStatus.ACTIVE.value, "active")

    def test_pool_status(self):
        from core.constants import PoolStatus
        self.assertEqual(PoolStatus.QUARANTINED.value, "quarantined")

    def test_trade_direction(self):
        from core.constants import TradeDirection
        self.assertEqual(TradeDirection.BUY.value, "buy")
        self.assertEqual(TradeDirection.BUY.opposite, TradeDirection.SELL)

    def test_execution_blocker(self):
        from core.constants import ExecutionBlocker, CURRENT_EXECUTION_BLOCKER
        self.assertEqual(ExecutionBlocker.EXECUTION_DISABLED.value, "EXECUTION_DISABLED")
        self.assertEqual(CURRENT_EXECUTION_BLOCKER, ExecutionBlocker.EXECUTION_DISABLED)


class TestValidatorsAPI(unittest.TestCase):
    """Test core.validators API contracts."""

    def test_max_deviation_cap_is_10000(self):
        """MAX_DEVIATION_BPS_CAP MUST be 10000."""
        from core.validators import MAX_DEVIATION_BPS_CAP
        self.assertEqual(MAX_DEVIATION_BPS_CAP, 10000)

    def test_calculate_deviation_5_percent_is_500_bps(self):
        """5% deviation MUST be exactly 500 bps (Decimal math)."""
        from core.validators import calculate_deviation_bps
        from decimal import Decimal
        
        dev, raw, capped = calculate_deviation_bps(Decimal("105"), Decimal("100"))
        self.assertEqual(dev, 500, "5% deviation should be exactly 500 bps")
        self.assertEqual(raw, 500)
        self.assertFalse(capped)

    def test_calculate_deviation_capping_to_10000(self):
        """Large deviation MUST be capped to 10000."""
        from core.validators import calculate_deviation_bps, MAX_DEVIATION_BPS_CAP
        from decimal import Decimal
        
        # 200% deviation = 20000 bps, should cap to 10000
        dev, raw, capped = calculate_deviation_bps(Decimal("300"), Decimal("100"))
        self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)
        self.assertEqual(raw, 20000)
        self.assertTrue(capped)

    def test_normalize_price_inversion_always_false(self):
        """normalize_price MUST have inversion_applied=False."""
        from core.validators import normalize_price
        
        price, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        self.assertEqual(diag["inversion_applied"], False)
        self.assertIn("suspect_quote", diag)

    def test_anchor_quote_dex_id_required(self):
        """AnchorQuote.dex_id MUST be required."""
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

    def test_check_price_sanity_accepts_anchor_source(self):
        """check_price_sanity MUST accept anchor_source parameter."""
        from core.validators import check_price_sanity
        from decimal import Decimal
        
        passed, dev, err, diag = check_price_sanity(
            price=Decimal("2600"),
            anchor_price=Decimal("2600"),
            pair="WETH/USDC",
            dex_id="uniswap_v3",
            anchor_source="test_source",
        )
        self.assertTrue(passed)
        self.assertEqual(diag.get("anchor_source"), "test_source")

    def test_check_price_sanity_deviation_capped_flag(self):
        """check_price_sanity diag MUST include deviation_bps_capped."""
        from core.validators import check_price_sanity
        from decimal import Decimal
        
        # Large deviation that should be capped
        passed, dev, err, diag = check_price_sanity(
            price=Decimal("8000"),
            anchor_price=Decimal("2600"),
            pair="WETH/USDC",
            dex_id="sushiswap_v3",
            max_deviation_bps=5000,
        )
        self.assertIn("deviation_bps_capped", diag)


class TestMonitoringImports(unittest.TestCase):
    """Test monitoring package imports."""

    def test_rpc_health_metrics(self):
        from monitoring.truth_report import RPCHealthMetrics
        metrics = RPCHealthMetrics()
        self.assertTrue(hasattr(metrics, 'success_rate'))

    def test_truth_report(self):
        from monitoring import TruthReport
        report = TruthReport()
        self.assertEqual(report.execution_blocker, "EXECUTION_DISABLED")


class TestCrossModuleCompat(unittest.TestCase):
    """Test cross-module compatibility."""

    def test_dex_type_values_in_anchor_priority(self):
        from core.constants import DexType, ANCHOR_DEX_PRIORITY
        
        dex_values = [m.value for m in DexType]
        for dex in ANCHOR_DEX_PRIORITY:
            self.assertIn(dex, dex_values, f"Missing in DexType: {dex}")


if __name__ == "__main__":
    unittest.main()
