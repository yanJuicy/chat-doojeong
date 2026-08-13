"""Business validation for shipment report input."""

from collections import defaultdict

from .models import ShipmentReportRequest, ValidationResult, ValidationStatus


def validate_request(request: ShipmentReportRequest) -> list[ValidationResult]:
    units = {row.unit for row in [*request.plans, *request.actuals]}
    results = [ValidationResult(
        code="SINGLE_UNIT",
        status=ValidationStatus.PASS if len(units) == 1 else ValidationStatus.FAIL,
        message="모든 수량의 단위가 일치합니다." if len(units) == 1 else "서로 다른 수량 단위가 포함되어 있습니다.",
    )]
    metadata: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in [*request.plans, *request.actuals]:
        metadata[row.item_code].add((row.item_name, row.unit))
    inconsistent = sorted(code for code, values in metadata.items() if len(values) > 1)
    results.append(ValidationResult(
        code="ITEM_METADATA",
        status=ValidationStatus.FAIL if inconsistent else ValidationStatus.PASS,
        message=f"품목 정보가 일치하지 않습니다: {', '.join(inconsistent)}" if inconsistent else "동일 품목 코드의 품목명과 단위가 일치합니다.",
    ))
    return results
