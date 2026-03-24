# PATH: tests/unit/test_r39gplus_fixes.py
"""
R39g+ contract tests:
1. Aerodrome re-enabled in onboard_base_stage2.yaml
2. PRICE_SCALE per-pair majority logic (direction bug vs data quality)
3. SyncSwap ordered before iZiSwap on applicable chains
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import yaml


class TestAerodromeEnabled(unittest.TestCase):
    """Aerodrome must be in onboard_base_stage2.yaml dexes list."""

    def setUp(self):
        cfg_path = Path(__file__).parent.parent.parent / "config" / "onboard_base_stage2.yaml"
        with open(cfg_path) as f:
            self.config = yaml.safe_load(f)

    def test_aerodrome_in_dexes(self):
        """R39g+: aerodrome re-enabled after VE33_QUOTE_FAILED diagnosed as transient."""
        dexes = self.config.get("dexes", [])
        self.assertIn("aerodrome", dexes)

    def test_base_has_4_dexes(self):
        """Base stage2 should have 4 DEXes: uni_v3 + sushi_v3 + pancake_v3 + aerodrome."""
        dexes = self.config.get("dexes", [])
        self.assertEqual(len(dexes), 4)
        self.assertIn("uniswap_v3", dexes)
        self.assertIn("sushiswap_v3", dexes)
        self.assertIn("pancakeswap_v3", dexes)
        self.assertIn("aerodrome", dexes)


class TestPriceScalePerPairLogic(unittest.TestCase):
    """Per-pair PRICE_SCALE logic from R39g+."""

    def setUp(self):
        from scripts.ci_m5_0_gate import validate_price_scale
        self.validate = validate_price_scale

    def test_all_bad_single_pair_is_direction_bug(self):
        """If ALL quotes for a pair are outside bounds, it's a direction bug → FAIL."""
        data = {"quotes_sample": [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.0005"},
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.0006"},
        ]}
        ok, msg = self.validate(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("DIRECTION BUG", msg)

    def test_majority_good_with_outlier_passes(self):
        """If pair has good quotes, outlier bad quote is data quality → PASS."""
        data = {"quotes_sample": [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2100.0"},
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2150.0"},
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.01476"},
        ]}
        ok, msg = self.validate(data, require_real=True)
        self.assertTrue(ok)
        self.assertIn("WARN", msg)

    def test_one_good_enough_to_save_pair(self):
        """Even 1 good quote saves the pair from direction-bug classification."""
        data = {"quotes_sample": [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2100.0"},  # 1 good
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.01"},    # bad
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.02"},    # bad
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.03"},    # bad
        ]}
        ok, msg = self.validate(data, require_real=True)
        self.assertTrue(ok)

    def test_two_pairs_one_all_bad_fails(self):
        """If one pair has all bad quotes, entire validation fails."""
        data = {"quotes_sample": [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2100.0"},  # good
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.01"},    # bad outlier
            {"token_in": "ARB", "token_out": "USDC", "price_exact": "0.001"},    # bad, no good ARB/USDC
        ]}
        ok, msg = self.validate(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("ARB/USDC", msg)

    def test_no_bounded_pairs_passes(self):
        """Quotes for pairs not in PRICE_SCALE_BOUNDS → always pass."""
        data = {"quotes_sample": [
            {"token_in": "FOO", "token_out": "BAR", "price_exact": "999999.0"},
        ]}
        ok, msg = self.validate(data, require_real=True)
        self.assertTrue(ok)

    def test_empty_quotes_passes(self):
        data = {"quotes_sample": []}
        ok, msg = self.validate(data, require_real=True)
        self.assertTrue(ok)

    def test_no_price_field_skipped(self):
        """Quotes without price_exact/price are skipped."""
        data = {"quotes_sample": [
            {"token_in": "WETH", "token_out": "USDC"},
        ]}
        ok, msg = self.validate(data, require_real=True)
        self.assertTrue(ok)


class TestSyncSwapOrdering(unittest.TestCase):
    """SyncSwap must be ordered BEFORE iZiSwap in all applicable configs."""

    CONFIGS_WITH_BOTH = [
        "config/onboard_linea_stage1.yaml",
        "config/onboard_scroll_stage1.yaml",
        "config/onboard_zksync_candidate.yaml",
    ]

    def test_syncswap_before_iziswap(self):
        root = Path(__file__).parent.parent.parent
        for cfg_name in self.CONFIGS_WITH_BOTH:
            cfg_path = root / cfg_name
            if not cfg_path.exists():
                continue
            with open(cfg_path) as f:
                cfg = yaml.safe_load(f)
            dexes = cfg.get("dexes", [])
            syncswap_keys = [d for d in dexes if "syncswap" in d]
            iziswap_keys = [d for d in dexes if "iziswap" in d]
            if syncswap_keys and iziswap_keys:
                sync_idx = dexes.index(syncswap_keys[0])
                izi_idx = dexes.index(iziswap_keys[0])
                self.assertLess(
                    sync_idx, izi_idx,
                    f"{cfg_name}: syncswap at {sync_idx}, iziswap at {izi_idx}"
                )


if __name__ == "__main__":
    unittest.main()
