"""Unit tests for RfqAdapter skeleton.

Verifies:
- ADAPTER_TYPE constant is "rfq"
- Disabled adapter raises QuoteError(POOL_DISABLED) — structured, not silent
- Error details include adapter_type, dex_id, token addresses
- supports_fee_tiers() returns False
- Enabled adapter raises NotImplementedError (activation placeholder)
"""
import pytest

from dex.adapters.rfq import RfqAdapter
from core.exceptions import ErrorCode, QuoteError


_DUMMY_TOKEN_IN = "0x" + "11" * 20
_DUMMY_TOKEN_OUT = "0x" + "22" * 20
_AMOUNT_IN = 10 ** 18


class TestRfqAdapterType:
    def test_adapter_type_constant(self):
        assert RfqAdapter.ADAPTER_TYPE == "rfq"

    def test_adapter_type_on_instance(self):
        adapter = RfqAdapter(provider=None)
        assert adapter.ADAPTER_TYPE == "rfq"


class TestRfqAdapterDisabledByDefault:
    def test_enabled_false_by_default(self):
        adapter = RfqAdapter(provider=None)
        assert adapter.enabled is False

    def test_disabled_raises_quote_error(self):
        adapter = RfqAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address="0x" + "00" * 20,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )
        assert exc_info.value.code == ErrorCode.POOL_DISABLED

    def test_disabled_error_has_adapter_type_in_details(self):
        adapter = RfqAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address="0x" + "00" * 20,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )
        details = exc_info.value.details
        assert details.get("adapter_type") == "rfq"

    def test_disabled_error_has_token_addresses_in_details(self):
        adapter = RfqAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address="0x" + "00" * 20,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )
        details = exc_info.value.details
        assert details.get("token_in") == _DUMMY_TOKEN_IN
        assert details.get("token_out") == _DUMMY_TOKEN_OUT

    def test_disabled_error_has_dex_id_in_details(self):
        adapter = RfqAdapter(provider=None, enabled=False, dex_id="hashflow")
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address="0x" + "00" * 20,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )
        assert exc_info.value.details.get("dex_id") == "hashflow"

    def test_disabled_error_is_not_generic_exception(self):
        """Disabled adapter must NOT silently return or raise bare Exception."""
        adapter = RfqAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="0x" + "00" * 20,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )


class TestRfqAdapterEnabledRaisesNotImplemented:
    def test_enabled_raises_not_implemented(self):
        """When enabled, skeleton raises NotImplementedError (activation placeholder)."""
        adapter = RfqAdapter(provider=None, enabled=True)
        with pytest.raises(NotImplementedError):
            adapter.get_quote(
                pool_address="0x" + "00" * 20,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )


class TestRfqAdapterMeta:
    def test_does_not_support_fee_tiers(self):
        adapter = RfqAdapter(provider=None)
        assert adapter.supports_fee_tiers() is False

    def test_custom_dex_id(self):
        adapter = RfqAdapter(provider=None, dex_id="bebop")
        assert adapter.dex_id == "bebop"
