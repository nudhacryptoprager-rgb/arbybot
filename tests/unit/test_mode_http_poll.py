"""Unit tests for m7.orderflow.mode_http_poll (E1.52 proof lane, schema v2)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from m7.orderflow import mode_http_poll
from m7.orderflow.mode_http_poll import run_http_poll_proof
from m7.orderflow.pool_price_state import (
    V2_SYNC_TOPIC,
    V3_SWAP_TOPIC,
    reset_registry_for_tests,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCHEMA_V2 = "m7.e1.52.proof.v2"

def _u256_hex(val: int) -> str:
    if val < 0:
        val += 1 << 256
    return f"{val:064x}"


def _i256_hex(val: int) -> str:
    if val < 0:
        val += 1 << 256
    return f"{val:064x}"


def _make_v3_log(*, pool: str, block: int, log_index: int = 0) -> dict:
    data_hex = (
        _i256_hex(1_000_000)
        + _i256_hex(-300_000_000_000_000)
        + _u256_hex(79228162514264337593543950336)
        + _u256_hex(12345678901234567890)
        + _i256_hex(-42)
    )
    return {
        "address": pool,
        "blockNumber": block,
        "logIndex": log_index,
        "data": "0x" + data_hex,
        "topics": [V3_SWAP_TOPIC],
        "transactionHash": "0x" + "11" * 32,
    }


def _make_v2_log(*, pool: str, block: int, log_index: int = 0) -> dict:
    data_hex = _u256_hex(1_000_000_000_000) + _u256_hex(500_000_000_000_000_000)
    return {
        "address": pool,
        "blockNumber": block,
        "logIndex": log_index,
        "data": "0x" + data_hex,
        "topics": [V2_SYNC_TOPIC],
        "transactionHash": "0x" + "22" * 32,
    }


class _FakeEth:
    def __init__(self, block_sequence, logs_by_block):
        self._blocks = list(block_sequence)
        self._idx = 0
        self._logs = logs_by_block

    @property
    def block_number(self):
        if self._idx < len(self._blocks):
            b = self._blocks[self._idx]
            self._idx += 1
            return b
        return self._blocks[-1]

    def get_logs(self, params):
        block = params.get("fromBlock")
        topics = params.get("topics") or []
        topic0 = topics[0] if topics else None
        all_logs = self._logs.get(block, [])
        if topic0 is None:
            return list(all_logs)
        return [lg for lg in all_logs if lg.get("topics", [None])[0] == topic0]


class _FakeWeb3:
    def __init__(self, eth):
        self.eth = eth


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProofArtifact:
    def setup_method(self):
        reset_registry_for_tests()

    def test_no_rpc_writes_minimal_artifact(self, tmp_path: Path):
        dest = tmp_path / "m7_proof_latest.json"
        art = run_http_poll_proof(
            chain="base",
            duration_s=0.0,
            poll_interval_s=0.01,
            rpc_url="",
            artifact_path=dest,
        )
        assert dest.exists()
        on_disk = json.loads(dest.read_text(encoding="utf-8"))
        # --- Step 3: artifact contract — exact JSON paths ---
        assert on_disk["schema_version"] == _SCHEMA_V2
        assert on_disk["lane"] == "proof_http_poll"
        assert on_disk["chain"] == "base"
        assert "started_at" in on_disk["window"]
        assert "ended_at" in on_disk["window"]
        assert "iterations" in on_disk["window"]
        assert "blocks_seen" in on_disk["window"]
        assert "last_block_number" in on_disk["window"]
        assert "v3_swap_total" in on_disk["logs"]
        assert "v2_sync_total" in on_disk["logs"]
        assert "v3_get_logs_errors_total" in on_disk["logs"]
        assert "v2_get_logs_errors_total" in on_disk["logs"]
        assert "errors_total" in on_disk["logs"]
        assert "v3_updates_total" in on_disk["pool_price_state"]
        assert "v2_updates_total" in on_disk["pool_price_state"]
        assert "pools_tracked" in on_disk["pool_price_state"]
        assert "POOL_STATE_OK" in on_disk["verdict_partial"]
        assert "RAW_LOGS_OK" in on_disk["verdict_partial"]
        assert "RPC_OK" in on_disk["verdict_partial"]
        assert "last_updated" in on_disk
        # No-RPC: errors_total >= 1, both verdicts false
        assert on_disk["window"]["iterations"] == 0
        assert on_disk["logs"]["errors_total"] >= 1
        assert on_disk["verdict_partial"]["POOL_STATE_OK"] is False
        assert on_disk["verdict_partial"]["RAW_LOGS_OK"] is False
        # Returned artifact equals on-disk
        assert art["lane"] == on_disk["lane"]

    def test_logs_feed_registry_and_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        dest = tmp_path / "m7_proof_latest.json"

        # Two distinct blocks: B1 has 2 V3 + 1 V2; B2 has 1 V3.
        b1 = 1_000_000
        b2 = 1_000_001
        logs = {
            b1: [
                _make_v3_log(pool="0xaaa0000000000000000000000000000000000001", block=b1, log_index=0),
                _make_v3_log(pool="0xbbb0000000000000000000000000000000000002", block=b1, log_index=1),
                _make_v2_log(pool="0xccc0000000000000000000000000000000000003", block=b1, log_index=2),
            ],
            b2: [
                _make_v3_log(pool="0xddd0000000000000000000000000000000000004", block=b2, log_index=0),
            ],
        }
        eth = _FakeEth(block_sequence=[b1, b1, b2, b2, b2], logs_by_block=logs)

        class _FakeWeb3Class:
            class HTTPProvider:
                def __init__(self, *a, **kw):
                    pass

            def __init__(self, *a, **kw):
                self.eth = eth

        import sys
        fake_web3_mod = MagicMock()
        fake_web3_mod.Web3 = _FakeWeb3Class
        monkeypatch.setitem(sys.modules, "web3", fake_web3_mod)

        art = run_http_poll_proof(
            chain="base",
            duration_s=0.4,
            poll_interval_s=0.05,
            rpc_url="http://fake.local/rpc",
            artifact_path=dest,
        )

        assert dest.exists()
        assert art["window"]["blocks_seen"] >= 2, "must observe at least 2 distinct blocks"
        assert art["logs"]["v3_swap_total"] == 3
        assert art["logs"]["v2_sync_total"] == 1
        # Session delta (step 2): setup_method resets registry before each test
        assert art["pool_price_state"]["v3_updates_total"] == 3
        assert art["pool_price_state"]["v2_updates_total"] == 1
        assert art["pool_price_state"]["pools_tracked"] == 4
        assert art["verdict_partial"]["POOL_STATE_OK"] is True
        assert art["verdict_partial"]["RAW_LOGS_OK"] is True
        assert art["verdict_partial"]["RPC_OK"] is True
        # getLogs errors should be 0 (no failures injected)
        assert art["logs"]["v3_get_logs_errors_total"] == 0
        assert art["logs"]["v2_get_logs_errors_total"] == 0
        # Final artifact has economics block (step 4-8)
        assert "economics" in art
        econ = art["economics"]
        assert "gas_bps" in econ
        assert "l1_fee_bps" in econ
        assert "total_cost_bps" in econ
        assert "TWO_POOL_RESOURCE_OK" in econ
        assert "LIQUIDITY_OK" in econ
        assert "SLIPPAGE_OK" in econ
        assert "ROUNDTRIP_SIM_OK" in econ
        # With V3 + V2 pools → TWO_POOL_RESOURCE_OK should be True
        assert econ["TWO_POOL_RESOURCE_OK"] is True
        # economics verdicts promoted to verdict_partial
        assert "TWO_POOL_RESOURCE_OK" in art["verdict_partial"]
        assert art["verdict_partial"]["TWO_POOL_RESOURCE_OK"] is True

    def test_artifact_overwritten_each_iteration(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Heartbeat: artifact must exist after very short window."""
        dest = tmp_path / "m7_proof_latest.json"
        eth = _FakeEth(block_sequence=[100, 100], logs_by_block={100: []})

        class _FakeWeb3Class:
            class HTTPProvider:
                def __init__(self, *a, **kw):
                    pass

            def __init__(self, *a, **kw):
                self.eth = eth

        import sys
        fake_web3_mod = MagicMock()
        fake_web3_mod.Web3 = _FakeWeb3Class
        monkeypatch.setitem(sys.modules, "web3", fake_web3_mod)

        art = run_http_poll_proof(
            chain="base",
            duration_s=0.15,
            poll_interval_s=0.05,
            rpc_url="http://fake.local/rpc",
            artifact_path=dest,
        )
        assert dest.exists()
        assert art["window"]["iterations"] >= 1
        # No logs but RPC works
        assert art["verdict_partial"]["POOL_STATE_OK"] is False
        assert art["verdict_partial"]["RAW_LOGS_OK"] is False

    def test_never_raises_on_get_logs_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        dest = tmp_path / "m7_proof_latest.json"

        class _BlowEth:
            @property
            def block_number(self):
                return 12345

            def get_logs(self, params):
                raise RuntimeError("boom")

        class _FakeWeb3Class:
            class HTTPProvider:
                def __init__(self, *a, **kw):
                    pass

            def __init__(self, *a, **kw):
                self.eth = _BlowEth()

        import sys
        fake_web3_mod = MagicMock()
        fake_web3_mod.Web3 = _FakeWeb3Class
        monkeypatch.setitem(sys.modules, "web3", fake_web3_mod)

        art = run_http_poll_proof(
            chain="base",
            duration_s=0.1,
            poll_interval_s=0.04,
            rpc_url="http://fake.local/rpc",
            artifact_path=dest,
        )
        assert dest.exists()
        assert art["logs"]["v3_swap_total"] == 0
        assert art["logs"]["v2_sync_total"] == 0
        # Step 1: getLogs errors are explicitly tracked — not silently dropped.
        assert art["logs"]["v3_get_logs_errors_total"] >= 1
        assert art["logs"]["v2_get_logs_errors_total"] >= 1

