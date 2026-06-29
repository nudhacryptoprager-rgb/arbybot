"""Tests for narrow-bridge target universe and shadow gate."""
from __future__ import annotations

from m9.graph_arb.narrow_universe_gate import (
    narrow_shadow_gate_blocked,
    non_target_narrow_universe,
    summarize_narrow_bridge_provenance,
)


def test_target_narrow_universe_gate_blocked_without_fresh_quote_ready():
    from m9.graph_arb.narrow_universe_gate import target_narrow_universe_gate_blocked

    blocked, reason = target_narrow_universe_gate_blocked(
        {
            "active_routes": [],
            "fresh_long_tail_quote_ready_tokens": 0,
        }
    )
    assert blocked is True
    assert reason == "NO_FRESH_LONG_TAIL_QUOTE_READY"


def test_non_target_when_only_known_major_audit_lane():
    bridge = {
        "active_routes": [
            {
                "token_class": "known_major",
                "refresh_lane": "audit_lane",
            },
            {
                "token_class": "known_major",
                "refresh_lane": "audit_lane",
            },
        ]
    }
    blocked, reason = non_target_narrow_universe(bridge)
    assert blocked is True
    assert reason == "NON_TARGET_NARROW_UNIVERSE"


def test_target_when_fresh_long_tail_present():
    bridge = {
        "active_routes": [
            {
                "token_class": "fresh_long_tail",
                "refresh_lane": "fresh_delta_lane",
            }
        ]
    }
    blocked, _ = non_target_narrow_universe(bridge)
    assert blocked is False


def test_narrow_shadow_blocked_zero_cycles_total():
    cap = {
        "cycles_total": 0,
        "cycles_by_profile": {
            "diagnostic_near_econ": {"cycles_at_floor": 5},
        },
    }
    bridge = {
        "fresh_long_tail_quote_ready_tokens": 1,
        "active_routes": [
            {"token_class": "fresh_long_tail", "refresh_lane": "fresh_delta_lane"}
        ],
    }
    blocked, reason = narrow_shadow_gate_blocked(cap, bridge)
    assert blocked is True
    assert "ZERO_CYCLES_TOTAL" in reason


def test_narrow_shadow_blocked_non_target_even_with_cycles():
    cap = {
        "cycles_total": 10,
        "cycles_by_profile": {
            "diagnostic_near_econ": {"cycles_at_floor": 2},
        },
    }
    bridge = {
        "fresh_long_tail_quote_ready_tokens": 1,
        "active_routes": [
            {"token_class": "known_major", "refresh_lane": "audit_lane"},
        ],
    }
    blocked, reason = narrow_shadow_gate_blocked(cap, bridge)
    assert blocked is True
    assert reason == "NON_TARGET_NARROW_UNIVERSE"


def test_summarize_narrow_bridge_provenance():
    bridge = {
        "active_routes": [
            {"token_class": "fresh_long_tail", "refresh_lane": "fresh_delta_lane"},
            {"token_class": "known_major", "refresh_lane": "audit_lane"},
        ]
    }
    summary = summarize_narrow_bridge_provenance(bridge)
    assert summary["active_routes_by_token_class"]["fresh_long_tail"] == 1
    assert summary["active_routes_by_refresh_lane"]["audit_lane"] == 1
