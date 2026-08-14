"""app/backend용 SSE 채팅 스트리밍 라우터 — 기존 _run_chat_pipeline을 그대로 재사용한다.

코드 안의 분기/흐름을 그림으로 보고 싶으면 router.md(같은 폴더)에 플로우차트가 있다.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, TypeAlias

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..api_models import ChatRequest, ChatResponse
from .schemas import BackendChatData, BackendErrorDetail

PipelineEvent: TypeAlias = tuple[str, Any]
ChatPipeline: TypeAlias = Callable[[Request, ChatRequest], AsyncIterator[PipelineEvent]]


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


def create_backend_router(run_chat_pipeline: ChatPipeline) -> APIRouter:
    """Build the router with the chat pipeline injected to avoid import cycles."""
    router = APIRouter(prefix="/api/v1", tags=["backend"])

    async def chat_stream(request: Request, question: str) -> StreamingResponse:
        async def event_generator() -> AsyncIterator[str]:
            body = ChatRequest(question=question)
            async for kind, payload in run_chat_pipeline(request, body):
                event = _format_event(kind, payload)
                if event is not None:
                    yield event

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    router.add_api_route("/chat-stream", chat_stream, methods=["GET"], name="backend_chat_stream")
    return router
