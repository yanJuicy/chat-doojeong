"""Input and output contracts for the daily shipment report."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ReportStatus(str, Enum):
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    FAILED = "FAILED"


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ShipmentItemStatus(str, Enum):
    NORMAL = "NORMAL"
    PARTIAL = "PARTIAL"
    UNSHIPPED = "UNSHIPPED"
    OVER_SHIPPED = "OVER_SHIPPED"


class Customer(StrictModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ShipmentPlan(StrictModel):
    plan_id: str = Field(min_length=1)
    item_code: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    planned_qty: Decimal = Field(gt=0)


class ShipmentActual(StrictModel):
    shipment_id: str = Field(min_length=1)
    item_code: str = Field(min_length=1)
    item_name: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    shipped_qty: Decimal = Field(gt=0)
    lot_no: str | None = Field(default=None, min_length=1)
    pallet_no: str | None = Field(default=None, min_length=1)
    unshipped_reason: str | None = Field(default=None, min_length=1)


class ShipmentReportRequest(StrictModel):
    report_date: date
    customer: Customer
    delivery_location: str | None = Field(default=None, min_length=1)
    plans: list[ShipmentPlan] = Field(min_length=1)
    actuals: list[ShipmentActual] = Field(default_factory=list)

    @model_validator(mode="after")
    def identifiers_must_be_unique(self) -> "ShipmentReportRequest":
        plan_ids = [row.plan_id for row in self.plans]
        shipment_ids = [row.shipment_id for row in self.actuals]
        if len(plan_ids) != len(set(plan_ids)):
            raise ValueError("plan_id must be unique")
        if len(shipment_ids) != len(set(shipment_ids)):
            raise ValueError("shipment_id must be unique")
        return self


class ValidationResult(StrictModel):
    code: str
    status: ValidationStatus
    message: str


class ShipmentReportLine(StrictModel):
    item_code: str
    item_name: str
    unit: str
    planned_qty: Decimal = Field(ge=0)
    shipped_qty: Decimal = Field(ge=0)
    unshipped_qty: Decimal = Field(ge=0)
    over_shipped_qty: Decimal = Field(ge=0)
    achievement_rate: Decimal = Field(ge=0)
    status: ShipmentItemStatus
    unshipped_reasons: list[str] = Field(default_factory=list)
    lot_numbers: list[str] = Field(default_factory=list)
    pallet_numbers: list[str] = Field(default_factory=list)


class ShipmentReportMetrics(StrictModel):
    unit: str
    total_planned_qty: Decimal = Field(ge=0)
    total_shipped_qty: Decimal = Field(ge=0)
    total_unshipped_qty: Decimal = Field(ge=0)
    total_over_shipped_qty: Decimal = Field(ge=0)
    achievement_rate: Decimal = Field(ge=0)
    normal_item_count: int = Field(ge=0)
    partial_item_count: int = Field(ge=0)
    unshipped_item_count: int = Field(ge=0)
    over_shipped_item_count: int = Field(ge=0)


class ShipmentReportResult(StrictModel):
    report_id: UUID
    report_type: str = "DAILY_SHIPMENT"
    status: ReportStatus
    title: str
    summary: str
    report_date: date
    customer: Customer
    delivery_location: str | None
    metrics: ShipmentReportMetrics | None
    details: list[ShipmentReportLine]
    validations: list[ValidationResult]
    warnings: list[str]
    generated_at: datetime
