# Chat Stream API 스펙

## 1. 엔드포인트

```
GET /api/v1/chat-stream
```

| 파라미터 | 위치 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| `question` | query | string | Y | 사용자 질문 |

- 응답 `Content-Type`: `text/event-stream`
- 인증: 없음
- 성공/실패 여부와 무관하게 HTTP 상태 코드는 `200`이다 (결과는 스트림 안의 `done` 이벤트로 판단).
  단, `question`이 아예 없는 요청은 FastAPI 기본 검증에 걸려 `422`를 반환한다.

## 2. 요청 예시

```bash
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=문서 업로드는 어떻게 하나요?"
```

## 3. 응답 — SSE 이벤트 스펙

매 줄 `data: <JSON>\n\n` 형태. `type` 필드로 종류를 구분한다.

### `progress`
```json
{"type": "progress", "message": "string"}
```

### `token`
```json
{"type": "token", "token": "string"}
```

### `done` (성공, 요청당 정확히 1회)
```json
{
  "type": "done",
  "success": true,
  "data": {
    "answer": "string",
    "sources": [
      {
        "document_id": "string",
        "filename": "string",
        "page_number": 0,
        "similarity": 0.0
      }
    ],
    "images": [
      {
        "image_url": "string",
        "caption": "string",
        "chunk_id": "string"
      }
    ]
  }
}
```

### `done` (실패, 요청당 정확히 1회)
```json
{
  "type": "done",
  "success": false,
  "error": {
    "message": "string"
  }
}
```

## 4. 필드 설명

| 필드 | 타입 | 설명 |
|---|---|---|
| `data.answer` | string | 완성된 답변 전체 텍스트. `token` 이벤트들을 순서대로 이어붙인 것과 동일한 내용 |
| `data.sources` | array | 답변 근거로 쓰인 문서 목록 (문서 단위로 중복 제거, 유사도 내림차순) |
| `data.sources[].document_id` | string | 문서 UUID |
| `data.sources[].filename` | string | 원본 파일명 |
| `data.sources[].page_number` | int \| null | 근거 페이지 번호. 없으면 `null` |
| `data.sources[].similarity` | float | 0~1 범위 유사도 점수 |
| `data.images` | array | 근거로 쓰인 이미지 목록. 없으면 빈 배열 |
| `data.images[].image_url` | string | 이미지 상대 경로 (`/images/...`). API 베이스 URL을 붙여서 사용 |
| `data.images[].caption` | string | 이미지 설명 |
| `data.images[].chunk_id` | string | 근거 청크 UUID |

## 5. 에러 응답

| 필드 | 타입 | 설명 |
|---|---|---|
| `error.message` | string | 실패 사유 (사람이 읽는 설명) |
