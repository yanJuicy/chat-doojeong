# RAG 최종 실행·이전 가이드 (Windows)

현재 PC의 유일한 작업 원본은 다음 Git 저장소의 `master` 브랜치다.

```text
C:\Users\mesul\Desktop\rag_chatbot_project_TRUE_LATEST\rag_chatbot_project
```

과거 ZIP이나 개선본을 편집 원본으로 다시 사용하지 않는다. 앱은 로컬 Python에서 실행하고
PostgreSQL·Qdrant·Ollama만 Docker로 실행한다.

## 최초 설치

준비물은 Docker Desktop, Python 3.11, BGE-M3·BGE 리랭커 모델과 `.env`에 지정한
Ollama 모델이다. 프로젝트 내부 venv는 Windows 긴 경로 오류를 일으킬 수 있으므로 사용하지 않는다.

프로젝트 루트에서 `SETUP_RAG.cmd`를 더블클릭한다. 기본 venv는
`C:\v\rag_latest`에 생성된다.

```powershell
.\SETUP_RAG.cmd                 # 이미 모델 폴더와 Ollama 모델이 있는 경우
.\SETUP_RAG.cmd -DownloadModels # 인터넷에서 누락 모델도 내려받기
.\SETUP_RAG.cmd -Wheelhouse "D:\rag-offline\wheelhouse" # 폐쇄망 wheel 사용
```

설치 스크립트는 `.env` 생성, 잠금 패키지 설치, Docker 인프라 기동, 모델 검사,
Alembic 적용까지만 수행한다. Docker Desktop이나 Python 자체는 임의로 설치하지 않는다.

## 평상시 실행

`RUN_RAG.cmd`를 더블클릭한다. 이 명령은 패키지나 모델을 다시 설치하지 않고 다음 항목을
검사한 뒤 Uvicorn을 포그라운드로 실행한다.

- Python 3.11 외부 venv와 핵심 패키지
- Docker Desktop과 세 인프라 서비스
- 8000번 포트 충돌
- BGE-M3·리랭커 모델 폴더
- 설정된 Ollama 모델
- Alembic 최신 상태

브라우저 주소는 `http://127.0.0.1:8000`이다. 콘솔을 닫거나 `Ctrl+C`를 누르면
앱이 종료된다. 이미 정상 서버가 실행 중이면 중복 실행하지 않는다.

## 상태 점검

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

PostgreSQL, Qdrant, 설정된 Ollama 모델, 로컬 BGE/리랭커 로드 상태를 모두 확인한다. 하나라도 실패하면
HTTP 503과 이유를 반환한다.

## 백업

문서 업로드·재처리가 없는 시점에 실행한다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\backup.ps1
```

`backups/<시각>/`에 PostgreSQL 덤프, Qdrant 스냅샷, 업로드 원본 ZIP,
SHA256 `manifest.json`이 생성된다.

## 새 PC 복원

코드, 모델 폴더, 원하는 `backups/<시각>` 폴더를 새 PC에 복사하고 앱을 실행하지 않은 상태에서
다음 명령을 사용한다.

```powershell
.\SETUP_RAG.cmd -RestoreTimestamp 20260809_213547
```

순서는 `빈 인프라 시작 → 백업 복원 → Alembic 마이그레이션 → 모델 확인`이다.
`pg_restore --clean`이 백업 스키마를 복원하므로 마이그레이션은 반드시 복원 뒤에 실행한다.

## 폐쇄망 반입

코드 ZIP과 데이터 백업만으로는 실행되지 않는다. 다음을 별도로 준비한다.

- `models/bge-m3`, `models/bge-reranker-v2-m3`
- Ollama 모델 데이터 볼륨
- `wheelhouse/`
- PostgreSQL·Qdrant·Ollama Docker image tar

Docker 이미지는 인터넷 PC에서 `docker save`, 폐쇄망 PC에서 `docker load`로
옮긴다. 모델과 데이터는 코드 ZIP에 섞지 않는다.

## 릴리스 생성

ZIP을 수동 복사하지 않는다. 테스트 통과 후 모든 변경을 커밋하고 다음을 실행한다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\release.ps1 -Version v1.0.0 -CreateTag
```

`releases/v1.0.0-<커밋>/`에 태그된 커밋의 코드 ZIP, SHA256, 매니페스트와 Git 로그가
생성된다. 이 ZIP은 배포물이며 편집 원본이 아니다.

## 자주 발생한 문제

| 증상 | 조치 |
|---|---|
| 스크립트 실행 정책 오류 | 직접 ps1을 실행하지 말고 `SETUP_RAG.cmd`·`RUN_RAG.cmd` 사용 |
| WinError 206 | 기본 외부 venv `C:\v\rag_latest` 사용 |
| Docker 명령 실패 | Docker Desktop 실행 후 `docker info` 확인 |
| 8000 포트 충돌 | 출력된 PID를 확인해 사용자가 직접 종료 |
| Ollama 모델 없음 | `docker compose exec ollama ollama pull <모델명>` |
| 모델 폴더 없음 | 모델 번들을 복사하거나 `SETUP_RAG.cmd -DownloadModels` |
