<#
.SYNOPSIS
    Daily startup for the local RAG application.

.DESCRIPTION
    Performs fast deterministic checks only. It never creates a venv, installs
    packages, downloads models, kills processes, or overwrites data.
#>
param(
    [string]$VenvPath = "C:\v\rag_latest",
    [int]$Port = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "rag-common.ps1")
Set-Location $script:RagProjectRoot

Write-Host "=== RAG daily startup ===" -ForegroundColor Cyan

if (Test-RagPortOpen $Port) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        $requiredChecks = @("postgres", "qdrant", "ollama_model", "local_models")
        $allChecksOk = ($health.status -eq "ok")
        foreach ($checkName in $requiredChecks) {
            $property = $health.checks.PSObject.Properties[$checkName]
            if (-not $property -or $property.Value -ne "ok") {
                $allChecksOk = $false
            }
        }
        if ($allChecksOk) {
            Write-Host "RAG is already running and healthy at http://127.0.0.1:$Port" -ForegroundColor Green
            Start-RagFrontendIfNeeded -FrontendPort $FrontendPort
            exit 0
        }
    } catch {}
    $owner = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $ownerText = if ($owner) { " PID=$($owner.OwningProcess)" } else { "" }
    throw "Port $Port is already in use by another process.$ownerText Stop it or choose another port with -Port."
}

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw "Verified venv not found at $VenvPath. Run SETUP_RAG.cmd first."
}
if (-not (Test-Path -LiteralPath (Join-Path $script:RagProjectRoot ".env"))) {
    throw ".env is missing. Run SETUP_RAG.cmd first or copy .env.example to .env."
}

& $venvPython -c "import fastapi, uvicorn, sqlalchemy, qdrant_client, FlagEmbedding, paddleocr"
Assert-LastExitCode "required Python package import check"
& $venvPython -m pip check
Assert-LastExitCode "pip dependency check"

Assert-DockerReady
docker compose up -d postgres qdrant ollama
Assert-LastExitCode "docker compose up"
Wait-RagInfrastructure

$missingModels = @(Get-MissingRagModelAssets)
if ($missingModels.Count -gt 0) {
    $details = ($missingModels | ForEach-Object { "$($_.Name) -> $($_.Path)" }) -join "; "
    throw "Required local models are missing: $details. Run SETUP_RAG.cmd or copy the model bundle."
}
$llmModel = Get-RagEnvValue "LLM_MODEL_NAME" "qwen3:8b"
if (-not (Test-OllamaModelInstalled $llmModel)) {
    throw "Ollama is running but model '$llmModel' is not installed. Run 'docker compose exec ollama ollama pull $llmModel'."
}

& $venvPython -m alembic upgrade head
Assert-LastExitCode "Alembic migration"

Start-RagFrontendIfNeeded -FrontendPort $FrontendPort

Write-Host "Starting Uvicorn at http://127.0.0.1:$Port (Ctrl+C to stop)" -ForegroundColor Green
& $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
