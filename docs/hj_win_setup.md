# hj 개인 Windows + Zed devcontainer 세팅

이 문서는 hj가 개인 Windows PC(Zed 에디터, GPU: GTX 1650 4GB)에서 이 프로젝트를
작업하기 위해 만든 devcontainer 세팅 기록이다. `.devcontainer/`는 개인 설정이라
`.gitignore` 처리했고, 팀 공유 파일(`docker-compose.yml`, `Dockerfile`, `app/` 이하 코드)은
전혀 수정하지 않았다.

## 왜 devcontainer인가

호스트 Windows에는 이미 Python 3.10(scoop)이 설치돼 있어서, 프로젝트가 요구하는
Python 3.11을 호스트에 또 설치하면 충돌 위험이 있었다. devcontainer로 프로젝트 전용
Python 3.11 환경을 컨테이너 안에만 격리하고, 호스트는 건드리지 않는 방식을 택했다.

## 구성 파일 (개인 전용, git에 안 올라감)

- `.devcontainer/devcontainer.json`
- `.devcontainer/docker-compose.override.yml` — 기존 `docker-compose.yml`에
  `devcontainer`라는 서비스 하나만 추가. `qdrant`/`postgres`/`ollama`는 기존 서비스를
  그대로 재사용(서비스 이름으로 접속). GPU 예약, `paddlex_models` 볼륨 재사용 포함.

주의: `.env`의 상대 경로(`context: .`, 볼륨 `.:/app`)는 **repo 루트 기준**으로 써야 한다.
Docker Compose가 여러 `-f` 파일을 합칠 때 상대 경로를 override 파일 자신의 위치가 아니라
첫 번째 `-f` 파일(=repo 루트의 `docker-compose.yml`) 기준으로 해석하기 때문에, `..`를 쓰면
repo 상위 폴더를 잘못 참조하게 된다 (실제로 이 문제로 빌드가 한 번 실패했었음).

## 사용법

1. Zed에서 프로젝트를 열면 뜨는 "Reopen in Container" 팝업을 클릭한다.
2. 컨테이너 터미널에서:
   ```bash
   alembic upgrade head
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   (`--reload`는 기존 프로젝트 원칙대로 쓰지 않는다 — OCR 캐시 무한 재시작 문제.)

## 호스트에 없는 것 준비 (models/, .env — 둘 다 gitignore됨)

```powershell
Copy-Item .env.example .env
```

`models/bge-m3`, `models/bge-reranker-v2-m3`는 HuggingFace 공개 모델이라 컨테이너
안에서 직접 받을 수 있다 (팀 전용 비공개 번들 아님):

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-m3', local_dir='./models/bge-m3')"
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-reranker-v2-m3', local_dir='./models/bge-reranker-v2-m3')"
```

Ollama LLM은 호스트 PowerShell에서:
```powershell
docker compose exec ollama ollama pull qwen3:4b-instruct
```

## 중요 발견: qwen3 "사고 과정" 모델을 쓰면 답변이 비정상적으로 느려짐 (팀 공유 필요)

**증상**: 3문장짜리 짧은 답변 요청에 30초~300초 이상 걸림. GPU 성능 문제가 아니었음.

**원인 (실측 확인)**: 기본으로 받는 `qwen3:4b`, `qwen3:8b` 같은 태그는 "사고 과정
켜고 끄기"가 가능한 하이브리드(thinking) 체크포인트다. `app/core/qwen_ollama_provider.py`가
이 사고 과정을 끄려고 프롬프트 끝에 `/no_think`를 붙이는 우회법을 쓰고 있는데, 이번에
Ollama 0.32.1 + `qwen3:4b` 조합에서 다음 세 가지 방법을 다 실측 테스트했고 전부 실패했다.

| 방법 | 결과 |
|---|---|
| 프롬프트 끝에 `/no_think` (기존 코드 방식) | 실패 — 2882 토큰까지 혼잣말 |
| `/api/chat` + `think: false` | 실패 — 695 토큰, `</think>` 그대로 존재 |
| `raw: true` + 어시스턴트 답변란에 빈 `<think></think>` 미리 채워넣기 | 실패 — 431 토큰, 모델이 새로 사고 시작 |

**해결책**: Ollama 라이브러리에 애초에 사고 과정이 없는 전용 instruct 체크포인트가
따로 있다 — `qwen3:4b-instruct` (2.5GB). 이걸로 바꾸면 아무 트릭 없이도 바로 답변만
나온다 (실측: 89토큰, 13.3초, `<think>` 흔적 없음).

**적용한 조치**: `.env`의 `LLM_MODEL_NAME=qwen3:4b-instruct`로 변경. **코드는 전혀
수정하지 않았다** — 순수하게 pull 받는 모델 태그를 바꾼 것뿐이다.

**다른 팀원 확인 필요**: 다른 PC에서 `qwen3:8b`(하이브리드) 그대로 쓰고 있다면 동일하게
답변마다 불필요한 시간을 낭비하고 있을 가능성이 높다. Ollama 라이브러리에
`qwen3:8b-instruct` 태그가 있는지 확인하고 있으면 교체를 권장한다.

## GPU 메모리 참고 (4GB 카드 기준)

`qwen3:4b-instruct` + `EMBEDDING_USE_GPU=true` + 리랭커까지 다 GPU에 올린 상태로
단일 질문 기준 VRAM 약 3.8/4.1GB 사용, 정상 응답 확인됨. 다만 여유가 300MB 수준으로
빠듯하다. 문서를 대량 업로드해서 청킹/임베딩이 배치로 몰릴 때는 VRAM이 부족해질 수
있으니, 그런 경우 `.env`의 `EMBEDDING_USE_GPU=false`로 내려서 임베딩을 CPU로 돌리면
LLM 쪽에 여유를 더 줄 수 있다.

## 기타

- `frontend/`는 npm이 아니라 **pnpm**을 쓴다 (`frontend/pnpm-lock.yaml`이 정식 lock
  파일). 실수로 `npm install`을 돌리면 `package-lock.json`이 새로 생기면서 lock 파일이
  꼬일 수 있으니 지우고 `pnpm install`로 다시 설치할 것.
