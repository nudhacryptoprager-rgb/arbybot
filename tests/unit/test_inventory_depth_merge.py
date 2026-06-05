"""Tests for verified/bridge depth merge."""
import json
import tempfile
import unittest
from pathlib import Path

from m9.graph_arb.inventory_depth import merge_depth_from_bridge, merge_verified_inventory_from_bridge


class TestInventoryDepthMerge(unittest.TestCase):
    def test_merge_by_pool_address(self) -> None:
        bridge = [
            {
                "route_id": "b1",
                "pool_address": "0xabc",
                "effective_depth_usd": 500.0,
                "pool_quality_state": "DEPTH_OK",
            },
        ]
        verified = [{"route_id": "v1", "pool_address": "0xAbC"}]
        stats = merge_depth_from_bridge(verified, bridge)
        self.assertEqual(stats["merged"], 1)
        self.assertEqual(verified[0]["effective_depth_usd"], 500.0)
        self.assertEqual(verified[0]["pool_quality_state"], "DEPTH_OK")

    def test_merge_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vpath = Path(tmp) / "verified.json"
            bpath = Path(tmp) / "bridge.json"
            bpath.write_text(
                json.dumps(
                    {
                        "active_routes": [
                            {
                                "route_id": "r1",
                                "pool_address": "0x1",
                                "effective_depth_usd": 100.0,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            vpath.write_text(
                json.dumps(
                    {
                        "active_routes": [
                            {"route_id": "r1", "pool_address": "0x1"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stats = merge_verified_inventory_from_bridge(
                str(vpath), str(bpath), write=True
            )
            self.assertEqual(stats["with_depth_after"], 1)
            data = json.loads(vpath.read_text(encoding="utf-8"))
            self.assertEqual(data["active_routes"][0]["effective_depth_usd"], 100.0)


if __name__ == "__main__":
    unittest.main()
