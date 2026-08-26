# 온프레미스 RAG 챗봇

FastAPI 앱과 PostgreSQL 중심 워커 파이프라인으로 문서를 추출·청킹·임베딩하고,
Qdrant 하이브리드 검색과 Ollama LLM으로 근거 기반 답변을 생성한다. 인터넷 연결 없는
폐쇄망(air-gapped) 환경에서 동작하는 것을 전제로 설계했다.

## 이 프로젝트의 차별화 포인트

- **문서 유형이 늘어나도 테이블을 새로 만들지 않는다.** `documents` 테이블 하나에
  `document_type_id` + 유연한 `type_specific_data`(JSONB) 구조로 RAG 업로드 문서, 주간보고서
  항목, 자재입출고 원본을 전부 담는다. 회사마다 서식이 다른 문서(주간보고서/견적서/거래명세서 등)를
  새 테이블 없이 그대로 수용할 수 있다는 뜻이다. 자세한 내용은 [Wiki: 아키텍처](../../wiki/Architecture)
  참고.
- **정확도를 위해 하이브리드 검색 + 2단계 리랭킹을 쓴다.** dense+sparse 벡터를 동시에 뽑는
  BGE-M3로 1차 후보 64개를 넓게 찾고, cross-encoder 리랭커(BGE-reranker-v2-m3)로 최종 5개만
  정밀하게 골라 LLM에 넘긴다. 왜 이 모델들을 골랐는지는 [Wiki: 모델 선정 근거](../../wiki/Model-Selection)
  참고.
- **폐쇄망 요건을 처음부터 전제로 설계했다.** LLM(Ollama+Qwen3), 임베딩(BGE-M3), 리랭커
  (BGE-reranker-v2-m3), OCR(PaddleOCR)까지 전부 오픈소스 로컬 모델만 쓴다 — 외부 API 호출이
  전혀 없다.
- **RAG 검색 외에 실제 업무 자동화 기능 3종을 붙였다.** 주간보고서 자동 생성(+부서별 문체
  자동 맞춤), 자재입출고 자동 반영, 출하보고서 생성 — 아래 "부가 기능" 참고.

## 구성

- Python 3.11 / FastAPI
- PostgreSQL + Alembic
- Qdrant dense+sparse 하이브리드 검색
- BGE-M3 임베딩, BGE reranker v2-m3
- Ollama + Qwen3
- React + Vite 웹 프론트엔드
- PyMuPDF + PaddleOCR/PPStructureV3
- extraction → chunking → embedding 독립 워커

## 설치와 실행

최초 한 번 `SETUP_RAG.cmd`, 평상시에는 `RUN_RAG.cmd`를 실행한다.

```text
SETUP_RAG.cmd   # 외부 venv + Docker 인프라 + 모델 검사 + Alembic
RUN_RAG.cmd     # 재설치 없이 상태 검사 후 로컬 Uvicorn 실행
```

브라우저 주소는 `http://127.0.0.1:8000`이다. FastAPI가 `frontend/dist`에 빌드된 React 화면을
첫 화면으로 제공한다. OCR 캐시가 프로젝트 안에서 변경되므로 문서 처리 중에는
`--reload`를 사용하지 않는다. 새 PC 복원은 `docs/FINAL_RUN_GUIDE.md`를 따른다.

## React 프론트엔드

프론트엔드 소스는 `frontend/`, FastAPI가 제공하는 빌드 결과는 `frontend/dist/`에 있다.
화면을 수정한 뒤에는 다음 명령으로 빌드 결과를 갱신한다.

```powershell
cd frontend
pnpm install
pnpm build
```

개발 중에는 `RUN_RAG.cmd`로 FastAPI를 `127.0.0.1:8000`에서 실행하고,
별도 창에서 `RUN_FRONTEND.cmd`를 실행한 뒤 `http://127.0.0.1:5173`에 접속한다.
Vite가 `/api`, `/health`, `/images` 요청을 FastAPI로 전달한다. 같은 와이파이의 다른 기기에서는
이 PC의 내부 IP에 포트 5173을 붙여 접속한다(예: `http://192.168.0.10:5173`).

React 화면에는 채팅 스트리밍, 답변 출처·참고 이미지, 문서 업로드, 공통·파일별 라벨 자동완성,
문서 처리 상태, 백엔드 연결 상태, 모바일 반응형 화면이 포함되어 있다.

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

**문서 검색(RAG)**
- `POST /api/documents/upload`: 파일과 다중 라벨 등록
- `POST /api/admin/run-workers`: 기본 16문서 단위로 추출→청킹→임베딩을 순환하는 백그라운드 파이프라인 실행
- `GET /api/documents/{id}/status`: 처리 상태와 추출 품질 확인
- `GET /api/documents/{id}/chunks`: 페이지·표·이미지별 청크 확인
- `PUT /api/documents/{id}/labels`: 라벨 수정 후 자동 재색인
- `POST /api/documents/{id}/reextract`: 기존 라벨·원본을 보존하고 OCR부터 재처리
- `DELETE /api/documents/{id}`: 문서·청크·라벨·벡터·관리 파일 삭제
- `POST /api/documents/delete-batch`: 선택 문서 최대 100개 일괄 삭제
- `POST /api/chat`: 일반 답변
- `GET /api/chat/stream`: SSE 토큰 스트리밍
- `POST /api/evaluation/run`: 콘솔 UI 없이 실행하는 회귀 평가 (`docs/EVALUATION.md` 참고)

**주간보고서 자동 생성** (`app/backend/work_reports.py`)
- `POST /api/v1/work-reports/upload-document`: 기존 보고서 PDF를 업로드하면 표를 자동으로 인식해 항목으로 저장
- `POST /api/v1/work-reports/chat-entry`: 자유롭게 입력한 텍스트를 실적/계획으로 분리하고, 해당 부서의
  기존 문체(어미)에 자동으로 맞춰 저장
- `GET /api/v1/work-reports/report` / `GET /api/v1/work-reports/report.docx`: 기간·부서 기준으로
  모아서 미리보기(JSON) 또는 완성 문서(DOCX)로 발급
- `PATCH` / `DELETE /api/v1/work-reports/{entry_id}`: 저장된 항목 수정/삭제

**자재입출고 자동 반영** (`app/reports/material_receipt/router.py`)
- `POST /api/material-receipt/preview`: 거래처 주문서 + 사내 `자재입출고.xlsx`를 올리면 저장 없이
  매칭/미매칭 목록만 미리 보여줌
- `POST /api/material-receipt/apply`: 실제로 반영한 수정된 xlsx 파일을 다운로드로 돌려줌

**출하보고서 생성** (`app/report_api/shipment_router.py`)
- `POST /api/reports/shipment/generate`: 계획·실적 데이터를 넣으면 항목별 상태(정상/부분출하/미출하/초과)를 계산
- `POST /api/reports/shipment/documents`: 같은 데이터로 완성된 DOCX 문서를 발급

## 더 알아보기

이 README는 실행 방법 위주다. RAG 개념 설명, 모델 선정 근거, 실제로 겪은 버그와 교훈, 발표/Q&A
대비 자료처럼 팀원이 프로젝트를 이해하고 공부하는 데 필요한 자세한 내용은 저장소의
**[Wiki](../../wiki)** 에 정리되어 있다.

## 이번 개선 사항

적용 및 기존 문서 재처리 방법은 `docs/UPGRADE_20260809.md`, 변경 내역은 `PATCH_NOTES.md`를 확인한다.
두정테크 용접 문서 회귀 질문은 `docs/EVAL_QUESTIONS.json`에 들어 있다.
