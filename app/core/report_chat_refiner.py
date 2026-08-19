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

_SYSTEM_PROMPT = (
    "당신은 사용자가 자유롭게 말한 업무 내용을 주간 업무보고 항목으로 정리하는 도우미입니다. "
    "입력에 서로 다른 여러 업무가 섞여 있으면 각각 별도 항목으로 나누세요. "
    "각 항목이 이미 끝난 일이면 [실적], 앞으로 할 일이면 [계획]으로 표시하세요. "
    "문장은 격식체 명사형 종결(예: '~완료', '~실시', '~진행', '~예정')로 간결하게 다듬으세요. "
    "원문에 없는 내용을 새로 지어내거나 추측하지 마세요. "
    "반드시 '번호. [실적|계획] 문장' 형식으로만, 한 줄에 항목 하나씩 출력하세요. "
    "다른 설명은 절대 덧붙이지 마세요."
)

_ITEM_LINE = re.compile(r"^\s*\d+\.\s*\[(실적|계획)\]\s*(.+)$")


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


async def refine_chat_input(text: str, llm_provider: Any) -> list[RefinedItem]:
    """
    자유 텍스트를 [실적/계획] 태그가 붙은 개별 항목으로 정제한다.

    실패하면 원문 전체를 "실적" 항목 하나로 그대로 반환한다(안전한 폴백 — 사용자가
    입력한 내용이 이 단계 실패로 사라지지 않게 함).
    """
    text = text.strip()
    if not text:
        return []

    try:
        response = await llm_provider.generate(prompt=_build_prompt(text), system_prompt=_SYSTEM_PROMPT)
    except Exception as exc:  # noqa: BLE001 — 실패해도 원문은 살려서 진행
        logger.warning("채팅 입력 정제 실패(%s: %s), 원문을 실적 항목 하나로 저장", type(exc).__name__, exc or "(메시지 없음)")
        return [RefinedItem(entry_type="실적", content=text)]

    items = _parse_response(response)
    if items is None:
        logger.warning("채팅 입력 정제 응답 형식이 예상과 달라 원문을 실적 항목 하나로 저장: %r", response[:200])
        return [RefinedItem(entry_type="실적", content=text)]

    return items
