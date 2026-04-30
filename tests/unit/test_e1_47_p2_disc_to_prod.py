"""M7.E1.47/P2: DISC -> PROD promotion module."""
from __future__ import annotations

from m7.orderflow.disc_to_prod_promotion import (
    PromotionThresholds,
    families_qualifying_from_scoreboard,
    merge_into_prod_candidates,
    pairs_from_disc_execution,
    select_pairs_to_promote,
)


def _sb(families: dict) -> dict:
    return {"families": families, "updated_at": "2026-04-30T00:00:00Z"}


def test_families_qualify_at_default_thresholds():
    sb = _sb({
        "WETH": {
            "scored_positive": 3, "route_viable": 5,
            "sessions_with_signal": [1, 2, 3], "total_scored": 10,
        },
        "RNDR": {
            "scored_positive": 0, "route_viable": 5,
            "sessions_with_signal": [1, 2], "total_scored": 8,
        },
        "TOOFEW": {
            "scored_positive": 1, "route_viable": 1,
            "sessions_with_signal": [1], "total_scored": 1,
        },
    })
    out = families_qualifying_from_scoreboard(sb)
    assert out == {"WETH"}


def test_thresholds_tightening_excludes_marginal():
    sb = _sb({
        "WETH": {
            "scored_positive": 1, "route_viable": 2,
            "sessions_with_signal": [1], "total_scored": 5,
        },
    })
    assert families_qualifying_from_scoreboard(sb) == {"WETH"}
    out_strict = families_qualifying_from_scoreboard(
        sb, thresholds=PromotionThresholds(min_positive=2, min_viable=3, min_sessions=2)
    )
    assert out_strict == set()


def test_pairs_from_disc_execution_passthrough():
    p = {"candidate": ["FOO/BAR"], "execution": ["WETH/USDC", "AERO/USDC", "broken"]}
    out = pairs_from_disc_execution(p)
    assert out == {"WETH/USDC", "AERO/USDC"}  # "broken" lacks "/"


def test_select_emits_disc_execution_unconditionally():
    sb = _sb({})  # no scoreboard signal
    p = {"execution": ["WETH/USDC"]}
    out = select_pairs_to_promote(sb, p)
    assert out == ["WETH/USDC"]


def test_select_uses_candidate_pool_for_family_promotion():
    sb = _sb({
        "WETH": {
            "scored_positive": 2, "route_viable": 3,
            "sessions_with_signal": [1, 2], "total_scored": 10,
        },
    })
    pool = ["WETH/USDC", "WETH/AERO", "RNDR/USDC"]
    out = select_pairs_to_promote(sb, {}, candidate_pool=pool)
    assert out == ["WETH/AERO", "WETH/USDC"]  # sorted; RNDR excluded


def test_select_drops_family_promotion_without_candidate_pool():
    sb = _sb({
        "WETH": {
            "scored_positive": 5, "route_viable": 5,
            "sessions_with_signal": [1, 2, 3], "total_scored": 10,
        },
    })
    out = select_pairs_to_promote(sb, {})
    assert out == []  # no pool => no synthesised pairs


def test_select_combines_disc_execution_and_family_pool():
    sb = _sb({
        "WETH": {
            "scored_positive": 2, "route_viable": 3,
            "sessions_with_signal": [1, 2], "total_scored": 10,
        },
    })
    p = {"execution": ["AERO/USDC"]}
    pool = ["WETH/USDC"]
    out = select_pairs_to_promote(sb, p, candidate_pool=pool)
    assert out == ["AERO/USDC", "WETH/USDC"]


def test_merge_dedups_and_preserves_execution():
    prod = {"candidate": ["AAA/BBB"], "execution": ["EXEC/A"]}
    out = merge_into_prod_candidates(prod, ["AAA/BBB", "CCC/DDD", "AAA/BBB"])
    assert out["candidate"] == ["AAA/BBB", "CCC/DDD"]
    assert out["execution"] == ["EXEC/A"]


def test_handles_malformed_scoreboard():
    assert families_qualifying_from_scoreboard({}) == set()
    assert families_qualifying_from_scoreboard({"families": "broken"}) == set()
    assert families_qualifying_from_scoreboard(None) == set()  # type: ignore[arg-type]


def test_handles_malformed_promoted():
    assert pairs_from_disc_execution({}) == set()
    assert pairs_from_disc_execution(None) == set()  # type: ignore[arg-type]


def test_merge_with_empty_existing_prod():
    out = merge_into_prod_candidates({}, ["X/Y"])
    assert out == {"candidate": ["X/Y"], "execution": []}
