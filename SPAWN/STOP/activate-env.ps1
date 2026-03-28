# Orchestrator Environment Activation Script

Write-Host "[ACTIVATE] Activating Orchestrator Environment..." -ForegroundColor Green

$env:ORCHESTRATOR_HOME = "D:\NextAura\orchestrator"
$env:WSL_PATH = "$env:ORCHESTRATOR_HOME\.wsl"
$env:PYTHONENVVAR_ROOT = "$env:ORCHESTRATOR_HOME\Stop"

if ($env:PATH -notmatch [regex]::Escape($env:ORCHESTRATOR_HOME)) {
    $env:PATH = "$env:ORCHESTRATOR_HOME;$env:ORCHESTRATOR_HOME\Stop\.orchestrator;$env:PATH"
}

Write-Host "[OK] Environment activated:" -ForegroundColor Green
Write-Host "    ORCHESTRATOR_HOME: $env:ORCHESTRATOR_HOME"
Write-Host "    WSL_PATH: $env:WSL_PATH"
Write-Host "    Python root: $env:PYTHONENVVAR_ROOT"
