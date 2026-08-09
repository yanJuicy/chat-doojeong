from __future__ import annotations

import unittest

from app.core.label_matching import find_question_label_hints, model_family_aliases, organization_label_aliases


class LabelMatchingTests(unittest.TestCase):
    def test_unique_organization_suffix_alias_is_matched(self) -> None:
        labels = ["별하자동화", "KX-41", "다온소재"]

        matches = find_question_label_hints("별하 로봇 팔은 몇 mm까지 뻗나?", labels)

        self.assertEqual(matches, ["별하자동화"])

    def test_ambiguous_short_alias_is_not_matched(self) -> None:
        labels = ["별하자동화", "별하테크"]

        matches = find_question_label_hints("별하 제품의 사양은?", labels)

        self.assertEqual(matches, [])

    def test_arbitrary_prefix_is_not_an_alias(self) -> None:
        self.assertEqual(organization_label_aliases("레인보우"), set())
        self.assertEqual(organization_label_aliases("별하자동화"), {"별하"})

    def test_model_family_matches_multiple_labels_only_for_comparison(self) -> None:
        labels = ["VTX-310", "VTX-310E", "KX-41"]

        comparison = find_question_label_hints("두 VTX 모델 중 작업 반경이 더 긴 것은?", labels)
        ordinary = find_question_label_hints("VTX 모델의 작업 반경은?", labels)

        self.assertEqual(set(comparison), {"VTX-310", "VTX-310E"})
        self.assertEqual(ordinary, [])
        self.assertEqual(model_family_aliases("VTX-310E"), {"vtx"})
        self.assertEqual(model_family_aliases("RB3-1200E"), set())


if __name__ == "__main__":
    unittest.main()
