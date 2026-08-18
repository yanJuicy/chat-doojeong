"""
멀티턴 대응 채팅 스트리밍 라우터 (GET /api/v1/chat-stream). app/backend/router.py를 대체한다.

핵심 원칙: 기존 _run_chat_pipeline(app/main.py)은 절대 안 건드린다. 이 파일이 하는 일은
"질문을 파이프라인에 넣기 직전에, 필요하면 대화 맥락을 반영해서 재작성하는 것"뿐이다.
파이프라인 안의 캐시/검색/리랭킹/답변생성 코드는 이 파일이 그 존재조차 몰라도 된다 —
ChatRequest(question=...)만 만들어서 넘기면 끝.

session_id가 없으면(멀티턴 미사용) 오늘까지의 싱글턴 동작과 완전히 동일하다.

클래스 없이 함수로만 구성한다 (app/backend/documents.py와 같은 스타일).
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeAlias

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ..api_models import ChatRequest, ChatResponse
from ..core.identifier_matching import extract_identifiers
from ..core.label_matching import find_question_label_hints
from ..db.models import ChatSession, ChatTurn, DocumentLabel
from ..db.session import async_session_factory
from .schemas import BackendChatData, BackendErrorDetail

logger = logging.getLogger(__name__)

PipelineEvent: TypeAlias = tuple[str, Any]
ChatPipeline: TypeAlias = Callable[[Request, ChatRequest], AsyncIterator[PipelineEvent]]

# 재작성 LLM 호출 상한 시간. QwenOllamaProvider.generate()는 httpx 타임아웃이 300초로
# 고정돼 있는데(답변 생성용 값), 재작성처럼 짧아야 하는 호출은 여기서 별도로 짧게 끊는다.
_REWRITE_TIMEOUT_SECONDS = 15

# 재작성 프롬프트에 넣을 이전 대화의 최대 토큰 수. 이 프로젝트 답변은 근거 인용이 붙은
# 긴 문단이 많아서, "턴 개수"가 아니라 토큰 예산으로 잘라야 프롬프트가 안 부풀어 오른다.
_HISTORY_TOKEN_BUDGET = 2000

# 토큰 예산으로 자르기 전에 DB에서 일단 넉넉히 가져올 개수(최신순).
_HISTORY_FETCH_LIMIT = 20

_REWRITE_SYSTEM_PROMPT = (
    "당신은 대화 이력을 보고 사용자의 마지막 질문을 독립적으로 이해 가능한 질문으로 "
    "바꿔주는 도우미입니다. 이전 대화에 실제로 등장한 제품명/모델명만 사용하세요. "
    "이전 대화에 없던 제품명을 새로 만들어내지 마세요. 가리키는 대상이 여러 개(비교 중인 "
    "제품 여러 개 등)라 하나로 특정할 수 없으면, 임의로 하나를 고르지 말고 전부 포함해서 "
    "질문을 완성하세요. 재작성된 질문 한 줄만 출력하세요."
)


# ── router.py에서 그대로 옮긴 함수 (변경 없음) ──────────────────────────────
def _to_backend_data(response: ChatResponse) -> dict:
    return BackendChatData(
        answer=response.answer,
        sources=response.sources,
        images=response.images,
    ).model_dump()


def _format_event(kind: str, payload: Any) -> str | None:
    """kind별로 FE 계약에 맞는 SSE 줄을 만든다. "timing"처럼 FE가 안 쓰는 종류는 None을 돌려줘서
    아예 내보내지 않는다 (디버그가 필요하면 서버 로그를 보면 되고, 와이어에 실을 필요는 없다)."""
    if kind == "progress":
        body: dict = {"type": "progress", "message": payload}
    elif kind == "token":
        body = {"type": "token", "token": payload}
    elif kind == "error":
        error = BackendErrorDetail(message=payload["message"])
        body = {"type": "done", "success": False, "error": error.model_dump()}
    elif kind == "result":
        body = {"type": "done", "success": True, "data": _to_backend_data(payload)}
    else:  # kind == "timing"
        return None
    return f"data: {json.dumps(body)}\n\n"


# ── 신규: ChatSession/ChatTurn 저장·조회 ────────────────────────────────────
async def _get_or_create_chat_session(session_id: str) -> None:
    """
    FE가 만든 id를 그대로 세션 id로 신뢰한다(인증이 없는 시스템이라 별도 발급 주체를
    두는 것보다 클라이언트가 만든 값을 그대로 쓰는 쪽이 더 단순하다). 이 id로 저장된
    세션이 없으면 지금 이 요청이 그 대화의 첫 메시지라는 뜻이므로 새로 만든다 — 그래서
    별도의 "세션 생성 API"가 필요 없다.
    """
    async with async_session_factory() as session:
        existing = await session.get(ChatSession, session_id)
        if existing is None:
            session.add(ChatSession(id=session_id))
            await session.commit()


async def _load_recent_turns(session_id: str, token_budget: int, embedding_provider: Any) -> list[ChatTurn]:
    """
    이 세션의 최근 발화들을 시간순(과거 -> 최신)으로 반환한다. 최신 것부터 채워서
    토큰 예산을 넘기지 않는 선까지만 남긴다 — 오래된 turn이 예산 밖으로 밀려나면
    재작성이 억지로 추측하지 않고 원본 질문을 그대로 쓰게 되는데(_rewrite_question의
    그라운딩 검증과 짝을 이룸), 이건 의도된 안전한 동작이다.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(ChatTurn)
            .where(ChatTurn.session_id == session_id)
            .order_by(ChatTurn.created_at.desc())
            .limit(_HISTORY_FETCH_LIMIT)
        )
        recent_desc = list(result.scalars().all())  # 최신 -> 과거 순

    trimmed: list[ChatTurn] = []
    used_tokens = 0
    for turn in recent_desc:
        # count_tokens는 app/core/embeddings.py에 이미 있는 동기 함수 — GPU를 안 쓰고
        # 가벼워서 예산 계산용으로 그냥 불러도 된다(구조화 청커도 같은 함수를 재사용 중).
        cost = embedding_provider.count_tokens(turn.content)
        if used_tokens + cost > token_budget:
            break
        trimmed.append(turn)
        used_tokens += cost

    trimmed.reverse()  # 프롬프트에는 과거 -> 최신 순서로 넣어야 자연스러움
    return trimmed


async def _save_turn(session_id: str, user_question: str, rewritten_question: str | None, answer: str) -> None:
    """이번 왕복(사용자 질문 1개 + 챗봇 답변 1개)을 두 행으로 저장한다."""
    async with async_session_factory() as session:
        session.add(
            ChatTurn(
                session_id=session_id,
                role="user",
                content=user_question,
                rewritten_question=rewritten_question,
            )
        )
        session.add(ChatTurn(session_id=session_id, role="assistant", content=answer))
        await session.commit()


async def _get_available_document_labels() -> list[str]:
    """
    등록된 라벨 전체 조회. app/main.py의 동일 이름 헬퍼와 로직은 같지만, backend가
    main을 import하면 순환참조가 생기므로(main이 backend를 import함) 여기서 3줄짜리
    쿼리를 그대로 복제한다 — 공유가 필요해지면 그때 app/core 쪽으로 옮기면 된다.
    """
    async with async_session_factory() as session:
        result = await session.execute(select(DocumentLabel.label).distinct())
        return [label for (label,) in result.all() if label]


# ── 신규: 재작성이 필요한 질문인지 저렴하게 먼저 판단 ────────────────────────
def _question_is_self_contained(question: str, available_labels: list[str]) -> bool:
    """
    질문에 모델명/라벨이 이미 들어있으면("RB-Y1의 무게는?") 대화 맥락 없이도 이해
    가능한 질문으로 보고 재작성(LLM 호출)을 생략한다.

    주의: 이건 "완벽한 의미 판단"이 아니라 "비용을 아끼기 위한 저렴한 근사치"다.
    판단이 틀려서 이미 완결된 질문을 재작성 LLM에 한 번 더 돌리는 정도는 괜찮지만
    (잘 만든 재작성 프롬프트라면 결과가 원본과 비슷하게 나올 것이므로), 반대로
    "완결됐다"고 잘못 판단해서 진짜 필요한 재작성을 건너뛰는 게 더 큰 문제다 —
    실사용 데이터를 보고 필요하면 판단 기준을 더 보강해야 한다.
    """
    if extract_identifiers(question):  # app/core/identifier_matching.py 재사용
        return True
    if find_question_label_hints(question, available_labels):  # app/core/label_matching.py 재사용
        return True
    return False


# ── 신규: 재작성 + 안전장치 ─────────────────────────────────────────────────
def _build_rewrite_prompt(question: str, history: list[ChatTurn]) -> str:
    """이전 turn들과 현재 질문을 이어붙여 재작성 LLM에 줄 프롬프트를 만든다."""
    history_lines = [f"{turn.role}: {turn.content}" for turn in history]
    history_text = "\n".join(history_lines)
    return (
        f"[이전 대화]\n{history_text}\n\n"
        f"[마지막 질문]\n{question}\n\n"
        "[작업] 마지막 질문을 이전 대화 없이도 이해 가능한 독립적인 질문 하나로 다시 쓰세요."
    )


def _rewritten_question_is_grounded(rewritten: str, history: list[ChatTurn]) -> bool:
    """
    재작성 결과가 실제 대화에 없던 모델명/식별자를 "지어냈는지" 확인한다. 재작성
    문장에서 뽑은 식별자 집합이 이전 대화 원문에서 뽑은 식별자 집합의 부분집합이어야만
    통과 — 새 식별자가 하나라도 있으면 재작성 LLM이 만들어낸 것으로 보고 거부한다.

    한계: 이 검사는 "완전히 없는 걸 지어낸 경우"만 잡는다. 이전 대화에 RB-Y1과
    RB-Y2가 둘 다 언급된 상태에서 재작성이 그중 틀린 쪽을 골랐다면, 그 식별자도
    "이전 대화에 있던 것"이라 이 검사를 통과해버린다 — 이 경우까지 막으려면 별도
    로직이 필요하고, 지금은 재작성 프롬프트 지시문(_REWRITE_SYSTEM_PROMPT)으로
    "애매하면 하나로 특정하지 말고 전부 포함하라"고 유도하는 정도로만 완화한다.
    """
    rewritten_ids = extract_identifiers(rewritten)
    if not rewritten_ids:
        return True  # 식별자를 새로 안 썼으면(일반 명사만 바뀐 경우 등) 검증할 대상이 없음
    history_text = " ".join(turn.content for turn in history)
    history_ids = extract_identifiers(history_text)
    return rewritten_ids <= history_ids  # 부분집합 연산자


async def _rewrite_question(
    question: str,
    history: list[ChatTurn],
    available_labels: list[str],
    llm_provider: Any,
) -> tuple[str, bool]:
    """
    최종적으로 파이프라인에 넘길 질문을 결정한다.
    반환값: (최종 질문, 실제로 재작성이 적용됐는지)

    실패/타임아웃/그라운딩 검증 탈락은 전부 원본 질문으로 안전하게 되돌아간다. 이
    프로젝트의 다른 워커들(예: chunking_worker의 라벨 자동생성)도 "부가 기능이
    실패해도 본 작업은 계속 진행"하는 패턴을 쓰는데, 여기도 같은 원칙을 따른다.
    """
    if not history:
        return question, False  # 첫 질문 -> 재작성할 대화 맥락 자체가 없음

    if _question_is_self_contained(question, available_labels):
        return question, False  # 이미 완결된 질문 -> LLM 호출 자체를 생략

    prompt = _build_rewrite_prompt(question, history)
    try:
        rewritten = await asyncio.wait_for(
            llm_provider.generate(prompt=prompt, system_prompt=_REWRITE_SYSTEM_PROMPT),
            timeout=_REWRITE_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — Ollama 다운/타임아웃 등, 요청 자체는 안 죽인다
        # asyncio.TimeoutError는 str(exc)가 항상 빈 문자열이라, 예외 타입까지 같이 찍어야
        # "다운된 건지 타임아웃인지"를 로그만 보고 구분할 수 있다.
        logger.warning(
            "질문 재작성 실패(%s: %s), 원본 질문으로 계속 진행", type(exc).__name__, exc or "(메시지 없음)"
        )
        return question, False

    rewritten = rewritten.strip()
    if not rewritten:
        return question, False

    if not _rewritten_question_is_grounded(rewritten, history):
        logger.warning("재작성 결과가 대화에 없던 식별자를 포함해 원본 질문 사용: %s", rewritten)
        return question, False

    return rewritten, True


# ── 라우터 ──────────────────────────────────────────────────────────────────
def create_chat_stream_router(run_chat_pipeline: ChatPipeline) -> APIRouter:
    """Build the router with the chat pipeline injected to avoid import cycles."""
    router = APIRouter(prefix="/api/v1", tags=["backend"])

    async def chat_stream(request: Request, question: str, session_id: str | None = None) -> StreamingResponse:
        """
        session_id가 없으면(=멀티턴 미사용) 오늘과 완전히 동일하게 싱글턴으로 동작한다.
        session_id가 있으면 파이프라인 호출 전에 질문 재작성을 먼저 시도한다.
        """

        async def event_generator() -> AsyncIterator[str]:
            final_question = question
            rewritten_question: str | None = None

            if session_id:
                # FE가 진행 상황을 계속 볼 수 있도록, 재작성 시작을 먼저 알린다
                # (기존 파이프라인의 progress 이벤트들과 같은 방식).
                yield _format_event("progress", "이전 대화 확인 중...") or ""

                await _get_or_create_chat_session(session_id)
                history = await _load_recent_turns(
                    session_id, _HISTORY_TOKEN_BUDGET, request.app.state.embedding_provider
                )
                available_labels = await _get_available_document_labels()
                final_question, was_rewritten = await _rewrite_question(
                    question, history, available_labels, request.app.state.llm_provider
                )
                if was_rewritten:
                    rewritten_question = final_question

            # 여기서부터는 기존 코드와 완전히 동일 — body만 재작성된 질문으로 만들어졌을 뿐,
            # run_chat_pipeline(=_run_chat_pipeline) 내부는 이 파일의 존재를 몰라도 된다.
            body = ChatRequest(question=final_question)
            answer_text = ""
            async for kind, payload in run_chat_pipeline(request, body):
                if kind == "result":
                    answer_text = payload.answer  # 저장용으로 최종 답변만 따로 붙잡아둠
                event = _format_event(kind, payload)
                if event is not None:
                    yield event

            if session_id:
                await _save_turn(session_id, question, rewritten_question, answer_text)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    router.add_api_route("/chat-stream", chat_stream, methods=["GET"], name="backend_chat_stream")
    return router
