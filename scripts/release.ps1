<# Creates a traceable git-archive release from a clean tagged commit. #>
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [switch]$CreateTag
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "rag-common.ps1")
Set-Location $projectRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git was not found." }
$dirty = git status --porcelain
if ($dirty) { throw "The working tree is not clean. Commit or discard changes before creating a release." }

$tag = git tag --list $Version
if (-not $tag) {
    if (-not $CreateTag) { throw "Tag '$Version' does not exist. Rerun with -CreateTag after reviewing the commit." }
    git tag -a $Version -m "RAG release $Version"
    if ($LASTEXITCODE -ne 0) { throw "git tag failed." }
}

$commit = (git rev-list -n 1 $Version).Trim()
$shortCommit = $commit.Substring(0, 8)
$releaseDir = Join-Path $projectRoot ("releases\" + $Version + "-" + $shortCommit)
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
$zipName = "rag-chatbot-" + $Version + "-" + $shortCommit + ".zip"
$zipPath = Join-Path $releaseDir $zipName

git archive --format=zip --prefix=rag_chatbot_project/ --output=$zipPath $Version
if ($LASTEXITCODE -ne 0) { throw "git archive failed." }

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
$latestBackup = Get-ChildItem (Join-Path $projectRoot "backups") -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "manifest.json") } |
    Sort-Object Name -Descending | Select-Object -First 1
$latestBackupName = $null
if ($latestBackup) { $latestBackupName = $latestBackup.Name }

$embeddingRelativePath = Get-RagEnvValue "EMBEDDING_MODEL_DIR" "./models/bge-m3"
$rerankerRelativePath = Get-RagEnvValue "RERANKER_MODEL_DIR" "./models/bge-reranker-v2-m3"
$embeddingPath = Resolve-RagPath $embeddingRelativePath
$rerankerPath = Resolve-RagPath $rerankerRelativePath
function Get-DirectorySummary([string]$Path, [string]$DisplayPath) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $files = @(Get-ChildItem -LiteralPath $Path -File -Recurse)
    return [ordered]@{
        path = $DisplayPath
        files = $files.Count
        bytes = ($files | Measure-Object Length -Sum).Sum
    }
}

$manifest = [ordered]@{
    version = $Version
    commit = $commit
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    code_archive = [ordered]@{
        file = $zipName
        sha256 = $zipHash
    }
    latest_data_backup = $latestBackupName
    required_models = [ordered]@{
        ollama = (Get-RagEnvValue "LLM_MODEL_NAME" "qwen3:8b")
        embedding = (Get-DirectorySummary $embeddingPath $embeddingRelativePath)
        reranker = (Get-DirectorySummary $rerankerPath $rerankerRelativePath)
    }
}
$manifest | ConvertTo-Json -Depth 7 | Set-Content (Join-Path $releaseDir "release-manifest.json") -Encoding UTF8
git log --date=short --pretty=format:"%ad %h %s" $Version | Set-Content (Join-Path $releaseDir "git-log.txt") -Encoding UTF8
"$zipHash  $zipName" | Set-Content (Join-Path $releaseDir "SHA256SUMS.txt") -Encoding ASCII

Write-Host "Release created: $releaseDir" -ForegroundColor Green
