"""Presentation models used by shipment document renderers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ShipmentDocumentMetric:
    label: str
    value: str


@dataclass(frozen=True)
class ShipmentDocumentLine:
    item_code: str
    item_name: str
    planned_qty: str
    shipped_qty: str
    unshipped_qty: str
    over_shipped_qty: str
    achievement_rate: str
    status: str
    note: str


@dataclass(frozen=True)
class ShipmentDocumentValidation:
    code: str
    status: str
    message: str


@dataclass(frozen=True)
class ShipmentDocumentView:
    report_id: str
    title: str
    report_date: str
    customer_code: str
    customer_name: str
    delivery_location: str
    summary: str
    generated_at: str
    metrics: tuple[ShipmentDocumentMetric, ...]
    details: tuple[ShipmentDocumentLine, ...]
    validations: tuple[ShipmentDocumentValidation, ...]
    warnings: tuple[str, ...]
