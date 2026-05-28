"""Unit tests for DodoPmmAdapter skeleton.

Verifies:
- ADAPTER_TYPE constant is "dodo_pmm"
- Disabled adapter raises QuoteError(POOL_DISABLED) — not a silent failure
- Structured error details include adapter_type and pool_address
- supports_fee_tiers() returns False
- get_quote() when enabled raises NotImplementedError (activation placeholder)
"""
import pytest

from dex.adapters.dodo_pmm import DodoPmmAdapter
from core.exceptions import ErrorCode, QuoteError


_DUMMY_POOL = "0x" + "ab" * 20
_DUMMY_TOKEN_IN = "0x" + "11" * 20
_DUMMY_TOKEN_OUT = "0x" + "22" * 20
_AMOUNT_IN = 10 ** 18


class TestDodoPmmAdapterType:
    def test_adapter_type_constant(self):
        assert DodoPmmAdapter.ADAPTER_TYPE == "dodo_pmm"

    def test_adapter_type_accessible_on_instance(self):
        adapter = DodoPmmAdapter(provider=None, enabled=False)
        assert adapter.ADAPTER_TYPE == "dodo_pmm"


class TestDodoPmmDisabledByDefault:
    def test_enabled_false_by_default(self):
        adapter = DodoPmmAdapter(provider=None)
        assert adapter.enabled is False

    def test_disabled_raises_quote_error(self):
        adapter = DodoPmmAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address=_DUMMY_POOL,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )
        assert exc_info.value.code == ErrorCode.POOL_DISABLED

    def test_disabled_error_has_pool_address_in_details(self):
        adapter = DodoPmmAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address=_DUMMY_POOL,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )
        details = exc_info.value.details or {}
        assert details.get("pool_address") == _DUMMY_POOL

    def test_disabled_error_has_adapter_type_in_details(self):
        adapter = DodoPmmAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError) as exc_info:
            adapter.get_quote(
                pool_address=_DUMMY_POOL,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )
        details = exc_info.value.details or {}
        assert details.get("adapter_type") == "dodo_pmm"

    def test_disabled_error_is_not_generic_exception(self):
        """Disabled adapter must NOT raise a bare Exception or RuntimeError."""
        adapter = DodoPmmAdapter(provider=None, enabled=False)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address=_DUMMY_POOL,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )


class TestDodoPmmEnabledRaisesNotImplemented:
    def test_enabled_raises_not_implemented(self):
        """When enabled, skeleton raises NotImplementedError (activation placeholder)."""
        adapter = DodoPmmAdapter(provider=None, enabled=True)
        with pytest.raises(NotImplementedError):
            adapter.get_quote(
                pool_address=_DUMMY_POOL,
                token_in=_DUMMY_TOKEN_IN,
                token_out=_DUMMY_TOKEN_OUT,
                amount_in=_AMOUNT_IN,
            )


class TestDodoPmmMeta:
    def test_does_not_support_fee_tiers(self):
        adapter = DodoPmmAdapter(provider=None)
        assert adapter.supports_fee_tiers() is False

    def test_custom_dex_id(self):
        adapter = DodoPmmAdapter(provider=None, dex_id="dodo_v2")
        assert adapter.dex_id == "dodo_v2"
