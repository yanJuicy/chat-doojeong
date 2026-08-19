"""
프로젝트 전체 환경설정 (Pydantic Settings).
각 서브모듈(table_extraction 등)은 자체 설정을 가질 수 있으며, 이 파일은 앱 공통 설정만 관리한다.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM (Ollama 서빙) ---
    llm_provider_base_url: str = "http://localhost:11434"
    llm_model_name: str = "qwen3:8b"
    llm_think: bool = False  # 사실 기반 RAG에서는 내부 사고 토큰을 끄면 정확도 손실 없이 지연이 크게 줄어듦
    llm_temperature: float = 0.1
    llm_top_p: float = 0.9
    llm_num_ctx: int = 4096
    llm_num_predict: int = 768
    llm_keep_alive: str = "10m"

    # --- 임베딩 ---
    embedding_model_dir: str = "./models/bge-m3"
    embedding_use_gpu: bool = True

    # --- 리랭커 ---
    reranker_model_dir: str = "./models/bge-reranker-v2-m3"
    reranker_top_k: int = 5  # 1차 검색 결과 중 최종적으로 남길 개수

    # --- 벡터DB (Qdrant) ---
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection_name: str = "documents"

    # --- RDB (PostgreSQL) ---
    postgres_dsn: str = "postgresql+asyncpg://user:password@localhost:5432/ragdb"

    # --- 청킹 ---
    chunk_similarity_threshold: float = 0.55  # 최소 길이를 채운 뒤 주제가 실제로 바뀔 때만 분할
    chunk_min_tokens: int = 128  # 지나치게 짧은 50~100자 청크가 쏟아지는 것을 방지
    chunk_max_tokens: int = 512

    # --- 워커 실패 복구 ---
    worker_max_retries: int = 3  # 이 횟수를 넘게 실패하면 더 이상 자동 재시도 안 하고 FAILED로 확정
    worker_claim_batch_size: int = 4  # 워커 하나가 한 번에 찜할 문서 수. 여러 워커가 일을 나눠 갖게 한다.
    pipeline_round_document_limit: int = 16  # 추출→청킹→임베딩 한 순환의 문서 상한. Qwen 재로딩과 대기시간의 균형값.
    embedding_claim_batch_size: int = 32  # 실제 인코딩 1배치와 같게 유지해 중간 커밋 후 중복 선점을 방지
    worker_stale_after_minutes: int = 30  # 이 시간 동안 진행률 갱신이 없던 EXTRACTING 작업은 자동 회수

    # --- 검색 ---
    reranker_enabled: bool = True  # 저사양 GPU에서 끄면 추론 1회를 아낄 수 있음 (지금 하드웨어는 충분해서 기본 켬)

    # --- 적응형 후보군 필터링 (고정 top_k 대신, 유사도 분포를 보고 후보 개수를 조정) ---
    adaptive_retrieval_fetch_pool: int = 64  # 리랭킹 24개를 보호·병합하기에 충분한 1차 후보 풀
    adaptive_retrieval_max: int = 24  # 전역 100개 중 보호·병합된 상위 후보만 교차인코더로 재평가
    adaptive_retrieval_max_cpu: int = 16  # 568M 교차인코더를 CPU에서 48개 돌리면 수분이 걸려 자동 축소
    adaptive_retrieval_floor_similarity: float = 0.20  # 낮은 OCR 표현도 리랭커가 살릴 수 있게 보수적으로 완화
    retrieval_max_chunks_per_document: int = 3  # 한 문서가 최종 근거를 독점하지 않도록 제한

    # --- 검색 힌트 ---
    explicit_label_boost_weight: float = 0.04  # 회사 라벨 하나가 검색을 지배하지 않는 약한 힌트
    exact_identifier_boost_weight: float = 0.15  # 정확한 모델명·인증번호는 일반 라벨보다 강하게 우선
    query_expansion_enabled: bool = True  # 과정↔공정, 용도↔기능 등 보수적인 검색어 확장

    # --- 라벨 자동화 ---
    auto_generate_labels_enabled: bool = True  # 라벨이 전혀 없는 문서에 검색 라벨을 생성
    auto_enrich_labels_enabled: bool = True  # 라벨이 1~2개뿐이면 회사/모델/주제/문서종류 축을 보충
    auto_label_min_count: int = 3
    auto_label_max_count: int = 6
    auto_reclassify_labels_enabled: bool = False  # 사람 라벨의 자동 교체/삭제는 오분류 위험 때문에 기본 비활성화

    # --- 질문 캐싱 ---
    question_cache_max_size: int = 200  # 메모리 캐시에 유지할 최대 질문 개수
    question_cache_ttl_hours: int = 48  # 마지막 사용 후 만료되는 sliding TTL (보수적으로 2일)
    question_cache_similarity_threshold: float = 0.92  # 후보 탐색용; 아래 안전조건까지 모두 맞아야 재사용

    # --- OCR (스캔본 PDF) ---
    scan_render_dpi: int = 200  # 300에서 낮춤 - 픽셀수가 약 44%로 줄어 OCR 시간 크게 단축 (인증서/도면류는 상향 권장)
    pdf_digital_min_chars: int = 20  # 이보다 짧은 네이티브 텍스트는 이미지 점유율과 함께 추가 판정
    pdf_native_quality_min_score: float = 0.20  # 텍스트 레이어가 길어도 깨진 결과면 OCR로 전환
    pdf_mixed_image_coverage: float = 0.55  # 페이지에서 큰 이미지가 이 비율 이상이면 혼합 페이지 후보
    pdf_mixed_max_native_chars: int = 400  # 제목 수준 텍스트+큰 이미지일 때 이미지 내부 OCR 병행
    pdf_native_table_detection_enabled: bool = True  # 디지털 텍스트 페이지에서도 find_tables()로 표 격자를 감지해 TABLE_BLOCK으로 보존
    ocr_table_detection_enabled: bool = True  # 켜면 표가 있어 보이는 페이지만 무거운 PPStructureV3, 나머지는 경량 OCR
    ocr_page_cache_enabled: bool = True  # 같은 파일(해시)+같은 페이지+같은 DPI를 재처리할 때 OCR을 다시 안 돌림
    ocr_cache_dir: str = "./uploaded_files/ocr_cache"  # 페이지 OCR 결과 캐시 저장 위치
    ocr_quality_gate_enabled: bool = True  # 저품질 OCR 결과가 청킹/임베딩으로 넘어가지 않게 차단
    ocr_quality_min_score: float = 0.45  # 이미지/PDF 전체 추출 품질 하한
    ocr_fallback_min_score: float = 0.60  # 페이지 OCR이 이 점수보다 낮으면 다른 OCR 경로를 추가 시도

    # --- 이미지 캡셔닝 (Vision-LLM, 선택 사항) ---
    direct_image_captioning_enabled: bool = True  # 직접 업로드한 이미지의 도식·사진 관계를 VLM으로 보강
    pdf_image_captioning_enabled: bool = False  # 수백 페이지 PDF 삽화를 전부 VLM 처리하는 비용은 기본 차단
    vlm_provider_base_url: str = "http://localhost:11434"
    vlm_model_name: str = "qwen3-vl:2b-instruct"
    vlm_keep_alive: str = "2m"  # 이미지 여러 장 연속 재처리 때 매번 3.2GB 모델을 다시 읽지 않음
    image_storage_dir: str = "./uploaded_files/images"  # 추출된 이미지 저장 위치 (정적 서빙 경로와 연결됨)

    # --- 업로드 안전장치 ---
    max_upload_size_mb: int = 200  # 파일 하나(또는 zip 안 파일 하나)당 최대 크기
    max_zip_total_uncompressed_mb: int = 1000  # zip 안 파일들의 압축 해제 후 총 용량 상한 (zip bomb 방지)


settings = Settings()
