# M8 sniper-complete -> M9 diagnostics (production, no IGNORE_STALE).
$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Log = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.log"
$Done = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.done"
$Fail = Join-Path $Repo "data\tmp\m8_m9_production_pipeline.fail"

Remove-Item $Done, $Fail -ErrorAction SilentlyContinue
"=== pipeline_start $(Get-Date -Format o) ===" | Tee-Object -FilePath $Log -Append

function Step([string]$Name, [scriptblock]$Block) {
    ">>> $Name $(Get-Date -Format o)" | Tee-Object -FilePath $Log -Append
    try {
        & $Block 2>&1 | Tee-Object -FilePath $Log -Append
        if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
            throw "exit=$LASTEXITCODE"
        }
    } catch {
        "FAILED $Name : $_" | Tee-Object -FilePath $Log -Append
        Set-Content -Path $Fail -Value "$Name`: $_"
        exit 1
    }
}

$py = "py"
$boot = @($py, "-3.11", "scripts/bootstrap_productive_rpc_env.py", "--", $py, "-3.11")

Step "m8_radar_two_phase" {
    & $py -3.11 scripts/m8_radar_two_phase_refresh.py --max-tokens 753 --skip-coingecko
}

Step "m8_cross_dex_expand" {
    & $py -3.11 scripts/m8_cross_dex_expand.py --chain base
}

Step "m8_2_acceptance_strict" {
    & $py -3.11 scripts/m8_2_acceptance_report.py --strict
}

Step "m8_3_registry_refresh" {
    & $py -3.11 scripts/m8_3_token_metadata_registry_refresh.py --chain base --task-mode aggregated --with-dex-workers
}

Step "m8_3_acceptance_strict" {
    & $py -3.11 scripts/m8_3_acceptance_report.py --strict
}

Step "m9_curve_discovery" {
    & $py -3.11 scripts/m9_curve_discovery.py
}

Step "bridge_curve_probe_for_indices" {
    $env:ARBY_M9_CURVE_ADMIT_ALL = "1"
    Remove-Item Env:ARBY_BRIDGE_IGNORE_EXPANSION_STALE -ErrorAction SilentlyContinue
    & $py -3.11 scripts/m9_bridge_build.py --graph-handoff-only --no-registry --include-expansion-duplicates-for-shadow --metadata-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json --output data/tmp/m9_bridge_curve_probe.json --no-enforce-m8-provenance
}

Step "discover_curve_indices" {
    & @($boot + @("scripts/discover_curve_indices.py", "--partial", "--debug", "--inventory", "data/tmp/m9_bridge_curve_probe.json", "--output", "data/runs/_rolling/m9_curve_pool_indices_latest.json"))
}

Step "m9_bridge_production" {
    Remove-Item Env:ARBY_BRIDGE_IGNORE_EXPANSION_STALE -ErrorAction SilentlyContinue
    $env:ARBY_CURVE_POOL_INDICES = "data/runs/_rolling/m9_curve_pool_indices_latest.json"
    & $py -3.11 scripts/m9_bridge_build.py --graph-handoff-only --no-registry --include-expansion-duplicates-for-shadow --metadata-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json --output data/tmp/m9_bridge_inventory_graph_handoff_latest.json
}

Step "m9_enrich_depth" {
    & @($boot + @(
        "scripts/m9_enrich_bridge_depth.py",
        "--inventory", "data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
        "--prioritize-false-positive-reprobe",
        "--sleep-ms", "150"
    ))
}

Step "m9_enrich_depth_broad" {
    & @($boot + @(
        "scripts/m9_enrich_bridge_depth.py",
        "--inventory", "data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
        "--force-reprobe",
        "--sleep-ms", "150"
    ))
}

Step "m9_topology_diagnostic" {
    & $py -3.11 scripts/m9_graph_topology_diagnostic.py --inventory data/tmp/m9_bridge_inventory_graph_handoff_latest.json --cycle-lengths 2,3,4
}

Step "m9_capacity_diagnostic" {
    & $py -3.11 scripts/m9_capacity_cycle_diagnostic.py --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json --cycle-lengths 2,3,4 --four-leg-rca --quarantine-rca
}

Step "m9_lane_acceptance" {
    & $py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json --m8-3-registry data/runs/_rolling/m8_3_token_metadata_registry_latest.json --bridge data/tmp/m9_bridge_inventory_graph_handoff_latest.json --shadow data/tmp/m9_graph_handoff_quote_validation_10m.json --rca data/tmp/m9_quote_lane_rca_graph_handoff_latest.json
}

"=== pipeline_done $(Get-Date -Format o) ===" | Tee-Object -FilePath $Log -Append
Set-Content -Path $Done -Value (Get-Date -Format o)
