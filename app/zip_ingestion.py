"""중첩 ZIP의 지원 문서를 DB 업로드 대기열에 등록한다."""
from __future__ import annotations

import hashlib
import io
import logging
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import select

from .api_models import ZipUploadItem
from .config import settings
from .db.models import Document, DocumentStatus
from .db.session import async_session_factory

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".jpg", ".jpeg", ".png"}
MAX_DEPTH = 5
MAX_TOTAL_ENTRIES = 500


def fix_zip_entry_name(zip_info: zipfile.ZipInfo) -> str:
    """UTF-8 플래그 없는 Windows ZIP의 한글 이름을 cp949로 복구한다."""
    name = zip_info.filename
    if zip_info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("cp949")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return name


async def process_zip_bytes(
    zip_bytes: bytes,
    upload_dir: Path,
    created: list[ZipUploadItem],
    skipped: list[str],
    depth: int = 0,
    _total_uncompressed_bytes: list[int] | None = None,
) -> None:
    """ZIP과 중첩 ZIP을 순회하며 지원 문서를 중복 확인 후 등록한다."""
    if _total_uncompressed_bytes is None:
        _total_uncompressed_bytes = [0]  # 중첩 zip 재귀 호출 전체에서 공유하는 압축 해제 누적 용량 (zip bomb 방지)
    max_total_bytes = settings.max_zip_total_uncompressed_mb * 1024 * 1024

    if len(created) + len(skipped) >= MAX_TOTAL_ENTRIES:
        return

    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        skipped.append("(손상된 zip 파일)")
        return

    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if len(created) + len(skipped) >= MAX_TOTAL_ENTRIES:
                logger.warning("zip 처리 개수 상한(%d) 도달, 나머지는 건너뜀", MAX_TOTAL_ENTRIES)
                return

            display_name = Path(fix_zip_entry_name(info)).name
            extension = Path(display_name).suffix.lower()

            if _total_uncompressed_bytes[0] + info.file_size > max_total_bytes:
                logger.warning(
                    "zip 압축 해제 총 용량 상한(%dMB) 도달, 나머지는 건너뜀", settings.max_zip_total_uncompressed_mb
                )
                skipped.append(f"{display_name} (압축 해제 총 용량 상한 초과로 건너뜀)")
                return

            file_bytes = archive.read(info)
            _total_uncompressed_bytes[0] += len(file_bytes)

            if extension == ".zip":
                if depth + 1 >= MAX_DEPTH:
                    skipped.append(f"{display_name} (중첩이 너무 깊어 건너뜀)")
                    continue
                await process_zip_bytes(
                    file_bytes, upload_dir, created, skipped, depth=depth + 1,
                    _total_uncompressed_bytes=_total_uncompressed_bytes,
                )
                continue

            if extension not in SUPPORTED_EXTENSIONS:
                skipped.append(display_name)
                continue

            document_id = str(uuid.uuid4())
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            async with async_session_factory() as session:
                existing = await session.execute(select(Document).where(Document.file_hash == file_hash))
                existing_document = existing.scalars().first()
                if existing_document is not None:
                    created.append(
                        ZipUploadItem(
                            document_id=existing_document.id,
                            filename=display_name,
                            is_duplicate=True,
                        )
                    )
                    continue

                saved_path = upload_dir / f"{document_id}_{display_name}"
                saved_path.write_bytes(file_bytes)
                session.add(
                    Document(
                        id=document_id,
                        filename=display_name,
                        file_path=str(saved_path),
                        file_hash=file_hash,
                        status=DocumentStatus.UPLOADED,
                    )
                )
                await session.commit()

            created.append(ZipUploadItem(document_id=document_id, filename=display_name))
