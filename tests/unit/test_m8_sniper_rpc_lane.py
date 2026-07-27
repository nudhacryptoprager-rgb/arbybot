"""M8 sniper discovery RPC lane — resolution + getLogs failover."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.rpc_urls import resolve_sniper_rpc_lane
from monitoring.sniper_funnel import FunnelTracker
from m8.runtime.smoke_run import SniperRpcLane, _single_get_logs


def _make_lane(
    primary_effects,
    secondary_effects=None,
    *,
    funnel: FunnelTracker | None = None,
) -> SniperRpcLane:
    funnel = funnel or FunnelTracker()

    def _w3(effects):
        w3 = MagicMock()
        w3.eth.get_logs.side_effect = effects
        return w3

    secondary = None
    if secondary_effects is not None:
        secondary = _w3(secondary_effects)

    return SniperRpcLane(
        w3_primary=_w3(primary_effects),
        w3_secondary=secondary,
        primary_provider="alchemy",
        secondary_provider="drpc" if secondary is not None else None,
        funnel=funnel,
    )


class TestResolveSniperRpcLane(unittest.TestCase):
    def test_priority_sniper_primary_over_productive(self):
        env = {
            "BASE_SNIPER_RPC_PRIMARY": "https://lb.drpc.live/base/sniper_pri",
            "BASE_RPC_PRIMARY": "https://base-mainnet.g.alchemy.com/v2/key",
            "BASE_RPC_SECONDARY": "https://lb.drpc.live/base/sec",
        }
        pri, pri_p, sec, sec_p, diag = resolve_sniper_rpc_lane(
            chain_id=8453, network="base", env=env
        )
        self.assertIn("drpc.live", pri)
        self.assertEqual(pri_p, "drpc")
        self.assertEqual(diag["primary_source"], "BASE_SNIPER_RPC_PRIMARY")
        self.assertIn("alchemy", sec or "")
        self.assertEqual(sec_p, "alchemy")

    def test_secondary_before_primary_when_no_sniper_env(self):
        env = {
            "BASE_RPC_SECONDARY": "https://lb.drpc.live/base/sec",
            "BASE_RPC_PRIMARY": "https://base-mainnet.g.alchemy.com/v2/key",
        }
        pri, pri_p, sec, sec_p, diag = resolve_sniper_rpc_lane(
            chain_id=8453, network="base", env=env
        )
        self.assertIn("drpc.live", pri)
        self.assertEqual(diag["primary_source"], "BASE_RPC_SECONDARY")
        self.assertIn("alchemy", sec or "")

    def test_cli_override_wins(self):
        env = {
            "BASE_SNIPER_RPC_PRIMARY": "https://lb.drpc.live/base/sniper_pri",
            "BASE_RPC_SECONDARY": "https://lb.drpc.live/base/sec",
        }
        pri, _pri_p, _sec, _sec_p, diag = resolve_sniper_rpc_lane(
            chain_id=8453,
            network="base",
            env=env,
            override="https://lb.drpc.live/base/cli",
        )
        self.assertIn("/cli", pri)
        self.assertEqual(diag["primary_source"], "cli_override")


class TestSniperGetLogsFailover(unittest.TestCase):
    def test_primary_400_failover_secondary(self):
        funnel = FunnelTracker()
        lane = _make_lane(
            [Exception("400 Bad Request: block range too large")],
            [["log_from_secondary"]],
            funnel=funnel,
        )
        logs, had_err, _ = lane.get_logs(
            {"fromBlock": 100, "toBlock": 199, "address": "0xabc"}
        )
        self.assertFalse(had_err)
        self.assertEqual(logs, ["log_from_secondary"])
        snap = funnel.snapshot()
        self.assertEqual(snap["sniper_rpc_failover_count"], 1)
        self.assertGreaterEqual(snap["getlogs_400_count"], 1)

    def test_primary_429_failover_secondary(self):
        funnel = FunnelTracker()
        lane = _make_lane(
            [
                Exception("429 Too Many Requests"),
                Exception("429 Too Many Requests"),
            ],
            [["ok"]],
            funnel=funnel,
        )
        logs, had_err, _ = lane.get_logs({"fromBlock": 1, "toBlock": 2})
        self.assertFalse(had_err)
        self.assertEqual(logs, ["ok"])
        self.assertEqual(funnel.snapshot()["getlogs_429_count"], 1)
        self.assertEqual(funnel.snapshot()["sniper_rpc_failover_count"], 1)

    def test_non_failover_error_stays_on_primary(self):
        funnel = FunnelTracker()
        lane = _make_lane(
            [Exception("invalid topic filter shape")],
            [["should_not_run"]],
            funnel=funnel,
        )
        logs, had_err, err = lane.get_logs({"fromBlock": 1, "toBlock": 2})
        self.assertTrue(had_err)
        self.assertEqual(logs, [])
        self.assertIn("invalid topic", err)
        self.assertEqual(funnel.snapshot()["sniper_rpc_failover_count"], 0)
        lane.w3_secondary.eth.get_logs.assert_not_called()

    def test_408_retries_before_failover(self):
        w3 = MagicMock()
        w3.eth.get_logs.side_effect = [
            Exception("408 Request Timeout"),
            ["log_after_retry"],
        ]
        logs, err = _single_get_logs(w3, {"fromBlock": 1, "toBlock": 2}, retries=2)
        self.assertIsNone(err)
        self.assertEqual(logs, ["log_after_retry"])
        self.assertEqual(w3.eth.get_logs.call_count, 2)

    def test_400_range_split_depth_is_bounded(self):
        from m8.runtime import smoke_run as smoke_mod

        funnel = FunnelTracker()
        lane = _make_lane(
            [Exception("400 Bad Request: block range too large")],
            funnel=funnel,
        )
        with unittest.mock.patch.object(smoke_mod, "_MAX_GETLOGS_SPLIT_DEPTH", 1):
            logs, had_err, err = lane._get_logs_lane(
                {"fromBlock": 1, "toBlock": 200},
                use_secondary=False,
                split_depth=1,
            )
        self.assertTrue(had_err)
        self.assertEqual(logs, [])
        self.assertIn("split depth exhausted", err)


class TestSniperArtifactPreserve(unittest.TestCase):
    def test_preserve_recent_events_on_rpc_error(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from m8.runtime.smoke_run import _load_preserved_recent_events_dicts

        with tempfile.TemporaryDirectory() as td:
            art = Path(td) / "new_pool_sniper_latest.json"
            prior = {
                "status": "ACTIVE",
                "recent_events": [{"event_id": "e1", "pool_address": "0xabc"}],
            }
            art.write_text(json.dumps(prior), encoding="utf-8")
            with patch("m8.runtime.smoke_run._ROLLING_SNIPER_ARTIFACT", art):
                preserved = _load_preserved_recent_events_dicts("RPC_ERROR", [])
                self.assertIsNotNone(preserved)
                self.assertEqual(len(preserved), 1)
                self.assertIsNone(_load_preserved_recent_events_dicts("ACTIVE", []))


if __name__ == "__main__":
    unittest.main()
