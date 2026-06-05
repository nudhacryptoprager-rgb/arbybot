"""Honeypot gate for positive gross evidence."""
from __future__ import annotations

from monitoring.sniper_honeypot import (
    HoneypotVerdict,
    KNOWN_SCAM_TOKENS,
    positive_gross_counts_as_evidence,
    probe_transfer_tax_sell_side,
)


def test_scam_token_blocks_positive_evidence():
    scam = next(iter(KNOWN_SCAM_TOKENS))
    assert positive_gross_counts_as_evidence([scam]) is False


def test_unknown_token_allows_evidence_phase3b():
    assert positive_gross_counts_as_evidence(["0x1234567890123456789012345678901234567890"]) is True


def test_probe_transfer_tax_unknown_by_default():
    assert probe_transfer_tax_sell_side("0xabc") == HoneypotVerdict.UNKNOWN
