# M8→M9 production refresh pipeline.
# -FullFromM8: M8 sniper + M8.1 before radar (required when bridge m8_stale=true).
# Default: radar-only continuation (no sniper/M8.1).
param(
    [switch]$FullFromM8,
    [switch]$SkipShadow,
    [int]$MaxRadarTokens = 753,
    [int]$SniperMinutes = 45
)

$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Log = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.log"
$Done = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.done"
$Fail = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.fail"
$ProdBridge = "data/tmp/m9_bridge_inventory_production_latest.json"
$CapacityDiag = "data/tmp/m9_capacity_cycle_diagnostic_latest.json"

Remove-Item $Done, $Fail -ErrorAction SilentlyContinue

function Write-Log([string]$Message) {
    Write-Host $Message
    try {
        Add-Content -Path $Log -Value $Message -Encoding utf8
    } catch {
        Write-Host "log_write_failed: $_"
    }
}

Write-Log "=== pipeline_start $(Get-Date -Format o) full_from_m8=$FullFromM8 ==="

function Step([string]$Name, [scriptblock]$Block) {
    Write-Log ">>> $Name $(Get-Date -Format o)"
    try {
        & $Block
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "exit=$LASTEXITCODE"
        }
    } catch {
        Write-Log "FAILED $Name : $_"
        Set-Content -Path $Fail -Value "$Name`: $_"
        exit 1
    }
}

function Gate([string]$Name, [string[]]$GateArgs) {
    Step $Name {
        & $py -3.11 scripts/m9_production_refresh_gates.py @GateArgs
        $rc = $LASTEXITCODE
        if ($rc -eq 1) { exit 1 }
    }
}

$py = "py"
$boot = @($py, "-3.11", "scripts/bootstrap_productive_rpc_env.py", "--", $py, "-3.11")

if ($FullFromM8) {
    Step "m8_sniper_45m" {
        $env:ARBY_SNIPER_ENABLE = "1"
        & @($boot + @(
            "-u", "scripts/sniper_smoke_run.py",
            "--chain", "base",
            "--duration-minutes", "$SniperMinutes",
            "--acceptance-run",
            "--blocks-back", "50"
        ))
    }

    Step "m8_1_stable_anchor" {
        & @($boot + @("scripts/m8_1_stable_anchor_run.py"))
    }
} else {
    Write-Log ">>> skip_m8_sniper_m81 (use -FullFromM8 for full chain from M8)"
}

Step "m8_radar_two_phase" {
    & $py -3.11 scripts/m8_radar_two_phase_refresh.py --max-tokens $MaxRadarTokens --skip-coingecko --lane-mode fresh_first
}

Gate "gate_fresh_delta_subset" @("fresh_delta_subset")

Step "m8_cross_dex_expand" {
    & $py -3.11 scripts/m8_cross_dex_expand.py --chain base
}

Step "m8_2_acceptance_strict" {
    & $py -3.11 scripts/m8_2_acceptance_report.py --strict
}

Step "m8_3_registry_refresh" {
    & @($boot + @(
        "scripts/m8_3_token_metadata_registry_refresh.py",
        "--chain", "base",
        "--task-mode", "aggregated",
        "--with-dex-workers"
    ))
}

Gate "gate_negative_cache_stats" @("negative_cache_stats")

Step "m8_3_acceptance_strict" {
    & $py -3.11 scripts/m8_3_acceptance_report.py --strict
}

Gate "gate_m8_3_acceptance_reached" @("m8_3_acceptance")

Step "m9_curve_discovery" {
    & @($boot + @("scripts/m9_curve_discovery.py"))
}

Step "bridge_curve_probe_for_indices" {
    $env:ARBY_M9_CURVE_ADMIT_ALL = "1"
    Remove-Item Env:ARBY_BRIDGE_IGNORE_EXPANSION_STALE -ErrorAction SilentlyContinue
    & $py -3.11 scripts/m9_bridge_build.py --graph-handoff-only --no-registry --include-expansion-duplicates-for-shadow --metadata-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json --output data/tmp/m9_bridge_curve_probe.json --no-enforce-m8-provenance
}

Step "discover_curve_indices" {
    & @($boot + @(
        "scripts/discover_curve_indices.py",
        "--partial", "--debug",
        "--inventory", "data/tmp/m9_bridge_curve_probe.json",
        "--output", "data/runs/_rolling/m9_curve_pool_indices_latest.json"
    ))
}

Step "m9_bridge_production" {
    Remove-Item Env:ARBY_M9_CURVE_ADMIT_ALL -ErrorAction SilentlyContinue
    Remove-Item Env:ARBY_BRIDGE_IGNORE_EXPANSION_STALE -ErrorAction SilentlyContinue
    $env:ARBY_CURVE_POOL_INDICES = "data/runs/_rolling/m9_curve_pool_indices_latest.json"
    & $py -3.11 scripts/m9_bridge_build.py `
        --metadata-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json `
        --output $ProdBridge `
        --no-enforce-m8-provenance
}

Step "m9_enrich_depth_false_positive" {
    & @($boot + @(
        "scripts/m9_enrich_bridge_depth.py",
        "--inventory", $ProdBridge,
        "--prioritize-false-positive-reprobe",
        "--sleep-ms", "150"
    ))
}

Step "m9_enrich_depth_broad" {
    & @($boot + @(
        "scripts/m9_enrich_bridge_depth.py",
        "--inventory", $ProdBridge,
        "--force-reprobe",
        "--sleep-ms", "150"
    ))
}

Step "m9_topology_diagnostic" {
    & $py -3.11 scripts/m9_graph_topology_diagnostic.py --inventory $ProdBridge --cycle-lengths 2,3,4
}

Step "m9_capacity_diagnostic" {
    & $py -3.11 scripts/m9_capacity_cycle_diagnostic.py `
        --bridge $ProdBridge `
        --cycle-lengths 2,3,4 `
        --four-leg-rca `
        --quarantine-rca `
        --output $CapacityDiag
}

$shadowAllowed = $false
Write-Log ">>> gate_capacity_shadow $(Get-Date -Format o)"
& $py -3.11 scripts/m9_production_refresh_gates.py capacity_shadow --capacity $CapacityDiag
if ($LASTEXITCODE -eq 0) {
    $shadowAllowed = $true
    Write-Log "shadow_gate: ALLOWED"
} else {
    Write-Log "shadow_gate: BLOCKED (cycles_at_floor=0 or missing capacity)"
}

if ($shadowAllowed -and -not $SkipShadow) {
    Step "m9_shadow_10m" {
        & @($boot + @(
            "-u", "-m", "m9.graph_arb.runner",
            "--chain", "base",
            "--config", "config/exotic_base_anchor.yaml",
            "--inventory", $ProdBridge,
            "--duration-minutes", "10",
            "--productive-lane",
            "--require-factory-verified",
            "--require-cycles-at-floor",
            "--capacity-diagnostic", $CapacityDiag,
            "--quote-backend", "raw_http",
            "--quote-workers", "1",
            "--max-cycles-per-sweep", "20",
            "--artifact-path", "data/tmp/m9_graph_handoff_quote_validation_10m.json"
        ))
    }
} else {
    Write-Log ">>> skip_m9_shadow (shadow_allowed=$shadowAllowed SkipShadow=$SkipShadow)"
}

Step "m9_lane_acceptance" {
    & $py -3.11 scripts/m9_lane_acceptance_report.py `
        --m8-2-report data/tmp/m8_2_acceptance_report_latest.json `
        --m8-3-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json `
        --bridge $ProdBridge `
        --shadow data/tmp/m9_graph_handoff_quote_validation_10m.json `
        --rca data/tmp/m9_quote_lane_rca_graph_handoff_latest.json
}

Write-Log "=== pipeline_done $(Get-Date -Format o) shadow_allowed=$shadowAllowed ==="
Set-Content -Path $Done -Value (Get-Date -Format o)
