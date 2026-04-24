"""E1.35 P1.1 step 3: SLIPSTREAM_PENDING_LOOKUP reclassification in execution_gate.

Verifies:
- When venue starts with "0x" / "ptt_direct" and best_buy_fee is in the
  known Aerodrome CL fee set, _build_tx_params returns
  `SLIPSTREAM_PENDING_LOOKUP:<fee>` IF `aerodrome_slipstream` config is
  present and `verified=True`.
- If the Slipstream config is missing or not verified, the legacy bucket
  `UNSUPPORTED_FEE_TIER:AERODROME_CL:<fee>` is preserved (back-compat).
- Non-CL non-standard fees still fall into ALGEBRA_DYNAMIC / UNKNOWN
  buckets as before.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from m7.orderflow.execution_gate import _build_sim_tx_params as _build_tx_params


def _result(
    *,
    amount_in_wei: int = 10**18,
    pair: str = "WETH/USDC",
    venue: str = "ptt_direct",
    best_buy_fee: int | None = None,
):
    return SimpleNamespace(
        amount_in_wei=amount_in_wei,
        actual_pair=pair,
        best_buy_venue=venue,
        best_buy_fee=best_buy_fee,
        backrun_token_in_address=None,
        backrun_token_out_address=None,
    )


class TestSlipstreamPendingLookup:
    def test_verified_config_yields_pending_lookup_bucket(self):
        from m7.orderflow.execution_gate import SLIPSTREAM_FEE_TO_TICKSPACING

        r = _result(best_buy_fee=2655)
        tx, reason = _build_tx_params(r, chain="base")
        assert tx is None
        # M7.E1.34k: without token addresses, lookup resolves ts but
        # cannot finish calldata build — bucket becomes
        # SLIPSTREAM_SIM_READY_TOKENS_MISSING:<fee>:ts<ts>.
        ts = SLIPSTREAM_FEE_TO_TICKSPACING.get(2655)
        assert ts is not None
        assert reason == f"SLIPSTREAM_SIM_READY_TOKENS_MISSING:2655:ts{ts}"

    @pytest.mark.parametrize("fee", [150, 445, 600, 1000, 2105, 3024, 5000, 20000])
    def test_all_known_cl_fees_route_to_pending_lookup(self, fee):
        from m7.orderflow.execution_gate import SLIPSTREAM_FEE_TO_TICKSPACING

        r = _result(best_buy_fee=fee)
        tx, reason = _build_tx_params(r, chain="base")
        assert tx is None
        ts = SLIPSTREAM_FEE_TO_TICKSPACING.get(fee)
        if ts is not None:
            assert reason == f"SLIPSTREAM_SIM_READY_TOKENS_MISSING:{fee}:ts{ts}"
        else:
            assert reason == f"SLIPSTREAM_PENDING_LOOKUP:{fee}"
    def test_unverified_config_falls_back_to_legacy_bucket(self):
        """When Slipstream config lacks router/quoter (not yet verified),
        the old AERODROME_CL bucket is preserved so we don't falsely
        advertise adapter availability."""
        from config import get_dex_config as _real_gdc

        def _fake_gdc(chain, dex):
            if dex == "aerodrome_slipstream":
                cfg = dict(_real_gdc(chain, dex))
                cfg["verified"] = False
                cfg["router"] = None
                cfg["quoter_v2"] = None
                return cfg
            return _real_gdc(chain, dex)

        with patch("config.get_dex_config", side_effect=_fake_gdc):
            r = _result(best_buy_fee=2655)
            tx, reason = _build_tx_params(r, chain="base")
            assert tx is None
            assert reason == "UNSUPPORTED_FEE_TIER:AERODROME_CL:2655"

    def test_small_non_standard_fee_still_algebra_dynamic(self):
        r = _result(best_buy_fee=85)
        tx, reason = _build_tx_params(r, chain="base")
        assert tx is None
        assert reason == "UNSUPPORTED_FEE_TIER:ALGEBRA_DYNAMIC:85"

    def test_unknown_large_fee_still_unknown_bucket(self):
        r = _result(best_buy_fee=7777)
        tx, reason = _build_tx_params(r, chain="base")
        assert tx is None
        assert reason == "UNSUPPORTED_FEE_TIER:UNKNOWN:7777"
