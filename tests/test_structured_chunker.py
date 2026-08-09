from __future__ import annotations

import unittest

from app.core.structured_chunker import (
    StructuredChunker,
    demote_consecutive_empty_headings,
    is_heading_line,
    merge_native_table_sections,
)


class _FakeEmbeddingProvider:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def embed_hybrid(self, texts: list[str]):
        return await self.embed_documents(texts), [{} for _ in texts]

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class StructuredChunkerHeadingTests(unittest.TestCase):
    def test_measurement_rows_are_not_section_headings(self) -> None:
        for line in (
            "7.3 kg",
            "54.6 kg",
            "12 kN 예압 인가",
            "28 kHz 초음파 진동 적용",
            "180°C 최고 온도",
            "1.65 m/s",
        ):
            with self.subTest(line=line):
                self.assertFalse(is_heading_line(line))

    def test_numbered_manual_sections_remain_headings(self) -> None:
        self.assertTrue(is_heading_line("7.3 작업 반경 설정"))
        self.assertTrue(is_heading_line("3. 설치 방법"))

    def test_consecutive_empty_numbered_headings_are_treated_as_list_rows(self) -> None:
        lines = ["제조 공정", "1. 부품검사", "2. 기판조립", "3. 절연테스트", "4. 출하검사"]
        headings = [index for index, line in enumerate(lines) if is_heading_line(line)]

        kept = demote_consecutive_empty_headings(lines, headings)

        self.assertEqual(kept, [])


class StructuredChunkerMeasurementPreservationTests(unittest.IsolatedAsyncioTestCase):
    def test_native_table_model_rows_are_rejoined_with_headers(self) -> None:
        sections = [
            ("GW 시리즈 제품 사양", "모델명\n유량(㎥/h)\n양정(m)\n소비전력(kW)"),
            ("GW-100", "50\n30\n7.5"),
            ("GW-250", "120\n45\n18.5"),
            ("GW-500", "300\n60\n45.0"),
        ]

        merged = merge_native_table_sections(sections)

        self.assertEqual(len(merged), 1)
        self.assertIn("모델명 | 유량(㎥/h) | 양정(m) | 소비전력(kW)", merged[0][1])
        self.assertIn("GW-250 | 120 | 45 | 18.5", merged[0][1])

    def test_two_ordinary_model_sections_are_not_merged_without_header_shape(self) -> None:
        sections = [
            ("제품 소개", "이 문서는 두 모델의 상세 사양을 설명한다."),
            ("AX-100", "10\n20\n30"),
            ("AX-200", "40\n50\n60"),
        ]

        self.assertEqual(merge_native_table_sections(sections), sections)

    async def test_table_like_measurement_values_survive_chunking(self) -> None:
        text = """<!-- PAGE:1 -->
제품 사양표
항목
KX-41 사양
정격 가반하중
7.3 kg
최대 작업 반경
1,184 mm
본체 질량
54.6 kg
보호 등급
IP55
적용 안내
수치를 초과하지 않는다.
"""
        chunks = await StructuredChunker(_FakeEmbeddingProvider()).split("doc", text)
        combined = "\n".join(chunk.text for chunk in chunks)

        self.assertIn("7.3 kg", combined)
        self.assertIn("54.6 kg", combined)
        self.assertIn("1,184 mm", combined)

    async def test_consecutive_process_steps_survive_as_one_section(self) -> None:
        text = """<!-- PAGE:1 -->
인버터 제조 공정
제조 공정은 다음 순서로 진행됩니다.
1. 부품검사
2. 기판조립
3. 방열판 부착
4. 절연테스트
5. 출하검사
"""
        chunks = await StructuredChunker(_FakeEmbeddingProvider()).split("doc", text)
        matching = [chunk.text for chunk in chunks if "절연테스트" in chunk.text]

        self.assertEqual(len(matching), 1)
        self.assertIn("4. 절연테스트\n5. 출하검사", matching[0])

    async def test_native_pdf_table_keeps_column_names_and_rows_in_one_chunk(self) -> None:
        text = """<!-- PAGE:1 -->
GW 시리즈 원심펌프 제품 사양
모델명
유량(㎥/h)
양정(m)
소비전력(kW)
GW-100
50
30
7.5
GW-250
120
45
18.5
GW-500
300
60
45.0
"""
        chunks = await StructuredChunker(_FakeEmbeddingProvider()).split("doc", text)
        matching = [chunk.text for chunk in chunks if "GW-250" in chunk.text]

        self.assertEqual(len(matching), 1)
        self.assertIn("모델명 | 유량(㎥/h) | 양정(m) | 소비전력(kW)", matching[0])
        self.assertIn("GW-250 | 120 | 45 | 18.5", matching[0])


if __name__ == "__main__":
    unittest.main()
