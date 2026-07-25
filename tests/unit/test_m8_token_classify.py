"""Tests for token_class / mechanic_pair shadow lane policy."""
from __future__ import annotations

from m8.discovery.token_classify import (
    MECHANIC_CROSS,
    MECHANIC_SAME,
    TOKEN_CLASS_FRESH,
    TOKEN_CLASS_KNOWN_MAJOR,
    TOKEN_CLASS_KNOWN_MID,
    annotate_hot_path_row,
    bridge_shadow_lane_eligible,
    build_spread_lifetime_histograms,
    classify_mechanic_pair,
    classify_token_class,
    production_lane_policy,
)

_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_WETH = "0x4200000000000000000000000000000000000006"
_FRESH = "0xdead000000000000000000000000000000000001"


def _cfg() -> dict:
    return {
        "chain": "base",
        "tokens": {"USDC": {"address": _USDC}, "WETH": {"address": _WETH}},
        "m8_2_fresh_token_window_s": 3600,
    }


class TestTokenClassify:
    def test_known_major_from_core_productive_default(self):
        tc = classify_token_class(_WETH, config=_cfg(), prior_pool_count=0)
        assert tc == TOKEN_CLASS_KNOWN_MAJOR

    def test_fresh_long_tail_unknown_addr(self):
        tc = classify_token_class(_FRESH, config=_cfg(), prior_pool_count=0)
        assert tc == TOKEN_CLASS_FRESH

    def test_session_fresh_requires_sniper_provenance(self, monkeypatch):
        from m8.discovery.token_classify import is_session_fresh_long_tail_quote_ready

        monkeypatch.delenv("ARBY_PIPELINE_SESSION_ID", raising=False)
        now = 1_700_000_000.0
        registry = {
            "tokens": {
                _FRESH: {
                    "first_seen_ts": now - 60,
                    "venues": {},
                }
            }
        }
        assert is_session_fresh_long_tail_quote_ready(
            _FRESH,
            config=_cfg(),
            registry=registry,
            provenance={"refresh_lane": "fresh_delta_lane", "first_seen_ts": now - 60},
            now_ts=now,
            mirror_quote_ready=True,
        )
        assert not is_session_fresh_long_tail_quote_ready(
            _FRESH,
            config=_cfg(),
            registry=registry,
            provenance={},
            now_ts=now,
            mirror_quote_ready=True,
        )

    def test_session_mismatch_blocks_when_session_differs(self):
        from m8.discovery.token_classify import is_session_fresh_long_tail_quote_ready

        now = 1_700_000_000.0
        registry = {"tokens": {_FRESH: {"first_seen_ts": now - 60, "venues": {}}}}
        assert not is_session_fresh_long_tail_quote_ready(
            _FRESH,
            config=_cfg(),
            registry=registry,
            provenance={
                "refresh_lane": "fresh_delta_lane",
                "first_seen_ts": now - 60,
                "session_id": "other-session",
            },
            now_ts=now,
            mirror_quote_ready=True,
            expected_session_id="canonical-session",
        )

    def test_missing_provenance_session_id_blocks_when_expected(self):
        from m8.discovery.token_classify import is_session_fresh_long_tail_quote_ready

        now = 1_700_000_000.0
        registry = {"tokens": {_FRESH: {"first_seen_ts": now - 60, "venues": {}}}}
        assert not is_session_fresh_long_tail_quote_ready(
            _FRESH,
            config=_cfg(),
            registry=registry,
            provenance={
                "refresh_lane": "fresh_delta_lane",
                "first_seen_ts": now - 60,
            },
            now_ts=now,
            mirror_quote_ready=True,
            expected_session_id="canonical-session",
        )

    def test_mechanic_pair_cross(self):
        assert classify_mechanic_pair(cross_mechanic=True) == MECHANIC_CROSS
        assert classify_mechanic_pair(cross_mechanic=False) == MECHANIC_SAME

    def test_known_major_same_mechanic_telemetry_only(self):
        assert production_lane_policy(TOKEN_CLASS_KNOWN_MAJOR, MECHANIC_SAME) == "telemetry_control"

    def test_known_major_cross_shadow_lane(self):
        assert production_lane_policy(TOKEN_CLASS_KNOWN_MAJOR, MECHANIC_CROSS) == "shadow_lane"

    def test_bridge_shadow_blocks_known_major_same_mechanic(self):
        assert bridge_shadow_lane_eligible(
            token_class=TOKEN_CLASS_KNOWN_MAJOR,
            mechanic_pair=MECHANIC_SAME,
            connector_tokens=2,
            cross_mechanic=False,
        ) is False

    def test_bridge_shadow_allows_fresh_with_connector(self):
        assert bridge_shadow_lane_eligible(
            token_class=TOKEN_CLASS_FRESH,
            mechanic_pair=MECHANIC_SAME,
            connector_tokens=1,
            cross_mechanic=False,
        ) is True

    def test_annotate_sets_lane_fields(self):
        row = annotate_hot_path_row(
            {"cross_mechanic": True, "summary": {"connector_tokens": ["AERO"]}},
            config=_cfg(),
            registry={"tokens": {}},
            focus_token=_FRESH,
            prior_pool_count=0,
        )
        assert row["token_class"] == TOKEN_CLASS_FRESH
        assert row["mechanic_pair"] == MECHANIC_CROSS
        assert row["bridge_shadow_lane_eligible"] is True

    def test_spread_histograms_separate_classes(self):
        h = build_spread_lifetime_histograms([
            {
                "token_class": TOKEN_CLASS_FRESH,
                "mechanic_pair": MECHANIC_CROSS,
                "spread_lifetime_s": 12.0,
                "focused_quote": {"cycles_positive_gross": 1},
            },
            {
                "token_class": TOKEN_CLASS_KNOWN_MAJOR,
                "mechanic_pair": MECHANIC_SAME,
                "focused_quote": {"cycles_positive_gross": 0},
            },
        ])
        assert TOKEN_CLASS_FRESH in h["spread_lifetime_by_token_class"]
        assert h["spread_lifetime_by_token_class"][TOKEN_CLASS_FRESH]["positive_gross_cycles"] == 1
