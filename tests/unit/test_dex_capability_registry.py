"""Tests for DexCapabilityRegistry."""
from __future__ import annotations

from core.dex_capability_registry import load_dex_capability_registry


def test_registry_loads_configured_candidates():
    reg = load_dex_capability_registry()
    caps = {c.dex_id: c for c in reg.all()}
    assert "alien_base_v2" in caps
    assert caps["alien_base_v2"].enabled is True
    assert caps["alien_base_v2"].quote_supported is True


def test_iziswap_disabled_in_exotic_config():
    reg = load_dex_capability_registry()
    cap = reg.get("iziswap_base")
    assert cap is not None
    assert cap.enabled is False
    assert cap.quote_supported is False
    assert cap.registry_status == "quarantine"


def test_registry_alias_lookup():
    reg = load_dex_capability_registry()
    cap = reg.get("alienbase")
    assert cap is not None
    assert cap.dex_id == "alien_base_v2"
