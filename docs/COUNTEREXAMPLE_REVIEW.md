# 검색 일반화 반례 리뷰 (claude 작성, agent-relay 스레드 rag-retrieval-accuracy-review)

structural-review-and-counterexamples 태스크 산출물. 코드/DB는 건드리지 않고 오프라인으로만 작성했다.
질문셋은 [EVAL_ADVERSARIAL_QUESTIONS.json](./EVAL_ADVERSARIAL_QUESTIONS.json).

## 실행 절차

서버/DB를 지금 이 세션에서 새로 띄우지 말라는 Codex 지시에 따라, 실행은 Codex(또는 이후 세션)가 아래 순서로 진행한다.

1. 기존에 문서화된 방식대로 인프라+앱 기동
   ```powershell
   docker compose up -d qdrant postgres ollama
   & "C:\v\rag_latest\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. `EVAL_ADVERSARIAL_QUESTIONS.json`의 `questions` 배열만 추출해 (category/note/confidence 필드는 API가 무시하므로 그대로 둬도 무방) `/api/evaluation/run`에 POST. PowerShell 따옴표 이스케이프 문제가 반복해서 있었으므로, curl에 인라인 JSON 대신 **파일로 저장 후 `--data @file` 방식**을 쓸 것.
   ```powershell
   curl.exe -s -X POST http://127.0.0.1:8000/api/evaluation/run `
     -H "Content-Type: application/json; charset=utf-8" `
     --data-binary "@docs\EVAL_ADVERSARIAL_QUESTIONS.json" -o eval_result.json
   ```
   (JSON에 `_note`/`categories` 최상위 키가 섞여 있어 `EvalRequest`가 `questions` 필드만 읽고 나머지는 무시하는지 Pydantic 동작을 먼저 확인. 만약 최상위 extra 키 때문에 400이 나면 `questions` 배열만 뽑은 축소본을 별도로 만들어 사용.)
3. 응답의 `results[]`를 아래 "실패 분류 기준"에 따라 분류해서 표로 남긴다.
4. Codex가 ①(런타임 OOM 폴백), ②(중복 렉시컬 계산 통합)를 적용하기 **전/후로 각각 한 번씩** 돌려서 비교한다. 회귀(전엔 통과, 후엔 실패)가 있으면 그게 진짜 문제다.

## 실패 분류 기준 (v2 — Codex 교차검증으로 수정됨)

**v1의 오류**: 아래 표의 이전 버전은 `expected_hit=false`를 "1차 검색 실패"로, `expected_rank > top_k`를 "순위 실패"로 정의했다.
실제로는 [main.py:1259-1264](../app/main.py:1259)의 `retrieval_info.result_document_ids`가 floor_similarity 필터와
`select_diverse_results`(top_k=5로 절단)를 **모두 거친 최종 후보**에서 나온다. 따라서:
- `expected_hit=false`는 1차 검색 실패·리랭킹 탈락·유사도 하한 제거·문서당 3청크 제한 중 어느 것이 원인인지 현재 API로는 구분 불가능하다.
- `expected_rank`는 정의상 5(reranker_top_k)를 넘을 수 없으므로 v1의 "순위 실패" 판정 조건은 애초에 발생할 수 없다.

이 오류는 Codex의 교차검증(relay 메시지 6번, 2026-08-08T23:04)으로 발견됐다. 정확한 판정을 하려면 전역검색/병합/리랭킹/floor/다양화 각 단계의 후보 문서ID·순위를 별도로 계측해야 하며, 이는 Codex 작업(단계별 trace 확장)에 달려 있다. 그 계측이 추가되기 전까지는 아래 표를 "확정 분류"가 아니라 "잠정 근사치"로만 쓴다.

| 분류(잠정) | 판정 조건 | 실제 의미(계측 확장 전까지는 근사치) |
|---|---|---|
| 최종 근거 탈락(Final-context miss) | `expected_hit == false` | 정답 문서가 최종 5개 근거에 없음. 원인은 1차검색/리랭킹/floor/다양화 중 하나이며 **현재 API로는 구분 불가** — 원인 특정은 단계별 trace 계측 후로 보류 |
| ~~순위 실패~~ | (삭제됨) | v1에서 `expected_rank > top_k`로 정의했으나 최종 리스트가 이미 top_k로 잘려 있어 발생 불가능한 조건이었음 |
| 사실 누락(Evidence-answer gap) | `expected_hit == true`, `expected_terms_hit == false` | 올바른 청크가 최종 근거에 있는데 LLM이 사실을 답변에 안 담음 — 프롬프트/컨텍스트 조립 문제 (이 판정은 계측 확장과 무관하게 현재도 유효) |
| 환각(Hallucination) | `D_no_answer` 카테고리 질문인데 `answer_preview`에 구체적 수치·고유값이 등장 | 없는 사실을 지어냄 — 가장 심각 (계측과 무관하게 유효) |
| 교차오염(Cross-contamination) | `C_cross_product_confusion` 카테고리에서 `answer_preview`에 질문 대상이 아닌 다른 모델의 값이 섞이거나 대체됨 | 식별자/라벨 가산점이 유사 모델을 혼동 (계측과 무관하게 유효) |
| 라벨 의존 실패(Label-dependent miss) | `F_no_explicit_label` 카테고리에서 `expected_hit == false`인데 같은 사실을 라벨 명시 버전으로 물으면 `expected_hit == true` | 전역 의미검색이 사실상 라벨 힌트에 의존한다는 정황증거(계측 전까지는 "정황"이지 "확정"은 아님) |

**Codex에게 요청**: 전역검색 직후, merge 직후, 리랭킹 직후, floor 필터 직후, diversify 직후 — 각 단계의 `[(document_id, chunk_id, score)]` 스냅샷을 `retrieval_info`(또는 별도 debug 필드)에 추가해주면, 위 "최종 근거 탈락"을 실제 원인별로 쪼갤 수 있다.

`confidence: "low"`로 표시한 질문은 내가(claude) 실제 DB 청크 원문을 열람하지 못한 채 이전 대화 요약만으로 적은 것이다. 이 질문들이 실패로 나오면 **파이프라인 문제로 단정하지 말고, 먼저 실제 청크 텍스트를 조회해서 내가 적은 `expected_terms`/`expected_filename` 자체가 틀렸는지부터 배제**할 것 (CLAUDE.md 원칙: 추측 대신 실측).

**2026-08-08 갱신**: 위 원칙에 따라 PostgreSQL을 읽기전용(SELECT만, docker exec psql)으로 열어 17문항 전체의 정답표를 실제 청크 원문과 대조했다. 코드/DB는 전혀 수정하지 않았다. 이 과정에서 v1 정답표의 확정 오류 3건을 발견해 `EVAL_ADVERSARIAL_QUESTIONS.json`을 직접 수정했다:
1. 용접 가접/본접 이후 검사 공정 — 내가 "누설검사"라고 적었으나 원문은 영문 그대로 "LEAK TEST"였음
2. 도장공정 "마스킹 다음 단계" 질문 — 실제로는 CAP MASKING이 삽입(2번)·제거(6번) 두 번 등장해서 질문 자체가 모호했음. "삽입" 명시로 수정
3. RB5-850 vs RB5-850E 교차혼동 문항 — 이 코퍼스에서 두 표기가 완전히 같은 값(5kg, 927.7mm)이라 애초에 혼동을 테스트할 수 없는 무효 문항이었음. RB3-1200E(1200mm) vs RB3-730ES(730mm)로 교체(가반하중은 둘 다 3kg로 같지만 도달범위는 다름 — 진짜 식별자 구분 테스트가 됨)

추가로 발견한 **일반 평가 인프라 한계**(문항 오류가 아니라 `/api/evaluation/run`의 term-matching 방식 자체의 한계): `expected_terms`는 LLM 최종 답변 문자열에 대해 단순 `casefold()` 후 substring `in` 검사만 한다. 원문이 "촉매 변환기"(띄어쓰기 있음)인데 내가 "촉매변환기"(붙여쓰기)로 정답어를 걸면, LLM이 띄어쓰기를 살려서 답하는 순간 실제로는 맞았는데도 `expected_terms_hit=false`로 오탐 처리된다. 한국어는 URL/모델명이 아닌 한 이런 스페이싱 변동이 흔하므로, 사실 확인용 `expected_terms`는 가능하면 스페이싱에 안전한 짧은 부분어(예: "촉매변환기" 대신 "촉매")를 쓰는 것이 좋다 — 이번에 해당 문항은 이렇게 완화해뒀다.

## 카테고리별 예상(가설) — 코드만 읽고 세운 예측, 검증 전

실제로 안 돌려봤으므로 이건 "예측"이지 "확인된 사실"이 아니다. Codex가 실행 후 이 예측이 맞았는지 틀렸는지 알려주면 다음 라운드 반례 설계에 반영하겠다.

- **A(어순 파괴)**: 실패 가능성 중간. `lightweight_reranker`의 45% 전체 키워드 커버리지가 30% 속성 가중치의 오작동을 어느 정도 상쇄할 수 있어서, CUDA 리랭커가 정상 동작 중이면(현재 확인된 상태) 영향이 A보다 작을 것으로 예상. CPU 폴백 상황에서는 더 취약할 것.
- **B(동의어)**: `_QUERY_EXPANSIONS`에 없는 표현은 실패 가능성 높음. 이건 사전을 계속 늘리는 방식으로는 못 끝내는 구조적 한계라, 실패가 나와도 "사전에 항목 추가"로 땜질하지 말고 애초에 이 방식이 맞는 접근인지 재논의 필요.
- **C(교차혼동)**: `exact_identifier_boost_weight`가 정규식 기반이라 `RB5-850` vs `RB5-850E`처럼 접미사 하나 차이는 정규식이 두 식별자를 별개로 추출하는지가 관건. `identifier_matching.py`의 패턴(`[A-Z0-9-]+(?:-[A-Z0-9]+)+`)상 `RB5-850`과 `RB5-850E`는 서로 다른 문자열로 추출되긴 하지만, 벡터 검색 자체가 두 모델 청크를 둘 다 상위권에 올릴 경우 리랭커의 의미점수가 구분을 못 할 수 있음.
- **D(자료없음)**: 가장 중요한 카테고리. `adaptive_retrieval_floor_similarity=0.20`이 상당히 낮게 설정되어 있어("낮은 OCR 표현도 살리기 위해") 무관한 질문에도 억지로 후보가 남을 가능성이 있음. 여기서 환각이 나오면 floor 값보다 "컨텍스트가 질문과 관련 없어 보이면 모른다고 답하라"는 프롬프트 지시 자체를 점검해야 함.
- **E(복합속성)**: A와 유사한 이유로 실패 가능성 있음. 특히 속성 2개 중 하나만 답하고 하나는 빠뜨리는 "부분 성공"이 가장 흔한 실패 형태일 것으로 예상.
- **F(라벨 미명시)**: 라벨 의존도를 직접 재는 카테고리라 가장 중요하게 봐야 함. 같은 사실을 라벨 명시/미명시 두 버전으로 나눠뒀으므로(머플러, 서빙로봇), 둘의 결과 차이 자체가 "지금 시스템이 의미검색으로 진짜 찾는지, 라벨 힌트가 없으면 사실상 못 찾는지"를 보여주는 직접 증거가 된다.

## 다음 라운드 제안

이번 라운드 결과(특히 D, F 카테고리)를 보고 나서, 실패 패턴이 확인되면 각 실패마다 규칙을 하나씩 추가하는 대신:
1. 실패를 유형별로 묶고
2. 유형당 근본 원인 하나를 지목하고
3. 그 원인 하나를 고친 뒤 전체 셋(6개 회귀 + 이번 16개)을 다시 돌려서 순증가/역효과를 함께 확인

하는 방식을 제안한다. 지금까지 반복된 "질문 하나 실패 → 규칙 하나 추가"의 재발을 막기 위함이다.
