"""E1.42: fee 2600 adapter audit — reject classification tests.

Goal: when scoring reports a (venue, fee) pair that the gate cannot
build a sell leg for, the reject reason MUST surface BOTH the venue
and the fee so reviewers can disambiguate:
  - SELL_FEE_UNSUPPORTED:AERODROME_CL:<fee>     (known CL pool)
  - SELL_FEE_UNSUPPORTED:ALGEBRA_DYNAMIC:<fee>  (Algebra-style)
  - SELL_FEE_UNSUPPORTED:VENUE_FEE_MISMATCH:<venue>:<fee>
        (registered venue with stray fee — discovery/scoring bug)
  - SELL_FEE_UNSUPPORTED:UNKNOWN_SOURCE:<venue>:<fee>
        (off-registry venue, no adapter wired)
"""

from __future__ import annotations

from types import SimpleNamespace

from m7.orderflow.execution_gate import (
    _build_sell_leg_tx_params,
    _reset_accepted_fees_cache,
)


def _mk_result(venue: str, fee: int) -> SimpleNamespace:
    return SimpleNamespace(
        amount_in_wei=10**18,
        best_sell_venue=venue,
        best_sell_fee=fee,
        best_buy_fee=fee,
        backrun_token_in_address="0x" + "11" * 20,
        backrun_token_out_address="0x" + "22" * 20,
    )


def test_aerodrome_cl_fee_classified() -> None:
    _reset_accepted_fees_cache()
    res = _mk_result("aerodrome_slipstream", 2105)
    tx, reason = _build_sell_leg_tx_params(res, sell_input_wei=10**17, chain="base")
    assert tx is None
    assert reason == "SELL_FEE_UNSUPPORTED:AERODROME_CL:2105"


def test_algebra_dynamic_fee_classified() -> None:
    _reset_accepted_fees_cache()
    res = _mk_result("lynex_v3", 50)
    tx, reason = _build_sell_leg_tx_params(res, sell_input_wei=10**17, chain="linea")
    assert tx is None
    assert reason == "SELL_FEE_UNSUPPORTED:ALGEBRA_DYNAMIC:50"


def test_venue_fee_mismatch_registered_venue_stray_fee() -> None:
    """fee=2600 with a registered venue → VENUE_FEE_MISMATCH (discovery bug)."""
    _reset_accepted_fees_cache()
    res = _mk_result("uniswap_v3", 2600)
    tx, reason = _build_sell_leg_tx_params(res, sell_input_wei=10**17, chain="base")
    assert tx is None
    assert reason == "SELL_FEE_UNSUPPORTED:VENUE_FEE_MISMATCH:uniswap_v3:2600"


def test_unknown_source_off_registry_venue() -> None:
    """Off-registry venue → UNKNOWN_SOURCE (no adapter wired)."""
    _reset_accepted_fees_cache()
    res = _mk_result("some_unknown_venue", 2600)
    tx, reason = _build_sell_leg_tx_params(res, sell_input_wei=10**17, chain="base")
    assert tx is None
    assert reason == "SELL_FEE_UNSUPPORTED:UNKNOWN_SOURCE:some_unknown_venue:2600"
