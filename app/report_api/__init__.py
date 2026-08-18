"""HTTP adapters for report modules."""

from .shipment_router import create_shipment_report_router
from .weekly_router import create_weekly_report_router

__all__ = ["create_shipment_report_router", "create_weekly_report_router"]
