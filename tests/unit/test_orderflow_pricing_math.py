"""
PRICING_MATH tests for M7 orderflow.

Test categories covered:
- Normalized bounds per-decimals
- Size normalization contract
- V3 swap math (compute_v3_swap_amount_out)
- V2 swap math (compute_v2_swap_amount_out)
- Algebra/Camelot swap math (compute_algebra_swap_amount_out)
- attempt_local_pricing orchestrator
- Adapter dispatch (V3/V2/Algebra)
"""
from __future__ import annotations

from m7.orderflow.pricing import _normalized_bounds
from m7.orderflow.v3_math import (
    attempt_local_pricing,
    compute_algebra_swap_amount_out,
    compute_v2_swap_amount_out,
    compute_v3_swap_amount_out,
)
from m7.orderflow.pool_registry import PoolRegistryEntry
from m7.shared.constants import _REF_MAX_WEI_18, _REF_MIN_WEI_18

from tests.unit.conftest import _make_event, _make_result


# ---------------------------------------------------------------------------
# 1. Normalized bounds (_normalized_bounds per-decimals)
# ---------------------------------------------------------------------------
class TestNormalizedBounds:
    """_normalized_bounds returns decimal-adjusted min/max."""

    def test_18_dec_identity(self):
        mn, mx = _normalized_bounds(18)
        assert mn == _REF_MIN_WEI_18
        assert mx == _REF_MAX_WEI_18

    def test_none_dec_fallback(self):
        mn, mx = _normalized_bounds(None)
        assert mn == _REF_MIN_WEI_18
        assert mx == _REF_MAX_WEI_18

    def test_6_dec_usdc(self):
        mn, mx = _normalized_bounds(6)
        assert mn == 10**3, f"min should be 10^3 for 6-dec, got {mn}"
        assert mx == 10**6, f"max should be 10^6 for 6-dec, got {mx}"

    def test_8_dec_wbtc(self):
        mn, mx = _normalized_bounds(8)
        assert mn == 10**5
        assert mx == 10**8

    def test_min_is_at_least_1(self):
        mn, mx = _normalized_bounds(1)
        assert mn >= 1
        assert mx >= 1

    def test_6_dec_far_smaller_than_18_dec(self):
        mn6, mx6 = _normalized_bounds(6)
        mn18, mx18 = _normalized_bounds(18)
        assert mn18 / mn6 == 10**12
        assert mx18 / mx6 == 10**12

    def test_custom_reference_bounds(self):
        mn, mx = _normalized_bounds(6, default_18_min=10**16, default_18_max=10**19)
        assert mn == 10**4
        assert mx == 10**7

    def test_all_common_decimals_positive(self):
        for dec in [0, 2, 4, 6, 8, 12, 18]:
            mn, mx = _normalized_bounds(dec)
            assert mn >= 1, f"min<1 for decimals={dec}"
            assert mx >= mn, f"max<min for decimals={dec}"

    def test_same_usd_comparable_units(self):
        mn6, mx6 = _normalized_bounds(6)
        mn18, mx18 = _normalized_bounds(18)
        assert mn6 < 10**6
        assert mx6 == 10**6
        assert mn18 < 10**18
        assert mx18 == 10**18


# ---------------------------------------------------------------------------
# 2. Size normalization contract
# ---------------------------------------------------------------------------
class TestSizeNormalizationContract:
    """Bounded size clamp must use _normalized_bounds for the token."""

    def test_usdc_event_not_clamped_to_weth_min(self):
        event_amount_usdc = 5000 * 10**6
        raw_size = max(event_amount_usdc // 10, 1)
        mn, mx = _normalized_bounds(6)
        bounded = max(mn, min(mx, raw_size))
        assert bounded == mx
        assert bounded < 10**15

    def test_weth_event_normal_range(self):
        event_amount_weth = 10**18
        raw_size = max(event_amount_weth // 10, 1)
        mn, mx = _normalized_bounds(18)
        bounded = max(mn, min(mx, raw_size))
        assert bounded == 10**17

    def test_usdt_6_dec_same_as_usdc(self):
        mn_usdc, mx_usdc = _normalized_bounds(6)
        mn_usdt, mx_usdt = _normalized_bounds(6)
        assert mn_usdc == mn_usdt
        assert mx_usdc == mx_usdt

    def test_wbtc_8_dec_reasonable(self):
        mn, mx = _normalized_bounds(8)
        assert mn == 10**5
        assert mx == 10**8


# ---------------------------------------------------------------------------
# 3. V3 swap math
# ---------------------------------------------------------------------------
class TestV3SwapMath:
    """compute_v3_swap_amount_out: single-tick V3 swap math."""

    SQRT_PRICE = 4685413736498040635278359 * (10**15)
    LIQUIDITY = 10**18
    FEE_500 = 500
    FEE_3000 = 3000

    def test_zero_for_one_positive_output(self):
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=self.SQRT_PRICE, liquidity=self.LIQUIDITY,
            amount_in=10**15, fee_pips=self.FEE_500, zero_for_one=True,
        )
        assert out is not None
        assert out > 0

    def test_one_for_zero_positive_output(self):
        Q96 = 1 << 96
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=Q96, liquidity=10**20,
            amount_in=10**15, fee_pips=self.FEE_500, zero_for_one=False,
        )
        assert out is not None
        assert out > 0

    def test_higher_fee_less_output(self):
        out_low = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_500, True,
        )
        out_high = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_3000, True,
        )
        assert out_low is not None and out_high is not None
        assert out_low > out_high

    def test_zero_liquidity_returns_none(self):
        out = compute_v3_swap_amount_out(self.SQRT_PRICE, 0, 10**15, self.FEE_500, True)
        assert out is None

    def test_zero_amount_in_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 0, self.FEE_500, True,
        )
        assert out is None

    def test_zero_sqrt_price_returns_none(self):
        out = compute_v3_swap_amount_out(0, self.LIQUIDITY, 10**15, self.FEE_500, True)
        assert out is None

    def test_negative_amount_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, -1, self.FEE_500, True,
        )
        assert out is None

    def test_fee_100_percent_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, 1_000_000, True,
        )
        assert out is None

    def test_larger_input_more_output(self):
        out_small = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**14, self.FEE_500, True,
        )
        out_large = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_500, True,
        )
        assert out_small is not None and out_large is not None
        assert out_large > out_small

    def test_output_less_than_input_for_equal_token_price(self):
        Q96 = 1 << 96
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=Q96, liquidity=10**20,
            amount_in=10**15, fee_pips=3000, zero_for_one=True,
        )
        assert out is not None
        assert out < 10**15


# ---------------------------------------------------------------------------
# 4. V2 swap math
# ---------------------------------------------------------------------------
class TestV2SwapMath:
    """compute_v2_swap_amount_out: constant-product swap math."""

    def test_basic_swap(self):
        out = compute_v2_swap_amount_out(
            reserve_in=10**18, reserve_out=10**18, amount_in=10**15,
        )
        assert out is not None
        assert out > 0
        assert out < 10**15

    def test_zero_reserves_returns_none(self):
        assert compute_v2_swap_amount_out(0, 10**18, 10**15) is None
        assert compute_v2_swap_amount_out(10**18, 0, 10**15) is None

    def test_zero_amount_returns_none(self):
        assert compute_v2_swap_amount_out(10**18, 10**18, 0) is None

    def test_larger_reserve_out_more_output(self):
        out_small = compute_v2_swap_amount_out(10**18, 10**17, 10**15)
        out_large = compute_v2_swap_amount_out(10**18, 10**19, 10**15)
        assert out_small is not None and out_large is not None
        assert out_large > out_small

    def test_fee_affects_output(self):
        out_low_fee = compute_v2_swap_amount_out(10**18, 10**18, 10**15, 999, 1000)
        out_high_fee = compute_v2_swap_amount_out(10**18, 10**18, 10**15, 990, 1000)
        assert out_low_fee is not None and out_high_fee is not None
        assert out_low_fee > out_high_fee


# ---------------------------------------------------------------------------
# 5. Algebra/Camelot swap math
# ---------------------------------------------------------------------------
class TestAlgebraSwapMath:
    """compute_algebra_swap_amount_out: Algebra/Camelot V3 swap math."""

    Q96 = 1 << 96

    def test_algebra_swap_zero_for_one(self):
        out = compute_algebra_swap_amount_out(
            sqrt_price_x96=self.Q96, liquidity=10**20, amount_in=10**15,
            fee_zto=500, fee_otz=3000, zero_for_one=True,
        )
        assert out is not None
        assert out > 0

    def test_algebra_swap_one_for_zero(self):
        out = compute_algebra_swap_amount_out(
            sqrt_price_x96=self.Q96, liquidity=10**20, amount_in=10**15,
            fee_zto=500, fee_otz=3000, zero_for_one=False,
        )
        assert out is not None
        assert out > 0

    def test_algebra_uses_direction_specific_fee(self):
        out_zto = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15, fee_zto=500, fee_otz=3000, zero_for_one=True,
        )
        out_otz = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15, fee_zto=500, fee_otz=3000, zero_for_one=False,
        )
        assert out_zto is not None and out_otz is not None
        assert out_zto > out_otz

    def test_algebra_zero_liquidity_none(self):
        out = compute_algebra_swap_amount_out(self.Q96, 0, 10**15, 500, 3000, True)
        assert out is None

    def test_algebra_zero_amount_none(self):
        out = compute_algebra_swap_amount_out(self.Q96, 10**20, 0, 500, 3000, True)
        assert out is None

    def test_algebra_matches_v3_when_same_fee(self):
        fee = 3000
        v3_out = compute_v3_swap_amount_out(self.Q96, 10**20, 10**15, fee, True)
        algebra_out = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15, fee_zto=fee, fee_otz=fee, zero_for_one=True,
        )
        assert v3_out == algebra_out


# ---------------------------------------------------------------------------
# 6. attempt_local_pricing orchestrator
# ---------------------------------------------------------------------------
class TestAttemptLocalPricing:
    """attempt_local_pricing: orchestrates local-state pricing across pools."""

    POOL_A = "0x" + "aa" * 20
    POOL_B = "0x" + "bb" * 20
    TOKEN_IN = "0x" + "11" * 20
    TOKEN_OUT = "0x" + "ff" * 20
    Q96 = 1 << 96

    def _make_candidate_pools(self):
        return [
            {"address": self.POOL_A, "fee": 500, "dex": "uniswap_v3", "liquidity": 10**18},
            {"address": self.POOL_B, "fee": 3000, "dex": "sushiswap_v3", "liquidity": 10**18},
        ]

    def _make_pool_states(self):
        return {
            self.POOL_A: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
            self.POOL_B: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
        }

    def test_successful_local_pricing(self):
        result = attempt_local_pricing(
            candidate_pools=self._make_candidate_pools(),
            local_sim_states=self._make_pool_states(),
            token_in_addr=self.TOKEN_IN,
            token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is not None
        assert result["buy_amount"] > 0
        assert result["sell_amount"] > 0
        assert result["pricing_path"] == "v3_local"
        assert result["pools_attempted"] >= 1
        assert result["pools_succeeded"] >= 1

    def test_empty_pools_returns_none(self):
        result = attempt_local_pricing(
            candidate_pools=[], local_sim_states={},
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_zero_liquidity_returns_none(self):
        pools = [{"address": self.POOL_A, "fee": 500, "liquidity": 0}]
        states = {self.POOL_A: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 0}}
        result = attempt_local_pricing(
            candidate_pools=pools, local_sim_states=states,
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_no_matching_state_returns_none(self):
        pools = self._make_candidate_pools()
        result = attempt_local_pricing(
            candidate_pools=pools, local_sim_states={},
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_picks_best_buy_venue(self):
        pools = self._make_candidate_pools()
        states = self._make_pool_states()
        result = attempt_local_pricing(
            candidate_pools=pools, local_sim_states=states,
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is not None
        assert result["buy_fee"] == 500


# ---------------------------------------------------------------------------
# 7. Adapter dispatch (V3/V2/Algebra)
# ---------------------------------------------------------------------------
class TestAdapterDispatchLocalPricing:
    """attempt_local_pricing: V3/V2/Algebra adapter dispatch."""

    POOL_V3 = "0x" + "a1" * 20
    POOL_V2 = "0x" + "b2" * 20
    POOL_ALG = "0x" + "c3" * 20
    TOKEN_IN = "0x" + "11" * 20
    TOKEN_OUT = "0x" + "ff" * 20
    Q96 = 1 << 96

    def test_v3_adapter_default(self):
        pools = [{"address": self.POOL_V3, "fee": 500}]
        states = {self.POOL_V3: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18}}
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
        )
        assert result is not None
        assert result["pricing_path"] == "v3_local"

    def test_v2_adapter_dispatch(self):
        pools = [{"address": self.POOL_V2, "fee": 3}]
        states = {self.POOL_V2: {"sqrt_price_x96": 10**18, "tick": 10**18, "liquidity": 0}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_V2, dex="sushiswap_v2",
                adapter_type="uniswap_v2", fee=3,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["pricing_path"] == "v2_local"

    def test_algebra_adapter_dispatch(self):
        pools = [{"address": self.POOL_ALG, "fee": 3000}]
        states = {self.POOL_ALG: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_ALG, dex="camelot_v3",
                adapter_type="algebra", fee=3000,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["pricing_path"] == "algebra_local"

    def test_backward_compatible_without_registry(self):
        pools = [
            {"address": self.POOL_V3, "fee": 500},
            {"address": self.POOL_V2, "fee": 3000},
        ]
        states = {
            self.POOL_V3: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
            self.POOL_V2: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
        }
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
        )
        assert result is not None
        assert result["pricing_path"] == "v3_local"

    def test_sell_pass_uses_adapter_dispatch(self):
        pools = [{"address": self.POOL_V2, "fee": 3}]
        states = {self.POOL_V2: {"sqrt_price_x96": 10**18, "tick": 10**18, "liquidity": 0}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_V2, dex="sushiswap_v2",
                adapter_type="uniswap_v2", fee=3,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["sell_amount"] > 0
