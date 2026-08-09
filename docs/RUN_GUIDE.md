# 실행 가이드 (Windows 기준, 실제 검증된 순서)

이 문서는 실제로 이 프로젝트를 처음부터 끝까지 띄우면서 겪었던 문제와 해결책을 그대로 반영한 가이드입니다.
`docs/DECISIONS.md`(스택 결정 이유)와 함께 보세요.

## 방법 A (권장, 유일하게 검증된 경로) — 앱까지 전부 Docker로 실행

`Dockerfile` + `docker-compose.yml`에 Python 버전 충돌, transformers 문제, PaddleOCR API 문제 등을
전부 반영해서 고정해뒀습니다. **venv를 따로 만들 필요가 없습니다** — Docker Desktop만 있으면 됩니다.

참고로 최신 Docker Desktop은 `docker-compose`(하이픈)가 아니라 `docker compose`(띄어쓰기) 명령을 씁니다.

```powershell
cd rag_chatbot_project
copy .env.example .env

# 모델 가중치는 호스트에 받아서 컨테이너에 마운트합니다 (컨테이너 안에서 받는 게 아님)
pip install huggingface_hub
hf download BAAI/bge-m3 --local-dir ./models/bge-m3
hf download BAAI/bge-reranker-v2-m3 --local-dir ./models/bge-reranker-v2-m3

# 전체 스택 빌드 + 기동
docker compose up -d --build
docker compose ps   # app, qdrant, postgres, ollama 4개 모두 Up인지 확인
docker compose logs app --tail 50   # "Application startup complete." 까지 나오는지 확인
```

### GPU 사용 여부에 따라 LLM 크기를 다르게 잡으세요

`docker-compose.yml`의 `app`/`ollama` 서비스에는 GPU 예약 설정이 이미 들어있어서,
NVIDIA GPU가 있으면 Docker Desktop이 자동으로 컨테이너에 GPU를 넘겨줍니다 (별도 툴킷 설치 없이
Windows + WSL2 조합이면 대부분 바로 됩니다). 다만 **VRAM 용량에 맞는 모델 크기를 골라야** 합니다 —
bge-m3(~2.2GB) + bge-reranker-v2-m3(~1.1GB)가 임베딩/리랭킹용으로 항상 GPU에 올라가 있고,
여기에 Ollama LLM이 더해지는 구조라서요.

| GPU VRAM | 권장 LLM 크기 | 비고 |
|---|---|---|
| 8GB (예: RTX 5060 Ti) | `qwen2.5:7b` | 셋 다 합쳐 8GB에 거의 맞음. 이보다 낮춰도(3b) 체감 속도 차이는 거의 없고 품질만 떨어짐 — 실측 확인됨 |
| 6GB 이하 (예: GTX 1060) | `qwen2.5:3b` | 7b는 못 올라갈 가능성이 높음. 1060은 세대가 오래돼(Pascal) fp16 가속도 약해서 GPU 이점 자체가 8GB급보다는 작게 느껴질 수 있음 |
| GPU 없음/CPU만 | `qwen2.5:3b` 이하 권장 | CPU면 7b도 응답까지 꽤 걸림(과거 300초 타임아웃까지 늘렸던 이력 있음) |

```powershell
docker compose exec ollama ollama pull qwen2.5:3b   # PC 사양에 맞는 크기로
notepad .env   # LLM_MODEL_NAME 값을 위에서 받은 크기로 맞추기
docker compose up -d --force-recreate app
```

### 자주 겪었던 문제들 (이 프로젝트에서 실제로 발생했던 것)

- **PaddleOCR 모델이 재빌드할 때마다 다시 다운로드됨** → `docker-compose.yml`에 이미
  `paddlex_models:/root/.paddlex` 볼륨을 넣어뒀습니다. 이게 없으면 `docker compose up --build`를
  할 때마다 11개 모델(수백MB)을 매번 새로 받아서 체감 속도가 크게 느려집니다. 최초 1회만 받고
  이후로는 재사용됩니다.
- **DB 테이블이 없다는 에러** → `main.py`의 `lifespan`에서 앱 시작 시 자동으로 테이블을 생성하도록
  이미 고쳐져 있습니다 (`create_all`). 옛날 코드에는 이게 빠져있어서 업로드가 500 에러로 실패했었습니다.
- **`docker compose up`인데 `unable to get image` / `port already in use`** → Docker Desktop이
  꺼져있거나(먼저 실행), 이전 컨테이너가 포트를 물고 안 놔주는 경우(`docker compose down` 후 재시도)입니다.
- **`.env`를 새로 복사했더니 LLM 모델명이 다시 32b로 돌아옴** → `.env.example`의 기본값이 32b라서
  그렇습니다. `.env`를 새로 만들 때마다 PC 사양에 맞는 크기로 다시 맞춰주세요.

### 새 PC로 옮길 때

1. 프로젝트 폴더 전체(zip)를 새 PC로 복사
2. Docker Desktop 설치
3. `models/` 폴더(bge-m3, bge-reranker-v2-m3 가중치)도 함께 복사하면 재다운로드 불필요
   - 폴더째로 복사하면 되고, 용량이 크면(수GB) USB나 사내 파일서버 경유를 추천합니다
4. `copy .env.example .env` 후 **그 PC의 GPU VRAM에 맞는 `LLM_MODEL_NAME`으로 수정** (위 표 참고)
5. `docker compose up -d --build` — venv, pip install 등 전혀 불필요
6. Ollama 모델은 용량이 커서 보통 재다운로드가 더 빠릅니다. 꼭 옮기고 싶다면 `ollama_data` 볼륨을
   통째로 백업/복원할 수 있습니다:
   ```powershell
   # 기존 PC에서 내보내기
   docker run --rm -v rag_chatbot_project_ollama_data:/data -v ${PWD}:/backup busybox tar czf /backup/ollama_data.tar.gz -C /data .

   # 새 PC에서 불러오기 (먼저 docker compose up -d ollama 한 번 실행해서 볼륨을 만들어둔 뒤)
   docker run --rm -v rag_chatbot_project_ollama_data:/data -v ${PWD}:/backup busybox tar xzf /backup/ollama_data.tar.gz -C /data
   ```
   (볼륨 이름은 `docker volume ls`로 정확한 이름을 먼저 확인하세요 — 폴더명에 따라 접두사가 달라질 수 있습니다.)

## 브라우저 콘솔로 바로 확인하기

`docker compose up`으로 다 띄운 뒤 브라우저에서 그냥 열면 됩니다 (curl/PowerShell 인코딩 문제 없이
질문·파일 업로드를 바로 할 수 있는 화면입니다):

```
http://localhost:8000
```

## 방법 B — 호스트에 직접 설치 (참고용 기록, 지금은 안 씀)

## 0. Docker Desktop 준비

```powershell
# Windows 기능 확인 (관리자 권한 PowerShell)
Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux

# 둘 다 Enabled가 아니면 아래 실행 후 재부팅
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
Restart-Computer

# 재부팅 후 확인
wsl --status
```

Docker Desktop 설치 후 앱을 실행해서 트레이 아이콘이 정상 상태가 될 때까지 기다립니다.

## 1. Python 3.11 가상환경 만들기

**중요**: Python 3.14는 이 프로젝트의 여러 패키지(tokenizers, paddleocr 등)가 아직 지원하지 않아 컴파일 오류가 납니다. 반드시 3.11을 쓰세요.

```powershell
py install 3.11
cd C:\Users\mesul\Downloads\rag_chatbot_project
py -3.11 -m venv venv
venv\Scripts\Activate.ps1
python --version   # Python 3.11.x 인지 확인
```

## 2. 패키지 설치 (버전 고정 포함)

실제로 이 조합이라야 충돌 없이 돌아갑니다.

```powershell
$env:PYTHONUTF8="1"   # requirements.txt 안 한글 주석 인코딩 오류 방지

pip install -r requirements.txt
pip install "transformers>=4.56,<5.0" --force-reinstall   # bge-m3/reranker와 호환되는 버전대
pip install sentencepiece protobuf                         # XLM-RoBERTa 토크나이저 필수 의존성
pip install python-multipart                                # PDF 파일 업로드(UploadFile)에 필수
pip install pymupdf                                          # PDF 텍스트 추출

# 표 추출(PaddleOCR) 관련
pip install -r app\services\table_extraction\requirements.txt
pip install "paddlex[ocr]"                                   # PPStructureV3 필수 부가 의존성
pip install paddlepaddle==3.2.2 --force-reinstall            # 3.3.x는 oneDNN 버그로 CPU 추론 실패
```

## 3. `.env` 파일 만들기

```powershell
copy .env.example .env
```

로컬 테스트 시 대부분 기본값(`localhost`) 그대로 두면 됩니다.

## 4. 인프라(Qdrant / PostgreSQL / Ollama) 기동

```powershell
docker-compose up -d qdrant postgres ollama
docker-compose ps   # 3개 다 Up 상태인지 확인
```

## 5. Ollama에 LLM 모델 받기

**주의**: GPU가 안 잡히는 환경에서 32B 모델은 CPU 메모리 부족(OOM)으로 실패합니다. 7B로 시작하세요.

```powershell
docker-compose exec ollama ollama pull qwen2.5:7b
docker-compose exec ollama ollama list   # 잘 받아졌는지 확인
```

`.env`의 `LLM_MODEL_NAME=qwen2.5:7b` 로 맞춰주세요.

## 6. 임베딩/리랭커 모델 받기

```powershell
hf download BAAI/bge-m3 --local-dir ./models/bge-m3
hf download BAAI/bge-reranker-v2-m3 --local-dir ./models/bge-reranker-v2-m3
```

(`huggingface-cli`는 최신 버전에서 사라졌고 `hf` 명령으로 대체되었습니다.)

## 7. 서버 실행

```powershell
uvicorn app.main:app --port 8000
```

`Application startup complete.`까지 에러 없이 나오면 성공입니다.
(`--reload` 옵션은 파일 변경 감지 중 간헐적으로 재시작이 꼬이는 걸 겪었어서, 안정적으로 테스트할 때는 빼고 쓰는 걸 추천합니다.)

## 8. 테스트 (PowerShell 한글 인코딩 우회 함수 포함)

PowerShell 5.1의 `Invoke-RestMethod`는 한글을 보내고 받을 때 인코딩이 깨지는 버그가 있어, 아래 함수를 매 세션 처음에 한 번 정의해두고 쓰는 걸 권장합니다.

```powershell
function Ask-Chatbot {
    param([string]$Question)
    $body = @{question=$Question} | ConvertTo-Json -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)

    $request = [System.Net.WebRequest]::Create("http://localhost:8000/api/chat")
    $request.Method = "POST"
    $request.ContentType = "application/json; charset=utf-8"
    $request.ContentLength = $bytes.Length
    $stream = $request.GetRequestStream()
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Close()

    $response = $request.GetResponse()
    $reader = New-Object System.IO.StreamReader($response.GetResponseStream(), [System.Text.Encoding]::UTF8)
    $result = $reader.ReadToEnd()
    $reader.Close()
    return $result
}
```

**텍스트로 바로 문서 넣기:**
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/documents/ingest" -Method Post -ContentType "application/json" -Body '{"document_id": "doc-1", "text": "테스트 문서 내용입니다."}'
```

**PDF 파일로 문서 넣기 (스캔본/디지털 텍스트 자동 판별):**
```powershell
curl.exe -X POST "http://localhost:8000/api/documents/ingest/pdf?document_id=test-pdf-1" -F "file=@내문서.pdf;type=application/pdf"
```

**질문하기 (한글 깨짐 없이):**
```powershell
Ask-Chatbot -Question "이 문서 내용 요약해줘"
```

## 문제 생겼을 때 체크리스트

| 증상 | 원인 | 해결 |
|---|---|---|
| `python`/`pip` 명령이 안 먹힘 | venv 비활성 상태 | `venv\Scripts\Activate.ps1` 먼저 실행 |
| tokenizers 빌드 실패(Rust 컴파일 에러) | Python 3.14 사용 중 | 3.11로 재구성 |
| `XLMRobertaTokenizer has no attribute prepare_for_model` | transformers 버전이 너무 최신(5.x) | `transformers<5.0,>=4.56`으로 재설치 |
| `XLMRobertaModel.__init__() got unexpected keyword argument 'dtype'` | transformers 버전이 너무 예전(4.46 이하) | 위와 동일하게 4.56 이상으로 재설치 |
| Ollama `500`, `llama-server process has terminated: signal: killed` | 모델이 GPU 없이 CPU로 로딩되며 메모리 부족 | 더 작은 모델(7B 등)로 전환 |
| `ConvertPirAttribute2RuntimeAttribute not support` | paddlepaddle 3.3.x의 oneDNN 버그 | `paddlepaddle==3.2.2`로 다운그레이드 |
| `Form data requires "python-multipart"` | PDF 업로드 의존성 누락 | `pip install python-multipart` |
| 한글 응답이 깨져서 보임 | PowerShell 콘솔/Invoke-RestMethod 인코딩 버그 | 위 `Ask-Chatbot` 함수 사용 |
