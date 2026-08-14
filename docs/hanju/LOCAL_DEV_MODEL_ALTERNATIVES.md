# 저사양 로컬 개발 환경용 모델 대안 (MacBook 2018, GPU 없음)

이 문서는 **팀 운영 스택(RTX GPU 서버)을 대체하는 문서가 아니라**, GPU가 없는 개발자 로컬 머신에서
같은 파이프라인을 CPU만으로 돌려서 개발/디버깅할 수 있게 하기 위한 "로컬 개발 티어(dev tier)" 모델
대안 정리입니다. 실서버(컴1/컴2, RTX 5070/5060) 설정은 그대로 두고, 이 문서의 조합은 로컬 venv에서
`.env` 또는 설정 오버라이드로 별도 프로파일을 만들 때 참고하세요.

## 대상 하드웨어

- MacBook (2018), 저전력 8세대 Intel Core i5 (Y/U 시리즈, 2코어 또는 4코어)
- 16GB DDR3 RAM
- GPU 없음 (Intel UHD 내장 그래픽만 존재, CUDA/Metal 가속 대상 아님) → **모든 추론은 CPU 전용**

CPU-only 환경에서 중요한 제약:
- 저전력 i5 8세대는 코어 수와 클럭이 낮아 동시 워커(추출/청킹/임베딩) 병렬화 여유가 거의 없음 → 워커를 순차 실행하거나 동시성 1로 제한 권장
- DDR3는 DDR4/5 대비 대역폭이 낮아, 파라미터 수가 큰 모델일수록 토큰 생성 속도가 급격히 느려짐 (메모리 대역폭이 병목)
- 16GB 중 OS/Docker(Postgres+Qdrant)가 상시 점유하는 몫이 있으므로, LLM 자체는 **RAM 4~6GB 이내**로 제한하는 것이 현실적

## 1. LLM (Ollama) 대안

운영 스택은 GPU 위에서 qwen3:8b/4b. CPU-only에서는 같은 Qwen3 계열의 더 작은 변형이 가장 무난합니다
(계열이 같으면 나중에 답변 스타일/프롬프트 튜닝 결과를 서버 모델로 옮기기 쉬움).

| 모델 | 파라미터 | Q4_K_M 크기(대략) | 비고 |
|---|---|---|---|
| **qwen3:4b** | 4B | ~2.5GB | 이 하드웨어에서 현실적인 상한선. 답변 품질은 준수하나 토큰 생성이 느림(체감 수 tok/s) — 상호작용용보다는 "정확도 확인용 배치 테스트"에 적합 |
| **qwen3:1.7b** (권장 기본값) | 1.7B | ~1.1GB | 속도와 품질의 균형점. 로컬 개발 중 반복 테스트(청킹/검색 로직 검증)에 가장 적합 |
| **qwen3:0.6b** | 0.6B | ~0.4GB | 가장 빠름. LLM 응답 품질 자체보다 파이프라인 배선(리트리버→프롬프트→출력 포맷)만 빨리 확인하고 싶을 때 |
| **exaone3.5:2.4b** (LG AI Research) | 2.4B | ~1.6GB | 한국어 전용 튜닝 비중이 높아 한국어 자연스러움이 Qwen3 동급 대비 우수할 수 있음. 다만 프롬프트/툴콜 포맷이 Qwen 계열과 달라 서버용 프롬프트를 그대로 재사용하기 어려울 수 있음 — 한국어 답변 품질만 별도로 비교할 때 사용 |

**권장**: 기본 개발용은 `qwen3:1.7b`, 정확도 회귀 테스트(운영 프롬프트와 최대한 동일 조건 유지)가 필요할 때만 `qwen3:4b`로 전환.
Ollama는 GPU가 없으면 자동으로 CPU 백엔드(llama.cpp)로 폴백하므로 코드 변경 없이 모델 태그만 바꾸면 됩니다.

```bash
ollama pull qwen3:1.7b
ollama pull qwen3:0.6b
ollama pull exaone3.5:2.4b   # 한국어 품질 비교용 옵션
```

## 2. 임베딩 모델 대안 (BAAI/bge-m3 대체)

`bge-m3`(약 2.2GB, dense+sparse 동시 지원)는 CPU에서도 동작은 하지만, 문서 대량 업로드 시 청킹당
임베딩 추출이 눈에 띄게 느립니다. 다만 **dense+sparse 동시 지원**은 하이브리드 검색(RRF) 설계의
전제이므로, 대체 모델을 고를 때 이 기능 유무를 반드시 확인해야 합니다.

| 모델 | 크기 | dense+sparse | 비고 |
|---|---|---|---|
| **BAAI/bge-m3** (그대로 유지, 권장) | ~2.2GB | O | 로컬에서는 느리지만 배치(비동기) 처리이므로 실사용상 큰 문제는 아님. 운영과 동일 모델 유지가 검색 품질 회귀를 막는 가장 안전한 선택 |
| `dragonkue/multilingual-e5-small-ko-v2` | ~120MB | X (dense only) | 매우 가볍고 한국어 특화 파인튜닝. **sparse 벡터가 없어 하이브리드 검색 구조를 못 씀** → 검색 로직 자체가 아니라 청킹/OCR 등 다른 파이프라인 단계만 테스트할 때 임시로 쓸 것 |
| `intfloat/multilingual-e5-base` | ~1.1GB | X (dense only) | 위와 동일한 한계. bge-m3보다 가볍지만 sparse 미지원은 동일 |

**권장**: 검색 품질(하이브리드 RRF)을 실제로 검증해야 하는 작업이면 **bge-m3를 그대로 사용**(느려도 CPU에서 완주는 가능).
sparse 벡터가 필요 없는 단순 파이프라인 배선 테스트(OCR→청킹 로직만 확인 등)에 한해서만 e5-small-ko로 임시 교체.

## 3. 리랭커 대안 (BAAI/bge-reranker-v2-m3 대체)

`bge-reranker-v2-m3`는 278M 파라미터의 비교적 가벼운 cross-encoder로, **CPU에서도 실사용 가능한
수준**입니다(배치당 수십 개 후보 기준 체감 지연은 크지 않음). 굳이 바꾸지 않아도 되지만, 더 가볍게 가고
싶다면 아래 옵션이 있습니다.

| 모델 | 크기 | 비고 |
|---|---|---|
| **BAAI/bge-reranker-v2-m3** (유지 권장) | 278M | CPU에서 이미 실용적 속도. 운영과 동일 모델 유지가 리랭킹 결과 재현성 측면에서 가장 안전 |
| `dragonkue/bge-reranker-v2-m3-ko` | 278M | 동일 구조의 한국어 파인튜닝 버전. 한국어 리랭킹 정밀도 비교용으로 시도해볼 수 있음 |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | ~80MB | 훨씬 가볍지만 한국어 학습 비중이 낮아 품질 저하 가능성 큼. 리랭커 유무 자체(on/off)의 파이프라인 영향만 볼 때 임시 사용 |

**권장**: 리랭커는 그대로 `bge-reranker-v2-m3` 유지. 후보 개수(top-k)만 운영보다 줄여서(예: 50→15) CPU
부하를 낮추는 편이 모델을 바꾸는 것보다 안전합니다.

## 4. OCR (PaddleOCR) — 변경 불필요

PaddleOCR은 원래 CPU 추론이 기본이라 GPU 유무와 무관하게 그대로 사용 가능합니다. 단, 저전력 CPU에서는
문서 1페이지당 처리 시간이 운영 서버 대비 훨씬 오래 걸릴 수 있으니:
- 로컬 테스트 시 문서를 전체가 아니라 1~2페이지만 잘라서 넣고 OCR 파이프라인 자체를 검증
- `lang="korean"` 명시는 CPU 환경에서도 동일하게 필수 (CLAUDE.md에 기록된 재발 버그, 모델 교체와 무관)

## 5. 권장 로컬 개발 조합 요약

| 구성요소 | 운영(GPU) | 로컬 개발(CPU, 이 맥북) |
|---|---|---|
| LLM | qwen3:8b / qwen3:4b | **qwen3:1.7b** (기본) / qwen3:4b (정확도 회귀 확인 시) |
| 임베딩 | bge-m3 | **bge-m3 그대로 유지** |
| 리랭커 | bge-reranker-v2-m3 | **bge-reranker-v2-m3 그대로 유지** (top-k만 축소) |
| 벡터DB | Qdrant | Qdrant 그대로 (변경 불필요, CPU에서도 가벼움) |
| RDB | PostgreSQL | PostgreSQL 그대로 |
| OCR | PaddleOCR (korean) | PaddleOCR (korean) 그대로, 테스트 문서만 축소 |

핵심 원칙: **바꿔야 하는 건 LLM 하나뿐**이고, 나머지(임베딩/리랭커/DB/OCR)는 원래도 GPU 필수가 아니므로
그대로 두는 편이 "로컬에서만 재현되는 검색 품질 차이"를 만들지 않아 팀 협업 시 혼선이 적습니다.

## 6. 확인이 필요한 부분

- 팀 확장 시 "로컬 개발 프로파일"을 config로 정식 분리할지(예: `.env.dev-cpu`), 아니면 이 문서만 참고용으로 두고 수동으로 모델 태그를 바꿔 쓸지는 아직 정하지 않았습니다. 정식 분리가 필요하면 별도로 설계 확인 후 진행하겠습니다.
- 위 속도 체감(tok/s 등)은 일반적인 CPU-only Ollama 벤치마크 기준 추정치이며, 이 맥북에서 직접 실측한 값이 아닙니다. 실제로 써보면서 `qwen3:1.7b`도 느리다면 `qwen3:0.6b`로 더 낮추는 걸 권장합니다.

## 7. 실측 기록 — 이 맥북에서 실제로 겪은 문제와 해결 (2026-08-12)

모델 자체를 바꾸는 것 말고도, 이 하드웨어(Intel macOS, GPU 없음)에서 프로젝트를 처음 세팅하면서 실제로 부딪힌 환경 문제들. 다른 팀원이 같은 기종(Intel Mac)에서 세팅할 때 그대로 재발할 수 있어서 남겨둔다.

### 7.1 Docker 인프라

- `docker-compose.yml`의 `ollama` 서비스에 `deploy.resources.reservations.devices: capabilities: [gpu]`가 걸려있어, GPU 없는 이 맥에서 `docker compose up`이 컨테이너를 못 띄울 수 있다. 팀 공용 파일(GPU 서버 기준)은 건드리지 않고, **로컬 전용 `docker-compose.override.yml`**을 만들어 `ollama` 서비스의 `deploy` 키를 무효화했다 (`.gitignore`에도 추가해서 커밋 안 되게 함).
  - 처음엔 `devices: []`(빈 리스트)로 덮어쓰려 했으나, Docker Compose의 병합 규칙상 리스트는 기본적으로 **병합**되지 합쳐지지 않은 채 대체되지 않는다 — 실제로 `docker compose config`로 확인해보니 base 파일의 GPU 예약이 그대로 남아있었다. `deploy: !reset null`(Compose Spec의 명시적 리셋 태그)을 써야 실제로 지워진다는 걸 실측으로 확인.
- 포트 충돌(5432, 11434)이 이 프로젝트가 아니라 **이 맥에서 이미 돌고 있던 다른 프로젝트의 컨테이너**(`rag-postgres`, `rag-ollama` 등, 이미지명으로 봐서 별도 devcontainer 기반 프로젝트) 때문인 경우가 있었다. `docker ps -a`로 먼저 확인하지 않고 포트 재매핑부터 시도했으면 불필요하게 복잡해질 뻔함 — 포트 충돌은 항상 `lsof -nP -iTCP:<port> -sTCP:LISTEN` + `docker ps -a`로 먼저 원인을 확인하고, 무관한 컨테이너면 지우는 쪽이, 이 프로젝트 설정을 포트 재매핑으로 꼬아두는 것보다 간단하다.

### 7.2 Python 환경

- **devcontainer/Dockerfile로 앱을 돌리지 말 것.** CLAUDE.md의 "app은 절대 Docker로 올리지 말 것" 원칙 그대로, 이 맥에서도 로컬 venv(Python 3.11) + `pip install -r requirements.txt` 방식으로 세팅했다. `Dockerfile`이 `python:3.11-slim`을 쓰는 이유(torch/transformers/paddlepaddle 버전 호환 검증)만 참고해서 로컬 venv도 3.11로 맞췄다.
- **`pip install -r requirements.txt`만으로는 부족하다.** `requirements.txt`는 `transformers` 버전을 제한하지 않아서(=`FlagEmbedding`의 의존성으로 딸려 들어오는 최신 버전이 그대로 설치됨) 최신 transformers(5.x)가 깔렸고, 이게 torch>=2.5를 요구해서 `torch`를 "없는 것"으로 취급하는 문제가 생겼다. `Dockerfile`에는 이미 이 문제를 피하려고 `requirements.txt` 설치 뒤에 `pip install "transformers>=4.56,<5.0"`을 따로 한 번 더 실행하는 단계가 있는데, 로컬 venv 세팅 시엔 이 단계가 안내 문서에 없어서 빠뜨리기 쉬웠다. **로컬 세팅 시 반드시 `pip install -r requirements.txt` 다음에 `pip install "transformers>=4.56,<5.0"`을 추가로 실행할 것.**
- **이 맥(Intel, 2018)에서 pip으로 설치 가능한 torch는 2.2.2가 사실상 상한이다.** PyPI가 그 이후 버전부터 Intel macOS(x86_64)용 torch 휠 배포를 중단했기 때문. `requirements-lock.txt`에 적힌 "`setup.ps1`은 CUDA 12.8용 torch 2.11.0을 설치"는 GPU(Windows/CUDA) 환경 얘기라 이 맥엔 해당 안 되고, 이 상한은 앞으로도 바뀌지 않는다(Apple Silicon Mac이면 다를 수 있음, 이건 Intel Mac 한정 얘기).
- 위 torch 상한 때문에 파생되는 문제: transformers의 보안 패치(CVE-2025-32434)가 `.bin`(pickle) 포맷 가중치 로딩 시 torch>=2.6을 강제한다. `BAAI/bge-m3`는 HuggingFace에 `pytorch_model.bin`만 올라와 있고(`model.safetensors` 없음) 이 게이트에 걸려서 로딩이 막혔다. **로컬 1회성 변환 스크립트로 `pytorch_model.bin`을 직접 `torch.load` + `safetensors.torch.save_file`해서 `model.safetensors`를 만들어두면, transformers가 safetensors 경로로 로딩하면서 이 게이트를 안 탄다** (`torch.load`를 우리가 직접 부르는 코드는 transformers의 게이트를 거치지 않기 때문). `BAAI/bge-reranker-v2-m3`는 원본이 이미 `model.safetensors`로 배포돼서 이 문제가 없었다.
- torch import 시 `A module that was compiled using NumPy 1.x cannot be run in NumPy 2.3.5...` 경고가 항상 뜨는데, torch 2.2.2가 numpy 1.x ABI 기준으로 빌드된 반면 프로젝트는 numpy 2.3.5로 고정돼 있어서(GPU 환경의 torch 2.11 기준 검증값) 나오는 것. 지금까지 실행 경로에서는 `UserWarning`일 뿐 실제 크래시로 이어지지 않아 무시 가능했지만, 근본 원인(ABI 불일치)은 실재하므로 원인 불명 크래시가 나면 이걸 의심할 것.
- `EMBEDDING_USE_GPU=true`(`.env` 기본값)는 이 맥에서도 손댈 필요 없음 — 코드가 `torch.cuda.is_available()`을 같이 확인해서 CUDA가 없으면 자동으로 CPU로 폴백한다.
- 리랭커(`bge-reranker-v2-m3`)도 GPU가 없으면 무거운 cross-encoder를 아예 로딩하지 않고 자동으로 "경량 하이브리드 재정렬"로 전환하는 로직이 이미 코드에 있었다 (`app/core/bge_reranker.py`). 설정을 따로 바꿀 필요 없이 실행 로그(`대형 리랭커를 로드하지 않고 경량 하이브리드 재정렬을 사용합니다`)로 확인만 하면 됨.
