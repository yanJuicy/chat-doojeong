"""Human-readable shipment report text composition."""

from .models import ShipmentReportMetrics, ShipmentReportRequest


def compose_title(request: ShipmentReportRequest) -> str:
    return f"{request.report_date.isoformat()} {request.customer.name} 출하보고서"


def compose_summary(metrics: ShipmentReportMetrics) -> str:
    return (
        f"출하계획 {metrics.total_planned_qty}{metrics.unit} 중 {metrics.total_shipped_qty}{metrics.unit}를 출하하여 "
        f"달성률은 {metrics.achievement_rate}%입니다. 미출하 {metrics.total_unshipped_qty}{metrics.unit}, "
        f"초과출하 {metrics.total_over_shipped_qty}{metrics.unit}입니다."
    )
