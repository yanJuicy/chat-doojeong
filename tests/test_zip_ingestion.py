from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import zip_ingestion
from app.zip_ingestion import process_zip_bytes


class _SessionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, *args, **kwargs):
        class _Result:
            def scalars(self):
                class _Scalars:
                    def first(self_inner):
                        return None

                return _Scalars()

        return _Result()

    def add(self, *args, **kwargs):
        pass

    async def commit(self):
        pass


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class ZipTotalSizeCapTests(unittest.IsolatedAsyncioTestCase):
    async def test_small_zip_processes_all_entries(self) -> None:
        zip_bytes = _make_zip({"a.txt": b"hello", "b.txt": b"world"})
        created: list = []
        skipped: list = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.object(zip_ingestion, "async_session_factory", return_value=_SessionContext()):
                await process_zip_bytes(zip_bytes, upload_dir=Path(tmp_dir), created=created, skipped=skipped)
        self.assertEqual(len(created), 2)
        self.assertEqual(skipped, [])

    async def test_total_uncompressed_cap_stops_further_entries(self) -> None:
        # 각 파일이 40바이트, 상한을 100바이트로 두면 2개까지만 처리되고 나머지는 건너뛴다.
        entries = {f"file{i}.txt": b"x" * 40 for i in range(5)}
        zip_bytes = _make_zip(entries)
        created: list = []
        skipped: list = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch.object(zip_ingestion.settings, "max_zip_total_uncompressed_mb", 100 / 1024 / 1024),
                patch.object(zip_ingestion, "async_session_factory", return_value=_SessionContext()),
            ):
                await process_zip_bytes(zip_bytes, upload_dir=Path(tmp_dir), created=created, skipped=skipped)
        self.assertLess(len(created), 5)
        self.assertTrue(any("용량 상한" in s for s in skipped))


if __name__ == "__main__":
    unittest.main()
