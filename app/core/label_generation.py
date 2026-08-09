"""자동 생성된 문서 라벨 응답을 안전하게 정리한다."""
from __future__ import annotations

import json
import re

_GENERIC_LABELS = {
    "image", "imagebox", "document", "file", "pdf", "text", "이미지", "문서", "파일", "자료",
}


def parse_generated_labels(raw: str) -> list[str]:
    """LLM의 JSON 배열 응답을 정리하고 의미 없는 일반 라벨을 제거한다."""
    candidate_text = raw.strip()
    match = re.search(r"\[[\s\S]*?\]", candidate_text)
    values: list[str] = []
    if match:
        try:
            decoded = json.loads(match.group(0))
            if isinstance(decoded, list):
                values = [str(value) for value in decoded]
        except json.JSONDecodeError:
            values = []
    if not values:
        values = re.split(r"[,\n|]", candidate_text)

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        label = re.sub(r"^\s*(?:[-•*]|\d+[.)])\s*", "", value).strip().strip('"').strip("'")
        normalized = label.casefold().replace(" ", "")
        if not label or len(label) > 40 or normalized in _GENERIC_LABELS or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(label)
        if len(cleaned) >= 5:
            break
    return cleaned
