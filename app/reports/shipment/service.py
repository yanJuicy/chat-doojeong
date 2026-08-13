"""Shipment report use case orchestration."""

from datetime import datetime, timezone
from uuid import uuid4

from .calculator import calculate_report
from .composer import compose_summary, compose_title
from .models import ReportStatus, ShipmentReportRequest, ShipmentReportResult, ValidationStatus
from .validator import validate_request


class ShipmentReportService:
    def generate(self, request: ShipmentReportRequest) -> ShipmentReportResult:
        validations = validate_request(request)
        common = dict(report_id=uuid4(), report_date=request.report_date, customer=request.customer,
                      delivery_location=request.delivery_location, validations=validations,
                      generated_at=datetime.now(timezone.utc))
        if any(row.status == ValidationStatus.FAIL for row in validations):
            return ShipmentReportResult(**common, status=ReportStatus.FAILED, title=compose_title(request),
                summary="입력 데이터 검증에 실패하여 보고서를 생성하지 못했습니다.",
                metrics=None, details=[], warnings=[])
        metrics, details, warnings = calculate_report(request)
        return ShipmentReportResult(**common,
            status=ReportStatus.READY_WITH_WARNINGS if warnings else ReportStatus.READY,
            title=compose_title(request), summary=compose_summary(metrics), metrics=metrics,
            details=details, warnings=warnings)
