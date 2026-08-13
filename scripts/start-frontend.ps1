<#
.SYNOPSIS
    Starts the React development server on port 5173.
#>
param(
    [int]$Port = 5173
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"

if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "package.json"))) {
    throw "React frontend was not found at $frontendRoot."
}

$existingResponse = $null
try {
    $existingResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/" -TimeoutSec 2
} catch {}

if ($existingResponse) {
    if ($existingResponse.Content -match '<div id="root"></div>') {
        Write-Host "React is already running at http://127.0.0.1:$Port" -ForegroundColor Green
        exit 0
    }
    throw "Port $Port is already in use by another application."
}

Set-Location $frontendRoot

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    $commonNodeRoot = Join-Path $env:ProgramFiles "nodejs"
    $commonNode = Join-Path $commonNodeRoot "node.exe"
    if (Test-Path -LiteralPath $commonNode) {
        $env:Path = "$commonNodeRoot;$env:Path"
    }
}

$pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
if ($pnpm) {
    Write-Host "Starting React at http://127.0.0.1:$Port (Ctrl+C to stop)" -ForegroundColor Green
    & $pnpm.Source dev --host 0.0.0.0 --port $Port --strictPort
    exit $LASTEXITCODE
}

$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($npm) {
    Write-Host "Starting React at http://127.0.0.1:$Port (Ctrl+C to stop)" -ForegroundColor Green
    & $npm.Source run dev -- --host 0.0.0.0 --port $Port --strictPort
    exit $LASTEXITCODE
}

throw "pnpm or npm was not found. Install Node.js first."
