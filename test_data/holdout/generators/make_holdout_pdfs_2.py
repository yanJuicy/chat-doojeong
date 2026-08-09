# -*- coding: utf-8 -*-
"""2차 홀드아웃 세트: 완전히 다른 업종(산업용 펌프), 이번엔 실제 표(Table) 구조 포함.
1차 세트(선다인테크/태양광)와 겹치는 내용 전혀 없음."""
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
styles = getSampleStyleSheet()
title_style = ParagraphStyle("KTitle", parent=styles["Title"], fontName="HYSMyeongJo-Medium", fontSize=18)
h_style = ParagraphStyle("KHeading", parent=styles["Heading2"], fontName="HYSMyeongJo-Medium", fontSize=13)
body_style = ParagraphStyle("KBody", parent=styles["Normal"], fontName="HYSMyeongJo-Medium", fontSize=11, leading=16)
cell_style = ParagraphStyle("KCell", parent=styles["Normal"], fontName="HYSMyeongJo-Medium", fontSize=10, leading=13)


def build_text(path, blocks):
    doc = SimpleDocTemplate(path, pagesize=A4)
    story = []
    for kind, text in blocks:
        style = {"title": title_style, "h": h_style}.get(kind, body_style)
        story.append(Paragraph(text, style))
        story.append(Spacer(1, 10))
    doc.build(story)
    print("wrote", path)


# 문서 D: 회사소개서 — 기능 나열 + 조립공정 순서
build_text(
    "holdout_D_company_intro.pdf",
    [
        ("title", "그린웨이브산업 회사소개서"),
        ("h", "GREENWAVE INDUSTRIAL"),
        (
            "b",
            "그린웨이브산업은 산업용 원심펌프를 전문으로 제조하는 회사입니다. "
            "주력 제품은 GW 시리즈 원심펌프이며, 이중 메카니컬 씰 구조를 채택하고 있습니다.",
        ),
        ("h", "이중 메카니컬 씰의 기능"),
        (
            "b",
            "1. 1차 누설 방지 기능<br/>펌프 축과 하우징 사이의 유체 누설을 1차적으로 차단합니다.",
        ),
        (
            "b",
            "2. 2차 백업 밀봉 기능<br/>1차 씰이 마모되어도 2차 씰이 즉시 백업하여 누설 사고를 방지합니다.",
        ),
        (
            "b",
            "3. 씰 챔버 압력 감지 기능<br/>두 씰 사이 챔버의 압력 변화를 감지해 씰 마모 시점을 사전에 알려줍니다.",
        ),
        (
            "b",
            "참고로 본 제품은 이중 메카니컬 씰 방식을 사용하며, 이는 단일 패킹글랜드 방식보다 "
            "부식성 유체 이송 환경에서 훨씬 낮은 유지보수 빈도를 제공합니다.",
        ),
        ("h", "펌프 조립 공정"),
        (
            "b",
            "조립 공정은 다음 순서로 진행됩니다.<br/>"
            "1. 임펠러 밸런싱<br/>2. 씰 하우징 조립<br/>3. 베어링 압입<br/>4. 수압 테스트<br/>5. 도장 및 출하",
        ),
    ],
)

# 문서 E: 제품 사양 — 실제 Table 구조 (교차혼동 테스트)
doc = SimpleDocTemplate("holdout_E_spec_table.pdf", pagesize=A4)
story = [Paragraph("GW 시리즈 원심펌프 제품 사양", title_style), Spacer(1, 14)]
table_data = [
    [Paragraph(h, cell_style) for h in ["모델명", "유량(㎥/h)", "양정(m)", "소비전력(kW)"]],
    [Paragraph(v, cell_style) for v in ["GW-100", "50", "30", "7.5"]],
    [Paragraph(v, cell_style) for v in ["GW-250", "120", "45", "18.5"]],
    [Paragraph(v, cell_style) for v in ["GW-500", "300", "60", "45.0"]],
]
t = Table(table_data, colWidths=[100, 110, 100, 120])
t.setStyle(
    TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.75, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
    )
)
story.append(t)
doc.build(story)
print("wrote holdout_E_spec_table.pdf")

# 문서 F: 인증서
build_text(
    "holdout_F_certificate.pdf",
    [
        ("title", "품질경영시스템 인증서"),
        ("b", "제품명: GW-250 원심펌프"),
        ("b", "제조사: 그린웨이브산업"),
        ("b", "인증번호: ISO9001-GW-77042"),
        ("b", "본 제품은 품질경영시스템 국제표준에 적합함을 인증합니다."),
    ],
)
