import unittest
from io import BytesIO

from docx import Document

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.report_api import create_shipment_report_router
from tests.test_shipment_report_service import request_data


class ShipmentReportApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        application = FastAPI()
        application.include_router(create_shipment_report_router())
        cls.client = TestClient(application)

    def test_generate_endpoint_returns_report_json(self) -> None:
        response = self.client.post("/api/reports/shipment/generate", json=request_data())

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["report_type"], "DAILY_SHIPMENT")
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["metrics"]["total_shipped_qty"], "1750")

    def test_invalid_or_unknown_fields_return_422(self) -> None:
        data = request_data()
        data["unexpected"] = True
        response = self.client.post("/api/reports/shipment/generate", json=data)
        self.assertEqual(response.status_code, 422)

    def test_empty_plan_list_returns_422(self) -> None:
        data = request_data()
        data["plans"] = []
        response = self.client.post("/api/reports/shipment/generate", json=data)
        self.assertEqual(response.status_code, 422)

    def test_document_endpoint_returns_downloadable_docx(self) -> None:
        response = self.client.post(
            "/api/reports/shipment/documents",
            json=request_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="shipment-report-2026-08-14-CUST-001.docx"',
        )
        self.assertTrue(response.content.startswith(b"PK"))
        document = Document(BytesIO(response.content))
        self.assertIn(
            "2026-08-14 두정테크 출하보고서",
            "\n".join(paragraph.text for paragraph in document.paragraphs),
        )

    def test_document_endpoint_rejects_business_validation_failure(self) -> None:
        data = request_data()
        data["plans"][1]["unit"] = "KG"
        data["actuals"][1]["unit"] = "KG"
        response = self.client.post(
            "/api/reports/shipment/documents",
            json=data,
        )

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertIn("문서로 생성할 수 없습니다", detail["message"])
        self.assertTrue(any(item["status"] == "FAIL" for item in detail["validations"]))


if __name__ == "__main__":
    unittest.main()
