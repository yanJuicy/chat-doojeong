# `/api/v1/chat-stream` API 문서

React 프론트엔드가 채팅 기능에서 쓰는 스트리밍 채팅 API. 기존 콘솔용 `/api/chat`, `/api/chat/stream`과는
별개로 `app/backend/` 아래에 새로 만들었고, 두 기존 엔드포인트는 전혀 건드리지 않았다.

## 왜 별도로 만들었나

- 기존 `/api/chat*`은 브라우저 콘솔(`app/static/index.html`, 개발용 관리 화면)이 쓰는 응답 형태라 필드가 많고
  (`intent_scores`, `stage_timings` 등 디버그 정보 포함) FE가 쓰기엔 불필요한 게 섞여 있었다.
- 검색→리랭킹→LLM 답변 생성이라는 **핵심 로직은 재구현하지 않고** `app/main.py`의 `_run_chat_pipeline`
  제너레이터를 그대로 재사용한다. `app/routers/evaluation.py`가 이미 같은 함수를 인자로 주입받아 쓰는
  패턴(`create_evaluation_router(run_chat_pipeline)`)이 있어서, `app/backend/router.py`도 똑같은
  `create_backend_router(run_chat_pipeline)` 형태로 만들었다.

## 파일 위치

| 파일 | 내용 |
|---|---|
| `app/backend/router.py` | 라우터 본체 — `create_backend_router()`, SSE 이벤트 포맷팅(`_format_event`) |
| `app/backend/schemas.py` | FE 응답 전용 Pydantic 모델 (`BackendChatData`, `BackendErrorDetail`) |
| `app/backend/__init__.py` | 빈 패키지 마커 |
| `app/main.py` | `app.include_router(create_backend_router(_run_chat_pipeline))` 한 줄로 연결 (평가 라우터 등록 바로 아래) |

## 엔드포인트

```
GET /api/v1/chat-stream?question=<질문 텍스트>
```

- **메서드가 GET인 이유**: 브라우저 네이티브 `EventSource`가 GET만 지원한다. 기존 `/api/chat/stream`도
  같은 방식이라 일관성을 맞췄다.
- `question`은 필수 쿼리 파라미터다. 빠뜨리면 FastAPI가 파이프라인까지 가지도 않고 자동으로
  `422 Unprocessable Entity`를 돌려준다(Pydantic 기본 검증 응답, 이 프로젝트 코드가 만든 게 아니라
  FastAPI 프레임워크 동작).
- 응답 `Content-Type`은 `text/event-stream` (SSE). `Cache-Control: no-cache`, `X-Accel-Buffering: no`
  헤더가 붙는다 (중간에 프록시/버퍼링이 스트리밍을 끊지 않도록).
- CORS: `app/main.py`에 등록된 `CORSMiddleware`가 `http://localhost:3000`, `http://127.0.0.1:3000`,
  `http://localhost:5173`, `http://127.0.0.1:5173`을 허용한다 (CRA/Vite 기본 포트). 배포 시 실제 프론트
  도메인으로 좁혀야 한다.

## SSE 이벤트 스펙

매 줄은 `data: <JSON>\n\n` 형태다 (`data: `는 SSE 프로토콜 자체 규칙). JSON 안의 `type` 필드로 종류를
구분한다.

### `progress` — 로딩 상태 문구

파이프라인이 새 단계(질문 임베딩, 캐시 확인 등)를 시작할 때마다 온다. 화면 로딩 인디케이터 문구로 쓰면 됨.

```json
{"type": "progress", "message": "문서 검색 중... (풀 64개에서 상위 후보 추림)"}
```

### `token` — 답변 조각 (스트리밍의 핵심)

LLM이 답변을 생성하는 동안 조각(토큰) 단위로 여러 번 온다. **받는 순서대로 이어붙이면 타이핑 효과가 됨.**
질문이 캐시에 걸리면(아래 참고) 이 이벤트 자체가 하나도 안 올 수 있다 — 그 경우 `done`의 `data.answer`를
바로 통째로 쓰면 된다.

```json
{"type": "token", "token": "안녕"}
{"type": "token", "token": "하세요"}
```

### `done` — 종료 (성공/실패 상관없이 요청당 정확히 1번만 옴)

**성공:**
```json
{
  "type": "done",
  "success": true,
  "data": {
    "answer": "완성된 답변 전체 텍스트",
    "sources": [
      {
        "document_id": "649592a0-28f8-4e27-955f-65fe4eefbd8d",
        "filename": "[레인보우로보틱스] RB 시리즈_사용자 매뉴얼_v6.3_국문_241106.pdf",
        "page_number": 439,
        "similarity": 0.4891
      }
    ],
    "images": [
      {"image_url": "/images/abc123.png", "caption": "이미지 설명(캡션)", "chunk_id": "..."}
    ]
  }
}
```

`images[].image_url`은 **상대 경로**다. 실제 이미지 바이트는 JSON에 안 실리고, `app/main.py`의
`app.mount("/images", StaticFiles(directory=settings.image_storage_dir), ...)`가 별도로 정적 서빙한다
— FE는 `<img src={`${API_BASE}${image_url}`} />`처럼 API 베이스 URL을 앞에 붙여서 써야 한다. 근거
청크 중 이미지가 없는 답변이면 `images`는 빈 배열로 온다.

**실패:**
```json
{
  "type": "done",
  "success": false,
  "error": {
    "message": "[질문 언어 감지 및 임베딩 생성] 단계에서 실패: Numpy is not available"
  }
}
```

FE 로직: `type === "done"`이면 `success`를 보고 정상 답변 화면(`data`) 또는 에러 화면(`error.message`)으로
전환. `data.answer`는 `token`을 이어붙인 것과 같은 내용이라, 스트리밍 중엔 `token`으로 실시간 표시하다가
`done` 도착 시 `data.answer`로 한 번 덮어써서 확정하는 방식을 권장 (토큰 하나가 유실돼도 최종본으로 보정됨).

### 응답에서 뺀 필드들 (의도적)

원래 파이프라인(`ChatResponse`)엔 더 많은 정보가 있지만, FE가 실제로 안 쓰는 디버그성 필드는 아예 안 보낸다:

| 뺀 필드 | 원래 의미 | 뺀 이유 |
|---|---|---|
| `timing` 이벤트 전체 | 단계별 소요시간 | 개발자 성능 디버깅용, 서버 로그로 충분 |
| `question_language` | 감지된 질문 언어 | 지금 FE 화면에 안 씀 |
| `meta.n_context_chunks` | 근거로 쓴 청크 개수 | 내부 로그성 |
| `meta.cache_hit`, `cache_similarity` | 캐시 히트 여부/유사도 | 디버깅용 |
| `intent_scores` | 질문 카테고리 분류 점수 | FE 미사용 |
| `error.code`, `error.stage` | 에러 코드/실패 단계 | 서버 로그에 이미 남음, FE 화면엔 `message`만 있으면 충분 |

나중에 필요해지면 `app/backend/schemas.py`의 `BackendChatData`/`BackendErrorDetail`에 필드 추가하고
`app/backend/router.py`의 `_to_backend_data`/`_format_event`에서 채워 넣으면 됨 — 원본 데이터
(`ChatResponse`)엔 이미 다 있어서 파이프라인 쪽은 안 건드려도 된다. (`images`가 실제로 이렇게 추가된
사례 — 처음엔 뺐다가, FE에서 근거 이미지를 보여주기로 하면서 이 두 파일만 고쳐서 다시 넣었다.)

## FE 연동 예시 (React)

```javascript
const es = new EventSource(
  `${API_BASE}/api/v1/chat-stream?question=${encodeURIComponent(question)}`
);

let answer = "";
es.onmessage = (e) => {
  const event = JSON.parse(e.data);
  if (event.type === "token") {
    answer += event.token;
    setAnswer(answer); // 실시간 타이핑 표시
  } else if (event.type === "progress") {
    setLoadingText(event.message);
  } else if (event.type === "done") {
    es.close();
    if (event.success) {
      setAnswer(event.data.answer); // 최종본으로 확정
      setSources(event.data.sources);
    } else {
      setError(event.error.message);
    }
  }
};
```

## curl로 직접 확인하기

```bash
# 스트리밍이 실제로 조각조각 오는지 (버퍼링 없이 보기: -N)
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=문서 업로드는 어떻게 하나요?"

# 한글이 \uXXXX로 안 보이게 (jq 있는 경우)
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=문서 업로드는 어떻게 하나요?" \
  | grep '^data: ' | sed 's/^data: //' | jq -r .

# CORS 헤더 확인
curl -sD - -o /dev/null -G "http://localhost:8000/api/v1/chat-stream" \
  -H "Origin: http://localhost:5173" \
  --data-urlencode "question=핑"
```

## 알아둘 점 / 한계

- **질문 하나짜리 단발 요청이다.** 대화 맥락(이전 질문 기억)은 없다 — `ChatRequest`가 `question` 필드
  하나뿐이라, 멀티턴 대화가 필요해지면 별도로 세션/히스토리 설계가 필요하다 (지금 범위 밖).
  `docs/BACKEND_API_PLAN.md`에 이미 이 이슈가 "확인이 필요한 부분"으로 남아 있음.
- **답변이 항상 사실에 근거한다고 착각하면 안 된다.** 이 시스템은 오직 업로드된 문서 내용만 근거로 답하도록
  설계돼 있어서, "이 챗봇 어떻게 써?" 같은 메타 질문을 하면 문서 내용에서 억지로 답을 찾으려 할 수 있다
  (실측 사례: "문서 업로드는 어떻게 하나요?"를 로봇 매뉴얼 안의 "프로그램 업로드" 내용으로 잘못 해석해서
  답한 적 있음).
- **에러 코드가 세분화돼 있지 않다.** `_run_chat_pipeline`이 모든 예외를 하나의 `except Exception`으로
  잡아서, 실패 원인(Qdrant 다운/Ollama 다운/DB 다운 등)을 FE가 구분해서 다른 화면을 보여주고 싶으면
  지금은 안 된다 — `error.message` 텍스트만 있음.
- **한글 파일명 인코딩 이슈 주의.** `sources[].filename`이 macOS에서 업로드된 문서라면 자모가 분리된
  NFD 형태로 올 수 있다(예: "레인보우로보틱스"가 자음/모음이 따로따로). FE에서 표시 전에
  `filename.normalize("NFC")`로 정규화하는 걸 권장 — 아직 백엔드에서 안 고친 상태.
