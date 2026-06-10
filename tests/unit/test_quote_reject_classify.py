"""Tests for adapter-specific quote reject classification."""
from __future__ import annotations

from m9.graph_arb.quote_reject_classify import (
    classify_balancer_revert,
    classify_maverick_revert,
    classify_quote_failure,
    extract_balancer_code,
)


def test_balancer_304_max_in_ratio():
    reason, detail = classify_balancer_revert("eth_call error: execution reverted: BAL#304")
    assert reason == "BALANCER_MAX_IN_RATIO"
    assert detail["balancer_code"] == "BAL#304"


def test_balancer_402_paused():
    reason, detail = classify_balancer_revert("execution reverted: BAL#402")
    assert reason == "BALANCER_PAUSED"
    assert detail["balancer_code"] == "BAL#402"


def test_maverick_zero_out():
    reason, _ = classify_maverick_revert("MAVERICK_ZERO_OUT")
    assert reason == "MAVERICK_NO_LIQUIDITY"


def test_maverick_token_a_lookup():
    reason, _ = classify_maverick_revert("Maverick V2 tokenA() lookup failed for pool 0xabc")
    assert reason == "MAVERICK_BAD_POOL_CONFIG"


def test_classify_quote_failure_balancer_adapter():
    reason, detail = classify_quote_failure(
        "balancer_stable",
        "eth_call error: execution reverted: BAL#304",
    )
    assert reason == "BALANCER_MAX_IN_RATIO"
    assert extract_balancer_code("reverted: BAL#304") == "BAL#304"


def test_maverick_json_payload_quoter_revert():
    payload = (
        '{"quote_contour":"maverick_quoter","status":"MAVERICK_QUOTE_REVERT",'
        '"raw_error":"eth_call error: execution reverted"}'
    )
    reason, detail = classify_maverick_revert(payload)
    assert reason == "MAVERICK_QUOTER_REVERT"
    assert detail["quote_contour"] == "maverick_quoter"


def test_balancer_metadata_incomplete():
    reason, detail = classify_balancer_revert("BALANCER_METADATA_INCOMPLETE missing pool_id")
    assert reason == "BALANCER_METADATA_INCOMPLETE"
    assert detail["balancer_reason"] == "metadata_incomplete"


def test_balancer_unknown_revert_with_metadata():
    reason, detail = classify_balancer_revert(
        "execution reverted",
        has_metadata=True,
    )
    assert reason == "BALANCER_UNKNOWN_REVERT_WITH_METADATA"
    assert detail["balancer_reason"] == "revert_with_complete_metadata"


def test_maverick_json_payload_pool_direct_empty():
    payload = (
        '{"quote_contour":"pool_direct","status":"MAVERICK_QUOTE_REVERT",'
        '"raw_error":"eth_call empty/short result: \'0x\'"}'
    )
    reason, _ = classify_maverick_revert(payload)
    assert reason == "MAVERICK_NO_LIQUIDITY"
