"""
WeeklyReportView를 원본 "주간 업무실적 및 계획" 양식(구분 1개: 사업관리)과 같은
모양의 DOCX로 렌더링한다.
"""
from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from .weekly_report_composer import ReportPeriodBlock, WeeklyReportView


def _set_run_font(run, *, size: float, bold: bool = False) -> None:
    run.font.name = "맑은 고딕"
    run.font.size = Pt(size)
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    fonts.set(qn("w:eastAsia"), "맑은 고딕")


def _set_cell_fill(cell, color: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), color)
    tc_pr.append(shading)


def _format_period(block: ReportPeriodBlock) -> str:
    return f"({block.period_start.strftime('%Y.%m.%d')} ~ {block.period_end.strftime('%Y.%m.%d')})"


def _fill_items_cell(cell, items: list, *, size: float = 10) -> None:
    paragraph = cell.paragraphs[0]
    if not items:
        _set_run_font(paragraph.add_run("-"), size=size)
        return
    for index, item in enumerate(items):
        target = paragraph if index == 0 else cell.add_paragraph()
        target.paragraph_format.space_before = Pt(0)
        target.paragraph_format.space_after = Pt(2)
        _set_run_font(target.add_run(f"• {item.content}"), size=size)


def render_weekly_report_docx(view: WeeklyReportView) -> bytes:
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.8)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run_font(title.add_run("주간 업무실적 및 계획"), size=18, bold=True)

    dept_paragraph = document.add_paragraph()
    _set_run_font(dept_paragraph.add_run(f"■ 부서명 : {view.department}"), size=10.5, bold=True)

    table = document.add_table(rows=2, cols=3)
    table.style = "Table Grid"
    for row in table.rows:
        for cell in row.cells:
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

    headers = (
        "구분",
        f"업무 실적\n{_format_period(view.current_week)}",
        f"업무 계획\n{_format_period(view.next_week)}",
    )
    for index, header in enumerate(headers):
        cell = table.cell(0, index)
        _set_cell_fill(cell, "D9E2F3")
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        lines = header.split("\n")
        _set_run_font(paragraph.add_run(lines[0]), size=10.5, bold=True)
        for line in lines[1:]:
            sub = cell.add_paragraph()
            sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_run_font(sub.add_run(line), size=9)

    row = table.rows[1]
    category_paragraph = row.cells[0].paragraphs[0]
    category_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run_font(category_paragraph.add_run("사업관리"), size=10.5, bold=True)

    _fill_items_cell(row.cells[1], view.current_week.items)
    _fill_items_cell(row.cells[2], view.next_week.items)

    document.core_properties.title = f"주간 업무실적 및 계획 ({view.department})"
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()
