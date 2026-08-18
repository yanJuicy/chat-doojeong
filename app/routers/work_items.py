"""업무 기록 CRUD와 자연어 업무 초안 추출 API."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request, status

from ..db.models import WorkItemStatus
from ..db.session import async_session_factory
from ..services.work_tracking import (
    NaturalWorkEntryExtractor,
    NaturalWorkEntryRequest,
    NaturalWorkEntryResponse,
    WorkActivityCreate,
    WorkActivityRead,
    WorkEntryExtractionError,
    WorkItemBulkCreate,
    WorkItemCreate,
    WorkItemRead,
    WorkItemUpdate,
)
from ..services.work_tracking.models import WorkItemList
from ..services.work_tracking.repository import WorkItemRepository
from ..services.work_tracking.service import WorkItemDateRangeError, WorkItemNotFoundError, WorkTrackingService


def create_work_item_router(session_factory=async_session_factory, extractor=None) -> APIRouter:  # noqa: ANN001
    router = APIRouter(tags=["work-items"])

    def as_read(item) -> WorkItemRead:  # noqa: ANN001
        return WorkItemRead.model_validate(item)

    @router.post("/api/work-items", response_model=WorkItemRead, status_code=status.HTTP_201_CREATED)
    async def create_work_item(body: WorkItemCreate) -> WorkItemRead:
        async with session_factory() as session:
            service = WorkTrackingService(WorkItemRepository(session))
            return as_read(await service.create(body))

    @router.post("/api/work-items/bulk", response_model=list[WorkItemRead], status_code=status.HTTP_201_CREATED)
    async def create_work_items(body: WorkItemBulkCreate) -> list[WorkItemRead]:
        async with session_factory() as session:
            service = WorkTrackingService(WorkItemRepository(session))
            return [as_read(item) for item in await service.create_many(body)]

    @router.get("/api/work-items", response_model=WorkItemList)
    async def list_work_items(
        item_status: WorkItemStatus | None = Query(default=None, alias="status"),
        due_from: date | None = None,
        due_to: date | None = None,
    ) -> WorkItemList:
        async with session_factory() as session:
            service = WorkTrackingService(WorkItemRepository(session))
            try:
                items = await service.list(status=item_status, due_from=due_from, due_to=due_to)
            except WorkItemDateRangeError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            rows = [as_read(item) for item in items]
            return WorkItemList(items=rows, total=len(rows))

    @router.get("/api/work-items/{item_id}", response_model=WorkItemRead)
    async def get_work_item(item_id: str) -> WorkItemRead:
        async with session_factory() as session:
            service = WorkTrackingService(WorkItemRepository(session))
            try:
                return as_read(await service.get(item_id))
            except WorkItemNotFoundError as exc:
                raise HTTPException(status_code=404, detail="업무를 찾을 수 없습니다.") from exc

    @router.patch("/api/work-items/{item_id}", response_model=WorkItemRead)
    async def update_work_item(item_id: str, body: WorkItemUpdate) -> WorkItemRead:
        async with session_factory() as session:
            service = WorkTrackingService(WorkItemRepository(session))
            try:
                return as_read(await service.update(item_id, body))
            except WorkItemNotFoundError as exc:
                raise HTTPException(status_code=404, detail="업무를 찾을 수 없습니다.") from exc
            except WorkItemDateRangeError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post(
        "/api/work-items/{item_id}/activities",
        response_model=WorkActivityRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_work_activity(item_id: str, body: WorkActivityCreate) -> WorkActivityRead:
        async with session_factory() as session:
            service = WorkTrackingService(WorkItemRepository(session))
            try:
                activity = await service.add_activity(item_id, body)
                return WorkActivityRead.model_validate(activity)
            except WorkItemNotFoundError as exc:
                raise HTTPException(status_code=404, detail="업무를 찾을 수 없습니다.") from exc

    @router.post("/api/work-entries/parse", response_model=NaturalWorkEntryResponse)
    async def parse_work_entry(request: Request, body: NaturalWorkEntryRequest) -> NaturalWorkEntryResponse:
        selected_extractor = extractor or NaturalWorkEntryExtractor(request.app.state.llm_provider)
        try:
            if extractor is not None or not hasattr(request.app.state, "gpu_lock"):
                return await selected_extractor.extract(body)
            async with request.app.state.gpu_lock:
                return await selected_extractor.extract(body)
        except WorkEntryExtractionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="업무 추출용 LLM을 사용할 수 없습니다.") from exc

    return router
