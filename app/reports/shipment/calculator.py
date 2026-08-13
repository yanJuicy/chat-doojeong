"""Deterministic shipment aggregation and calculations."""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from .models import ShipmentItemStatus, ShipmentReportLine, ShipmentReportMetrics, ShipmentReportRequest


def _rate(shipped: Decimal, planned: Decimal) -> Decimal:
    if planned == 0:
        return Decimal("0.0")
    return ((shipped / planned) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def calculate_report(request: ShipmentReportRequest) -> tuple[ShipmentReportMetrics, list[ShipmentReportLine], list[str]]:
    plans = defaultdict(lambda: Decimal("0"))
    actuals = defaultdict(lambda: Decimal("0"))
    metadata: dict[str, tuple[str, str]] = {}
    reasons: dict[str, set[str]] = defaultdict(set)
    lots: dict[str, set[str]] = defaultdict(set)
    pallets: dict[str, set[str]] = defaultdict(set)
    for row in request.plans:
        plans[row.item_code] += row.planned_qty
        metadata[row.item_code] = (row.item_name, row.unit)
    for row in request.actuals:
        actuals[row.item_code] += row.shipped_qty
        metadata.setdefault(row.item_code, (row.item_name, row.unit))
        if row.unshipped_reason:
            reasons[row.item_code].add(row.unshipped_reason)
        if row.lot_no:
            lots[row.item_code].add(row.lot_no)
        if row.pallet_no:
            pallets[row.item_code].add(row.pallet_no)

    warnings: list[str] = []
    details: list[ShipmentReportLine] = []
    for item_code in sorted(set(plans) | set(actuals)):
        planned, shipped = plans[item_code], actuals[item_code]
        unshipped = max(planned - shipped, Decimal("0"))
        over = max(shipped - planned, Decimal("0"))
        if over > 0:
            item_status = ShipmentItemStatus.OVER_SHIPPED
            warnings.append(f"{item_code}: 계획 대비 초과 출하되었습니다.")
        elif shipped == 0:
            item_status = ShipmentItemStatus.UNSHIPPED
        elif shipped < planned:
            item_status = ShipmentItemStatus.PARTIAL
        else:
            item_status = ShipmentItemStatus.NORMAL
        if planned == 0:
            warnings.append(f"{item_code}: 출하계획 없이 출하실적이 입력되었습니다.")
        if unshipped > 0 and not reasons[item_code]:
            warnings.append(f"{item_code}: 미출하 사유가 입력되지 않았습니다.")
        item_name, unit = metadata[item_code]
        details.append(ShipmentReportLine(
            item_code=item_code, item_name=item_name, unit=unit,
            planned_qty=planned, shipped_qty=shipped, unshipped_qty=unshipped,
            over_shipped_qty=over, achievement_rate=_rate(shipped, planned), status=item_status,
            unshipped_reasons=sorted(reasons[item_code]), lot_numbers=sorted(lots[item_code]),
            pallet_numbers=sorted(pallets[item_code]),
        ))

    total_planned = sum((row.planned_qty for row in details), Decimal("0"))
    total_shipped = sum((row.shipped_qty for row in details), Decimal("0"))
    metrics = ShipmentReportMetrics(
        unit=request.plans[0].unit,
        total_planned_qty=total_planned, total_shipped_qty=total_shipped,
        total_unshipped_qty=sum((row.unshipped_qty for row in details), Decimal("0")),
        total_over_shipped_qty=sum((row.over_shipped_qty for row in details), Decimal("0")),
        achievement_rate=_rate(total_shipped, total_planned),
        normal_item_count=sum(row.status == ShipmentItemStatus.NORMAL for row in details),
        partial_item_count=sum(row.status == ShipmentItemStatus.PARTIAL for row in details),
        unshipped_item_count=sum(row.status == ShipmentItemStatus.UNSHIPPED for row in details),
        over_shipped_item_count=sum(row.status == ShipmentItemStatus.OVER_SHIPPED for row in details),
    )
    return metrics, details, warnings
