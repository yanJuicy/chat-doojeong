"""Map calculated shipment results to document-ready display values."""

from decimal import Decimal

from ..models import ReportStatus, ShipmentItemStatus, ShipmentReportResult
from .models import (
    ShipmentDocumentLine,
    ShipmentDocumentMetric,
    ShipmentDocumentValidation,
    ShipmentDocumentView,
)


STATUS_LABELS = {
    ShipmentItemStatus.NORMAL: "정상",
    ShipmentItemStatus.PARTIAL: "부분출하",
    ShipmentItemStatus.UNSHIPPED: "미출하",
    ShipmentItemStatus.OVER_SHIPPED: "초과출하",
}


def _format_number(value: Decimal) -> str:
    if value == value.to_integral_value():
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _format_quantity(value: Decimal, unit: str) -> str:
    return f"{_format_number(value)} {unit}"


def map_shipment_report(result: ShipmentReportResult) -> ShipmentDocumentView:
    if result.status == ReportStatus.FAILED or result.metrics is None:
        raise ValueError("검증에 실패한 출하보고서는 문서로 생성할 수 없습니다.")

    unit = result.metrics.unit
    summary = (
        f"출하계획 {_format_quantity(result.metrics.total_planned_qty, unit)} 중 "
        f"{_format_quantity(result.metrics.total_shipped_qty, unit)}를 출하하여 "
        f"달성률은 {result.metrics.achievement_rate:.1f}%입니다. "
        f"미출하 {_format_quantity(result.metrics.total_unshipped_qty, unit)}, "
        f"초과출하 {_format_quantity(result.metrics.total_over_shipped_qty, unit)}입니다."
    )
    metrics = (
        ShipmentDocumentMetric("계획수량", _format_quantity(result.metrics.total_planned_qty, unit)),
        ShipmentDocumentMetric("출하수량", _format_quantity(result.metrics.total_shipped_qty, unit)),
        ShipmentDocumentMetric("미출하량", _format_quantity(result.metrics.total_unshipped_qty, unit)),
        ShipmentDocumentMetric("초과출하량", _format_quantity(result.metrics.total_over_shipped_qty, unit)),
        ShipmentDocumentMetric("달성률", f"{result.metrics.achievement_rate:.1f}%"),
    )
    details = tuple(
        ShipmentDocumentLine(
            item_code=line.item_code,
            item_name=line.item_name,
            planned_qty=_format_quantity(line.planned_qty, line.unit),
            shipped_qty=_format_quantity(line.shipped_qty, line.unit),
            unshipped_qty=_format_quantity(line.unshipped_qty, line.unit),
            over_shipped_qty=_format_quantity(line.over_shipped_qty, line.unit),
            achievement_rate=f"{line.achievement_rate:.1f}%",
            status=STATUS_LABELS[line.status],
            note=", ".join(line.unshipped_reasons) or "-",
        )
        for line in result.details
    )
    validations = tuple(
        ShipmentDocumentValidation(
            code=validation.code,
            status=validation.status.value,
            message=validation.message,
        )
        for validation in result.validations
    )
    return ShipmentDocumentView(
        report_id=str(result.report_id),
        title=result.title,
        report_date=result.report_date.isoformat(),
        customer_code=result.customer.code,
        customer_name=result.customer.name,
        delivery_location=result.delivery_location or "-",
        summary=summary,
        generated_at=result.generated_at.isoformat(),
        metrics=metrics,
        details=details,
        validations=validations,
        warnings=tuple(result.warnings),
    )
