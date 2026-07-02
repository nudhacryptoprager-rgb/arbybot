"""Curve toxic pool admission tests."""
from __future__ import annotations

from m9.graph_arb.adapter_metadata import load_adapter_metadata


def test_toxic_stable_curve_pool_not_quotable():
    # Test YAML trust-anchor classification, not runtime-merged rolling state.
    # The rolling artifact may re-probe and upgrade a pool to QUOTE_OK_*;
    # that is a runtime reality, not a unit-test contract.
    meta = load_adapter_metadata(merge_rolling_indices=False)
    pool = "0xd4e59bfd7bce4a5bc1ee12ea930c7495831d6aef"
    assert meta.curve_pool_quotable(pool, chain="base") is False
