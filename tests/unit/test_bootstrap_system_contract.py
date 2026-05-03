from pathlib import Path


def _script_text() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "scripts" / "bootstrap_system.ps1").read_text(encoding="utf-8")


def test_bootstrap_provider_budget_free_contract() -> None:
    text = _script_text()

    assert "[ValidateSet('standard','free')]" in text
    assert "[string]$ProviderBudget = 'standard'" in text
    assert "if ($ProviderBudget -eq 'free')" in text
    assert "$RpcRpsLimit = 35" in text
    assert "$RpcRpsBurst = 5" in text
    assert "$WsMaxReconnectAttempts = 1" in text
    assert "$WsReconnectCooldownSeconds = 180" in text


def test_bootstrap_rpc_ws_envs_are_parameterized() -> None:
    text = _script_text()

    assert "$env:ARBY_RPC_RPS_LIMIT                        = [string]$RpcRpsLimit" in text
    assert "$env:ARBY_RPC_RPS_BURST                        = [string]$RpcRpsBurst" in text
    assert "$env:ARBY_WS_MAX_RECONNECT_ATTEMPTS            = [string]$WsMaxReconnectAttempts" in text
    assert "$env:ARBY_WS_RECONNECT_RATE_LIMIT_COOLDOWN_S   = [string]$WsReconnectCooldownSeconds" in text


def test_bootstrap_tenderly_disable_not_set_when_prod_is_tenderly() -> None:
    """ARBY_TENDERLY_DISABLE must NOT be unconditionally set to '1'.
    When ProdSimBackend=tenderly, the operator wants Tenderly enabled.
    The bootstrap must use a conditional so the disable flag is only
    applied for non-tenderly backends.
    """
    text = _script_text()

    # The unconditional hardcode must be gone
    assert "$env:ARBY_TENDERLY_DISABLE                     = '1'" not in text
    # A conditional block must exist
    assert "if ($ProdSimBackend -ne 'tenderly')" in text
    assert "ARBY_TENDERLY_DISABLE" in text
