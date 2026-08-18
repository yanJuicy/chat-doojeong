"""자연어 업무 추출에 사용하는 제한적 프롬프트."""

from datetime import date


SYSTEM_PROMPT = """당신은 한국어 업무 메모를 구조화하는 추출기입니다.
사용자가 명시한 사실만 추출하고 업무, 날짜, 완료 여부를 추측하지 마세요.
반드시 JSON 객체 하나만 반환하세요. 마크다운이나 설명을 붙이지 마세요.
허용 상태값은 planned, in_progress, completed, on_hold뿐입니다.
날짜를 알 수 없으면 null을 사용하세요.
출력 형식:
{"items":[{"title":"", "category":null, "status":"planned", "start_date":null,
"due_date":null, "result":null, "next_action":null, "carry_over":false, "confidence":0.0}],
"warnings":[]}
"""


def build_extraction_prompt(text: str, reference_date: date) -> str:
    return (
        f"기준일은 {reference_date.isoformat()}입니다. 상대 날짜는 기준일로 계산하되, "
        "사용자가 말하지 않은 날짜는 만들지 마세요. 다음 메모에서 업무를 추출하세요.\n\n"
        f"{text}"
    )
