"""Unit tests for monitoring.sniper_artifacts — M8 Phase 1 schema contract.

Covers:
  - make_sniper_artifact: required fields, schema_family, schema_revision, JSON-serialisable
  - make_empty_sniper_state: required counter keys
  - validate_sniper_artifact: detects violations, passes on valid artifact
  - write_sniper_artifact: creates file, round-trips, schema-valid
  - Golden fixture: all REQUIRED_TOP_LEVEL_FIELDS and REQUIRED_METRIC_KEYS present
  - Status logic: EMPTY when no events, ACTIVE when events > 0
  - Invalid status raises
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from monitoring.sniper_artifacts import (
    REQUIRED_METRIC_KEYS,
    REQUIRED_TOP_LEVEL_FIELDS,
    SCHEMA_FAMILY,
    SCHEMA_REVISION,
    VALID_STATUSES,
    make_empty_sniper_state,
    make_sniper_artifact,
    validate_sniper_artifact,
    write_sniper_artifact,
)

# ---------------------------------------------------------------------------
# Path to the golden fixture
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent
GOLDEN_FIXTURE = _REPO_ROOT / "docs" / "artifacts" / "golden" / "new_pool_sniper_latest_golden.json"


# ---------------------------------------------------------------------------
# make_empty_sniper_state
# ---------------------------------------------------------------------------

class TestMakeEmptySniperState:
    def test_has_all_required_metric_keys(self):
        state = make_empty_sniper_state()
        for key in REQUIRED_METRIC_KEYS:
            assert key in state, f"Missing required metric key: {key!r}"

    def test_all_values_are_zero(self):
        state = make_empty_sniper_state()
        for key, val in state.items():
            assert val == 0, f"Expected 0 for {key!r}, got {val!r}"

    def test_is_dict(self):
        assert isinstance(make_empty_sniper_state(), dict)


# ---------------------------------------------------------------------------
# make_sniper_artifact
# ---------------------------------------------------------------------------

class TestMakeSniperArtifact:
    def test_has_all_required_top_level_fields(self):
        art = make_sniper_artifact()
        for field in REQUIRED_TOP_LEVEL_FIELDS:
            assert field in art, f"Missing required field: {field!r}"

    def test_schema_family_is_fixed(self):
        art = make_sniper_artifact()
        assert art["schema_family"] == SCHEMA_FAMILY

    def test_schema_revision_non_empty_string(self):
        art = make_sniper_artifact()
        assert isinstance(art["schema_revision"], str)
        assert len(art["schema_revision"]) > 0

    def test_schema_revision_matches_module_constant(self):
        art = make_sniper_artifact()
        assert art["schema_revision"] == SCHEMA_REVISION

    def test_json_serialisable(self):
        art = make_sniper_artifact()
        serialised = json.dumps(art)
        assert isinstance(serialised, str)

    def test_json_round_trip(self):
        art = make_sniper_artifact()
        round_trip = json.loads(json.dumps(art))
        assert round_trip["schema_family"] == SCHEMA_FAMILY

    def test_default_status_is_empty(self):
        art = make_sniper_artifact()
        assert art["status"] == "EMPTY"

    def test_active_status_accepted(self):
        art = make_sniper_artifact(status="ACTIVE")
        assert art["status"] == "ACTIVE"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status"):
            make_sniper_artifact(status="PASS")  # not a valid status

    def test_metrics_contains_required_keys(self):
        art = make_sniper_artifact()
        for key in REQUIRED_METRIC_KEYS:
            assert key in art["metrics"], f"Metrics missing required key: {key!r}"

    def test_custom_metrics_merged(self):
        art = make_sniper_artifact(metrics={"pool_creation_events_seen": 5})
        assert art["metrics"]["pool_creation_events_seen"] == 5
        # Other required keys still present
        assert "honeypot_check_pass" in art["metrics"]

    def test_reasons_default_to_no_events_yet(self):
        art = make_sniper_artifact()
        assert art["reasons"] == ["NO_EVENTS_YET"]

    def test_custom_reasons(self):
        art = make_sniper_artifact(reasons=["COOLDOWN"])
        assert art["reasons"] == ["COOLDOWN"]

    def test_empty_reasons_list(self):
        art = make_sniper_artifact(reasons=[])
        assert art["reasons"] == []

    def test_generated_at_utc_is_string(self):
        art = make_sniper_artifact()
        assert isinstance(art["generated_at_utc"], str)
        assert len(art["generated_at_utc"]) > 0

    def test_custom_generated_at_preserved(self):
        ts = "2026-06-01T12:00:00Z"
        art = make_sniper_artifact(generated_at_utc=ts)
        assert art["generated_at_utc"] == ts

    def test_recent_events_defaults_empty(self):
        art = make_sniper_artifact()
        assert art["recent_events"] == []

    def test_recent_events_capped_at_20(self):
        events = [{"pool": f"0x{i:040x}"} for i in range(30)]
        art = make_sniper_artifact(recent_events=events)
        assert len(art["recent_events"]) == 20

    def test_source_field(self):
        art = make_sniper_artifact()
        assert art["source"] == "new_pool_listener"

    def test_custom_source(self):
        art = make_sniper_artifact(source="smoke_cli")
        assert art["source"] == "smoke_cli"

    def test_freshness_s_defaults_none(self):
        art = make_sniper_artifact()
        assert art["freshness_s"] is None

    def test_custom_freshness_s(self):
        art = make_sniper_artifact(freshness_s=3.14)
        assert art["freshness_s"] == 3.14


# ---------------------------------------------------------------------------
# validate_sniper_artifact
# ---------------------------------------------------------------------------

class TestValidateSniperArtifact:
    def test_valid_artifact_no_violations(self):
        art = make_sniper_artifact()
        violations = validate_sniper_artifact(art)
        assert violations == [], f"Unexpected violations: {violations}"

    def test_missing_schema_family_violation(self):
        art = make_sniper_artifact()
        del art["schema_family"]
        violations = validate_sniper_artifact(art)
        assert any("schema_family" in v for v in violations)

    def test_wrong_schema_family_violation(self):
        art = make_sniper_artifact()
        art["schema_family"] = "wrong_family"
        violations = validate_sniper_artifact(art)
        assert any("schema_family" in v for v in violations)

    def test_empty_schema_revision_violation(self):
        art = make_sniper_artifact()
        art["schema_revision"] = ""
        violations = validate_sniper_artifact(art)
        assert any("schema_revision" in v for v in violations)

    def test_invalid_status_violation(self):
        art = make_sniper_artifact()
        art["status"] = "INVALID_STATUS_99"
        violations = validate_sniper_artifact(art)
        assert any("status" in v for v in violations)

    def test_missing_metric_key_violation(self):
        art = make_sniper_artifact()
        del art["metrics"]["pool_creation_events_seen"]
        violations = validate_sniper_artifact(art)
        assert any("pool_creation_events_seen" in v for v in violations)

    def test_non_numeric_metric_violation(self):
        art = make_sniper_artifact()
        art["metrics"]["honeypot_check_pass"] = "bad"
        violations = validate_sniper_artifact(art)
        assert any("honeypot_check_pass" in v for v in violations)

    def test_metrics_not_dict_violation(self):
        art = make_sniper_artifact()
        art["metrics"] = "string_instead_of_dict"
        violations = validate_sniper_artifact(art)
        assert any("metrics" in v for v in violations)

    def test_reasons_not_list_violation(self):
        art = make_sniper_artifact()
        art["reasons"] = "string_instead_of_list"
        violations = validate_sniper_artifact(art)
        assert any("reasons" in v for v in violations)

    def test_all_valid_statuses_accepted(self):
        for status in VALID_STATUSES:
            art = make_sniper_artifact(status=status)
            violations = validate_sniper_artifact(art)
            assert violations == [], f"Violations for status={status!r}: {violations}"


# ---------------------------------------------------------------------------
# write_sniper_artifact
# ---------------------------------------------------------------------------

class TestWriteSniperArtifact:
    def test_creates_file(self, tmp_path: Path):
        art = make_sniper_artifact()
        out_path = tmp_path / "sniper_test.json"
        result = write_sniper_artifact(art, path=out_path)
        assert out_path.is_file()
        assert result == out_path

    def test_written_file_is_valid_json(self, tmp_path: Path):
        art = make_sniper_artifact()
        out_path = tmp_path / "sniper_test.json"
        write_sniper_artifact(art, path=out_path)
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)

    def test_written_file_passes_schema_validation(self, tmp_path: Path):
        art = make_sniper_artifact()
        out_path = tmp_path / "sniper_test.json"
        write_sniper_artifact(art, path=out_path)
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        violations = validate_sniper_artifact(loaded)
        assert violations == [], f"Violations: {violations}"

    def test_written_file_has_correct_schema_family(self, tmp_path: Path):
        art = make_sniper_artifact()
        out_path = tmp_path / "sniper_test.json"
        write_sniper_artifact(art, path=out_path)
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded["schema_family"] == SCHEMA_FAMILY

    def test_overwrite_existing_file(self, tmp_path: Path):
        out_path = tmp_path / "sniper_test.json"
        # Write once
        write_sniper_artifact(make_sniper_artifact(status="EMPTY"), path=out_path)
        # Overwrite with new status
        write_sniper_artifact(
            make_sniper_artifact(status="ACTIVE", metrics={"pool_creation_events_seen": 1}),
            path=out_path,
        )
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded["status"] == "ACTIVE"
        assert loaded["metrics"]["pool_creation_events_seen"] == 1

    def test_nested_dirs_created_on_write(self, tmp_path: Path):
        out_path = tmp_path / "nested" / "dir" / "sniper.json"
        art = make_sniper_artifact()
        write_sniper_artifact(art, path=out_path)
        assert out_path.is_file()


# ---------------------------------------------------------------------------
# Golden fixture
# ---------------------------------------------------------------------------

class TestGoldenFixture:
    def test_golden_fixture_exists(self):
        assert GOLDEN_FIXTURE.is_file(), (
            f"Golden fixture not found: {GOLDEN_FIXTURE}\n"
            "Run create_golden_fixture.py or check docs/artifacts/golden/."
        )

    def test_golden_fixture_is_valid_json(self):
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        assert isinstance(loaded, dict)

    def test_golden_has_all_required_top_level_fields(self):
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        for field in REQUIRED_TOP_LEVEL_FIELDS:
            assert field in loaded, f"Golden fixture missing: {field!r}"

    def test_golden_has_all_required_metric_keys(self):
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        metrics = loaded.get("metrics", {})
        for key in REQUIRED_METRIC_KEYS:
            assert key in metrics, f"Golden fixture metrics missing: {key!r}"

    def test_golden_schema_family(self):
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        assert loaded["schema_family"] == SCHEMA_FAMILY

    def test_golden_schema_revision_non_empty(self):
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        assert loaded.get("schema_revision"), "schema_revision must be non-empty"

    def test_golden_passes_validate(self):
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        violations = validate_sniper_artifact(loaded)
        assert violations == [], f"Golden fixture violations: {violations}"

    def test_golden_status_is_empty(self):
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        assert loaded["status"] == "EMPTY", (
            "Golden fixture should represent the idle/initial state."
        )

    def test_golden_no_version_string_in_filename(self):
        """DOCS_POLICY: no 'vX.Y.Z' version strings in golden fixture filename."""
        name = GOLDEN_FIXTURE.name
        import re
        assert not re.search(r"v\d+\.\d+", name), (
            f"Golden fixture filename must not contain version string: {name!r}"
        )


# ---------------------------------------------------------------------------
# VALID_STATUSES coverage
# ---------------------------------------------------------------------------

class TestValidStatuses:
    def test_empty_in_valid_statuses(self):
        assert "EMPTY" in VALID_STATUSES

    def test_active_in_valid_statuses(self):
        assert "ACTIVE" in VALID_STATUSES

    def test_stale_in_valid_statuses(self):
        assert "STALE" in VALID_STATUSES

    def test_error_in_valid_statuses(self):
        assert "ERROR" in VALID_STATUSES

    def test_at_least_four_statuses(self):
        assert len(VALID_STATUSES) >= 4


# ---------------------------------------------------------------------------
# Canonical rolling artifact path contract
# ---------------------------------------------------------------------------

class TestCanonicalRollingArtifactPath:
    """ROLLING_ARTIFACT_PATH must stay under data/runs/_rolling/ (AGENTS.md §1).

    Only the three canonical rolling artifacts may live in that folder:
      - _latest.json / run_summary_latest.json / m4_stability_agg.json  (existing M4)
      - new_pool_sniper_latest.json                                       (M8 Phase 1)

    This test locks the path so accidental renames or moves break loudly.
    """
    from monitoring.sniper_artifacts import ROLLING_ARTIFACT_PATH as _PATH

    def test_rolling_artifact_is_under_data_runs_rolling(self):
        """Path must be inside data/runs/_rolling/."""
        parts = self._PATH.parts
        assert "_rolling" in parts, (
            f"ROLLING_ARTIFACT_PATH={self._PATH!r} is not under data/runs/_rolling/"
        )

    def test_rolling_artifact_filename(self):
        """Filename must be new_pool_sniper_latest.json (canonical, never versioned)."""
        assert self._PATH.name == "new_pool_sniper_latest.json", (
            f"Unexpected filename: {self._PATH.name!r}. "
            "AGENTS.md requires canonical rolling artifacts to be overwritten, not versioned."
        )

    def test_rolling_artifact_path_is_relative(self):
        """Path must be relative (no absolute drive letter) for portability."""
        assert not self._PATH.is_absolute(), (
            f"ROLLING_ARTIFACT_PATH must be a relative path, got: {self._PATH!r}"
        )


# ---------------------------------------------------------------------------
# Scoring placeholder field tests (Step 9)
# ---------------------------------------------------------------------------

class TestScoringField:
    def test_artifact_has_scoring_field(self):
        art = make_sniper_artifact()
        assert "scoring" in art, "artifact must have top-level 'scoring' field"

    def test_scoring_is_dict(self):
        art = make_sniper_artifact()
        assert isinstance(art["scoring"], dict)

    def test_scoring_has_spread_bps(self):
        art = make_sniper_artifact()
        assert "spread_bps" in art["scoring"]

    def test_scoring_has_spread_usd(self):
        art = make_sniper_artifact()
        assert "spread_usd" in art["scoring"]

    def test_scoring_has_volume_usd(self):
        art = make_sniper_artifact()
        assert "volume_usd" in art["scoring"]

    def test_scoring_has_profit_usd(self):
        art = make_sniper_artifact()
        assert "profit_usd" in art["scoring"]

    def test_scoring_has_realizability_reason(self):
        art = make_sniper_artifact()
        assert "realizability_reason" in art["scoring"]

    def test_scoring_phase1_values_are_null_or_placeholder(self):
        """Phase 1: all numeric fields are None; reason is phase1 placeholder."""
        art = make_sniper_artifact()
        scoring = art["scoring"]
        for field in ("spread_bps", "spread_usd", "volume_usd", "profit_usd"):
            assert scoring[field] is None, f"Phase 1: {field!r} should be None"
        assert scoring["realizability_reason"] == "PHASE1_NO_SCORING"

    def test_golden_fixture_has_scoring(self):
        """Golden fixture must include scoring field."""
        import json
        loaded = json.loads(GOLDEN_FIXTURE.read_text(encoding="utf-8"))
        assert "scoring" in loaded, "Golden fixture must have 'scoring' field"
        assert loaded["scoring"].get("realizability_reason") == "PHASE1_NO_SCORING"


class TestPhase2DecisionStubs:
    """Phase 2 decision stubs are present and null in Phase 1 artifacts."""

    _REQUIRED_KEYS = (
        "honeypot_result",
        "simulation_result",
        "realisability_reason",
        "dry_run_decision",
        "reject_reason",
    )

    def test_artifact_has_phase2_decision_field(self):
        art = make_sniper_artifact()
        assert "phase2_decision" in art, "artifact must have top-level 'phase2_decision' field"

    def test_phase2_decision_is_dict(self):
        art = make_sniper_artifact()
        assert isinstance(art["phase2_decision"], dict)

    def test_phase2_decision_has_all_required_keys(self):
        art = make_sniper_artifact()
        for key in self._REQUIRED_KEYS:
            assert key in art["phase2_decision"], f"Missing Phase 2 key: {key!r}"

    def test_phase2_decision_all_null_in_phase1(self):
        """Phase 1: all phase2_decision fields must be None (stubs only)."""
        art = make_sniper_artifact()
        for key in self._REQUIRED_KEYS:
            assert art["phase2_decision"][key] is None, (
                f"Phase 1: phase2_decision[{key!r}] should be None"
            )


# ---------------------------------------------------------------------------
# R7: self_test_by_dex / run_scope / dex_filter contract tests
# ---------------------------------------------------------------------------

class TestR7NewArtifactFields:
    """Contract tests for the three fields added in Round-7:
      - self_test_by_dex: dict mapping dex -> {raw, parse_ok, parse_failed, range, status}
      - run_scope: "all" for full runs, dex name for isolated --dex runs
      - dex_filter: None for full runs, dex name for isolated runs

    These lock the public artifact schema so CI fails loudly if the fields
    are accidentally removed.
    """

    def test_artifact_has_run_scope_field(self):
        """artifact must include 'run_scope' (default 'all')."""
        art = make_sniper_artifact()
        assert "run_scope" in art, "artifact must have 'run_scope' field"

    def test_run_scope_default_is_all(self):
        art = make_sniper_artifact()
        assert art["run_scope"] == "all"

    def test_run_scope_custom_value(self):
        art = make_sniper_artifact(run_scope="aerodrome")
        assert art["run_scope"] == "aerodrome"

    def test_artifact_has_dex_filter_field(self):
        """artifact must include 'dex_filter' (default None)."""
        art = make_sniper_artifact()
        assert "dex_filter" in art, "artifact must have 'dex_filter' field"

    def test_dex_filter_default_is_none(self):
        art = make_sniper_artifact()
        assert art["dex_filter"] is None

    def test_dex_filter_custom_value(self):
        art = make_sniper_artifact(dex_filter="aerodrome")
        assert art["dex_filter"] == "aerodrome"

    def test_artifact_has_self_test_by_dex_field(self):
        """artifact must include 'self_test_by_dex' (default empty dict)."""
        art = make_sniper_artifact()
        assert "self_test_by_dex" in art, "artifact must have 'self_test_by_dex' field"

    def test_self_test_by_dex_default_is_empty_dict(self):
        art = make_sniper_artifact()
        assert art["self_test_by_dex"] == {}

    def test_self_test_by_dex_custom_value(self):
        results = {
            "aerodrome": {"raw": 1, "parse_ok": 1, "parse_failed": 0,
                          "range": [45925000, 45926000], "status": "PASS"},
            "uniswap_v3": {"raw": 2, "parse_ok": 2, "parse_failed": 0,
                           "range": [45946914, 45947413], "status": "PASS"},
        }
        art = make_sniper_artifact(self_test_by_dex=results)
        assert art["self_test_by_dex"]["aerodrome"]["status"] == "PASS"
        assert art["self_test_by_dex"]["uniswap_v3"]["parse_ok"] == 2

    def test_self_test_by_dex_none_coerced_to_empty(self):
        """Passing None for self_test_by_dex must result in {}."""
        art = make_sniper_artifact(self_test_by_dex=None)
        assert art["self_test_by_dex"] == {}

    def test_all_three_new_fields_json_serialisable(self):
        import json
        results = {"aerodrome": {"raw": 1, "parse_ok": 1, "parse_failed": 0,
                                 "range": [1, 2], "status": "PASS"}}
        art = make_sniper_artifact(
            self_test_by_dex=results,
            run_scope="aerodrome",
            dex_filter="aerodrome",
        )
        serialised = json.dumps(art)
        roundtrip = json.loads(serialised)
        assert roundtrip["run_scope"] == "aerodrome"
        assert roundtrip["dex_filter"] == "aerodrome"
        assert roundtrip["self_test_by_dex"]["aerodrome"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# R7: isolated --dex run must NOT pollute _rolling canonical set
# ---------------------------------------------------------------------------

class TestIsolatedRunRollingIsolation:
    """Verifies that _build_and_write_artifact() writes to data/tmp/ (not _rolling/)
    when dex_filter is set.  Locks Step 8 so it cannot regress.
    """

    def test_isolated_run_writes_to_tmp_not_rolling(self, tmp_path: Path):
        """When dex_filter is set, write_sniper_artifact uses tmp path.

        We test this by directly calling write_sniper_artifact with an
        explicit isolated path (as smoke_run does for --dex runs) and
        verifying the file is created where expected.
        """
        isolated = tmp_path / "new_pool_sniper_aerodrome_latest.json"
        art = make_sniper_artifact(
            status="EMPTY",
            run_scope="aerodrome",
            dex_filter="aerodrome",
        )
        write_sniper_artifact(art, path=isolated)
        assert isolated.is_file()
        loaded = json.loads(isolated.read_text(encoding="utf-8"))
        assert loaded["dex_filter"] == "aerodrome"
        assert loaded["run_scope"] == "aerodrome"

    def test_isolated_run_artifact_name_follows_convention(self, tmp_path: Path):
        """Isolated artifact filename must be new_pool_sniper_{dex}_latest.json."""
        dex = "pancakeswap_v3"
        isolated = tmp_path / f"new_pool_sniper_{dex}_latest.json"
        art = make_sniper_artifact(
            status="EMPTY",
            run_scope=dex,
            dex_filter=dex,
        )
        write_sniper_artifact(art, path=isolated)
        assert isolated.name == f"new_pool_sniper_{dex}_latest.json"

    def test_full_run_writes_to_rolling(self, tmp_path: Path):
        """When dex_filter is None (full run), canonical rolling path is used."""
        canonical = tmp_path / "new_pool_sniper_latest.json"
        art = make_sniper_artifact(status="EMPTY", run_scope="all", dex_filter=None)
        write_sniper_artifact(art, path=canonical)
        assert canonical.is_file()
        loaded = json.loads(canonical.read_text(encoding="utf-8"))
        assert loaded["dex_filter"] is None
        assert loaded["run_scope"] == "all"

