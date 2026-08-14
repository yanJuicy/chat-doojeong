"""중복 문서 정리 스크립트.

같은 filename으로 여러 번 인덱싱된 Document 중, raw_text 내용까지 완전히 동일한
"진짜 중복"만 찾아서 가장 먼저 인덱싱된 것 하나만 남기고 나머지를 삭제한다.

삭제 순서는 이 프로젝트의 기존 재추출 엔드포인트(app/main.py의 reextract_document)와
동일하게: 청크(document_chunks) 먼저 삭제 -> Document 삭제(DocumentLabel은
relationship(cascade="all, delete-orphan")이라 자동 정리됨) -> Qdrant 벡터 삭제.
이 순서를 지키지 않으면 FK 제약 위반이나 orphan 청크가 생길 수 있다.

기본은 --dry-run: 실제로 아무것도 지우지 않고, 뭘 지울지만 보여준다.

사용법:
    python scripts/dedupe_documents.py                # 미리보기만
    python scripts/dedupe_documents.py --apply         # 실제 삭제
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

# 프로젝트 루트(app/ 패키지가 있는 위치)를 sys.path에 추가.
# "python scripts/dedupe_documents.py"처럼 직접 실행하면 파이썬이 scripts/ 폴더만
# 기본 경로로 잡아서 app.* 임포트를 못 찾는데, 이 두 줄로 그 문제를 해결한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.qdrant_store import QdrantVectorStore
from app.db.models import Document, DocumentChunk
from app.db.session import async_session_factory


async def find_duplicate_groups() -> list[list[Document]]:
    async with async_session_factory() as session:
        result = await session.execute(select(Document))
        docs = list(result.scalars().all())

    # 1차: filename + 본문 길이로 후보 묶기 (완전 무관한 문서끼리 비교하는 걸 방지)
    candidates: dict[tuple[str, int], list[Document]] = defaultdict(list)
    for d in docs:
        if d.raw_text:
            candidates[(d.filename, len(d.raw_text))].append(d)

    # 2차: 후보 안에서 raw_text가 글자 하나까지 완전히 같은 것만 "진짜 중복"으로 확정
    duplicate_groups: list[list[Document]] = []
    for group in candidates.values():
        if len(group) < 2:
            continue
        by_text: dict[str, list[Document]] = defaultdict(list)
        for d in group:
            by_text[d.raw_text].append(d)
        for dupes in by_text.values():
            if len(dupes) >= 2:
                duplicate_groups.append(sorted(dupes, key=lambda x: x.created_at))

    return duplicate_groups


async def delete_document(session, vector_store: QdrantVectorStore, document: Document) -> None:
    chunks_result = await session.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == document.id)
    )
    for chunk in chunks_result.scalars().all():
        await session.delete(chunk)
    await session.delete(document)
    await session.commit()
    await vector_store.delete_by_document_id(document.id)


async def main(apply: bool) -> None:
    duplicate_groups = await find_duplicate_groups()

    if not duplicate_groups:
        print("중복 문서가 없습니다.")
        return

    total_to_delete = 0
    for group in duplicate_groups:
        keep, *remove = group
        total_to_delete += len(remove)
        print(f"\n[{keep.filename}] {len(group)}개 중복 발견")
        print(f"  유지: {keep.id}  (생성: {keep.created_at})")
        for d in remove:
            print(f"  삭제 예정: {d.id}  (생성: {d.created_at})")

    print(f"\n총 {len(duplicate_groups)}개 그룹, {total_to_delete}개 문서 "
          f"{'삭제 완료' if apply else '삭제 예정(-- dry-run, 실제 삭제 없음)'}.")

    if not apply:
        print("실제로 삭제하려면 --apply 옵션을 붙여서 다시 실행하세요.")
        return

    vector_store = QdrantVectorStore()
    async with async_session_factory() as session:
        for group in duplicate_groups:
            _keep, *remove = group
            for d in remove:
                await delete_document(session, vector_store, d)
                print(f"  삭제 완료: {d.id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="실제로 삭제 (기본은 미리보기만)")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
