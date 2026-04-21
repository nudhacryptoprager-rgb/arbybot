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
        "simulation_error_histogram": {},
    }
    current = {
        "session_id": "cur",
        "last_updated": "2026-04-21T00:30:00Z",
        "sim_passed_total": 12,
        "roundtrip_attempted_total": 6,
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
