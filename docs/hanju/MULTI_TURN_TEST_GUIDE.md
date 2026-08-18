# 멀티턴 채팅 기능 — 팀원 GPU 장비 테스트 가이드

## 이 문서가 왜 필요한가

멀티턴 채팅(후속 질문이 이전 대화를 이해하게 만드는 기능)을 구현했는데, **개발한 Mac에
GPU가 없어서 실제 속도를 확인할 수 없었다.** 재작성 LLM 호출에 15초 타임아웃을 걸어놨는데,
Mac에서 직접 Ollama에 같은 프롬프트를 던져보니 2분이 지나도 응답이 안 왔다.
`ollama ps`로 확인해보니 모델이 `"size_vram": 0`으로 — **GPU가 아니라 CPU로 돌고 있어서**
생긴 문제였다. 그래서 **실제 GPU 장비(RTX 5060/5070)에서 이 기능이 정상 속도로 동작하는지
확인이 필요하다.**

확인하고 싶은 것 두 가지:
1. 후속 질문("그럼 무게는?")이 실제로 이전 대화("RB-Y1 가반하중은?")를 반영해서 재작성되는가 (로직 정합성)
2. 재작성 LLM 호출이 15초 타임아웃 안에 정상적으로 끝나는가 (실제 속도)

---

## 0. (작성자가 먼저 할 일) 코드를 커밋/푸시

**주의: 이 문서를 팀원에게 넘기기 전에, 아래 작업이 아직 안 끝났다면 먼저 해야 한다.**
지금 `hj-api_multi_turn_chat` 브랜치엔 멀티턴 기능 외에도 이전에 스태시로 쌓인 무관한
파일이 잔뜩 섞여 있는 상태다(프론트 앱 등, 이전 세션에서 이미 확인한 내용). **멀티턴
관련 파일만 골라서 커밋**해야 팀원이 필요한 것만 받는다.

```bash
git add \
  app/db/models.py \
  app/main.py \
  app/backend/router.py app/backend/router.md \
  app/backend/chat_stream.py app/backend/chat_stream.md \
  migrations/versions/0009_chat_sessions_and_turns.py \
  frontend/src/api.js frontend/src/hooks/useChat.js \
  docs/hanju/api/chat_stream_api.md \
  docs/hanju/api/multi_turn_chat_api.md \
  docs/hanju/api/multi_turn_chat_design.md \
  docs/hanju/MULTI_TURN_TEST_GUIDE.md

git status   # 위 파일들만 스테이징됐는지, 무관한 파일이 안 끼었는지 반드시 확인

git commit -m "feat: 멀티턴 채팅(질문 재작성) 기능 추가

- ChatSession/ChatTurn 테이블 추가, /api/v1/chat-stream에 session_id 선택 파라미터 추가
- 재작성은 _run_chat_pipeline 진입 전에 끝내고 기존 파이프라인은 무변경
- 재작성 실패/타임아웃/그라운딩 검증 탈락 시 원본 질문으로 안전하게 fallback"

git push -u origin hj-api_multi_turn_chat
```

(`app/backend/router.py`/`router.md`는 삭제된 파일이라 `git add`로 삭제가 스테이징된다.)

---

## 1. 팀원이 받은 뒤 할 준비

```bash
git fetch origin
git checkout hj-api_multi_turn_chat
git pull

# DB 스키마 반영 (chat_sessions, chat_turns 테이블 생성)
alembic upgrade head
```

### 1-1. `.env`에서 실제 GPU용 모델을 쓰는지 확인

```bash
grep LLM_MODEL_NAME .env
```
`qwen3:8b`(컴1) 또는 `qwen3:4b`(컴2)여야 한다. Mac 개발 환경의 `.env`에는 테스트용으로
`qwen3:1.7b`(CPU에서도 그나마 돌아가라고 넣어둔 작은 모델)로 돼있을 수 있으니, **팀원
장비의 `.env`는 원래 쓰던 실제 모델 그대로인지만 확인**하면 된다(따로 안 바꿔도 됨).

### 1-2. Ollama가 실제로 GPU에 모델을 올렸는지 확인

```bash
curl -s http://127.0.0.1:11434/api/ps | python3 -m json.tool
```
결과에서 `"size_vram"` 값이 **0보다 커야 한다.** 0이면 이 장비에서도 CPU로 돌고 있는 거라
같은 문제가 재현될 것이다 — 그 경우 Ollama/GPU 드라이버 쪽부터 봐야 한다(이 문서 범위 밖).

### 1-3. 서버 실행

CLAUDE.md 원칙대로 **`--reload` 없이** 실행한다 (OCR 캐시 파일 때문에 무한 재시작에 빠짐).

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`docker compose up -d qdrant postgres ollama`로 세 서비스가 이미 떠 있어야 한다.

---

## 2. 뭐가 바뀌었는지 (요약)

- `GET /api/v1/chat-stream`에 **`session_id` 선택 파라미터**가 추가됨. 안 보내면 오늘까지와
  완전히 동일(싱글턴).
- `session_id`를 보내면: 이전 대화를 조회해서 후속 질문("그럼 무게는?")을 standalone
  질문("RB-Y1의 무게는?")으로 재작성한 뒤, 그 재작성된 질문으로 **기존 검색/리랭킹/답변생성
  파이프라인을 그대로** 태운다 (파이프라인 내부 코드는 무변경).
- 대화 이력은 새 테이블 `chat_sessions`/`chat_turns`에 저장됨 (기존 `chat_logs`는 안 건드림).

상세 스펙: `docs/hanju/api/multi_turn_chat_api.md` / 설계 배경: `multi_turn_chat_design.md` /
서버 내부 코드 흐름: `app/backend/chat_stream.md`.

---

## 3. 테스트 시나리오

**공통 주의사항**: curl에 한글/공백이 들어가는데, `-G --data-urlencode`를 꼭 써야 한다.
그냥 URL에 공백을 넣으면(`question=A B`) `Invalid HTTP request received`로 서버가 거부한다.

아래 예시는 `RB-Y1`(레인보우로보틱스 RB 시리즈)을 쓰는데, **실제로 인덱싱된 문서에 있는
제품명/모델명으로 바꿔서 테스트해도 된다** (없는 모델명을 쓰면 애초에 검색 결과가 없어서
재작성이 잘 됐는지와 별개로 답변 자체가 "모른다"로 나올 수 있음).

### 시나리오 1 — 첫 질문 (세션 생성, 재작성 없음)

```bash
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=RB-Y1 최대 가반하중이 뭐야?" \
  --data-urlencode "session_id=team-test-1"
```
**기대 결과**: `"이전 대화 확인 중..."` progress는 뜨지만(session_id가 있으니), 서버 로그에
재작성 관련 경고/LLM 호출이 **없어야 한다** (`_load_recent_turns`가 빈 리스트를 반환 →
`_rewrite_question`이 `history`가 비어서 곧바로 원본 질문 반환). 답변은 평소 싱글턴과 동일한
속도로 나와야 한다.

### 시나리오 2 — 일반 후속 질문 (핵심 테스트)

```bash
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=그럼 무게는?" \
  --data-urlencode "session_id=team-test-1"
```
**기대 결과**:
- 서버 로그에 `app.main: 질문 수신 (language=ko): ...` 줄이 뜨는데, **그 뒤에 오는 텍스트가
  "그럼 무게는?"이 아니라 "RB-Y1의 무게는?"처럼 재작성된 문장이어야 한다** — 이게 재작성이
  실제로 적용됐다는 증거다.
- 재작성 LLM 호출이 **15초 안에 끝나야 한다** (`질문 재작성 실패` 경고가 로그에 없어야 함).
- 답변이 RB-Y1의 실제 무게로 나와야 한다(문서에 있는 값이라면).

### 시나리오 3 — 지시어("아까 말한 모델")

```bash
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=아까 말한 모델 속도는 얼마야?" \
  --data-urlencode "session_id=team-test-1"
```
**기대 결과**: 시나리오 2와 마찬가지로 RB-Y1로 정확히 치환되는지 확인.

### 시나리오 4 — 이미 완결된 질문 (재작성 스킵 확인)

```bash
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=RB-Y1의 도달거리는?" \
  --data-urlencode "session_id=team-test-1"
```
**기대 결과**: 질문 안에 `RB-Y1`이 이미 있어서 `_question_is_self_contained()`가 `True`를
반환 → **재작성 LLM 호출 자체가 로그에 안 남아야 한다.** (진행 속도가 시나리오 2보다 눈에
띄게 빨라야 정상.)

### 시나리오 5 — 여러 제품 비교 후 애매한 후속 질문

```bash
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=RB-Y1과 RBQ 중 뭐가 더 가벼워?" \
  --data-urlencode "session_id=team-test-2"

curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=그럼 가격은?" \
  --data-urlencode "session_id=team-test-2"
```
**기대 결과**: 재작성이 "RB-Y1과 RBQ의 가격은?"처럼 **둘 다 포함**하는지, 아니면 한쪽만
임의로 골랐는지 확인 — 이건 알려진 한계 케이스라 완벽을 기대하긴 어렵고, 실제로 어떻게
나오는지 결과만 기록해두면 된다.

### 시나리오 6 — 재작성 LLM이 없는 제품명을 지어내는 경우 (수동 확인 어려움)

이건 의도적으로 재현하기 어렵다(모델이 정상 동작하면 잘 안 지어냄). 대신 **로그에
`"재작성 결과가 대화에 없던 식별자를 포함해 원본 질문 사용"`이라는 경고가 뜨는 경우가
있는지** 다른 테스트 도중 우연히 발생하면 캡처해서 공유해달라.

### 시나리오 7 — Ollama 일시 중단 (fallback 확인)

```bash
# 별도 터미널에서 Ollama 컨테이너/프로세스를 잠깐 내렸다가
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=그럼 무게는?" \
  --data-urlencode "session_id=team-test-1"
# 다시 올린다
```
**기대 결과**: 재작성은 실패하지만(로그에 `ConnectError` 등 예외 타입이 찍힘) **요청 자체는
에러 없이 원본 질문으로 계속 처리돼서 답이 나와야 한다.**

### 시나리오 8 — 서로 다른 세션의 동일 문자열 (캐시 오염 확인, 가장 중요)

```bash
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=RB-Y1 가반하중은?" --data-urlencode "session_id=team-a"
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=RBQ 가반하중은?" --data-urlencode "session_id=team-b"

# 두 세션에서 완전히 같은 문자열로 후속 질문
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=그럼 무게는?" --data-urlencode "session_id=team-a"
curl -N -G "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=그럼 무게는?" --data-urlencode "session_id=team-b"
```
**기대 결과**: `team-a`는 RB-Y1 무게로, `team-b`는 RBQ 무게로 **서로 다르게** 답해야 한다.
둘이 같은 답을 하면(특히 캐시 히트로 즉시 답이 오면) 캐시가 섞인 것 — 이게 나오면 바로
공유해달라, 설계 자체를 다시 봐야 한다.

---

## 4. DB에서 직접 확인하기

```bash
docker exec -it <postgres 컨테이너 이름> psql -U user -d ragdb
# 또는 로컬에 psql이 있으면: psql "postgresql://user:password@localhost:5432/ragdb"
```

```sql
-- 세션 목록
SELECT id, created_at, updated_at FROM chat_sessions ORDER BY created_at DESC LIMIT 10;

-- 특정 세션의 대화 흐름 (원본 질문과 재작성 결과를 나란히 확인)
SELECT role, content, rewritten_question, created_at
FROM chat_turns
WHERE session_id = 'team-test-1'
ORDER BY created_at;
```

`rewritten_question`이 `NULL`이면 그 turn은 재작성이 안 일어난 것(첫 질문/완결된 질문/실패),
값이 있으면 실제로 검색에 쓰인 문장이다 — 시나리오 2, 3에서 이 값이 기대한 대로 채워졌는지
확인하면 된다.

---

## 5. 속도 측정 (이번 테스트의 핵심 목적)

지금 코드엔 재작성 단계만 따로 재는 타이머가 없어서, 로그의 타임스탬프로 직접 계산해야 한다.

```
"이전 대화 확인 중..." progress가 클라이언트에 도착한 시각
   → (재작성 LLM 호출 구간)
"app.main: 질문 수신 (language=ko): ..." 로그가 찍힌 시각
```

이 두 시점의 차이가 대략 "재작성에 걸린 시간"이다 (DB 조회 시간도 약간 포함되지만 무시할
수준). curl에 `-w '\n[%{time_total}s]\n'`을 붙이면 전체 요청 시간도 같이 볼 수 있다:

```bash
curl -N -G -w '\n[전체 소요: %{time_total}s]\n' "http://localhost:8000/api/v1/chat-stream" \
  --data-urlencode "question=그럼 무게는?" \
  --data-urlencode "session_id=team-test-1"
```

## 6. 결과를 이렇게 공유해줘

1. 시나리오 1~8을 실행한 서버 로그 전체 (터미널 출력 그대로 복사)
2. `curl http://127.0.0.1:11434/api/ps` 결과 (GPU에 올라갔는지, `size_vram` 값)
3. 시나리오 2/3의 재작성이 실제로 몇 초 걸렸는지 (5절 방법으로 측정)
4. 시나리오 8(캐시 오염 확인)이 통과했는지 여부 — 제일 중요

이 네 가지만 있으면 `_REWRITE_TIMEOUT_SECONDS`(현재 15초) 값이 실제 운영 환경에 적절한지
판단할 수 있다.

---

## 7. 문제가 생기면

- **재작성이 매번 15초를 다 채우고 실패한다** → GPU 장비에서도 느리다는 뜻. 모델 크기
  (`qwen3:8b` vs `4b`)나 `num_predict`(현재 768, 재작성엔 과함) 설정을 다시 봐야 한다.
- **캐시가 섞인다(시나리오 8 실패)** → 설계 원칙(재작성이 캐시 확인보다 먼저 끝나야 함)이
  코드에서 깨진 것 — `app/backend/chat_stream.py`의 `chat_stream()`에서 `ChatRequest` 생성
  전에 재작성이 정말 끝나 있는지 확인 필요.
- 그 외 애매한 결과는 전부 캡처해서 공유 — 추측하지 말고 실측 결과로 판단한다.
