from __future__ import annotations

import unittest

from app.api_models import RunWorkersAcceptedResponse, UploadResponse, ZipUploadItem
from app.core.chunking import Chunk
from app.db.models import ChatLog, Document, DocumentChunk


class LegacyCleanupTests(unittest.TestCase):
    def test_unused_database_fields_are_not_exposed_by_models(self) -> None:
        self.assertNotIn("language", Document.__table__.c)
        self.assertNotIn("category", Document.__table__.c)
        self.assertNotIn("category_similarity", Document.__table__.c)
        self.assertNotIn("precomputed_dense_vector", DocumentChunk.__table__.c)
        self.assertNotIn("question_embedding", ChatLog.__table__.c)

    def test_unused_runtime_and_response_fields_are_removed(self) -> None:
        self.assertNotIn("precomputed_dense_vector", Chunk.model_fields)
        self.assertNotIn("duplicate_of", UploadResponse.model_fields)
        self.assertNotIn("duplicate_similarity", UploadResponse.model_fields)
        self.assertNotIn("duplicate_of", ZipUploadItem.model_fields)
        self.assertEqual(set(RunWorkersAcceptedResponse.model_fields), {"status"})


if __name__ == "__main__":
    unittest.main()
