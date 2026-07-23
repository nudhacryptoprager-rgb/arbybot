"""Streaming pipeline batch helpers."""
from __future__ import annotations

import json
from pathlib import Path

from core.pipeline_streaming import (
    m81_streaming_cli_args,
    resolve_sniper_minutes,
    resolve_streaming_batches,
)
from m8.discovery.streaming_handoff import (
    extract_sniper_token_addresses,
    write_streaming_batch_manifest,
)


def test_streaming_caps_sniper_minutes():
    assert resolve_sniper_minutes(45, streaming=True, batch_minutes=15) == 15
    assert resolve_sniper_minutes(45, streaming=False) == 45


def test_streaming_batches_split_total():
    assert resolve_streaming_batches(45, batch_minutes=15) == [15, 15, 15]


def test_extract_sniper_tokens(tmp_path: Path):
    sniper = tmp_path / "sniper.json"
    sniper.write_text(
        json.dumps(
            {
                "recent_events": [
                    {"token0": "0x" + "1" * 40, "token1": "0x" + "2" * 40},
                ]
            }
        ),
        encoding="utf-8",
    )
    addrs = extract_sniper_token_addresses(sniper)
    assert "0x" + "1" * 40 in addrs
    assert "0x" + "2" * 40 in addrs


def test_write_manifest_emits_subset_file(tmp_path: Path):
    sniper = tmp_path / "sniper.json"
    sniper.write_text(
        json.dumps(
            {
                "recent_events": [
                    {"token0": "0x" + "3" * 40, "token1": "0x" + "4" * 40},
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = write_streaming_batch_manifest(
        session_id="sess-1",
        batch_index=2,
        batch_minutes=15,
        sniper_artifact=str(sniper),
        output_path=tmp_path / "latest.json",
        immutable_path=tmp_path / "batch2.json",
        token_subset_path=tmp_path / "subset2.json",
    )
    assert manifest["batch_index"] == 2
    assert Path(manifest["token_subset_file"]).is_file()
    args = m81_streaming_cli_args(batch_index=2)
    assert "--streaming-batch-index" in args
    assert "--publish-rolling" in args
