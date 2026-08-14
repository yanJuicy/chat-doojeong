"""Document generation layer for shipment reports."""

from .docx_renderer import ShipmentDocxRenderer
from .service import (
    ShipmentDocument,
    ShipmentDocumentGenerationError,
    ShipmentDocumentService,
)

__all__ = [
    "ShipmentDocument",
    "ShipmentDocumentGenerationError",
    "ShipmentDocumentService",
    "ShipmentDocxRenderer",
]
