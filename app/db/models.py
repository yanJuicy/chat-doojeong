"""
SQLAlchemy 모델 (PostgreSQL, 비동기 asyncpg 드라이버 사용 전제).

설계 원칙 (DB 중심 아키텍처):
  OCR/청킹/임베딩 각 단계는 서로를 함수 호출로 직접 알지 못한다.
  대신 Document.status를 거쳐가며, 각 워커(app/workers/*)가 자기 단계의 상태만 보고
  DB를 읽고 쓴다. 그래서 한 단계(예: OCR 엔진)를 통째로 교체해도
  다른 단계는 코드를 한 줄도 고칠 필요가 없다 — DB 스키마(계약)만 지키면 된다.

  status 흐름: uploaded -> extracted -> chunked -> ready (실패 시 failed)
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# document_types.id 시드 값. 마이그레이션(0012_unify_documents.py)의 시드와 반드시 일치해야 한다.
# 새 문서 유형이 필요하면: (1) document_types에 행 추가 + (2) 여기 상수 + (3) Document 서브클래스
# 하나만 추가하면 된다 — 새 SQL 테이블은 필요 없다 (docs/DB_확장_구조_설계초안.md 참고).
RAG_UPLOAD_TYPE_ID = 1
WEEKLY_REPORT_ENTRY_TYPE_ID = 2
WEEKLY_REPORT_SOURCE_TYPE_ID = 3


class DocumentType(Base):
    """문서 유형 lookup 테이블. 새 유형 추가 = 이 테이블에 행 INSERT (스키마 변경 없음)."""

    __tablename__ = "document_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)


class DocumentStatus(str, enum.Enum):
    """문서가 파이프라인의 어느 단계까지 처리됐는지를 나타내는 상태.
    각 워커는 자기 담당 상태의 문서만 조회해서 처리하고 다음 상태로 넘긴다."""

    UPLOADED = "uploaded"      # 파일만 저장됨, 아직 텍스트 추출 전 (extraction_worker 대상)
    EXTRACTING = "extracting"  # 추출(OCR 포함) 진행 중 — 이 상태인 동안은 잠금 없이 오래 걸리는 작업을 함
    NEEDS_REVIEW = "needs_review"  # 추출은 끝났지만 OCR 품질이 낮아 사람 확인/재처리가 필요함
    EXTRACTED = "extracted"    # OCR/텍스트 추출 완료, 청킹 전 (chunking_worker 대상)
    CHUNKED = "chunked"        # 청킹 완료, 임베딩 전 (embedding_worker 대상)
    READY = "ready"            # 임베딩까지 완료, 검색 가능한 상태
    FAILED = "failed"          # 어느 단계에서든 실패 (error_message 참고)


class Document(Base):
    """
    모든 문서 유형(RAG 업로드, 주간보고서 항목, 주간보고서 원본 PDF, ...)을 담는 통합 테이블.
    document_type_id로 유형을 구분하고(document_types 참고), 유형별 서브클래스
    (RagUploadDocument/WeeklyReportEntry/WeeklyReportSource, 아래)를 통해 조회한다.

    **주의**: 이 기본 클래스로 직접 `select(Document)`를 하면 모든 유형이 섞여서 나온다.
    RAG 업로드 문서만 다루는 코드(문서관리 목록, 중복 정리, 재추출 등)는 반드시
    `select(RagUploadDocument)`처럼 서브클래스로 조회해서 다른 유형이 섞이는 걸 막는다 —
    SQLAlchemy가 polymorphic_identity로 자동 필터링해준다(수동 WHERE 필요 없음).
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_type_id: Mapped[int | None] = mapped_column(ForeignKey("document_types.id"), nullable=True, index=True)

    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)  # 원본 파일 저장 위치 (extraction_worker가 읽는 경로)
    file_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # sha256, 동일 파일 재업로드 감지용
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 검색용 본문 — RAG 업로드=OCR 추출문, 생성형=템플릿 요약
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # status=FAILED일 때 원인
    warning_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # 실패는 아니지만 청킹 품질 등에서 감지된 이상 징후
    retry_count: Mapped[int] = mapped_column(default=0)  # 실패 후 자동/수동 재시도된 횟수 (max_retries 넘으면 FAILED로 확정)
    current_page: Mapped[int | None] = mapped_column(nullable=True)  # 추출(OCR) 진행률 - 지금 처리 중인 페이지
    total_pages: Mapped[int | None] = mapped_column(nullable=True)  # 추출(OCR) 진행률 - 전체 페이지 수
    extraction_quality_score: Mapped[float | None] = mapped_column(nullable=True)
    extraction_quality_details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 진단값
    extraction_method: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # raw_text의 SHA256, 자동 중복 감지용
    pipeline_version: Mapped[str | None] = mapped_column(String, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- weekly_report_entry에서 검증된 컬럼. 다른 유형은 같은 개념이 있을 때만 재사용, 없으면 NULL
    #     (docs/DB_확장_구조_설계초안.md 2-3 참고 — "모든 유형 공통"이 아니라 선택적 컬럼) ---
    subject: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # 부서명/거래처명 등
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 검색/미리보기용 요약 문장

    # --- 생성형 문서(chat/document 입력) 전용 ---
    source: Mapped[str | None] = mapped_column(String, nullable=True)  # "chat" | "document"
    source_document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- 그 유형에만 있는 구조 필드 (예: entry_type, items, total_amount 등) ---
    type_specific_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")
    labels: Mapped[list["DocumentLabel"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __mapper_args__ = {"polymorphic_on": document_type_id}


class RagUploadDocument(Document):
    """사용자가 업로드해서 OCR/청킹/임베딩 파이프라인을 타는 일반 RAG 문서. 지금까지의 Document와 동일."""

    __mapper_args__ = {"polymorphic_identity": RAG_UPLOAD_TYPE_ID}


class WeeklyReportEntry(Document):
    """
    주간(추후 월간도 가능) 업무보고 원자료 항목 하나. 채팅으로 직접 입력하거나 기존
    보고서 문서(표)를 업로드해서 추출한 뒤, 정제(문체 정규화)를 거쳐 여기 저장된다.
    이전의 별도 work_report_entries 테이블을 대체 — 이 행 자체가 검색 가능한 Document라서
    별도 "그림자 문서" 복제가 필요 없다.

    "구분"(사업/관리/시군특화... 등 원본 문서마다 다를 수 있는 값)은 고정 enum으로
    만들지 않는다. 최종 보고서를 뽑을 타겟 양식의 구분 체계가 원본과 다를 수 있어서
    (예: 원본은 구분 3개, 타겟 양식은 구분 1개), 저장 시점엔 type_specific_data.source_category에
    원본 표기를 느슨한 태그로만 보존하고, 실제로 어느 칸에 넣을지는 보고서 생성 시점에
    타겟 양식을 보고 결정한다.

    subject=부서명, period_start/end=보고 기간, content=정제된 최종 문장(공통 컬럼 사용).
    entry_type/source_category/source_format은 이 유형에만 있는 필드라 type_specific_data에.
    """

    __mapper_args__ = {"polymorphic_identity": WEEKLY_REPORT_ENTRY_TYPE_ID}

    def __init__(
        self,
        *,
        id: str,
        department: str,
        entry_type: str,
        period_start: date,
        period_end: date,
        content: str,
        source: str,
        source_category: str | None = None,
        source_document_id: str | None = None,
        raw_input: str | None = None,
        source_format: str | None = None,
    ) -> None:
        # 옛 WorkReportEntry(department=.., entry_type=.., ...) 생성자와 동일한 키워드를 받는다 —
        # 호출부(work_reports.py)는 안 바뀌고, 내부적으로만 subject/type_specific_data로 매핑한다.
        super().__init__(
            id=id,
            filename=f"주간보고_{department}_{period_start.isoformat()}",
            subject=department,
            period_start=period_start,
            period_end=period_end,
            content=content,
            source=source,
            source_document_id=source_document_id,
            raw_input=raw_input,
            type_specific_data={
                "entry_type": entry_type,
                "source_category": source_category,
                "source_format": source_format,
            },
        )

    # hybrid_property: 인스턴스에서 entry.department처럼 읽고 쓸 수 있으면서, 동시에
    # select(WeeklyReportEntry.department)/.where(...)/.order_by(...)처럼 클래스 레벨 쿼리
    # 표현식으로도 그대로 쓸 수 있다 (plain @property는 인스턴스에서만 동작해서 쿼리에 못 씀).
    @hybrid_property
    def department(self) -> str | None:
        return self.subject

    @department.setter
    def department(self, value: str) -> None:
        self.subject = value

    @department.expression
    def department(cls):  # noqa: N805 — SQLAlchemy hybrid_property 관례
        return cls.subject

    @hybrid_property
    def entry_type(self) -> str | None:
        return (self.type_specific_data or {}).get("entry_type")

    @entry_type.setter
    def entry_type(self, value: str) -> None:
        self.type_specific_data = {**(self.type_specific_data or {}), "entry_type": value}

    @entry_type.expression
    def entry_type(cls):  # noqa: N805
        return cls.type_specific_data["entry_type"].astext

    @property
    def source_category(self) -> str | None:
        return (self.type_specific_data or {}).get("source_category")

    @source_category.setter
    def source_category(self, value: str | None) -> None:
        self.type_specific_data = {**(self.type_specific_data or {}), "source_category": value}

    # source=document일 때만 채워짐. 원본 표 셀에서 이 항목이 어떤 표현 형식으로 쓰여
    # 있었는지(report_table_parser가 정규식으로 감지) — "bullet:•", "bullet:-"처럼 글머리
    # 기호를 썼으면 그 기호를, 기호 없이 문장 하나로 쓰여 있었으면 "prose"를 저장한다.
    # 최종 보고서 DOCX를 만들 때 이 부서의 원본 문서가 쓰던 표현 형식을 그대로 재현하는 데 쓴다
    # (weekly_report_composer.detect_department_format 참고). weekly_report_composer가
    # select(...source_format)으로 조회하므로 이것도 hybrid_property로 둔다.
    @hybrid_property
    def source_format(self) -> str | None:
        return (self.type_specific_data or {}).get("source_format")

    @source_format.setter
    def source_format(self, value: str | None) -> None:
        self.type_specific_data = {**(self.type_specific_data or {}), "source_format": value}

    @source_format.expression
    def source_format(cls):  # noqa: N805
        return cls.type_specific_data["source_format"].astext


class WeeklyReportSource(Document):
    """
    주간보고서 작성용으로 업로드된 원본 PDF 파일 1건. WeeklyReportEntry.source_document_id가
    가리키는 대상. 검색 대상이 아니라 표 데이터 추출용 원본 보관이 목적이라
    OCR/청킹/임베딩 파이프라인을 타지 않는다(raw_text 비워둠).
    subject=부서명(공통 컬럼 재사용). pages_with_table 등 이 유형에만 있는 통계는
    type_specific_data에.
    """

    __mapper_args__ = {"polymorphic_identity": WEEKLY_REPORT_SOURCE_TYPE_ID}

    def __init__(
        self,
        *,
        id: str,
        filename: str,
        file_path: str,
        department: str | None = None,
        pages_with_table: int = 0,
        pages_without_table: int = 0,
        entries_created: int = 0,
    ) -> None:
        # 옛 WorkReportDocument(...) 생성자와 동일한 키워드를 받는다 (호출부 변경 최소화).
        super().__init__(
            id=id,
            filename=filename,
            file_path=file_path,
            subject=department,
            status=DocumentStatus.READY,  # 검색 파이프라인을 안 타므로 처리 대기 상태로 두지 않는다
            type_specific_data={
                "pages_with_table": pages_with_table,
                "pages_without_table": pages_without_table,
                "entries_created": entries_created,
            },
        )

    @property
    def department(self) -> str | None:
        return self.subject

    @department.setter
    def department(self, value: str | None) -> None:
        self.subject = value

    @property
    def pages_with_table(self) -> int:
        return (self.type_specific_data or {}).get("pages_with_table", 0)

    @pages_with_table.setter
    def pages_with_table(self, value: int) -> None:
        self.type_specific_data = {**(self.type_specific_data or {}), "pages_with_table": value}

    @property
    def pages_without_table(self) -> int:
        return (self.type_specific_data or {}).get("pages_without_table", 0)

    @pages_without_table.setter
    def pages_without_table(self, value: int) -> None:
        self.type_specific_data = {**(self.type_specific_data or {}), "pages_without_table": value}

    @property
    def entries_created(self) -> int:
        return (self.type_specific_data or {}).get("entries_created", 0)

    @entries_created.setter
    def entries_created(self, value: int) -> None:
        self.type_specific_data = {**(self.type_specific_data or {}), "entries_created": value}

    @property
    def uploaded_at(self) -> datetime:
        return self.created_at


class DocumentLabel(Base):
    """
    문서에 붙는 "어디의 무엇" 라벨. documents.source_label(문서당 하나) 대신 별도 테이블로 뺐다 —
    실제로는 문서 하나가 "두정테크"이면서 동시에 "용접방식"이기도 한 것처럼, 회사(누구)와
    주제(뭐에 대한 건지) 등 여러 라벨을 동시에 가지는 경우가 자연스럽다.
    """

    __tablename__ = "document_labels"
    __table_args__ = (UniqueConstraint("document_id", "label", name="uq_document_labels_document_label"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    label: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="labels")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    is_table: Mapped[bool] = mapped_column(default=False)
    table_confidence: Mapped[float | None] = mapped_column(nullable=True)  # 표 청크의 행별 열개수 일관성 비율
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)  # 이미지 캡션 청크인 경우 원본 이미지 경로
    embedded: Mapped[bool] = mapped_column(Boolean, default=False)  # embedding_worker가 처리 완료 시 True로 표시
    embed_retry_count: Mapped[int] = mapped_column(default=0)  # 이 청크의 임베딩이 실패해서 재시도된 횟수
    parent_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Parent-Child 청킹: 이 청크(자식)가 속한 더 큰 맥락(부모). 검색은 text로, 답변 생성 시 맥락은 이걸로.

    document: Mapped["Document"] = relationship(back_populates="chunks")


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_language: Mapped[str | None] = mapped_column(String, nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    """
    멀티턴 대화 세션 하나. FE가 새 대화를 시작할 때 UUID를 만들어 이 id로 쓴다.
    이 프로젝트엔 로그인이 없어서 "누구의 세션인지"는 구분하지 않는다 — 이 id를
    아는 클라이언트가 그 대화의 주인이라고 취급한다(사내 폐쇄망이라 감수하는 리스크).
    """

    __tablename__ = "chat_sessions"

    # FE(crypto.randomUUID() 기반)가 만든 값을 그대로 PK로 쓴다. 서버가 별도로 발급하지
    # 않고, 처음 보는 id로 메시지가 들어오면 그 자리에서 새로 생성한다(get-or-create).
    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 새 turn이 저장될 때마다 갱신된다. 지금은 안 쓰지만, 나중에 "최근 대화 목록"을
    # 만들 때 정렬 기준으로 쓸 수 있어서 미리 남겨둔다.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    turns: Mapped[list["ChatTurn"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatTurn(Base):
    """
    ChatSession 안의 발화 하나 (사용자 질문 1개 또는 챗봇 답변 1개 = 각각 별도 행).
    멀티턴 질문 재작성(이전 대화를 보고 "그럼 무게는?"을 "RB-Y1의 무게는?"으로
    바꾸는 것)의 재료가 되는 이력이 여기 쌓인다.
    """

    __tablename__ = "chat_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)

    # "user" 또는 "assistant" — 재작성 프롬프트를 만들 때 누가 한 말인지 구분해야 해서 필요.
    role: Mapped[str] = mapped_column(String)

    # role=user면 사용자가 실제로 입력한 원문 그대로("그럼 무게는?").
    # role=assistant면 최종 답변 전문.
    content: Mapped[str] = mapped_column(Text)

    # role=user인 행에만 채워진다 — 질문 재작성이 실제로 검색에 넘긴 standalone 질문
    # ("RB-Y1의 무게는?"). 재작성이 안 일어났으면(첫 질문/이미 완결된 질문/재작성 실패)
    # None으로 남겨서, 나중에 "왜 이런 검색 결과가 나왔는지" 원인 추적에 쓴다.
    rewritten_question: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="turns")


# WorkReportEntry/WorkReportDocument는 위 WeeklyReportEntry/WeeklyReportSource로 통합됐다
# (docs/DB_확장_구조_설계초안.md, migrations/versions/0012_unify_documents.py 참고).
