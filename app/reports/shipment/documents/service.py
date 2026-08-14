"""Application service that calculates and renders a shipment document."""

import re
from dataclasses import dataclass

from ..models import ShipmentReportRequest, ShipmentReportResult
from ..service import ShipmentReportService
from .base import ShipmentDocumentRenderer
from .docx_renderer import ShipmentDocxRenderer
from .mapper import map_shipment_report


@dataclass(frozen=True)
class ShipmentDocument:
    filename: str
    media_type: str
    content: bytes
    report: ShipmentReportResult


class ShipmentDocumentGenerationError(ValueError):
    def __init__(self, report: ShipmentReportResult) -> None:
        super().__init__("검증에 실패한 출하보고서는 문서로 생성할 수 없습니다.")
        self.report = report


class ShipmentDocumentService:
    def __init__(
        self,
        report_service: ShipmentReportService | None = None,
        renderer: ShipmentDocumentRenderer | None = None,
    ) -> None:
        self._report_service = report_service or ShipmentReportService()
        self._renderer = renderer or ShipmentDocxRenderer()

    def generate(self, request: ShipmentReportRequest) -> ShipmentDocument:
        report = self._report_service.generate(request)
        try:
            view = map_shipment_report(report)
        except ValueError as exc:
            raise ShipmentDocumentGenerationError(report) from exc

        customer_code = re.sub(r"[^A-Za-z0-9_-]", "-", request.customer.code).strip("-") or "customer"
        filename = (
            f"shipment-report-{request.report_date.isoformat()}-"
            f"{customer_code}.{self._renderer.extension}"
        )
        return ShipmentDocument(
            filename=filename,
            media_type=self._renderer.media_type,
            content=self._renderer.render(view),
            report=report,
        )
