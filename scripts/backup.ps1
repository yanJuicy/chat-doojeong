<#
.SYNOPSIS
    PostgreSQL + Qdrant + uploaded_files를 한 번에 백업한다.

.DESCRIPTION
    2026-08-09에 수동으로 겪었던 문제(Git Bash의 Docker 경로 변환, docker cp 대상 경로 처리)를
    피하기 위해 PowerShell로 작성했다. 매번 실행할 때마다 backups/<타임스탬프>/ 폴더를 만들고
    그 안에 세 가지를 전부 담는다. 오래된 백업은 -KeepCount 개수만 남기고 자동 삭제한다.

.PARAMETER KeepCount
    보관할 최근 백업 개수. 기본 7개.

.EXAMPLE
    .\scripts\backup.ps1
    .\scripts\backup.ps1 -KeepCount 14
#>
param(
    [int]$KeepCount = 7
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupDir = Join-Path $ProjectRoot "backups\$Stamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "=== 백업 시작: $Stamp ===" -ForegroundColor Cyan

# --- 1. PostgreSQL ---
Write-Host "[1/3] PostgreSQL 덤프 중..." -ForegroundColor Yellow
$pgContainer = "rag_chatbot_project-postgres-1"
docker exec $pgContainer pg_dump -U user -d ragdb -F c -f /tmp/backup.dump
if (-not $?) { throw "pg_dump 실패" }
docker cp "${pgContainer}:/tmp/backup.dump" (Join-Path $BackupDir "ragdb.dump")
docker exec $pgContainer rm -f /tmp/backup.dump
$pgSize = (Get-Item (Join-Path $BackupDir "ragdb.dump")).Length / 1MB
Write-Host ("  완료: ragdb.dump ({0:N1} MB)" -f $pgSize) -ForegroundColor Green

# --- 2. Qdrant ---
Write-Host "[2/3] Qdrant 스냅샷 생성 중..." -ForegroundColor Yellow
$qdrantContainer = "rag_chatbot_project-qdrant-1"
$snapshotResponse = Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections/documents/snapshots" -Method Post
$snapshotName = $snapshotResponse.result.name
if (-not $snapshotName) { throw "Qdrant 스냅샷 생성 실패" }
docker cp "${qdrantContainer}:/qdrant/snapshots/documents/$snapshotName" (Join-Path $BackupDir "qdrant_documents.snapshot")
# 컨테이너 안에는 스냅샷을 계속 쌓아두지 않도록 삭제 (로컬 백업 폴더에 이미 복사됨)
Invoke-RestMethod -Uri "http://127.0.0.1:6333/collections/documents/snapshots/$snapshotName" -Method Delete | Out-Null
$qdrantSize = (Get-Item (Join-Path $BackupDir "qdrant_documents.snapshot")).Length / 1MB
Write-Host ("  완료: qdrant_documents.snapshot ({0:N1} MB)" -f $qdrantSize) -ForegroundColor Green

# --- 3. uploaded_files ---
Write-Host "[3/3] uploaded_files 압축 중... (용량에 따라 시간이 걸릴 수 있음)" -ForegroundColor Yellow
$uploadedFilesPath = Join-Path $ProjectRoot "uploaded_files"
$zipPath = Join-Path $BackupDir "uploaded_files.zip"
Compress-Archive -Path "$uploadedFilesPath\*" -DestinationPath $zipPath -CompressionLevel Optimal
$zipSize = (Get-Item $zipPath).Length / 1MB
Write-Host ("  완료: uploaded_files.zip ({0:N1} MB)" -f $zipSize) -ForegroundColor Green

# --- 오래된 백업 정리 ---
$allBackups = Get-ChildItem (Join-Path $ProjectRoot "backups") -Directory | Sort-Object Name -Descending
if ($allBackups.Count -gt $KeepCount) {
    $toDelete = $allBackups | Select-Object -Skip $KeepCount
    foreach ($old in $toDelete) {
        Write-Host "오래된 백업 삭제: $($old.Name)" -ForegroundColor DarkGray
        Remove-Item -Recurse -Force $old.FullName
    }
}

Write-Host "=== 백업 완료: $BackupDir ===" -ForegroundColor Cyan
Write-Host "복구 방법은 scripts\restore.ps1 참고"
