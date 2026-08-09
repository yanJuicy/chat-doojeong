# -*- coding: utf-8 -*-
"""3차 홀드아웃: 아예 다른 문서 구조(Q&A/FAQ 형식, 서비스업). 1·2차와 도메인도 겹치지 않음."""
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
        style = {"title": title_style, "h": h_style}.get(kind, body_style)
        story.append(Paragraph(text, style))
        story.append(Spacer(1, 10))
    doc.build(story)
    print("wrote", path)


build(
    "holdout_G_faq.pdf",
    [
        ("title", "모래언덕 세탁구독 서비스 이용안내 (FAQ)"),
        ("h", "모래언덕이란?"),
        (
            "b",
            "모래언덕은 정기 방문 세탁 수거·배달 구독 서비스입니다. 서울·경기 지역에서 "
            "주 1회 또는 격주 1회 방문 주기를 선택할 수 있습니다.",
        ),
        ("h", "Q. 세탁물은 몇 시간 안에 돌려받나요?"),
        ("b", "A. 수거 후 48시간 이내에 배달을 완료합니다. 단, 명절 연휴 기간에는 72시간까지 소요될 수 있습니다."),
        ("h", "Q. 구독 요금제는 어떻게 되나요?"),
        (
            "b",
            "A. 라이트 요금제는 월 29,000원(주 1회, 최대 5kg), 스탠다드 요금제는 월 49,000원(주 1회, 최대 12kg), "
            "패밀리 요금제는 월 79,000원(주 2회, 최대 20kg)입니다.",
        ),
        ("h", "Q. 가죽 제품도 세탁 가능한가요?"),
        ("b", "A. 가죽 및 모피 제품은 별도 협력업체를 통해 처리하며, 기본 구독 요금과 별도로 건당 추가 요금이 부과됩니다."),
        ("h", "Q. 해지는 언제든 가능한가요?"),
        ("b", "A. 최소 이용기간 없이 다음 결제일 전까지 앱에서 해지 신청하면 위약금 없이 해지됩니다."),
    ],
)
