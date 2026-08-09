"""
Qwen2.5(Ollama 서빙) LLM Provider 구현체.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from ..config import settings
from .llm_provider import BaseLLMProvider

logger = logging.getLogger(__name__)


class QwenOllamaProvider(BaseLLMProvider):
    """Ollama에 로컬 서빙된 Qwen2.5를 호출하는 LLM Provider"""

    def __init__(self) -> None:
        self._base_url = settings.llm_provider_base_url
        self._model = settings.llm_model_name

    def _payload(self, prompt: str, system_prompt: str | None, stream: bool) -> dict:
        return {
            "model": self._model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": stream,
            "think": settings.llm_think,
            "keep_alive": settings.llm_keep_alive,
            "options": {
                "temperature": settings.llm_temperature,
                "top_p": settings.llm_top_p,
                "num_ctx": settings.llm_num_ctx,
                "num_predict": settings.llm_num_predict,
            },
        }

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """답변을 한 번에 반환한다."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=300.0) as client:
            response = await client.post("/api/generate", json=self._payload(prompt, system_prompt, False))
            response.raise_for_status()
            data = response.json()
            return str(data.get("response", "")).strip()

    async def generate_stream(self, prompt: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        """답변을 토큰 단위(NDJSON 라인 단위)로 스트리밍한다."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=300.0) as client:
            async with client.stream(
                "POST",
                "/api/generate",
                json=self._payload(prompt, system_prompt, True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break

    async def ping(self) -> None:
        """Ollama 서버가 응답하는지만 확인한다 (/health용). 모델을 로드하지 않는 가벼운 호출."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()

    async def unload(self) -> None:
        """메타데이터 생성 뒤 Ollama 모델을 내려 다음 GPU 단계에 VRAM을 양보한다."""
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
                response = await client.post(
                    "/api/generate",
                    json={"model": self._model, "prompt": "", "stream": False, "keep_alive": 0},
                )
                response.raise_for_status()
            logger.info("Ollama LLM 언로드 완료: %s", self._model)
        except Exception as exc:  # noqa: BLE001
            # 언로드 최적화 실패가 문서 파이프라인 자체를 중단시키면 안 된다.
            logger.warning("Ollama LLM 언로드 실패(임베딩은 계속 진행): %s", exc)


def build_cross_lingual_system_prompt(question_language: str, answer_language: str = "ko") -> str:
    """
    교차언어 대응용 system_prompt를 만든다.
    질문/검색된 문서 언어가 다르더라도, 지정된 answer_language로 답변하도록 명시적으로 지시한다.
    """
    return (
        f"사용자의 질문 언어는 '{question_language}'이지만, 반드시 '{answer_language}' 언어로 답변하세요. "
        "제공된 컨텍스트가 다른 언어(예: 영어, 중국어 등)로 되어 있어도 정확히 이해하고 "
        f"'{answer_language}'로 자연스럽게 번역/요약해서 답변하세요."
    )
