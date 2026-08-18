"""Standalone FastAPI application for shipment report development."""

from __future__ import annotations

from fastapi import FastAPI

from .shipment_router import create_shipment_report_router
from .weekly_router import create_weekly_report_router


def create_app() -> FastAPI:
    application = FastAPI(
        title="출하보고서 생성 API",
        version="0.2.0",
        description="JSON 입력을 검증·집계하여 일일 출하보고서 JSON과 DOCX를 생성합니다.",
    )
    application.include_router(create_shipment_report_router())
    application.include_router(create_weekly_report_router())

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "report-api",
            "report_type": "DAILY_SHIPMENT",
        }

    return application


app = create_app()
