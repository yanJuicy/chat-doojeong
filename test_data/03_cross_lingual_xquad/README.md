# XQuAD (교차언어 QA 테스트셋)

- 원본: https://github.com/deepmind/xquad (라이선스: CC BY-SA 4.0, `xquad_original_README.md` 참고)
- 실제 데이터 파일(`xquad.*.json`)은 이번에 정상적으로 다운로드해서 이 폴더에 포함해뒀습니다.
- 11개 언어(ar, de, el, en, es, hi, ro, ru, th, tr, vi, zh) — **한국어는 포함되어 있지 않습니다.**

## 활용 방법 (외국 문서 해석 시나리오 테스트)

같은 240개 문단이 언어별로 병렬 번역되어 있어, 다음과 같은 교차언어 테스트가 가능합니다:

1. `xquad.en.json`(영어 원문)을 문서로 임베딩/적재
2. `xquad.de.json`, `xquad.zh.json` 등 다른 언어의 질문을 한국어로 번역해서 질의 (또는 그대로 질의)
3. bge-m3 임베딩이 언어가 달라도 같은 문단을 정확히 찾아내는지, Qwen2.5가 영어 원문 근거로 한국어 답변을 정확히 생성하는지 확인

## 파일 구조 (예: xquad.en.json)

SQuAD 형식과 동일합니다:
```json
{
  "data": [
    {
      "paragraphs": [
        {
          "context": "문단 원문",
          "qas": [
            {"question": "질문", "answers": [{"text": "정답", "answer_start": 123}]}
          ]
        }
      ]
    }
  ]
}
```

## 참고

한국어가 껴 있는 교차언어 테스트가 꼭 필요하면, 별도로 **KorQuAD 1.0**(한국어 SQuAD, https://korquad.github.io/)을
같이 받아서 "한국어 문서 + 영어 질문" 같은 역방향 조합으로 직접 테스트셋을 구성하는 것도 방법입니다.
(KorQuAD도 github 기반이라 이 환경에서 바로 받아드릴 수 있습니다 — 필요하시면 말씀해주세요.)
