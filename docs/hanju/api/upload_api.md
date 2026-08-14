# 문서 업로드 / 상태 조회 API 스펙

## 1. 엔드포인트

```
POST /api/v1/upload
GET  /api/v1/documents/{document_id}
```

업로드 후 곧바로 검색 가능한 게 아니다 — 파일 저장/등록만 끝난 상태(`status: "uploaded"`)로
응답이 오고, OCR → 청킹 → 임베딩 처리는 서버가 백그라운드에서 이어서 진행한다. 프론트는
업로드 응답을 받은 직후부터 `GET /api/v1/documents/{document_id}`를 몇 초 간격으로 폴링해서
`status`가 `"ready"`가 되는 시점을 확인해야 한다 (그 전까지는 이 문서 내용이 검색/답변에
쓰이지 않는다).

인증 없음. HTTP 상태 코드가 그대로 성공/실패를 의미한다 (chat-stream과 달리 SSE가 아님).

## 2. 흐름 (시퀀스 다이어그램)

업로드 한 번에 두 엔드포인트가 함께 쓰인다 — `POST /upload`는 등록 + 백그라운드 처리 시작만
하고 바로 응답하며, 실제 처리가 끝났는지는 `GET /documents/{id}`를 반복 호출해서 확인한다.

```mermaid
sequenceDiagram
    participant FE as 프론트엔드
    participant Upload as POST /api/v1/upload
    participant DB as PostgreSQL
    participant Worker as 백그라운드 워커<br/>(추출→청킹→임베딩)
    participant Status as GET /api/v1/documents/{id}

    FE->>Upload: 파일 업로드 (multipart)
    Upload->>Upload: 확장자 / 크기 검사
    Upload->>DB: 파일 해시(sha256)로 중복 확인

    alt 동일 파일 이미 존재
        Upload-->>FE: 200 success, data.is_duplicate=true
    else 신규 파일
        Upload->>DB: 파일 저장 + Document(status=uploaded) 기록
        Upload-->>FE: 200 success, data.status="uploaded"
        Upload->>Worker: 백그라운드 트리거 (응답 이후 실행, 대기 안 함)
    end

    loop status가 "ready"(또는 "failed"/"needs_review")가 될 때까지
        FE->>Status: GET /documents/{document_id}
        Status->>DB: 현재 status 조회
        Status-->>FE: 200 success, data.status="extracting" 등
        Note over FE: 잠시 대기 후 다시 폴링 (예: 2~3초 간격)
    end

    par 백그라운드 처리는 폴링과 별개로 계속 진행
        Worker->>DB: status 순차 갱신<br/>uploaded→extracting→extracted→chunked→ready
    end

    FE->>Status: GET /documents/{document_id}
    Status-->>FE: 200 success, data.status="ready"
    Note over FE: 이 시점부터 /api/chat 등으로<br/>이 문서 내용 검색 가능
```

## 3. `POST /api/v1/upload`

### 요청

`multipart/form-data`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `file` | file | Y | 업로드할 파일 |
| `labels` | string[] | N | 이 문서를 설명하는 태그 (예: `["두정테크", "용접방식"]`). 같은 키로 여러 번 보내면 됨 |

지원 파일 형식: `.pdf` `.docx` `.txt` `.md` `.html` `.htm` `.jpg` `.jpeg` `.png`
(zip 일괄 업로드는 이 엔드포인트에서 지원하지 않음)

파일 크기 상한: 서버 설정값(`max_upload_size_mb`, 기본 200MB) 초과 시 `413`.

### 요청 예시

```bash
curl -X POST "http://localhost:8000/api/v1/upload" \
  -F "file=@manual.pdf" \
  -F "labels=두정테크" \
  -F "labels=용접방식"
```

### 응답 — 성공 (`200`)

```json
{
  "success": true,
  "data": {
    "document_id": "string",
    "filename": "string",
    "status": "uploaded",
    "is_duplicate": false
  }
}
```

같은 파일(바이트 단위로 완전히 동일)이 이미 업로드돼 있으면, 새로 등록하지 않고
`is_duplicate: true`와 함께 기존 문서의 `document_id`/`status`를 그대로 돌려준다.

### 응답 — 실패

| 상황 | 상태 코드 | `error.code` |
|---|---|---|
| 지원하지 않는 확장자 | `400` | `VALIDATION_ERROR` |
| 파일 크기 초과 | `413` | `VALIDATION_ERROR` |

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "사람이 읽는 실패 사유"
  }
}
```

## 4. `GET /api/v1/documents/{document_id}`

업로드 후 처리 진행 상황을 확인하는 폴링용 엔드포인트.

### 요청 예시

```bash
curl "http://localhost:8000/api/v1/documents/1f2e3d4c-..."
```

### 응답 — 성공 (`200`)

```json
{
  "success": true,
  "data": {
    "document_id": "string",
    "filename": "string",
    "status": "ready",
    "error_message": null,
    "warning_message": null,
    "current_page": 12,
    "total_pages": 12
  }
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `status` | string | 파이프라인 진행 단계. 아래 "status 흐름" 참고 |
| `error_message` | string \| null | `status: "failed"`일 때 실패 원인 |
| `warning_message` | string \| null | 실패는 아니지만 품질 경고 (예: OCR 저품질) |
| `current_page` / `total_pages` | int \| null | OCR 진행률 (이미지/텍스트 등 페이지 개념이 없는 문서는 `null`) |

**`status` 흐름:**
```
uploaded → extracting → extracted → chunked → ready   ← 이 상태부터 검색/답변에 사용됨
                └→ needs_review (OCR 품질 미달, 사람 확인 필요 — 청킹/임베딩 진행 안 함)
각 단계 실패 시 어디서든 → failed (error_message 참고)
```

### 응답 — 실패 (`404`)

```json
{
  "success": false,
  "error": {
    "code": "NOT_FOUND",
    "message": "문서를 찾을 수 없습니다."
  }
}
```
