"""HTTP adapter for the shipment report module."""

from fastapi import APIRouter

from ..reports.shipment import ShipmentReportRequest, ShipmentReportResult, ShipmentReportService


def create_shipment_report_router(service: ShipmentReportService | None = None) -> APIRouter:
    report_service = service or ShipmentReportService()
    router = APIRouter(prefix="/api/reports/shipment", tags=["reports"])

    @router.post("/generate", response_model=ShipmentReportResult)
    async def generate_shipment_report(body: ShipmentReportRequest) -> ShipmentReportResult:
        return report_service.generate(body)

    return router
