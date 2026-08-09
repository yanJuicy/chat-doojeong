from __future__ import annotations

import unittest

from app.core.extraction_quality import choose_better_extraction, evaluate_extraction_quality


class ExtractionQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broken = "SQ 1.CO20 2. 3. 4."
        self.good = (
            "탄산가스 아크용접은 CO2 용접이라고 불린다. "
            "아르곤 대신 이산화탄소 가스를 사용하며 용접 속도가 빠르고 비용이 저렴하다. "
            "공정은 용접, 누설 검사, 스패터 제거, 평면도 측정, 출하 순으로 진행된다."
        )

    def test_broken_ocr_is_blocked(self) -> None:
        self.assertLess(evaluate_extraction_quality(self.broken).score, 0.45)

    def test_meaningful_ocr_passes(self) -> None:
        self.assertGreaterEqual(evaluate_extraction_quality(self.good).score, 0.45)

    def test_fallback_selects_better_text(self) -> None:
        selected, quality, source = choose_better_extraction(self.broken, self.good)
        self.assertEqual(selected, self.good)
        self.assertEqual(source, "fallback")
        self.assertGreaterEqual(quality.score, 0.45)

    def test_html_image_markup_does_not_inflate_broken_ocr_score(self) -> None:
        broken_with_markup = """WELDING BUSINESS
SQ
1.CO20
<div style="text-align: center;"><img src="imgs/a.jpg" alt="Image" width="76%" /></div>
2.
3.
4.
5.00人
"""
        quality = evaluate_extraction_quality(broken_with_markup)
        self.assertLess(quality.score, 0.45)
        self.assertLess(quality.char_count, 60)

    def test_hanja_substitution_does_not_pass_korean_ocr_gate(self) -> None:
        broken_hanja = "機器設備連結裝置性能說明安全檢査方法運轉條件製品規格使用方法"
        quality = evaluate_extraction_quality(broken_hanja)
        self.assertLess(quality.score, 0.45)
        self.assertIn("한글 대비 한자 비율이 높아 폰트/OCR 깨짐 가능성", quality.reasons)


if __name__ == "__main__":
    unittest.main()
