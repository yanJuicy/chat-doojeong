from __future__ import annotations

import unittest

from app.core.pdf_page_classifier import (
    choose_mixed_page_text,
    classify_pdf_page,
    rectangle_coverage_ratios,
    rectangle_union_area,
)


class PdfPageClassifierTests(unittest.TestCase):
    def test_readable_native_text_without_large_image_is_digital(self) -> None:
        profile = classify_pdf_page(
            "협동로봇 설치 방법입니다. 전원을 연결하고 초기 위치를 확인합니다.",
            image_coverage_ratio=0.08,
            max_image_coverage_ratio=0.05,
        )
        self.assertEqual(profile.mode, "digital")

    def test_empty_text_with_full_page_image_is_ocr(self) -> None:
        profile = classify_pdf_page("", image_coverage_ratio=0.96, max_image_coverage_ratio=0.96)
        self.assertEqual(profile.mode, "ocr")

    def test_short_title_with_large_body_image_is_mixed(self) -> None:
        profile = classify_pdf_page(
            "제품 주요 기능",
            image_coverage_ratio=0.82,
            max_image_coverage_ratio=0.78,
        )
        self.assertEqual(profile.mode, "mixed")

    def test_garbled_hanja_native_text_is_ocr(self) -> None:
        profile = classify_pdf_page(
            "機器設備連結裝置機器設備連結裝置機器設備連結裝置",
            image_coverage_ratio=0.10,
            max_image_coverage_ratio=0.10,
        )
        self.assertEqual(profile.mode, "ocr")
        self.assertTrue(profile.is_garbled)

    def test_short_readable_title_without_image_stays_digital(self) -> None:
        profile = classify_pdf_page(
            "제품 개요",
            image_coverage_ratio=0.0,
            max_image_coverage_ratio=0.0,
        )
        self.assertEqual(profile.mode, "digital")

    def test_richer_ocr_replaces_title_only_native_text(self) -> None:
        selected, strategy = choose_mixed_page_text(
            "MUFFLER의 기능",
            "MUFFLER의 기능\n소음 감소 기능\n배기가스 냉각 팽창 기능\n배기가스 흐름 유도 기능\n배기가스 정화 기능",
        )
        self.assertEqual(strategy, "ocr_richer")
        self.assertIn("배기가스 정화 기능", selected)

    def test_complementary_lines_are_merged_without_exact_duplicate(self) -> None:
        selected, strategy = choose_mixed_page_text(
            "매니폴드는 배기가스를 모아 전달한다.\n산소 센서를 장착한다.",
            "매니폴드는 배기가스를 모아 전달한다.\n촉매변환기로 배기가스를 보낸다.",
        )
        self.assertEqual(strategy, "merged")
        self.assertEqual(selected.count("매니폴드는 배기가스를 모아 전달한다."), 1)
        self.assertIn("산소 센서를 장착한다.", selected)
        self.assertIn("촉매변환기로 배기가스를 보낸다.", selected)

    def test_rectangle_union_does_not_double_count_overlap(self) -> None:
        area = rectangle_union_area([(0, 0, 10, 10), (5, 0, 15, 10)])
        self.assertEqual(area, 150)

    def test_rectangle_coverage_clips_to_page(self) -> None:
        union_ratio, max_ratio = rectangle_coverage_ratios(
            (0, 0, 100, 100),
            [(-20, -20, 80, 80), (70, 70, 120, 120)],
        )
        self.assertAlmostEqual(union_ratio, 0.72)
        self.assertAlmostEqual(max_ratio, 0.64)


if __name__ == "__main__":
    unittest.main()
