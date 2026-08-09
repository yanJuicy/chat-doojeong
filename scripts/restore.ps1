<#
.SYNOPSIS
    backup.ps1으로 만든 백업에서 PostgreSQL + Qdrant + uploaded_files를 복원한다.

.DESCRIPTION
    **파괴적 작업이다.** 현재 PostgreSQL의 ragdb와 Qdrant의 documents 컬렉션을 지우고
    백업 시점 상태로 덮어쓴다. uploaded_files는 기존 폴더를 통째로 치워두고 백업 내용으로
    새로 채운 뒤 성공했을 때만 이전 폴더를 지운다 (진짜 시점 복원 — 덮어쓰기 병합이 아니라서
    백업 이후에 추가된 파일이 그대로 남는 일이 없음. 실패하면 이전 폴더로 자동 롤백).
    실행 전 반드시 -Confirm 스위치를 명시해야 실제로 진행된다(안 붙이면 무엇을 할지만 보여주고 끝).
    기본적으로 3개 아티팩트(ragdb.dump, qdrant_documents.snapshot, uploaded_files.zip)가
    전부 있어야만 실제 복원이 진행된다 — 일부만 복원하면 PostgreSQL과 Qdrant가 서로 다른
    시점을 가리키게 되는 위험이 있기 때문. 불완전한 백업이어도 강행하려면 -AllowPartial 필요.

.PARAMETER BackupTimestamp
    backups/ 아래의 타임스탬프 폴더명 (예: 20260809_201500). 생략하면 최신 백업을 사용한다.

.PARAMETER Confirm
    이 스위치 없이 실행하면 dry-run(할 일만 출력)만 한다.

.PARAMETER AllowPartial
    3개 아티팩트 중 일부가 없어도 있는 것만으로 강제 진행한다. PostgreSQL/Qdrant 시점
    불일치 위험을 감수한다는 뜻이므로 기본값은 꺼져 있다.

.EXAMPLE
    .\scripts\restore.ps1                          # 최신 백업으로 무엇을 할지만 미리보기
    .\scripts\restore.ps1 -Confirm                 # 최신 백업으로 실제 복원
    .\scripts\restore.ps1 -BackupTimestamp 20260809_201500 -Confirm
#>
param(
    [string]$BackupTimestamp,
    [switch]$Confirm,
    [switch]$AllowPartial
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Assert-LastExitCode {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description 실패 (exit code $LASTEXITCODE)"
    }
}

function Get-ComposeContainerId {
    param([string]$Service)
    $id = docker compose ps -q $Service
    Assert-LastExitCode "docker compose ps -q $Service"
    if (-not $id) {
        throw "$Service 컨테이너를 찾을 수 없습니다. docker compose로 실행 중인지 확인하세요."
    }
    return ($id | Select-Object -First 1).Trim()
}

if (-not $BackupTimestamp) {
    $latest = Get-ChildItem (Join-Path $ProjectRoot "backups") -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $latest) { throw "backups/ 아래에 백업이 없습니다." }
    $BackupTimestamp = $latest.Name
}
$BackupDir = Join-Path $ProjectRoot "backups\$BackupTimestamp"
if (-not (Test-Path $BackupDir)) { throw "백업 폴더를 찾을 수 없습니다: $BackupDir" }

$pgDump = Join-Path $BackupDir "ragdb.dump"
$qdrantSnapshot = Join-Path $BackupDir "qdrant_documents.snapshot"
$uploadedZip = Join-Path $BackupDir "uploaded_files.zip"

$missing = @()
if (-not (Test-Path $pgDump)) { $missing += "ragdb.dump" }
if (-not (Test-Path $qdrantSnapshot)) { $missing += "qdrant_documents.snapshot" }
if (-not (Test-Path $uploadedZip)) { $missing += "uploaded_files.zip" }

Write-Host "=== 복원 대상 백업: $BackupTimestamp ===" -ForegroundColor Cyan
Write-Host "  PostgreSQL: $pgDump $(if (Test-Path $pgDump) {'(존재)'} else {'(없음)'})"
Write-Host "  Qdrant:     $qdrantSnapshot $(if (Test-Path $qdrantSnapshot) {'(존재)'} else {'(없음)'})"
Write-Host "  업로드파일: $uploadedZip $(if (Test-Path $uploadedZip) {'(존재)'} else {'(없음)'})"
if ($missing.Count -gt 0) {
    Write-Host "  경고: 누락된 아티팩트 - $($missing -join ', ')" -ForegroundColor Red
}

if (-not $Confirm) {
    Write-Host ""
    Write-Host "*** dry-run 모드입니다. 실제로 복원하려면 -Confirm 스위치를 붙여서 다시 실행하세요. ***" -ForegroundColor Yellow
    Write-Host "*** 이 작업은 현재 PostgreSQL ragdb와 Qdrant documents 컬렉션, uploaded_files를 전부 덮어씁니다. ***" -ForegroundColor Yellow
    if ($missing.Count -gt 0) {
        Write-Host "*** 백업이 불완전합니다. -AllowPartial 없이는 실제 복원이 거부됩니다. ***" -ForegroundColor Red
    }
    exit 0
}

if ($missing.Count -gt 0 -and -not $AllowPartial) {
    throw "백업이 불완전합니다 (누락: $($missing -join ', ')). PostgreSQL/Qdrant 시점 불일치 위험이 있어 기본적으로 거부합니다. 그래도 강행하려면 -AllowPartial을 명시하세요."
}
if ($missing.Count -gt 0) {
    Write-Host "경고: 불완전한 백업으로 강제 복원합니다 (누락: $($missing -join ', '))." -ForegroundColor Red
}

Write-Host ""
Write-Host "실제 복원을 시작합니다..." -ForegroundColor Red

# --- 1. PostgreSQL ---
if (Test-Path $pgDump) {
    Write-Host "[1/3] PostgreSQL 복원 중... (기존 ragdb 내용을 덮어씁니다)" -ForegroundColor Yellow
    $pgContainer = Get-ComposeContainerId "postgres"
    try {
        docker cp $pgDump "${pgContainer}:/tmp/restore.dump"
        Assert-LastExitCode "docker cp (restore.dump 업로드)"
        docker exec $pgContainer pg_restore -U user -d ragdb --clean --if-exists -1 /tmp/restore.dump
        Assert-LastExitCode "pg_restore"
    } finally {
        docker exec $pgContainer rm -f /tmp/restore.dump 2>$null
    }
    Write-Host "  완료" -ForegroundColor Green
}

# --- 2. Qdrant ---
if (Test-Path $qdrantSnapshot) {
    Write-Host "[2/3] Qdrant 복원 중... (기존 documents 컬렉션을 덮어씁니다)" -ForegroundColor Yellow
    $qdrantContainer = Get-ComposeContainerId "qdrant"
    try {
        docker cp $qdrantSnapshot "${qdrantContainer}:/qdrant/snapshots/documents/restore.snapshot"
        Assert-LastExitCode "docker cp (qdrant snapshot 업로드)"
        Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections/documents/snapshots/recover" -Method Put -ContentType "application/json" -Body '{"location": "file:///qdrant/snapshots/documents/restore.snapshot"}'
    } finally {
        docker exec $qdrantContainer rm -f /qdrant/snapshots/documents/restore.snapshot 2>$null
    }
    Write-Host "  완료" -ForegroundColor Green
}

# --- 3. uploaded_files (rename-aside 방식으로 진짜 시점 복원) ---
if (Test-Path $uploadedZip) {
    Write-Host "[3/3] uploaded_files 복원 중... (기존 폴더를 백업 시점 내용으로 완전히 교체합니다)" -ForegroundColor Yellow
    $uploadedFilesPath = Join-Path $ProjectRoot "uploaded_files"
    $asideName = "uploaded_files.pre_restore_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
    $asidePath = Join-Path $ProjectRoot $asideName
    $didRename = $false
    if (Test-Path $uploadedFilesPath) {
        Rename-Item -Path $uploadedFilesPath -NewName $asideName
        $didRename = $true
    }
    try {
        Expand-Archive -Path $uploadedZip -DestinationPath $uploadedFilesPath -Force
        if ($didRename) { Remove-Item -Recurse -Force $asidePath }
        Write-Host "  완료" -ForegroundColor Green
    } catch {
        Write-Host "  uploaded_files 복원 실패 - 기존 폴더로 되돌립니다." -ForegroundColor Red
        if (Test-Path $uploadedFilesPath) { Remove-Item -Recurse -Force $uploadedFilesPath }
        if ($didRename) { Rename-Item -Path $asidePath -NewName (Split-Path -Leaf $uploadedFilesPath) }
        throw
    }
}

Write-Host ""
Write-Host "=== 복원 완료. 앱을 재시작하세요. ===" -ForegroundColor Cyan
