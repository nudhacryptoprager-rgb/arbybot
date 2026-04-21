# PATH: tests/unit/test_revert_decoder.py
"""
E1.32/C2: Tests for revert reason decoder.

Covers:
  - Human-readable reverts after "execution reverted: " prefix
  - ABI-encoded Error(string) payloads
  - ABI-encoded Panic(uint256) payloads
  - Custom error selectors (Uniswap V3, Aerodrome, ERC-20)
  - Short token reverts (stf, spl, lok, as) as exact tokens only
  - Payloads embedded without the canonical prefix
  - Bare "execution reverted" → REVERT:unknown fallback
"""
import pytest

from m7.orderflow.sim_backends.rpc_fork_backend import _decode_revert_reason


class TestHumanReadable:
    def test_too_little_received_tagged_slippage(self):
        assert _decode_revert_reason(
            "execution reverted: Too little received"
        ) == "REVERT:SLIPPAGE"

    def test_insufficient_output_amount_slippage(self):
        assert _decode_revert_reason(
            "execution reverted: INSUFFICIENT_OUTPUT_AMOUNT"
        ) == "REVERT:SLIPPAGE"

    def test_safetransferfrom_stf(self):
        assert _decode_revert_reason(
            "execution reverted: TransferHelper::safeTransferFrom: transferFrom failed"
        ) == "REVERT:STF"

    def test_allowance_tag(self):
        assert _decode_revert_reason(
            "execution reverted: ERC20: transfer amount exceeds allowance"
        ) == "REVERT:INSUFFICIENT_ALLOWANCE"

    def test_balance_tag(self):
        assert _decode_revert_reason(
            "execution reverted: ERC20: transfer amount exceeds balance"
        ) == "REVERT:INSUFFICIENT_BALANCE"

    def test_expired_deadline(self):
        assert _decode_revert_reason(
            "execution reverted: Transaction too old"
        ) == "REVERT:DEADLINE_EXPIRED"


class TestShortTokens:
    def test_stf_as_exact_token(self):
        assert _decode_revert_reason("execution reverted: STF") == "REVERT:STF"

    def test_spl_as_exact_token(self):
        assert _decode_revert_reason("execution reverted: SPL") == "REVERT:PRICE_LIMIT"

    def test_lok_as_exact_token(self):
        assert _decode_revert_reason("execution reverted: LOK") == "REVERT:POOL_LOCKED"

    def test_as_token_pool_not_initialized(self):
        assert _decode_revert_reason("execution reverted: AS") == "REVERT:POOL_NOT_INITIALIZED"

    def test_short_token_not_false_matched_in_longer_text(self):
        # "lok" must not hijack words like "blockchain" or "class".
        msg = "execution reverted: something about blockchain class"
        result = _decode_revert_reason(msg)
        assert result.startswith("REVERT:")
        assert "POOL_LOCKED" not in result
        assert "POOL_NOT_INITIALIZED" not in result


class TestAbiEncoded:
    def test_error_string_slippage(self):
        # Error(string) encoded "Too little received"
        # selector 0x08c379a0 + offset(32) + length(19) + data padded to 32
        msg_bytes = b"Too little received"
        hex_data = (
            "08c379a0"
            + (32).to_bytes(32, "big").hex()
            + len(msg_bytes).to_bytes(32, "big").hex()
            + msg_bytes.hex().ljust(64, "0")
        )
        raw = f"execution reverted: 0x{hex_data}"
        assert _decode_revert_reason(raw) == "REVERT:SLIPPAGE"

    def test_panic_overflow(self):
        raw = "execution reverted: 0x4e487b71" + (0x11).to_bytes(32, "big").hex()
        assert _decode_revert_reason(raw) == "PANIC:overflow"


class TestEmbeddedHex:
    def test_hex_payload_without_prefix(self):
        # Alchemy-style: message "execution reverted" + separate data field
        # gets combined into: "execution reverted: 0x08c379a0...."
        msg_bytes = b"STF"
        hex_data = (
            "08c379a0"
            + (32).to_bytes(32, "big").hex()
            + len(msg_bytes).to_bytes(32, "big").hex()
            + msg_bytes.hex().ljust(64, "0")
        )
        # Without canonical prefix — decoder's Case 5 should still parse.
        raw = f"some rpc context 0x{hex_data} more stuff"
        assert _decode_revert_reason(raw) == "REVERT:STF"


class TestFallback:
    def test_bare_execution_reverted_unknown(self):
        # P0 (2026-04-20): bare "execution reverted" now surfaces as
        # REVERT:unknown:<fingerprint> so the histogram retains the raw
        # error snippet for diagnostics.
        result = _decode_revert_reason("execution reverted")
        assert result.startswith("REVERT:unknown")
        assert "execution reverted" in result

    def test_empty_returns_unknown(self):
        assert _decode_revert_reason("") == "REVERT:unknown"
