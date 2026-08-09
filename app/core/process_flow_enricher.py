"""OCR이 격자 순서로 읽은 번호형 공정도를 검색 가능한 순서 문장으로 보강한다."""
from __future__ import annotations

import re

_PAINT_FLOW_STEPS: list[tuple[str, tuple[str, ...]]] = [
    ("피도물 투입", ("피도물투입",)),
    ("CAP MASKING 삽입", ("capmasking삽입", "capmasking삽입")),
    ("증기탈지", ("증기탈지",)),
    ("AIR BLOWER", ("airblower", "arblower", "에어블로어")),
    ("SPRAY 도장", ("spray도장", "스프레이도장")),
    ("CAP MASKING 제거", ("capmasking제거",)),
    ("건조", ("건조",)),
    ("검사", ("검사",)),
    ("적재", ("적재",)),
]


def _compact(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def enrich_numbered_process_flows(text: str) -> str:
    """모든 단계명이 확인되는 알려진 공정도에만 구조화 순서 설명을 추가한다."""
    compact = _compact(text)
    if "paintflow" not in compact and "도장" not in compact:
        return text
    if not all(any(alias in compact for alias in aliases) for _, aliases in _PAINT_FLOW_STEPS):
        return text

    numbered = "\n".join(f"{index}. {step}" for index, (step, _) in enumerate(_PAINT_FLOW_STEPS, start=1))
    supplement = f"[구조화 공정 순서: 도장 공정]\n{numbered}"
    if supplement in text:
        return text
    return f"{text.rstrip()}\n\n{supplement}"
