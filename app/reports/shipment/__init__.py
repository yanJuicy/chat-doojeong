"""Shipment report domain module."""

from .models import ShipmentReportRequest, ShipmentReportResult
from .service import ShipmentReportService

__all__ = ["ShipmentReportRequest", "ShipmentReportResult", "ShipmentReportService"]
