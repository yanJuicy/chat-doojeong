"""
채팅으로 자유롭게 입력한 업무 내용을, work_report_entries에 저장할 개별 항목
(실적/계획 구분 + 격식체 문장)으로 정제한다.

문서(표) 경로(report_table_parser.py)는 구조가 이미 확정돼 있어서 LLM 없이 결정적으로
처리했지만, 채팅은 자유 텍스트라 다음 두 가지를 LLM이 판단해야 한다:
  1. 여러 사실이 한 문장에 뒤섞여 있으면 개별 항목으로 분리
  2. 각 항목이 이미 끝난 일(실적)인지 앞으로 할 일(계획)인지 판단

실패(호출 예외/응답 형식 이상)하면 원문 전체를 "실적" 항목 하나로 그대로 남긴다 —
이 기능이 실패했다고 사용자가 입력한 내용 자체가 유실되면 안 되기 때문이다.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_BASE_SYSTEM_PROMPT = (
    "당신은 사용자가 자유롭게 말한 업무 내용을 주간 업무보고 항목으로 정리하는 도우미입니다. "
    "입력에 서로 다른 여러 업무가 섞여 있으면 각각 별도 항목으로 나누세요. "
    "각 항목이 이미 끝난 일이면 [실적], 앞으로 할 일이면 [계획]으로 표시하세요. "
    "{style_instruction} "
    "원문에 없는 내용을 새로 지어내거나 추측하지 마세요. "
    "반드시 '번호. [실적|계획] 문장' 형식으로만, 한 줄에 항목 하나씩 출력하세요. "
    "다른 설명은 절대 덧붙이지 마세요."
)

# 이 부서가 작성한 문서가 하나도 없어서 참고할 예시 문장이 없을 때만 쓰는 기본값.
_DEFAULT_STYLE_INSTRUCTION = (
    "문장은 격식체 명사형 종결(예: '~완료', '~실시', '~진행', '~예정')로 간결하게 다듬으세요."
)

_ITEM_LINE = re.compile(r"^\s*\d+\.\s*\[(실적|계획)\]\s*(.+)$")


def _build_style_instruction(style_examples: list[str] | None) -> str:
    """부서가 기존에 쓰던 문장 예시가 있으면 그 문장 구조·어미·표현을 따르라고 지시한다.

    카테고리(동사형/명사형 등)로 미리 분류하지 않는다 — 예시 문장 자체를 LLM에게 보여주고
    스타일을 판단하게 맡기는 편이, 어미뿐 아니라 문장 구조·표현까지 함께 반영되고, 새로운
    스타일이 나타나도 규칙을 미리 정의해둘 필요가 없어서 더 견고하다."""
    if not style_examples:
        return _DEFAULT_STYLE_INSTRUCTION
    examples = "\n".join(f"- {example}" for example in style_examples)
    return (
        "문장을 다듬을 때, 아래는 이 부서가 기존에 작성한 보고서 문장 예시이니 이것과 "
        f"비슷한 문장 구조·어미·표현으로 맞추세요:\n{examples}"
    )


def _build_system_prompt(style_examples: list[str] | None) -> str:
    return _BASE_SYSTEM_PROMPT.format(style_instruction=_build_style_instruction(style_examples))


@dataclass
class RefinedItem:
    entry_type: str  # "실적" 또는 "계획"
    content: str


def _build_prompt(text: str) -> str:
    return f"[사용자 입력]\n{text}\n\n[작업] 위 내용을 개별 업무보고 항목으로 나누어 정리하세요."


def _parse_response(response: str) -> list[RefinedItem] | None:
    items: list[RefinedItem] = []
    for line in response.strip().splitlines():
        match = _ITEM_LINE.match(line)
        if match:
            items.append(RefinedItem(entry_type=match.group(1), content=match.group(2).strip()))
    return items or None


async def refine_chat_input(
    text: str, llm_provider: Any, style_examples: list[str] | None = None
) -> list[RefinedItem]:
    """
    자유 텍스트를 [실적/계획] 태그가 붙은 개별 항목으로 정제한다.

    style_examples: 이 부서가 기존에 업로드한 문서에서 뽑은 문장 몇 개(가공 없이 원문
    그대로). 주어지면 그 문장들과 비슷한 스타일로 다듬으라고 LLM에게 지시한다 — 부서마다
    문체가 다를 때, 사용자가 어떤 말투로 입력하든 그 부서의 기존 보고서 문체를 따라가게
    하기 위함. 없으면(이 부서 문서가 아직 없음) 기본 스타일로 정제한다.

    실패하면 원문 전체를 "실적" 항목 하나로 그대로 반환한다(안전한 폴백 — 사용자가
    입력한 내용이 이 단계 실패로 사라지지 않게 함).
    """
    text = text.strip()
    if not text:
        return []

    system_prompt = _build_system_prompt(style_examples)
    try:
        response = await llm_provider.generate(prompt=_build_prompt(text), system_prompt=system_prompt)
    except Exception as exc:  # noqa: BLE001 — 실패해도 원문은 살려서 진행
        logger.warning("채팅 입력 정제 실패(%s: %s), 원문을 실적 항목 하나로 저장", type(exc).__name__, exc or "(메시지 없음)")
        return [RefinedItem(entry_type="실적", content=text)]

    items = _parse_response(response)
    if items is None:
        logger.warning("채팅 입력 정제 응답 형식이 예상과 달라 원문을 실적 항목 하나로 저장: %r", response[:200])
        return [RefinedItem(entry_type="실적", content=text)]

    return items
