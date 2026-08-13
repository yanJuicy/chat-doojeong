import unittest

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


if __name__ == "__main__":
    unittest.main()
