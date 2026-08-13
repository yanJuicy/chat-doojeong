# 백엔드 작업 계획 — RAG 핵심 기능 API화 (`app/backend`)

이 문서는 아직 아무것도 구현하지 않은 상태의 계획 문서다. 담당자가 백엔드를 새로 맡으면서
"RAG 핵심 기능을 프론트엔드가 쓸 수 있는 JSON API로 만드는 것"이 급한 작업이라고 정했고,
로그인/인증은 지금 범위에서 뺐다. 새 엔드포인트는 기존 `app/main.py`에 이어붙이지 않고
`app/backend/` 아래에 새로 만들기로 했다 (기존 것과 별개로).

## 0. 반드시 지켜야 하는 제약 — `app/backend`는 별도 서버가 아니다

`app/main.py`의 `lifespan`이 앱 시작 시 딱 한 번 무거운 모델들(bge-m3 임베딩, 리랭커, Qdrant
클라이언트, Ollama LLM 클라이언트, 청커, 의도 분류기, 질문 캐시, GPU 잠금)을 로딩해서
`app.state`에 올려둔다 (`app/main.py:75-114`). 이 로딩 자체가 무겁고(CPU 환경에서도 수 초~수십 초),
GPU 서버에서는 VRAM을 점유하는 리소스라서 **두 번 로딩하면 안 된다.**

그래서 `app/backend`는:
- 독립된 FastAPI 앱이나 별도 프로세스가 아니라, **`APIRouter`를 만들어서 기존 `app` 인스턴스에
  `include_router`로 등록하는 방식**이어야 한다.
- 무거운 리소스(임베딩/리랭커/LLM/벡터스토어)가 필요하면 새로 만들지 말고 `request.app.state.*`에서
  꺼내 쓴다.
- 검색→리랭킹→LLM 답변 생성 로직(`app/main.py`의 `_run_chat_pipeline`)을 다시 구현하지 말고
  그대로 재사용한다. 이미 이 프로젝트에 이렇게 재사용하는 예시가 있다 — `app/routers/evaluation.py`가
  `create_evaluation_router(run_chat_pipeline)` 형태로 `_run_chat_pipeline`을 함수 인자로 받아서
  씀 (`app/main.py:1101`: `app.include_router(create_evaluation_router(_run_chat_pipeline))`).
  `app/backend`도 이 패턴을 그대로 따라가면 된다.

## 1. JSON 응답 규격 (요청대로 이번에 확정)

프론트엔드가 아직 없어서 임의로 정한다. 모든 `app/backend` 엔드포인트는 아래 봉투(envelope)
형식을 쓴다 — 프론트가 매 엔드포인트마다 다른 응답 모양을 기억할 필요 없이, 항상
`success`를 먼저 보고 `data`나 `error`만 보면 되게 하려는 목적.

**성공 (HTTP 200)**
```json
{
  "success": true,
  "data": { "...엔드포인트별 실제 데이터..." }
}
```

**실패 (HTTP 4xx/5xx, 상태 코드도 의미대로 구분)**
```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "사람이 읽을 수 있는 설명",
    "stage": "실패한 단계 (선택, 파이프라인 에러일 때만)"
  }
}
```

`code`는 프론트가 분기 처리할 수 있는 짧은 문자열: `VALIDATION_ERROR`(400),
`NOT_FOUND`(404), `PIPELINE_ERROR`(500, RAG 파이프라인 중간 실패 — `_run_chat_pipeline`이
이미 `{"stage":..., "message":...}` 형태로 에러를 주므로 그대로 옮기면 됨), `INTERNAL_ERROR`(500).

FastAPI 기본 에러 포맷(`{"detail": "..."}`)과 다르므로, `app/backend` 라우터 전용으로
예외 핸들러를 하나 둬서 이 형식으로 통일하는 게 좋다 (앱 전체에 적용할지, `app/backend` 응답에만
적용할지는 기존 `/api/documents/*`, `/api/chat` 등 콘솔이 쓰는 엔드포인트의 응답 형식을 바꾸고
싶은지에 달려있다 — 지금은 기존 엔드포인트는 안 건드리고 `app/backend`만 새 형식을 쓰는 걸 권장).

### 1-1. 채팅(질문 응답) 엔드포인트

```
POST /api/backend/chat
Request:  { "question": "질문 내용" }

Response.data:
{
  "answer": "...",
  "question_language": "ko",
  "sources": [
    { "document_id": "...", "filename": "...", "page_number": 3, "similarity": 0.82 }
  ],
  "images": [
    { "image_url": "/images/...", "caption": "...", "chunk_id": "..." }
  ],
  "meta": {
    "n_context_chunks": 5,
    "cache_hit": false,
    "cache_similarity": null,
    "stage_timings": [ { "stage": "문서 검색", "seconds": 0.31 } ]
  }
}
```

기존 `ChatResponse`(`app/api_models.py`)와 필드는 거의 같지만, `intent_scores`/`stage_timings`처럼
디버깅용 정보는 `meta` 아래로 몰아서 프론트가 실제로 화면에 쓸 필드(`answer`, `sources`, `images`)와
분리했다. 스트리밍(`/api/chat/stream`, SSE)이 필요해지면 `/api/backend/chat/stream`을 별도로
추가하면 되고, 이때도 `_run_chat_pipeline`을 그대로 재사용한다 (기존 SSE 엔드포인트 구현이
`app/main.py:1037-1064`에 있어 그대로 참고 가능).

### 1-2. 문서(업로드/상태) 엔드포인트

```
POST /api/backend/documents          (multipart: file, labels[])
  -> data: { document_id, filename, status, is_duplicate }

GET  /api/backend/documents/{id}
  -> data: { document_id, filename, status, error_message, warning_message,
             extraction_quality_score, current_page, total_pages }

GET  /api/backend/documents
  -> data: { items: [ {...위와 동일 요약...} ], total }
```

업로드된 문서를 실제로 처리(추출→청킹→임베딩)하는 트리거는 기존 `/api/admin/run-workers`가
이미 하고 있다. 새로 안 만들고 그대로 재사용(내부 호출)하거나, 필요하면 `/api/backend/documents`
업로드 응답에 "백그라운드로 처리 시작됨"을 포함하는 정도만 추가하면 된다 — 이 부분은 프론트가
업로드 후 처리 완료를 어떻게 알고 싶어하는지(폴링? SSE?)에 따라 갈릴 수 있어서, 실제 프론트
연동 시점에 다시 확인하는 게 좋다.

## 2. 현재 DB 스키마 (`app/db/models.py`, PostgreSQL)

테이블은 4개뿐이다. Alembic이 관리하므로 이 문서에 옮겨적은 내용이 아니라 항상
`app/db/models.py` + `migrations/`가 최종 소스다 (스키마가 바뀌면 이 표도 같이 갱신할 것).

### `documents`

문서 하나당 행 하나. 파이프라인 상태(`status`)가 이 테이블의 핵심이고, 나머지 컬럼 대부분은
각 단계가 남기는 진단/진행률 정보다.

| 컬럼 | 타입 | Null | 설명 |
|---|---|---|---|
| `id` | String (UUID) | PK | |
| `filename` | String | NOT NULL | 원본 파일명 |
| `file_path` | String | Y | 서버에 저장된 실제 경로. `extraction_worker`가 읽음 |
| `file_hash` | String (index) | Y | SHA256. 동일 파일 재업로드 감지용 |
| `status` | Enum(`DocumentStatus`) | NOT NULL, 기본 `uploaded` | 아래 상태 흐름 참고 |
| `raw_text` | Text | Y | 추출된 원문(표 마커 포함). `extraction_worker`가 채움 |
| `language` | String | Y | 감지된 언어 |
| `category` | String | Y | 소프트 의도 분류 결과 (가장 가까운 카테고리) |
| `category_similarity` | float | Y | 위 카테고리와의 코사인 유사도 |
| `error_message` | Text | Y | `status=failed`일 때 원인 |
| `warning_message` | Text | Y | 실패는 아니지만 품질 경고 (예: OCR 저품질) |
| `retry_count` | int | 기본 0 | 자동/수동 재시도 횟수 |
| `current_page` / `total_pages` | int | Y | OCR 진행률 |
| `extraction_quality_score` | float | Y | 추출 품질 점수 |
| `extraction_quality_details` | Text(JSON) | Y | 품질 진단 상세 |
| `extraction_method` | String | Y | 어떤 추출 경로를 탔는지 (native/OCR 등) |
| `pipeline_version` | String | Y | |
| `indexed_at` | DateTime(tz) | Y | 임베딩까지 끝나 `ready`가 된 시각 |
| `created_at` / `updated_at` | DateTime(tz) | 자동 | |

**`status` 흐름** (`DocumentStatus` enum, DB엔 소문자 값으로 저장됨):
```
uploaded → extracting → extracted → chunked → ready
                └→ needs_review (OCR 품질 미달, 사람 확인 필요 — 청킹/임베딩 안 함)
각 단계 실패 시 어디서든 → failed (error_message 참고)
```

관계: `chunks`(1:N, `DocumentChunk`), `labels`(1:N, `DocumentLabel`, 문서 삭제 시 cascade 삭제).

### `document_labels`

문서 1개 : 라벨 N개 (다대다 아님, 문서 기준 1:N). `(document_id, label)` 조합에 유니크 제약.

| 컬럼 | 타입 | Null | 설명 |
|---|---|---|---|
| `id` | String (UUID) | PK | |
| `document_id` | String | FK → `documents.id`, index | |
| `label` | String, index | NOT NULL | 예: "두정테크", "용접방식" |
| `created_at` | DateTime(tz) | 자동 | |

### `document_chunks`

청킹된 조각 하나당 행 하나. 텍스트/표/이미지 청크가 이 한 테이블에 섞여 있고, `is_table`/
`image_path` 유무로 구분한다 (`GET /api/documents/{id}/chunks`가 이 판별 로직의 실제 예시).

| 컬럼 | 타입 | Null | 설명 |
|---|---|---|---|
| `id` | String (UUID) | PK | |
| `document_id` | String | FK → `documents.id` | |
| `text` | Text | NOT NULL | 청크 본문 (라벨 접두어 `[문서: ...]` 포함) |
| `page_number` | int | Y | |
| `is_table` | bool | 기본 False | |
| `table_confidence` | float | Y | 표 청크일 때 행별 열개수 일관성 비율 |
| `image_path` | String | Y | 있으면 이미지 캡션 청크 (원본 이미지 경로) |
| `embedded` | bool | 기본 False | `embedding_worker`가 완료 시 True |
| `embed_retry_count` | int | 기본 0 | |
| `precomputed_dense_vector` | Text(JSON) | Y | 청킹 단계에서 이미 계산된 벡터 (있으면 재임베딩 생략) |

실제 벡터(dense+sparse)는 이 테이블이 아니라 **Qdrant**(`documents` 컬렉션)에 있다 —
`document_chunks.id`가 Qdrant 포인트와 매칭되는 키다. 즉 검색은 Qdrant에서, 청크 원문/메타는
필요시 PostgreSQL에서 보충하는 구조.

### `chat_logs`

질문-답변 기록 (감사 로그 성격). **user_id 같은 사용자 식별 컬럼이 없다** — 지금 인증을
안 하기로 했으니 당장은 문제없지만, 나중에 "누가 물어봤는지"가 필요해지면 이 테이블에
컬럼을 추가하는 Alembic 마이그레이션이 필요하다.

| 컬럼 | 타입 | Null | 설명 |
|---|---|---|---|
| `id` | String (UUID) | PK | |
| `question` | Text | NOT NULL | |
| `question_language` | String | Y | |
| `question_embedding` | Text(JSON) | Y | 질문 캐싱용 dense 벡터 |
| `answer` | Text | NOT NULL | |
| `created_at` | DateTime(tz) | 자동 | |

## 3. 기존 코드에서 반드시 읽어야 할 부분

새로 안 만들고 재사용해야 하는 부분과, 계약(스키마/DB)만 참고하면 되는 부분을 구분했다.

| 파일 | 왜 봐야 하는지 |
|---|---|
| `app/main.py` (`lifespan`, 75~114줄) | `app.state`에 뭐가 올라가 있는지(embedding_provider, vector_store, reranker, llm_provider, question_cache, gpu_lock 등) — 새 라우터가 그대로 꺼내 쓸 것들 |
| `app/main.py` (`_run_chat_pipeline`, 723~1023줄) | 검색→리랭킹→LLM 답변까지의 실제 로직 전체. **재구현 금지, 그대로 import해서 재사용**. 캐시/의도분류/GPU 잠금까지 다 여기 들어있음 |
| `app/main.py` (`upload_document`, 141~200줄) | 파일 저장 + `Document(status=UPLOADED)` 기록 로직. 새 업로드 엔드포인트를 만들 때 이 흐름(파일 해시로 중복 검사 등)을 그대로 참고 |
| `app/routers/evaluation.py` | "기존 파이프라인 함수를 인자로 받는 별도 라우터"를 실제로 만든 예시. `app/backend`도 이 구조를 그대로 따라가면 됨 (import 순환 피하는 방법 포함) |
| `app/api_models.py` | 기존 요청/응답 Pydantic 스키마. 새 계약을 그대로 베끼지는 않지만 필드명 참고용 |
| `app/db/models.py` | `Document.status` 흐름(`uploaded→...→ready`), `DocumentChunk`, `DocumentLabel` — API가 결국 이 테이블들을 읽고 쓰는 것이므로 스키마를 이해해야 함. 이 파일 자체는 안 건드림 |
| `app/core/retrieval_pipeline.py` | `_run_chat_pipeline`이 내부적으로 쓰는 `retrieve_candidates`/`rerank_candidates`. 직접 호출할 일은 적지만, 검색 결과(`SearchResult`)에 어떤 메타데이터(document_id, filename, page_number, image_path)가 들어있는지 알아야 응답 스키마를 정확히 짤 수 있음 |
| `app/config.py` | 환경변수로 조정 가능한 값들 전체 목록. 새 엔드포인트에 타임아웃/페이지네이션 상한 등을 추가할 때 기존 패턴(Pydantic Settings) 따라가기 |

## 4. 권장 폴더 구조 (초안)

```
app/backend/
  __init__.py
  schemas.py     # envelope(SuccessEnvelope/ErrorEnvelope) + 요청/응답 모델
  chat.py        # POST /api/backend/chat 라우터
  documents.py   # 문서 업로드/조회 라우터
  router.py      # 위 라우터들을 하나로 묶어서 main.py에 등록할 진입점
```

`app/main.py`에는 아래 한 줄만 추가되는 형태를 목표로 한다 (기존 로직 건드리지 않음).
```python
from .backend.router import create_backend_router
...
app.include_router(create_backend_router(_run_chat_pipeline))
```

## 5. 확인이 필요한 부분

- 문서 업로드까지 `app/backend`에 새로 만들지, 아니면 업로드는 기존 `/api/documents/upload`를
  프론트가 그대로 쓰고 `app/backend`는 채팅(질문 응답)만 새 계약으로 감쌀지 — "RAG 핵심 기능"이
  구체적으로 업로드까지 포함하는지 채팅만 급한 건지에 따라 1차 작업 범위가 달라진다.
- 에러 응답 포맷(`success/error` 봉투)을 `app/backend` 라우터에만 적용할지, 기존 콘솔용
  엔드포인트에도 나중에 맞출지 — 지금은 기존 걸 안 건드리는 쪽으로 잡았지만, 프론트가 두 가지
  포맷을 다 상대해야 하면 나중에 불편해질 수 있다.
- 업로드 후 처리 완료 시점을 프론트가 어떻게 알아야 하는지(폴링 vs SSE vs 웹훅) — 아직 프론트
  설계가 없어서 이건 실제 프론트 작업 시작 시점에 다시 맞추는 걸 권장한다.
