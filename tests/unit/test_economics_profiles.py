"""Economics profile contract tests."""
from __future__ import annotations

from m9.graph_arb.size_truth import (
    economic_size_floor_for_profile,
    economics_profile_specs,
    load_cost_model,
)


def test_production_conservative_floor_is_180():
    cm = load_cost_model("config/exotic_base_anchor.yaml")
    floor = economic_size_floor_for_profile(cm, "production_conservative")
    assert floor == 180.0


def test_economics_profiles_present():
    specs = economics_profile_specs(config_path="config/exotic_base_anchor.yaml")
    assert "production_conservative" in specs
    assert "base_realistic" in specs
    assert "diagnostic_near_econ" in specs
    assert specs["production_conservative"]["economics_floor_usd"] == 180.0
    assert specs["diagnostic_near_econ"]["profit_claim_allowed"] is False
    realistic = specs["base_realistic"]["economics_floor_usd"]
    assert 60.0 <= realistic <= 105.0
