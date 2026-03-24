# PATH: tests/unit/test_base_profit_contracts.py
"""
R39n contract tests for the Base profit-lane patch set.

Tests:
1. ve33 executable reprieve allowed
2. Alpha routes prioritized over calibration
3. 429 on Base alpha route — failover / no slot0 truth contamination
4. Base profit config keeps merged anchors
"""

import os
from unittest.mock import patch, MagicMock

import yaml

from core.constants import EXECUTABLE_QUOTE_SOURCES, get_pair_role, PAIR_ROLES

# Tests that touch RPC code need ARBY_SKIP_RPC=0 (conftest sets it to "1")
_SKIP_RPC_OFF = {"ARBY_SKIP_RPC": "0"}


# ============================================================================
# 1. ve33 executable reprieve allowed
# ============================================================================

class TestVe33ExecutableReprieve:
    """ve33_getAmountOut routes must pass the sweep reprieve executable gate."""

    def test_ve33_in_executable_sources(self):
        assert "ve33_getAmountOut" in EXECUTABLE_QUOTE_SOURCES

    def test_ve33_route_passes_reprieve(self):
        from strategy.roundtrip_selection import select_sweep_reprieve_candidates

        opps = [
            {
                "pair": "AERO/USDC",
                "buy_dex": "aerodrome",
                "sell_dex": "uniswap_v3",
                "buy_fee": 500,
                "sell_fee": 500,
                "gross_spread_bps": 15.0,
                "gate_passed": False,
                "reject_reason": "NET_PROFIT_TOO_LOW: -0.05 < 0.50",
                "buy_quote_source": "ve33_getAmountOut",
                "sell_quote_source": "quoter_v2",
            },
        ]
        result, stats = select_sweep_reprieve_candidates(opps)
        assert len(result) == 1, "ve33_getAmountOut route must be reprieve-eligible"
        assert result[0]["pair"] == "AERO/USDC"

    def test_slot0_route_rejected_by_reprieve(self):
        from strategy.roundtrip_selection import select_sweep_reprieve_candidates

        opps = [
            {
                "pair": "WETH/USDC",
                "buy_dex": "aerodrome",
                "sell_dex": "uniswap_v3",
                "buy_fee": 500,
                "sell_fee": 500,
                "gross_spread_bps": 15.0,
                "gate_passed": False,
                "reject_reason": "NET_PROFIT_TOO_LOW: -0.05 < 0.50",
                "buy_quote_source": "slot0",
                "sell_quote_source": "quoter_v2",
            },
        ]
        result, _ = select_sweep_reprieve_candidates(opps)
        assert len(result) == 0, "slot0 route must NOT pass reprieve gate"


# ============================================================================
# 2. Alpha routes prioritized over calibration
# ============================================================================

class TestAlphaFirstOrdering:
    """Alpha pairs must be evaluated before benchmark/calibration."""

    def test_alpha_before_calibration(self):
        from strategy.roundtrip_selection import select_roundtrip_candidates

        opps = [
            {
                "pair": "USDC/DAI",  # calibration
                "buy_dex": "uniswap_v3",
                "sell_dex": "sushiswap_v3",
                "buy_fee": 500,
                "sell_fee": 500,
                "gross_spread_bps": 20.0,
                "spread_minus_required_bps": 5.0,
            },
            {
                "pair": "cbBTC/USDC",  # alpha on base
                "buy_dex": "uniswap_v3",
                "sell_dex": "aerodrome",
                "buy_fee": 500,
                "sell_fee": 500,
                "gross_spread_bps": 18.0,
                "spread_minus_required_bps": 3.0,
            },
            {
                "pair": "WETH/USDC",  # benchmark on base
                "buy_dex": "uniswap_v3",
                "sell_dex": "pancakeswap_v3",
                "buy_fee": 500,
                "sell_fee": 500,
                "gross_spread_bps": 19.0,
                "spread_minus_required_bps": 4.0,
            },
        ]
        eligible, stats = select_roundtrip_candidates(opps, chain="base")
        assert len(eligible) == 3
        # Alpha first, then benchmark, then calibration
        assert eligible[0]["pair"] == "cbBTC/USDC", "Alpha pair must be first"
        assert eligible[1]["pair"] == "WETH/USDC", "Benchmark pair second"
        assert eligible[2]["pair"] == "USDC/DAI", "Calibration pair last"

    def test_no_chain_no_reorder(self):
        """Without chain parameter, ordering is by margin (existing behavior)."""
        from strategy.roundtrip_selection import select_roundtrip_candidates

        opps = [
            {
                "pair": "USDC/DAI",
                "buy_dex": "uniswap_v3",
                "sell_dex": "sushiswap_v3",
                "buy_fee": 500,
                "sell_fee": 500,
                "gross_spread_bps": 20.0,
                "spread_minus_required_bps": 10.0,
            },
            {
                "pair": "cbBTC/USDC",
                "buy_dex": "uniswap_v3",
                "sell_dex": "aerodrome",
                "buy_fee": 500,
                "sell_fee": 500,
                "gross_spread_bps": 18.0,
                "spread_minus_required_bps": 3.0,
            },
        ]
        eligible, _ = select_roundtrip_candidates(opps, chain="")
        # Without chain, best_per_pair sorts by margin desc — USDC/DAI has higher margin
        assert eligible[0]["pair"] == "USDC/DAI"

    def test_pair_roles_classification(self):
        """Verify PAIR_ROLES contains expected alpha classifications."""
        assert get_pair_role("base", "cbBTC/USDC") == "alpha"
        assert get_pair_role("base", "cbBTC/WETH") == "alpha"
        assert get_pair_role("base", "AERO/USDC") == "alpha"
        assert get_pair_role("base", "WETH/USDC") == "benchmark"
        assert get_pair_role("arbitrum_one", "WETH/USDC") == "benchmark"
        assert get_pair_role("base", "USDC/DAI") == "calibration"


# ============================================================================
# 3. 429 on Base alpha route — failover / no slot0 truth contamination
# ============================================================================

class TestQuoterV2Failover:
    """QuoterV2 429 failover with fallback RPCs and alpha slot0 suppression."""

    @patch.dict(os.environ, _SKIP_RPC_OFF)
    def test_read_quoter_v2_tries_fallback_on_429(self):
        """When primary RPC 429s, should try fallback RPC before giving up."""
        from strategy.quote_rpc import read_quoter_v2, QUOTER_RATE_LIMITED

        call_count = {"n": 0}

        def mock_eth_call(tx, block_identifier=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: 429
                raise Exception("429 Too Many Requests")
            # Second call: success (minimal valid QuoterV2 response)
            # 4 x 32-byte words: amount_out, sqrtPriceAfter, ticksCrossed, gasEstimate
            return bytes.fromhex(
                "0000000000000000000000000000000000000000000000000000000000000064"  # amount_out=100
                "0000000000000000000000000000000000000000000000000000000000000001"  # sqrtPriceAfter=1
                "0000000000000000000000000000000000000000000000000000000000000001"  # ticksCrossed=1
                "0000000000000000000000000000000000000000000000000000000000030d40"  # gasEstimate=200000
            )

        mock_w3 = MagicMock()
        mock_w3.eth.call = mock_eth_call

        with patch("strategy.quote_rpc._get_shared_w3", return_value=mock_w3), \
             patch("strategy.quote_rpc._is_rate_limit_error", side_effect=lambda e: "429" in str(e)):
            result = read_quoter_v2(
                quoter_address="0x" + "ab" * 20,
                token_in="0x" + "01" * 20,
                token_out="0x" + "02" * 20,
                amount_in=1000000,
                fee=500,
                rpc_url="https://primary.rpc",
                block_num=12345,
                fallback_rpc_urls=["https://fallback.rpc"],
            )

        assert result is not QUOTER_RATE_LIMITED, "Should succeed on fallback RPC"
        assert result is not None
        assert result["amount_out"] == 100
        assert call_count["n"] == 2

    @patch.dict(os.environ, _SKIP_RPC_OFF)
    def test_read_quoter_v2_all_rpcs_rate_limited(self):
        """When all RPCs return 429, should return QUOTER_RATE_LIMITED."""
        from strategy.quote_rpc import read_quoter_v2, QUOTER_RATE_LIMITED

        def mock_eth_call(tx, block_identifier=None):
            raise Exception("429 Too Many Requests")

        mock_w3 = MagicMock()
        mock_w3.eth.call = mock_eth_call

        with patch("strategy.quote_rpc._get_shared_w3", return_value=mock_w3), \
             patch("strategy.quote_rpc._is_rate_limit_error", return_value=True):
            result = read_quoter_v2(
                quoter_address="0x" + "ab" * 20,
                token_in="0x" + "01" * 20,
                token_out="0x" + "02" * 20,
                amount_in=1000000,
                fee=500,
                rpc_url="https://primary.rpc",
                block_num=12345,
                fallback_rpc_urls=["https://fallback1.rpc", "https://fallback2.rpc"],
            )

        assert result is QUOTER_RATE_LIMITED


# ============================================================================
# 4. Base profit config keeps merged anchors
# ============================================================================

class TestBaseProfitConfig:
    """config/onboard_base_profit.yaml must load with correct merged anchors."""

    def test_config_loads_valid_yaml(self):
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "onboard_base_profit.yaml"
        )
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        assert cfg["chain"] == "base"
        assert cfg["chain_id"] == 8453

    def test_merged_anchor_block(self):
        """All anchors must be in a SINGLE tokens_anchor_price block (no duplicate YAML keys)."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "onboard_base_profit.yaml"
        )
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        anchors = cfg.get("tokens_anchor_price", {})
        # Must have all expected anchors including alpha pairs
        assert "cbBTC_USDC" in anchors, "cbBTC_USDC anchor missing"
        assert "cbBTC_WETH" in anchors, "cbBTC_WETH anchor missing"
        assert "AERO_USDC" in anchors, "AERO_USDC anchor missing"
        assert "WETH_USDC" in anchors, "WETH_USDC anchor missing"
        # Verify anchor values are plausible
        assert anchors["cbBTC_USDC"] > 10000, "cbBTC price too low"
        assert anchors["AERO_USDC"] < 10, "AERO price too high"

    def test_narrow_sweep_sizes(self):
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "onboard_base_profit.yaml"
        )
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        sizes = cfg["dynamic_probe"]["sizes_usd"]
        assert sizes == [25, 50, 75, 100, 150, 250], "Sweep sizes must be narrow corridor"
        assert max(sizes) <= 250, "Max size must not exceed 250 for profit lane"

    def test_include_pairs_contour(self):
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "onboard_base_profit.yaml"
        )
        with open(config_path, "r") as f:
            cfg = yaml.safe_load(f)
        pairs = cfg.get("include_pairs", [])
        assert len(pairs) == 6
        assert "cbBTC/USDC" in pairs
        assert "cbBTC/WETH" in pairs
        assert "AERO/USDC" in pairs

    def test_no_duplicate_yaml_keys(self):
        """Ensure tokens_anchor_price appears exactly once in the raw YAML."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "onboard_base_profit.yaml"
        )
        with open(config_path, "r") as f:
            content = f.read()
        # Count top-level occurrences of tokens_anchor_price:
        import re
        matches = re.findall(r"^tokens_anchor_price:", content, re.MULTILINE)
        assert len(matches) == 1, f"tokens_anchor_price must appear exactly once, found {len(matches)}"
