"""주간보고서 DOCX 생성 결과와 오류."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WeeklyDocument:
    report_id: str
    content: bytes
    filename: str
    media_type: str
    file_path: Path


class WeeklyTemplateNotFoundError(LookupError):
    pass


class WeeklyDocumentGenerationError(RuntimeError):
    pass
