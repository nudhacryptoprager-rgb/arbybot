"""M4/M5 discovery must not include m9_only DEX entries from dexes.yaml by default."""
from __future__ import annotations

import pytest

from discovery.index_factories import get_chain_dexes


@pytest.mark.parametrize(
    "dex_id",
    ["curve_stable", "balancer_vault", "maverick_v2", "aerodrome_v2_stable", "uniswap_v2"],
)
def test_get_chain_dexes_excludes_m9_only_by_default(dex_id: str):
    dexes = get_chain_dexes("base", include_m9_only=False)
    assert dex_id not in dexes


def test_get_chain_dexes_includes_m9_only_when_requested():
    dexes = get_chain_dexes("base", include_m9_only=True)
    assert "curve_stable" in dexes
    assert "uniswap_v3" in dexes


def test_runtime_imports_index_get_chain_dexes():
    """discovery/runtime.py re-exports get_chain_dexes from index_factories (m9 guard there)."""
    from discovery.runtime import get_chain_dexes as rt_get

    assert rt_get is get_chain_dexes
    assert "curve_stable" not in rt_get("base")
