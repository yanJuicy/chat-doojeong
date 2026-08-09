<#
.SYNOPSIS
    backup.ps1으로 만든 백업에서 PostgreSQL + Qdrant + uploaded_files를 복원한다.

.DESCRIPTION
    **파괴적 작업이다.** 현재 PostgreSQL의 ragdb와 Qdrant의 documents 컬렉션을 지우고
    백업 시점 상태로 덮어쓴다. uploaded_files도 백업 시점 내용으로 덮어쓴다.
    실행 전 반드시 -Confirm 스위치를 명시해야 실제로 진행된다(안 붙이면 무엇을 할지만 보여주고 끝).

.PARAMETER BackupTimestamp
    backups/ 아래의 타임스탬프 폴더명 (예: 20260809_201500). 생략하면 최신 백업을 사용한다.

.PARAMETER Confirm
    이 스위치 없이 실행하면 dry-run(할 일만 출력)만 한다.

.EXAMPLE
    .\scripts\restore.ps1                          # 최신 백업으로 무엇을 할지만 미리보기
    .\scripts\restore.ps1 -Confirm                 # 최신 백업으로 실제 복원
    .\scripts\restore.ps1 -BackupTimestamp 20260809_201500 -Confirm
#>
param(
    [string]$BackupTimestamp,
    [switch]$Confirm
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

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

Write-Host "=== 복원 대상 백업: $BackupTimestamp ===" -ForegroundColor Cyan
Write-Host "  PostgreSQL: $pgDump $(if (Test-Path $pgDump) {'(존재)'} else {'(없음 - 건너뜀)'})"
Write-Host "  Qdrant:     $qdrantSnapshot $(if (Test-Path $qdrantSnapshot) {'(존재)'} else {'(없음 - 건너뜀)'})"
Write-Host "  업로드파일: $uploadedZip $(if (Test-Path $uploadedZip) {'(존재)'} else {'(없음 - 건너뜀)'})"

if (-not $Confirm) {
    Write-Host ""
    Write-Host "*** dry-run 모드입니다. 실제로 복원하려면 -Confirm 스위치를 붙여서 다시 실행하세요. ***" -ForegroundColor Yellow
    Write-Host "*** 이 작업은 현재 PostgreSQL ragdb와 Qdrant documents 컬렉션, uploaded_files를 전부 덮어씁니다. ***" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "실제 복원을 시작합니다..." -ForegroundColor Red

# --- 1. PostgreSQL ---
if (Test-Path $pgDump) {
    Write-Host "[1/3] PostgreSQL 복원 중... (기존 ragdb 내용을 덮어씁니다)" -ForegroundColor Yellow
    $pgContainer = "rag_chatbot_project-postgres-1"
    docker cp $pgDump "${pgContainer}:/tmp/restore.dump"
    docker exec $pgContainer pg_restore -U user -d ragdb --clean --if-exists -1 /tmp/restore.dump
    docker exec $pgContainer rm -f /tmp/restore.dump
    Write-Host "  완료" -ForegroundColor Green
}

# --- 2. Qdrant ---
if (Test-Path $qdrantSnapshot) {
    Write-Host "[2/3] Qdrant 복원 중... (기존 documents 컬렉션을 덮어씁니다)" -ForegroundColor Yellow
    $qdrantContainer = "rag_chatbot_project-qdrant-1"
    docker cp $qdrantSnapshot "${qdrantContainer}:/qdrant/snapshots/documents/restore.snapshot"
    Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections/documents/snapshots/recover" -Method Put -ContentType "application/json" -Body '{"location": "file:///qdrant/snapshots/documents/restore.snapshot"}'
    Write-Host "  완료" -ForegroundColor Green
}

# --- 3. uploaded_files ---
if (Test-Path $uploadedZip) {
    Write-Host "[3/3] uploaded_files 복원 중... (기존 폴더 내용을 덮어씁니다)" -ForegroundColor Yellow
    $uploadedFilesPath = Join-Path $ProjectRoot "uploaded_files"
    Expand-Archive -Path $uploadedZip -DestinationPath $uploadedFilesPath -Force
    Write-Host "  완료" -ForegroundColor Green
}

Write-Host ""
Write-Host "=== 복원 완료. 앱을 재시작하세요. ===" -ForegroundColor Cyan
