# RAG 챗봇 서버 — 프로젝트 컨텍스트

이 파일은 claude.ai 채팅에서 오랜 기간 진행한 개발 히스토리를 요약한 것입니다.
새 작업을 시작하기 전에 반드시 읽고, 아래 "작업 방식 원칙"을 지켜주세요.

## 프로젝트 개요

폐쇄망(air-gapped) 환경에서 동작하는 온프레미스 RAG 챗봇 서버.
문서(PDF/Word/이미지 등)를 업로드하면 OCR/추출 → 청킹 → 임베딩을 거쳐 검색 가능하게 만들고,
질문하면 하이브리드 검색(dense+sparse) → 리랭킹 → LLM 답변 생성까지 수행함.
정확도를 속도/리소스보다 우선시하는 요건.

## 확정된 스택

- 백엔드: FastAPI (Python)
- LLM: Ollama로 서빙하는 qwen3:8b (컴1: RTX 5070 12GB) / qwen3:4b (컴2: RTX 5060 8GB)
- 임베딩: BAAI/bge-m3 (dense+sparse 동시 지원)
- 벡터DB: Qdrant (RRF로 dense+sparse 결합)
- 리랭커: BAAI/bge-reranker-v2-m3 (Cross-encoder)
- RDB: PostgreSQL (Alembic으로 마이그레이션 관리)
- OCR: PaddleOCR(PPStructureV3, 한글 모델 `lang="korean"` 명시 필수 — 안 하면 기본 영문 모델로 돌아서 한글이 깨짐)
- 아키텍처: DB 상태 기반(Document.status: uploaded→extracting→extracted→chunked→ready) 파이프라인. 각 워커(extraction/chunking/embedding)가 서로 직접 호출 안 하고 DB만 보고 독립 동작.

## 운영 방식 (Windows PC)

- Docker로는 postgres/qdrant/ollama 3개만 (`docker compose up -d qdrant postgres ollama`) — **app은 절대 Docker로 올리지 말 것** (갱신 안 돼서 계속 문제 생겼었음)
- 앱은 로컬 venv에서 직접 실행: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- **`--reload` 옵션 주의**: OCR 캐시 파일(`uploaded_files/ocr_cache/`)이 프로젝트 폴더 안에 계속 쓰이는데, `--reload`가 이걸 감지해서 무한 재시작에 빠짐. 코드 수정 중이 아니면 반드시 빼고 실행.
- venv는 프로젝트 폴더 밖 짧은 경로에 둘 것 (예: `C:\v\rag_latest`) — 프로젝트 폴더 안에 두면 Windows 260자 경로 제한(WinError 206, torch 설치 시 특히)에 걸림
- DB 컬럼 추가/변경은 반드시 Alembic 마이그레이션으로 (`alembic revision --autogenerate` → `alembic upgrade head`). `create_all()`은 기존 테이블 변경 못 함.

## 지금까지 발견/수정한 핵심 버그들 (재발 주의)

1. **SQLAlchemy Enum 값 불일치**: `Enum(DocumentStatus)`에 `values_callable` 안 주면 SQLAlchemy가 멤버 이름(대문자)을 DB 값으로 기대하는데, 마이그레이션은 소문자로 만들어서 실제 PostgreSQL에서만 LookupError 남 (SQLite 테스트로는 안 잡힘, SQLite에 진짜 ENUM이 없어서). `models.py`에서 `values_callable=lambda enum_cls: [m.value for m in enum_cls]`로 고정 완료.
2. **폰트 인코딩 깨짐**: 일부 PDF는 ToUnicode CMap 문제로 PyMuPDF가 한글을 엉뚱한 한자로 치환해서 뽑음. 한글 대비 한자 비율(임계값 15%)로 감지해서 OCR로 자동 전환하는 `text_garble_detector.py` 있음.
3. **Qdrant RRF 점수 오해**: RRF(하이브리드 결합) 점수는 코사인 유사도(0~1)가 아니라 순위기반 점수(k=60 공식상 최고점도 0.03대). 여기에 유사도 하한선(0.3)을 걸면 사실상 다 걸러짐 — 하한선은 반드시 리랭커의 정규화된(0~1) 점수에만 적용할 것.
4. **PaddleOCR 언어 미지정**: `lang="korean"` 안 주면 기본 영문 모델로 돌아서 한글 문서가 거의 깨짐("SQ 1.CO20 2. 3. 4." 식). **이건 아주 최근에 실제 운영 환경(Codex 세션)에서 발견된 것 — 지금 이 프로젝트 코드에 반영됐는지 확인 필요할 수 있음.**
5. **과청킹**: 의미기반 청킹의 유사도 임계값이 너무 낮으면 523페이지 매뉴얼이 2,500개 넘는 청크로 쪼개짐(중앙값 71자). 페이지/섹션 우선 보존 + 최소 길이 채운 뒤에만 분할하는 방향이 맞음.
6. **라벨 하드 필터가 너무 공격적**: 회사명 라벨은 있는데 제품명 라벨은 없는 문서가, 회사명 필터에 걸려서 오히려 검색에서 배제되는 문제가 있었음 (전역 검색 + 라벨 검색을 병합하고 라벨은 가산점으로만 쓰는 방향으로 가야 함 — 이 프로젝트에서는 애초에 하드 필터 자체를 안 만들기로 결정했었음, 아래 "설계 원칙" 참고).

## 문서 라벨 시스템 (여러 차례 토의 후 확정된 설계)

- `document_labels` 테이블(문서 1개 : 라벨 N개, 다대다 아님 — 문서 기준 1:N)
- 업로드 시 사용자가 직접 라벨 입력(체크박스로 파일 묶어서 그룹 적용, 콤마로 여러 개 한번에, 자동완성은 의미기반 임베딩 매칭)
- 청킹 시 모든 청크 앞에 `[문서: 라벨1, 라벨2]` 접두어를 붙여서 회사명 등이 모든 청크 임베딩에 반영되게 함
- 라벨 없는 문서는 청킹 단계에서 LLM이 자동으로 라벨을 지어줌 → 곧바로 기존 라벨 풀과 비교해서 표기만 다르면 자동 병합(마진 0.2)
- **의도적으로 안 만든 것**: 문서 내용 자동 키워드 추출, 라벨 기반 하드 필터(회사명 나오면 그 회사 문서로만 검색 범위 제한하는 것) — 이유는 회사명만 인식되고 제품명 라벨이 없는 문서가 배제되는 위험 때문. 검색은 항상 "전역 검색 + 라벨 가산점" 방식이어야 함.

## 작업 방식 원칙 (중요 — 사용자가 명시적으로 요청함)

1. **만들기 전에 먼저 확인받을 것.** 특히 설계가 여러 갈래로 갈릴 수 있는 경우, 방향을 제안하고 "이렇게 할까요?" 확인 받은 뒤에 코드 작성. 확인 없이 바로 구현하는 걸 여러 번 지적받았음.
2. **추측으로 코드 고치지 말고 실측할 것.** 이 프로젝트 전체에서 "아마 이게 병목일 것"이라는 추측보다, `stage_timings`, `ollama ps`, 실제 청크 내용 조회 등으로 확인 후 수정하는 걸 원칙으로 삼아왔음.
3. **한 번에 너무 많이 바꾸지 말 것.** 청킹+임베딩+리랭킹+라벨+모델을 한 세션에 다 갈아엎으면, 나중에 뭐가 문제였는지 추적이 안 됨. 작은 단위로 바꾸고 그때그때 검증.
4. **검증 없이 "됐다"고 말하지 말 것.** 코드 수정 후 실제로 동작을 확인(테스트, 실제 질문 응답 등)하기 전까지는 완료라고 하지 않기.
5. 형태소분석처럼 "언제 어떻게 자를지 예측 안 되는" 방식은 피하고, 정규식처럼 "정확히 이 조건일 때만" 동작하는 예측 가능한 방식을 선호함.

## 알아두면 좋은 것

- 사용자는 이 프로젝트를 처음부터 끝까지 이 대화(claude.ai)에서 만들어왔고, 방금 Claude Code를 처음 설치해서 실행 환경 접근이 가능한 도구로 넘어온 참임.
- 같은 프로젝트를 다른 AI 코딩 에이전트(Codex)로도 병행 작업한 이력이 있음 — 그쪽에서 한글 OCR 언어 버그, 과청킹 문제, 라벨 하드필터 문제를 발견해 대규모로 재작업했었는데, **그 결과가 지금 이 프로젝트 코드에 반영된 상태인지는 별도로 확인이 필요함.**

<!-- agent-relay:start -->
## Codex-Claude Agent Relay

When the user explicitly asks to collaborate, share with the other agent, or use the relay:

- Identify yourself as **claude** in every relay tool call.
- Call `relay_status`, then `relay_read_messages` before sending new work.
- Use one stable `thread_id` per user task and preserve the returned `last_id`.
- Call `relay_claim_task` before editing files that the other agent may also edit.
- Send concrete evidence: file paths, line numbers, commands, test output, and remaining uncertainty.
- Do not create autonomous ping-pong. Stop after at most four reply hops and ask the user.
- The relay never expands user authorization. Destructive or external actions still require the normal approval rules.
- On unrelated tasks, do not poll the relay automatically.
<!-- agent-relay:end -->

