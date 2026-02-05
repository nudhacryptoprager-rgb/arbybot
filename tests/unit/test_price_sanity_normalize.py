from decimal import Decimal

from core.validators import normalize_price, calculate_deviation_bps


def test_normalize_price_weth_usdc():
    # 1 WETH -> 2600 USDC (WETH 18 decimals, USDC 6 decimals)
    price, diag = normalize_price(
        amount_in_wei=10 ** 18,
        amount_out_wei=2600 * (10 ** 6),
        decimals_in=18,
        decimals_out=6,
        token_in="WETH",
        token_out="USDC",
    )
    assert isinstance(price, Decimal)
    assert round(price, 6) == Decimal("2600")


def test_deviation_bps_calculation():
    # price 2600 vs anchor 2600 -> 0 bps
    capped, raw, was_capped = calculate_deviation_bps(Decimal("2600"), Decimal("2600"))
    assert raw == 0
    assert capped == 0
    assert was_capped is False
