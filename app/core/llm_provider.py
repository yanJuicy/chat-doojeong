"""
LLM Provider 추상 인터페이스.
Ollama(Qwen2.5) 구현체는 이 인터페이스를 상속한다. 추후 vLLM 등으로 교체 가능하도록 분리.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class BaseLLMProvider(ABC):
    """LLM 답변 생성 엔진의 공통 인터페이스"""

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """프롬프트에 대한 답변을 한 번에 반환한다."""
        raise NotImplementedError

    @abstractmethod
    async def generate_stream(self, prompt: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        """답변을 스트리밍으로 반환한다 (SSE 등에 활용)."""
        raise NotImplementedError
