# 온프레미스 RAG 챗봇

FastAPI 앱과 PostgreSQL 중심 워커 파이프라인으로 문서를 추출·청킹·임베딩하고,
Qdrant 하이브리드 검색과 Ollama LLM으로 근거 기반 답변을 생성한다.

## 구성

- Python 3.11 / FastAPI
- PostgreSQL + Alembic
- Qdrant dense+sparse 하이브리드 검색
- BGE-M3 임베딩, BGE reranker v2-m3
- Ollama + Qwen3
- PyMuPDF + PaddleOCR/PPStructureV3
- extraction → chunking → embedding 독립 워커

## 설치와 실행

최초 한 번 `SETUP_RAG.cmd`, 평상시에는 `RUN_RAG.cmd`를 실행한다.

```text
SETUP_RAG.cmd   # 외부 venv + Docker 인프라 + 모델 검사 + Alembic
RUN_RAG.cmd     # 재설치 없이 상태 검사 후 로컬 Uvicorn 실행
```

브라우저 주소는 `http://127.0.0.1:8000`이다. OCR 캐시가 프로젝트 안에서 변경되므로 문서 처리 중에는
`--reload`를 사용하지 않는다. 새 PC 복원은 `docs/FINAL_RUN_GUIDE.md`를 따른다.

앱까지 Docker로 실행할 때만 다음 프로필을 켠다.

```powershell
docker compose --profile container-app up -d
```

## 파이프라인 상태

```text
uploaded → extracting → extracted → chunked → ready
                   └→ needs_review (OCR 품질 기준 미달)
각 단계 오류 ─────────────────────→ failed
```

`needs_review` 문서는 잘못된 텍스트가 검색 결과를 오염시키지 않도록 청킹·임베딩하지 않는다.
문서 상태 API에서 OCR 품질 점수와 진단 이유를 확인할 수 있다.

PDF를 실제 재처리하기 전에 페이지 유형만 빠르게 감사하려면 다음을 실행한다. 이 명령은
OCR·DB·Qdrant를 변경하지 않고 `text_pdf / scan_pdf / mixed_pdf`와 페이지별 판정 이유만 출력한다.

```powershell
python scripts/audit_pdf_pages.py --summary-only "C:\path\to\pdf-folder"
```

## 핵심 API

- `POST /api/documents/upload`: 파일과 다중 라벨 등록
- `POST /api/admin/run-workers`: 기본 16문서 단위로 추출→청킹→임베딩을 순환하는 백그라운드 파이프라인 실행
- `GET /api/documents/{id}/status`: 처리 상태와 추출 품질 확인
- `GET /api/documents/{id}/chunks`: 페이지·표·이미지별 청크 확인
- `PUT /api/documents/{id}/labels`: 라벨 수정 후 자동 재색인
- `POST /api/documents/{id}/reextract`: 기존 라벨·원본을 보존하고 OCR부터 재처리
- `POST /api/chat`: 일반 답변
- `GET /api/chat/stream`: SSE 토큰 스트리밍
- `POST /api/evaluation/run`: 콘솔 UI 없이 실행하는 회귀 평가 (`docs/EVALUATION.md` 참고)

## 이번 개선 사항

적용 및 기존 문서 재처리 방법은 `docs/UPGRADE_20260809.md`, 변경 내역은 `PATCH_NOTES.md`를 확인한다.
두정테크 용접 문서 회귀 질문은 `docs/EVAL_QUESTIONS.json`에 들어 있다.
