"""Renderer contract for shipment report documents."""

from typing import Protocol

from .models import ShipmentDocumentView


class ShipmentDocumentRenderer(Protocol):
    media_type: str
    extension: str

    def render(self, view: ShipmentDocumentView) -> bytes:
        """Render a document from a presentation model."""
