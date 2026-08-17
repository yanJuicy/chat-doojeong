"""Daily report use case orchestration. (app/reports/shipment/service.py와 동일한 구조)"""
from __future__ import annotations

from .composer import compose_body, compose_title
from .models import DailyReportRequest, DailyReportResult, ValidationStatus
from .validator import validate_request


class DailyReportService:
    def generate(self, request: DailyReportRequest) -> DailyReportResult:
        issues = validate_request(request)
        if issues:
            return DailyReportResult(status=ValidationStatus.FAILED, issues=issues)

        return DailyReportResult(
            status=ValidationStatus.OK,
            title=compose_title(request),
            body_markdown=compose_body(request),
        )
