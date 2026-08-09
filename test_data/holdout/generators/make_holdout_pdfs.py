# -*- coding: utf-8 -*-
"""오늘 만든 검색/답변 파이프라인이 로봇/두정테크 문서에 과적합됐는지 검증하기 위해,
완전히 다른 주제(태양광 인버터 회사 '선다인테크')의 가짜 PDF 3개를 새로 만든다.
이 문서들은 코드나 프롬프트 어디에도 언급된 적 없는 최초 등장 콘텐츠다.
"""
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))

styles = getSampleStyleSheet()
title_style = ParagraphStyle("KTitle", parent=styles["Title"], fontName="HYSMyeongJo-Medium", fontSize=18)
h_style = ParagraphStyle("KHeading", parent=styles["Heading2"], fontName="HYSMyeongJo-Medium", fontSize=13)
body_style = ParagraphStyle("KBody", parent=styles["Normal"], fontName="HYSMyeongJo-Medium", fontSize=11, leading=16)


def build(path, blocks):
    doc = SimpleDocTemplate(path, pagesize=A4)
    story = []
    for kind, text in blocks:
        if kind == "title":
            story.append(Paragraph(text, title_style))
        elif kind == "h":
            story.append(Paragraph(text, h_style))
        else:
            story.append(Paragraph(text, body_style))
        story.append(Spacer(1, 10))
    doc.build(story)
    print("wrote", path)


# 문서 A: 회사소개서 — 공정 순서(process order) + 다기능 컴포넌트(function list) 테스트용
build(
    "holdout_A_company_intro.pdf",
    [
        ("title", "선다인테크 회사소개서"),
        ("h", "SUNDYNE TECH"),
        (
            "b",
            "선다인테크는 태양광 발전용 인버터를 전문으로 생산하는 제조사입니다. "
            "주력 제품은 SD 시리즈 태양광 인버터이며, MPPT(최대전력점 추적) 방식을 채택하고 있습니다.",
        ),
        ("h", "MPPT 컨트롤러의 기능"),
        (
            "b",
            "1. 최대전력점 추적 기능<br/>"
            "태양광 패널의 전압-전류 곡선에서 실시간으로 최대 출력점을 찾아 발전 효율을 높이는 핵심 기능입니다.",
        ),
        (
            "b",
            "2. 과전압 보호 기능<br/>"
            "입력 전압이 정격치를 초과하면 회로를 차단하여 내부 부품의 손상을 방지합니다.",
        ),
        (
            "b",
            "3. 온도 보상 기능<br/>"
            "주변 온도 변화에 따른 패널 출력 특성 변화를 자동으로 보정하여 발전량 손실을 줄입니다.",
        ),
        (
            "b",
            "참고로 본 제품은 MPPT 방식을 사용하며, 이는 고정 듀티비로 동작하는 PWM 방식보다 "
            "일사량 변화가 큰 환경에서 더 높은 발전 효율을 제공합니다.",
        ),
        ("h", "인버터 제조 공정"),
        (
            "b",
            "제조 공정은 다음 순서로 진행됩니다.<br/>"
            "1. 부품검사<br/>2. 기판조립<br/>3. 방열판 부착<br/>4. 절연테스트<br/>5. 출하검사",
        ),
    ],
)

# 문서 B: 제품 사양서 — 교차혼동(cross-product) 테스트용, 모델별 스펙이 서로 다름
build(
    "holdout_B_spec_sheet.pdf",
    [
        ("title", "SD 시리즈 인버터 제품 사양"),
        ("h", "SD-500"),
        ("b", "정격출력: 5kW<br/>변환효율: 98.1%<br/>중량: 12kg"),
        ("h", "SD-1000"),
        ("b", "정격출력: 10kW<br/>변환효율: 98.6%<br/>중량: 21kg"),
        ("h", "SD-3000"),
        ("b", "정격출력: 30kW<br/>변환효율: 97.9%<br/>중량: 58kg"),
    ],
)

# 문서 C: 인증서 — 정확한 식별자(exact identifier) 테스트용
build(
    "holdout_C_certificate.pdf",
    [
        ("title", "형식승인 인증서"),
        ("b", "제품명: SD-1000 태양광 인버터"),
        ("b", "제조사: 선다인테크"),
        ("b", "인증번호: KC-INV-2024-88231"),
        ("b", "본 제품은 전기용품 및 생활용품 안전관리법에 따라 안전기준에 적합함을 인증합니다."),
    ],
)
