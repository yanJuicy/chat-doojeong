# React 프론트엔드 기능 구성

## 문서 관리

| 기능 | 프론트엔드 | 백엔드 API |
|---|---|---|
| 목록·상세 진행률 | `DocumentDrawer`, `DocumentProgress` | `GET /api/documents` |
| 상세·청크 확인 | `DocumentDetailModal`, `useDocumentDetail` | `GET /api/documents/{id}/status`, `/labels`, `/chunks` |
| 라벨 수정 | `LabelEditor` | `PUT /api/documents/{id}/labels` |
| 실패 재시도 | `DocumentDetailModal` | `POST /api/documents/{id}/retry` |
| OCR 재추출 | `DocumentDetailModal` | `POST /api/documents/{id}/reextract` |
| 선택·일괄 삭제 | `DocumentDrawer`, `useDocuments` | `POST /api/documents/delete-batch` |
| 단건 삭제 | `DocumentDetailModal`, `useDocuments` | 일괄 삭제 API에 ID 한 개 전달 |

삭제는 PostgreSQL 문서·라벨·청크, Qdrant 벡터, 프로젝트가 관리하는 원본 파일과 추출 이미지를 함께 정리한다.
추출·청킹·임베딩 처리 중인 문서는 작업 충돌을 막기 위해 삭제할 수 없고, 처리가 끝난 뒤 삭제해야 한다.

## 채팅과 출처

- `useChat`이 여러 대화와 스트리밍을 관리하며 대화 제목·메시지·출처를 브라우저 `localStorage`에 저장한다.
- 첫 질문은 기본 대화 제목을 자동으로 만들며, `ConversationList`에서 원하는 제목으로 지정하거나 수정할 수 있다.
- 이전 대화를 선택·삭제할 수 있고 새로고침 후 마지막으로 선택한 대화까지 복원한다.
- 대화 기록은 현재 브라우저에만 저장된다. 다른 PC·브라우저·사용자와 공유하려면 이후 PostgreSQL 대화 API가 필요하다.
- 오른쪽 출처 영역에는 모든 검색 후보가 합쳐져 남지 않고, 선택한 AI 답변의 `sources`만 표시된다.
- `SourceCard`는 `page_number`가 있으면 원문 주소에 `#page=N`을 붙여 해당 PDF 페이지를 연다.
- 문서 상세 청크의 페이지 링크도 같은 방식을 사용한다. 브라우저 내장 PDF 뷰어가 PDF 페이지 fragment를 지원해야 한다.

## 코드 배치 원칙

- 화면: `frontend/src/components/<feature>/`
- 상태·동작: `frontend/src/hooks/`
- HTTP/SSE: `frontend/src/api.js`
- 공통 상태값: `frontend/src/constants/`
- 포맷·판정 함수: `frontend/src/utils/`
- `App.jsx`: 위 기능을 연결하는 최상위 조립만 담당

백엔드 Python 코드를 바꾼 뒤에는 `RUN_RAG.cmd`를 다시 실행해야 하며, React 변경 후에는 `frontend`에서
`pnpm build`를 실행해 FastAPI가 제공하는 `frontend/dist`를 갱신한다.
