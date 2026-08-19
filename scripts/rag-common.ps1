Set-StrictMode -Version Latest

$script:RagProjectRoot = Split-Path -Parent $PSScriptRoot

function Assert-LastExitCode {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE)."
    }
}

function Get-RagEnvValue {
    param(
        [string]$Name,
        [string]$DefaultValue = ""
    )

    $envPath = Join-Path $script:RagProjectRoot ".env"
    if (Test-Path -LiteralPath $envPath) {
        $escapedName = [regex]::Escape($Name)
        foreach ($line in Get-Content -LiteralPath $envPath) {
            if ($line -match "^\s*$escapedName\s*=\s*(.*)\s*$") {
                return $Matches[1].Trim().Trim('"').Trim("'")
            }
        }
    }
    return $DefaultValue
}

function Resolve-RagPath {
    param([string]$PathValue)
    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return $PathValue
    }
    return Join-Path $script:RagProjectRoot $PathValue
}

function Assert-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install and start Docker Desktop first."
    }
    docker info *> $null
    Assert-LastExitCode "docker info"
    docker compose version *> $null
    Assert-LastExitCode "docker compose version"
}

function Wait-RagInfrastructure {
    param([int]$TimeoutSeconds = 90)

    $postgresUser = Get-RagEnvValue "POSTGRES_USER" "user"
    $postgresDb = Get-RagEnvValue "POSTGRES_DB" "ragdb"
    $qdrantHost = Get-RagEnvValue "QDRANT_HOST" "localhost"
    $qdrantPort = Get-RagEnvValue "QDRANT_PORT" "6333"
    $ollamaBaseUrl = (Get-RagEnvValue "LLM_PROVIDER_BASE_URL" "http://localhost:11434").TrimEnd('/')

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $postgresOk = $false
        $qdrantOk = $false
        $ollamaOk = $false

        docker compose exec -T postgres pg_isready -U $postgresUser -d $postgresDb *> $null
        $postgresOk = ($LASTEXITCODE -eq 0)
        try {
            $qdrantUrl = "http://" + $qdrantHost + ":" + $qdrantPort + "/readyz"
            Invoke-RestMethod -Uri $qdrantUrl -TimeoutSec 3 | Out-Null
            $qdrantOk = $true
        } catch {}
        try {
            Invoke-RestMethod -Uri "$ollamaBaseUrl/api/tags" -TimeoutSec 3 | Out-Null
            $ollamaOk = $true
        } catch {}

        if ($postgresOk -and $qdrantOk -and $ollamaOk) {
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "Infrastructure did not become ready within $TimeoutSeconds seconds. Run 'docker compose ps' and inspect the container logs."
}

function Get-OllamaModelNames {
    $baseUrl = (Get-RagEnvValue "LLM_PROVIDER_BASE_URL" "http://localhost:11434").TrimEnd('/')
    $response = Invoke-RestMethod -Uri "$baseUrl/api/tags" -TimeoutSec 10
    $names = @()
    foreach ($model in @($response.models)) {
        if ($model.name) { $names += [string]$model.name }
        if ($model.model) { $names += [string]$model.model }
    }
    return @($names | ForEach-Object { $_.Trim().ToLowerInvariant() } | Select-Object -Unique)
}

function ConvertTo-NormalizedOllamaName {
    param([string]$Name)
    $normalized = $Name.Trim().ToLowerInvariant().Split('@')[0]
    $lastPart = ($normalized -split '/')[-1]
    if ($normalized -and -not $lastPart.Contains(':')) {
        $normalized = $normalized + ":latest"
    }
    return $normalized
}

function Test-OllamaModelInstalled {
    param([string]$ModelName)
    $wanted = ConvertTo-NormalizedOllamaName $ModelName
    foreach ($name in Get-OllamaModelNames) {
        if ((ConvertTo-NormalizedOllamaName $name) -eq $wanted) {
            return $true
        }
    }
    return $false
}

function Get-MissingRagModelAssets {
    $missing = @()
    $embeddingPath = Resolve-RagPath (Get-RagEnvValue "EMBEDDING_MODEL_DIR" "./models/bge-m3")
    $rerankerPath = Resolve-RagPath (Get-RagEnvValue "RERANKER_MODEL_DIR" "./models/bge-reranker-v2-m3")

    foreach ($item in @(
        @{ Name = "BAAI/bge-m3"; Path = $embeddingPath },
        @{ Name = "BAAI/bge-reranker-v2-m3"; Path = $rerankerPath }
    )) {
        $hasFile = Get-ChildItem -LiteralPath $item.Path -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not (Test-Path -LiteralPath $item.Path) -or -not $hasFile) {
            $missing += $item
        }
    }
    return $missing
}

function Start-RagFrontendIfNeeded {
    param([int]$FrontendPort = 5173)

    if (Test-RagPortOpen $FrontendPort) {
        Write-Host "Frontend already running at http://127.0.0.1:$FrontendPort" -ForegroundColor Green
        return
    }
    $frontendDir = Join-Path $script:RagProjectRoot "frontend"
    if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "node_modules"))) {
        Write-Host "Frontend dependencies not installed (frontend\node_modules missing) - skipping frontend startup. Run 'npm install' in frontend\ first." -ForegroundColor Yellow
        return
    }
    Write-Host "Starting frontend (Vite) in a new window..." -ForegroundColor Green
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit", "-Command", "Set-Location -LiteralPath `"$frontendDir`"; npm run dev"
    ) | Out-Null
}

function Test-RagPortOpen {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(700)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}
