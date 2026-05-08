from m7.orderflow.scoring_parallel import (
    _quote_implied_size_usd,
    _usd_target_rescaled_size_wei,
)


def test_quote_implied_size_usd_from_weth_output_and_live_eth_price():
    usd = _quote_implied_size_usd(
        amount_in_wei=1_000_000_000_000_000_000,
        decimals_in=18,
        symbol_in="B3",
        amount_out_wei=25_000_000_000_000_000,
        decimals_out=18,
        symbol_out="WETH",
        eth_price_usd=3200.0,
    )
    assert usd == 80.0


def test_quote_implied_size_usd_does_not_hardcode_eth_price():
    usd = _quote_implied_size_usd(
        amount_in_wei=1_000_000_000_000_000_000,
        decimals_in=18,
        symbol_in="B3",
        amount_out_wei=25_000_000_000_000_000,
        decimals_out=18,
        symbol_out="WETH",
        eth_price_usd=None,
    )
    assert usd is None


def test_quote_implied_size_usd_from_stable_input_anchor():
    usd = _quote_implied_size_usd(
        amount_in_wei=1_500_000,
        decimals_in=6,
        symbol_in="USDC",
        amount_out_wei=None,
        decimals_out=None,
        symbol_out="WETH",
        eth_price_usd=None,
    )
    assert usd == 1.5


def test_usd_target_rescaled_size_wei_scales_low_price_token():
    new_size = _usd_target_rescaled_size_wei(
        amount_in_wei=10**18,
        current_size_usd=0.0005,
        target_usd=10.0,
        max_scale=100000.0,
    )
    assert new_size == 20_000 * 10**18


def test_usd_target_rescaled_size_wei_is_off_without_target():
    new_size = _usd_target_rescaled_size_wei(
        amount_in_wei=10**18,
        current_size_usd=0.0005,
        target_usd=0.0,
    )
    assert new_size is None


def test_usd_target_rescaled_size_wei_respects_max_scale():
    new_size = _usd_target_rescaled_size_wei(
        amount_in_wei=10**18,
        current_size_usd=0.0005,
        target_usd=10.0,
        max_scale=1000.0,
    )
    assert new_size == 1000 * 10**18


# E1.65 fix step 4/7: stable-coin decimal override tests
def test_quote_implied_size_usd_usdc_output_cache_miss_dec_none():
    """FUN/USDC: buy_amount=1000 USDC-raw (6dec), dec_out=None (cache miss).
    Old code: round(1000 / 10^18, 6) = 0.0.  Fixed: use STABLE_DEC_OVERRIDE → 6.
    """
    usd = _quote_implied_size_usd(
        amount_in_wei=1_000_000_000_000_000_000,
        decimals_in=18,
        symbol_in="FUN",
        amount_out_wei=1000,
        decimals_out=None,        # cache miss → must use override
        symbol_out="USDC",
        eth_price_usd=None,
    )
    # 1000 / 10^6 = 0.001 USDC
    assert usd == 0.001


def test_quote_implied_size_usd_usdc_output_correct_dec():
    """FUN/USDC: dec_out=6 (from cache) must still work unchanged."""
    usd = _quote_implied_size_usd(
        amount_in_wei=1_000_000_000_000_000_000,
        decimals_in=18,
        symbol_in="FUN",
        amount_out_wei=5_000_000,
        decimals_out=6,
        symbol_out="USDC",
        eth_price_usd=None,
    )
    # 5_000_000 / 10^6 = 5.0 USDC
    assert usd == 5.0
