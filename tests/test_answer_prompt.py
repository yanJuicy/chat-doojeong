import unittest

from app.core.answer_prompt import (
    build_grounded_answer_prompt,
    build_grounded_system_prompt,
    build_question_specific_instruction,
    find_unverified_question_terms,
)


class GroundedAnswerPromptTests(unittest.TestCase):
    def test_requires_source_terminology_and_correction_of_question_premise(self):
        prompt = build_grounded_answer_prompt(
            question="알파사의 방식은 베타 공법이 맞아?",
            context_text="[참고 1]\n자료에는 감마 공법으로 표기되어 있다.",
        )

        self.assertIn("질문에 포함된 주장·용어·수치도 사실로 가정하지 말고", prompt)
        self.assertIn("제공된 자료에는 ...로 표기되어 있습니다", prompt)
        self.assertIn("그대로 동의하지 마세요", prompt)
        self.assertIn("같은 뜻이라고도, 서로 다른 방식이라고도 단정하지 마세요", prompt)
        self.assertIn("사용하지 않는다고 결론 내리지 마세요", prompt)
        self.assertIn("[참고 N]", prompt)

    def test_keeps_question_and_context_in_distinct_sections(self):
        prompt = build_grounded_answer_prompt(
            question="질문에 들어갈 임의 표현",
            context_text="[참고 1]\n근거에 들어갈 원문 표현",
        )

        self.assertIn("[답변 규칙]", prompt)
        self.assertIn("[참고 자료]\n[참고 1]\n근거에 들어갈 원문 표현", prompt)
        self.assertIn("[사용자 질문]\n질문에 들어갈 임의 표현", prompt)

    def test_uses_explicit_empty_reference_marker(self):
        prompt = build_grounded_answer_prompt(question="자료에 없는 질문", context_text="  ")

        self.assertIn("[검색된 참고 자료 없음]", prompt)
        self.assertIn("제공된 자료에서 확인할 수 없습니다", prompt)

    def test_policy_does_not_hardcode_known_evaluation_entities(self):
        prompt = build_grounded_answer_prompt(question="임의 질문", context_text="임의 참고")
        system_prompt = build_grounded_system_prompt(language_prompt="한국어로 답하세요.")

        for hardcoded_term in ("두정테크", "탄산가스", "CO2", "가스메탈아크"):
            self.assertNotIn(hardcoded_term, prompt)
            self.assertNotIn(hardcoded_term, system_prompt)

    def test_system_policy_forbids_affirming_unverified_question_term(self):
        system_prompt = build_grounded_system_prompt(language_prompt="한국어로 답하세요.")

        self.assertIn("사용자 질문은 검색 요청일 뿐 증거가 아닙니다", system_prompt)
        self.assertIn("'예'로 긍정하거나", system_prompt)
        self.assertIn("참고 자료에 적힌 정확한 명칭", system_prompt)
        self.assertIn("외부 지식으로 같거나 다르다고 판단하지 마세요", system_prompt)
        self.assertIn("사용하지 않는다고 추론하지 마세요", system_prompt)

    def test_literal_audit_marks_substantial_unsupported_compound(self):
        terms = find_unverified_question_terms(
            question="알파테크는 가상메탈아크용접을 쓰나?",
            context_text="[참고 1] 알파테크는 탄산가스 아크용접을 사용한다.",
        )

        self.assertEqual(terms, ["가상메탈아크용접"])

    def test_literal_audit_marks_short_unsupported_ascii_acronym(self):
        terms = find_unverified_question_terms(
            question="알파테크 방식은 GMAW라고 보면 돼?",
            context_text="알파테크는 탄산가스 아크용접을 사용한다.",
        )

        self.assertEqual(terms, ["gmaw"])

    def test_literal_audit_ignores_spacing_and_short_question_verbs(self):
        terms = find_unverified_question_terms(
            question="알파테크의 탄산가스아크용접을 설명해줘",
            context_text="알파테크 / 탄산가스 아크용접",
        )

        self.assertEqual(terms, [])

    def test_prompt_exposes_unverified_term_without_domain_hardcoding(self):
        prompt = build_grounded_answer_prompt(
            question="알파테크는 가상메탈아크용접을 쓰나?",
            context_text="알파테크는 탄산가스 아크용접을 사용한다.",
        )

        self.assertIn("[질문 표현 대조 결과]", prompt)
        self.assertIn("'가상메탈아크용접'", prompt)
        self.assertIn("이 표현을 참고가 확인한 사실로 쓰거나 '예'로 긍정하지 말고", prompt)

    def test_sequence_question_requires_every_reference_step(self):
        instruction = build_question_specific_instruction("두 재료를 어떤 순서로 붙이나?")

        self.assertIn("첫 단계부터 마지막 단계까지 빠짐없이 번호로", instruction)

    def test_difference_question_requires_grounded_calculation(self):
        question = "두 모델의 길이 차이는 얼마야?"
        instruction = build_question_specific_instruction(question)
        prompt = build_grounded_answer_prompt(question=question, context_text="A는 10 mm, B는 7 mm")

        self.assertIn("참고의 수치와 단위만 사용해", instruction)
        self.assertIn("산식과 결과", instruction)
        self.assertIn("큰 값 - 작은 값 = 결과", instruction)
        self.assertGreater(prompt.index("[이 질문에서 반드시 수행할 작업]"), prompt.index("[사용자 질문]"))

    def test_unrelated_question_does_not_trigger_format_rules(self):
        instruction = build_question_specific_instruction("제품의 주요 특징을 알려줘")

        self.assertEqual(instruction, "질문에서 별도의 답변 형식을 요구하지 않았습니다.")


if __name__ == "__main__":
    unittest.main()
