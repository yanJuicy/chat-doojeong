# RAG 파이프라인 흐름

특정 엔드포인트 하나가 아니라, 이 서버의 핵심 로직 두 단계 — **문서를 검색 가능하게 만드는
인덱싱 파이프라인**과 **질문에 답하는 질의 파이프라인** — 를 정리한 문서다. 각 단계마다
다이어그램을 먼저 보고, 그 아래 짧은 설명으로 "왜/어떻게"를 채우는 순서로 구성했다.

## 0. 전체 그림

```mermaid
flowchart LR
    subgraph 인덱싱[" 1. 인덱싱 파이프라인 (문서를 검색 가능하게) "]
        direction LR
        A[업로드] --> B[추출<br/>ExtractorRegistry] --> C[청킹<br/>StructuredChunker] --> D[임베딩<br/>embedding_worker]
    end
    subgraph 질의[" 2. 질의 파이프라인 (질문에 답하기) "]
        direction LR
        E[질문] --> F[검색<br/>retrieval_pipeline] --> G[리랭킹<br/>BgeRerankerV2] --> H[LLM 답변 생성]
    end
    D -.->|"status=ready가 된 청크만<br/>검색 대상이 됨"| F
```

두 파이프라인은 **DB 상태(`Document.status`)로만 연결**되고 서로 직접 호출하지 않는다.

---

## 1. 인덱싱 파이프라인 — 문서를 검색 가능하게 만들기

### 1-1. 공통 설계: "찜 → 처리 → 저장"

세 워커(`extraction_worker.py`, `chunking_worker.py`, `embedding_worker.py`) 모두 같은 패턴을
쓴다. 오래 걸리는 작업(OCR, LLM 호출, GPU 인코딩) 동안 DB 행 잠금을 쥐고 있지 않으려는 목적이다.

```mermaid
flowchart LR
    A["① 찜<br/>SELECT ... FOR UPDATE SKIP LOCKED<br/>상태 변경 후 즉시 커밋 (짧은 트랜잭션)"] --> B["② 처리<br/>잠금 없이 OCR/청킹/임베딩<br/>(몇 초~몇 분 걸릴 수 있음)"] --> C["③ 저장<br/>결과를 다시 짧은 트랜잭션으로 커밋<br/>성공→다음 상태 / 실패→재시도 또는 failed"]
```

`SKIP LOCKED`는 이미 다른 워커가 잠근 행을 기다리지 않고 건너뛰게 해서, 워커를 여러 개
동시에 돌려도 같은 문서를 중복으로 집어가지 않는다. `②` 도중 프로세스가 죽으면 문서가 중간
상태에 멈춰 남는데, 추출 워커는 일정 시간 갱신이 없으면 자동으로 되돌리고, 급하면
`POST /api/documents/{id}/retry`(`document_management_api.md`)로 수동 복구한다.

### 1-2. 추출 워커 (`extraction_worker.py`) — `status: uploaded → extracted`

**담당 함수**: `process_pending_documents()`(찜) → `_process_one_document()`(문서 1개 처리)

```mermaid
flowchart TD
    A[파일 확장자 확인] --> B{"ExtractorRegistry가<br/>확장자별 추출기 선택<br/>(최초 1회만 생성 후 캐싱)"}
    B -->|.pdf| C["PdfExtractor<br/>PyMuPDF + PaddleOCR"]
    B -->|.docx| D[WordExtractor]
    B -->|".txt / .md"| E[PlainTextExtractor]
    B -->|".html / .htm"| F[HtmlExtractor]
    B -->|".jpg / .png"| G[ImageExtractor]
    C --> H["텍스트 추출<br/>(페이지마다 current_page 즉시 커밋)"]
    D --> H
    E --> H
    F --> H
    G --> H
    H --> I{"content_hash가<br/>기존 문서와 완전히 같음?"}
    I -->|Yes| J["status = failed<br/>(중복 안내 메시지)"]
    I -->|No| K["evaluate_extraction_quality()<br/>로 품질 점수 계산"]
    K --> L{"OCR 대상 문서(pdf/jpg/png)이고<br/>score < ocr_quality_min_score?"}
    L -->|Yes| M["status = needs_review<br/>(사람 확인 대기, 이후 단계 중단)"]
    L -->|No| N["status = extracted"]
```

새 포맷을 지원하려면 `ExtractorRegistry`에 매핑 한 줄만 추가하면 되고, 워커/서버 코드는
안 건드려도 된다.

**품질 점수 공식** (`evaluate_extraction_quality`) — 한글 자리에 한자가 대량으로 나오는 건
PaddleOCR 언어 미지정이나 PDF ToUnicode 매핑 깨짐의 전형적 신호라, 강하게 감점한다:

```
score = 0.45·길이점수 + 0.30·문자밀도점수 + 0.25·어휘다양성점수 − 한자오염페널티
  길이점수        = min(글자수 / 180, 1.0)
  문자밀도점수    = min(영숫자·한글·한자 비율 / 0.55, 1.0)
  어휘다양성점수  = min(단어수 / 18, 1.0) × min(고유단어비율 / 0.45, 1.0)
  한자오염페널티  = min(한자 / (한글+한자) / 0.30, 1.0) × 0.70  (반복 특수문자 있으면 +0.10)
```

**실패 시**: `retry_count`를 올리고, 상한(`worker_max_retries`) 전이면 `uploaded`로 되돌려
다음 실행 때 자동 재시도, 상한을 넘으면 `failed`로 확정.

### 1-3. 청킹 워커 (`chunking_worker.py`) — `status: extracted → chunked`

**담당 함수**: `process_pending_documents()`. 추출 워커가 뭘로 텍스트를 뽑았는지 전혀 모르고
`Document.raw_text`(문자열)만 본다. 실제 분할은 `StructuredChunker`가 담당한다 — "제목/섹션
구조를 최우선으로 존중"하는 방식이라, 문장 유사도 같은 모호한 기준보다 "이 줄이 제목처럼
보이는가"를 정규식으로 판별하는 규칙 기반 로직이다 (CLAUDE.md의 "예측 가능한 방식 선호" 원칙).

```mermaid
flowchart TD
    A[원문 텍스트] --> B["표/이미지 블록 먼저 분리<br/>(각각 통째로 청크화 예약)"]
    B --> C["제목 후보 줄 탐색<br/>is_heading_line()"]
    C --> D{"제목이 2개 이상<br/>발견됨?"}
    D -->|No, 구조 불명확| E["SemanticChunker에<br/>전체 위임 (의미기반 청킹)"]
    D -->|Yes| F["섹션 트리 구성<br/>heading_path (예: 1.설치 > 1.2 설치절차)"]
    F --> G["표 재조립<br/>merge_native_table_sections()<br/>(모델코드 헤더+숫자행 → 표로 병합)"]
    G --> H["작은 섹션 병합<br/>(토큰수 < 100, 같은 상위 섹션일 때만)"]
    H --> I{"섹션 하나가<br/>chunk_max_tokens 초과?"}
    I -->|Yes| J["그 섹션 안에서만<br/>SemanticChunker로 추가 분할"]
    I -->|No| K[섹션 그대로 청크화]
    J --> L["[섹션: 제목경로] 접두어 부착"]
    K --> L
```

**제목 판별 규칙** (`is_heading_line`): 마크다운(`#`)·번호매기기(`1.`, `1.1`)·도메인 키워드("설치
방법" 등)·전대문자 줄 중 하나면 제목 후보. 단 **한국어 문장 종결 어미(다/요/음/함/니다)로
끝나면 절차 문장으로 보고 제외**한다 ("1. 프로그램을 종료한다."가 제목으로 오인되는 것 방지).
표 안 측정값 행("7.3 kg")도 단위 패턴으로 걸러 섹션 번호 오인을 막는다.

**라벨 자동 생성/교정** — 청크를 실제로 만들기 **전에** 먼저 처리한다 (`embedding_provider`/
`llm_provider`가 주입돼 있을 때만 동작):

```mermaid
flowchart TD
    A[문서에 라벨이 하나도 없음] -->|LLM 호출| B["회사/제품명/주제/문서종류<br/>2~5개 라벨 생성<br/>(원문에 없는 건 추측 금지)"]
    B --> C[라벨 재분류 검사]
    A2[문서에 이미 라벨 있음] --> C
    C --> D["원문 앞 1000자와<br/>현재 라벨의 임베딩 유사도 계산"]
    D --> E{"다른 기존 라벨이<br/>+0.2(LABEL_SWAP_MARGIN) 이상<br/>더 잘 맞음?"}
    E -->|Yes| F[그 라벨로 자동 교체]
    E -->|No| G{"현재 유사도가<br/>0.15(LABEL_ABSOLUTE_FLOOR) 미만?"}
    G -->|Yes| H[라벨 자동 제거]
    G -->|No| I[그대로 유지]
    F --> J["확정된 라벨(없으면 파일명)을<br/>모든 청크 앞에 [문서: 라벨1, 라벨2] 부착"]
    H --> J
    I --> J
```

두 판단 모두 **사람에게 확인 안 받고 조용히 처리한다** (사용자가 "확인 절차 자체가
번거롭다"고 명시적으로 요청해서 이렇게 결정됨 — 여러 파일을 한 번에 묶어 라벨을 대충
적용했을 때 안 맞는 파일에 엉뚱한 라벨이 남는 걸 막는 안전장치).

### 1-4. 임베딩 워커 (`embedding_worker.py`) — `status: chunked → ready`

**담당 함수**: `process_pending_chunks()`. 청킹 워커가 어떤 전략을 썼는지 모르고
`DocumentChunk.embedded == false`인 행만 본다.

```mermaid
flowchart TD
    A["embedded=false 청크<br/>최대 32개(_ENCODE_BATCH_SIZE) 찜"] --> B["embed_hybrid()로<br/>dense+sparse 배치 인코딩<br/>(청크 하나씩이 아니라 묶어서 — 훨씬 빠름)"]
    B --> C["Qdrant 동시 upsert<br/>(Semaphore(16)로 병렬 상한)"]
    C --> D{"배치 성공?"}
    D -->|Yes| E["embedded=true<br/>배치마다 즉시 커밋"]
    D -->|No| F["그 배치 청크만<br/>embed_retry_count += 1"]
    F --> G{"상한(worker_max_retries)<br/>초과?"}
    G -->|Yes| H["다음 실행부터<br/>조회 대상에서 제외"]
    G -->|No| I["embedded는 그대로 false<br/>→ 다음 실행에 재시도"]
    E --> J{"이 문서의 남은<br/>embedded=false 청크가 있음?"}
    J -->|No| K["status = ready<br/>indexed_at = now() 승격"]
    J -->|Yes| L["아직 대기<br/>(문서 전체가 끝나야 ready)"]
```

문서 하나가 청크 100개 중 1개만 계속 실패해도 그 문서 전체는 `ready`가 안 되고 검색에도
노출되지 않는다 — "일부만 검색되는" 어중간한 상태를 피하기 위해서다.

---

## 2. 질의 파이프라인 — 질문에 답하기

`app/main.py`의 `_run_chat_pipeline` 제너레이터 하나가 `/api/chat`, `/api/chat/stream`
`/api/v1/chat-stream`, `/api/evaluation/run` 네 군데에서 재사용된다.

### 2-0. 전체 흐름

```mermaid
sequenceDiagram
    participant FE as 프론트엔드
    participant Pipe as _run_chat_pipeline
    participant Cache as SemanticQuestionCache
    participant Embed as BgeM3EmbeddingProvider
    participant Intent as IntentClassifier
    participant Retrieval as retrieval_pipeline
    participant Reranker as rerank_candidates
    participant LLM as Qwen (Ollama)
    participant DB as PostgreSQL

    FE->>Pipe: 질문
    Pipe->>Pipe: gpu_lock 획득 → 언어 감지
    Pipe->>Cache: get_exact() 완전 일치 확인
    alt 완전 일치 히트
        Cache-->>FE: 즉시 반환 (검색/LLM 생략)
    else 미스
        Pipe->>Embed: embed_hybrid() 질문 임베딩
        Pipe->>Intent: classify() 의도 분류
        Pipe->>Cache: get_semantic() 의미 유사 + 안전조건 확인
        alt 의미 유사 히트
            Cache-->>FE: 즉시 반환
        else 완전 미스
            Pipe->>Retrieval: retrieve_candidates()
            Retrieval-->>Pipe: status=ready 후보
            Pipe->>Reranker: rerank_candidates()
            Reranker-->>Pipe: 상위 K개
            Pipe->>LLM: 근거 프롬프트로 스트리밍 생성
            LLM-->>FE: 토큰 단위 실시간 전달
            Pipe->>Cache: store()
            Pipe->>DB: ChatLog 기록
        end
    end
    Pipe->>Pipe: gpu_lock 해제
```

### 2-1. `gpu_lock` — 왜 필요한가

```mermaid
flowchart LR
    subgraph 공유자원["GPU / VRAM (RTX 5060 8GB 등 소형 카드)"]
    end
    A["질의 파이프라인<br/>(임베딩·리랭커·LLM)"] -->|"gpu_lock 획득"| 공유자원
    B["백그라운드 인덱싱 워커<br/>(임베딩 계산, LLM 라벨 생성)"] -->|"gpu_lock 획득"| 공유자원
    A -.->|"한쪽이 쥐고 있으면<br/>다른 쪽은 대기"| B
```

`app.state.gpu_lock`은 앱 시작 시 만들어지는 `asyncio.Lock()` 인스턴스 **하나**다. DB의
`FOR UPDATE SKIP LOCKED`는 "같은 문서를 두 워커가 중복으로 집어가는 것"만 막지, "채팅 응답
생성 중에 백그라운드 임베딩 배치가 동시에 GPU를 잡는 것"은 막지 못한다. 이게 겹치면 VRAM이
작은 카드에서 OOM이 났던 실제 사례가 있어서, GPU를 만지는 모든 경로를 이 잠금 하나로 완전히
직렬화한다.

### 2-2. 언어 감지 → 완전 일치 캐시 확인

`langdetect`로 질문 언어를 감지한 뒤, `SemanticQuestionCache.get_exact()`가 먼저 확인한다.

```mermaid
flowchart LR
    A[질문] --> B["normalize_question()<br/>casefold + 공백 정리"]
    B --> C{"정규화된 문자열이<br/>완전히 같은 캐시 항목?"}
    C -->|있음| D["_touch()<br/>last_used_at/expires_at 갱신<br/>(슬라이딩 TTL)"]
    D --> E["캐시된 답변 즉시 반환<br/>(임베딩·검색·LLM 전부 생략)"]
    C -->|없음| F[다음 단계로]
```

크기 제한(`question_cache_max_size`)을 넘으면 `last_used_at`이 가장 오래된 항목부터 제거된다
(LRU). 문서가 수정되면 그 문서를 근거로 쓴 캐시 항목만 골라 지운다.

### 2-3. 질문 임베딩 + 의도 분류

완전 일치가 없으면 `expand_search_query()`(고정된 동의어 사전 기반 — 예: "과정"이 들어간
질문엔 "공정 절차"를 덧붙임)로 검색어를 살짝 보강한 뒤, `embed_hybrid()`가 dense+sparse
벡터를 동시에 만든다. 이 벡터를 `IntentClassifier.classify()`가 재사용해서(중복 임베딩 방지)
11개 카테고리(overview/feature/specification/... )와의 코사인 유사도를 계산한다.

```mermaid
flowchart LR
    A[질문 dense 벡터] --> B["11개 카테고리 설명문과<br/>코사인 유사도 계산<br/>(설명문 벡터는 서버 시작 후 1회만 캐시)"]
    B --> C[카테고리별 점수 전체 반환]
    C --> D["검색 순위에는 미반영<br/>(오분류가 근거를 배제하면 피해가 크므로)"]
    C --> E[의미 캐시 안전조건에 사용]
    C --> F[화면 진단 정보에 사용]
```

### 2-4. 의미 유사 캐시 안전조건 — `QuerySignature`

"임베딩이 비슷하다"만으로 캐시를 재사용하면 위험하다 — "A모델 가반하중은?"과 "B모델
가반하중은?"은 임베딩이 매우 비슷하지만 정답은 다르다. 그래서 5가지 항목을 뽑아 **전부
정확히 일치할 때만**(임계값 아님, `==` 비교) 캐시를 재사용한다.

```mermaid
flowchart TD
    Q[새 질문] --> S1["식별자<br/>(모델명·인증번호 정규식)"]
    Q --> S2["라벨<br/>(등록된 라벨 완전일치 + 회사 별칭)"]
    Q --> S3["속성 키워드<br/>(가반하중·무게·전력 등 16종)"]
    Q --> S4["질문 유형<br/>(비교질문 vs 단순조회)"]
    Q --> S5["의도<br/>(2-3절 분류 1등 카테고리)"]
    S1 & S2 & S3 & S4 & S5 --> AND{"캐시된 질문과<br/>5개 전부 동일?"}
    AND -->|"Yes AND 임베딩 유사도 ≥ 임계값"| Hit[캐시 재사용]
    AND -->|하나라도 다름| Miss["캐시 미스<br/>→ 실제 검색으로 진행"]
```

이렇게 하면 "비슷한 질문처럼 보이지만 실제로는 다른 걸 묻는" 경우의 오답 캐싱을 막는다.

### 2-5. 문서 검색 — `retrieve_candidates()`

```mermaid
flowchart TD
    A[질문] --> B{"질문에서 라벨 감지됨?<br/>(2-4절의 labels)"}
    B -->|Yes| C["_find_labeled_document_ids()<br/>라벨 전부 가진 문서 우선,<br/>없으면 일부만 가진 문서 최대 100개"]
    B -->|No| D[라벨 범위 검색 생략]
    C --> E["Qdrant: 전역 검색 +<br/>라벨 범위 검색 각각 호출"]
    D --> E2["Qdrant: 전역 검색만"]
    E --> F["dense/sparse 각각 넉넉히 뽑아<br/>Qdrant 내장 RRF로 결합"]
    E2 --> F
    F --> G["merge_global_and_labeled_candidates()"]
    G --> H["status=ready인 문서의<br/>청크만 최종 필터링"]
```

**후보 병합 우선순위** (`merge_global_and_labeled_candidates`):

```mermaid
flowchart LR
    A["최대 후보 개수"] --> B["① 질문 핵심어가 많이 포함된<br/>후보 보호쿼터 (최대 1/4)"]
    B --> C["② 전역 검색 결과<br/>(전체의 약 2/3까지)"]
    C --> D["③ 라벨 범위 검색 결과<br/>(나머지, 약 1/3까지)"]
    D --> E["자리가 남으면<br/>전역→라벨 순으로 채움"]
```

①은 CPU 리랭커 모드에서 후보 개수를 줄일 때, 벡터 순위로는 밖이지만 정확한 숫자·사양이
담긴 청크가 통째로 사라지는 걸 막는 안전장치다.

> **RRF 점수 주의**: Qdrant의 RRF(Reciprocal Rank Fusion)는 점수 자체를 더하지 않고 **순위만**
> 결합한다. 반환 점수는 0~1 유사도가 아니라 `1/(k+순위)` 형태(k=60)라 1등이어도 보통 0.03대
> 값이 나온다. 여기에 "유사도 0.3 이상만" 같은 하한선을 걸면 사실상 전부 걸러진다 — CLAUDE.md에
> 기록된 실제 버그. 유사도 하한선은 반드시 다음 단계(리랭커)의 정규화된 점수에만 건다.

### 2-6. 리랭킹 — `rerank_candidates()`

1차 검색 후보를 질문과 다시 정밀 비교해서 순위를 다듬는 단계. 아래 흐름 전체를
`retrieval_pipeline.rerank_candidates()`가 순서대로 수행한다.

```mermaid
flowchart TD
    A[1차 검색 후보] --> B{리랭커 사용 설정?}
    B -->|No| Z[1차 점수 그대로 사용]
    B -->|Yes| C{GPU 사용 가능?}
    C -->|Yes| D["BgeRerankerV2<br/>Cross-encoder로 질문-후보 쌍 채점"]
    D --> E{CUDA OOM 발생?}
    E -->|Yes| F["경량 리랭커(lightweight_rerank)로 폴백<br/>이후 요청도 계속 CPU 모드로 전환"]
    E -->|No| G[점수 갱신]
    C -->|No| F
    F --> G
    G --> H["라벨 가산점<br/>(질문의 라벨 문서면 +weight)"]
    H --> I["식별자 완전일치 가산점<br/>(모델명이 본문에 그대로 있으면 가산)"]
    I --> J{"관련도 하한선<br/>(adaptive_retrieval_floor_similarity)<br/>이상인 후보가 있음?"}
    J -->|충분히 있음| K[다양화 선택 select_diverse_results]
    J -->|"라벨 문서만 전멸"| L["RRF 재결합 후<br/>라벨 문서 안에서만 최대 3개 구조"]
    J -->|"무라벨 질문 전멸"| M["문서명에 대상어 + 본문에 다른 속성어<br/>모두 있는 후보만 구조"]
    M --> N{그래도 없음?}
    N -->|Yes| O["DB ILIKE로 폭넓게 재검색 후<br/>1차검색이 신뢰한 문서 안에서만 최종 구조"]
    N -->|No| K
    L --> K
    O --> K
```

**CPU 경량 리랭커 공식** (`lightweight_rerank`, GPU 없거나 OOM 이후):

```
최종점수 = 0.10·1차검색 정규화점수
         + 0.45·질문 전체 핵심어 등장률
         + 0.30·질문 뒤쪽 3단어("묻는 속성") 등장률
         + 0.15·라벨 문서 여부(0 또는 1)
```

**다양화** (`select_diverse_results`): 한 문서의 비슷한 청크가 결과를 도배하지 않도록 문서당
상한을 둔다. 라벨 문서가 있으면 그 근거를 최소 3개까지 먼저 확보하고, 남는 자리는 점수 순으로
다시 채운다 (관련 문서가 하나뿐인 질문에서 다양화 때문에 컨텍스트가 줄어드는 손해를 막기 위해).

### 2-7. LLM 답변 생성

`answer_prompt.py`가 프롬프트를 만든다. 핵심 방침: **질문에 등장한 주장·용어도 사실로
가정하지 않고 참고 자료와 대조**하도록 강제한다.

```mermaid
flowchart TD
    A["질문 핵심어 추출<br/>(3자+숫자/영문 또는 5자 이상)"] --> B{"참고 자료에<br/>문자 그대로 있음?"}
    B -->|No, 확인 안 됨| C["경고 블록 생성:<br/>'이 표현은 참고에서 확인 안 됨,<br/>사실처럼 긍정하지 말 것'"]
    B -->|Yes| D[경고 없음]
    C --> E[프롬프트 조립]
    D --> E
    E --> F["질문에 순서/단계 표현 있으면<br/>번호로 빠짐없이 답하라는 지시 추가"]
    F --> G["질문에 차이/합계 표현 있으면<br/>산식 포함하라는 지시 추가"]
    G --> H["최종 프롬프트 =<br/>[답변 규칙] + [대조 결과] + [참고 자료]<br/>+ [질문] + [형식 지시]"]
    H --> I["LLM 스트리밍 생성<br/>(토큰마다 즉시 yield)"]
```

참고 자료 블록은 리랭킹 결과 각각을 `[참고 N | 파일: ... | 페이지: ...]`로 번호 매겨 이어붙인
것이며, LLM은 답변 문장 끝에 그 번호를 인용하도록 지시받는다. 실측 결과 전체 응답 시간의
90% 이상이 이 단계라, 스트리밍으로 체감 대기시간을 줄인다 (총 시간 자체는 줄지 않음).

### 2-8. 캐시 저장 + 로그

답변이 완성되면 `SemanticQuestionCache.store()`가 질문/답변/`QuerySignature`/근거 문서·청크
ID를 함께 저장하고, `ChatLog` 테이블에도 질문/답변을 기록한다 (일일 보고서의 참고자료 검색
등에서 재사용됨, `daily_report_api.md` 참고).

---

## 3. 핵심 구성요소

| 역할 | 구현체 | 비고 |
|---|---|---|
| 임베딩 | `BgeM3EmbeddingProvider` (BAAI/bge-m3) | dense+sparse 동시 지원, `embed_hybrid()` 하나로 처리 |
| 벡터DB | `QdrantVectorStore` | dense+sparse를 내장 RRF로 결합, `document_id` 메타데이터로 문서 단위 삭제 가능 |
| 리랭커 | `BgeRerankerV2` (BAAI/bge-reranker-v2-m3, Cross-encoder) | GPU 없거나 OOM 나면 `lightweight_rerank`로 자동 전환 |
| LLM | `QwenOllamaProvider` (Ollama, qwen3:8b/4b) | 스트리밍 생성 지원 |
| 질문 캐시 | `SemanticQuestionCache` | 완전 일치(슬라이딩 TTL) / 의미 유사(임베딩 유사도 + `QuerySignature` 완전 일치) 2단 |
| 의도 분류 | `IntentClassifier` | 11개 카테고리, 서버 시작 후 1회 임베딩 캐시, 검색 순위엔 미반영 |

## 4. 관련 문서

- 업로드/상태 폴링: `upload_api.md`
- 채팅 스트리밍: `chat_stream_api.md`
- 워커 수동 실행: `admin_run_workers_api.md`
- 라벨 수정 시 재인덱싱: `document_management_api.md`
- 라벨 개념 자체: `CLAUDE.md`의 "문서 라벨 시스템" 절
