"""Unit tests for token contract age probe."""
from __future__ import annotations

from m8.discovery.token_contract_age import probe_token_creation_block


def test_probe_finds_first_block_with_code():
    deployed_at = {100: False, 150: False, 151: True, 200: True}

    def has_code(_addr: str, block: int) -> bool:
        for b in sorted(deployed_at):
            if block <= b:
                return deployed_at[b]
        return deployed_at[200]

    block = probe_token_creation_block(
        w3=None,
        address="0xabc",
        latest_block=200,
        has_code_fn=has_code,
    )
    assert block == 151


def test_probe_returns_none_when_never_deployed():
    def has_code(_addr: str, _block: int) -> bool:
        return False

    assert probe_token_creation_block(
        w3=None,
        address="0xabc",
        latest_block=100,
        has_code_fn=has_code,
    ) is None
