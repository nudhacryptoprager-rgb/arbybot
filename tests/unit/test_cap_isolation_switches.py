"""R28.27: Tests for cap-isolation toggles in run_scan_real.py.

Modeled after test_quotes_runtime_filter_switches.py — same ENV/config/default
priority chain applied to hard caps (discovery_max_pairs, rt_max_candidates, rt_top_n).
"""

import os

from strategy.jobs.run_scan_real import _get_cap_isolation_switches


# --- Default: all caps ACTIVE (nothing uncapped) ---

def test_cap_isolation_default_all_active(monkeypatch):
    monkeypatch.delenv("ARBY_UNCAP_ALL", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_DISCOVERY_MAX_PAIRS", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_MAX_CANDIDATES", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_TOP_N", raising=False)

    switches = _get_cap_isolation_switches({})

    assert switches == {
        "uncap_discovery_max_pairs": False,
        "uncap_rt_max_candidates": False,
        "uncap_rt_top_n": False,
    }


# --- Global uncap via config ---

def test_cap_isolation_global_config_uncap():
    switches = _get_cap_isolation_switches({"uncap_all": True})

    assert switches == {
        "uncap_discovery_max_pairs": True,
        "uncap_rt_max_candidates": True,
        "uncap_rt_top_n": True,
    }


# --- Global uncap via env var ---

def test_cap_isolation_global_env_uncap(monkeypatch):
    monkeypatch.setenv("ARBY_UNCAP_ALL", "1")
    monkeypatch.delenv("ARBY_UNCAP_DISCOVERY_MAX_PAIRS", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_MAX_CANDIDATES", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_TOP_N", raising=False)

    switches = _get_cap_isolation_switches({})

    assert switches == {
        "uncap_discovery_max_pairs": True,
        "uncap_rt_max_candidates": True,
        "uncap_rt_top_n": True,
    }


# --- Individual config toggles ---

def test_cap_isolation_individual_config_toggle():
    switches = _get_cap_isolation_switches({
        "uncap_discovery_max_pairs": True,
        "uncap_rt_max_candidates": False,
        "uncap_rt_top_n": False,
    })

    assert switches["uncap_discovery_max_pairs"] is True
    assert switches["uncap_rt_max_candidates"] is False
    assert switches["uncap_rt_top_n"] is False


# --- Individual env var overrides config ---

def test_cap_isolation_env_overrides_config(monkeypatch):
    monkeypatch.setenv("ARBY_UNCAP_RT_TOP_N", "true")
    monkeypatch.delenv("ARBY_UNCAP_ALL", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_DISCOVERY_MAX_PAIRS", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_MAX_CANDIDATES", raising=False)

    switches = _get_cap_isolation_switches({"uncap_rt_max_candidates": False})

    assert switches["uncap_discovery_max_pairs"] is False
    assert switches["uncap_rt_max_candidates"] is False
    assert switches["uncap_rt_top_n"] is True


# --- Mixed: env global + individual config ---

def test_cap_isolation_env_global_overrides_individual(monkeypatch):
    monkeypatch.setenv("ARBY_UNCAP_ALL", "yes")
    monkeypatch.delenv("ARBY_UNCAP_DISCOVERY_MAX_PAIRS", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_MAX_CANDIDATES", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_TOP_N", raising=False)

    # Even with individual configs set to False, global env wins
    switches = _get_cap_isolation_switches({
        "uncap_discovery_max_pairs": False,
        "uncap_rt_top_n": False,
    })

    assert switches["uncap_discovery_max_pairs"] is True
    assert switches["uncap_rt_max_candidates"] is True
    assert switches["uncap_rt_top_n"] is True


# --- Truthy value variants (matching _env_flag_enabled contract) ---

def test_cap_isolation_truthy_variants(monkeypatch):
    monkeypatch.delenv("ARBY_UNCAP_ALL", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_DISCOVERY_MAX_PAIRS", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_TOP_N", raising=False)

    for val in ("1", "true", "True", "TRUE", "yes", "on", "ON"):
        monkeypatch.setenv("ARBY_UNCAP_RT_MAX_CANDIDATES", val)
        switches = _get_cap_isolation_switches({})
        assert switches["uncap_rt_max_candidates"] is True, f"Failed for value: {val}"


def test_cap_isolation_falsy_variants(monkeypatch):
    monkeypatch.delenv("ARBY_UNCAP_ALL", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_DISCOVERY_MAX_PAIRS", raising=False)
    monkeypatch.delenv("ARBY_UNCAP_RT_TOP_N", raising=False)

    for val in ("0", "false", "no", "off", "", "  "):
        monkeypatch.setenv("ARBY_UNCAP_RT_MAX_CANDIDATES", val)
        switches = _get_cap_isolation_switches({})
        assert switches["uncap_rt_max_candidates"] is False, f"Failed for value: {val}"
