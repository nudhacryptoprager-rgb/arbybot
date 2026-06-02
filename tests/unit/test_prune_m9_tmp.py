"""Tests for scripts/prune_m9_tmp.py."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.prune_m9_tmp import collect_prune_targets


def test_collect_prune_targets_respects_tmp_keep(tmp_path, monkeypatch):
    manifest = tmp_path / "m9_active_manifest.yaml"
    manifest.write_text(
        """
tmp_stale_globs:
  - data/tmp/m9_graph_*.json
tmp_keep:
  - data/tmp/m9_config_audit.json
""",
        encoding="utf-8",
    )
    repo = tmp_path
    (repo / "data" / "tmp").mkdir(parents=True)
    stale = repo / "data" / "tmp" / "m9_graph_test.json"
    stale.write_text("{}", encoding="utf-8")
    keep = repo / "data" / "tmp" / "m9_config_audit.json"
    keep.write_text("{}", encoding="utf-8")

    import scripts.prune_m9_tmp as mod

    monkeypatch.setattr(mod, "REPO_ROOT", repo)
    targets = collect_prune_targets(manifest)
    rels = {str(t.relative_to(repo)).replace("\\", "/") for t in targets}
    assert "data/tmp/m9_graph_test.json" in rels
    assert "data/tmp/m9_config_audit.json" not in rels
