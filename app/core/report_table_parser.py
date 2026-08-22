"""
"주간 업무실적 및 계획" 표를 find_tables()로 뽑은 행/열 그리드에서 곧바로
WorkReportEntry 레코드로 구조화한다.

핵심 설계: 이 파싱은 LLM을 쓰지 않는다. 구분(열0)/기간·실적-계획 구분(헤더 행)은
find_tables()가 이미 좌표 기반으로 정확히 나눠준 그리드에서 그대로 읽으면 되므로,
"이 문장이 어느 칸 것인지" 추측할 필요가 없다. 원본 표의 문장 자체도 이미 담당자가
격식체로 써둔 것이라(채팅으로 막 입력한 게 아니라), 문체를 다시 다듬을 필요도 없다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_DEPARTMENT_PATTERN = re.compile(r"■\s*부서명\s*[:：]\s*(.+)")
_PERIOD_PATTERN = re.compile(
    r"(\d{4})\.(\d{2})\.(\d{2})\s*~\s*(\d{4})\.(\d{2})\.(\d{2})"
)
_BULLET_PATTERN = re.compile(r"^\s*([•·▪-])\s*")
_KOREAN_SYLLABLE = re.compile(r"[가-힣]")


@dataclass
class ParsedReportEntry:
    department: str
    entry_type: str  # "실적" 또는 "계획"
    period_start: date
    period_end: date
    source_category: str
    content: str
    # 원본 셀에서 이 항목이 쓰여 있던 표현 형식. 글머리 기호를 썼으면 "bullet:<기호>"
    # (예: "bullet:•", "bullet:-"), 기호 없이 문장 하나로 쓰여 있었으면 "prose".
    source_format: str


def extract_department(page_text: str) -> str | None:
    """"■ 부서명 : 시군 특화 일자리 사업단" 줄에서 부서명만 뽑는다."""
    match = _DEPARTMENT_PATTERN.search(page_text)
    return match.group(1).strip() if match else None


def _parse_period(header_cell: str) -> tuple[date, date] | None:
    match = _PERIOD_PATTERN.search(header_cell)
    if not match:
        return None
    y1, m1, d1, y2, m2, d2 = (int(part) for part in match.groups())
    return date(y1, m1, d1), date(y2, m2, d2)


def _entry_type_from_header(header_cell: str) -> str | None:
    if "실적" in header_cell:
        return "실적"
    if "계획" in header_cell:
        return "계획"
    return None


def _join_wrapped_lines(lines: list[str]) -> str:
    """PDF 자동 줄바꿈으로 쪼개진 한 항목의 여러 줄을 하나의 문장으로 합친다.

    줄 경계 앞뒤가 둘 다 한글 음절이면(예: "추진계"+"획") 단어 중간에서 그냥 꺾인
    것으로 보고 공백 없이 붙인다. 그 외(숫자/영문/기호와 맞닿은 경우, 예: "총"+"2개")는
    원래 공백이 있었을 가능성이 있어 공백을 넣는다 — 완벽하진 않지만 실제 관찰된
    패턴(한글 단어 중간 줄바꿈은 항상 공백 없음)에 기반한 근사치다.
    """
    result = lines[0]
    for line in lines[1:]:
        prev_char = result[-1] if result else ""
        next_char = line[0] if line else ""
        if _KOREAN_SYLLABLE.match(prev_char) and _KOREAN_SYLLABLE.match(next_char):
            result += line
        else:
            result += " " + line if result else line
    return result


def _split_cell_into_items(cell_text: str) -> tuple[str, list[str]]:
    """셀 안의 여러 항목을 글머리 기호(•, -) 기준으로 나누고, 감지된 표현 형식도 같이 반환한다.

    글머리 기호가 없는 셀(항목이 하나뿐이거나, 원본이 불릿을 안 쓴 경우)은 셀 전체를
    항목 하나("prose")로 취급한다 — 불릿 유무를 가정하지 않는다.
    """
    raw_lines = [line for line in cell_text.split("\n") if line.strip()]
    if not raw_lines:
        return "prose", []

    if not any(_BULLET_PATTERN.match(line) for line in raw_lines):
        return "prose", [_join_wrapped_lines([line.strip() for line in raw_lines])]

    marker: str | None = None
    items: list[list[str]] = []
    for line in raw_lines:
        stripped = line.strip()
        match = _BULLET_PATTERN.match(stripped)
        if match:
            marker = marker or match.group(1)
            items.append([_BULLET_PATTERN.sub("", stripped, count=1).strip()])
        elif items:
            items[-1].append(stripped)
        # 첫 줄부터 불릿이 아니면(드묾) 버리지 않고 무시 — 실제로 이런 헤더성 잡음은
        # 표 밖 텍스트에서 이미 걸러지므로 여기까지 들어오는 경우는 거의 없다.

    return f"bullet:{marker}", [_join_wrapped_lines(lines) for lines in items if lines]


def parse_report_table(rows: list[list[str | None]], page_text: str) -> list[ParsedReportEntry]:
    """find_tables()의 table.extract() 결과(2차원 셀 배열)를 구조화된 항목 리스트로 바꾼다.

    rows[0]은 헤더 행("구분" | "업무 실적 (기간)" | "업무 계획 (기간)"), rows[1:]은
    구분별 데이터 행이라고 가정한다 — 지금까지 확인한 실제 문서 33주치가 전부 이 구조.
    """
    if not rows or len(rows) < 2:
        return []

    department = extract_department(page_text) or ""
    header = rows[0]

    column_specs: dict[int, tuple[str, date, date]] = {}
    for col_idx, header_cell in enumerate(header[1:], start=1):
        header_text = (header_cell or "").strip()
        entry_type = _entry_type_from_header(header_text)
        period = _parse_period(header_text)
        if entry_type is None or period is None:
            continue
        column_specs[col_idx] = (entry_type, period[0], period[1])

    entries: list[ParsedReportEntry] = []
    for row in rows[1:]:
        if not row:
            continue
        source_category = (row[0] or "").replace("\n", " ").strip()
        if not source_category:
            continue
        for col_idx, (entry_type, period_start, period_end) in column_specs.items():
            if col_idx >= len(row):
                continue
            cell_text = row[col_idx] or ""
            source_format, items = _split_cell_into_items(cell_text)
            for item in items:
                entries.append(
                    ParsedReportEntry(
                        department=department,
                        entry_type=entry_type,
                        period_start=period_start,
                        period_end=period_end,
                        source_category=source_category,
                        content=item,
                        source_format=source_format,
                    )
                )

    return entries
