from scripts.reviewer_soak_summary import (
    _find_bucket_delta,
    summarise_lane,
)


def test_find_bucket_delta_matches_transport_prefixed_block_out_of_range() -> None:
    delta_hist = {
        "eth_call: BlockOutOfRangeError: requested block 10 is beyond latest": 2,
        "CALLDATA_BUILD_FAILED:AMOUNT_ZERO": 3,
    }

    assert _find_bucket_delta(delta_hist, "BlockOutOfRangeError") == 2
    assert _find_bucket_delta(delta_hist, "AMOUNT_ZERO") == 3


def test_reviewer_acceptance_fails_on_prefixed_block_out_of_range() -> None:
    baseline = {
        "session_id": "base",
        "last_updated": "2026-04-21T00:00:00Z",
        "sim_passed_total": 10,
        "roundtrip_attempted_total": 5,
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-21T00:30:00Z",
        "sim_passed_total": 11,
        "roundtrip_attempted_total": 6,
        "simulation_error_histogram": {
            "eth_call: BlockOutOfRangeError: requested block is beyond latest": 1,
        },
    }

    ok, reason = summarise_lane("production", baseline, current)

    assert ok is False
    assert "BLOCK_OUT_OF_RANGE_ERRORS=1" in reason


def test_reviewer_acceptance_passes_with_fresh_sim_and_no_block_out_of_range() -> None:
    baseline = {
        "session_id": "base",
        "last_updated": "2026-04-21T00:00:00Z",
        "sim_passed_total": 10,
        "roundtrip_attempted_total": 5,
        "fast_path_scored_total": 0,
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-21T00:30:00Z",
        "sim_passed_total": 12,
        "roundtrip_attempted_total": 6,
        # M7.E1.34e fix #5: acceptance now requires fast_path_scored_delta
        # >= 20 unless ARBY_REVIEWER_QUIET_OK=1.
        "fast_path_scored_total": 25,
        "simulation_error_histogram": {
            "CALLDATA_BUILD_FAILED:VENUE_MISSING": 1,
        },
    }

    ok, reason = summarise_lane("production", baseline, current)

    assert ok is True
    assert "pre_sim_skip_total=0" in reason


def test_reviewer_acceptance_fails_without_fresh_roundtrip() -> None:
    baseline = {
        "session_id": "base",
        "last_updated": "2026-04-21T00:00:00Z",
        "sim_passed_total": 10,
        "roundtrip_attempted_total": 5,
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-21T00:30:00Z",
        "sim_passed_total": 11,
        "roundtrip_attempted_total": 5,
        "simulation_error_histogram": {},
    }

    ok, reason = summarise_lane("production", baseline, current)

    assert ok is False
    assert "NO_FRESH_ROUNDTRIP_ATTEMPTED" in reason


def test_reviewer_acceptance_fails_on_strict_provider_breach() -> None:
    baseline = {
        "session_id": "base",
        "last_updated": "2026-04-21T00:00:00Z",
        "sim_passed_total": 10,
        "roundtrip_attempted_total": 5,
        "strict_provider_breaches_total": 0,
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-21T00:30:00Z",
        "sim_passed_total": 11,
        "roundtrip_attempted_total": 6,
        "strict_provider_breaches_total": 1,
        "simulation_error_histogram": {},
    }

    ok, reason = summarise_lane("production", baseline, current)

    assert ok is False
    assert "STRICT_PROVIDER_BREACHES=1" in reason


def test_scoring_blackhole_detected_when_events_seen_but_no_scoring() -> None:
    # Reviewer post-20m-control fix #2: when the feed produces events but
    # NONE reach fast-path scoring, the funnel itself is blocked. Operators
    # need this signal explicitly so they do not misclassify a scoring
    # regression as a quiet market.
    baseline = {
        "session_id": "base",
        "last_updated": "2026-04-29T00:00:00Z",
        "events_seen_total": 0,
        "fast_path_scored_total": 0,
        "sim_passed_total": 0,
        "roundtrip_attempted_total": 0,
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-29T00:20:00Z",
        "events_seen_total": 100,
        "fast_path_scored_total": 0,
        "sim_passed_total": 0,
        "roundtrip_attempted_total": 0,
        "simulation_error_histogram": {},
    }

    ok, reason = summarise_lane("production", baseline, current)

    assert ok is False
    assert "SCORING_BLACKHOLE" in reason
    assert "events_seen_delta=100" in reason
    assert "fast_path_scored_delta=0" in reason


def test_scoring_blackhole_not_emitted_when_zero_events() -> None:
    # Pure quiet market: zero events seen, zero scored. SCORING_BLACKHOLE
    # must NOT trigger here — that's the regular FAST_PATH_SCORED_TOO_LOW
    # case.
    baseline = {
        "session_id": "base",
        "last_updated": "2026-04-29T00:00:00Z",
        "events_seen_total": 0,
        "fast_path_scored_total": 0,
        "sim_passed_total": 0,
        "roundtrip_attempted_total": 0,
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-29T00:20:00Z",
        "events_seen_total": 0,
        "fast_path_scored_total": 0,
        "sim_passed_total": 0,
        "roundtrip_attempted_total": 0,
        "simulation_error_histogram": {},
    }

    ok, reason = summarise_lane("production", baseline, current)

    assert ok is False
    assert "SCORING_BLACKHOLE" not in reason


def test_scoring_blackhole_not_emitted_when_some_scoring_happened() -> None:
    # If even a single event reached scoring, the funnel is not a blackhole
    # — could still be too low for acceptance, but a different signal.
    baseline = {
        "session_id": "base",
        "last_updated": "2026-04-29T00:00:00Z",
        "events_seen_total": 0,
        "fast_path_scored_total": 0,
        "sim_passed_total": 0,
        "roundtrip_attempted_total": 0,
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-29T00:20:00Z",
        "events_seen_total": 100,
        "fast_path_scored_total": 1,
        "sim_passed_total": 0,
        "roundtrip_attempted_total": 0,
        "simulation_error_histogram": {},
    }

    ok, reason = summarise_lane("production", baseline, current)

    assert ok is False
    assert "SCORING_BLACKHOLE" not in reason
