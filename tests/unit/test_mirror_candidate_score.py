"""Tests for mirror verify candidate scoring."""
from __future__ import annotations

from m8.discovery.mirror_candidate_score import (
    rank_tokens_for_verify,
    score_mirror_verify_candidate,
)
from m8.discovery.pool_hints import PoolHint
from m8.discovery.radar_layer import RADAR_REASON_NEW_POOL


def _hint(tok: str, dex: str, reason: str = RADAR_REASON_NEW_POOL) -> PoolHint:
    return PoolHint(
        source="dexscreener",
        chain="base",
        focus_token=tok,
        token0_addr=tok,
        token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        dex_id=dex,
        pool_address=f"0x{dex[:8]}",
        radar_reason=reason,
    )


def test_score_multi_venue_and_fresh_token():
    tok = "0x" + "a" * 40
    rows = [_hint(tok, "uniswap_v3"), _hint(tok, "aerodrome")]
    score, reasons = score_mirror_verify_candidate(tok, rows)
    assert score >= 45.0
    assert "multi_venue_hint" in reasons


def test_score_fresh_long_tail_and_second_pool_hint():
    tok = "0x" + "c" * 40
    rows = [_hint(tok, "uniswap_v3")]
    watchlist_entry = {
        "token_class": "fresh_long_tail",
        "second_pool_hint": True,
        "refresh_lane": "fresh_delta_lane",
    }
    score, reasons = score_mirror_verify_candidate(
        tok, rows, watchlist_entry=watchlist_entry
    )
    assert score >= 75.0
    assert "fresh_long_tail" in reasons
    assert "second_pool_hint" in reasons


def test_rank_fresh_long_tail_beats_known_major():
    fresh_tok = "0x" + "d" * 40
    major_tok = "0x" + "e" * 40
    fresh_rows = [_hint(fresh_tok, "uniswap_v3")]
    major_rows = [_hint(major_tok, "uniswap_v3"), _hint(major_tok, "aerodrome")]
    fresh_score, _ = score_mirror_verify_candidate(
        fresh_tok,
        fresh_rows,
        watchlist_entry={
            "token_class": "fresh_long_tail",
            "second_pool_hint": True,
            "refresh_lane": "fresh_delta_lane",
        },
    )
    major_score, major_reasons = score_mirror_verify_candidate(
        major_tok,
        major_rows,
        watchlist_entry={
            "token_class": "known_major",
            "refresh_lane": "audit_lane",
        },
    )
    assert fresh_score > major_score
    assert "known_major_penalty" in major_reasons


def test_rank_tokens_for_verify_prefers_second_pool_signal():
    tok = "0x" + "b" * 40
    hints = [_hint(tok, "uniswap_v3")]
    watchlist = {
        "tokens": {
            tok: {
                "transitions_1_to_2": 1,
                "refresh_lane": "fresh_delta_lane",
            }
        }
    }
    ranked = rank_tokens_for_verify(hints, watchlist=watchlist, min_score=10.0)
    assert ranked
    assert ranked[0]["token"] == tok
    assert ranked[0]["priority_score"] >= 30.0


def test_verify_budget_disposition_and_histogram():
    from m8.discovery.mirror_candidate_score import (
        DISPOSITION_NO_RADAR_POOL,
        DISPOSITION_SELECTED_FOR_VERIFY,
        rank_tokens_for_verify_with_budget,
    )

    tok_a = "0x" + "1" * 40
    tok_b = "0x" + "2" * 40
    hints = [_hint(tok_a, "uniswap_v3"), _hint(tok_a, "aerodrome")]
    watchlist = {
        "tokens": {
            tok_a: {"token_class": "fresh_long_tail", "refresh_lane": "fresh_delta_lane"},
            tok_b: {"token_class": "fresh_long_tail", "refresh_lane": "fresh_delta_lane"},
        }
    }
    _, budget = rank_tokens_for_verify_with_budget(
        hints,
        watchlist=watchlist,
        min_score=10.0,
        max_tokens=1,
        top_n_table=5,
    )
    assert budget["verify_subset_cap"] == 1
    assert budget["top_candidates"]
    assert budget["disposition_histogram"]
    dispositions = {row["disposition"] for row in budget["top_candidates"]}
    assert DISPOSITION_SELECTED_FOR_VERIFY in dispositions
    assert DISPOSITION_NO_RADAR_POOL in dispositions or DISPOSITION_DROPPED_TO_WARM in dispositions
