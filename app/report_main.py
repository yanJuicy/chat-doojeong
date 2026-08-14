"""Compatibility entry point; prefer ``app.report_api.app:app``."""

from .report_api.app import app

__all__ = ["app"]
