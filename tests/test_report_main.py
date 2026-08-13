import unittest

from fastapi.testclient import TestClient

from app.report_main import app
from tests.test_shipment_report_service import request_data


class ReportOnlyAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_health_identifies_shipment_report_api(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok", "service": "report-api", "report_type": "DAILY_SHIPMENT"
        })

    def test_exposes_shipment_generation_endpoint(self) -> None:
        response = self.client.post("/api/reports/shipment/generate", json=request_data())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report_type"], "DAILY_SHIPMENT")


if __name__ == "__main__":
    unittest.main()
