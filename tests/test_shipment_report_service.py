import unittest
from decimal import Decimal

from app.reports.shipment import ShipmentReportRequest, ShipmentReportService


def request_data() -> dict:
    return {
        "report_date": "2026-08-14",
        "customer": {"code": "CUST-001", "name": "두정테크"},
        "delivery_location": "아산공장",
        "plans": [
            {"plan_id": "P-1", "item_code": "A-1001", "item_name": "브래킷", "unit": "EA", "planned_qty": 1000},
            {"plan_id": "P-2", "item_code": "A-1002", "item_name": "커버", "unit": "EA", "planned_qty": 800},
        ],
        "actuals": [
            {"shipment_id": "S-1", "item_code": "A-1001", "item_name": "브래킷", "unit": "EA", "shipped_qty": 1000, "lot_no": "L-1"},
            {"shipment_id": "S-2", "item_code": "A-1002", "item_name": "커버", "unit": "EA", "shipped_qty": 750, "unshipped_reason": "차량 지연"},
        ],
    }


class ShipmentReportServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ShipmentReportService()

    def test_generates_ready_report_from_direct_json_data(self) -> None:
        result = self.service.generate(ShipmentReportRequest.model_validate(request_data()))

        self.assertEqual(result.status.value, "READY")
        self.assertEqual(result.metrics.total_planned_qty, 1800)
        self.assertEqual(result.metrics.total_shipped_qty, 1750)
        self.assertEqual(result.metrics.achievement_rate, Decimal("97.2"))
        self.assertEqual(result.metrics.partial_item_count, 1)
        self.assertEqual(len(result.details), 2)

    def test_missing_unshipped_reason_adds_warning(self) -> None:
        data = request_data()
        del data["actuals"][1]["unshipped_reason"]
        result = self.service.generate(ShipmentReportRequest.model_validate(data))

        self.assertEqual(result.status.value, "READY_WITH_WARNINGS")
        self.assertIn("미출하 사유", result.warnings[0])

    def test_multiple_actuals_are_aggregated_by_item(self) -> None:
        data = request_data()
        data["actuals"] = [
            {"shipment_id": "S-1", "item_code": "A-1001", "item_name": "브래킷", "unit": "EA", "shipped_qty": 400},
            {"shipment_id": "S-2", "item_code": "A-1001", "item_name": "브래킷", "unit": "EA", "shipped_qty": 600},
            {"shipment_id": "S-3", "item_code": "A-1002", "item_name": "커버", "unit": "EA", "shipped_qty": 800},
        ]
        result = self.service.generate(ShipmentReportRequest.model_validate(data))

        self.assertEqual(result.metrics.total_shipped_qty, 1800)
        self.assertEqual(result.details[0].shipped_qty, 1000)

    def test_mixed_units_return_failed_result_without_calculation(self) -> None:
        data = request_data()
        data["plans"][1]["unit"] = "KG"
        data["actuals"][1]["unit"] = "KG"
        result = self.service.generate(ShipmentReportRequest.model_validate(data))

        self.assertEqual(result.status.value, "FAILED")
        self.assertIsNone(result.metrics)
        self.assertEqual(result.details, [])
        self.assertTrue(any(v.status.value == "FAIL" for v in result.validations))


if __name__ == "__main__":
    unittest.main()
