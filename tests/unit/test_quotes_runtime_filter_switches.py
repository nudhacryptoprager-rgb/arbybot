import os

from strategy.quotes import _get_runtime_filter_switches


def test_runtime_filter_switches_default_enabled(monkeypatch):
    monkeypatch.delenv("ARBY_DISABLE_RUNTIME_SUPPRESSION", raising=False)
    monkeypatch.delenv("ARBY_DISABLE_RUNTIME_QUARANTINE", raising=False)
    monkeypatch.delenv("ARBY_DISABLE_RUNTIME_DISABLED", raising=False)

    flags = _get_runtime_filter_switches({})

    assert flags == {
        "quarantine_enabled": True,
        "runtime_disabled_enabled": True,
    }


def test_runtime_filter_switches_global_config_disable():
    flags = _get_runtime_filter_switches({"disable_runtime_suppression": True})

    assert flags == {
        "quarantine_enabled": False,
        "runtime_disabled_enabled": False,
    }


def test_runtime_filter_switches_individual_config_disable():
    flags = _get_runtime_filter_switches(
        {
            "disable_runtime_quarantine": True,
            "disable_runtime_disabled": False,
        }
    )

    assert flags["quarantine_enabled"] is False
    assert flags["runtime_disabled_enabled"] is True


def test_runtime_filter_switches_global_env_disable(monkeypatch):
    monkeypatch.setenv("ARBY_DISABLE_RUNTIME_SUPPRESSION", "1")
    monkeypatch.delenv("ARBY_DISABLE_RUNTIME_QUARANTINE", raising=False)
    monkeypatch.delenv("ARBY_DISABLE_RUNTIME_DISABLED", raising=False)

    flags = _get_runtime_filter_switches({})

    assert flags == {
        "quarantine_enabled": False,
        "runtime_disabled_enabled": False,
    }


def test_runtime_filter_switches_env_overrides_config(monkeypatch):
    monkeypatch.setenv("ARBY_DISABLE_RUNTIME_DISABLED", "true")
    monkeypatch.delenv("ARBY_DISABLE_RUNTIME_SUPPRESSION", raising=False)
    monkeypatch.delenv("ARBY_DISABLE_RUNTIME_QUARANTINE", raising=False)

    flags = _get_runtime_filter_switches({"disable_runtime_quarantine": False})

    assert flags["quarantine_enabled"] is True
    assert flags["runtime_disabled_enabled"] is False
