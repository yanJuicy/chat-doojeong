"""업무 기록 생성·조회·상태 변경 유스케이스."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from ...db.models import WorkActivity, WorkItem, WorkItemStatus
from .models import WorkActivityCreate, WorkItemBulkCreate, WorkItemCreate, WorkItemUpdate
from .repository import WorkItemRepository


class WorkItemNotFoundError(LookupError):
    pass


class WorkItemDateRangeError(ValueError):
    pass


class WorkTrackingService:
    def __init__(self, repository: WorkItemRepository) -> None:
        self._repository = repository

    @staticmethod
    def _completed_at(status: WorkItemStatus, current: datetime | None = None) -> datetime | None:
        if status == WorkItemStatus.COMPLETED:
            return current or datetime.now(timezone.utc)
        return None

    @staticmethod
    def _validate_dates(start_date: date | None, due_date: date | None) -> None:
        if start_date and due_date and due_date < start_date:
            raise WorkItemDateRangeError("due_date must be on or after start_date")

    @staticmethod
    def _status_activity_content(status: WorkItemStatus, result: str | None) -> str:
        if result:
            return result
        labels = {
            WorkItemStatus.PLANNED: "예정",
            WorkItemStatus.IN_PROGRESS: "진행 중",
            WorkItemStatus.COMPLETED: "완료",
            WorkItemStatus.ON_HOLD: "보류",
        }
        return f"상태 변경: {labels[status]}"

    async def create(self, payload: WorkItemCreate) -> WorkItem:
        values = payload.model_dump()
        item = WorkItem(**values, completed_at=self._completed_at(payload.status))
        self._repository.add(item)
        await self._repository.commit()
        created = await self._repository.get(item.id)
        assert created is not None
        return created

    async def create_many(self, payload: WorkItemBulkCreate) -> list[WorkItem]:
        items: list[WorkItem] = []
        try:
            for row in payload.items:
                item = WorkItem(
                    **row.model_dump(),
                    completed_at=self._completed_at(row.status),
                )
                self._repository.add(item)
                items.append(item)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        created: list[WorkItem] = []
        for item in items:
            loaded = await self._repository.get(item.id)
            assert loaded is not None
            created.append(loaded)
        return created

    async def get(self, item_id: str) -> WorkItem:
        item = await self._repository.get(item_id)
        if item is None:
            raise WorkItemNotFoundError(item_id)
        return item

    async def list(
        self,
        *,
        status: WorkItemStatus | None = None,
        due_from: date | None = None,
        due_to: date | None = None,
    ) -> list[WorkItem]:
        self._validate_dates(due_from, due_to)
        return await self._repository.list(status=status, due_from=due_from, due_to=due_to)

    async def update(self, item_id: str, payload: WorkItemUpdate) -> WorkItem:
        item = await self.get(item_id)
        values = payload.model_dump(exclude_unset=True)
        previous_status = item.status
        previous_result = item.result
        prospective_start = values.get("start_date", item.start_date)
        prospective_due = values.get("due_date", item.due_date)
        self._validate_dates(prospective_start, prospective_due)
        for field, value in values.items():
            setattr(item, field, value)
        if "status" in values:
            item.completed_at = self._completed_at(item.status, item.completed_at)
        status_changed = item.status != previous_status
        result_changed = bool(item.result) and item.result != previous_result
        if status_changed or result_changed:
            self._repository.add_activity(
                WorkActivity(
                    work_item_id=item.id,
                    activity_date=datetime.now(ZoneInfo("Asia/Seoul")).date(),
                    content=self._status_activity_content(item.status, item.result),
                    status=item.status,
                )
            )
        await self._repository.commit()
        updated = await self._repository.get(item.id)
        assert updated is not None
        return updated

    async def add_activity(self, item_id: str, payload: WorkActivityCreate) -> WorkActivity:
        item = await self.get(item_id)
        activity = WorkActivity(work_item_id=item.id, **payload.model_dump())
        self._repository.add_activity(activity)
        if payload.status is not None:
            item.status = payload.status
            item.completed_at = self._completed_at(payload.status, item.completed_at)
        await self._repository.flush()
        await self._repository.refresh(activity)
        await self._repository.commit()
        return activity
