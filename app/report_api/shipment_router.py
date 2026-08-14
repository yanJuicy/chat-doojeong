"""HTTP adapter for the shipment report module."""

from fastapi import APIRouter, HTTPException, Response, status
from starlette.concurrency import run_in_threadpool

from ..reports.shipment import ShipmentReportRequest, ShipmentReportResult, ShipmentReportService
from ..reports.shipment.documents import (
    ShipmentDocumentGenerationError,
    ShipmentDocumentService,
)


def create_shipment_report_router(
    service: ShipmentReportService | None = None,
    document_service: ShipmentDocumentService | None = None,
) -> APIRouter:
    report_service = service or ShipmentReportService()
    report_document_service = document_service or ShipmentDocumentService(report_service)
    router = APIRouter(prefix="/api/reports/shipment", tags=["reports"])

    @router.post("/generate", response_model=ShipmentReportResult)
    async def generate_shipment_report(body: ShipmentReportRequest) -> ShipmentReportResult:
        return report_service.generate(body)

    @router.post(
        "/documents",
        response_class=Response,
        responses={
            200: {
                "content": {
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}
                },
                "description": "Generated DOCX shipment report",
            },
            422: {"description": "Shipment data failed business validation"},
        },
    )
    async def generate_shipment_document(body: ShipmentReportRequest) -> Response:
        try:
            document = await run_in_threadpool(report_document_service.generate, body)
        except ShipmentDocumentGenerationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "message": str(exc),
                    "validations": [
                        validation.model_dump(mode="json")
                        for validation in exc.report.validations
                    ],
                },
            ) from exc
        return Response(
            content=document.content,
            media_type=document.media_type,
            headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
        )

    return router
