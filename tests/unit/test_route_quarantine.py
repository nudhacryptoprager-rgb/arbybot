import json
import tempfile
import unittest
from pathlib import Path

from m9.graph_arb.route_quarantine import (
    parse_max_cycles_per_length_env,
    resolve_diagnostic_quarantine_pools,
    update_revert_quarantine_from_diagnostic,
)


class TestRouteQuarantine(unittest.TestCase):
    def test_resolve_diagnostic_pools(self) -> None:
        diag = {
            "rows": [
                {"ok": False, "reject_reason": "QUOTE_REVERT", "pool_address": "0xABC"},
                {"ok": True, "pool_address": "0xDEF"},
            ]
        }
        pools = resolve_diagnostic_quarantine_pools(diag)
        self.assertEqual(pools, {"0xabc"})

    def test_parse_length_caps(self) -> None:
        self.assertEqual(parse_max_cycles_per_length_env("3:20,4:6"), {3: 20, 4: 6})

    def test_update_quarantine_merges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            diag = Path(tmp) / "diag.json"
            out = Path(tmp) / "q.json"
            diag.write_text(
                json.dumps(
                    {
                        "rows": [
                            {
                                "ok": False,
                                "reject_reason": "QUOTE_CONFIG_MISSING",
                                "pool_address": "0x1",
                                "route_id": "r1",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            stats = update_revert_quarantine_from_diagnostic(
                str(diag), output_path=str(out), merge=False
            )
            self.assertEqual(stats["added"], 1)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(data["routes"]), 1)


if __name__ == "__main__":
    unittest.main()
