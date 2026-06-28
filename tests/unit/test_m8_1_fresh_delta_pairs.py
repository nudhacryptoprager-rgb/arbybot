"""Tests for M8.1 fresh_delta pair enumeration."""
from __future__ import annotations

from types import SimpleNamespace

from m8_1.stable_anchor.fresh_delta_pairs import enumerate_fresh_delta_pairs


def _mock_cfg():
  tokens = {
      "USDC": SimpleNamespace(address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", decimals=6),
      "WETH": SimpleNamespace(address="0x4200000000000000000000000000000000000006", decimals=18),
  }
  return SimpleNamespace(tokens=tokens)


def test_fresh_delta_pairs_for_non_config_token():
    import json
    import tempfile
    from pathlib import Path

    exotic = "0x" + "a" * 40
    with tempfile.TemporaryDirectory() as tmp:
        wl = Path(tmp) / "wl.json"
        wl.write_text(
            json.dumps({"tokens": {exotic: {"symbol": "NEW", "decimals": 18}}}),
            encoding="utf-8",
        )
        pairs = enumerate_fresh_delta_pairs(
            _mock_cfg(),
            {exotic},
            w3=None,
            watchlist_path=wl,
            registry_path=Path(tmp) / "missing.json",
        )
        assert len(pairs) >= 2
        addrs = {p[0].address for p in pairs} | {p[1].address for p in pairs}
        assert exotic in addrs


def test_fresh_delta_pairs_dedup_by_address_not_symbol():
    import json
    import tempfile
    from pathlib import Path

    exotic_a = "0x" + "a" * 40
    exotic_b = "0x" + "b" * 40
    with tempfile.TemporaryDirectory() as tmp:
        wl = Path(tmp) / "wl.json"
        wl.write_text(
            json.dumps(
                {
                    "tokens": {
                        exotic_a: {"symbol": "SAME", "decimals": 18},
                        exotic_b: {"symbol": "SAME", "decimals": 18},
                    }
                }
            ),
            encoding="utf-8",
        )
        pairs = enumerate_fresh_delta_pairs(
            _mock_cfg(),
            {exotic_a, exotic_b},
            w3=None,
            watchlist_path=wl,
            registry_path=Path(tmp) / "missing.json",
        )
        exotic_addrs = {
            p[0].address if p[0].address in {exotic_a, exotic_b} else p[1].address
            for p in pairs
        }
        assert exotic_a in exotic_addrs
        assert exotic_b in exotic_addrs
