<#
.SYNOPSIS
    One-time Windows bootstrap for the local RAG application.

.DESCRIPTION
    Creates a short-path Python 3.11 venv, installs the verified package lock,
    starts Docker infrastructure, optionally restores a backup, verifies model
    assets, and applies Alembic migrations. It does not start Uvicorn.
#>
param(
    [string]$VenvPath = "C:\v\rag_latest",
    [string]$Wheelhouse = "",
    [string]$RestoreTimestamp = "",
    [switch]$SkipPackages,
    [switch]$DownloadModels
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "rag-common.ps1")
Set-Location $script:RagProjectRoot

Write-Host "=== RAG one-time setup ===" -ForegroundColor Cyan

$envPath = Join-Path $script:RagProjectRoot ".env"
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item (Join-Path $script:RagProjectRoot ".env.example") $envPath
    Write-Host "Created .env from .env.example. Review LLM_MODEL_NAME before production use." -ForegroundColor Yellow
}

$venvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[1/5] Creating Python 3.11 venv at $VenvPath" -ForegroundColor Yellow
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.11 -c "import sys; assert sys.version_info[:2] == (3, 11)"
        Assert-LastExitCode "Python 3.11 check"
        py -3.11 -m venv $VenvPath
        Assert-LastExitCode "venv creation"
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        python -c "import sys; assert sys.version_info[:2] == (3, 11)"
        Assert-LastExitCode "Python 3.11 check"
        python -m venv $VenvPath
        Assert-LastExitCode "venv creation"
    } else {
        throw "Python 3.11 was not found. Install it from python.org, then run SETUP_RAG.cmd again."
    }
}

& $venvPython -c "import sys; assert sys.version_info[:2] == (3, 11), sys.version"
Assert-LastExitCode "venv Python 3.11 validation"

if (-not $SkipPackages) {
    Write-Host "[2/5] Installing verified Python packages" -ForegroundColor Yellow
    if ($Wheelhouse) {
        $wheelhousePath = (Resolve-Path -LiteralPath $Wheelhouse).Path
        & $venvPython -m pip install --no-index --find-links $wheelhousePath "torch==2.11.0"
        Assert-LastExitCode "offline torch installation"
        & $venvPython -m pip install --no-index --find-links $wheelhousePath -r (Join-Path $script:RagProjectRoot "requirements-lock.txt")
        Assert-LastExitCode "offline locked package installation"
    } else {
        & $venvPython -m pip install --upgrade pip
        Assert-LastExitCode "pip upgrade"
        & $venvPython -m pip install "torch==2.11.0" --index-url "https://download.pytorch.org/whl/cu128"
        Assert-LastExitCode "CUDA PyTorch installation"
        & $venvPython -m pip install -r (Join-Path $script:RagProjectRoot "requirements-lock.txt")
        Assert-LastExitCode "locked package installation"
    }
    & $venvPython -m pip check
    Assert-LastExitCode "pip dependency check"
} else {
    Write-Host "[2/5] Package installation skipped by request" -ForegroundColor DarkGray
}

Write-Host "[3/5] Starting Docker infrastructure" -ForegroundColor Yellow
Assert-DockerReady
docker compose up -d postgres qdrant ollama
Assert-LastExitCode "docker compose up"
Wait-RagInfrastructure

if ($RestoreTimestamp) {
    Write-Host "[4/5] Restoring backup $RestoreTimestamp before migrations" -ForegroundColor Yellow
    if (Test-RagPortOpen 8000) {
        throw "Port 8000 is already in use. Stop the RAG app before restoring a backup."
    }
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "restore.ps1") -BackupTimestamp $RestoreTimestamp -Confirm
    Assert-LastExitCode "backup restore"
} else {
    Write-Host "[4/5] No backup restore requested" -ForegroundColor DarkGray
}

$missingModels = @(Get-MissingRagModelAssets)
if ($missingModels.Count -gt 0 -and $DownloadModels) {
    foreach ($item in $missingModels) {
        Write-Host "Downloading $($item.Name) to $($item.Path)" -ForegroundColor Yellow
        $downloadCode = "from huggingface_hub import snapshot_download; snapshot_download(repo_id=r'$($item.Name)', local_dir=r'$($item.Path)')"
        & $venvPython -c $downloadCode
        Assert-LastExitCode "model download: $($item.Name)"
    }
    $missingModels = @(Get-MissingRagModelAssets)
}
if ($missingModels.Count -gt 0) {
    $details = ($missingModels | ForEach-Object { "$($_.Name) -> $($_.Path)" }) -join "; "
    throw "Required local models are missing: $details. Copy the model bundle or rerun setup with -DownloadModels."
}

$llmModel = Get-RagEnvValue "LLM_MODEL_NAME" "qwen3:8b"
if (-not (Test-OllamaModelInstalled $llmModel)) {
    if ($DownloadModels) {
        docker compose exec -T ollama ollama pull $llmModel
        Assert-LastExitCode "Ollama model download"
    } else {
        throw "Ollama model '$llmModel' is missing. Run 'docker compose exec ollama ollama pull $llmModel' or rerun setup with -DownloadModels."
    }
}

Write-Host "[5/5] Applying Alembic migrations" -ForegroundColor Yellow
& $venvPython -m alembic upgrade head
Assert-LastExitCode "Alembic migration"

Write-Host "Setup complete. Run RUN_RAG.cmd for daily startup." -ForegroundColor Green
